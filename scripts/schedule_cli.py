"""Utility CLI for managing playback schedules.

This helper is aimed at Raspberry Pi deployments where the database lives
locally.  It allows an operator to quickly list, add, enable/disable, or
delete schedules without opening the web UI – useful when the device is
running headless or when you want to script initial provisioning.

Example usage::

    # list existing schedules
    python scripts/schedule_cli.py list

    # add a new weekday morning schedule
    python scripts/schedule_cli.py add --name "Morning" --playlist "Morning Mix" \
        --time 08:00 --minutes 20 --days Mon-Fri

    # disable a schedule by its identifier
    python scripts/schedule_cli.py disable 3

The script intentionally keeps dependencies minimal so it can run in
lightweight environments (including cron jobs or SSH sessions).
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterable, Sequence

from config import load_config
from models import Base, Schedule, make_engine, make_session_factory
from sqlalchemy import select

from schedule_utils import normalise_days, resolve_playlist

def _init_session():
    config = load_config()
    engine = make_engine(config["db_path"])
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    return Session(), config


def _print_schedules(schedules: Sequence[Schedule]) -> None:
    if not schedules:
        print("No schedules defined.")
        return
    header = f"{'ID':<4} {'Name':<20} {'Playlist':<20} {'Days':<12} {'Start':<6} {'Minutes':<7} {'Enabled':<7}"
    print(header)
    print("-" * len(header))
    for sched in schedules:
        playlist_name = sched.playlist.name if sched.playlist else "—"
        line = f"{sched.id:<4} {sched.name:<20} {playlist_name:<20} {sched.days:<12} {sched.start_time:<6} {sched.session_minutes:<7} {str(sched.enabled):<7}"
        print(line)


def command_list(session, _config) -> int:
    schedules = session.scalars(select(Schedule).order_by(Schedule.start_time)).all()
    _print_schedules(schedules)
    return 0


def command_add(session, _config, args) -> int:
    playlist = resolve_playlist(session, args.playlist)
    days = normalise_days(args.days)
    schedule = Schedule(
        name=args.name,
        playlist_id=playlist.id,
        days=days,
        start_time=args.time,
        session_minutes=args.minutes,
        enabled=not args.disabled,
    )
    session.add(schedule)
    session.commit()
    print(f"Created schedule #{schedule.id} for playlist '{playlist.name}'.")
    return 0


def command_enable_disable(session, _config, args, enabled: bool) -> int:
    schedule = session.get(Schedule, args.schedule_id)
    if not schedule:
        print(f"Schedule id {args.schedule_id} not found.", file=sys.stderr)
        return 1
    schedule.enabled = enabled
    session.commit()
    state = "enabled" if enabled else "disabled"
    print(f"Schedule #{schedule.id} {state}.")
    return 0


def command_delete(session, _config, args) -> int:
    schedule = session.get(Schedule, args.schedule_id)
    if not schedule:
        print(f"Schedule id {args.schedule_id} not found.", file=sys.stderr)
        return 1
    session.delete(schedule)
    session.commit()
    print(f"Schedule #{args.schedule_id} deleted.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage playback schedules")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all schedules")

    add_parser = subparsers.add_parser("add", help="Create a new schedule")
    add_parser.add_argument("--name", required=True, help="Name for the schedule")
    add_parser.add_argument("--playlist", required=True, help="Playlist id or exact name")
    add_parser.add_argument("--time", required=True, help="Start time in HH:MM (24h)")
    add_parser.add_argument("--minutes", type=int, default=15, help="Session length in minutes")
    add_parser.add_argument(
        "--days",
        help="Comma separated day list (numbers or names). Defaults to all days.",
    )
    add_parser.add_argument(
        "--disabled",
        action="store_true",
        help="Create the schedule in disabled state",
    )

    enable_parser = subparsers.add_parser("enable", help="Enable a schedule")
    enable_parser.add_argument("schedule_id", type=int)

    disable_parser = subparsers.add_parser("disable", help="Disable a schedule")
    disable_parser.add_argument("schedule_id", type=int)

    delete_parser = subparsers.add_parser("delete", help="Delete a schedule")
    delete_parser.add_argument("schedule_id", type=int)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    session, config = _init_session()
    try:
        if args.command == "list":
            return command_list(session, config)
        if args.command == "add":
            return command_add(session, config, args)
        if args.command == "enable":
            return command_enable_disable(session, config, args, True)
        if args.command == "disable":
            return command_enable_disable(session, config, args, False)
        if args.command == "delete":
            return command_delete(session, config, args)
    finally:
        session.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
