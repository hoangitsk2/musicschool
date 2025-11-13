"""Flask application for the auto_break_player project."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Dict, Iterable, Optional
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

def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in app.config["ALLOWED_EXTENSIONS"]


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
            if file.filename == "":
                continue
            if not allowed_file(file.filename):
                flash(f"File '{file.filename}' has an invalid extension.", "error")
                continue
            stored_name = f"{uuid4().hex}{Path(file.filename).suffix.lower()}"
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
                orig_filename=secure_filename(file.filename),
                stored_filename=secure_name,
                content_type=file.mimetype or "audio/mpeg",
                duration_sec=duration,
            )
            session.add(track)
            session.commit()
            log(session, "info", "File uploaded", {"track_id": track.id, "filename": track.orig_filename})
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


@app.route("/api/playlists")
def api_playlists() -> Response:
    session = get_session()
    playlists = session.scalars(select(Playlist)).all()
    return jsonify([{"id": p.id, "name": p.name} for p in playlists])


@app.route("/api/tracks")
def api_tracks() -> Response:
    session = get_session()
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


def _playlist_track_count(session, playlist_id: int) -> int:
    return session.scalar(
        select(func.count()).select_from(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
    ) or 0


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


@app.route("/music/<path:filename>")
def serve_music(filename: str) -> Response:
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host=config.get("host", "127.0.0.1"), port=config.get("port", 8000))
