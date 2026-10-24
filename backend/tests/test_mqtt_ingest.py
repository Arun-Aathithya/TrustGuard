"""MQTT messages are matched to the right configured sensor, and bad messages never reach the database.
The broker itself is not needed: messages are handed to the same callback paho calls."""
import json
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tests.conftest import ADMIN, DEVICE


def _now():
    return datetime.now(timezone.utc).isoformat()


def _publish(topic, payload, retain=False):
    from hardware import mqtt_client

    raw = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode()
    mqtt_client._on_message(None, None, SimpleNamespace(topic=topic, payload=raw, retain=retain))


def _readings(client, sensor_id):
    return client.get("/api/readings", params={"sensor_id": sensor_id, "minutes": 60}).json()


def _events(client):
    return client.get("/api/hardware/events", params={"limit": 200}).json()


@pytest.fixture(scope="module")
def rig(client):
    """One machine, one ESP32 with two temperature probes and one vibration sensor, plus an unlinked sensor."""
    mid = client.post("/api/machines", json={"name": "MQTT rig"}, headers=ADMIN).json()["id"]

    def add(stype, name, device="ESP32-MQ1"):
        r = client.post("/api/sensors", headers=ADMIN, json={"machine_id": mid, "sensor_type": stype, "name": name, "device_id": device})
        assert r.status_code == 201, r.text
        return r.json()

    probe_a, probe_b, vib = add("temperature", "Probe A"), add("temperature", "Probe B"), add("vibration", "Vib")
    waiting = client.post("/api/sensors", headers=ADMIN, json={"machine_id": mid, "sensor_type": "temperature", "name": "Waiting"}).json()
    return SimpleNamespace(mid=mid, a=probe_a, b=probe_b, v=vib, waiting=waiting)


def test_each_message_lands_on_its_own_sensor(client, rig):
    _publish(rig.a["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": 40.0, "timestamp": _now()})
    _publish(rig.b["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": 50.0, "timestamp": _now()})
    _publish(rig.v["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": 0.31, "timestamp": _now(), "unit": "m/s²"})
    assert [r["value"] for r in _readings(client, rig.a["id"])] == [40.0]
    assert [r["value"] for r in _readings(client, rig.b["id"])] == [50.0]
    assert [r["value"] for r in _readings(client, rig.v["id"])] == [0.31]
    assert all(r["source"] == "hardware" for r in _readings(client, rig.a["id"]))
    snap = {s["sensor"]["id"]: s for s in client.get(f"/api/machines/{rig.mid}/dashboard").json()["sensors"]}
    assert snap[rig.a["id"]]["latest_value"] == 40.0 and snap[rig.b["id"]]["latest_value"] == 50.0
    assert snap[rig.a["id"]]["sensor"]["device_status"] == "online"


def test_bad_messages_do_not_create_readings(client, rig):
    before = {s["id"]: len(_readings(client, s["id"])) for s in (rig.a, rig.b, rig.v)}
    topic = rig.a["mqtt_topic"]
    for raw in (b"\xff\xfe\x00", b"not json", b"[]", b"null", b"{}", b'{"device_id":"ESP32-MQ1"}',
                b'{"device_id":"ESP32-MQ1","value":"21"}', b'{"device_id":"ESP32-MQ1","value":NaN}',
                b'{"device_id":"ESP32-MQ1","value":1,"pad":"' + b"a" * 3000 + b'"}'):
        _publish(topic, raw)
    _publish(topic, {"device_id": "ESP32-OTHER", "value": 41.0, "timestamp": _now()})                       # wrong device
    _publish(topic, {"device_id": "ESP32-MQ1", "value": 41.0, "sensor_id": rig.b["id"], "timestamp": _now()})  # wrong sensor id
    _publish(topic, {"device_id": "ESP32-MQ1", "value": 41.0, "sensor_type": "vibration", "timestamp": _now()})
    _publish(rig.v["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": 0.4, "unit": "mm/s", "timestamp": _now()})  # wrong unit
    _publish("trustguard/sensors/999/temperature/999", {"device_id": "ESP32-MQ1", "value": 1.0})              # no such sensor
    after = {s["id"]: len(_readings(client, s["id"])) for s in (rig.a, rig.b, rig.v)}
    assert after == before
    types_seen = {e["event_type"] for e in _events(client)}
    assert {"malformed", "invalid_value", "device_mismatch", "sensor_mismatch", "type_mismatch", "unit_mismatch", "unregistered_topic"} <= types_seen


def test_sensor_without_a_linked_device_rejects_messages_with_a_clear_reason(client, rig):
    _publish(rig.waiting["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": 22.0, "timestamp": _now()})
    assert _readings(client, rig.waiting["id"]) == []
    ev = next(e for e in _events(client) if e["event_type"] == "device_not_linked")
    assert "Device ID" in ev["detail"]


def test_duplicate_message_is_stored_once(client, rig):
    ts = _now()
    for _ in range(3):
        _publish(rig.b["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": 51.0, "timestamp": ts})
    assert [r["value"] for r in _readings(client, rig.b["id"])].count(51.0) == 1


def test_null_value_is_recorded_as_missing_not_as_a_number(client, rig):
    _publish(rig.a["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": None, "timestamp": _now()})
    last = _readings(client, rig.a["id"])[-1]
    assert last["value"] is None and last["is_missing"] is True


def test_retained_messages_are_ignored(client, rig):
    before = len(_readings(client, rig.a["id"]))
    _publish(rig.a["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": 99.0, "timestamp": _now()}, retain=True)
    assert len(_readings(client, rig.a["id"])) == before


