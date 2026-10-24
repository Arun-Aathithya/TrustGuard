import { useEffect, useRef, useState } from "react";
import { Line } from "react-chartjs-2";
import { errorMessage, fetchSensorReadings, fetchSensorTrustHistory } from "../api/client";
import { absTime, relSeconds, relTime, sensorName } from "../lib/format";
import { sensorFlags } from "./SensorCard";
import { DeviceStatusPill } from "./StatusBadges";

const RANGES = [{ m: 15, label: "15 min" }, { m: 60, label: "1 hour" }, { m: 360, label: "6 hours" }];
const axis = { grid: { color: "#1a222c" }, ticks: { color: "#8a99a8", maxTicksLimit: 6, font: { size: 10 } } };
const baseOptions = (yExtra = {}) => ({
  responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
  plugins: { legend: { position: "top", align: "end", labels: { color: "#8a99a8", boxWidth: 10, boxHeight: 10, font: { size: 11 } } } },
  scales: { x: axis, y: { ...axis, ...yExtra } },
  elements: { line: { borderWidth: 2, tension: 0.25 } },
});
const hhmm = (iso) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** Modal with full history for one sensor. Esc or the Close button dismisses it. */
export default function SensorDetail({ snapshot, onClose }) {
  const { sensor, latest_value, trust } = snapshot;
  const [minutes, setMinutes] = useState(60);
  const [state, setState] = useState({ loading: true, error: null, readings: [], trustRows: [] });
  const closeRef = useRef(null);
  const label = sensorName(sensor);
  const isHw = sensor.data_source === "hardware";

  useEffect(() => {
    const opener = document.activeElement;
    closeRef.current?.focus();
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); opener?.focus?.(); };
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.all([fetchSensorReadings(sensor.id, minutes), fetchSensorTrustHistory(sensor.id, minutes)])
      .then(([readings, trustRows]) => !cancelled && setState({ loading: false, error: null, readings, trustRows }))
      .catch((e) => !cancelled && setState({ loading: false, error: errorMessage(e), readings: [], trustRows: [] }));
    return () => { cancelled = true; };
  }, [sensor.id, minutes, latest_value]);

  const { readings, trustRows, loading, error } = state;
  const missing = readings.filter((r) => r.is_missing).length;
  const outliers = readings.filter((r) => r.is_outlier).length;
  const delayed = readings.filter((r) => r.is_delayed).length;
  const vals = readings.filter((r) => r.value !== null).map((r) => r.value);
  const flags = sensorFlags(sensor, trust);

  const readingData = {
    labels: readings.map((r) => hhmm(r.timestamp)),
    datasets: [{
      label: `${label} (${sensor.display_unit || sensor.unit})`, data: readings.map((r) => r.value), borderColor: "#4a9fd8", spanGaps: false,
      pointRadius: readings.map((r) => (r.is_outlier || r.is_missing || r.is_delayed ? 4 : 0)),
      pointStyle: readings.map((r) => (r.is_outlier ? "crossRot" : r.is_delayed ? "triangle" : "rect")),
      pointBackgroundColor: readings.map((r) => (r.is_outlier ? "#de5a5a" : "#de9c3d")),
      pointBorderColor: readings.map((r) => (r.is_outlier ? "#de5a5a" : "#de9c3d")),
    }],
  };
  const trustData = {
    labels: trustRows.map((r) => hhmm(r.computed_at)),
    datasets: [
      { label: "Trust score", data: trustRows.map((r) => r.trust_score), borderColor: "#23c4a8", borderWidth: 3 },
      { label: "Drift", data: trustRows.map((r) => r.drift_score), borderColor: "#de9c3d", borderDash: [4, 3] },
      { label: "Noise", data: trustRows.map((r) => r.noise_score), borderColor: "#8a99a8", borderDash: [4, 3] },
      { label: "Missing", data: trustRows.map((r) => r.missing_score), borderColor: "#de5a5a", borderDash: [4, 3] },
    ],
  };
  const noPoints = { elements: { point: { radius: 0 }, line: { borderWidth: 2, tension: 0.25 } } };

  return (
    <div className="tg-modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="sd-title" className="tg-modal">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
          <div>
            <h2 id="sd-title" style={{ margin: 0, fontSize: 18 }}>{label} sensor</h2>
            <div className="mono" style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 3 }}>
              {isHw ? "REAL HARDWARE" : "SIMULATED"} · {isHw ? `device ${sensor.device_id || "—"}` : "no physical device"}
            </div>
          </div>
          <button ref={closeRef} className="tg-btn" onClick={onClose}>Close</button>
        </div>

        <dl className="tg-facts">
          <div><dt>Current value</dt><dd className="mono">{latest_value != null ? `${latest_value.toFixed(2)} ${sensor.display_unit || sensor.unit}` : "—"}</dd></div>
          <div><dt>Trust score</dt><dd className="mono">{trust ? `${Math.round(trust.trust_score)}%` : "—"}</dd></div>
          <div><dt>Status</dt><dd><DeviceStatusPill status={sensor.device_status} /></dd></div>
          <div><dt>Last updated</dt><dd title={absTime(sensor.last_data_at)}>{isHw ? relSeconds(sensor.seconds_since_seen) : relTime(sensor.last_data_at)}</dd></div>
          {isHw && <div><dt>MQTT topic</dt><dd className="mono" style={{ wordBreak: "break-all" }}>{sensor.mqtt_topic || "—"}</dd></div>}
        </dl>

        {flags.length > 0 && (
          <ul aria-label="Data quality warnings" style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", gap: 6, flexWrap: "wrap" }}>
            {flags.map((f) => <li key={f.key} style={{ fontSize: 12, padding: "2px 8px", border: `1px solid ${f.level === "fault" ? "var(--accent-fault)" : "var(--accent-caution)"}`, borderRadius: "var(--radius-sm)" }}>⚠ {f.text}</li>)}
          </ul>
        )}

        <div role="group" aria-label="History range" style={{ display: "flex", gap: 6 }}>
          {RANGES.map((r) => (
            <button key={r.m} className="tg-btn" aria-pressed={minutes === r.m} onClick={() => setMinutes(r.m)} style={minutes === r.m ? { borderColor: "var(--accent-signal)" } : undefined}>{r.label}</button>
          ))}
        </div>

        {loading && <div role="status" style={{ fontSize: 13, color: "var(--text-secondary)" }}>Loading history…</div>}
        {error && <div role="alert" style={{ fontSize: 13, color: "var(--accent-fault)" }}>Could not load history: {error}</div>}
        {!loading && !error && readings.length === 0 && (
          <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>No readings in this time range yet.</div>
        )}

        {!error && readings.length > 0 && (
          <>
            <div>
              <div className="tg-chart-title">READINGS</div>
              <div className="tg-chart" role="img" aria-label={`${label} readings over the last ${minutes} minutes. ${readings.length} readings, ${missing} missing, ${outliers} suspicious.`}>
                <Line data={readingData} options={baseOptions()} />
              </div>
              <div style={{ fontSize: 11.5, color: "var(--text-secondary)", marginTop: 4 }}>
                {readings.length} readings{vals.length ? ` · min ${Math.min(...vals).toFixed(1)}, max ${Math.max(...vals).toFixed(1)} ${sensor.display_unit || sensor.unit}` : ""} ·
                {" "}{missing} missing · {outliers} suspicious (✕) · {delayed} delayed (▲)
              </div>
            </div>
            <div>
              <div className="tg-chart-title">TRUST SCORE & COMPONENTS (data reliability, not failure risk)</div>
              <div className="tg-chart" role="img" aria-label="Trust score history">
                {trustRows.length > 1 ? <Line data={trustData} options={{ ...baseOptions({ min: 0, max: 100 }), ...noPoints }} /> : <span style={{ fontSize: 12.5, color: "var(--text-tertiary)" }}>Not enough trust history yet.</span>}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
