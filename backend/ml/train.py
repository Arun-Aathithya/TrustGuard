"""
Machine Failure Prediction — model training
=============================================
Trains a RandomForestClassifier that outputs a failure probability (0-1,
displayed as Failure Risk %) from sensor readings only (not trust scores).

Since real historical failure data doesn't exist yet for a new deployment,
this script bootstraps a synthetic-but-physically-reasonable dataset:
higher temperature/vibration/current => higher failure
probability, with noise so the model isn't a trivial linear rule.

Run directly:  python -m ml.train
Produces:      ml_models/failure_model.joblib
"""
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

FEATURE_COLUMNS = [
    "temperature_norm",
    "vibration_norm",
    "pressure_norm",
    "current_norm",
    "rpm_norm",
]  # process readings only. Sensor trust must NOT be a feature: it belongs to prediction confidence.

FEATURE_VERSION = 3  # 3 = trust removed from the inputs (2 = operating-band scaling, 1 = hard-limit scaling)
MODEL_LABEL = "rf-v3"
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "ml_models", "failure_model.joblib")


def _synthesize_dataset(n_samples: int = 6000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    temperature_norm = rng.beta(2, 3, n_samples)
    vibration_norm = rng.beta(2, 3, n_samples)
    pressure_norm = rng.beta(2, 4, n_samples)
    current_norm = rng.beta(2, 3, n_samples)
    rpm_norm = rng.beta(2, 4, n_samples)

    # Physically-motivated "true" risk score (0-1) before noise/labeling.
    stress = (
        0.30 * temperature_norm
        + 0.25 * vibration_norm
        + 0.15 * pressure_norm
        + 0.20 * current_norm
        + 0.10 * rpm_norm
    )
    true_risk = np.clip(stress, 0, 1)

    # Label as a noisy threshold around 0.5 rather than a pure Bernoulli draw:
    # this keeps some realistic randomness at the boundary while still giving
    # the model a learnable signal (a pure Bernoulli(true_risk) draw caps
    # achievable accuracy far below what's useful for a demo).
    noisy_risk = np.clip(true_risk + rng.normal(0, 0.08, n_samples), 0, 1)
    labels = (noisy_risk > 0.5).astype(int)

    df = pd.DataFrame(
        {
            "temperature_norm": temperature_norm,
            "vibration_norm": vibration_norm,
            "pressure_norm": pressure_norm,
            "current_norm": current_norm,
            "rpm_norm": rpm_norm,
            "failure": labels,
        }
    )
    return df


def train_and_save(n_samples: int = 6000):
    df = _synthesize_dataset(n_samples)
    X = df[FEATURE_COLUMNS]
    y = df["failure"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=5,
        random_state=42,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    proba = model.predict_proba(X_test)[:, 1]
    acc = accuracy_score(y_test, preds)
    try:
        auc = roc_auc_score(y_test, proba)
    except ValueError:
        auc = float("nan")

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump({"model": model, "features": FEATURE_COLUMNS, "feature_version": FEATURE_VERSION}, MODEL_PATH)

    print(f"Trained RandomForestClassifier on {n_samples} synthetic samples")
    print(f"  Test accuracy: {acc:.3f}")
    print(f"  Test ROC-AUC : {auc:.3f}")
    print(f"  Saved model to: {os.path.abspath(MODEL_PATH)}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    train_and_save(n)
