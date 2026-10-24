"""
Machine Failure Prediction — inference
=========================================
Loads the trained RandomForest model (if present) and turns current sensor
readings (NOT trust scores) into a Failure Risk percentage (0-100).

If no trained model exists yet (first run, before `python -m ml.train`),
falls back to a transparent weighted heuristic so the API never breaks.
"""
import os
import threading

import joblib

from ml.train import FEATURE_COLUMNS, FEATURE_VERSION, MODEL_PATH, MODEL_LABEL, train_and_save
from services.data_processing import normalize_operating as normalize

_lock = threading.Lock()
_cache = {"model": None, "loaded": False}


def _load_model():
    with _lock:
        if _cache["loaded"]:
            return _cache["model"]
        model = None
        try:
            if os.path.exists(MODEL_PATH):
                bundle = joblib.load(MODEL_PATH)
                if bundle.get("feature_version") == FEATURE_VERSION:
                    model = bundle["model"]
            if model is None:  # missing, stale feature scaling, or unreadable -> retrain (a few seconds)
                train_and_save()
                model = joblib.load(MODEL_PATH)["model"]
        except Exception:  # never let the model break the API; the heuristic is the safe fallback
            model = None
        _cache["model"] = model
        _cache["loaded"] = True
        return _cache["model"]


def _heuristic_risk(features: dict) -> float:
    """Transparent fallback used only if the model hasn't been trained yet."""
    stress = (
        0.30 * features["temperature_norm"]
        + 0.25 * features["vibration_norm"]
        + 0.15 * features["pressure_norm"]
        + 0.20 * features["current_norm"]
        + 0.10 * features["rpm_norm"]
    )
    risk = min(1.0, stress)
    return round(risk * 100, 2)


def build_features(latest_values: dict[str, float]) -> dict:
    """
    latest_values: e.g. {'temperature': 92.1, 'vibration': 2.4, ...} in the model's units.
    Sensor trust is intentionally NOT part of the features: risk must not move because a sensor is distrusted
    (that is what prediction confidence is for). A sensor with no usable value falls back to its healthy level,
    so it neither raises nor lowers risk; the confidence calculation is told about it separately.
    """
    return {
        "temperature_norm": normalize(latest_values.get("temperature", 65.0), "temperature"),
        "vibration_norm": normalize(latest_values.get("vibration", 2.5), "vibration"),
        "pressure_norm": normalize(latest_values.get("pressure", 100.0), "pressure"),
        "current_norm": normalize(latest_values.get("current", 12.0), "current"),
        "rpm_norm": normalize(latest_values.get("rpm", 1750.0), "rpm"),
    }


def predict_failure_risk(features: dict) -> tuple[float, str]:
    """
    Returns (failure_risk_percent, model_version_label).
    """
    model = _load_model()
    if model is None:
        return _heuristic_risk(features), "heuristic-fallback"

    ordered = [[features[col] for col in FEATURE_COLUMNS]]
    proba = model.predict_proba(ordered)[0][1]
    return round(float(proba) * 100, 2), MODEL_LABEL
