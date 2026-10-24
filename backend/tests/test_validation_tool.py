"""Checks that tools/validate_labelled.py computes what it claims. The data here is invented: it tests the tool, not the model."""
import importlib.util
import os
import tempfile

import numpy as np

_path = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "validate_labelled.py")
_spec = importlib.util.spec_from_file_location("validate_labelled", _path)
vl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vl)


def test_auc_perfect_chance_and_ties():
    y = np.array([0, 0, 1, 1])
    assert vl.auc(y, np.array([1.0, 2.0, 3.0, 4.0])) == 1.0
    assert vl.auc(y, np.array([4.0, 3.0, 2.0, 1.0])) == 0.0
    assert vl.auc(y, np.array([5.0, 5.0, 5.0, 5.0])) == 0.5
    assert np.isnan(vl.auc(np.array([0, 0]), np.array([1.0, 2.0])))


def test_metrics_on_known_confusion():
    y = np.array([0, 0, 0, 0, 1, 1])
    risk = np.array([10, 70, 20, 30, 90, 40.0])  # one false alarm, one miss
    m = vl.metrics(y, risk, threshold=60)
    assert m["confusion"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 3}
    assert m["false_alarm_rate"] == 0.25 and m["recall"] == 0.5 and m["precision"] == 0.5
    assert abs(m["majority_class_accuracy"] - 4 / 6) < 1e-9


def test_lead_time_counts_early_late_and_missed():
    y = np.array([0, 0, 0, 1, 1])
    runs = {"early": (y, np.array([0, 70, 70, 80, 90.0])), "late": (y, np.array([0, 0, 0, 0, 90.0])), "missed": (y, np.zeros(5))}
    lt = vl.lead_times(runs, 60)
    assert (lt["alarmed_in_time"], lt["late"], lt["missed"]) == (1, 1, 1) and lt["median_lead_rows"] == 2.0


def test_csv_loader_reads_label_run_and_sensor_columns():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "runs.csv")
        open(f, "w").write("run,faulty,temperature,vibration\nA,0,65,2.5\nA,1,95,7\nB,0,64,2.4\n")
        y, risk, runs = vl.load_csv(f, "faulty", "run")
        assert list(y) == [0, 1, 0] and set(runs) == {"A", "B"} and risk[1] > risk[0]


def test_cmapss_loader_labels_by_remaining_life_and_rescales_to_baseline():
    rng = np.random.default_rng(1)
    rows = []
    for unit, n in ((1, 60), (2, 50)):
        for cyc in range(1, n + 1):
            s = rng.normal(0, 0.01, 21) + 100
            s[3] += cyc * 0.2 * (cyc / n)   # sensor 4 degrades
            rows.append([unit, cyc, 0, 0, 100, *s])
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "train_FD001.txt")
        np.savetxt(f, np.array(rows))
        y, risk, runs = vl.load_cmapss(f, 10, {"temperature": 4}, 0.2)
    assert len(y) == 110 and int(y.sum()) == 22           # RUL <= 10 is 11 cycles per engine (RUL is 0 at the last cycle)
    assert risk[(y == 1)].mean() > risk[(y == 0)].mean()  # the invented degradation is visible
