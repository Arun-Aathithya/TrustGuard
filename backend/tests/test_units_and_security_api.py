"""API-level checks for unit handling, the structured security/setup issues and the cross-sensor fields."""
from datetime import datetime, timezone

from tests.conftest import ADMIN, DEVICE


def _register_vibration(client, device="ESP32-VU", machine_id=3, unit="m/s²"):
    r = client.post("/api/hardware/devices/register", headers=ADMIN,
                    json={"device_id": device, "machine_id": machine_id, "sensor_type": "vibration", "unit": unit})
    assert r.status_code == 200, r.text
    return r.json()


def test_uncalibrated_acceleration_sensor_is_flagged_everywhere(client, monkeypatch):
    monkeypatch.delenv("SENSOR_CALIBRATION", raising=False)
    dev = _register_vibration(client)
    assert dev["unit_status"] == "unconverted" and "mm/s" in dev["unit_warning"]
    body = {"device_id": "ESP32-VU", "sensor_type": "vibration", "value": 0.31, "timestamp": datetime.now(timezone.utc).isoformat()}
    assert client.post("/api/hardware/ingest", json=body, headers=DEVICE).status_code == 200
    dash = client.get("/api/machines/3/dashboard").json()
    snap = next(s for s in dash["sensors"] if s["sensor"]["id"] == dev["sensor_id"])
    assert snap["latest_value"] == 0.31  # the raw reading is still shown, honestly labelled
    assert snap["sensor"]["unit_status"] == "unconverted" and snap["sensor"]["display_unit"] == "m/s²"


def test_calibration_turns_it_into_an_index_not_mm_per_s(client, monkeypatch):
    monkeypatch.setenv("SENSOR_CALIBRATION", '{"ESP32-VU:vibration": {"scale": 8.0}}')
    dash = client.get("/api/machines/3/dashboard").json()
    sensor = next(s["sensor"] for s in dash["sensors"] if s["sensor"]["device_id"] == "ESP32-VU")
    assert sensor["unit_status"] == "calibrated_index" and sensor["display_unit"] == "idx" and sensor["unit_warning"] is None


def test_broker_endpoint_lists_structured_security_and_setup_issues(client):
    b = client.get("/api/hardware/broker").json()
    assert isinstance(b["security_issues"], list)
    kinds = {i["kind"] for i in b["security_issues"]}
    assert "setup" in kinds  # MQTT_ENABLED=false in the test environment
    assert all(i["message"] for i in b["security_issues"])
    assert set(b["security_warnings"]) <= {i["message"] for i in b["security_issues"]}  # old field still consistent


def test_dashboard_reports_a_cross_sensor_verdict(client):
    d = client.get("/api/machines/1/dashboard").json()
    assert d["cross_sensor_verdict"] in ("agree", "machine_change", "sensor_suspect", "ambiguous", "insufficient")
    assert isinstance(d["cross_sensor_moved"], list) and isinstance(d["cross_sensor_suspects"], list)
