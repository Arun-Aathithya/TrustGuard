"""
Remove the demo fleet that older TrustGuard builds pre-loaded into an existing database.

New installs no longer create any machines, so this is only needed for a trustguard.db / PostgreSQL
database that was created by an earlier build (it holds the 5 demo machines and their simulated history).

    python purge_demo_data.py            # DRY RUN: only prints what would change
    python purge_demo_data.py --apply    # really delete (SQLite: a backup copy is made first)

What it touches (and nothing else):
  * Only machines whose name matches the old demo list below.
  * A demo machine with NO registered hardware sensor is deleted completely.
  * A demo machine that has a registered hardware sensor (e.g. your ESP32) is KEPT, together with its
    hardware sensors and their readings. Only its simulated sensors are removed, plus its predictions,
    alerts and maintenance tasks, because those were computed from a mix that included simulated data.
    They are regenerated from real readings as hardware data arrives.
Machines you created yourself under other names are never touched.
"""
import argparse
import shutil
import sys
from datetime import datetime

from sqlalchemy import update

from database.models import (
    Alert, IngestionEvent, Machine, Maintenance, Prediction, Sensor, SensorReading, SensorTrust,
)
from database.session import DATABASE_URL, SessionLocal, init_db

DEMO_MACHINE_NAMES = {
    "CNC Mill #1", "Hydraulic Press #2", "Conveyor Motor #3", "Industrial Pump #4", "Air Compressor #5",
}


def _delete_sensors(db, sensor_ids: list[int]) -> None:
    if not sensor_ids:
        return
    db.execute(update(IngestionEvent).where(IngestionEvent.sensor_id.in_(sensor_ids)).values(sensor_id=None))
    db.query(SensorReading).filter(SensorReading.sensor_id.in_(sensor_ids)).delete(synchronize_session=False)
    db.query(SensorTrust).filter(SensorTrust.sensor_id.in_(sensor_ids)).delete(synchronize_session=False)
    db.query(Sensor).filter(Sensor.id.in_(sensor_ids)).delete(synchronize_session=False)


def _delete_machine_analysis(db, machine_id: int) -> None:
    """Maintenance first (it points at alerts), then alerts, then predictions."""
    db.query(Maintenance).filter(Maintenance.machine_id == machine_id).delete(synchronize_session=False)
    db.query(Alert).filter(Alert.machine_id == machine_id).delete(synchronize_session=False)
    db.query(Prediction).filter(Prediction.machine_id == machine_id).delete(synchronize_session=False)


def plan(db) -> list[dict]:
    items = []
    for m in db.query(Machine).filter(Machine.name.in_(DEMO_MACHINE_NAMES)).order_by(Machine.id).all():
        hw = [s for s in m.sensors if s.data_source == "hardware"]
        sim = [s for s in m.sensors if s.data_source != "hardware"]
        n_sim_readings = (db.query(SensorReading).filter(SensorReading.sensor_id.in_([s.id for s in sim])).count() if sim else 0)
        items.append({"machine": m, "hardware": hw, "simulated": sim, "sim_readings": n_sim_readings,
                      "action": "keep (has hardware)" if hw else "delete"})
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually delete (default is a dry run)")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        items = plan(db)
        if not items:
            print("No old demo machines found. Nothing to do.")
            return 0
        print(f"Database: {DATABASE_URL.split('@')[-1]}")
        for it in items:
            m = it["machine"]
            print(f"- machine {m.id} '{m.name}': {it['action']}; {len(it['simulated'])} simulated sensor(s) "
                  f"({it['sim_readings']} readings) to remove; {len(it['hardware'])} hardware sensor(s) kept")
        if not args.apply:
            print("\nDry run only. Re-run with --apply to make these changes.")
            return 0

        if DATABASE_URL.startswith("sqlite:///"):
            path = DATABASE_URL.replace("sqlite:///", "", 1)
            backup = f"{path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            shutil.copy2(path, backup)
            print(f"\nBackup written: {backup}")
        else:
            print("\nNOTE: this is not a SQLite file, so no automatic backup was made. Back up your database first if unsure.")

        for it in items:
            m = it["machine"]
            _delete_sensors(db, [s.id for s in it["simulated"]])
            _delete_machine_analysis(db, m.id)
            if not it["hardware"]:
                db.query(Machine).filter(Machine.id == m.id).delete(synchronize_session=False)
        db.commit()
        print("Done.")
        return 0
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"Failed, nothing was changed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
