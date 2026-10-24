"""
Explainable recommendation
============================
Builds a plain-language explanation for one machine from numbers the pipeline already has.
It keeps three things apart (never merged into one score):
  * sensor trust       - is the DATA reliable?
  * failure risk       - how likely is a machine problem?
  * prediction confidence - how much should we rely on that risk figure?

It separates *suspected sensor faults* from *probable machine faults* and words everything as
evidence ("suggests", "may"), never as certainty. Pure Python, no database access.
"""
from recommendation.recommender import recommend
from services.data_processing import SOFT_STATS

LABELS = {"temperature": "Temperature", "vibration": "Vibration / accelerometer", "pressure": "Pressure", "current": "Current", "rpm": "RPM"}
FAULT_LABELS = {
    "none": "No fault indicated",
    "sensor_fault_suspected": "Suspected sensor fault",
    "machine_fault_probable": "Probable machine fault",
    "both": "Possible machine fault AND suspected sensor fault",
    "unclear": "Sensors disagree: cannot tell which is wrong",
}
URGENCY_LABELS = {"routine": "Routine - no action needed", "soon": "Soon - plan action this shift or day", "immediate": "Immediate - inspect now"}
SUSPECT_TRUST = 60.0


def _z(sensor_type: str, value):
    st = SOFT_STATS.get(sensor_type)
    if value is None or not st or not st["std"]:
        return None
    return (value - st["mean"]) / st["std"]


def sensor_issues(trust: dict | None, device_status: str | None, connection_status: str | None, unit_status: str | None = None) -> list[str]:
    """Data-quality problems for one sensor, as short keys."""
    out = []
    if device_status == "offline":
        out.append("offline")
    elif device_status == "stale":
        out.append("stale")
    if connection_status == "faulty":
        out.append("suspicious_value")
    if unit_status == "unconverted":
        out.append("unit_mismatch")
    if trust:
        for key, name in (("missing_score", "missing_readings"), ("drift_score", "drift"), ("noise_score", "noise"), ("cross_agreement_score", "disagrees_with_others")):
            if trust.get(key, 100) < 70:
                out.append(name)
    return out


ISSUE_TEXT = {
    "offline": "device is offline", "stale": "data is stale", "suspicious_value": "reported a suspicious value",
    "missing_readings": "has missing readings", "drift": "shows drift", "noise": "is unusually noisy",
    "disagrees_with_others": "disagrees with the other sensors",
    "unit_mismatch": "reports in units the model cannot use yet (not calibrated), so it is left out of the risk estimate",
}


