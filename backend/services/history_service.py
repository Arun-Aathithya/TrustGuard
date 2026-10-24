"""
Pure helpers for the history API (no database, no third-party imports, so they are easy to test).

Timestamps are stored as naive UTC in the database. Everything here treats a naive datetime as UTC and
anything that goes out in JSON/CSV is written as ISO-8601 with a trailing "Z".
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

RANGE_PRESETS = {"15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
DEFAULT_RANGE = "24h"
NICE_BUCKETS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400, 172800, 604800]
_EPOCH = datetime(1970, 1, 1)


def parse_instant(value: str) -> datetime:
    """ISO-8601 (a trailing Z is fine; no zone means UTC) or epoch seconds/milliseconds -> aware UTC datetime."""
    text = (value or "").strip()
    if not text:
        raise ValueError("empty time value")
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"'{value}' is not a valid time")
        seconds = number / 1000.0 if number > 1e11 else number
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"'{value}' is not a valid ISO-8601 time (example: 2026-10-24T12:00:00Z)") from None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(timezone.utc)


def resolve_window(start: str | None, end: str | None, range_: str | None, now: datetime) -> tuple[datetime | None, datetime]:
    """
    Returns (start, end) as aware UTC datetimes. start None means "from the beginning".
    An explicit `start` wins over `range`; with neither, the last 24 hours are used. `range=all` means no start.
    """
    end_dt = parse_instant(end) if end else now
    if start:
        start_dt = parse_instant(start)
    else:
        key = (range_ or DEFAULT_RANGE).strip().lower()
        if key == "all":
            start_dt = None
        elif key in RANGE_PRESETS:
            start_dt = end_dt - timedelta(seconds=RANGE_PRESETS[key])
        else:
            raise ValueError(f"range must be one of {', '.join(RANGE_PRESETS)} or all")
    if start_dt is not None and start_dt >= end_dt:
        raise ValueError("start must be earlier than end")
    return start_dt, end_dt


def to_db(dt: datetime | None) -> datetime | None:
    """Aware -> naive UTC, the form stored in the database."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    naive = to_db(dt)
    return naive.isoformat(timespec="milliseconds") + "Z"


def choose_bucket_seconds(span_seconds: float, max_points: int) -> int:
    """Smallest 'nice' bucket size that keeps the number of points at or below max_points."""
    need = max(1.0, math.ceil(span_seconds / max(1, max_points)))
    for b in NICE_BUCKETS:
        if b >= need:
            return b
    return int(need)


@dataclass
class _Bucket:
    n: int = 0
    total: float = 0.0
    lo: float = math.inf
    hi: float = -math.inf
    missing: int = 0


@dataclass
class SeriesAggregator:
    """Streams readings once: overall summary + fixed-size time buckets, so memory depends on buckets, not rows."""
    bucket_seconds: int
    buckets: dict[int, _Bucket] = field(default_factory=dict)
    count: int = 0
    missing: int = 0
    total: float = 0.0
    lo: float = math.inf
    hi: float = -math.inf
    first_at: datetime | None = None
    last_at: datetime | None = None

    def add(self, ts: datetime, value: float | None) -> None:
        ts = to_db(ts)
        self.count += 1
        self.first_at = ts if self.first_at is None or ts < self.first_at else self.first_at
        self.last_at = ts if self.last_at is None or ts > self.last_at else self.last_at
        key = int((ts - _EPOCH).total_seconds() // self.bucket_seconds) * self.bucket_seconds
        b = self.buckets.setdefault(key, _Bucket())
        if value is None or not math.isfinite(value):
            self.missing += 1
            b.missing += 1
            return
        self.total += value
        self.lo, self.hi = min(self.lo, value), max(self.hi, value)
        b.n += 1
        b.total += value
        b.lo, b.hi = min(b.lo, value), max(b.hi, value)

    def points(self) -> list[dict]:
        out = []
        for key in sorted(self.buckets):
            b = self.buckets[key]
            out.append({
                "t": iso_z(_EPOCH + timedelta(seconds=key)),
                "avg": round(b.total / b.n, 4) if b.n else None,
                "min": b.lo if b.n else None, "max": b.hi if b.n else None,
                "count": b.n, "missing": b.missing,
            })
        return out

    def summary(self) -> dict:
        valued = self.count - self.missing
        return {
            "count": self.count, "missing": self.missing,
            "min": self.lo if valued else None, "max": self.hi if valued else None,
            "avg": round(self.total / valued, 4) if valued else None,
            "first_at": iso_z(self.first_at), "last_at": iso_z(self.last_at),
        }


def csv_safe(text) -> str:
    """Stop a spreadsheet from running a sensor name such as '=HYPERLINK(...)' as a formula."""
    s = "" if text is None else str(text)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
