import { useState } from "react";
import { createMachine, errorMessage } from "../api/client";
import { AdminAccess, Field } from "../components/FormBits";

const card = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-hairline)",
  borderRadius: "var(--radius-md)",
  padding: "14px 16px",
};

/**
 * Manual machine setup. Nothing is pre-loaded: a machine only exists once the user adds it here,
 * and it shows no readings until a registered sensor actually reports one.
 */
export default function AddMachine({ empty, onCreated, onOpenHardware }) {
  const [form, setForm] = useState({ name: "", machine_type: "", location: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { setError("Give the machine a name."); return; }
    setBusy(true);
    setError(null);
    try {
      const machine = await createMachine({
        name: form.name.trim(),
        machine_type: form.machine_type.trim() || "generic",
        location: form.location.trim() || null,
      });
      setForm({ name: "", machine_type: "", location: "" });
      await onCreated(machine);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tg-page" style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 720 }}>
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>{empty ? "No machines yet" : "Add a machine"}</h1>
        <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.55, margin: "8px 0 0" }}>
          Nothing is pre-loaded. Add the machine you want to monitor, then connect your ESP32 sensors to it under{" "}
          {onOpenHardware ? <button className="tg-btn" style={{ border: "none", padding: 0, color: "var(--accent-signal)" }} onClick={onOpenHardware}>Hardware management</button> : "Hardware management"}.
          A machine shows no readings, risk or trust figures until a sensor really reports.
        </p>
      </div>

      <form onSubmit={submit} aria-label="Add machine" style={{ ...card, display: "flex", flexDirection: "column", gap: 12 }}>
        <Field label="Machine name (required)">
          <input className="tg-input" value={form.name} onChange={set("name")} maxLength={120} required placeholder="e.g. Lathe 2" />
        </Field>
        <Field label="Machine type (optional)" hint="Free text. Defaults to “generic”.">
          <input className="tg-input" value={form.machine_type} onChange={set("machine_type")} maxLength={120} />
        </Field>
        <Field label="Location (optional)">
          <input className="tg-input" value={form.location} onChange={set("location")} maxLength={120} />
        </Field>
        {error && <div role="alert" style={{ fontSize: 12.5, color: "var(--accent-fault)" }}>{error}</div>}
        <div><button className="tg-btn" type="submit" disabled={busy}>{busy ? "Adding…" : "Add machine"}</button></div>
      </form>

      <AdminAccess />
    </div>
  );
}
