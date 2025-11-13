"""Database models for auto_break_player."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    orig_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    playlist_entries: Mapped[Iterable["PlaylistTrack"]] = relationship("PlaylistTrack", back_populates="track", cascade="all,delete")


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=func.now(), nullable=False)

    tracks: Mapped[Iterable["PlaylistTrack"]] = relationship(
        "PlaylistTrack",
        order_by="PlaylistTrack.position",
        back_populates="playlist",
        cascade="all,delete-orphan",
    )


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    playlist: Mapped[Playlist] = relationship("Playlist", back_populates="tracks")
    track: Mapped[Track] = relationship("Track", back_populates="playlist_entries")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    playlist_id: Mapped[int] = mapped_column(ForeignKey("playlists.id"))
    days: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4,5,6", nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    session_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_fired_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

    playlist: Mapped[Optional[Playlist]] = relationship("Playlist")


class Command(Base):
    __tablename__ = "commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    processed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)


class State(Base):
    __tablename__ = "state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    current_track_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tracks.id"))
    playlist_id: Mapped[Optional[int]] = mapped_column(ForeignKey("playlists.id"))
    volume: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    session_end_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    power_on: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    heartbeat_at: Mapped[dt.datetime] = mapped_column(DateTime, default=func.now(), nullable=False)


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    meta: Mapped[Optional[str]] = mapped_column(Text)


def make_engine(db_path: str | Path) -> Engine:
    database_uri = f"sqlite:///{Path(db_path)}"
    return create_engine(database_uri, future=True)


def make_session_factory(engine: Engine):
    return sessionmaker(engine, expire_on_commit=False, future=True)


def log(session: Session, level: str, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
    entry = LogEntry(level=level, message=message, meta=json.dumps(meta or {}))
    session.add(entry)
    session.commit()


def ensure_state_row(session: Session) -> State:
    state = session.get(State, 1)
    if not state:
        state = State(id=1)
        session.add(state)
        session.commit()
    return state


__all__ = [
    "Base",
    "Track",
    "Playlist",
    "PlaylistTrack",
    "Schedule",
    "Command",
    "State",
    "LogEntry",
    "make_engine",
    "make_session_factory",
    "log",
    "ensure_state_row",
]
