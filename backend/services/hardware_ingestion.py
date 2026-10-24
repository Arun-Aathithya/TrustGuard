"""
Hardware ingestion - the single entry point for real device readings
(MQTT messages and the HTTP fallback both call process_hardware_message).

Pipeline per message:
  parse/validate payload -> resolve registered sensor (topic / device_id / type)
  -> timestamp checks (future / delayed / too old) -> duplicate check
  -> range check -> ingest_reading() -> full trust + prediction pipeline.

Every rejected or noteworthy message is written to `ingestion_events`
so problems are visible in the UI instead of being silently dropped.
"""
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import IngestionEvent, Sensor, SensorReading
from services.calibration import calibrate
from services.data_processing import HARD_RANGES
from services.ingestion_service import ingest_reading, run_pipeline_for_machine
from services.payload_validation import PayloadError, classify_timing, parse_payload, same_unit
from simulation.simulator import BASELINES

logger = logging.getLogger("trustguard.ingest")

_last_pipeline_run: dict[int, float] = {}
_pipeline_lock = threading.Lock()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class IngestResult:
    accepted: bool
    event_type: str  # accepted | delayed | missing | out_of_range | malformed | duplicate | ...
    detail: str = ""
    sensor_id: int | None = None
    reading_id: int | None = None


def log_event(db: Session, *, event_type: str, detail: str, channel: str, accepted: bool = False,
              sensor_id: int | None = None, device_id: str | None = None, topic: str | None = None) -> None:
    ev = IngestionEvent(sensor_id=sensor_id, device_id=(device_id or None) and device_id[:80], topic=(topic or None) and topic[:160],
                        channel=channel, event_type=event_type, accepted=accepted, detail=detail[:300])
    db.add(ev)
    db.flush()
    if ev.id % 500 == 0:  # simple retention: keep the newest ~5000 events
        db.execute(delete(IngestionEvent).where(IngestionEvent.id < ev.id - 5000))
    level = logging.INFO if accepted else logging.WARNING
    logger.log(level, "ingest %s [%s] sensor=%s device=%s topic=%s: %s", event_type, channel, sensor_id, device_id, topic, detail)


def _reject(db, result_type, detail, channel, **kw) -> IngestResult:
    log_event(db, event_type=result_type, detail=detail, channel=channel, accepted=False, **kw)
    db.commit()
    return IngestResult(False, result_type, detail, sensor_id=kw.get("sensor_id"))


def _find_sensor(db: Session, topic: str | None, parsed, channel: str):
    """
    Match a message to the user-configured sensor it belongs to. Returns (sensor, error_type, error_detail).

      MQTT: the topic identifies the sensor (each configured sensor has its own topic).
      HTTP: payload.sensor_id if given, else device_id + sensor_type (rejected when that is ambiguous).
    In both cases the payload's device_id (and sensor_id / sensor_type / unit, when present) must agree with the
    configuration, so a message can never be stored against the wrong sensor.
    """
    device_id, sensor_type = parsed.device_id, parsed.sensor_type
    if topic:
        sensor = db.execute(select(Sensor).where(Sensor.mqtt_topic == topic)).scalars().first()
        if sensor is None:
            return None, "unregistered_topic", f"no sensor is configured for topic {topic}"
    elif parsed.sensor_id is not None:
        sensor = db.get(Sensor, parsed.sensor_id)
        if sensor is None:
            return None, "unregistered_sensor", f"no sensor with id {parsed.sensor_id} is configured"
    else:
        if not sensor_type:
            return None, "malformed", "sensor_id or sensor_type is required for HTTP ingestion"
        matches = [s for s in db.execute(
            select(Sensor).where(Sensor.device_id == device_id, Sensor.data_source == "hardware")).scalars().all()
            if s.sensor_type.value == sensor_type]
        if not matches:
            return None, "unregistered_device", f"device {device_id} has no registered {sensor_type} sensor"
        if len(matches) > 1:
            return None, "ambiguous_sensor", (f"device {device_id} has {len(matches)} {sensor_type} sensors; "
                                              "send sensor_id (or publish to the sensor's own MQTT topic)")
        sensor = matches[0]
    if sensor.data_source != "hardware":
        return None, "not_registered_hardware", "sensor is not registered to a hardware device"
    if not sensor.device_id:
        return None, "device_not_linked", (f"sensor '{sensor.name or sensor.id}' has no device linked yet; "
                                           f"enter Device ID {device_id} for it on the dashboard")
    if sensor.device_id != device_id:
        return None, "device_mismatch", f"payload device_id '{device_id}' does not match the registered device for this sensor"
    if parsed.sensor_id is not None and parsed.sensor_id != sensor.id:
        return None, "sensor_mismatch", f"payload sensor_id {parsed.sensor_id} does not match the sensor for this topic ({sensor.id})"
    if sensor_type and sensor_type != sensor.sensor_type.value:
        return None, "type_mismatch", f"payload sensor_type '{sensor_type}' does not match registered '{sensor.sensor_type.value}'"
    if parsed.unit and sensor.unit and not same_unit(parsed.unit, sensor.unit):
        return None, "unit_mismatch", f"payload unit '{parsed.unit}' does not match the sensor's unit '{sensor.unit}'"
    return sensor, None, None


