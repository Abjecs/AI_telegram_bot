from datetime import datetime, timedelta

import pytest

from handlers.reminders import parse_remind_time


def test_parse_relative_minutes_is_future():
    before = datetime.now().astimezone()
    result = parse_remind_time("+5m")
    after = datetime.now().astimezone()
    assert before + timedelta(minutes=4, seconds=59) < result < after + timedelta(minutes=5, seconds=1)


def test_parse_invalid_time():
    with pytest.raises(ValueError):
        parse_remind_time("tomorrow")


def test_parse_invalid_unit():
    with pytest.raises(ValueError):
        parse_remind_time("+5x")
