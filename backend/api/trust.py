from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import schemas
from database.models import Sensor, SensorTrust
from database.session import get_db

router = APIRouter(prefix="/api/trust", tags=["trust"])


@router.get("", response_model=list[schemas.SensorTrustOut])
def list_trust_history(sensor_id: int, minutes: int = 120, db: Session = Depends(get_db)):
    sensor = db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    stmt = (
        select(SensorTrust)
        .where(SensorTrust.sensor_id == sensor_id, SensorTrust.computed_at >= since)
        .order_by(SensorTrust.computed_at.asc())
    )
    return list(db.execute(stmt).scalars())
