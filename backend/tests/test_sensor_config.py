"""User-configurable sensors: only Temperature (DS18B20) and Vibration (MPU6050), custom names, persisted, removable."""
from datetime import datetime, timezone

import pytest

from tests.conftest import ADMIN, DEVICE


@pytest.fixture(scope="module")
def machine_id(client):
    r = client.post("/api/machines", json={"name": "Sensor-config machine"}, headers=ADMIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add(client, machine_id, stype="temperature", name="Motor bearing", **extra):
    return client.post("/api/sensors", headers=ADMIN, json={"machine_id": machine_id, "sensor_type": stype, "name": name, **extra})


def test_catalog_lists_exactly_two_types(client):
    types = client.get("/api/sensors/types").json()
    assert {t["value"] for t in types} == {"temperature", "vibration"}
    assert {t["hardware_model"] for t in types} == {"DS18B20", "MPU6050"}


def test_add_temperature_sensor_with_custom_name(client, machine_id):
    r = _add(client, machine_id, "temperature", "  Motor   bearing ")
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["name"] == "Motor bearing" and s["display_name"] == "Motor bearing"
    assert s["sensor_type"] == "temperature" and s["hardware_model"] == "DS18B20" and s["unit"] == "°C"
    assert s["data_source"] == "hardware" and s["device_id"] is None
    # nothing is invented for it: no reading, not online
    dash = client.get(f"/api/machines/{machine_id}/dashboard").json()
    snap = next(x for x in dash["sensors"] if x["sensor"]["id"] == s["id"])
    assert snap["latest_value"] is None and snap["sensor"]["device_status"] != "online"
    assert dash["latest_prediction"] is None


def test_add_vibration_sensor_and_multiple_of_a_type(client, machine_id):
    v = _add(client, machine_id, "vibration", "Gearbox vibration")
    assert v.status_code == 201 and v.json()["hardware_model"] == "MPU6050" and v.json()["unit"] == "m/s²"
    t2 = _add(client, machine_id, "temperature", "Housing temperature")
    assert t2.status_code == 201
    names = {s["name"] for s in client.get("/api/sensors", params={"machine_id": machine_id}).json()}
    assert {"Motor bearing", "Gearbox vibration", "Housing temperature"} <= names


@pytest.mark.parametrize("stype", ["pressure", "current", "rpm", "humidity", ""])
def test_unsupported_types_are_rejected(client, machine_id, stype):
    assert _add(client, machine_id, stype, f"bad {stype}").status_code == 422


def test_name_rules(client, machine_id):
    assert _add(client, machine_id, "temperature", "   ").status_code == 422
    assert _add(client, machine_id, "temperature", "x" * 61).status_code == 422
    assert _add(client, machine_id, "temperature", "motor BEARING").status_code == 409  # same name, different case
    assert _add(client, 999999, "temperature", "Nowhere").status_code == 404


def test_link_device_and_conflicts(client, machine_id):
    a = _add(client, machine_id, "temperature", "Linked temp", device_id="ESP32-CFG1")
    assert a.status_code == 201 and a.json()["device_id"] == "ESP32-CFG1"
    # one ESP32 may carry several sensors of the same type (e.g. two DS18B20 probes); each has its own MQTT topic
    second = _add(client, machine_id, "temperature", "Second temp same device", device_id="ESP32-CFG1")
    assert second.status_code == 201 and second.json()["mqtt_topic"] != a.json()["mqtt_topic"]
    assert _add(client, machine_id, "vibration", "Vib same device", device_id="ESP32-CFG1").status_code == 201
    assert _add(client, machine_id, "temperature", "Bad id", device_id="x").status_code == 422
    sid = a.json()["id"]
    r = client.patch(f"/api/sensors/{sid}", headers=ADMIN, json={"name": "Renamed temp"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed temp"
    assert client.patch(f"/api/sensors/{sid}", headers=ADMIN, json={"name": "Gearbox vibration"}).status_code == 409


def test_admin_key_is_required_to_change_sensors(client, machine_id):
    assert client.post("/api/sensors", json={"machine_id": machine_id, "sensor_type": "temperature", "name": "No key"}).status_code == 401


def test_configuration_is_stored_in_the_database(client, machine_id):
    """What the API lists comes from the database, so it is still there after a refresh or restart."""
    from database.models import Sensor
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(Sensor).filter(Sensor.machine_id == machine_id).all()
        assert {"Motor bearing", "Gearbox vibration"} <= {r.name for r in rows}
    finally:
        db.close()


def test_register_binds_a_waiting_sensor_instead_of_duplicating(client):
    mid = client.post("/api/machines", json={"name": "Bind machine"}, headers=ADMIN).json()["id"]
    sid = _add(client, mid, "temperature", "Waiting temp").json()["id"]
    r = client.post("/api/hardware/devices/register", headers=ADMIN, json={"device_id": "ESP32-BIND", "machine_id": mid, "sensor_type": "temperature"})
    assert r.status_code == 200 and r.json()["sensor_id"] == sid
    assert len(client.get("/api/sensors", params={"machine_id": mid}).json()) == 1
    bad = client.post("/api/hardware/devices/register", headers=ADMIN, json={"device_id": "ESP32-BIND2", "machine_id": mid, "sensor_type": "pressure"})
    assert bad.status_code == 422


def test_remove_sensor_deletes_it_and_its_history(client):
    mid = client.post("/api/machines", json={"name": "Removal machine"}, headers=ADMIN).json()["id"]
    sid = _add(client, mid, "temperature", "Short-lived", device_id="ESP32-RM1").json()["id"]
    body = {"device_id": "ESP32-RM1", "sensor_type": "temperature", "value": 41.5, "timestamp": datetime.now(timezone.utc).isoformat()}
    assert client.post("/api/hardware/ingest", json=body, headers=DEVICE).status_code == 200
    assert len(client.get("/api/readings", params={"sensor_id": sid, "minutes": 60}).json()) >= 1

    assert client.delete(f"/api/sensors/{sid}").status_code == 401
    assert client.delete(f"/api/sensors/{sid}", headers=ADMIN).status_code == 204
    assert client.get(f"/api/sensors/{sid}").status_code == 404
    assert client.get("/api/readings", params={"sensor_id": sid, "minutes": 60}).status_code == 404
    from database.models import SensorReading
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        assert db.query(SensorReading).filter(SensorReading.sensor_id == sid).count() == 0  # history removed with the sensor
    finally:
        db.close()
    dash = client.get(f"/api/machines/{mid}/dashboard").json()
    assert dash["sensors"] == [] and dash["latest_prediction"] is None
    assert client.delete(f"/api/sensors/{sid}", headers=ADMIN).status_code == 404
