import { useEffect, useState } from "react";
import { buildChecklist } from "../lib/setupChecklist";

/** Step-by-step hardware bring-up for one device: broker -> registered -> first reading -> online. */
export default function SetupChecklist({ broker, devices, loading }) {
  const hw = devices.filter((d) => d.data_source === "hardware");
  // Default to the device furthest from done, so the thing that needs attention is what you see first.
  const defaultId = (hw.find((d) => d.device_status !== "online") || hw[0])?.sensor_id ?? null;
  const [picked, setPicked] = useState(null);
  useEffect(() => { if (picked != null && !hw.some((d) => d.sensor_id === picked)) setPicked(null); }, [hw, picked]);
  const device = hw.find((d) => d.sensor_id === (picked ?? defaultId)) || null;
  const { steps, current, complete, doneCount } = buildChecklist(broker, device);
  const unitWarnings = hw.filter((d) => d.unit_warning);

  return (
    <section aria-label="Hardware setup checklist" style={{ background: "var(--bg-panel)", border: `1px solid ${complete ? "var(--accent-trust)" : "var(--border-hairline)"}`, borderRadius: "var(--radius-md)", padding: "14px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)", letterSpacing: "0.02em" }}>
          HARDWARE SETUP CHECKLIST · <span className="mono">{doneCount}/4</span>
        </div>
        {hw.length > 1 && (
          <label style={{ fontSize: 12, color: "var(--text-secondary)", display: "flex", gap: 6, alignItems: "center" }}>
            Device
            <select className="tg-input" style={{ width: "auto" }} value={device?.sensor_id ?? ""} onChange={(e) => setPicked(Number(e.target.value))}>
              {hw.map((d) => <option key={d.sensor_id} value={d.sensor_id}>{d.device_id} · {d.machine_name} · {d.sensor_type}</option>)}
            </select>
          </label>
        )}
      </div>
      {loading && !broker ? <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>Loading…</div> : (
        <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {steps.map((s, i) => {
            const state = s.done ? "done" : i === current ? "current" : "pending";
            const color = state === "done" ? "var(--accent-trust)" : state === "current" ? "var(--accent-caution)" : "var(--text-tertiary)";
            return (
              <li key={s.id} aria-current={state === "current" ? "step" : undefined} style={{ display: "flex", gap: 10 }}>
                <span aria-hidden="true" className="mono" style={{ color, width: 18, flexShrink: 0 }}>{state === "done" ? "✓" : state === "current" ? "▶" : "○"}</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: state === "pending" ? "var(--text-secondary)" : "var(--text-primary)" }}>
                    {i + 1}. {s.title}
                    <span className="sr-only">{state === "done" ? " (done)" : state === "current" ? " (next step)" : " (not yet)"}</span>
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>{s.detail}</div>
                  {state === "current" && <div style={{ fontSize: 12, color: "var(--accent-caution)", marginTop: 2 }}>Next: {s.fix}</div>}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {unitWarnings.length > 0 && (
        <div role="status" style={{ marginTop: 12, fontSize: 12, color: "var(--accent-caution)", borderTop: "1px solid var(--border-hairline)", paddingTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
          {unitWarnings.map((d) => <div key={d.sensor_id}>⚠ Units, {d.device_id} / {d.sensor_type}: {d.unit_warning}</div>)}
        </div>
      )}
      {complete && unitWarnings.length === 0 && <div style={{ marginTop: 10, fontSize: 12, color: "var(--accent-trust)" }}>Device is sending valid, recent data.</div>}
    </section>
  );
}
