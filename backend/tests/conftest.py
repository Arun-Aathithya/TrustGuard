import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_tmp = tempfile.mkdtemp(prefix="tg_test_")
# TEST_POSTGRES_URL=postgresql+psycopg2://user:pw@host:5432/trustguard_test  runs the WHOLE suite on PostgreSQL
# (use a throw-away database: the tests create tables and data in it).
os.environ["DATABASE_URL"] = os.getenv("TEST_POSTGRES_URL") or f"sqlite:///{_tmp}/test.db"
os.environ["MQTT_ENABLED"] = "false"
os.environ["APP_ENV"] = "development"
os.environ["ADMIN_API_KEY"] = "test-admin"
os.environ["DEVICE_API_KEY"] = "test-device"

import pytest  # noqa: E402


# What the API returned right after a fresh startup, before any test data exists.
# tests/test_no_preset_fleet.py asserts the app starts completely empty.
STARTUP: dict = {}


def _create_test_machines(count: int = 5) -> None:
    """The app pre-loads nothing, so the tests create their own machines (ids 1..count on a fresh DB)."""
    from database.models import Machine, Sensor, SensorType
    from database.session import SessionLocal
    from simulation.simulator import BASELINES

    db = SessionLocal()
    try:
        for n in range(1, count + 1):
            m = Machine(name=f"Test Machine {n}", machine_type="test", location="pytest")
            db.add(m)
            db.flush()
            for stype in SensorType:
                db.add(Sensor(machine_id=m.id, sensor_type=stype, unit=BASELINES[stype.value]["unit"]))
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as c:
        STARTUP["machines"] = c.get("/api/machines").json()
        STARTUP["dashboards"] = c.get("/api/machines/dashboard/all").json()
        STARTUP["devices"] = c.get("/api/hardware/devices").json()
        STARTUP["hardware_summary"] = c.get("/api/hardware/summary").json()
        _create_test_machines()
        yield c


ADMIN = {"X-API-Key": "test-admin"}
DEVICE = {"X-Device-Key": "test-device"}
