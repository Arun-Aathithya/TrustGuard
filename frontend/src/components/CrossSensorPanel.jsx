const VERDICT = {
  agree: { label: "CONSENSUS", color: "var(--accent-trust)", help: "All sensors agree." },
  machine_change: { label: "MACHINE CHANGE", color: "var(--accent-signal)", help: "Several sensors moved together, so this is treated as a real change in the machine or process. No sensor's trust is reduced for it." },
  sensor_suspect: { label: "SENSOR SUSPECT", color: "var(--accent-caution)", help: "One sensor moved while two or more others stayed normal." },
  ambiguous: { label: "CANNOT TELL", color: "var(--accent-caution)", help: "The two sensors disagree; cannot tell which is wrong. Neither is blamed. Add a third sensor to break the tie." },
  insufficient: { label: "TOO FEW SENSORS", color: "var(--text-tertiary)", help: "Fewer than two sensors have usable data, so nothing can be cross-checked." },
};

export default function CrossSensorPanel({ dashboard }) {
  const { sensors, cross_sensor_verdict = "insufficient", cross_sensor_detail, cross_sensor_moved = [], cross_sensor_suspects = [] } = dashboard;
  const v = VERDICT[cross_sensor_verdict] || VERDICT.insufficient;

  const tile = (type) => {
    if (cross_sensor_suspects.includes(type)) return { text: "OUTLIER", color: "var(--accent-caution)", bg: "var(--accent-caution-dim)" };
    if (cross_sensor_verdict === "ambiguous") return { text: cross_sensor_moved.includes(type) ? "MOVED" : "STEADY", color: "var(--accent-caution)", bg: "var(--accent-caution-dim)" };
    if (cross_sensor_moved.includes(type)) return { text: "MOVED", color: "var(--accent-signal)", bg: "var(--accent-signal-dim)" };
    return { text: "AGREE", color: "var(--accent-trust)", bg: "var(--bg-inset)" };
  };

  return (
    <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border-hairline)", borderRadius: "var(--radius-md)", padding: "14px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>CROSS-SENSOR VALIDATION</span>
        <span className="mono" style={{ fontSize: 10.5, padding: "2px 7px", borderRadius: "var(--radius-sm)", color: v.color, border: `1px solid ${v.color}` }}>{v.label}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))", gap: 8 }}>
        {sensors.map(({ sensor }) => {
          const t = tile(sensor.sensor_type);
          return (
            <div key={sensor.id} style={{ textAlign: "center", padding: "8px 4px", borderRadius: "var(--radius-sm)", background: t.bg, border: `1px solid ${t.color}` }}>
              <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", textTransform: "capitalize" }}>{sensor.sensor_type}</div>
              <div className="mono" style={{ fontSize: 11, marginTop: 2, color: t.color }}>{t.text}</div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 10, lineHeight: 1.45 }}>
        {cross_sensor_verdict === "ambiguous" || cross_sensor_verdict === "machine_change" ? (cross_sensor_detail || v.help) : v.help}
      </div>
    </div>
  );
}
