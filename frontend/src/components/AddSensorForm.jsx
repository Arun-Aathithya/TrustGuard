import { useState } from "react";
import { createSensor, errorMessage } from "../api/client";
import { SUPPORTED_SENSOR_TYPES } from "../lib/format";
import { AdminAccess, Field } from "./FormBits";

const card = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-hairline)",
  borderRadius: "var(--radius-md)",
  padding: "14px 16px",
};

/** Adds a Temperature (DS18B20) or Vibration (MPU6050) sensor with a custom name to one machine. */
export default function AddSensorForm({ machineId, onDone, onCancel }) {
  const [type, setType] = useState(SUPPORTED_SENSOR_TYPES[0].value);
  const [name, setName] = useState("");
  const [deviceId, setDeviceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const spec = SUPPORTED_SENSOR_TYPES.find((t) => t.value === type);

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { setError("Give the sensor a name."); return; }
    setBusy(true);
    setError(null);
    try {
      await createSensor({ machine_id: machineId, sensor_type: type, name: name.trim(), device_id: deviceId.trim() || null });
      await onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <form onSubmit={submit} aria-label="Add sensor" style={{ ...card, display: "flex", flexDirection: "column", gap: 12 }}>
        <Field label="Sensor type" hint={`${spec.model} · readings shown in ${spec.unit}`}>
          <select className="tg-input" value={type} onChange={(e) => setType(e.target.value)}>
            {SUPPORTED_SENSOR_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label} ({t.model})</option>)}
          </select>
        </Field>
        <Field label="Sensor name (required)" hint="Shown on the dashboard and on the OLED display.">
          <input className="tg-input" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} required
                 placeholder={type === "temperature" ? "e.g. Motor bearing" : "e.g. Gearbox vibration"} />
        </Field>
        <Field label="Device ID (optional)" hint="The ESP32's DEVICE_ID. Leave empty to link it later; the sensor shows no reading until a device reports.">
          <input className="tg-input" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} maxLength={80} pattern={String.raw`[A-Za-z0-9_.\-]{3,80}`} placeholder="ESP32-A1" />
        </Field>
        {error && <div role="alert" style={{ fontSize: 12.5, color: "var(--accent-fault)" }}>{error}</div>}
        <div style={{ display: "flex", gap: 8 }}>
          <button className="tg-btn" type="submit" disabled={busy}>{busy ? "Adding…" : "Add sensor"}</button>
          {onCancel && <button className="tg-btn" type="button" onClick={onCancel}>Cancel</button>}
        </div>
      </form>
      <AdminAccess />
    </div>
  );
}
