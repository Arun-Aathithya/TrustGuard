"""
Dependency-light tests (no web framework, no database) for the trust / risk / confidence separation,
cross-sensor verdicts and unit handling.
"""
from types import SimpleNamespace

import pytest

from ml.predictor import build_features, predict_failure_risk
from ml.train import FEATURE_COLUMNS
from prediction.confidence import compute_confidence
from recommendation.explain import build_explanation
from services.units import unit_assessment
from trust_engine.cross_sensor import validate
from trust_engine.trust_engine import apply_cross_sensor

HEALTHY = {"temperature": 65.0, "vibration": 2.5, "pressure": 100.0, "current": 12.0}


def row(**kw):
    base = dict(consistency_score=95.0, noise_score=95.0, drift_score=95.0, missing_score=100.0,
                cross_agreement_score=100.0, communication_score=100.0, trust_score=96.0)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------- risk, trust and confidence are independent ----------------
def test_trust_is_not_a_risk_model_input():
    assert not [c for c in FEATURE_COLUMNS if "trust" in c]
    assert not [k for k in build_features(HEALTHY) if "trust" in k]


def test_failure_risk_does_not_depend_on_trust():
    hot = dict(HEALTHY, temperature=95.0, vibration=6.0)
    # build_features no longer accepts trust at all, so the same readings must give the same risk, always.
    with pytest.raises(TypeError):
        build_features(hot, 20.0, 10.0)
    assert predict_failure_risk(build_features(hot)) == predict_failure_risk(build_features(dict(hot)))
    assert predict_failure_risk(build_features(hot))[0] > predict_failure_risk(build_features(HEALTHY))[0] + 20


def test_confidence_responds_to_trust_but_not_to_risk():
    good = compute_confidence(trust_scores=[95, 92], cross_sensor_disagreement=False)
    bad = compute_confidence(trust_scores=[95, 30], cross_sensor_disagreement=False)
    assert bad.prediction_confidence < good.prediction_confidence - 20
    # signature has no risk parameter: confidence cannot be a function of risk
    with pytest.raises(TypeError):
        compute_confidence(trust_scores=[95], cross_sensor_disagreement=False, failure_risk=80)


def test_conflict_and_excluded_sensors_lower_confidence_machine_change_does_not():
    base = compute_confidence(trust_scores=[90, 90, 90], cross_sensor_disagreement=False).prediction_confidence
    assert compute_confidence(trust_scores=[90, 90, 90], cross_sensor_disagreement=True, cross_verdict="ambiguous").prediction_confidence < base
    assert compute_confidence(trust_scores=[90, 90, 90], cross_sensor_disagreement=False, excluded_sensor_count=1).prediction_confidence < base
    assert compute_confidence(trust_scores=[90, 90, 90], cross_sensor_disagreement=False, cross_verdict="machine_change").prediction_confidence == base
    assert compute_confidence(trust_scores=[90], cross_sensor_disagreement=False, usable_sensor_count=0).prediction_confidence == 0.0


# ---------------- cross-sensor verdicts ----------------
def test_nothing_moved_is_agreement():
    assert validate(HEALTHY).verdict == "agree"


def test_other_sensors_also_moving_is_a_machine_change():
    r = validate(dict(HEALTHY, temperature=95.0, vibration=6.0))
    assert r.verdict == "machine_change" and not r.disagreement and r.suspect_sensor_types == []


def test_one_sensor_outvoted_by_two_or_more_is_the_suspect():
    r = validate(dict(HEALTHY, temperature=150.0))
    assert r.verdict == "sensor_suspect" and r.suspect_sensor_types == ["temperature"] and r.disagreement


def test_two_sensors_that_disagree_blame_nobody():
    r = validate({"temperature": 150.0, "vibration": 2.5})
    assert r.verdict == "ambiguous" and r.disagreement
    assert r.suspect_sensor_types == []
    assert "two sensors disagree; cannot tell which is wrong" in r.detail.lower()


