"""Database migration helper for auto_break_player."""
from __future__ import annotations

from config import load_config
from models import Base, ensure_state_row, make_engine, make_session_factory


def main() -> None:
    config = load_config()
    engine = make_engine(config["db_path"])
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        ensure_state_row(session)
    print("DB migrated/initialized OK.")


if __name__ == "__main__":
    main()
