import { useNow } from "../hooks/useNow";
import { formatAge } from "../lib/format";
import { sensorFreshness, summarizeFreshness } from "../lib/freshness";
import { SENSOR_LABELS } from "../lib/format";

const fmtClock = (ms) => (ms == null ? "never" : new Date(ms).toLocaleString([], { dateStyle: "medium", timeStyle: "medium" }));

/** Always-visible "last sensor reading" line for the machine header. */
export function LastUpdateLine({ sensors }) {
  const now = useNow(1000);
  const f = summarizeFreshness(sensors, now);
  const color = f.state === "fresh" ? "var(--text-secondary)" : f.state === "stale" ? "var(--accent-caution)" : "var(--accent-fault)";
  return (
    <div className="mono" style={{ fontSize: 12.5, marginTop: 6, color }} aria-live="off">
      Last sensor reading: <strong>{fmtClock(f.newestMs)}</strong>
      {f.newestAgeS != null && <> ({formatAge(f.newestAgeS)} ago)</>}
    </div>
  );
}

/**
 * Loud warning when any sensor's last reading is too old. Hardware sensors go stale after 30 s and
 * "no data" after 120 s (same as the backend); simulated sensors after 10 min / 1 h.
 */
export default function FreshnessBanner({ sensors }) {
  const now = useNow(1000);
  const f = summarizeFreshness(sensors, now);
  if (f.state === "fresh" || f.items.length === 0) return null;
  const bad = f.state === "dead" || f.state === "none";
  const color = bad ? "var(--accent-fault)" : "var(--accent-caution)";
  return (
    <div role={bad ? "alert" : "status"} style={{ border: `1px solid ${color}`, background: bad ? "var(--accent-fault-dim)" : "var(--accent-caution-dim)", borderRadius: "var(--radius-md)", padding: "12px 14px" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", alignItems: "baseline" }}>
        <strong style={{ fontSize: 14, color }}>{bad ? "⚠ NO RECENT SENSOR DATA" : "⚠ STALE SENSOR DATA"}</strong>
        <span className="mono" style={{ fontSize: 15, fontWeight: 600 }}>
          {f.stalestMs == null ? "No reading ever received" : <>Last update {formatAge(f.stalestAgeS)} ago</>}
        </span>
        {f.stalestMs != null && <span className="mono" style={{ fontSize: 12, color: "var(--text-secondary)" }}>({fmtClock(f.stalestMs)}, oldest affected sensor)</span>}
      </div>
      <div style={{ fontSize: 12.5, marginTop: 6 }}>
        Risk, trust and confidence below are computed from these old readings and may not reflect the machine right now.
      </div>
      <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none", fontSize: 12.5, display: "flex", flexDirection: "column", gap: 3 }}>
        {f.problems.map((i) => (
          <li key={i.sensor.id}>
            <span className="mono">{SENSOR_LABELS[i.sensor.sensor_type] || i.sensor.sensor_type}</span>
            {" "}({i.source === "hardware" ? `device ${i.sensor.device_id || "?"}` : "simulated"}):{" "}
            {i.lastMs == null ? "no reading has ever arrived" : `last reading ${formatAge(i.ageS)} ago at ${new Date(i.lastMs).toLocaleTimeString()}`}
          </li>
        ))}
      </ul>
    </div>
  );
}

export { sensorFreshness };
