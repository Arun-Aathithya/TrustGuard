"""Pure tests (no database): time-range parsing and chart bucketing for the history API."""
from datetime import datetime, timedelta, timezone

import pytest

from services.history_service import (
    SeriesAggregator, choose_bucket_seconds, csv_safe, iso_z, parse_instant, resolve_window, to_db,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def test_parse_instant_accepts_iso_and_epoch():
    assert parse_instant("2026-10-24T12:00:00Z") == NOW
    assert parse_instant("2026-10-24T17:30:00+05:30") == NOW
    assert parse_instant("2026-10-24T12:00:00") == NOW  # no zone = UTC
    assert parse_instant(str(int(NOW.timestamp()))) == NOW
    assert parse_instant(str(int(NOW.timestamp() * 1000))) == NOW


@pytest.mark.parametrize("bad", ["", "   ", "yesterday", "-5", "nan", "inf", "2026-13-01", "12:00"])
def test_parse_instant_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_instant(bad)


def test_resolve_window_defaults_presets_and_all():
    s, e = resolve_window(None, None, None, NOW)
    assert e == NOW and e - s == timedelta(hours=24)
    s, e = resolve_window(None, None, "1h", NOW)
    assert e - s == timedelta(hours=1)
    assert resolve_window(None, None, "all", NOW)[0] is None
    s, e = resolve_window("2026-10-24T10:00:00Z", "2026-10-24T11:00:00Z", "7d", NOW)  # explicit start wins over range
    assert e - s == timedelta(hours=1)


@pytest.mark.parametrize("args", [
    ("2026-10-24T12:00:00Z", "2026-10-24T11:00:00Z", None),
    ("2026-10-24T12:00:00Z", "2026-10-24T12:00:00Z", None),
    (None, None, "2y"),
    ("nonsense", None, None),
])
def test_resolve_window_rejects_bad_input(args):
    with pytest.raises(ValueError):
        resolve_window(*args, NOW)


def test_timestamp_output_is_utc_with_z():
    assert iso_z(NOW) == "2026-10-24T12:00:00.000Z"
    assert iso_z(to_db(NOW)) == iso_z(NOW) and iso_z(None) is None
    assert to_db(NOW).tzinfo is None


def test_bucket_size_keeps_points_under_the_limit():
    assert choose_bucket_seconds(3600, 300) == 15
    assert choose_bucket_seconds(60, 300) == 1
    assert choose_bucket_seconds(86400, 300) == 300
    assert choose_bucket_seconds(30 * 86400, 300) == 14400
    for span in (1, 59, 3600, 86400, 7 * 86400, 400 * 86400):
        b = choose_bucket_seconds(span, 300)
        assert span / b <= 300


def test_aggregator_summary_and_buckets():
    agg = SeriesAggregator(60)
    base = datetime(2026, 10, 24, 12, 0, 0)
    for i, v in enumerate([10, 20, None, 30, 40]):  # 12:00:00 12:00:20 12:00:40 | 12:01:00 12:01:20
        agg.add(base + timedelta(seconds=i * 20), v)
    p, sm = agg.points(), agg.summary()
    assert len(p) == 2
    assert p[0]["t"] == "2026-10-24T12:00:00.000Z" and p[0]["avg"] == 15 and p[0]["count"] == 2 and p[0]["missing"] == 1
    assert p[1]["avg"] == 35 and p[1]["min"] == 30 and p[1]["max"] == 40
    assert (sm["count"], sm["missing"], sm["min"], sm["max"], sm["avg"]) == (5, 1, 10, 40, 25)
    assert sm["first_at"].startswith("2026-10-24T12:00:00") and sm["last_at"].startswith("2026-10-24T12:01:20")


def test_aggregator_handles_empty_and_all_missing():
    assert SeriesAggregator(60).points() == [] and SeriesAggregator(60).summary()["avg"] is None
    only_missing = SeriesAggregator(60)
    only_missing.add(datetime(2026, 10, 24, 12, 0, 0), None)
    assert only_missing.points()[0]["avg"] is None and only_missing.summary()["min"] is None


def test_csv_cells_cannot_start_a_formula():
    assert csv_safe("=1+1") == "'=1+1" and csv_safe("@x") == "'@x" and csv_safe("+1") == "'+1" and csv_safe("-1") == "'-1"
    assert csv_safe("Motor bearing") == "Motor bearing" and csv_safe(None) == ""
