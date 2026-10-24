import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import { fetchSensorReadings } from "../api/client";
import { relSeconds, relTime, SENSOR_LABELS as LABELS, sensorName } from "../lib/format";
import { DeviceStatusPill } from "./StatusBadges";


function trustTone(score) {
  if (score >= 80) return "var(--accent-trust)";
  if (score >= 50) return "var(--accent-caution)";
  return "var(--accent-fault)";
}

const sparklineOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: { enabled: false } },
  scales: {
    x: { display: false },
    y: { display: false },
  },
  elements: {
    point: { radius: 0 },
    line: { borderWidth: 1.5, tension: 0.35 },
  },
};

/** Plain-language data-quality flags derived from the trust breakdown + device state. */
export function sensorFlags(sensor, trust) {
  const flags = [];
  if (sensor.device_status === "offline") flags.push({ key: "offline", text: "No data: device offline", level: "fault" });
  else if (sensor.device_status === "stale") flags.push({ key: "stale", text: "Stale data", level: "caution" });
  if (sensor.unit_warning) flags.push({ key: "units", text: "Units not converted", level: "caution" });
  if (sensor.connection_status === "faulty") flags.push({ key: "suspicious", text: "Suspicious value", level: "fault" });
  if (trust) {
    if (trust.missing_score < 70) flags.push({ key: "missing", text: "Missing readings", level: "caution" });
    if (trust.drift_score < 70) flags.push({ key: "drift", text: "Drift detected", level: "caution" });
    if (trust.noise_score < 70) flags.push({ key: "noise", text: "Noisy signal", level: "caution" });
    if (trust.cross_agreement_score < 70) flags.push({ key: "cross", text: "Disagrees with other sensors", level: "caution" });
  }
  return flags;
}

export default function SensorCard({ snapshot, onOpen, onRemove }) {
  const [history, setHistory] = useState([]);
  const { sensor, latest_value, trust } = snapshot;
  const trustScore = trust?.trust_score ?? 100;
  const tone = trustTone(trustScore);
  const flags = sensorFlags(sensor, trust);
  const isHardware = sensor.data_source === "hardware";
  const lastUpdated = isHardware ? relSeconds(sensor.seconds_since_seen) : relTime(sensor.last_data_at);
  const name = sensorName(sensor);
  const typeLine = [LABELS[sensor.sensor_type] || sensor.sensor_type, sensor.hardware_model].filter(Boolean).join(" · ");
  const unlinked = isHardware && !sensor.device_id; // configured on the website, no ESP32 assigned yet
  const hasReading = latest_value != null;

  useEffect(() => {
    let cancelled = false;
    fetchSensorReadings(sensor.id, 30)
      .then((rows) => {
        if (!cancelled) setHistory(rows.filter((r) => r.value !== null).map((r) => r.value));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sensor.id, latest_value]);

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: `1px solid ${flags.some((f) => f.level === "fault") ? "var(--accent-fault)" : flags.length ? "var(--accent-caution)" : "var(--border-hairline)"}`,
        borderRadius: "var(--radius-md)",
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", overflowWrap: "anywhere" }}>{name}</div>
          <div className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)" }}>{typeLine}</div>
        </div>
        {unlinked
          ? <span className="mono" style={{ fontSize: 10.5, color: "var(--text-secondary)", border: "1px solid var(--border-hairline)", borderRadius: "var(--radius-sm)", padding: "2px 6px", whiteSpace: "nowrap" }}>NO DEVICE</span>
          : <DeviceStatusPill status={sensor.device_status} />}
      </div>

      <div className="mono" style={{ fontSize: 24, fontWeight: 600, color: hasReading ? "var(--text-primary)" : "var(--text-tertiary)" }}>
        {hasReading ? latest_value.toFixed(sensor.sensor_type === "vibration" ? 2 : 1) : "—"}
        <span style={{ fontSize: 13, color: "var(--text-secondary)", marginLeft: 4 }} title={sensor.unit_warning || sensor.unit_note || undefined}>{sensor.display_unit || sensor.unit}</span>
      </div>
      {!hasReading && (
        <div style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
          {unlinked ? "No reading: no ESP32 is linked to this sensor yet." : "No reading received yet."}
        </div>
      )}

      {(sensor.unit_warning || sensor.unit_note) && (
        <div style={{ fontSize: 10.5, color: sensor.unit_warning ? "var(--accent-caution)" : "var(--text-tertiary)", lineHeight: 1.35 }}>
          {sensor.unit_warning || "Calibrated index on the mm/s scale, not a true mm/s measurement."}
        </div>
      )}

      <div className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)" }} title={sensor.last_data_at || ""}>
        {isHardware ? `Device ${sensor.device_id || "—"} · ` : "Simulated · "}last updated {lastUpdated}
      </div>

      <div style={{ height: 32 }} aria-hidden="true">
        {history.length > 1 && (
          <Line
            data={{
              labels: history.map((_, i) => i),
              datasets: [{ data: history, borderColor: tone, fill: false }],
            }}
            options={sparklineOptions}
          />
        )}
      </div>

      {flags.length > 0 && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexWrap: "wrap", gap: 5 }} aria-label="Data quality warnings">
          {flags.map((f) => (
            <li
              key={f.key}
              style={{
                fontSize: 10.5,
                padding: "2px 6px",
                borderRadius: "var(--radius-sm)",
                color: f.level === "fault" ? "var(--accent-fault)" : "var(--accent-caution)",
                border: `1px solid ${f.level === "fault" ? "var(--accent-fault-dim)" : "var(--accent-caution-dim)"}`,
              }}
            >
              <span aria-hidden="true">⚠ </span>
              {f.text}
            </li>
          ))}
        </ul>
      )}

      {onOpen && (
        <button className="tg-btn" onClick={() => onOpen(sensor.id)} aria-label={`Details and history for ${name}`}>
          Details &amp; history
        </button>
      )}
      {onRemove && (
        <button className="tg-btn" onClick={() => onRemove(sensor)} aria-label={`Remove sensor ${name}`}>
          Remove sensor
        </button>
      )}

      {trust && <div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: "var(--text-tertiary)", marginBottom: 3 }}>
          <span>TRUST SCORE</span>
          <span className="mono" style={{ color: tone }}>{Math.round(trustScore)}%</span>
        </div>
        <div
          role="progressbar"
          aria-label={`${name} trust score`}
          aria-valuenow={Math.round(trustScore)}
          aria-valuemin={0}
          aria-valuemax={100}
          style={{ height: 4, background: "var(--bg-inset)", borderRadius: 2, overflow: "hidden" }}
        >
          <div style={{ width: `${trustScore}%`, height: "100%", background: tone }} />
        </div>
      </div>}
    </div>
  );
}
