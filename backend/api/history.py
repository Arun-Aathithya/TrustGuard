"""
Historical readings API. Everything the dashboard needs to show "what happened before", from the database.

  GET /api/history/sensors               every configured sensor with its stored-reading count and first/last time
  GET /api/history/readings              pages of stored readings (filter: sensor, machine, time range, source)
  GET /api/history/sensors/{id}/series   min/avg/max per time bucket for a chart, plus a summary of the range
  GET /api/history/export.csv            the same filter as /readings, as a CSV download

Time filters (all endpoints):  start / end  = ISO-8601 (2026-10-24T12:00:00Z) or epoch seconds/ms,
                               range        = 15m | 1h | 6h | 24h | 7d | 30d | all   (default 24h; start wins over range)
Timestamps in responses are UTC with a trailing "Z". Each reading keeps its source ("hardware" or "simulation").
Readings are kept until their sensor (or machine) is removed.
"""
import csv
import io
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models import Machine, Sensor, SensorReading
from database.session import SessionLocal, get_db
from services import history_service as hs
from services import sensor_catalog

router = APIRouter(prefix="/api/history", tags=["history"])

MAX_PAGE = 5000
Source = Literal["hardware", "simulation"]


def _limit(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _window(start, end, range_):
    try:
        s, e = hs.resolve_window(start, end, range_, datetime.now(timezone.utc))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return s, e


def _sensor_label(sensor: Sensor) -> str:
    return sensor.name or sensor_catalog.default_label(sensor.sensor_type)


def _sensor_info(sensor: Sensor, machine_name: str | None = None) -> dict:
    return {
        "id": sensor.id, "machine_id": sensor.machine_id, "machine_name": machine_name,
        "name": _sensor_label(sensor), "sensor_type": sensor.sensor_type.value, "hardware_model": sensor.hardware_model,
        "unit": sensor.unit, "data_source": sensor.data_source, "device_id": sensor.device_id,
    }


def _conditions(sensor_ids, machine_id, start, end, source, include_missing):
    conds = [SensorReading.timestamp <= hs.to_db(end)]
    if start is not None:
        conds.append(SensorReading.timestamp >= hs.to_db(start))
    if sensor_ids:
        conds.append(SensorReading.sensor_id.in_(sensor_ids))
    if machine_id is not None:
        conds.append(Sensor.machine_id == machine_id)
    if source:
        conds.append(SensorReading.source == source)
    if not include_missing:
        conds.append(SensorReading.value.is_not(None))
    return conds


def _row(reading: SensorReading, sensor: Sensor) -> dict:
    return {
        "id": reading.id, "timestamp": hs.iso_z(reading.timestamp), "sensor_id": sensor.id,
        "sensor_name": _sensor_label(sensor), "sensor_type": sensor.sensor_type.value,
        "hardware_model": sensor.hardware_model, "unit": sensor.unit, "machine_id": sensor.machine_id,
        "value": reading.value, "raw_value": reading.raw_value, "is_missing": bool(reading.is_missing),
        "is_outlier": bool(reading.is_outlier), "is_delayed": bool(reading.is_delayed), "source": reading.source,
    }


@router.get("/sensors")
def history_sensors(machine_id: int | None = None, db: Session = Depends(get_db)):
    """Pick-list for a history view: every configured sensor, including ones with no readings yet."""
    stats = {
        sid: (n, first, last)
        for sid, n, first, last in db.execute(
            select(SensorReading.sensor_id, func.count(SensorReading.id), func.min(SensorReading.timestamp), func.max(SensorReading.timestamp))
            .group_by(SensorReading.sensor_id)
        ).all()
    }
    q = select(Sensor, Machine.name).join(Machine, Machine.id == Sensor.machine_id).order_by(Sensor.machine_id, Sensor.id)
    if machine_id is not None:
        q = q.where(Sensor.machine_id == machine_id)
    out = []
    for sensor, machine_name in db.execute(q).all():
        n, first, last = stats.get(sensor.id, (0, None, None))
        out.append({**_sensor_info(sensor, machine_name), "reading_count": n, "first_at": hs.iso_z(first), "last_at": hs.iso_z(last)})
    return out


@router.get("/readings")
def history_readings(
    sensor_id: list[int] | None = Query(None, description="repeat to include several sensors"),
    machine_id: int | None = None,
    start: str | None = None, end: str | None = None, range: str | None = None,
    source: Source | None = None,
    include_missing: bool = True,
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(500, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _window(start, end, range)
    if sensor_id:
        known = {s for (s,) in db.execute(select(Sensor.id).where(Sensor.id.in_(sensor_id))).all()}
        missing = sorted(set(sensor_id) - known)
        if missing:
            raise HTTPException(404, f"Sensor not found: {', '.join(map(str, missing))}")
    if machine_id is not None and not db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    conds = _conditions(sensor_id, machine_id, start_dt, end_dt, source, include_missing)
    base = select(SensorReading, Sensor).join(Sensor, Sensor.id == SensorReading.sensor_id).where(*conds)
    total = db.execute(select(func.count(SensorReading.id)).join(Sensor, Sensor.id == SensorReading.sensor_id).where(*conds)).scalar_one()
    direction = SensorReading.timestamp.asc() if order == "asc" else SensorReading.timestamp.desc()
    rows = db.execute(base.order_by(direction, SensorReading.id.asc() if order == "asc" else SensorReading.id.desc()).limit(limit).offset(offset)).all()
    return {
        "start": hs.iso_z(start_dt), "end": hs.iso_z(end_dt), "total": total, "limit": limit, "offset": offset,
        "has_more": offset + len(rows) < total, "items": [_row(r, s) for r, s in rows],
    }


@router.get("/sensors/{sensor_id}/series")
def history_series(
    sensor_id: int,
    start: str | None = None, end: str | None = None, range: str | None = None,
    source: Source | None = None,
    max_points: int = Query(300, ge=10, le=2000),
    db: Session = Depends(get_db),
):
    """Chart data: one point per time bucket (average, min, max, how many readings and how many were missing)."""
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    start_dt, end_dt = _window(start, end, range)
    if start_dt is None:  # range=all: begin at the first stored reading
        first = db.execute(select(func.min(SensorReading.timestamp)).where(SensorReading.sensor_id == sensor_id)).scalar_one()
        start_dt = first.replace(tzinfo=timezone.utc) if first else end_dt.replace(microsecond=0)
        if start_dt >= end_dt:
            start_dt = end_dt - timedelta(seconds=1)
    bucket = hs.choose_bucket_seconds((end_dt - start_dt).total_seconds(), max_points)
    agg = hs.SeriesAggregator(bucket)
    max_rows = _limit("HISTORY_SERIES_MAX_ROWS", 2_000_000)
    stmt = (
        select(SensorReading.timestamp, SensorReading.value)
        .where(*_conditions([sensor_id], None, start_dt, end_dt, source, True))
        .order_by(SensorReading.timestamp.asc())
        .execution_options(yield_per=5000)
    )
    for ts, value in db.execute(stmt):
        agg.add(ts, value)
        if agg.count > max_rows:
            raise HTTPException(422, f"That range holds more than {max_rows} readings; choose a shorter range.")
    return {
        "sensor": _sensor_info(sensor), "start": hs.iso_z(start_dt), "end": hs.iso_z(end_dt),
        "bucket_seconds": bucket, "source": source, "summary": agg.summary(), "points": agg.points(),
    }


@router.get("/export.csv")
def history_export(
    sensor_id: list[int] | None = Query(None),
    machine_id: int | None = None,
    start: str | None = None, end: str | None = None, range: str | None = None,
    source: Source | None = None,
    include_missing: bool = True,
    db: Session = Depends(get_db),
):
    start_dt, end_dt = _window(start, end, range)
    conds = _conditions(sensor_id, machine_id, start_dt, end_dt, source, include_missing)
    total = db.execute(select(func.count(SensorReading.id)).join(Sensor, Sensor.id == SensorReading.sensor_id).where(*conds)).scalar_one()
    max_rows = _limit("HISTORY_EXPORT_MAX_ROWS", 500_000)
    if total > max_rows:
        raise HTTPException(422, f"{total} readings match; the export limit is {max_rows}. Choose a shorter range or one sensor.")

    def generate():
        # Its own session: the request's dependency session may already be closed while the file streams out.
        session = SessionLocal()
        try:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["timestamp_utc", "sensor_id", "sensor_name", "sensor_type", "unit", "machine_id", "value",
                             "is_missing", "is_outlier", "is_delayed", "source"])
            yield buf.getvalue()
            stmt = (select(SensorReading, Sensor).join(Sensor, Sensor.id == SensorReading.sensor_id).where(*conds)
                    .order_by(SensorReading.timestamp.asc(), SensorReading.id.asc()).execution_options(yield_per=5000))
            for reading, sensor in session.execute(stmt):
                buf.seek(0); buf.truncate()
                writer.writerow([hs.iso_z(reading.timestamp), sensor.id, hs.csv_safe(_sensor_label(sensor)), sensor.sensor_type.value,
                                 hs.csv_safe(sensor.unit), sensor.machine_id, "" if reading.value is None else reading.value,
                                 int(bool(reading.is_missing)), int(bool(reading.is_outlier)), int(bool(reading.is_delayed)), reading.source])
                yield buf.getvalue()
        finally:
            session.close()

    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="trustguard_history.csv"'})
