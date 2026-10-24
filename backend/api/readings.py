from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import schemas
from database.models import Sensor, SensorReading
from api.security import require_admin
from database.session import get_db

router = APIRouter(prefix="/api/readings", tags=["readings"])


@router.get("", response_model=list[schemas.SensorReadingOut])
def list_readings(sensor_id: int, minutes: int = 60, source: str | None = None, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    stmt = (
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor_id, SensorReading.timestamp >= since)
        .order_by(SensorReading.timestamp.asc())
    )
    if source:
        stmt = stmt.where(SensorReading.source == source)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=schemas.SensorReadingOut, status_code=201, dependencies=[Depends(require_admin)])
def create_reading(payload: schemas.SensorReadingCreate, db: Session = Depends(get_db)):
    """Manual test-data ingestion (admin only). Real hardware must use /api/hardware/ingest or MQTT."""
    from services.ingestion_service import ingest_reading

    sensor = db.get(Sensor, payload.sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    if sensor.data_source == "hardware":
        raise HTTPException(409, "This sensor is registered to hardware; send data via MQTT or /api/hardware/ingest.")
    reading = ingest_reading(db, sensor, payload.value, payload.timestamp, source="simulation")
    db.commit()
    db.refresh(reading)
    return reading
