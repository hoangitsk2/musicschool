from pathlib import Path

from sqlalchemy import select

from models import Base, Playlist, Schedule, make_engine, make_session_factory
from playback_daemon import PlaybackDaemon


def _prepare_db(db_path: Path):
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def test_bootstrap_creates_schedule(tmp_path):
    db_path = tmp_path / "boot.db"
    Session = _prepare_db(db_path)
    with Session() as session:
        session.add(Playlist(name="Morning Playlist"))
        session.commit()

    config = {
        "db_path": str(db_path),
        "music_dir": str(tmp_path / "music"),
        "logs_dir": str(tmp_path / "logs"),
        "vlc_backend": "dummy",
        "bootstrap_schedules": [
            {
                "name": "Morning Bell",
                "playlist": "Morning Playlist",
                "time": "08:00",
                "days": "Mon-Fri",
                "minutes": 20,
            }
        ],
    }

    PlaybackDaemon(config)

    with Session() as session:
        schedule = session.scalars(select(Schedule)).one()
        assert schedule.name == "Morning Bell"
        assert schedule.days == "0,1,2,3,4"
        assert schedule.start_time == "08:00"
        assert schedule.session_minutes == 20
        assert schedule.enabled is True


def test_bootstrap_updates_existing(tmp_path):
    db_path = tmp_path / "boot_update.db"
    Session = _prepare_db(db_path)
    with Session() as session:
        playlist = Playlist(name="Morning Playlist")
        alt_playlist = Playlist(name="Alt Playlist")
        session.add_all([playlist, alt_playlist])
        session.commit()
        schedule = Schedule(
            name="Morning Bell",
            playlist_id=alt_playlist.id,
            days="0,1,2,3,4,5,6",
            start_time="07:30",
            session_minutes=10,
            enabled=False,
        )
        session.add(schedule)
        session.commit()

    config = {
        "db_path": str(db_path),
        "music_dir": str(tmp_path / "music2"),
        "logs_dir": str(tmp_path / "logs2"),
        "vlc_backend": "dummy",
        "bootstrap_schedules": [
            {
                "name": "Morning Bell",
                "playlist": "Morning Playlist",
                "time": "08:15",
                "days": "Weekend",
                "minutes": 25,
                "enabled": True,
            }
        ],
    }

    PlaybackDaemon(config)

    with Session() as session:
        schedule = session.scalars(select(Schedule)).one()
        assert schedule.playlist.name == "Morning Playlist"
        assert schedule.days == "5,6"
        assert schedule.start_time == "08:15"
        assert schedule.session_minutes == 25
        assert schedule.enabled is True
