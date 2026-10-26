"""
Simulation control endpoints. Lets the frontend (or a cron/background job)
advance the simulated world by one "tick": every sensor on the target
machine(s) generates a new reading under the chosen scenario, which then
flows through the full ingestion + trust + ML + recommendation pipeline.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import schemas
from database.models import Machine
from database.session import get_db
from api.security import require_admin
from services.ingestion_service import ingest_reading, run_pipeline_for_machine
from simulation.simulator import BASELINES, SCENARIOS, simulator

router = APIRouter(prefix="/api/simulate", tags=["simulate"])
SENSOR_FAULT_SCENARIOS = {"noisy", "drift", "failure", "missing"}


@router.get("/scenarios")
def list_scenarios():
    return {
        "scenarios": SCENARIOS,
        "descriptions": {
            "normal": "Stable readings on every simulated sensor.",
            "noisy": "INJECTED sensor fault: extra noise on the temperature sensor only.",
            "drift": "INJECTED sensor fault: temperature sensor slowly drifts away from truth.",
            "failure": "INJECTED sensor fault: temperature sensor stuck / wildly wrong.",
            "missing": "INJECTED sensor fault: temperature sensor stops reporting.",
            "machine_fault": "SIMULATED machine problem: all sensors consistently show overheating, vibration and load.",
        },
    }


@router.post("/tick", response_model=list[schemas.MachineDashboard], dependencies=[Depends(require_admin)])
def run_tick(payload: schemas.SimulationTick, db: Session = Depends(get_db)):
    """One simulated tick. Sensor-fault scenarios hit the temperature sensor only; machine_fault hits all."""
    from services.dashboard_service import build_machine_dashboard

    if payload.scenario not in SCENARIOS:
        raise HTTPException(400, f"Unknown scenario '{payload.scenario}'. Valid: {SCENARIOS}")

    q = db.query(Machine)
    if payload.machine_id is not None:
        q = q.filter(Machine.id == payload.machine_id)
    machines = q.all()
    if not machines:
        raise HTTPException(404, "No matching machine(s) found")

    results = []
    for machine in machines:
        if not machine.sensors:
            continue  # nothing configured on this machine, so there is nothing to simulate
        machine_baseline = {t: BASELINES[t]["mean"] for t in BASELINES}
        for sensor in machine.sensors:
            if sensor.data_source == "hardware":
                continue  # simulation controls never touch real hardware sensors
            # Only the temperature sensor carries the "problem" scenario by
            # default so cross-sensor validation stays meaningful; other
            # sensors stay normal unless the whole machine is targeted with
            # a non-normal scenario explicitly.
            sensor_scenario = payload.scenario
            if sensor_scenario in SENSOR_FAULT_SCENARIOS and sensor.sensor_type.value != "temperature":
                sensor_scenario = "normal"  # inject the fault into ONE sensor so cross-sensor checks can work
            reading = simulator.generate(sensor.sensor_type.value, str(sensor.id), sensor_scenario)
            ingest_reading(db, sensor, reading.value, source="simulation")
        db.flush()
        run_pipeline_for_machine(db, machine, machine_baseline)
        db.commit()
        results.append(build_machine_dashboard(db, machine))

    if not results:
        raise HTTPException(409, "No sensors are configured on the selected machine(s), so there is nothing to simulate.")
    return results
