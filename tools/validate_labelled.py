#!/usr/bin/env python3
"""
Validate TrustGuard's failure-risk output against LABELLED data (healthy vs faulty / run-to-failure).

Why this exists: the shipped risk model is trained on synthetic data. Nothing in the repo shows it separates real
healthy from real faulty machines. This tool measures that on data you supply, and prints plain numbers
(AUC, precision/recall at the app's "high risk" threshold, false-alarm rate, warning lead time) next to the
trivial baseline so a weak result cannot hide.

Modes
  csv      YOUR OWN recorded runs (recommended; this is the data that matters for your machine):
             python tools/validate_labelled.py csv runs.csv --label-col faulty --run-col run
           columns: label (0 healthy / 1 faulty), optional run id (rows in time order), and any of
           temperature, vibration, pressure, current, rpm in the units the app uses (vibration = mm/s or the
           calibrated index; see docs/HARDWARE_SETUP.md).
  cmapss   NASA C-MAPSS turbofan run-to-failure (train_FD00x.txt). Label = remaining useful life <= --rul-threshold.
           C-MAPSS has no vibration or current, so engine sensors are rescaled onto this tool's temperature /
           pressure / rpm channels using each engine's own early-life baseline. That tests the PIPELINE MECHANICS on
           real degradation; it is not evidence about your machine.
  ims      NASA IMS bearing run-to-failure (folder of per-snapshot text files, one column per bearing channel).
           Per-file RMS of --channel becomes vibration (rescaled by the first --baseline-fraction of files);
           label = last --faulty-fraction of the run. Only vibration is available, so risk can move on one channel.
  selftest synthetic data, only to check this script runs. NOT a validation.

Download the public sets yourself (NASA Prognostics Data Repository); this tool does not fetch anything.
"""
import argparse
import csv
import glob
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from ml.predictor import build_features, predict_failure_risk  # noqa: E402
from services.data_processing import SOFT_STATS  # noqa: E402

CHANNELS = ["temperature", "vibration", "pressure", "current", "rpm"]
HIGH_RISK = 60.0  # same threshold as recommendation/recommender.py


def risk_for(row: dict) -> float:
    vals = {c: float(row[c]) for c in CHANNELS if row.get(c) not in (None, "") and not math.isnan(float(row[c]))}
    return predict_failure_risk(build_features(vals))[0]


