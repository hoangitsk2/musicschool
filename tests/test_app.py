from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from config import load_config
from models import Base, Command, Playlist, PlaylistTrack, Track, ensure_state_row, make_engine
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


def test_player_cvlc_instantiation():
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
