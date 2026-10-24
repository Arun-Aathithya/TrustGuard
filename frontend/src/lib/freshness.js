// Sensor-data freshness, computed in the browser from timestamps so it keeps ticking
// even when no new dashboard payload arrives (a silent sensor sends nothing to react to).
// Hardware thresholds mirror the backend (DEVICE_STALE_SECONDS=30, DEVICE_OFFLINE_SECONDS=120).
// Simulated sensors only change when someone runs a tick, so they get far longer limits.
import { parseUtcMs } from "./format";

export const THRESHOLDS = {
  hardware: { staleS: 30, deadS: 120 },
  simulation: { staleS: 600, deadS: 3600 },
};

const RANK = { fresh: 0, stale: 1, dead: 2, none: 3 };

/** -> { state: fresh|stale|dead|none, ageS, lastMs, source } for one sensor. */
export function sensorFreshness(sensor, nowMs = Date.now()) {
  const hw = sensor.data_source === "hardware";
  const lastMs = parseUtcMs(hw ? sensor.last_seen_at : sensor.last_data_at);
  const source = hw ? "hardware" : "simulation";
  if (lastMs == null) return { state: "none", ageS: null, lastMs: null, source };
  const ageS = Math.max(0, (nowMs - lastMs) / 1000);
  const t = THRESHOLDS[source];
  return { state: ageS > t.deadS ? "dead" : ageS > t.staleS ? "stale" : "fresh", ageS, lastMs, source };
}

/** Worst state across sensors, the newest reading time, and which sensors are not fresh. */
export function summarizeFreshness(sensors, nowMs = Date.now()) {
  const items = sensors.map((s) => ({ sensor: s, ...sensorFreshness(s, nowMs) }));
  if (items.length === 0) return { state: "none", newestMs: null, newestAgeS: null, stalestAgeS: null, stalestMs: null, items, problems: [] };
  const worst = items.reduce((w, i) => (RANK[i.state] > RANK[w] ? i.state : w), "fresh");
  const newestMs = items.reduce((m, i) => (i.lastMs != null && (m == null || i.lastMs > m) ? i.lastMs : m), null);
  // The most out-of-date sensor that is actually a problem: this, not the newest reading, is what a stale warning is about.
  const problems = items.filter((i) => i.state !== "fresh");
  const stalest = problems.filter((i) => i.lastMs != null).reduce((m, i) => (m == null || i.lastMs < m.lastMs ? i : m), null);
  return {
    stalestMs: stalest ? stalest.lastMs : null,
    stalestAgeS: stalest ? stalest.ageS : null,
    state: worst,
    newestMs,
    newestAgeS: newestMs == null ? null : Math.max(0, (nowMs - newestMs) / 1000),
    items,
    problems,
  };
}
