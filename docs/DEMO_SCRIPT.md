# Demo script (about 3 minutes)

Always say aloud which data is **real hardware** and which is **simulated / injected**. The dashboard badges show it.

1. **Normal operation** - open a machine, click *1. Normal operation*. Point out: stable readings, high sensor trust, low failure risk, high confidence. Three separate gauges: trust (is the data reliable?), risk (how likely is a problem?), confidence (how much to rely on the risk figure?).
2. **Sensor fault (injected)** - click *2. Sensor fault*. The temperature sensor drifts, others stay normal. Expect: trust and confidence drop, explanation says *suspected sensor fault*, action is to check the sensor, not to repair the machine. Open *Details & history* on Temperature to show the drift in the chart and the trust components.
3. **Machine failure (simulated)** - click *3. Machine failure*. All sensors agree on overheating, vibration and load. Expect: high risk, high confidence, explanation names the contributing sensors, action *Schedule preventive maintenance* with urgency.
3b. **Two-sensor tie** - with only two sensors on a machine, one moving cannot be blamed on either: the panel shows *CANNOT TELL* and the alert reads "the two sensors disagree; cannot tell which is wrong". Say that a third sensor fixes this.
4. **Real hardware** (ESP32 connected): Hardware page -> register device -> *Test connection*. Unplug it and show Online -> Stale -> Offline and the delayed-data warning. See `HARDWARE_SETUP.md`.

## What to say about accuracy
- An injected software fault shows how the system responds; it does not prove detection of every real sensor failure.
- The risk model is trained on synthetic data and is not validated on labelled real failures. Do not claim predictive accuracy or industrial reliability until it is tested on labelled data.
