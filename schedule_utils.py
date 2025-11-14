"""Shared helpers for working with playback schedules."""
from __future__ import annotations

import datetime as dt
from typing import Iterable, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Playlist

DAY_ALIASES = {
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "SUN": 6,
    "SUNDAY": 6,
    "MON": 0,
    "MONDAY": 0,
    "TUE": 1,
    "TUESDAY": 1,
    "WED": 2,
    "WEDNESDAY": 2,
    "THU": 3,
    "THUR": 3,
    "THURSDAY": 3,
    "FRI": 4,
    "FRIDAY": 4,
    "SAT": 5,
    "SATURDAY": 5,
}

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_single_day(token: str) -> int:
    try:
        return DAY_ALIASES[token]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown day token '{token}'") from exc


def _expand_token(token: str) -> List[int]:
    upper = token.upper()
    if upper in ("WEEKDAY", "WEEKDAYS"):
        return list(range(0, 5))
    if upper in ("WEEKEND", "WEEKENDS"):
        return [5, 6]
    if "-" in upper:
        start_str, end_str = [segment.strip() for segment in upper.split("-", 1)]
        start = _parse_single_day(start_str)
        end = _parse_single_day(end_str)
        if start <= end:
            return list(range(start, end + 1))
        return list(range(start, 7)) + list(range(0, end + 1))
    return [_parse_single_day(upper)]


def _coerce_iterable_days(items: Iterable[object]) -> List[int]:
    result: List[int] = []
    for item in items:
        if isinstance(item, int):
            value = item
        elif isinstance(item, str):
            value = _parse_single_day(item.strip().upper())
        else:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported day value {item!r}")
        if value < 0 or value > 6:
            raise ValueError(f"Day value must be between 0 and 6, got {value}")
        result.append(value)
    return result


def normalise_days(days: object | None) -> str:
    """Normalise day expressions into a comma separated weekday string."""
    if days is None:
        return "0,1,2,3,4,5,6"
    values: List[int] = []
    if isinstance(days, str):
        for raw in days.replace("/", ",").split(","):
            token = raw.strip()
            if not token:
                continue
            values.extend(_expand_token(token))
    elif isinstance(days, Iterable) and not isinstance(days, (str, bytes)):
        values.extend(_coerce_iterable_days(days))
    else:  # pragma: no cover - defensive
        raise ValueError("Days must be provided as a string or iterable")
    unique_sorted = sorted(set(values))
    return ",".join(str(item) for item in unique_sorted)


def parse_day_string(days: str | None) -> List[int]:
    if not days:
        return list(range(7))
    try:
        parsed = [int(item.strip()) for item in days.split(",") if item.strip() != ""]
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid day entry in '{days}'") from exc
    if not parsed:
        return list(range(7))
    for value in parsed:
        if value < 0 or value > 6:
            raise ValueError(f"Day value must be between 0 and 6, got {value}")
    return sorted(set(parsed))


def describe_days(days: str | None) -> str:
    parsed = parse_day_string(days)
    if len(parsed) == 7:
        return "Every day"
    if parsed == list(range(5)):
        return "Weekdays"
    if parsed == [5, 6]:
        return "Weekend"
    if not parsed:
        return "—"

    def _label_for_group(start: int, end: int) -> str:
        if start == end:
            return DAY_LABELS[start]
        if end == start + 1:
            return f"{DAY_LABELS[start]} – {DAY_LABELS[end]}"
        return f"{DAY_LABELS[start]} – {DAY_LABELS[end]}"

    groups: List[List[int]] = []
    for value in parsed:
        if not groups or value != groups[-1][-1] + 1:
            groups.append([value, value])
        else:
            groups[-1][-1] = value
    labels = [_label_for_group(group[0], group[1]) for group in groups]
    return ", ".join(labels)


def next_occurrence(schedule, reference: dt.datetime | None = None) -> dt.datetime | None:
    if reference is None:
        reference = dt.datetime.now()
    days = parse_day_string(getattr(schedule, "days", None))
    if not days:
        return None
    start_time = getattr(schedule, "start_time", "00:00") or "00:00"
    try:
        hour, minute = [int(part) for part in start_time.split(":", 1)]
    except ValueError:
        return None
    start_time_obj = dt.time(hour=hour, minute=minute)
    reference = reference.replace(second=0, microsecond=0)

    for offset in range(14):
        candidate_date = reference.date() + dt.timedelta(days=offset)
        if candidate_date.weekday() not in days:
            continue
        candidate = dt.datetime.combine(candidate_date, start_time_obj)
        if candidate >= reference:
            return candidate
    return None


def resolve_playlist(session: Session, identifier: object) -> Playlist:
    """Resolve a playlist by id or exact name."""
    if isinstance(identifier, Playlist):
        return identifier
    if isinstance(identifier, int):
        playlist = session.get(Playlist, identifier)
        if not playlist:
            raise ValueError(f"Playlist id {identifier} not found")
        return playlist
    if not isinstance(identifier, str):  # pragma: no cover - defensive
        raise ValueError("Playlist identifier must be string or integer")
    token = identifier.strip()
    if not token:
        raise ValueError("Playlist identifier cannot be empty")
    if token.isdigit():
        playlist = session.get(Playlist, int(token))
        if playlist:
            return playlist
    stmt = select(Playlist).where(Playlist.name == token)
    playlist = session.scalars(stmt).first()
    if not playlist:
        raise ValueError(f"Playlist '{token}' not found")
    return playlist


__all__ = [
    "DAY_ALIASES",
    "DAY_LABELS",
    "normalise_days",
    "parse_day_string",
    "describe_days",
    "next_occurrence",
    "resolve_playlist",
]
