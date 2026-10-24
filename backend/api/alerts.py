from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import schemas
from database.models import Alert
from api.security import require_admin
from database.session import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[schemas.AlertOut])
def list_alerts(machine_id: int | None = None, only_open: bool = False, db: Session = Depends(get_db)):
    q = db.query(Alert)
    if machine_id is not None:
        q = q.filter(Alert.machine_id == machine_id)
    if only_open:
        q = q.filter(Alert.is_resolved.is_(False))
    return q.order_by(Alert.created_at.desc()).limit(200).all()


@router.post("/{alert_id}/resolve", response_model=schemas.AlertOut, dependencies=[Depends(require_admin)])
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.is_resolved = True
    alert.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert
