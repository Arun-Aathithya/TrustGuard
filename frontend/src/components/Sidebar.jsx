import ConnectionStatus from "./ConnectionStatus";

const STATUS_META = {
  operational: { label: "Operational", color: "var(--accent-trust)" },
  at_risk: { label: "At Risk", color: "var(--accent-caution)" },
  down: { label: "Down", color: "var(--accent-fault)" },
};

const SOURCE_TAG = { hardware: "HW", simulation: "SIM", mixed: "MIX" };

function NavButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      style={{
        width: "100%",
        textAlign: "left",
        background: active ? "var(--bg-panel-raised)" : "transparent",
        border: "none",
        borderLeft: active ? "2px solid var(--accent-signal)" : "2px solid transparent",
        padding: "11px 16px", minHeight: 44,
        cursor: "pointer",
        color: "var(--text-primary)",
        fontSize: 13.5,
      }}
    >
      {children}
    </button>
  );
}

export default function Sidebar({ dashboards, selectedId, onSelect, mode, lastSyncAt, view, onView }) {
  return (
    <aside className="tg-sidebar" aria-label="Navigation">
      <div style={{ padding: "20px 18px 14px", borderBottom: "1px solid var(--border-hairline)" }}>
        <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: "-0.01em" }}>TrustGuard AI</div>
        <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>Sensor-trust predictive maintenance</div>
        <ConnectionStatus dashboards={dashboards} mode={mode} lastSyncAt={lastSyncAt} />
      </div>

      <div className="tg-sidebar-scroll">
        <nav aria-label="Main">
          <NavButton active={view === "overview"} onClick={() => onView("overview")}>Overview</NavButton>
          <NavButton active={view === "hardware"} onClick={() => onView("hardware")}>Hardware management</NavButton>
          <NavButton active={view === "add"} onClick={() => onView("add")}>+ Add machine</NavButton>
        </nav>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", padding: "14px 18px 8px", letterSpacing: "0.04em" }}>
          MACHINES ({dashboards.length})
        </div>
        {dashboards.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--text-tertiary)", padding: "0 18px 12px" }}>No machines yet.</div>
        )}
        {dashboards.map((d) => {
          const meta = STATUS_META[d.machine.status] || STATUS_META.operational;
          const active = view === "machine" && d.machine.id === selectedId;
          const risk = d.latest_prediction?.failure_risk ?? null; // null = no prediction yet (never shown as 0%)
          return (
            <button
              key={d.machine.id}
              onClick={() => onSelect(d.machine.id)}
              aria-current={active ? "page" : undefined}
              style={{
                width: "100%",
                textAlign: "left",
                background: active ? "var(--bg-panel-raised)" : "transparent",
                border: "none",
                borderLeft: active ? `2px solid ${meta.color}` : "2px solid transparent",
                padding: "10px 16px", minHeight: 44,
                cursor: "pointer",
                color: "var(--text-primary)",
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 13.5, fontWeight: 500 }}>
                  {d.machine.name}{" "}
                  <span className="mono" style={{ fontSize: 9.5, color: "var(--text-tertiary)" }}>
                    {d.sensors.length > 0 ? (SOURCE_TAG[d.data_source] || "SIM") : ""}
                  </span>
                </span>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: meta.color }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
                <span style={{ color: "var(--text-tertiary)" }}>{d.machine.location}</span>
                <span className="mono" style={{ color: "var(--text-secondary)" }}>
                  {risk === null ? "NO DATA YET" : `RISK ${Math.round(risk)}%`}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
