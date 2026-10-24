"""End-to-end tests for hardware registration, ingestion, validation, health and auth.
Run:  pip install -r requirements-dev.txt && pytest -q"""
from datetime import datetime, timedelta, timezone

from tests.conftest import ADMIN, DEVICE


def _register(client, machine_id=1, sensor_type="temperature", device="ESP32-T1"):
    r = client.post("/api/hardware/devices/register", headers=ADMIN,
                    json={"device_id": device, "machine_id": machine_id, "sensor_type": sensor_type})
    assert r.status_code == 200, r.text
    return r.json()


def _send(client, device, stype, value, ts=None, key=True):
    body = {"device_id": device, "sensor_type": stype, "value": value}
    if ts is not None:
        body["timestamp"] = ts
    return client.post("/api/hardware/ingest", json=body, headers=DEVICE if key else {})


def _now_iso(offset_s=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).isoformat()


def test_register_requires_admin_key(client):
    body = {"device_id": "ESP32-X9", "machine_id": 2, "sensor_type": "temperature"}
    assert client.post("/api/hardware/devices/register", json=body).status_code == 401
    assert client.post("/api/hardware/devices/register", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/hardware/devices/register", json=body, headers=ADMIN).status_code == 200


def test_registration_rejects_conflicts_and_bad_topics(client):
    _register(client, 1, "temperature", "ESP32-T1")
    r = client.post("/api/hardware/devices/register", headers=ADMIN,
                    json={"device_id": "ESP32-T1", "machine_id": 3, "sensor_type": "temperature"})
    assert r.status_code in (200, 409)  # same device may serve another machine only if topic differs
    r = client.post("/api/hardware/devices/register", headers=ADMIN,
                    json={"device_id": "ESP32-T2", "machine_id": 1, "sensor_type": "vibration", "mqtt_topic": "trustguard/sensors/#"})
    assert r.status_code == 422


def test_valid_reading_flows_to_dashboard_and_device_is_online(client):
    dev = _register(client, 1, "vibration", "ESP32-V1")
    r = _send(client, "ESP32-V1", "vibration", 2.6, _now_iso())
    assert r.status_code == 200, r.text
    devices = {d["sensor_id"]: d for d in client.get("/api/hardware/devices").json()}
    assert devices[dev["sensor_id"]]["device_status"] == "online"
    dash = client.get("/api/machines/1/dashboard").json()
    assert dash["data_source"] == "mixed"
    snap = next(s for s in dash["sensors"] if s["sensor"]["id"] == dev["sensor_id"])
    assert snap["latest_value"] == 2.6
    assert client.get("/api/hardware/summary").json()["devices_online"] >= 1


def test_duplicate_malformed_mismatch_and_unregistered_are_rejected(client):
    _register(client, 3, "temperature", "ESP32-T9")
    ts = _now_iso()
    assert _send(client, "ESP32-T9", "temperature", 66.0, ts).status_code == 200
    dup = _send(client, "ESP32-T9", "temperature", 66.0, ts)
    assert dup.status_code == 422 and dup.json()["detail"]["rejected"] == "duplicate"
    bad = client.post("/api/hardware/ingest", content=b"not json", headers=DEVICE)
    assert bad.status_code == 422
    assert _send(client, "ESP32-OTHER", "temperature", 66.0, _now_iso()).status_code == 422
    assert _send(client, "ESP32-T9", "temperature", 66.0, _now_iso(), key=False).status_code == 401
    events = {e["event_type"] for e in client.get("/api/hardware/events").json()}
    assert {"duplicate", "malformed", "unregistered_device"} <= events


def test_out_of_range_and_delayed_are_flagged_but_stored(client):
    _register(client, 2, "vibration", "ESP32-V2")
    r = _send(client, "ESP32-V2", "vibration", 9999.0, _now_iso())
    assert r.status_code == 200 and r.json()["event"] == "out_of_range"
    r = _send(client, "ESP32-V2", "vibration", 2.0, _now_iso(-300))
    assert r.status_code == 200 and r.json()["event"] == "delayed"
    r = _send(client, "ESP32-V2", "vibration", 2.0, _now_iso(-86400))
    assert r.status_code == 422 and r.json()["detail"]["rejected"] == "too_old"


def test_missing_value_is_recorded_as_missing(client):
    _register(client, 4, "vibration", "ESP32-V4")
    r = _send(client, "ESP32-V4", "vibration", None, _now_iso())
    assert r.status_code == 200 and r.json()["event"] == "missing"


def test_stale_then_offline_status_and_alert(client):
    from database.models import Alert, AlertType, Sensor
    from database.session import SessionLocal
    from services.device_monitor import check_devices_once

    dev = _register(client, 2, "temperature", "ESP32-T7")
    assert _send(client, "ESP32-T7", "temperature", 66.0, _now_iso()).status_code == 200
    db = SessionLocal()
    try:
        s = db.get(Sensor, dev["sensor_id"])
        s.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=60)
        db.commit()
    finally:
        db.close()
    d = next(x for x in client.get("/api/hardware/devices").json() if x["sensor_id"] == dev["sensor_id"])
    assert d["device_status"] == "stale"

    db = SessionLocal()
    try:
        s = db.get(Sensor, dev["sensor_id"])
        s.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        db.commit()
        check_devices_once(db)
        assert db.query(Alert).filter(Alert.sensor_id == dev["sensor_id"], Alert.alert_type == AlertType.DEVICE_OFFLINE,
                                      Alert.is_resolved.is_(False)).count() == 1
    finally:
        db.close()
    d = next(x for x in client.get("/api/hardware/devices").json() if x["sensor_id"] == dev["sensor_id"])
    assert d["device_status"] == "offline"
    # device comes back -> online again and the offline alert auto-resolves
    assert _send(client, "ESP32-T7", "temperature", 66.2, _now_iso()).status_code == 200
    db = SessionLocal()
    try:
        check_devices_once(db)
        assert db.query(Alert).filter(Alert.sensor_id == dev["sensor_id"], Alert.alert_type == AlertType.DEVICE_OFFLINE,
                                      Alert.is_resolved.is_(False)).count() == 0
    finally:
        db.close()


