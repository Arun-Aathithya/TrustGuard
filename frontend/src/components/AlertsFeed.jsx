import { useState } from "react";
import { errorMessage, resolveAlert, setAdminKey } from "../api/client";
import { useAdmin } from "../hooks/useAdmin";

const SEVERITY_COLOR = {
  info: "var(--accent-trust)",
  warning: "var(--accent-caution)",
  critical: "var(--accent-fault)",
};

function timeAgo(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ago`;
}

export default function AlertsFeed({ alerts, onResolved }) {
  const { isAdmin } = useAdmin();
  const [error, setError] = useState(null);
  const [needsKey, setNeedsKey] = useState(null); // alert id awaiting an admin key
  const [keyInput, setKeyInput] = useState("");
  const handleResolve = async (id) => {
    try {
      await resolveAlert(id);
      setError(null);
      setNeedsKey(null);
      onResolved?.(id);
    } catch (e) {
      setError(errorMessage(e));
      if (e?.response?.status === 401) setNeedsKey(id);
    }
  };

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ fontSize: 12.5, color: "var(--text-secondary)", letterSpacing: "0.02em" }}>OPEN ALERTS</div>
      {error && (
        <div role="alert" style={{ fontSize: 12, color: "var(--accent-fault)" }}>
          Could not resolve alert: {error}
        </div>
      )}
      {needsKey !== null && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <label className="sr-only" htmlFor="alert-admin-key">Admin key</label>
          <input id="alert-admin-key" className="tg-input" type="password" autoComplete="off" placeholder="Admin key (kept in this tab only)" value={keyInput} onChange={(e) => setKeyInput(e.target.value)} style={{ flex: "1 1 160px" }} />
          <button className="tg-btn" onClick={() => { setAdminKey(keyInput.trim()); setKeyInput(""); handleResolve(needsKey); }}>Save &amp; retry</button>
        </div>
      )}
      {alerts.length === 0 && (
        <div style={{ fontSize: 12.5, color: "var(--text-tertiary)" }}>No open alerts. All sensors nominal.</div>
      )}
      {alerts.map((alert) => (
        <div
          key={alert.id}
          style={{
            display: "flex",
            gap: 10,
            alignItems: "flex-start",
            paddingBottom: 10,
            borderBottom: "1px solid var(--border-hairline)",
          }}
        >
          <span
            style={{
              marginTop: 5,
              width: 6,
              height: 6,
              borderRadius: "50%",
              flexShrink: 0,
              background: SEVERITY_COLOR[alert.severity] || SEVERITY_COLOR.warning,
            }}
          />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, lineHeight: 1.4 }}>{alert.message}</div>
            <div className="mono" style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 3 }}>
              {alert.alert_type.replace(/_/g, " ").toUpperCase()} · {timeAgo(alert.created_at)}
            </div>
          </div>
          {isAdmin && <button
            aria-label={`Resolve alert: ${alert.message.slice(0, 40)}`}
            onClick={() => handleResolve(alert.id)}
            style={{
              background: "transparent",
              border: "1px solid var(--border-strong)",
              color: "var(--text-secondary)",
              borderRadius: "var(--radius-sm)",
              fontSize: 11,
              padding: "4px 8px",
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            Resolve
          </button>}
        </div>
      ))}
    </div>
  );
}
