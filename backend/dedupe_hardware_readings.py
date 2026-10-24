"""
Find and remove duplicate hardware readings (same sensor, same timestamp) so the database's unique index can be built.
Only needed for a database from an older build that already contains such duplicates.

    python dedupe_hardware_readings.py           # dry run: prints what would be removed
    python dedupe_hardware_readings.py --apply   # remove (SQLite: a backup copy is written first)

For each duplicated (sensor, timestamp) the earliest stored reading is kept and the later copies are deleted.
"""
import argparse
import shutil
import sys
from datetime import datetime

from sqlalchemy import delete, func, select

from database.models import SensorReading
from database.session import DATABASE_URL, SessionLocal, init_db


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    init_db()
    db = SessionLocal()
    try:
        groups = db.execute(
            select(SensorReading.sensor_id, SensorReading.timestamp, func.min(SensorReading.id), func.count(SensorReading.id))
            .where(SensorReading.source == "hardware")
            .group_by(SensorReading.sensor_id, SensorReading.timestamp)
            .having(func.count(SensorReading.id) > 1)
        ).all()
        extra = sum(n - 1 for *_, n in groups)
        if not groups:
            print("No duplicate hardware readings found.")
            return 0
        print(f"{len(groups)} duplicated timestamps, {extra} surplus readings would be removed.")
        if not args.apply:
            print("Dry run only. Re-run with --apply to delete them.")
            return 0
        if DATABASE_URL.startswith("sqlite:///"):
            path = DATABASE_URL.replace("sqlite:///", "", 1)
            backup = f"{path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            shutil.copy2(path, backup)
            print(f"Backup written: {backup}")
        for sensor_id, ts, keep_id, _n in groups:
            db.execute(delete(SensorReading).where(
                SensorReading.sensor_id == sensor_id, SensorReading.timestamp == ts,
                SensorReading.source == "hardware", SensorReading.id != keep_id))
        db.commit()
        print("Done. Restart the backend so the unique index is created.")
        return 0
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"Failed, nothing was changed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
