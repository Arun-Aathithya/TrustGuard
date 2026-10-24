"""Pure tests (no database, no broker, no paho): MQTT settings validation, flood limiter, payload contract."""
import pytest

from hardware.mqtt_config import MqttConfigError, RateLimiter, is_enabled, load_config
from services.payload_validation import PayloadError, parse_payload, same_unit


def test_defaults_are_plain_local_broker():
    c = load_config({})
    assert (c.host, c.port, c.use_tls, c.base_topic, c.client_id) == ("localhost", 1883, False, "trustguard/sensors", "trustguard-backend")
    assert c.username == "" and c.max_messages_per_second == 100 and c.keepalive == 30


def test_tls_changes_default_port_and_is_reported_honestly():
    c = load_config({"MQTT_TLS": "true"})
    assert c.use_tls and c.port == 8883


def test_password_is_never_shown_in_repr():
    c = load_config({"MQTT_USERNAME": "u", "MQTT_PASSWORD": "s3cret-value"})
    assert "s3cret-value" not in repr(c)


@pytest.mark.parametrize("env", [
    {"MQTT_BROKER_PORT": "abc"}, {"MQTT_BROKER_PORT": "0"}, {"MQTT_BROKER_PORT": "70000"},
    {"MQTT_BROKER_HOST": "mqtt://broker"}, {"MQTT_BROKER_HOST": "bad host"},
    {"MQTT_TLS": "maybe"}, {"MQTT_BASE_TOPIC": "trustguard/#"}, {"MQTT_BASE_TOPIC": "/x"}, {"MQTT_BASE_TOPIC": "a//b"},
    {"MQTT_PASSWORD": "pw"},  # password without a username
    {"MQTT_KEEPALIVE_SECONDS": "1"},
])
def test_bad_settings_are_rejected_with_a_message(env):
    with pytest.raises(MqttConfigError):
        load_config(env)


def test_missing_ca_file_is_an_error_only_when_tls_is_on(tmp_path):
    missing = str(tmp_path / "nope.crt")
    with pytest.raises(MqttConfigError):
        load_config({"MQTT_TLS": "true", "MQTT_CA_CERTS": missing})
    c = load_config({"MQTT_TLS": "false", "MQTT_CA_CERTS": missing})
    assert not c.use_tls and any("NOT enabled" in w for w in c.warnings)
    ok = tmp_path / "ca.crt"
    ok.write_text("x")
    assert load_config({"MQTT_TLS": "true", "MQTT_CA_CERTS": str(ok)}).ca_certs == str(ok)


def test_port_and_tls_mismatch_warns():
    assert any("8883" in w for w in load_config({"MQTT_TLS": "false", "MQTT_BROKER_PORT": "8883"}).warnings)
    assert any("1883" in w for w in load_config({"MQTT_TLS": "true", "MQTT_BROKER_PORT": "1883"}).warnings)


def test_production_requires_tls_and_credentials_unless_explicitly_allowed():
    with pytest.raises(MqttConfigError):
        load_config({"APP_ENV": "production"})
    with pytest.raises(MqttConfigError):
        load_config({"APP_ENV": "production", "MQTT_TLS": "true"})
    assert load_config({"APP_ENV": "production", "MQTT_TLS": "true", "MQTT_USERNAME": "u", "MQTT_PASSWORD": "p"}).use_tls
    assert not load_config({"APP_ENV": "production", "ALLOW_INSECURE_MQTT": "true"}).use_tls


def test_enabled_flag():
    assert is_enabled({"MQTT_ENABLED": "true"}) and not is_enabled({}) and not is_enabled({"MQTT_ENABLED": "false"})
    with pytest.raises(MqttConfigError):
        is_enabled({"MQTT_ENABLED": "sure"})


def test_rate_limiter_allows_a_burst_then_refills():
    now = [0.0]
    rl = RateLimiter(5, clock=lambda: now[0])
    assert [rl.allow() for _ in range(7)] == [True] * 5 + [False] * 2
    now[0] += 0.4  # 2 tokens back
    assert [rl.allow() for _ in range(3)] == [True, True, False]
    assert all(RateLimiter(0).allow() for _ in range(1000))  # 0 = unlimited


def test_payload_contract_accepts_the_documented_message():
    p = parse_payload(b'{"device_id":"ESP32-A1","sensor_id":7,"sensor_type":"Temperature","unit":"\xc2\xb0C","value":21.5,"timestamp":"2026-10-18T12:00:00Z"}')
    assert (p.device_id, p.sensor_id, p.sensor_type, p.unit, p.value) == ("ESP32-A1", 7, "temperature", "°C", 21.5)
    assert p.timestamp is not None and p.flags == []
    assert parse_payload('{"device_id":"ESP32-A1","value":null}').value is None  # failed read = missing, not zero


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"\xff\xfe", b"[]", b"null", b'"text"', b"{}",
    b'{"device_id":"x","value":1}', b'{"device_id":"ESP32-A1"}', b'{"device_id":"ESP32-A1","value":"21"}',
    b'{"device_id":"ESP32-A1","value":true}', b'{"device_id":"ESP32-A1","value":1,"sensor_id":0}',
    b'{"device_id":"ESP32-A1","value":1,"sensor_id":"7"}', b'{"device_id":"ESP32-A1","value":1,"sensor_id":true}',
    b'{"device_id":"ESP32-A1","value":1,"unit":5}', b'{"device_id":"ESP32-A1","value":1,"timestamp":"yesterday"}',
    b'{"device_id":"ESP32-A1","value":NaN}', b'{"device_id":"ESP32-A1","value":Infinity}',
    b'{"device_id":"ESP32-A1","value":1,"pad":"' + b"a" * 3000 + b'"}',
])
def test_invalid_payloads_are_rejected(raw):
    with pytest.raises(PayloadError):
        parse_payload(raw)


def test_unit_comparison_ignores_notation():
    assert same_unit("m/s²", "m/s2") and same_unit("M/S^2", "m/s²") and same_unit("°C", "C") and same_unit("degC", "°C")
    assert not same_unit("mm/s", "m/s²") and not same_unit("°F", "°C")
