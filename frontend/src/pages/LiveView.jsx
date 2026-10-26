import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import { fetchSensorReadings } from "../api/client";
import { DeviceStatusPill } from "../components/StatusBadges";
import { relSeconds, relTime, sensorName } from "../lib/format";

/** Exact value: temperature 2 decimals, vibration 3 decimals. */
export function exactValue(sensor, v) {
  if (v == null) return "—";
  return v.toFixed(sensor.sensor_type === "vibration" ? 3 : 2);
}

const spark = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: { enabled: false } },
  scales: { x: { display: false }, y: { display: false } },
  elements: { point: { radius: 0 }, line: { borderWidth: 2, tension: 0.35 } },
};

function Tile({ snapshot }) {
  const { sensor, latest_value } = snapshot;
  const [hist, setHist] = useState([]);
  useEffect(() => {
    let off = false;
    fetchSensorReadings(sensor.id, 40)
      .then((rows) => { if (!off) setHist(rows.filter((r) => r.value !== null).map((r) => r.value)); })
      .catch(() => {});
    return () => { off = true; };
  }, [sensor.id, latest_value]);
  const isHw = sensor.data_source === "hardware";
  const age = isHw ? relSeconds(sensor.seconds_since_seen) : relTime(sensor.last_data_at);
  const has = latest_value != null;
  const bad = isHw && sensor.device_status === "offline";
  return (
    <div className="tg-panel tg-live-tile">
      <div className="tg-live-top">
        <span className="tg-live-name">{sensorName(sensor)}</span>
        <DeviceStatusPill status={sensor.device_status} />
      </div>
      <div className="mono tg-live-value" style={{ color: has && !bad ? "var(--text-primary)" : "var(--text-tertiary)" }}>
        {exactValue(sensor, latest_value)}
        <span className="tg-live-unit">{sensor.display_unit || sensor.unit}</span>
      </div>
      <div className="mono tg-live-age">{has ? `Updated ${age}` : "No reading yet"}</div>
      <div style={{ height: 44 }} aria-hidden="true">
        {hist.length > 1 && (
          <Line data={{ labels: hist.map((_, i) => i), datasets: [{ data: hist, borderColor: "#4ea3d8", fill: false }] }} options={spark} />
        )}
      </div>
    </div>
  );
}

const pct = (v) => (v == null ? "—" : `${Math.round(v)}%`);
const riskWord = (r) => (r == null ? "No data yet" : r >= 60 ? "High" : r >= 35 ? "Medium" : "Low");
const riskColor = (r) => (r == null ? "var(--text-tertiary)" : r >= 60 ? "var(--accent-fault)" : r >= 35 ? "var(--accent-caution)" : "var(--accent-trust)");

function Machine({ d, onOpen }) {
  const p = d.latest_prediction;
  const ex = d.explanation;
  const hasTrust = d.sensors.some((s) => s.trust);
  const alerts = (d.open_alerts || []).slice(0, 3);
  return (
    <section className="tg-live-machine" aria-label={d.machine.name}>
      <div className="tg-live-head">
        <h2>{d.machine.name}</h2>
        <button className="tg-btn" onClick={() => onOpen(d.machine.id)}>Full details</button>
      </div>
      <div className="tg-live-grid">
        {d.sensors.map((s) => <Tile key={s.sensor.id} snapshot={s} />)}
        {d.sensors.length === 0 && <div className="tg-panel" style={{ fontSize: 13 }}>No sensors on this machine yet.</div>}
      </div>
      <div className="tg-live-grid tg-live-three">
        <div className="tg-panel">
          <div className="tg-live-label">FAILURE RISK</div>
          <div className="mono tg-live-mid" style={{ color: riskColor(p?.failure_risk) }}>{riskWord(p?.failure_risk)}</div>
          <div className="mono tg-live-sub">{pct(p?.failure_risk)}</div>
        </div>
        <div className="tg-panel">
          <div className="tg-live-label">CONFIDENCE</div>
          <div className="mono tg-live-mid">{pct(p?.prediction_confidence)}</div>
          <div className="tg-live-sub">How sure the estimate is</div>
        </div>
        <div className="tg-panel">
          <div className="tg-live-label">DATA TRUST</div>
          <div className="mono tg-live-mid">{hasTrust ? pct(d.overall_trust) : "—"}</div>
          <div className="tg-live-sub">How reliable the sensor data is</div>
        </div>
      </div>
      {ex?.headline && (
        <div className="tg-panel" style={{ fontSize: 14, lineHeight: 1.45 }}>
          <div className="tg-live-label">WHAT TO DO</div>
          <strong>{ex.headline}</strong>
          {ex.action && <div style={{ color: "var(--text-secondary)", marginTop: 4 }}>{ex.action}</div>}
        </div>
      )}
      {alerts.length > 0 && (
        <div className="tg-panel">
          <div className="tg-live-label">LATEST ALERTS</div>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 13, lineHeight: 1.5 }}>
            {alerts.map((a) => <li key={a.id}>{a.message}</li>)}
          </ul>
        </div>
      )}
    </section>
  );
}

export default function LiveView({ dashboards, onOpenMachine }) {
  return (
    <div className="tg-page" style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 1100 }}>
      <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Live readings</h1>
      {dashboards.map((d) => <Machine key={d.machine.id} d={d} onOpen={onOpenMachine} />)}
    </div>
  );
}
