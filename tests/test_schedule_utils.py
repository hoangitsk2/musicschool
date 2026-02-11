import datetime as dt

from schedule_utils import describe_days, next_occurrence, normalise_days, parse_day_string


class DummySchedule:
    def __init__(self, days: str, start_time: str, enabled: bool = True):
        self.days = days
        self.start_time = start_time
        self.enabled = enabled


def test_describe_days_aliases():
    assert describe_days("0,1,2,3,4,5,6") == "Every day"
    assert describe_days("0,1,2,3,4") == "Weekdays"
    assert describe_days("5,6") == "Weekend"
    assert describe_days("0,2,4") == "Mon, Wed, Fri"
    assert describe_days("4,5,6") == "Fri – Sun"
    assert describe_days(None) == "Every day"


def test_parse_day_string_handles_empty():
    assert parse_day_string(None) == list(range(7))
    assert parse_day_string("0,2,2,4") == [0, 2, 4]


def test_next_occurrence_rolls_over_week():
    reference = dt.datetime(2024, 1, 1, 9, 0)  # Monday
    schedule = DummySchedule("1,3", "08:15")  # Tue & Thu
    upcoming = next_occurrence(schedule, reference)
    assert upcoming == dt.datetime(2024, 1, 2, 8, 15)


def test_next_occurrence_same_day_future():
    reference = dt.datetime(2024, 1, 1, 9, 0)  # Monday
    schedule = DummySchedule("0,2", "10:00")
    upcoming = next_occurrence(schedule, reference)
    assert upcoming == dt.datetime(2024, 1, 1, 10, 0)


def test_normalise_days_supports_aliases():
    assert normalise_days("Weekend") == "5,6"
    assert normalise_days("Fri-Mon") == "0,4,5,6"
