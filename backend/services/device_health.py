"""
Device health: Online / Stale / Offline from the server-side time of the last message.

  Online   - a message arrived within DEVICE_STALE_SECONDS      (default 30 s)
  Stale    - last message is older than that but within DEVICE_OFFLINE_SECONDS (default 120 s)
  Offline  - older than DEVICE_OFFLINE_SECONDS, or no message ever received
  Simulated - sensor is not registered to hardware (data comes from the simulator)
"""
import os
from datetime import datetime, timezone

ONLINE, STALE, OFFLINE, SIMULATED = "online", "stale", "offline", "simulated"


def stale_after_s() -> int:
    return int(os.getenv("DEVICE_STALE_SECONDS", "30"))


def offline_after_s() -> int:
    return int(os.getenv("DEVICE_OFFLINE_SECONDS", "120"))


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def seconds_since(last_seen: datetime | None, now: datetime | None = None) -> float | None:
    if last_seen is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (_aware(now) - _aware(last_seen)).total_seconds())


def compute_status(data_source: str | None, last_seen: datetime | None, now: datetime | None = None) -> str:
    if (data_source or "simulation") != "hardware":
        return SIMULATED
    age = seconds_since(last_seen, now)
    if age is None or age > offline_after_s():
        return OFFLINE
    if age > stale_after_s():
        return STALE
    return ONLINE
