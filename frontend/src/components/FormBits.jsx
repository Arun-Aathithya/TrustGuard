import { useState } from "react";
import { getAdminKey, setAdminKey } from "../api/client";

const card = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-hairline)",
  borderRadius: "var(--radius-md)",
  padding: "14px 16px",
};

export function Field({ label, children, hint }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "var(--text-secondary)" }}>
      {label}
      {children}
      {hint && <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{hint}</span>}
    </label>
  );
}

export function AdminAccess() {
  const [value, setValue] = useState(getAdminKey());
  const [saved, setSaved] = useState(Boolean(getAdminKey()));
  return (
    <form
      style={{ ...card, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}
      onSubmit={(e) => { e.preventDefault(); setAdminKey(value.trim()); setSaved(Boolean(value.trim())); }}
    >
      <Field label="Admin access: API key" hint="Needed to add or remove machines and devices when the server has ADMIN_API_KEY set. Kept only in this browser tab.">
        <input className="tg-input" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} style={{ minWidth: 240 }} />
      </Field>
      <button className="tg-btn" type="submit">{saved ? "Update key" : "Use key"}</button>
      {saved && (
        <button className="tg-btn" type="button" onClick={() => { setValue(""); setAdminKey(""); setSaved(false); }}>Forget key</button>
      )}
    </form>
  );
}
