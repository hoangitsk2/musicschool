from types import SimpleNamespace

from sqlalchemy import select

from models import Base, Playlist, Schedule, make_engine, make_session_factory

from schedule_utils import normalise_days
from scripts import schedule_cli


def _make_session(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    return Session()


def test_normalise_days_variants():
    assert normalise_days(None) == "0,1,2,3,4,5,6"
    assert normalise_days("Mon-Fri") == "0,1,2,3,4"
    assert normalise_days("Weekend") == "5,6"
    assert normalise_days("Fri-Mon") == "0,4,5,6"
    assert normalise_days([0, 6, 0]) == "0,6"


def test_schedule_lifecycle(tmp_path):
    session = _make_session(tmp_path)
    playlist = Playlist(name="Morning Mix")
    session.add(playlist)
    session.commit()

    add_args = SimpleNamespace(
        name="Morning",
        playlist=str(playlist.id),
        time="08:00",
        minutes=20,
        days="Mon-Fri",
        disabled=False,
    )
    schedule_cli.command_add(session, {}, add_args)

    schedule = session.scalars(select(Schedule).where(Schedule.name == "Morning")).first()
    assert schedule is not None
    assert schedule.days == "0,1,2,3,4"
    assert schedule.enabled

    toggle_args = SimpleNamespace(schedule_id=schedule.id)
    schedule_cli.command_enable_disable(session, {}, toggle_args, False)
    session.expire_all()
    updated = session.get(Schedule, schedule.id)
    assert updated is not None
    assert not updated.enabled

    schedule_cli.command_enable_disable(session, {}, toggle_args, True)
    session.expire_all()
    updated = session.get(Schedule, schedule.id)
    assert updated is not None and updated.enabled

    delete_args = SimpleNamespace(schedule_id=schedule.id)
    schedule_cli.command_delete(session, {}, delete_args)
    remaining = session.scalars(select(Schedule)).all()
    assert remaining == []
