"""PostgreSQL-specific checks. Skipped unless the suite runs against PostgreSQL:
    TEST_POSTGRES_URL=postgresql+psycopg2://user:pw@localhost:5432/trustguard_test pytest -q
(the conftest then points the whole suite at that database, so every other test also exercises PostgreSQL)."""
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="set TEST_POSTGRES_URL to run against PostgreSQL")


def test_running_on_postgresql_in_utc(client):
    from sqlalchemy import text
    from database.session import SessionLocal, engine

    assert engine.dialect.name == "postgresql"
    db = SessionLocal()
    try:
        assert db.execute(text("show timezone")).scalar().upper() in ("UTC", "ETC/UTC")
    finally:
        db.close()


def test_recent_timestamp_round_trips_without_a_time_shift(client):
    """A reading stamped 'now' must come back as ~now (not hours off) and be treated as recent by the trust window."""
    from database.models import Sensor, SensorReading
    from database.session import SessionLocal
    from services.ingestion_service import _recent_window, ingest_reading

    db = SessionLocal()
    try:
        sensor = db.query(Sensor).first()
        now = datetime.now(timezone.utc)
        ingest_reading(db, sensor, 65.0, now, source="simulation")
        db.commit()
        row = db.query(SensorReading).filter(SensorReading.sensor_id == sensor.id).order_by(SensorReading.id.desc()).first()
        stored = row.timestamp.replace(tzinfo=timezone.utc) if row.timestamp.tzinfo is None else row.timestamp
        assert abs((stored - now).total_seconds()) < 5
        assert any(r.id == row.id for r in _recent_window(db, sensor.id, source="simulation"))
    finally:
        db.close()


def test_full_pipeline_writes_prediction_with_cross_sensor_verdict(client):
    import json
    from database.models import Prediction

    assert client.post("/api/simulate/tick", json={"machine_id": 1, "scenario": "normal"}).status_code == 200
    from database.session import SessionLocal
    db = SessionLocal()
    try:
        p = db.query(Prediction).filter(Prediction.machine_id == 1).order_by(Prediction.id.desc()).first()
        inputs = json.loads(p.inputs_json)
        assert inputs["cross_sensor"]["verdict"] in ("agree", "machine_change", "sensor_suspect", "ambiguous", "insufficient")
        assert not [k for k in inputs["features"] if "trust" in k]  # trust is not a risk input
    finally:
        db.close()
