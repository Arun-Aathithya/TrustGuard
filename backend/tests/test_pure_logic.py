"""Dependency-free tests (stdlib only) for payload validation and device health."""
from datetime import datetime, timedelta, timezone

import pytest

from services.device_health import compute_status
from services.payload_validation import PayloadError, classify_timing, parse_payload


@pytest.mark.parametrize("raw", [b"\xff", b"nope", b"[1]", b'{"value":1}', b'{"device_id":"ESP32-A1"}',
                                 b'{"device_id":"ESP32-A1","value":"7"}', b'{"device_id":"ESP32-A1","value":true}',
                                 b'{"device_id":"ESP32-A1","value":NaN}', b'{"device_id":"ESP32-A1","value":1,"timestamp":"junk"}'])
def test_bad_payloads_rejected(raw):
    with pytest.raises(PayloadError):
        parse_payload(raw)


def test_good_payload_and_null_value():
    p = parse_payload(b'{"device_id":"ESP32-A1","value":71.4,"timestamp":"2026-10-18T12:00:00Z"}')
    assert p.value == 71.4 and p.timestamp.tzinfo is not None
    assert parse_payload({"device_id": "ESP32-A1", "value": None}).value is None


def test_unsynced_device_clock_is_flagged():
    p = parse_payload({"device_id": "ESP32-A1", "value": 1, "timestamp": 12345})
    assert p.timestamp is None and p.flags


def test_timing_classes():
    now = datetime.now(timezone.utc)
    got = [classify_timing(now - timedelta(seconds=s), now, delayed_after_s=30, max_age_s=3600, future_skew_s=60)[0] for s in (1, 45, 4000, -120)]
    assert got == ["ok", "delayed", "too_old", "future"]


def test_device_status_thresholds():
    n = datetime.now(timezone.utc)
    assert [compute_status("hardware", n - timedelta(seconds=s), n) for s in (5, 60, 500)] == ["online", "stale", "offline"]
    assert compute_status("hardware", None) == "offline"
    assert compute_status("simulation", n) == "simulated"


# ---------------- Phase 3: explanation + operating-band scaling ----------------
from recommendation.explain import build_explanation  # noqa: E402
from services.data_processing import normalize_operating  # noqa: E402


def _s(t, v, trust, issues=()):
    return {"sensor_type": t, "value": v, "unit": "", "trust": trust, "issues": list(issues), "device_status": "simulated"}


def test_machine_fault_vs_sensor_fault_are_separated():
    machine = build_explanation(failure_risk=89, prediction_confidence=90, cross_disagreement=False,
                                sensors=[_s("temperature", 95, 90), _s("vibration", 7, 92), _s("current", 18, 90)])
    assert machine["fault_class"] == "machine_fault_probable" and machine["urgency"] == "immediate"
    sensor = build_explanation(failure_risk=52, prediction_confidence=40, cross_disagreement=True,
                               sensors=[_s("temperature", 150, 30, ["drift", "disagrees_with_others"]), _s("vibration", 2.5, 95)])
    assert sensor["fault_class"] == "sensor_fault_suspected"
    assert sensor["contributors"][0]["sensor_type"] == "temperature"
    assert "check" in sensor["action"].lower() or "sensor" in sensor["action"].lower()


def test_normal_is_routine_and_never_claims_certainty():
    e = build_explanation(failure_risk=8, prediction_confidence=95, cross_disagreement=False,
                          sensors=[_s("temperature", 65, 95), _s("vibration", 2.5, 95)])
    assert e["fault_class"] == "none" and e["urgency"] == "routine"
    assert any("not been validated" in c for c in e["caveats"])  # accuracy caveat always shown


def test_operating_band_scaling():
    assert normalize_operating(65, "temperature") < 0.4 < normalize_operating(95, "temperature")
    assert normalize_operating(1e9, "rpm") == 1.0


# ---------------- calibration ----------------
def test_calibration_scale_offset_and_overrides(monkeypatch):
    from services.calibration import calibrate
    monkeypatch.setenv("SENSOR_CALIBRATION", '{"vibration": {"scale": 10}, "ESP32-A1:vibration": {"scale": 20, "offset": 1}}')
    assert calibrate("vibration", "OTHER", 0.25) == (2.5, True)
    assert calibrate("vibration", "ESP32-A1", 0.25) == (6.0, True)   # device key wins
    assert calibrate("temperature", "ESP32-A1", 66.0) == (66.0, False)
    assert calibrate("vibration", "OTHER", None) == (None, False)    # missing stays missing


def test_bad_calibration_config_is_ignored(monkeypatch):
    from services.calibration import calibrate
    for bad in ("not json", '{"vibration": {"scale": 0}}', '[1]'):
        monkeypatch.setenv("SENSOR_CALIBRATION", bad)
        assert calibrate("vibration", "X", 1.5) == (1.5, False)
