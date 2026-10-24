const SEVERITY_META = {
  info: { color: "var(--accent-trust)", bg: "var(--accent-trust-dim)", label: "MONITOR" },
  warning: { color: "var(--accent-caution)", bg: "var(--accent-caution-dim)", label: "ATTENTION" },
  critical: { color: "var(--accent-fault)", bg: "var(--accent-fault-dim)", label: "ACTION REQUIRED" },
};

const FAULT_ICON = { none: "✓", sensor_fault_suspected: "◐", machine_fault_probable: "⚙", both: "⚠" };
const ROLE_META = {
  sensor_suspect: { label: "Suspect sensor", color: "var(--accent-caution)", icon: "◐" },
  machine_signal: { label: "Machine signal", color: "var(--accent-fault)", icon: "▲" },
  ok: { label: "Normal", color: "var(--accent-trust)", icon: "✓" },
};

function Block({ title, children }) {
  return (
    <div style={{ flex: "1 1 240px", minWidth: 0 }}>
      <div className="mono" style={{ fontSize: 10.5, letterSpacing: "0.05em", color: "var(--text-tertiary)", marginBottom: 3 }}>{title}</div>
      <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--text-secondary)" }}>{children}</div>
    </div>
  );
}

/** Explainable recommendation. Falls back to the old one-line banner if the API has no explanation yet. */
export default function RecommendationBanner({ dashboard }) {
  const ex = dashboard.explanation;
  if (!ex) {
    return (
      <div className="tg-panel" role="status">
        <div style={{ fontSize: 16, fontWeight: 600 }}>{dashboard.recommendation || "Waiting for first prediction…"}</div>
      </div>
    );
  }
  const meta = SEVERITY_META[ex.severity] || SEVERITY_META.info;
  const suspects = ex.contributors.filter((c) => c.role === "sensor_suspect");
  const signals = ex.contributors.filter((c) => c.role === "machine_signal");

  return (
    <section aria-label="Recommendation and explanation" style={{ background: meta.bg, border: `1px solid ${meta.color}`, borderRadius: "var(--radius-md)", padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 10.5, letterSpacing: "0.06em", color: meta.color }}>{meta.label}</span>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--text-secondary)" }}>URGENCY: {ex.urgency_label}</span>
      </div>

      <div>
        <div style={{ fontSize: 16, fontWeight: 600 }}>{ex.action}</div>
        <div style={{ fontSize: 13, marginTop: 3 }}>
          <span aria-hidden="true">{FAULT_ICON[ex.fault_class]} </span>
          <strong>{ex.fault_label}.</strong> <span style={{ color: "var(--text-secondary)" }}>{ex.headline}</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <Block title="WHY IS RISK THIS LEVEL?">{ex.why_risk}</Block>
        <Block title="WHY THIS CONFIDENCE?">{ex.why_confidence}</Block>
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <Block title="SUSPECTED SENSOR FAULTS">
          {suspects.length === 0 ? "None indicated." : (
            <ul style={{ margin: 0, paddingLeft: 16 }}>{suspects.map((c) => <li key={c.sensor_type}><strong>{c.name}:</strong> {c.note}</li>)}</ul>
          )}
        </Block>
        <Block title="SIGNS OF A MACHINE PROBLEM">
          {signals.length === 0 ? "None indicated by reliable sensors." : (
            <ul style={{ margin: 0, paddingLeft: 16 }}>{signals.map((c) => <li key={c.sensor_type}><strong>{c.name}:</strong> {c.note}</li>)}</ul>
          )}
        </Block>
      </div>

      <details>
        <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--text-secondary)" }}>Sensor-by-sensor contribution</summary>
        <ul style={{ listStyle: "none", margin: "8px 0 0", padding: 0, display: "grid", gap: 4 }}>
          {ex.contributors.map((c) => {
            const r = ROLE_META[c.role];
            return (
              <li key={c.sensor_type} style={{ fontSize: 12, display: "flex", gap: 8 }}>
                <span style={{ color: r.color, minWidth: 130 }}><span aria-hidden="true">{r.icon} </span>{r.label}</span>
                <span><strong>{c.name}</strong> — {c.note}</span>
              </li>
            );
          })}
        </ul>
      </details>

      <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11.5, color: "var(--text-tertiary)", lineHeight: 1.5 }}>
        {ex.caveats.map((c, i) => <li key={i}>{c}</li>)}
      </ul>
    </section>
  );
}