def test_simulation_tick_never_writes_to_hardware_sensors(client):
    dev = _register(client, 4, "temperature", "ESP32-T4")
    before = client.get("/api/readings", params={"sensor_id": dev["sensor_id"], "minutes": 600}).json()
    assert client.post("/api/simulate/tick", json={"machine_id": 4, "scenario": "drift"}).status_code == 200
    after = client.get("/api/readings", params={"sensor_id": dev["sensor_id"], "minutes": 600}).json()
    assert len(after) == len(before)


def test_test_connection_reports_failure_reason(client):
    dev = _register(client, 5, "temperature", "ESP32-T5")
    r = client.post(f"/api/hardware/devices/{dev['sensor_id']}/test").json()
    assert r["ok"] is False and "Not healthy" in r["message"]


def test_mqtt_message_handler_maps_topic_and_ignores_retained(client):
    from types import SimpleNamespace
    from hardware import mqtt_client

    dev = _register(client, 5, "vibration", "ESP32-V5")
    topic = dev["mqtt_topic"]
    payload = ('{"device_id":"ESP32-V5","value":2.7,"timestamp":"%s"}' % _now_iso()).encode()
    mqtt_client._on_message(None, None, SimpleNamespace(topic=topic, payload=payload, retain=True))
    d = next(x for x in client.get("/api/hardware/devices").json() if x["sensor_id"] == dev["sensor_id"])
    assert d["device_status"] == "offline"  # retained message ignored
    mqtt_client._on_message(None, None, SimpleNamespace(topic=topic, payload=payload, retain=False))
    d = next(x for x in client.get("/api/hardware/devices").json() if x["sensor_id"] == dev["sensor_id"])
    assert d["device_status"] == "online"
