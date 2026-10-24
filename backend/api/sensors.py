"""
Sensor configuration. Users add sensors here (through the website); only Temperature (DS18B20) and
Vibration (MPU6050) can be added. Configuration lives in the database, so it survives refreshes and restarts.

A newly added sensor is a *hardware* sensor that is waiting for its ESP32: it has no reading until a real
device reports, and nothing simulated is ever written to it.
"""
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from api.security import require_admin
from database import schemas
from database.models import (
    Alert, ConnectionStatus, IngestionEvent, Machine, Maintenance, Prediction, Sensor, SensorReading, SensorType,
)
from database.session import get_db
from services import sensor_catalog
from services.ingestion_service import run_pipeline_for_machine
from services.payload_validation import DEVICE_ID_RE
from simulation.simulator import BASELINES

logger = logging.getLogger("trustguard.sensors")
router = APIRouter(prefix="/api/sensors", tags=["sensors"])


def _clean_name(raw: str | None) -> str:
    name = " ".join((raw or "").split())  # trim and collapse whitespace
    if not name:
        raise HTTPException(422, "Give the sensor a name.")
    if len(name) > sensor_catalog.NAME_MAX_LENGTH:
        raise HTTPException(422, f"Sensor name is too long (max {sensor_catalog.NAME_MAX_LENGTH} characters).")
    if not name.isprintable():
        raise HTTPException(422, "Sensor name contains unsupported characters.")
    return name


def _ensure_name_free(machine: Machine, name: str, exclude_id: int | None = None) -> None:
    for s in machine.sensors:
        if s.id != exclude_id and (s.name or "").casefold() == name.casefold():
            raise HTTPException(409, f"This machine already has a sensor named '{s.name}'.")


def _clean_device_id(raw: str | None) -> str | None:
    device_id = (raw or "").strip()
    if not device_id:
        return None
    if not DEVICE_ID_RE.match(device_id):
        raise HTTPException(422, "device_id must be 3-80 characters: letters, digits, _ . -")
    return device_id


@router.get("", response_model=list[schemas.SensorOut])
def list_sensors(machine_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Sensor)
    if machine_id is not None:
        q = q.filter(Sensor.machine_id == machine_id)
    return q.order_by(Sensor.id).all()


@router.get("/types")
def list_supported_types():
    """The sensor types the website offers."""
    return [{"value": k, **v} for k, v in sensor_catalog.SUPPORTED_SENSORS.items()]


@router.post("", response_model=schemas.SensorOut, status_code=201, dependencies=[Depends(require_admin)])
def create_sensor(payload: schemas.SensorCreate, db: Session = Depends(get_db)):
    stype_raw = sensor_catalog.type_value(payload.sensor_type)
    if not sensor_catalog.is_supported(stype_raw):
        raise HTTPException(422, f"Unsupported sensor type '{payload.sensor_type}'. Supported: {sensor_catalog.supported_list()}.")
    machine = db.get(Machine, payload.machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    name = _clean_name(payload.name)
    _ensure_name_free(machine, name)
    stype = SensorType(stype_raw)
    device_id = _clean_device_id(payload.device_id)

    spec = sensor_catalog.SUPPORTED_SENSORS[stype_raw]
    sensor = Sensor(
        machine_id=machine.id, sensor_type=stype, name=name, hardware_model=spec["hardware_model"], unit=spec["unit"],
        device_id=device_id, data_source="hardware", connection_status=ConnectionStatus.OFFLINE,
        registered_at=datetime.now(timezone.utc),
    )
    db.add(sensor)
    db.flush()
    base = os.getenv("MQTT_BASE_TOPIC", "trustguard/sensors")
    sensor.mqtt_topic = f"{base}/{machine.id}/{stype_raw}/{sensor.id}"
    db.commit()
    db.refresh(sensor)
    logger.info("sensor %s '%s' (%s) added to machine %s", sensor.id, name, stype_raw, machine.id)
    return sensor


@router.get("/{sensor_id}", response_model=schemas.SensorOut)
def get_sensor(sensor_id: int, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    return sensor


@router.patch("/{sensor_id}", response_model=schemas.SensorOut, dependencies=[Depends(require_admin)])
def update_sensor(sensor_id: int, payload: schemas.SensorUpdate, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    if payload.name is not None:
        name = _clean_name(payload.name)
        _ensure_name_free(sensor.machine, name, exclude_id=sensor.id)
        sensor.name = name
    if payload.device_id is not None:
        device_id = _clean_device_id(payload.device_id)
        if device_id != sensor.device_id:
            sensor.device_id = device_id
            sensor.last_seen_at = None  # a different device has not reported yet
            sensor.data_source = "hardware"
    db.commit()
    db.refresh(sensor)
    return sensor


def _refresh_analysis(db: Session, machine_id: int) -> None:
    """After a sensor is removed: recompute from what is left, or clear results that no longer have any data."""
    machine = db.get(Machine, machine_id)
    if machine is None:
        return
    db.expire(machine)
    has_data = db.execute(
        select(SensorReading.id).join(Sensor, Sensor.id == SensorReading.sensor_id)
        .where(Sensor.machine_id == machine_id, SensorReading.value.is_not(None)).limit(1)
    ).first()
    if has_data:
        run_pipeline_for_machine(db, machine, {t: BASELINES[t]["mean"] for t in BASELINES})
    else:
        db.query(Prediction).filter(Prediction.machine_id == machine_id).delete(synchronize_session=False)
        db.execute(update(Alert).where(Alert.machine_id == machine_id, Alert.sensor_id.is_(None), Alert.is_resolved.is_(False))
                   .values(is_resolved=True, resolved_at=datetime.now(timezone.utc)))
    db.commit()


@router.delete("/{sensor_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_sensor(sensor_id: int, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    machine_id = sensor.machine_id
    # Alerts (and the maintenance tasks raised from them) that point at this sensor go with it.
    alert_ids = [a for (a,) in db.execute(select(Alert.id).where(Alert.sensor_id == sensor_id)).all()]
    if alert_ids:
        db.query(Maintenance).filter(Maintenance.alert_id.in_(alert_ids)).delete(synchronize_session=False)
        db.query(Alert).filter(Alert.id.in_(alert_ids)).delete(synchronize_session=False)
    db.execute(update(IngestionEvent).where(IngestionEvent.sensor_id == sensor_id).values(sensor_id=None))
    db.delete(sensor)  # readings and trust history cascade
    db.commit()
    logger.info("sensor %s removed from machine %s", sensor_id, machine_id)
    try:
        _refresh_analysis(db, machine_id)
    except Exception:  # noqa: BLE001 - the sensor is already gone; a failed recompute must not turn that into an error
        db.rollback()
        logger.exception("recomputing machine %s after removing sensor %s failed", machine_id, sensor_id)
