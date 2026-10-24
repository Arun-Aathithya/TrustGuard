from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import schemas
from database.models import Machine, Prediction
from database.session import get_db

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("", response_model=list[schemas.PredictionOut])
def list_predictions(machine_id: int, limit: int = 50, db: Session = Depends(get_db)):
    machine = db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    stmt = (
        select(Prediction)
        .where(Prediction.machine_id == machine_id)
        .order_by(Prediction.created_at.desc())
        .limit(limit)
    )
    rows = list(db.execute(stmt).scalars())
    rows.reverse()
    return rows
