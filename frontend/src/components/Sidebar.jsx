import { useState } from "react";
import AdminLogin from "./AdminLogin";
import ConnectionStatus from "./ConnectionStatus";
import { useAdmin } from "../hooks/useAdmin";

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
  const [menuOpen, setMenuOpen] = useState(false);
  const { isAdmin } = useAdmin();
  const go = (v) => { onView(v); setMenuOpen(false); };
  const pick = (id) => { onSelect(id); setMenuOpen(false); };
  return (
    <aside className={`tg-sidebar${menuOpen ? " is-open" : ""}`} aria-label="Navigation">
      <div className="tg-sidebar-head">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, letterSpacing: "-0.01em" }}>TrustGuard AI</div>
            <div className="tg-tagline" style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>Sensor-trust predictive maintenance</div>
          </div>
          <button className="tg-btn tg-menu-btn" aria-expanded={menuOpen} aria-controls="tg-sidebar-body" onClick={() => setMenuOpen((o) => !o)}>
            {menuOpen ? "Close" : "Menu"}
          </button>
        </div>
        <ConnectionStatus dashboards={dashboards} mode={mode} lastSyncAt={lastSyncAt} />
      </div>

      <div className="tg-sidebar-scroll" id="tg-sidebar-body">
        <nav aria-label="Main">
          <NavButton active={view === "live"} onClick={() => go("live")}>Live readings</NavButton>
          <NavButton active={view === "overview"} onClick={() => go("overview")}>Fleet overview</NavButton>
          <NavButton active={view === "hardware"} onClick={() => go("hardware")}>Hardware management</NavButton>
          {isAdmin && <NavButton active={view === "add"} onClick={() => go("add")}>+ Add machine</NavButton>}
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
              onClick={() => pick(d.machine.id)}
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
        <AdminLogin />
      </div>
    </aside>
  );
}
