from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import schemas
from database.models import Maintenance
from api.security import require_admin
from database.session import get_db

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("", response_model=list[schemas.MaintenanceOut])
def list_maintenance(machine_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Maintenance)
    if machine_id is not None:
        q = q.filter(Maintenance.machine_id == machine_id)
    return q.order_by(Maintenance.created_at.desc()).limit(200).all()


@router.patch("/{maintenance_id}", response_model=schemas.MaintenanceOut, dependencies=[Depends(require_admin)])
def update_maintenance(maintenance_id: int, payload: schemas.MaintenanceUpdate, db: Session = Depends(get_db)):
    record = db.get(Maintenance, maintenance_id)
    if not record:
        raise HTTPException(404, "Maintenance record not found")
    record.status = payload.status
    if payload.scheduled_at:
        record.scheduled_at = payload.scheduled_at
    if payload.status == "completed":
        from datetime import datetime, timezone

        record.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return record
