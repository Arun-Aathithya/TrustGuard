#!/usr/bin/env python3
"""
Compute a SENSOR_CALIBRATION entry from a HEALTHY baseline run (stdlib only).

1. Run the machine in a known-good state and let the ESP32 send readings for 10+ minutes.
2. Either read them from the API ...
     python tools/calibrate_baseline.py --api http://localhost:8000 --sensor-id 7 --sensor-type vibration --minutes 30
   ... or from a text/CSV file with one raw number per line:
     python tools/calibrate_baseline.py --file raw.txt --sensor-type vibration
3. Paste the printed line into backend/.env and restart. Existing readings are not rewritten.

It sets scale so the healthy mean maps to the simulator/model's healthy mean (vibration 2.5, temperature 65 ...).
Temperature normally needs no scale (use --offset-only to correct a known bias against a reference thermometer).
This is a baseline alignment, not a physical unit conversion: vibration becomes an index. Validate on labelled data.
"""
import argparse, json, statistics, sys, urllib.request

TARGET = {"temperature": 65.0, "vibration": 2.5, "pressure": 100.0, "current": 12.0, "rpm": 1750.0}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sensor-type", required=True, choices=TARGET)
    p.add_argument("--file"); p.add_argument("--api"); p.add_argument("--sensor-id", type=int); p.add_argument("--minutes", type=int, default=30)
    p.add_argument("--device-id", help="calibrate this device only (key DEVICE:type)")
    p.add_argument("--offset-only", action="store_true", help="shift by (target - mean) instead of scaling")
    p.add_argument("--target", type=float, help="override the healthy target mean")
    a = p.parse_args()

    if a.file:
        vals = [float(x) for x in open(a.file).read().replace(",", "\n").split() if x.strip()]
    elif a.api and a.sensor_id:
        url = f"{a.api.rstrip('/')}/api/readings?sensor_id={a.sensor_id}&minutes={a.minutes}&source=hardware"
        rows = json.load(urllib.request.urlopen(url, timeout=10))
        vals = [r["raw_value"] if r.get("raw_value") is not None else r["value"] for r in rows if r.get("value") is not None]
    else:
        sys.exit("Give --file, or --api with --sensor-id.")
    if len(vals) < 20:
        sys.exit(f"Only {len(vals)} readings: collect at least 20 healthy readings first.")
    mean, sd = statistics.fmean(vals), statistics.pstdev(vals)
    target = a.target if a.target is not None else TARGET[a.sensor_type]
    if a.offset_only:
        cfg = {"scale": 1.0, "offset": round(target - mean, 4)}
    else:
        if mean <= 0:
            sys.exit("Healthy mean is <= 0; use --offset-only.")
        cfg = {"scale": round(target / mean, 4), "offset": 0.0}
    key = f"{a.device_id}:{a.sensor_type}" if a.device_id else a.sensor_type
    print(f"{len(vals)} readings, healthy mean {mean:.4f}, std {sd:.4f} (relative noise {sd / mean * 100 if mean else 0:.1f}%)")
    print("Add to backend/.env (merge with any existing entries):")
    print("SENSOR_CALIBRATION=" + json.dumps({key: cfg}))


if __name__ == "__main__":
    main()
