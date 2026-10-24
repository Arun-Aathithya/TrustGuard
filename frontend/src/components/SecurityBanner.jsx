import { useState } from "react";

/**
 * Persistent, non-dismissable strip: security and setup problems reported by the backend.
 * It stays on every page until the configuration is fixed (it can be collapsed to one line, never hidden).
 */
export default function SecurityBanner({ broker, onOpenHardware }) {
  const [open, setOpen] = useState(true);
  if (!broker) return null;
  // Older backends only send plain strings.
  const issues = Array.isArray(broker.security_issues)
    ? broker.security_issues
    : (broker.security_warnings || []).map((m) => ({ id: m, kind: "security", message: m, fix: null }));
  if (issues.length === 0) return null;
  const security = issues.filter((i) => i.kind === "security").length;
  return (
    <section aria-label="Security and setup warnings" style={{ borderBottom: "1px solid var(--accent-caution)", background: "var(--accent-caution-dim)", padding: "8px 28px", fontSize: 12.5 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ color: "var(--accent-caution)" }}>⚠ {issues.length} {issues.length === 1 ? "issue" : "issues"} to fix{security ? " before using this on a shared network" : ""}</strong>
        <button className="tg-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? "Collapse" : "Show details"}</button>
        {onOpenHardware && <button className="tg-btn" onClick={onOpenHardware}>Open Hardware setup</button>}
      </div>
      {open && (
        <ul style={{ margin: "8px 0 2px", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 5 }}>
          {issues.map((i) => (
            <li key={i.id + i.message}>
              <span className="mono" style={{ fontSize: 10.5, marginRight: 6, color: "var(--accent-caution)" }}>{i.kind === "setup" ? "SETUP" : "SECURITY"}</span>
              {i.message}
              {i.fix && <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>Fix: {i.fix}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