def test_http_fallback_needs_sensor_id_when_a_device_has_two_sensors_of_one_type(client, rig):
    body = {"device_id": "ESP32-MQ1", "sensor_type": "temperature", "value": 42.0, "timestamp": _now()}
    r = client.post("/api/hardware/ingest", json=body, headers=DEVICE)
    assert r.status_code == 422 and r.json()["detail"]["rejected"] == "ambiguous_sensor"
    r = client.post("/api/hardware/ingest", json={**body, "sensor_id": rig.a["id"]}, headers=DEVICE)
    assert r.status_code == 200 and r.json()["sensor_id"] == rig.a["id"]


def test_flood_is_limited_and_counted(client, rig):
    from hardware import mqtt_client
    from hardware.mqtt_config import RateLimiter

    mqtt_client._limiter = RateLimiter(1, clock=lambda: 0.0)  # frozen clock: exactly one message allowed
    dropped_before = mqtt_client.broker_status()["messages_dropped"]
    try:
        for _ in range(5):
            _publish(rig.b["mqtt_topic"], {"device_id": "ESP32-MQ1", "value": 52.0, "timestamp": _now()})
    finally:
        mqtt_client._limiter = None
    assert mqtt_client.broker_status()["messages_dropped"] - dropped_before == 4


# ---- bridge lifecycle (a fake paho module stands in for the broker connection) -----------------------------------

class _RC:
    """Stand-in for paho's failing ReasonCode."""
    is_failure = True

    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


class _FakeClient:
    instances = []

    def __init__(self, *a, **k):
        self.kwargs, self.calls = k, []
        _FakeClient.instances.append(self)

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append((name, a, k))


@pytest.fixture
def fake_paho(monkeypatch):
    mqtt_pkg, client_mod = types.ModuleType("paho.mqtt"), types.ModuleType("paho.mqtt.client")
    client_mod.Client = _FakeClient
    client_mod.CallbackAPIVersion = SimpleNamespace(VERSION2=2)
    paho = types.ModuleType("paho")
    paho.mqtt, mqtt_pkg.client = mqtt_pkg, client_mod
    for name, mod in (("paho", paho), ("paho.mqtt", mqtt_pkg), ("paho.mqtt.client", client_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    _FakeClient.instances.clear()
    yield
    from hardware import mqtt_client

    mqtt_client.stop_mqtt_bridge()
    mqtt_client._config = mqtt_client._limiter = None
    mqtt_client._set(**mqtt_client._STATE_DEFAULTS)


def test_starting_twice_opens_only_one_connection_and_stop_closes_it(fake_paho):
    from hardware import mqtt_client

    env = {"MQTT_ENABLED": "true", "MQTT_BROKER_HOST": "broker.local", "MQTT_USERNAME": "u", "MQTT_PASSWORD": "p"}
    first = mqtt_client.start_mqtt_bridge(env)
    second = mqtt_client.start_mqtt_bridge(env)
    assert first is second and len(_FakeClient.instances) == 1
    names = [c[0] for c in first.calls]
    assert names.count("connect_async") == 1 and names.count("loop_start") == 1
    st = mqtt_client.broker_status()
    assert st["enabled"] and st["host"] == "broker.local" and st["port"] == 1883 and st["tls"] is False and st["authenticated"]
    assert "p" != st.get("password")  # the password is never exposed
    mqtt_client.stop_mqtt_bridge()
    assert [c[0] for c in first.calls][-2:] == ["loop_stop", "disconnect"]
    assert mqtt_client.broker_status()["connected"] is False
    mqtt_client.stop_mqtt_bridge()  # stopping twice is harmless


def test_tls_is_reported_only_when_it_was_really_set_up(fake_paho, tmp_path):
    from hardware import mqtt_client

    ca = tmp_path / "ca.crt"
    ca.write_text("pem")
    client = mqtt_client.start_mqtt_bridge({"MQTT_ENABLED": "true", "MQTT_TLS": "true", "MQTT_CA_CERTS": str(ca)})
    assert any(c[0] == "tls_set" for c in client.calls)
    assert mqtt_client.broker_status()["tls"] is True and mqtt_client.broker_status()["port"] == 8883


def test_bad_settings_do_not_crash_startup_and_are_reported(fake_paho):
    from hardware import mqtt_client

    assert mqtt_client.start_mqtt_bridge({"MQTT_ENABLED": "true", "MQTT_BROKER_PORT": "abc"}) is None
    assert "MQTT_BROKER_PORT" in mqtt_client.broker_status()["last_error"] and _FakeClient.instances == []
    assert mqtt_client.start_mqtt_bridge({"MQTT_ENABLED": "false"}) is None and _FakeClient.instances == []


def test_connection_loss_and_reconnect_are_tracked(fake_paho):
    from hardware import mqtt_client

    client = mqtt_client.start_mqtt_bridge({"MQTT_ENABLED": "true"})
    ok = SimpleNamespace(is_failure=False)
    mqtt_client._on_connect(client, None, {}, ok)
    assert mqtt_client.broker_status()["connected"] and ("subscribe", ("trustguard/sensors/#",), {"qos": 1}) in client.calls
    mqtt_client._on_disconnect(client, None, {}, _RC("Unspecified error"), None)
    st = mqtt_client.broker_status()
    assert not st["connected"] and st["disconnects"] == 1 and "reconnecting" in st["last_error"]
    mqtt_client._on_connect(client, None, {}, ok)  # the broker came back: subscribes again, error cleared
    assert mqtt_client.broker_status()["connected"] and mqtt_client.broker_status()["last_error"] is None
    assert [c[0] for c in client.calls].count("subscribe") == 2
    mqtt_client._on_connect(client, None, {}, _RC("Not authorized"))
    assert "MQTT_USERNAME" in mqtt_client.broker_status()["last_error"]
