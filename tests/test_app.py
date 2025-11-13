from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path

import pytest

from config import load_config
from models import Base, Command, Playlist, PlaylistTrack, Schedule, Track, ensure_state_row, make_engine
from player import CVLCPlayer, DummyPlayer, make_player
from sqlalchemy import select


def test_db_init(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    assert db_path.exists()


def test_config_load():
    cfg = load_config()
    assert "session_default_minutes" in cfg


def test_cors_allows_any_origin(app_module, client):
    response = client.options("/api/status", headers={"Origin": "https://example.com"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]
    assert response.headers["Access-Control-Allow-Headers"] == "Content-Type"


def test_cors_restricts_to_configured_origins(app_module, client):
    original_origins = app_module._CORS_ORIGINS
    try:
        app_module._CORS_ORIGINS = ("https://allowed.example",)
        disallowed = client.get("/api/status", headers={"Origin": "https://blocked.example"})
        assert "Access-Control-Allow-Origin" not in disallowed.headers

        allowed = client.get("/api/status", headers={"Origin": "https://allowed.example"})
        assert allowed.headers["Access-Control-Allow-Origin"] == "https://allowed.example"
        assert "Origin" in allowed.headers.get("Vary", "")
    finally:
        app_module._CORS_ORIGINS = original_origins


def test_player_dummy():
    player = DummyPlayer()
    player.load_playlist(["track1.mp3", "track2.mp3"])
    player.play()
    assert player.is_playing()
    player.skip()
    assert player.current_index() == 1
    player.stop()
    assert not player.is_playing()
    auto_player = make_player("dummy")
    assert isinstance(auto_player, DummyPlayer)


def test_player_cvlc_instantiation(monkeypatch, tmp_path):
    fake_vlc = tmp_path / "vlc"
    fake_vlc.write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("CVLC_PATH", str(fake_vlc))
    player = make_player("cvlc")
    assert isinstance(player, CVLCPlayer)


@pytest.fixture(scope="session")
def app_module(tmp_path_factory):
    cfg_dir = tmp_path_factory.mktemp("cfg")
    config_path = Path("config.yaml")
    backup = config_path.read_text() if config_path.exists() else None
    config_path.write_text(
        """
secret_key: test
host: 127.0.0.1
port: 8000
db_path: {db}
music_dir: {music}
logs_dir: {logs}
vlc_backend: dummy
gpio:
  enabled: false
""".strip().format(
            db=cfg_dir / "test.db",
            music=cfg_dir / "music",
            logs=cfg_dir / "logs",
        )
    )
    import config as config_module

    importlib.reload(config_module)
    if "app" in sys.modules:
        del sys.modules["app"]
    app_module = importlib.import_module("app")
    yield app_module
    app_module.engine.dispose()
    if backup is None:
        config_path.unlink(missing_ok=True)
    else:
        config_path.write_text(backup)
    importlib.reload(config_module)
    if "app" in sys.modules:
        del sys.modules["app"]


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()


def _add_track(session, name="track.mp3"):
    track = Track(orig_filename=name, stored_filename=name, content_type="audio/mpeg")
    session.add(track)
    session.commit()
    return track


def _add_playlist(session, name="Playlist"):
    playlist = Playlist(name=name)
    session.add(playlist)
    session.commit()
    return playlist


def _link_track(session, playlist, track, position=0):
    entry = PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=position)
    session.add(entry)
    session.commit()
    return entry


def test_api_play_validation(app_module, client):
    with app_module.SessionLocal() as session:
        ensure_state_row(session)
        playlist = _add_playlist(session)
        track = _add_track(session)
        _link_track(session, playlist, track)

    response = client.post("/api/play", json={"minutes": 5})
    assert response.status_code == 200

    with app_module.SessionLocal() as session:
        second = _add_playlist(session, "Second")

    response_multi = client.post("/api/play", json={"minutes": 5})
    assert response_multi.status_code == 400

    response_empty = client.post("/api/play", json={"playlist_id": second.id})
    assert response_empty.status_code == 400


def test_volume_endpoint(app_module, client):
    with app_module.SessionLocal() as session:
        state = ensure_state_row(session)
        state.volume = 30
        session.commit()

    response = client.post("/api/volume", json={"volume": 55})
    assert response.status_code == 200

    with app_module.SessionLocal() as session:
        state = ensure_state_row(session)
        assert state.volume == 55


def test_api_tracks_and_preview(app_module, client):
    with app_module.SessionLocal() as session:
        ensure_state_row(session)
        track = _add_track(session, "sample.mp3")

    list_response = client.get("/api/tracks")
    assert list_response.status_code == 200
    data = list_response.get_json()
    assert any(item["id"] == track.id for item in data)

    preview_response = client.post("/api/preview", json={"track_id": track.id})
    assert preview_response.status_code == 200

    with app_module.SessionLocal() as session:
        command = session.scalars(
            select(Command).where(Command.type == "PREVIEW").order_by(Command.created_at.desc())
        ).first()
        assert command is not None


def test_api_tracks_upload_and_delete(app_module, client):
    data = {
        "files": (io.BytesIO(b"fake data"), "upload.mp3"),
    }
    response = client.post("/api/tracks", data=data, content_type="multipart/form-data")
    assert response.status_code == 201
    data = response.get_json()
    uploaded = data["uploaded"][0]

    delete_response = client.delete(f"/api/tracks/{uploaded['id']}")
    assert delete_response.status_code == 200


def test_api_playlist_management(app_module, client):
    playlist_response = client.post("/api/playlists", json={"name": "Gym"})
    assert playlist_response.status_code == 201
    playlist_id = playlist_response.get_json()["id"]

    with app_module.SessionLocal() as session:
        track = _add_track(session, "gym.mp3")

    add_response = client.post(
        f"/api/playlists/{playlist_id}/tracks",
        json={"track_id": track.id, "position": 0},
    )
    assert add_response.status_code == 201
    entry_id = add_response.get_json()["entry_id"]

    detail_response = client.get(f"/api/playlists/{playlist_id}")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    assert any(item["entry_id"] == entry_id for item in detail["tracks"])

    delete_entry = client.delete(f"/api/playlists/{playlist_id}/tracks/{entry_id}")
    assert delete_entry.status_code == 200


def test_api_schedule_management(app_module, client):
    with app_module.SessionLocal() as session:
        playlist = _add_playlist(session, "Focus")

    create_response = client.post(
        "/api/schedules",
        json={
            "name": "Morning",
            "playlist_id": playlist.id,
            "days": ["0", "1"],
            "start_time": "08:00",
            "session_minutes": 20,
            "enabled": True,
        },
    )
    assert create_response.status_code == 201
    schedule_id = create_response.get_json()["id"]

    list_response = client.get("/api/schedules")
    assert list_response.status_code == 200
    schedules = list_response.get_json()
    assert any(item["id"] == schedule_id for item in schedules)

    toggle_response = client.post(f"/api/schedules/{schedule_id}/toggle")
    assert toggle_response.status_code == 200


def test_break_plan_helper_and_api(app_module, client):
    with app_module.SessionLocal() as session:
        playlist = _add_playlist(session, "Recess")
        track = _add_track(session, "bell.mp3")
        _link_track(session, playlist, track)
        result = app_module.apply_break_plan(
            session,
            playlist.id,
            start_times=["09:30", "15:30"],
            days=["1", "2", "3", "4", "5"],
            minutes=15,
            name_prefix="Recess",
            replace=True,
        )
        assert len(result["created"]) == 2
        created_ids = set(result["created"])  # noqa: F841 - ensure not empty

    response = client.post(
        "/api/schedules/break-plan",
        json={
            "playlist_id": playlist.id,
            "start_times": ["09:30"],
            "session_minutes": 20,
            "days": ["1", "2", "3", "4", "5"],
            "name_prefix": "Recess",
            "replace": True,
        },
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["updated"]

    with app_module.SessionLocal() as session:
        schedules = session.scalars(select(Schedule)).all()
        assert any(not sched.enabled for sched in schedules if sched.start_time == "15:30")