def build_explanation(*, failure_risk, prediction_confidence, sensors: list[dict], cross_disagreement: bool,
                      data_source: str = "simulation", model_version: str | None = None,
                      cross_verdict: str | None = None, unclear_types: list[str] | None = None) -> dict:
    """
    sensors: [{sensor_type, value, unit, trust (0-100 or None), issues: [...], device_status, data_source}]
    """
    trusts = [s["trust"] for s in sensors if s.get("trust") is not None]
    min_trust = min(trusts) if trusts else 100.0
    rec = recommend(failure_risk=failure_risk, prediction_confidence=prediction_confidence,
                    min_sensor_trust=min_trust, cross_sensor_disagreement=cross_disagreement, cross_verdict=cross_verdict)
    unclear = set(unclear_types or []) if cross_verdict == "ambiguous" else set()
    high_risk = failure_risk >= 60
    low_conf = prediction_confidence < 55

    contributors, suspects, signals = [], [], []
    for s in sensors:
        name = LABELS.get(s["sensor_type"], s["sensor_type"])
        z = _z(s["sensor_type"], s.get("value"))
        trust = s.get("trust")
        issues = s.get("issues", [])
        is_suspect = bool(issues and (trust is None or trust < SUSPECT_TRUST or any(i in issues for i in ("offline", "stale", "suspicious_value", "disagrees_with_others", "unit_mismatch")))) \
            or (trust is not None and trust < SUSPECT_TRUST)
        abnormal = z is not None and abs(z) >= 2
        if s["sensor_type"] in unclear:
            # Two sensors, one moved: there is no majority, so neither is blamed and neither is trusted as "the machine".
            contributors.append({"sensor_type": s["sensor_type"], "name": name, "role": "unclear", "trust": trust,
                                 "note": "This sensor and the other one disagree; it cannot be told which of the two is wrong."})
            continue
        if is_suspect:
            why = ", ".join(ISSUE_TEXT.get(i, i) for i in issues) or "low data reliability"
            note = f"Data from this sensor may be unreliable ({why})" + (f"; trust {trust:.0f}%." if trust is not None else ".")
            suspects.append(s["sensor_type"])
            contributors.append({"sensor_type": s["sensor_type"], "name": name, "role": "sensor_suspect", "trust": trust, "note": note})
        elif abnormal:
            direction = "above" if z > 0 else "below"
            val = f"{s['value']:.1f} {s.get('unit', '')}".strip()
            note = f"{val} is about {abs(z):.1f}σ {direction} its normal operating level, and the sensor itself looks reliable (trust {trust:.0f}%)." if trust is not None else f"{val} is {abs(z):.1f}σ {direction} normal."
            signals.append(s["sensor_type"])
            contributors.append({"sensor_type": s["sensor_type"], "name": name, "role": "machine_signal", "trust": trust, "note": note})
        else:
            contributors.append({"sensor_type": s["sensor_type"], "name": name, "role": "ok", "trust": trust,
                                 "note": "Reading within normal range." if s.get("value") is not None else "No recent reading."})
    order = {"sensor_suspect": 0, "unclear": 0, "machine_signal": 1, "ok": 2}
    contributors.sort(key=lambda c: (order[c["role"]], c["trust"] if c["trust"] is not None else 0))

    if unclear:
        fault_class = "unclear"
    elif suspects and signals:
        fault_class = "both"
    elif suspects:
        fault_class = "sensor_fault_suspected"
    elif high_risk and signals and not low_conf:
        fault_class = "machine_fault_probable"
    else:
        fault_class = "none"

    action, severity = rec.action, rec.severity
    if fault_class in ("sensor_fault_suspected", "both") and rec.recommendation_type == "monitor":
        action, severity = "Check the flagged sensor, then keep monitoring", "warning"
    if fault_class == "unclear":
        action, severity = "Check both sensors by hand (or add a third sensor) before acting on the risk figure", "warning"

    # --- urgency ---
    if fault_class == "machine_fault_probable" and failure_risk >= 80:
        urgency = "immediate"
    elif fault_class in ("machine_fault_probable", "both", "sensor_fault_suspected", "unclear") or high_risk or min_trust < 50:
        urgency = "soon"
    else:
        urgency = "routine"

    # --- why risk / why confidence (hedged wording) ---
    sig_names = [LABELS.get(t, t) for t in signals]
    if high_risk:
        why_risk = f"Failure risk is {failure_risk:.0f}%. " + (
            f"Raised mainly by: {', '.join(sig_names)}. These readings suggest a machine problem, but this is an estimate, not a confirmed fault."
            if sig_names else "No single reliable sensor stands out, so treat this figure cautiously.")
    elif failure_risk >= 35:
        why_risk = f"Failure risk is moderate ({failure_risk:.0f}%)." + (f" Slightly elevated: {', '.join(sig_names)}." if sig_names else "")
    else:
        why_risk = f"Failure risk is low ({failure_risk:.0f}%); readings are close to normal operation."

    sus_names = [LABELS.get(t, t) for t in suspects]
    if low_conf:
        why_confidence = f"Prediction confidence is only {prediction_confidence:.0f}% because " + (
            f"data from {', '.join(sus_names)} looks unreliable" if sus_names else "overall sensor trust is low") + \
            (" and sensors disagree with each other" if cross_disagreement else "") + ". The risk figure may be wrong in either direction."
    elif prediction_confidence < 75:
        why_confidence = f"Confidence is moderate ({prediction_confidence:.0f}%); some sensor data quality is imperfect."
    else:
        why_confidence = f"Confidence is {prediction_confidence:.0f}%: sensor data looks consistent. That says the data is reliable, not that the model is certain."

    # --- headline in careful language ---
    headline = {
        "machine_fault_probable": "Several reliable sensors point to a possible machine problem.",
        "sensor_fault_suspected": "A sensor may be faulty; check it before acting on the risk figure.",
        "both": "Signs of a machine problem, and at least one sensor is unreliable.",
        "none": "No fault indicated by the current data.",
        "unclear": "The two sensors disagree; cannot tell which is wrong.",
    }[fault_class]
    if cross_verdict == "machine_change" and fault_class != "unclear":
        headline += " Several sensors moved together, which points to a change in the machine or process rather than a sensor fault."

    caveats = []
    if fault_class == "unclear":
        caveats.append("Only two sensors report on this machine, so there is no majority to decide which one is wrong. Add a third sensor (for example current or a second temperature probe) to break the tie.")
    if any(s.get("device_status") in ("stale", "offline") for s in sensors):
        caveats.append("Some hardware data is stale or offline, so these scores may reflect old readings.")
    if data_source != "hardware":
        caveats.append("Data shown is simulated" + (" (mixed with hardware)" if data_source == "mixed" else "") + "; injected faults are artificial and do not prove real-sensor fault detection.")
    caveats.append("Failure risk comes from a model trained on synthetic data and has not been validated against labelled real failures. Use it as a decision aid, not a guarantee.")
    if model_version == "heuristic-fallback":
        caveats.append("The trained model is unavailable; a simple rule-based estimate is in use.")

    return {
        "fault_class": fault_class, "fault_label": FAULT_LABELS[fault_class],
        "urgency": urgency, "urgency_label": URGENCY_LABELS[urgency],
        "action": action, "severity": severity, "headline": headline,
        "why_risk": why_risk, "why_confidence": why_confidence,
        "contributors": contributors, "caveats": caveats, "reasoning": rec.reasoning,
    }