def test_drift_of_two_sensors_together_counts_as_moved_together():
    r = validate(HEALTHY, drifting_types={"temperature", "current"})
    assert r.verdict == "machine_change"


def test_single_sensor_is_insufficient():
    assert validate({"temperature": 65.0}).verdict == "insufficient"
    assert validate({}).verdict == "insufficient"


# ---------------- trust adjustments follow the verdict ----------------
def test_machine_change_does_not_penalise_trust():
    rows = {"temperature": row(drift_score=10.0, cross_agreement_score=30.0, trust_score=60.0), "vibration": row(drift_score=20.0, trust_score=70.0)}
    changed = apply_cross_sensor(rows, "machine_change", ["temperature", "vibration"], [])
    assert set(changed) == {"temperature", "vibration"}
    assert rows["temperature"].drift_score == 100.0 and rows["temperature"].cross_agreement_score == 100.0
    assert rows["temperature"].trust_score > 90 and rows["vibration"].trust_score > 90


def test_only_the_outvoted_sensor_is_penalised():
    rows = {"temperature": row(), "vibration": row(), "current": row()}
    before = rows["vibration"].trust_score
    apply_cross_sensor(rows, "sensor_suspect", ["temperature"], ["temperature"])
    assert rows["temperature"].trust_score < 80 and rows["temperature"].cross_agreement_score == 30.0
    assert rows["vibration"].trust_score == before


def test_two_sensor_tie_changes_no_trust():
    rows = {"temperature": row(), "vibration": row()}
    assert apply_cross_sensor(rows, "ambiguous", ["temperature"], []) == {}
    assert rows["temperature"].trust_score == 96.0 and rows["temperature"].cross_agreement_score == 100.0


# ---------------- explanation wording ----------------
def _s(t, v, trust):
    return {"sensor_type": t, "value": v, "unit": "", "trust": trust, "issues": [], "device_status": "simulated"}


def test_explanation_for_two_sensor_disagreement_blames_nobody():
    e = build_explanation(failure_risk=55, prediction_confidence=40, cross_disagreement=True, cross_verdict="ambiguous",
                          unclear_types=["temperature", "vibration"], sensors=[_s("temperature", 150, 90), _s("vibration", 2.5, 92)])
    assert e["fault_class"] == "unclear"
    assert "cannot tell which is wrong" in e["headline"]
    assert all(c["role"] == "unclear" for c in e["contributors"])
    assert any("third sensor" in c for c in e["caveats"])


# ---------------- units ----------------
def test_simulated_and_non_vibration_sensors_are_unit_ok():
    assert unit_assessment("vibration", "simulation", "mm/s", None)["status"] == "ok"
    assert unit_assessment("temperature", "hardware", "°C", "ESP32-A1")["status"] == "ok"


def test_uncalibrated_acceleration_is_flagged_and_excluded(monkeypatch):
    monkeypatch.delenv("SENSOR_CALIBRATION", raising=False)
    a = unit_assessment("vibration", "hardware", "m/s²", "ESP32-A1")
    assert a["status"] == "unconverted" and a["warning"] and "mm/s" in a["warning"]
    assert unit_assessment("vibration", "hardware", "", "ESP32-A1")["status"] == "unconverted"  # unknown unit is not assumed fine


def test_calibrated_acceleration_is_an_index_not_mm_per_s(monkeypatch):
    monkeypatch.setenv("SENSOR_CALIBRATION", '{"ESP32-A1:vibration": {"scale": 8.0}}')
    a = unit_assessment("vibration", "hardware", "m/s²", "ESP32-A1")
    assert a["status"] == "calibrated_index" and a["display_unit"] == "idx" and a["warning"] is None
    assert unit_assessment("vibration", "hardware", "m/s²", "OTHER")["status"] == "unconverted"  # per-device


def test_real_velocity_sensor_in_mm_per_s_needs_no_calibration(monkeypatch):
    monkeypatch.delenv("SENSOR_CALIBRATION", raising=False)
    assert unit_assessment("vibration", "hardware", "mm/s", "VEL-1")["status"] == "ok"
