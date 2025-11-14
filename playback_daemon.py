"""Background daemon responsible for scheduled playback."""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import load_config
from gpio_control import RelayController
from models import (
    Base,
    Command,
    Playlist,
    PlaylistTrack,
    Schedule,
    Track,
    ensure_state_row,
    log,
    make_engine,
    make_session_factory,
)
from player import BasePlayer, make_player
from schedule_utils import normalise_days, resolve_playlist
from sqlalchemy import select


class PlaybackDaemon:
    def __init__(self, config: Dict[str, object]) -> None:
        self.config = config
        db_path = config["db_path"]  # type: ignore[index]
        music_dir = Path(config["music_dir"])  # type: ignore[index]
        logs_dir = Path(config["logs_dir"])  # type: ignore[index]
        music_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        engine = make_engine(db_path)
        Base.metadata.create_all(engine)
        self.session_factory = make_session_factory(engine)

        with self.session_factory() as session:
            ensure_state_row(session)
            self._apply_bootstrap_schedules(session)

        gpio_cfg = config.get("gpio", {})
        self.relay = RelayController(
            enabled=bool(gpio_cfg.get("enabled", False)),
            relay_pin=int(gpio_cfg.get("relay_pin", 17)),
            active_high=bool(gpio_cfg.get("active_high", True)),
        )

        backend = str(config.get("vlc_backend", "auto"))
        self.player: BasePlayer = make_player(backend)
        self.current_track_ids: List[int] = []

    # ------------------------------------------------------------------
    def _log(self, session, level: str, message: str, meta: Optional[Dict[str, object]] = None) -> None:
        log(session, level, message, meta or {})

    def _apply_bootstrap_schedules(self, session) -> None:
        definitions = self.config.get("bootstrap_schedules")
        if not definitions:
            return
        if not isinstance(definitions, list):
            self._log(
                session,
                "warning",
                "bootstrap_schedules must be a list",
                {"received_type": type(definitions).__name__},
            )
            return
        for index, entry in enumerate(definitions):
            if not isinstance(entry, dict):
                self._log(
                    session,
                    "warning",
                    "Schedule definition must be a mapping",
                    {"index": index},
                )
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                self._log(session, "warning", "Schedule definition missing name", {"index": index})
                continue
            playlist_ref = entry.get("playlist")
            if playlist_ref is None:
                self._log(session, "warning", "Schedule definition missing playlist", {"name": name})
                continue
            try:
                playlist = resolve_playlist(session, playlist_ref)
            except Exception as exc:  # pragma: no cover - defensive
                self._log(
                    session,
                    "warning",
                    "Playlist for bootstrap schedule not found",
                    {"name": name, "playlist": playlist_ref, "error": str(exc)},
                )
                continue
            start_time = str(entry.get("time") or entry.get("start_time") or "").strip()
            if not start_time:
                self._log(session, "warning", "Schedule definition missing start time", {"name": name})
                continue
            raw_minutes = entry.get("minutes", entry.get("session_minutes", self.config.get("session_default_minutes", 15)))
            try:
                minutes = max(1, int(raw_minutes))
            except (TypeError, ValueError):
                minutes = int(self.config.get("session_default_minutes", 15))
            try:
                days = normalise_days(entry.get("days"))
            except Exception as exc:  # pragma: no cover - defensive
                self._log(
                    session,
                    "warning",
                    "Invalid days for bootstrap schedule",
                    {"name": name, "error": str(exc)},
                )
                days = normalise_days(None)
            enabled_value = entry.get("enabled")
            enabled = bool(enabled_value) if enabled_value is not None else True
            schedule = session.scalars(select(Schedule).where(Schedule.name == name)).first()
            if schedule:
                schedule.playlist_id = playlist.id
                schedule.days = days
                schedule.start_time = start_time
                schedule.session_minutes = minutes
                schedule.enabled = enabled
            else:
                schedule = Schedule(
                    name=name,
                    playlist_id=playlist.id,
                    days=days,
                    start_time=start_time,
                    session_minutes=minutes,
                    enabled=enabled,
                )
                session.add(schedule)
            session.commit()
            self._log(
                session,
                "info",
                "Bootstrap schedule applied",
                {
                    "schedule": name,
                    "playlist_id": playlist.id,
                    "start_time": start_time,
                    "minutes": minutes,
                    "days": days,
                    "enabled": enabled,
                },
            )


    def _playlist_files(self, session, playlist_id: int) -> Tuple[List[str], List[int]]:
        stmt = (
            select(PlaylistTrack, Track)
            .join(Track)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
        )
        result = session.execute(stmt).all()
        music_dir = Path(self.config["music_dir"])  # type: ignore[index]
        track_ids = [track.id for _, track in result]
        files = [str(music_dir / track.stored_filename) for _, track in result]
        return files, track_ids

    def _start_tracks(
        self,
        session,
        file_paths: List[str],
        track_ids: List[int],
        duration_seconds: int,
        playlist_id: Optional[int],
    ) -> bool:
        if not file_paths:
            return False
        duration_seconds = max(30, duration_seconds)
        state = ensure_state_row(session)
        volume = state.volume or int(self.config.get("volume_default", 70))
        state.volume = volume
        if not self.relay.is_power_on:
            self.relay.power_on()
        self.player.load_playlist(file_paths)
        self.player.set_volume(volume)
        self.player.play()
        now = dt.datetime.now()
        state.status = "playing"
        state.playlist_id = playlist_id
        state.session_end_at = now + dt.timedelta(seconds=duration_seconds)
        state.power_on = True
        self.current_track_ids = track_ids
        state.current_track_id = track_ids[0] if track_ids else None
        state.updated_at = now
        session.commit()
        return True

    def _start_session(self, session, playlist_id: int, minutes: int, reason: str) -> None:
        files, track_ids = self._playlist_files(session, playlist_id)
        if not files:
            self._log(session, "warning", "Playlist empty, cannot start session", {"playlist_id": playlist_id})
            return
        if self._start_tracks(session, files, track_ids, minutes * 60, playlist_id):
            self._log(
                session,
                "info",
                "Session started",
                {
                    "playlist_id": playlist_id,
                    "minutes": minutes,
                    "reason": reason,
                },
            )

    def _start_preview(self, session, track_id: int) -> None:
        track = session.get(Track, track_id)
        if not track:
            self._log(session, "warning", "Preview track missing", {"track_id": track_id})
            return
        music_dir = Path(self.config["music_dir"])  # type: ignore[index]
        file_path = music_dir / track.stored_filename
        if not file_path.exists():
            self._log(session, "warning", "Preview file missing", {"track_id": track_id})
            return
        state = ensure_state_row(session)
        if state.status == "playing":
            self._stop_session(session, "preview interrupt")
        duration = track.duration_sec or int(self.config.get("session_default_minutes", 15)) * 60
        duration = max(30, int(duration))
        if self._start_tracks(session, [str(file_path)], [track.id], duration, None):
            self._log(
                session,
                "info",
                "Preview started",
                {
                    "track_id": track_id,
                    "duration_seconds": duration,
                },
            )

    def _stop_session(self, session, reason: str) -> None:
        state = ensure_state_row(session)
        if state.status != "playing" and not self.relay.is_power_on:
            return
        self.player.stop()
        if self.relay.is_power_on:
            self.relay.power_off()
        state.status = "idle"
        state.playlist_id = None
        state.session_end_at = None
        state.current_track_id = None
        state.power_on = False
        self.current_track_ids = []
        state.updated_at = dt.datetime.now()
        session.commit()
        self._log(session, "info", "Session stopped", {"reason": reason})

    def _tick_schedules(self, session) -> None:
        now = dt.datetime.now()
        minute_key = now.strftime("%H:%M")
        weekday = str(now.weekday())
        schedules = session.scalars(select(Schedule).where(Schedule.enabled == True)).all()  # noqa: E712
        for sched in schedules:
            if weekday not in sched.days.split(","):
                continue
            if sched.start_time != minute_key:
                continue
            if sched.last_fired_at and (now - sched.last_fired_at).total_seconds() < 50:
                continue
            if sched.playlist_id is None:
                continue
            minutes = sched.session_minutes or int(self.config.get("session_default_minutes", 15))
            self._start_session(session, sched.playlist_id, minutes, f"schedule:{sched.id}")
            sched.last_fired_at = now
            session.commit()

    def _tick_commands(self, session) -> None:
        commands = session.scalars(select(Command).where(Command.processed_at.is_(None)).order_by(Command.created_at)).all()
        for command in commands:
            payload = json.loads(command.payload) if command.payload else {}
            if command.type == "PLAY":
                playlist_id = payload.get("playlist_id")
                minutes = int(payload.get("minutes", self.config.get("session_default_minutes", 15)))
                if playlist_id is None:
                    playlist_id = self._resolve_playlist(session)
                if playlist_id is None:
                    self._log(session, "warning", "No playlist available for PLAY command")
                else:
                    self._start_session(session, int(playlist_id), minutes, "command")
            elif command.type == "STOP":
                self._stop_session(session, "command")
            elif command.type == "SET_VOLUME":
                volume = int(payload.get("volume", self.config.get("volume_default", 70)))
                self.player.set_volume(volume)
                state = ensure_state_row(session)
                state.volume = volume
                state.updated_at = dt.datetime.now()
                session.commit()
                self._log(session, "info", "Volume updated", {"volume": volume})
            elif command.type == "SKIP":
                self.player.skip()
                idx = self.player.current_index()
                state = ensure_state_row(session)
                if 0 <= idx < len(self.current_track_ids):
                    state.current_track_id = self.current_track_ids[idx]
                state.updated_at = dt.datetime.now()
                session.commit()
            elif command.type == "POWER_ON":
                self.relay.power_on()
                state = ensure_state_row(session)
                state.power_on = True
                state.updated_at = dt.datetime.now()
                session.commit()
                self._log(session, "info", "Relay powered on")
            elif command.type == "POWER_OFF":
                self.relay.power_off()
                state = ensure_state_row(session)
                state.power_on = False
                state.updated_at = dt.datetime.now()
                session.commit()
                self._log(session, "info", "Relay powered off")
            elif command.type == "PREVIEW":
                track_id = payload.get("track_id")
                if track_id is None:
                    self._log(session, "warning", "Preview command missing track_id")
                else:
                    self._start_preview(session, int(track_id))
            command.processed_at = dt.datetime.now()
            session.commit()

    def _resolve_playlist(self, session) -> Optional[int]:
        playlists = session.scalars(select(Playlist.id)).all()
        if len(playlists) == 1:
            return playlists[0]
        return None

    def _tick_player(self, session) -> None:
        idx = self.player.update()
        if idx is None:
            idx = self.player.current_index()
        state = ensure_state_row(session)
        if idx is not None and idx >= 0 and idx < len(self.current_track_ids):
            state.current_track_id = self.current_track_ids[idx]
        elif idx is not None and idx < 0:
            state.current_track_id = None
        if not self.player.is_playing() and state.status == "playing" and idx == -1:
            self._stop_session(session, "playlist finished")
            return
        state.updated_at = dt.datetime.now()
        session.commit()

    def _tick_session_timeout(self, session) -> None:
        state = ensure_state_row(session)
        if state.status != "playing" or not state.session_end_at:
            return
        if dt.datetime.now() >= state.session_end_at:
            self._stop_session(session, "session timeout")

    def _heartbeat(self, session) -> None:
        state = ensure_state_row(session)
        state.heartbeat_at = dt.datetime.now()
        session.commit()

    def run_forever(self) -> None:
        try:
            while True:
                start = time.time()
                with self.session_factory() as session:
                    ensure_state_row(session)
                    self._tick_schedules(session)
                    self._tick_commands(session)
                    self._tick_player(session)
                    self._tick_session_timeout(session)
                    self._heartbeat(session)
                elapsed = time.time() - start
                time.sleep(max(0.1, 0.5 - elapsed))
        except KeyboardInterrupt:
            pass
        finally:
            self.player.stop()
            self.relay.cleanup()


def main() -> None:
    config = load_config()
    daemon = PlaybackDaemon(config)
    daemon.run_forever()


if __name__ == "__main__":
    main()