def _maybe_run_pipeline(db: Session, sensor: Sensor) -> None:
    min_interval = _env_float("PIPELINE_MIN_INTERVAL_SECONDS", 2.0)
    now = time.monotonic()
    with _pipeline_lock:
        if now - _last_pipeline_run.get(sensor.machine_id, 0.0) < min_interval:
            return
        _last_pipeline_run[sensor.machine_id] = now
    baseline = {t: BASELINES[t]["mean"] for t in BASELINES}
    run_pipeline_for_machine(db, sensor.machine, baseline)


def process_hardware_message(db: Session, *, channel: str, raw, topic: str | None = None) -> IngestResult:
    received_at = datetime.now(timezone.utc)
    ctx = {"topic": topic}

    try:
        parsed = parse_payload(raw)
    except PayloadError as exc:
        return _reject(db, exc.event_type, exc.detail, channel, **ctx)
    ctx["device_id"] = parsed.device_id

    sensor, err_type, err_detail = _find_sensor(db, topic, parsed, channel)
    if sensor is None:
        return _reject(db, err_type, err_detail, channel, **ctx)
    ctx["sensor_id"] = sensor.id

    notes = list(parsed.flags)
    ts = parsed.timestamp
    is_delayed = False
    if ts is None:
        ts = received_at
    else:
        status, ts = classify_timing(
            ts, received_at,
            delayed_after_s=_env_float("DELAYED_AFTER_SECONDS", 30),
            max_age_s=_env_float("MAX_READING_AGE_SECONDS", 3600),
            future_skew_s=_env_float("FUTURE_SKEW_SECONDS", 60),
        )
        if status == "too_old":
            return _reject(db, "too_old", "reading timestamp is older than the accepted maximum age", channel, **ctx)
        if status == "future":
            notes.append("timestamp_replaced: timestamp is in the future")
        if status == "delayed":
            is_delayed = True
            notes.append(f"delayed by {(received_at - ts).total_seconds():.0f}s")

    # Duplicate: same sensor + same measurement timestamp already stored (device retransmit / broker redelivery).
    if parsed.timestamp is not None and ts == parsed.timestamp:
        dup = db.execute(
            select(SensorReading.id).where(SensorReading.sensor_id == sensor.id, SensorReading.timestamp == ts,
                                           SensorReading.source == "hardware").limit(1)
        ).first()
        if dup:
            return _reject(db, "duplicate", f"a reading with timestamp {ts.isoformat()} already exists", channel, **ctx)

    # Calibrate device value onto the scale the trust/ML logic expects (no-op unless SENSOR_CALIBRATION is set).
    value, calibrated = calibrate(sensor.sensor_type.value, parsed.device_id, parsed.value)

    event_type = "accepted"
    if value is None:
        event_type = "missing"
        notes.append("device reported no value (sensor read failed)")
    else:
        lo, hi = HARD_RANGES.get(sensor.sensor_type.value, (float("-inf"), float("inf")))
        if value < lo or value > hi:
            event_type = "out_of_range"
            notes.append(f"value {value} outside physical range [{lo}, {hi}]")
    if is_delayed and event_type == "accepted":
        event_type = "delayed"

    try:
        reading = ingest_reading(db, sensor, value, ts, source="hardware", is_delayed=is_delayed, received_at=received_at)
        if calibrated:
            reading.raw_value = parsed.value  # keep what the device actually sent
        if event_type != "accepted" or notes:
            log_event(db, event_type=event_type, detail="; ".join(notes) or event_type, channel=channel, accepted=True, **ctx)
        _maybe_run_pipeline(db, sensor)
        db.commit()
    except IntegrityError:
        # The database's unique index caught a duplicate that the check above could not see (two identical messages
        # processed at the same moment). Nothing was stored for this one.
        db.rollback()
        return _reject(db, "duplicate", "a reading for this sensor and timestamp was stored at the same moment", channel, **ctx)
    except Exception:
        db.rollback()
        logger.exception("Pipeline failure while ingesting reading for sensor %s", sensor.id)
        return _reject(db, "internal_error", "server failed to process the reading", channel, **ctx)

    return IngestResult(True, event_type, "; ".join(notes), sensor_id=sensor.id, reading_id=reading.id)