def auc(y: np.ndarray, score: np.ndarray) -> float:
    """Rank-based ROC-AUC (no sklearn dependency here). nan if only one class is present."""
    pos, neg = score[y == 1], score[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    allv = np.concatenate([pos, neg])
    # average ranks for ties
    sorted_vals = allv[order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1
        i = j + 1
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def metrics(y: np.ndarray, risk: np.ndarray, threshold: float = HIGH_RISK) -> dict:
    pred = (risk >= threshold).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    n = len(y)
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return {
        "rows": n, "faulty_rows": int(y.sum()), "healthy_rows": int(n - y.sum()),
        "auc": auc(y, risk), "threshold": threshold,
        "accuracy": (tp + tn) / n if n else float("nan"),
        "majority_class_accuracy": max(y.mean(), 1 - y.mean()) if n else float("nan"),
        "precision": prec, "recall": rec,
        "false_alarm_rate": fp / (fp + tn) if fp + tn else float("nan"),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "median_risk_healthy": float(np.median(risk[y == 0])) if (y == 0).any() else float("nan"),
        "median_risk_faulty": float(np.median(risk[y == 1])) if (y == 1).any() else float("nan"),
    }


def lead_times(runs: dict, threshold: float = HIGH_RISK) -> dict:
    """
    Per run (rows in time order) that contains a fault: lead = rows between the first alarm (risk >= threshold)
    and the first faulty row. An alarm only after the fault started counts as late, no alarm at all as missed.
    (A false alarm long before the fault inflates the lead, so read it together with the false-alarm rate.)
    """
    leads, late, missed = [], 0, 0
    for _rid, (y, risk) in runs.items():
        if not (y == 1).any():
            continue
        first_fault = int(np.argmax(y == 1))
        alarms = np.where(risk >= threshold)[0]
        if len(alarms) == 0:
            missed += 1
        elif alarms[0] <= first_fault:
            leads.append(first_fault - int(alarms[0]))
        else:
            late += 1
    return {"runs_with_fault": len(leads) + late + missed, "alarmed_in_time": len(leads), "late": late, "missed": missed,
            "median_lead_rows": float(np.median(leads)) if leads else None}


def report(y, risk, runs=None, title=""):
    m = metrics(np.asarray(y), np.asarray(risk))
    print(f"\n=== {title} ===")
    print(f"rows {m['rows']}  (faulty {m['faulty_rows']}, healthy {m['healthy_rows']})")
    print(f"ROC-AUC {m['auc']:.3f}   (0.5 = no better than chance)")
    print(f"At risk >= {m['threshold']:.0f}%: accuracy {m['accuracy']:.3f} vs always-guess-majority {m['majority_class_accuracy']:.3f}")
    print(f"  precision {m['precision']:.3f}  recall {m['recall']:.3f}  false-alarm rate {m['false_alarm_rate']:.3f}  {m['confusion']}")
    print(f"  median risk: healthy {m['median_risk_healthy']:.1f}%  faulty {m['median_risk_faulty']:.1f}%")
    if runs:
        lt = lead_times(runs)
        print(f"Warning lead: {lt['alarmed_in_time']}/{lt['runs_with_fault']} runs alarmed before the fault, {lt['late']} late, {lt['missed']} missed; median lead {lt['median_lead_rows']} rows")
    if m["faulty_rows"] < 30 or m["healthy_rows"] < 30:
        print("WARNING: fewer than 30 rows in a class; these numbers are not statistically meaningful.")
    print("Reminder: one dataset does not make the model validated. Test on runs the model has never seen, from your own machine.")
    return m


# ------------------------------------------------------------------ loaders
def load_csv(path, label_col, run_col):
    rows = list(csv.DictReader(open(path, newline="")))
    if not rows:
        sys.exit("empty file")
    if label_col not in rows[0]:
        sys.exit(f"label column '{label_col}' not found; columns: {list(rows[0])}")
    if not any(c in rows[0] for c in CHANNELS):
        sys.exit(f"no sensor columns; expected some of {CHANNELS}")
    y, risk, runs = [], [], {}
    for r in rows:
        yy, rr = int(float(r[label_col])), risk_for(r)
        y.append(yy); risk.append(rr)
        runs.setdefault(r.get(run_col, "all") if run_col else "all", ([], []))
        runs[r.get(run_col, "all") if run_col else "all"][0].append(yy)
        runs[r.get(run_col, "all") if run_col else "all"][1].append(rr)
    return np.array(y), np.array(risk), {k: (np.array(a), np.array(b)) for k, (a, b) in runs.items()}


# C-MAPSS columns: unit, cycle, 3 settings, 21 sensors. Directions: sensors known to rise with degradation in FD001.
CMAPSS_DEFAULT_MAP = {"temperature": 4, "pressure": 11, "rpm": 8}  # T50, Ps30, Nf (sensor numbers)


def baseline_rescale(x: np.ndarray, channel: str, baseline_fraction: float) -> np.ndarray:
    """Map a raw series onto the app's scale using its own early-life mean/std (healthy mean -> SOFT mean)."""
    k = max(5, int(len(x) * baseline_fraction))
    mu, sd = x[:k].mean(), x[:k].std()
    sd = sd if sd > 1e-9 else 1e-9
    st = SOFT_STATS[channel]
    return st["mean"] + (x - mu) / sd * st["std"] / 3.0  # healthy noise ~ 1/3 of the app's outlier band


def load_cmapss(path, rul_threshold, mapping, baseline_fraction):
    data = np.loadtxt(path)
    y, risk, runs = [], [], {}
    for unit in np.unique(data[:, 0]):
        d = data[data[:, 0] == unit]
        n = len(d)
        rul = n - d[:, 1]
        feats = {ch: baseline_rescale(d[:, 5 + s - 1], ch, baseline_fraction) for ch, s in mapping.items()}
        yy = (rul <= rul_threshold).astype(int)
        rr = np.array([risk_for({ch: feats[ch][i] for ch in feats}) for i in range(n)])
        y += list(yy); risk += list(rr); runs[int(unit)] = (yy, rr)
    return np.array(y), np.array(risk), runs


def load_ims(folder, channel, faulty_fraction, baseline_fraction):
    files = sorted(glob.glob(os.path.join(folder, "*")))
    if len(files) < 20:
        sys.exit("expected a folder with many snapshot files (IMS has hundreds)")
    rms = np.array([math.sqrt(np.mean(np.loadtxt(f, usecols=channel) ** 2)) for f in files])
    vib = baseline_rescale(rms, "vibration", baseline_fraction)
    y = (np.arange(len(files)) >= int(len(files) * (1 - faulty_fraction))).astype(int)
    risk = np.array([risk_for({"vibration": v}) for v in vib])
    return y, risk, {"run": (y, risk)}


def selftest():
    rng = np.random.default_rng(0)
    healthy = [{"temperature": rng.normal(65, 1.5), "vibration": rng.normal(2.5, 0.3), "pressure": rng.normal(100, 3), "current": rng.normal(12, .5), "rpm": rng.normal(1750, 25)} for _ in range(200)]
    faulty = [{"temperature": rng.normal(88, 3), "vibration": rng.normal(6, 1), "pressure": rng.normal(100, 3), "current": rng.normal(17, 1), "rpm": rng.normal(1750, 25)} for _ in range(200)]
    y = np.array([0] * 200 + [1] * 200)
    risk = np.array([risk_for(r) for r in healthy + faulty])
    report(y, risk, title="SELFTEST on invented data. This only shows the script runs. It validates nothing.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("csv"); c.add_argument("file"); c.add_argument("--label-col", default="label"); c.add_argument("--run-col")
    m = sub.add_parser("cmapss"); m.add_argument("file"); m.add_argument("--rul-threshold", type=int, default=30)
    m.add_argument("--baseline-fraction", type=float, default=0.2)
    m.add_argument("--map", default="", help="e.g. temperature=4,pressure=11,rpm=8 (C-MAPSS sensor numbers 1-21)")
    i = sub.add_parser("ims"); i.add_argument("folder"); i.add_argument("--channel", type=int, default=0)
    i.add_argument("--faulty-fraction", type=float, default=0.2); i.add_argument("--baseline-fraction", type=float, default=0.2)
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.mode == "selftest":
        return selftest()
    if a.mode == "csv":
        y, risk, runs = load_csv(a.file, a.label_col, a.run_col)
    elif a.mode == "cmapss":
        mapping = dict(CMAPSS_DEFAULT_MAP)
        if a.map:
            mapping = {k: int(v) for k, v in (kv.split("=") for kv in a.map.split(","))}
        y, risk, runs = load_cmapss(a.file, a.rul_threshold, mapping, a.baseline_fraction)
    else:
        y, risk, runs = load_ims(a.folder, a.channel, a.faulty_fraction, a.baseline_fraction)
    report(y, risk, runs, title=f"{a.mode}: {getattr(a, 'file', None) or a.folder}")


if __name__ == "__main__":
    main()
