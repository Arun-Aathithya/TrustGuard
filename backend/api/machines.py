from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import schemas
from database.models import Machine
from api.security import require_admin
from database.session import get_db
from services.dashboard_service import build_machine_dashboard

router = APIRouter(prefix="/api/machines", tags=["machines"])


@router.get("", response_model=list[schemas.MachineOut])
def list_machines(db: Session = Depends(get_db)):
    return db.query(Machine).order_by(Machine.id).all()


@router.post("", response_model=schemas.MachineOut, status_code=201, dependencies=[Depends(require_admin)])
def create_machine(payload: schemas.MachineCreate, db: Session = Depends(get_db)):
    machine = Machine(**payload.model_dump())
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine


@router.get("/{machine_id}", response_model=schemas.MachineOut)
def get_machine(machine_id: int, db: Session = Depends(get_db)):
    machine = db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    return machine


@router.get("/{machine_id}/dashboard", response_model=schemas.MachineDashboard)
def get_machine_dashboard(machine_id: int, db: Session = Depends(get_db)):
    machine = db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    return build_machine_dashboard(db, machine)


@router.get("/dashboard/all", response_model=list[schemas.MachineDashboard])
def get_all_dashboards(db: Session = Depends(get_db)):
    machines = db.query(Machine).order_by(Machine.id).all()
    return [build_machine_dashboard(db, m) for m in machines]


@router.delete("/{machine_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_machine(machine_id: int, db: Session = Depends(get_db)):
    machine = db.get(Machine, machine_id)
    if not machine:
        raise HTTPException(404, "Machine not found")
    db.delete(machine)
    db.commit()
