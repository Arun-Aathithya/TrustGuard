import { useState } from "react";
import { adminLogin, adminLogout, useAdmin } from "../hooks/useAdmin";

/** Small admin sign-in at the bottom of the sidebar. Visitors stay read-only unless they know the key. */
export default function AdminLogin() {
  const { enforced, isAdmin, checking } = useAdmin();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  if (enforced === null) return null;

  if (enforced === false) {
    return (
      <div className="tg-admin" role="status">
        <span className="tg-admin-dot" style={{ background: "var(--accent-caution)" }} />
        <span>No admin key set on the server. Everyone can edit.</span>
      </div>
    );
  }

  if (isAdmin) {
    return (
      <div className="tg-admin">
        <span className="tg-admin-dot" style={{ background: "var(--accent-trust)" }} />
        <span style={{ flex: 1 }}>Admin mode</span>
        <button className="tg-btn" onClick={adminLogout}>Log out</button>
      </div>
    );
  }

  const submit = async (e) => {
    e.preventDefault();
    if (!key.trim()) return;
    setBusy(true);
    const msg = await adminLogin(key);
    setBusy(false);
    setErr(msg);
    if (!msg) { setKey(""); setOpen(false); }
  };

  return (
    <div className="tg-admin" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="tg-admin-dot" style={{ background: "var(--text-tertiary)" }} />
        <span style={{ flex: 1 }}>{checking ? "Checking…" : "Viewing only"}</span>
        {!open && <button className="tg-btn" onClick={() => setOpen(true)}>Admin login</button>}
      </div>
      {open && (
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
          <label className="sr-only" htmlFor="admin-key-input">Admin key</label>
          <input id="admin-key-input" className="tg-input" type="password" autoComplete="off" placeholder="Admin key" value={key} onChange={(e) => setKey(e.target.value)} />
          {err && <div role="alert" style={{ fontSize: 11.5, color: "var(--accent-fault)" }}>{err}</div>}
          <div style={{ display: "flex", gap: 6 }}>
            <button className="tg-btn" type="submit" disabled={busy}>{busy ? "Checking…" : "Sign in"}</button>
            <button className="tg-btn" type="button" onClick={() => { setOpen(false); setErr(null); }}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}
