"""Flask application for the auto_break_player project."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from config import load_config
from models import (
    Base,
    Command,
    Playlist,
    PlaylistTrack,
    Schedule,
    State,
    Track,
    ensure_state_row,
    log,
    make_engine,
    make_session_factory,
)
from sqlalchemy import func, select

try:  # pragma: no cover - optional dependency
    from mutagen import File as MutagenFile
except Exception:  # pragma: no cover - executed when mutagen missing
    MutagenFile = None

# ---------------------------------------------------------------------------
config = load_config()
app = Flask(__name__)
app.config["SECRET_KEY"] = config["secret_key"]
app.config["UPLOAD_FOLDER"] = str(Path(config["music_dir"]).absolute())
app.config["MAX_CONTENT_LENGTH"] = int(config.get("max_upload_mb", 50)) * 1024 * 1024
app.config["ALLOWED_EXTENSIONS"] = set(config.get("allowed_extensions", [".mp3", ".wav"]))

Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
Path(config["logs_dir"]).mkdir(parents=True, exist_ok=True)

_CORS_METHODS = "GET,POST,DELETE,OPTIONS"
_CORS_HEADERS = "Content-Type"
_CORS_ORIGINS = tuple(config.get("cors_origins", ["*"]))

engine = make_engine(config["db_path"])
Base.metadata.create_all(engine)
SessionLocal = make_session_factory(engine)

# ----------------------------------------------------------------------------

def get_session():
    from flask import g

    if "db" not in g:
        g.db = SessionLocal()
    return g.db


@app.teardown_appcontext
def shutdown_session(exception=None):  # pragma: no cover - cleanup
    from flask import g

    session = g.pop("db", None)
    if session is not None:
        session.close()


# ----------------------------------------------------------------------------


@app.before_request
def _handle_cors_preflight():
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        return _apply_cors_headers(response)


def _apply_cors_headers(response: Response) -> Response:
    origin = request.headers.get("Origin") or ""
    allow_all = "*" in _CORS_ORIGINS
    if allow_all:
        response.headers["Access-Control-Allow-Origin"] = "*"
    elif origin in _CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        existing_vary = response.headers.get("Vary")
        if existing_vary:
            if "Origin" not in {item.strip() for item in existing_vary.split(",")}:
                response.headers["Vary"] = f"{existing_vary}, Origin"
        else:
            response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Headers"] = _CORS_HEADERS
    response.headers["Access-Control-Allow-Methods"] = _CORS_METHODS
    return response


@app.after_request
def _add_cors_headers(response: Response) -> Response:
    return _apply_cors_headers(response)


# ----------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in app.config["ALLOWED_EXTENSIONS"]


def _store_track_file(file: FileStorage, session) -> Track:
    filename = file.filename or ""
    if filename == "":
        raise ValueError("File name is required")
    if not allowed_file(filename):
        raise ValueError(f"File '{filename}' has an invalid extension.")
    stored_name = f"{uuid4().hex}{Path(filename).suffix.lower()}"
    secure_name = secure_filename(stored_name)
    target_path = Path(app.config["UPLOAD_FOLDER"]) / secure_name
    file.save(target_path)
    duration = None
    if MutagenFile is not None:
        try:
            audio = MutagenFile(target_path)
            if audio and audio.info:
                duration = int(audio.info.length)
        except Exception:
            duration = None
    track = Track(
        orig_filename=secure_filename(filename),
        stored_filename=secure_name,
        content_type=file.mimetype or "audio/mpeg",
        duration_sec=duration,
    )
    session.add(track)
    session.commit()
    log(session, "info", "File uploaded", {"track_id": track.id, "filename": track.orig_filename})
    return track


def get_data() -> Dict[str, object]:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict(flat=True)
    return {}


def to_int(value, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def enqueue_command(session, type_: str, payload: Optional[Dict[str, object]] = None) -> None:
    command = Command(type=type_, payload=json.dumps(payload or {}))
    session.add(command)
    session.commit()


def _normalize_days(days: Iterable[object]) -> List[str]:
    normalized = []
    for day in days:
        if day is None:
            continue
        value = str(day).strip()
        if value == "":
            continue
        if value not in {"0", "1", "2", "3", "4", "5", "6"}:
            raise ValueError("Day values must be between 0 (Monday) and 6 (Sunday)")
        normalized.append(value)
    if not normalized:
        return ["1", "2", "3", "4", "5"]  # default to school days Mon-Fri
    # remove duplicates while preserving order
    seen: set[str] = set()
    unique: List[str] = []
    for value in normalized:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _parse_start_times(raw_times: Iterable[object]) -> List[str]:
    parsed: List[str] = []
    for item in raw_times:
        if item is None:
            continue
        value = str(item).strip()
        if not value:
            continue
        try:
            dt.datetime.strptime(value, "%H:%M")
        except ValueError as exc:  # pragma: no cover - validated by caller tests
            raise ValueError(f"Invalid time format '{value}', expected HH:MM") from exc
        if value not in parsed:
            parsed.append(value)
    if not parsed:
        raise ValueError("At least one start time is required")
    return parsed


def apply_break_plan(
    session,
    playlist_id: int,
    *,
    start_times: Iterable[object],
    days: Iterable[object] | None = None,
    minutes: int | None = None,
    name_prefix: str | None = None,
    replace: bool = False,
):
    playlist = session.get(Playlist, playlist_id)
    if not playlist:
        raise ValueError("Playlist not found")
    times = _parse_start_times(start_times)
    normalized_days = _normalize_days(days or [])
    minutes_value = max(1, minutes or int(config.get("session_default_minutes", 15)))
    prefix = (name_prefix or "School Break").strip() or "School Break"
    created: List[int] = []
    updated: List[int] = []

    day_csv = ",".join(normalized_days)
    for start in times:
        schedule = session.scalar(
            select(Schedule).where(
                Schedule.playlist_id == playlist_id,
                Schedule.start_time == start,
            )
        )
        if schedule:
            schedule.name = f"{prefix} {start}"
            schedule.days = day_csv
            schedule.session_minutes = minutes_value
            schedule.enabled = True
            updated.append(schedule.id)
        else:
            schedule = Schedule(
                name=f"{prefix} {start}",
                playlist_id=playlist_id,
                days=day_csv,
                start_time=start,
                session_minutes=minutes_value,
                enabled=True,
            )
            session.add(schedule)
            session.flush()
            created.append(schedule.id)

    disabled: List[int] = []
    if replace:
        keep_ids = set(created + updated)
        stmt = select(Schedule).where(
            Schedule.playlist_id == playlist_id,
            Schedule.name.like(f"{prefix}%"),
        )
        if keep_ids:
            stmt = stmt.where(~Schedule.id.in_(list(keep_ids)))
        for schedule in session.scalars(stmt).all():
            if schedule.enabled:
                schedule.enabled = False
                disabled.append(schedule.id)

    session.commit()
    log(
        session,
        "info",
        "Break plan applied",
        {
            "playlist_id": playlist_id,
            "created": created,
            "updated": updated,
            "disabled": disabled,
            "start_times": times,
        },
    )
    return {
        "created": created,
        "updated": updated,
        "disabled": disabled,
        "days": day_csv,
        "minutes": minutes_value,
        "prefix": prefix,
    }


# ----------------------------------------------------------------------------
@app.before_request
def ensure_state():  # pragma: no cover - trivial
    session = get_session()
    ensure_state_row(session)


@app.route("/")
def index() -> str:
    session = get_session()
    playlists = session.scalars(select(Playlist)).all()
    state = ensure_state_row(session)
    current_playlist = session.get(Playlist, state.playlist_id) if state.playlist_id else None
    current_track = session.get(Track, state.current_track_id) if state.current_track_id else None
    schedules = session.scalars(select(Schedule)).all()
    return render_template(
        "index.html",
        config=config,
        playlists=playlists,
        state=state,
        current_playlist=current_playlist,
        current_track=current_track,
        schedules=schedules,
    )


@app.route("/upload", methods=["GET", "POST"])
def upload() -> str | Response:
    session = get_session()
    if request.method == "POST":
        files: Iterable[FileStorage] = request.files.getlist("files") or []
        saved = 0
        for file in files:
            try:
                _store_track_file(file, session)
            except ValueError as exc:
                flash(str(exc), "error")
                continue
            saved += 1
        if saved:
            flash(f"Uploaded {saved} file(s).", "success")
        else:
            flash("No files uploaded.", "warning")
        return redirect(url_for("upload"))
    tracks = session.scalars(select(Track)).all()
    return render_template("tracks.html", tracks=tracks, config=config)


@app.route("/tracks/<int:track_id>/delete", methods=["POST"])
def delete_track(track_id: int) -> Response:
    session = get_session()
    track = session.get(Track, track_id)
    if not track:
        flash("Track not found.", "error")
        return redirect(url_for("upload"))
    in_use = session.scalar(select(PlaylistTrack).where(PlaylistTrack.track_id == track_id).limit(1))
    if in_use:
        flash("Track is referenced by a playlist and cannot be deleted.", "error")
        return redirect(url_for("upload"))
    file_path = Path(app.config["UPLOAD_FOLDER"]) / track.stored_filename
    if file_path.exists():
        file_path.unlink()
    session.delete(track)
    session.commit()
    log(session, "info", "Track deleted", {"track_id": track_id})
    flash("Track deleted.", "success")
    return redirect(url_for("upload"))


@app.route("/playlists", methods=["GET", "POST"])
def playlists() -> str | Response:
    session = get_session()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Playlist name is required.", "error")
        else:
            playlist = Playlist(name=name)
            session.add(playlist)
            session.commit()
            log(session, "info", "Playlist created", {"playlist_id": playlist.id})
            flash("Playlist created.", "success")
        return redirect(url_for("playlists"))
    playlists = session.scalars(select(Playlist)).all()
    tracks = session.scalars(select(Track)).all()
    return render_template("playlists.html", playlists=playlists, tracks=tracks, active_playlist=None, entries=[])


@app.route("/playlists/<int:playlist_id>", methods=["GET", "POST"])
def edit_playlist(playlist_id: int) -> str | Response:
    session = get_session()
    playlist = session.get(Playlist, playlist_id)
    if not playlist:
        flash("Playlist not found.", "error")
        return redirect(url_for("playlists"))
    if request.method == "POST":
        track_id = to_int(request.form.get("track_id"))
        position = to_int(request.form.get("position"), 0) or 0
        if track_id is None:
            flash("Track selection required.", "error")
        else:
            entry = PlaylistTrack(playlist_id=playlist_id, track_id=track_id, position=position)
            session.add(entry)
            session.commit()
            log(session, "info", "Track added to playlist", {"playlist_id": playlist_id, "track_id": track_id})
            flash("Track added.", "success")
        return redirect(url_for("edit_playlist", playlist_id=playlist_id))
    entries = session.scalars(
        select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id).order_by(PlaylistTrack.position)
    ).all()
    playlists = session.scalars(select(Playlist)).all()
    tracks = session.scalars(select(Track)).all()
    return render_template(
        "playlists.html",
        playlists=playlists,
        tracks=tracks,
        active_playlist=playlist,
        entries=entries,
    )


@app.route("/playlists/<int:playlist_id>/remove/<int:entry_id>", methods=["POST"])
def remove_playlist_entry(playlist_id: int, entry_id: int) -> Response:
    session = get_session()
    entry = session.get(PlaylistTrack, entry_id)
    if entry:
        session.delete(entry)
        session.commit()
        log(session, "info", "Track removed from playlist", {"playlist_id": playlist_id, "entry_id": entry_id})
        flash("Entry removed.", "success")
    return redirect(url_for("edit_playlist", playlist_id=playlist_id))


@app.route("/schedules", methods=["GET", "POST"])
def schedules_view() -> str | Response:
    session = get_session()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        playlist_id = to_int(request.form.get("playlist_id"))
        days = request.form.getlist("days")
        start_time = request.form.get("start_time") or "00:00"
        minutes = to_int(request.form.get("session_minutes"), config.get("session_default_minutes", 15))
        enabled = bool(request.form.get("enabled"))
        schedule = Schedule(
            name=name or "Session",
            playlist_id=playlist_id,
            days=",".join(days) if days else "0,1,2,3,4,5,6",
            start_time=start_time,
            session_minutes=minutes or config.get("session_default_minutes", 15),
            enabled=enabled,
        )
        session.add(schedule)
        session.commit()
        log(session, "info", "Schedule created", {"schedule_id": schedule.id})
        flash("Schedule saved.", "success")
        return redirect(url_for("schedules_view"))
    playlists = session.scalars(select(Playlist)).all()
    schedules = session.scalars(select(Schedule)).all()
    return render_template("schedules.html", playlists=playlists, schedules=schedules, config=config)


@app.route("/schedules/break-plan", methods=["POST"])
def schedules_break_plan() -> Response:
    session = get_session()
    playlist_id = to_int(request.form.get("playlist_id"))
    if playlist_id is None:
        flash("Cần chọn playlist cho kế hoạch giờ ra chơi.", "error")
        return redirect(url_for("schedules_view"))
    minutes = to_int(request.form.get("session_minutes"), config.get("session_default_minutes", 15))
    days = request.form.getlist("days")
    start_times_raw = request.form.get("start_times", "")
    prefix = (request.form.get("name_prefix") or "").strip()
    replace = bool(request.form.get("replace"))
    try:
        result = apply_break_plan(
            session,
            int(playlist_id),
            start_times=start_times_raw.replace("\n", ",").split(","),
            days=days,
            minutes=minutes,
            name_prefix=prefix,
            replace=replace,
        )
        flash(
            f"Kế hoạch giờ ra chơi đã cập nhật: {len(result['created'])} mới, {len(result['updated'])} cập nhật.",
            "success",
        )
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("schedules_view"))


@app.route("/schedules/<int:schedule_id>/toggle", methods=["POST"])
def toggle_schedule(schedule_id: int) -> Response:
    session = get_session()
    schedule = session.get(Schedule, schedule_id)
    if schedule:
        schedule.enabled = not schedule.enabled
        session.commit()
        log(session, "info", "Schedule toggled", {"schedule_id": schedule_id, "enabled": schedule.enabled})
    return redirect(url_for("schedules_view"))


# ----------------------------------------------------------------------------
# REST API


@app.route("/api/playlists", methods=["GET", "POST"])
def api_playlists() -> Response:
    session = get_session()
    if request.method == "POST":
        data = get_data()
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name required"}), 400
        playlist = Playlist(name=name)
        session.add(playlist)
        session.commit()
        log(session, "info", "Playlist created", {"playlist_id": playlist.id})
        return jsonify({"id": playlist.id, "name": playlist.name}), 201
    playlists = session.scalars(select(Playlist)).all()
    return jsonify([{"id": p.id, "name": p.name} for p in playlists])


@app.route("/api/tracks", methods=["GET", "POST"])
def api_tracks() -> Response:
    session = get_session()
    if request.method == "POST":
        files: Iterable[FileStorage] = request.files.getlist("files") or []
        if not files:
            return jsonify({"error": "files required"}), 400
        uploaded = []
        errors: list[str] = []
        for file in files:
            try:
                track = _store_track_file(file, session)
                uploaded.append(
                    {
                        "id": track.id,
                        "name": track.orig_filename,
                        "duration": track.duration_sec,
                        "preview_url": url_for(
                            "serve_music", filename=track.stored_filename, _external=True
                        ),
                    }
                )
            except ValueError as exc:
                errors.append(str(exc))
        status_code = 201 if uploaded else 400
        payload: Dict[str, object] = {"uploaded": uploaded}
        if errors:
            payload["errors"] = errors
        return jsonify(payload), status_code
    tracks = session.scalars(select(Track)).all()
    return jsonify(
        [
            {
                "id": track.id,
                "name": track.orig_filename,
                "duration": track.duration_sec,
                "preview_url": url_for("serve_music", filename=track.stored_filename, _external=True),
            }
            for track in tracks
        ]
    )


@app.route("/api/tracks/<int:track_id>", methods=["DELETE"])
def api_delete_track(track_id: int) -> Response:
    session = get_session()
    track = session.get(Track, track_id)
    if not track:
        return jsonify({"error": "Track not found"}), 404
    in_use = session.scalar(select(PlaylistTrack).where(PlaylistTrack.track_id == track_id).limit(1))
    if in_use:
        return jsonify({"error": "Track is referenced by a playlist"}), 400
    file_path = Path(app.config["UPLOAD_FOLDER"]) / track.stored_filename
    if file_path.exists():
        file_path.unlink()
    session.delete(track)
    session.commit()
    log(session, "info", "Track deleted", {"track_id": track_id})
    return jsonify({"status": "deleted"})


def _playlist_track_count(session, playlist_id: int) -> int:
    return session.scalar(
        select(func.count()).select_from(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
    ) or 0


def _serialize_playlist_entry(entry: PlaylistTrack) -> Dict[str, object]:
    track = entry.track  # type: ignore[attr-defined]
    return {
        "entry_id": entry.id,
        "track_id": entry.track_id,
        "position": entry.position,
        "track_name": track.orig_filename if track else None,
        "duration": track.duration_sec if track else None,
    }


@app.route("/api/play", methods=["POST"])
def api_play() -> Response:
    session = get_session()
    data = get_data()
    playlist_id = data.get("playlist_id")
    if playlist_id is not None:
        playlist_id = to_int(playlist_id)
    else:
        playlists = session.scalars(select(Playlist.id)).all()
        if len(playlists) == 1:
            playlist_id = playlists[0]
    if playlist_id is None:
        return jsonify({"error": "playlist_id required"}), 400
    if _playlist_track_count(session, playlist_id) == 0:
        return jsonify({"error": "Playlist trống"}), 400
    minutes = to_int(data.get("minutes"), config.get("session_default_minutes", 15)) or config.get(
        "session_default_minutes", 15
    )
    enqueue_command(session, "PLAY", {"playlist_id": playlist_id, "minutes": minutes})
    log(session, "info", "Play command queued", {"playlist_id": playlist_id, "minutes": minutes})
    return jsonify({"status": "queued"})


@app.route("/api/stop", methods=["POST"])
def api_stop() -> Response:
    session = get_session()
    enqueue_command(session, "STOP")
    log(session, "info", "Stop command queued")
    return jsonify({"status": "queued"})


@app.route("/api/skip", methods=["POST"])
def api_skip() -> Response:
    session = get_session()
    enqueue_command(session, "SKIP")
    log(session, "info", "Skip command queued")
    return jsonify({"status": "queued"})


@app.route("/api/volume", methods=["POST"])
def api_volume() -> Response:
    session = get_session()
    data = get_data()
    volume = to_int(data.get("volume"), ensure_state_row(session).volume) or ensure_state_row(session).volume
    volume = max(0, min(100, volume))
    state = ensure_state_row(session)
    state.volume = volume
    session.commit()
    enqueue_command(session, "SET_VOLUME", {"volume": volume})
    log(session, "info", "Volume command queued", {"volume": volume})
    return jsonify({"status": "queued", "volume": volume})


@app.route("/api/power", methods=["POST"])
def api_power() -> Response:
    session = get_session()
    data = get_data()
    raw = data.get("on")
    if isinstance(raw, str):
        desired = raw.lower() in {"1", "true", "yes", "on"}
    else:
        desired = bool(raw)
    state = ensure_state_row(session)
    state.power_on = desired
    session.commit()
    enqueue_command(session, "POWER_ON" if desired else "POWER_OFF")
    log(session, "info", "Power command queued", {"power_on": desired})
    return jsonify({"status": "queued", "power_on": desired})


@app.route("/api/preview", methods=["POST"])
def api_preview() -> Response:
    session = get_session()
    data = get_data()
    track_id = to_int(data.get("track_id")) if data else None
    if track_id is None:
        return jsonify({"error": "track_id required"}), 400
    track = session.get(Track, track_id)
    if not track:
        return jsonify({"error": "Track not found"}), 404
    enqueue_command(session, "PREVIEW", {"track_id": track_id})
    log(session, "info", "Preview command queued", {"track_id": track_id})
    return jsonify({"status": "queued"})


@app.route("/api/schedules", methods=["GET", "POST"])
def api_schedules() -> Response:
    session = get_session()
    if request.method == "POST":
        data = get_data()
        name = (data.get("name") or "Session").strip() or "Session"
        playlist_id = to_int(data.get("playlist_id")) if data else None
        days_value = data.get("days") if isinstance(data, dict) else None
        if isinstance(days_value, str):
            days = [item.strip() for item in days_value.split(",") if item.strip()]
        elif isinstance(days_value, list):
            days = [str(item) for item in days_value]
        else:
            days = []
        start_time = (data.get("start_time") or "00:00") if isinstance(data, dict) else "00:00"
        minutes = to_int(data.get("session_minutes"), config.get("session_default_minutes", 15)) or config.get(
            "session_default_minutes", 15
        )
        enabled = data.get("enabled")
        enabled_value = bool(enabled) if enabled is not None else True
        schedule = Schedule(
            name=name,
            playlist_id=playlist_id,
            days=",".join(days) if days else "0,1,2,3,4,5,6",
            start_time=start_time,
            session_minutes=minutes,
            enabled=enabled_value,
        )
        session.add(schedule)
        session.commit()
        log(session, "info", "Schedule created", {"schedule_id": schedule.id})
        return jsonify(
            {
                "id": schedule.id,
                "name": schedule.name,
                "playlist_id": schedule.playlist_id,
                "days": schedule.days,
                "start_time": schedule.start_time,
                "session_minutes": schedule.session_minutes,
                "enabled": schedule.enabled,
            }
        ), 201
    schedules = session.scalars(select(Schedule)).all()
    return jsonify(
        [
            {
                "id": schedule.id,
                "name": schedule.name,
                "playlist_id": schedule.playlist_id,
                "days": schedule.days,
                "start_time": schedule.start_time,
                "session_minutes": schedule.session_minutes,
                "enabled": schedule.enabled,
            }
            for schedule in schedules
        ]
    )


@app.route("/api/schedules/break-plan", methods=["POST"])
def api_break_plan() -> Response:
    session = get_session()
    data = get_data()
    if not isinstance(data, dict):
        return jsonify({"error": "invalid payload"}), 400
    playlist_id = to_int(data.get("playlist_id"))
    if playlist_id is None:
        return jsonify({"error": "playlist_id required"}), 400
    start_times_value = data.get("start_times")
    if isinstance(start_times_value, str):
        raw_times = start_times_value.replace("\n", ",").split(",")
    elif isinstance(start_times_value, list):
        raw_times = start_times_value
    else:
        raw_times = []
    days_value = data.get("days")
    if isinstance(days_value, str):
        days = [item.strip() for item in days_value.split(",") if item.strip()]
    elif isinstance(days_value, list):
        days = days_value
    else:
        days = []
    minutes = to_int(data.get("session_minutes"), config.get("session_default_minutes", 15))
    prefix = data.get("name_prefix")
    replace = bool(data.get("replace"))
    try:
        result = apply_break_plan(
            session,
            int(playlist_id),
            start_times=raw_times,
            days=days,
            minutes=minutes,
            name_prefix=prefix,
            replace=replace,
        )
    except ValueError as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 400
    return (
        jsonify(
            {
                "status": "ok",
                "created": result["created"],
                "updated": result["updated"],
                "disabled": result["disabled"],
                "days": result["days"],
                "session_minutes": result["minutes"],
                "name_prefix": result["prefix"],
            }
        ),
        201,
    )


@app.route("/api/schedules/<int:schedule_id>/toggle", methods=["POST"])
def api_toggle_schedule(schedule_id: int) -> Response:
    session = get_session()
    schedule = session.get(Schedule, schedule_id)
    if not schedule:
        return jsonify({"error": "Schedule not found"}), 404
    data = get_data()
    if data and "enabled" in data:
        desired = bool(data.get("enabled"))
        schedule.enabled = desired
    else:
        schedule.enabled = not schedule.enabled
    session.commit()
    log(session, "info", "Schedule toggled", {"schedule_id": schedule_id, "enabled": schedule.enabled})
    return jsonify({"id": schedule.id, "enabled": schedule.enabled})


@app.route("/api/status")
def api_status() -> Response:
    session = get_session()
    state = ensure_state_row(session)
    payload = {
        "status": state.status,
        "volume": state.volume,
        "session_end_at": state.session_end_at.isoformat() if state.session_end_at else None,
        "power_on": state.power_on,
        "playlist_id": state.playlist_id,
        "current_track_id": state.current_track_id,
        "heartbeat_at": state.heartbeat_at.isoformat() if state.heartbeat_at else None,
    }
    return jsonify(payload)


@app.route("/api/playlists/<int:playlist_id>")
def api_playlist_detail(playlist_id: int) -> Response:
    session = get_session()
    playlist = session.get(Playlist, playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404
    entries = session.scalars(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    ).all()
    # Ensure track relationship is loaded
    for entry in entries:
        _ = entry.track
    return jsonify(
        {
            "id": playlist.id,
            "name": playlist.name,
            "tracks": [_serialize_playlist_entry(entry) for entry in entries],
        }
    )


@app.route("/api/playlists/<int:playlist_id>/tracks", methods=["POST"])
def api_playlist_add_track(playlist_id: int) -> Response:
    session = get_session()
    playlist = session.get(Playlist, playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404
    data = get_data()
    track_id = to_int(data.get("track_id")) if data else None
    if track_id is None:
        return jsonify({"error": "track_id required"}), 400
    track = session.get(Track, track_id)
    if not track:
        return jsonify({"error": "Track not found"}), 404
    position = to_int(data.get("position"), None)
    if position is None:
        position = _playlist_track_count(session, playlist_id)
    entry = PlaylistTrack(playlist_id=playlist_id, track_id=track_id, position=position)
    session.add(entry)
    session.commit()
    log(
        session,
        "info",
        "Track added to playlist",
        {"playlist_id": playlist_id, "track_id": track_id, "position": position},
    )
    return jsonify(_serialize_playlist_entry(entry)), 201


@app.route("/api/playlists/<int:playlist_id>/tracks/<int:entry_id>", methods=["DELETE"])
def api_playlist_remove_entry(playlist_id: int, entry_id: int) -> Response:
    session = get_session()
    entry = session.get(PlaylistTrack, entry_id)
    if not entry or entry.playlist_id != playlist_id:
        return jsonify({"error": "Entry not found"}), 404
    session.delete(entry)
    session.commit()
    log(
        session,
        "info",
        "Track removed from playlist",
        {"playlist_id": playlist_id, "entry_id": entry_id},
    )
    return jsonify({"status": "deleted"})


@app.route("/music/<path:filename>")
def serve_music(filename: str) -> Response:
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host=config.get("host", "127.0.0.1"), port=config.get("port", 8000))
