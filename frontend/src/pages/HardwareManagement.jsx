import { useEffect, useState } from "react";
import {
  errorMessage, fetchTelegramStatus, registerDevice, sendTelegramTest, testDevice, unregisterDevice,
} from "../api/client";
import { AdminAccess, Field } from "../components/FormBits";
import SetupChecklist from "../components/SetupChecklist";
import { DeviceStatusPill } from "../components/StatusBadges";
import { absTime, relSeconds, relTime, SENSOR_LABELS, SUPPORTED_SENSOR_TYPES } from "../lib/format";

const card = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-hairline)",
  borderRadius: "var(--radius-md)",
  padding: "14px 16px",
};
const heading = { fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10, letterSpacing: "0.02em" };
const SENSOR_TYPES = SUPPORTED_SENSOR_TYPES.map((t) => t.value); // Temperature (DS18B20) and Vibration (MPU6050) only

function RegisterForm({ machines, initial, onDone, onCancel }) {
  const [form, setForm] = useState({
    machine_id: initial?.machine_id ?? machines[0]?.machine.id ?? "",
    sensor_type: initial?.sensor_type ?? "temperature",
    device_id: initial?.device_id ?? "",
    mqtt_topic: "",
    unit: initial?.unit ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await registerDevice({
        machine_id: Number(form.machine_id),
        sensor_type: form.sensor_type,
        device_id: form.device_id.trim(),
        mqtt_topic: form.mqtt_topic.trim() || undefined,
        unit: form.unit.trim() || undefined,
      });
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ ...card, display: "flex", flexDirection: "column", gap: 12 }} aria-label="Register device">
      <div style={heading}>REGISTER DEVICE → MACHINE SENSOR</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 12 }}>
        <Field label="Machine">
          <select className="tg-input" value={form.machine_id} onChange={set("machine_id")} required>
            {machines.map((d) => <option key={d.machine.id} value={d.machine.id}>{d.machine.name}</option>)}
          </select>
        </Field>
        <Field label="Sensor type" hint="Accelerometers map to Vibration.">
          <select className="tg-input" value={form.sensor_type} onChange={set("sensor_type")}>
            {SENSOR_TYPES.map((t) => <option key={t} value={t}>{SENSOR_LABELS[t]}</option>)}
          </select>
        </Field>
        <Field label="Device ID" hint="Must match DEVICE_ID in the ESP32 firmware.">
          <input className="tg-input" value={form.device_id} onChange={set("device_id")} required minLength={3} maxLength={80} pattern="[A-Za-z0-9_.\-]+" placeholder="ESP32-A1" />
        </Field>
        <Field label="MQTT topic (optional)" hint="Default: trustguard/sensors/<machine>/<type>">
          <input className="tg-input mono" value={form.mqtt_topic} onChange={set("mqtt_topic")} />
        </Field>
        <Field label="Unit (optional)" hint={form.sensor_type === "vibration" ? "An accelerometer reports m/s², but the model works in mm/s. Enter the unit the device really sends and calibrate it (docs/HARDWARE_SETUP.md 4b); uncalibrated vibration is kept out of risk scoring." : undefined}>
          <input className="tg-input" value={form.unit} onChange={set("unit")} maxLength={20} placeholder={form.sensor_type === "vibration" ? "m/s²" : "°C"} />
        </Field>
      </div>
      {error && <div role="alert" style={{ color: "var(--accent-fault)", fontSize: 12.5 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="tg-btn" type="submit" disabled={busy}>{busy ? "Registering…" : "Register device"}</button>
        <button className="tg-btn" type="button" onClick={onCancel}>Cancel</button>
      </div>
      <div style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>
        Registering switches this sensor from simulation to real hardware. It will show Offline until the first valid message arrives.
      </div>
    </form>
  );
}

function TestResult({ result, onClose }) {
  return (
    <div style={{ ...card, borderColor: result.ok ? "var(--accent-trust)" : "var(--accent-caution)" }} role="status">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <strong style={{ fontSize: 13 }}>{result.ok ? "✓ " : "⚠ "}{result.message}</strong>
        <button className="tg-btn" onClick={onClose}>Close</button>
      </div>
      <ul style={{ margin: "10px 0 0", padding: 0, listStyle: "none", fontSize: 12.5, display: "flex", flexDirection: "column", gap: 4 }}>
        {result.checks.map((c) => (
          <li key={c.name}>
            <span aria-hidden="true" style={{ color: c.ok ? "var(--accent-trust)" : "var(--accent-fault)" }}>{c.ok ? "✓" : "✗"}</span>{" "}
            <span className="sr-only">{c.ok ? "Passed: " : "Failed: "}</span>
            {c.name} <span style={{ color: "var(--text-tertiary)" }}>({c.detail})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TelegramCard() {
  const [st, setSt] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const data = await fetchTelegramStatus();
        if (alive) { setSt(data); setLoadError(null); }
      } catch (e) {
        if (alive) setLoadError(errorMessage(e));
      }
    };
    load();
    const id = setInterval(load, 10000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const sendTest = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await sendTelegramTest();
      setResult(r.ok ? { ok: true, text: `Test message delivered to ${r.delivered} of ${r.recipients} chat(s).` } : { ok: false, text: r.detail || "Delivery failed." });
    } catch (e) {
      setResult({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  const state = !st ? "" : !st.enabled ? "○ Disabled (TELEGRAM_ENABLED=false)" : st.polling ? "● Running" : "○ Not connected";
  const color = st?.enabled && st?.polling ? "var(--accent-trust)" : "var(--accent-caution)";
  return (
    <section aria-label="Telegram bot" style={card}>
      <div style={heading}>TELEGRAM BOT (ALERTS &amp; STATUS ON YOUR PHONE)</div>
      {loadError && <div role="alert" style={{ color: "var(--accent-fault)", fontSize: 12.5 }}>Could not load Telegram status: {loadError}</div>}
      {!st && !loadError && <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>Loading…</div>}
      {st && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, fontSize: 12.5 }}>
          <div>Status: <strong style={{ color }}>{state}</strong></div>
          <div>Bot: <span className="mono">{st.bot_username ? `@${st.bot_username}` : "—"}</span></div>
          <div>Authorised chats: <span className="mono">{st.recipients}</span></div>
          <div>Alerts sent: <span className="mono">{st.messages_sent}</span> · commands answered: <span className="mono">{st.commands_handled}</span></div>
          {st.last_error && <div style={{ color: "var(--accent-fault)", gridColumn: "1 / -1" }}>Last error: {st.last_error}</div>}
          {st.enabled && st.recipients === 0 && (
            <div role="status" style={{ color: "var(--accent-caution)", gridColumn: "1 / -1" }}>
              No chat is authorised yet. Send /chatid to the bot, put that number in TELEGRAM_ALLOWED_CHAT_IDS and restart the backend.
            </div>
          )}
          <div style={{ gridColumn: "1 / -1", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button className="tg-btn" onClick={sendTest} disabled={busy || !st.enabled}>{busy ? "Sending…" : "Send test message"}</button>
            <span style={{ color: "var(--text-tertiary)" }}>Needs the admin key (see Admin access below). Commands: /status /machine /alerts /devices /mute</span>
          </div>
          {result && <div role={result.ok ? "status" : "alert"} style={{ gridColumn: "1 / -1", color: result.ok ? "var(--accent-trust)" : "var(--accent-fault)" }}>{result.text}</div>}
        </div>
      )}
    </section>
  );
}

export default function HardwareManagement({ dashboards, hardware }) {
  const { broker, devices, events, loading, error, reload } = hardware;
  const [showForm, setShowForm] = useState(false);
  const [prefill, setPrefill] = useState(null);
  const [onlyRegistered, setOnlyRegistered] = useState(false);
  const [testing, setTesting] = useState(null);
  const [testResult, setTestResult] = useState(null);
  const [actionError, setActionError] = useState(null);

  const rows = onlyRegistered ? devices.filter((d) => d.data_source === "hardware") : devices;

  const runTest = async (d) => {
    setTesting(d.sensor_id);
    setActionError(null);
    try {
      setTestResult({ ...(await testDevice(d.sensor_id)), name: `${d.machine_name} · ${d.sensor_type}` });
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setTesting(null);
    }
  };

  const remove = async (d) => {
    if (!window.confirm(`Unregister ${d.device_id} and return ${d.machine_name} / ${d.sensor_type} to simulation?`)) return;
    setActionError(null);
    try {
      await unregisterDevice(d.sensor_id);
      reload();
    } catch (e) {
      setActionError(errorMessage(e));
    }
  };

  return (
    <div className="tg-page" style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 1180 }}>
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Hardware management</h1>
        <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 4 }}>
          Map physical devices to machine sensors and monitor their connection. Simulation controls live on each machine page, separately.
        </div>
      </div>

      {error && <div role="alert" style={{ ...card, borderColor: "var(--accent-fault)", fontSize: 13 }}>Could not load hardware data: {error}</div>}

      <SetupChecklist broker={broker} devices={devices} loading={loading} />

      <section aria-label="MQTT broker" style={card}>
        <div style={heading}>MQTT BROKER</div>
        {!broker ? (
          <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>{loading ? "Loading…" : "Unavailable."}</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, fontSize: 12.5 }}>
            <div>
              Status:{" "}
              <strong style={{ color: broker.connected ? "var(--accent-trust)" : "var(--accent-caution)" }}>
                {broker.connected ? "● Connected" : broker.enabled ? "○ Not connected" : "○ Disabled (MQTT_ENABLED=false)"}
              </strong>
            </div>
            <div>Host: <span className="mono">{broker.host ? `${broker.host}:${broker.port}` : "—"}</span></div>
            <div>Encryption: {broker.enabled ? (broker.tls ? "TLS on" : "⚠ TLS off") : "—"}</div>
            <div>Messages received: <span className="mono">{broker.messages_received}</span> (last {relTime(broker.last_message_at)})</div>
            <div>Base topic: <span className="mono">{broker.base_topic}</span></div>
            {broker.last_error && <div style={{ color: "var(--accent-fault)" }}>Last error: {broker.last_error}</div>}
            {broker.security_warnings?.length > 0 && (
              <div role="status" style={{ color: "var(--accent-caution)", gridColumn: "1 / -1" }}>
                <strong>Security checklist (fix before using a shared network):</strong>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {broker.security_warnings.map((w) => <li key={w}>{w}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      <TelegramCard />

      <AdminAccess />

      {actionError && <div role="alert" style={{ color: "var(--accent-fault)", fontSize: 13 }}>{actionError}</div>}
      {testResult && <TestResult result={testResult} onClose={() => setTestResult(null)} />}

      {showForm ? (
        <RegisterForm
          machines={dashboards}
          initial={prefill}
          onCancel={() => setShowForm(false)}
          onDone={() => { setShowForm(false); setPrefill(null); reload(); }}
        />
      ) : (
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="tg-btn" onClick={() => { setPrefill(null); setShowForm(true); }} disabled={dashboards.length === 0}>+ Register device</button>
          <label style={{ fontSize: 12.5, color: "var(--text-secondary)", display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={onlyRegistered} onChange={(e) => setOnlyRegistered(e.target.checked)} /> Show registered hardware only
          </label>
        </div>
      )}

      <section aria-label="Devices" style={{ ...card, padding: 0, overflowX: "auto" }}>
        <div style={{ ...heading, padding: "14px 16px 0" }}>DEVICES &amp; SENSOR MAPPING</div>
        {loading ? (
          <div style={{ padding: 16, fontSize: 13, color: "var(--text-tertiary)" }}>Loading devices…</div>
        ) : rows.length === 0 ? (
          <div style={{ padding: 16, fontSize: 13, color: "var(--text-tertiary)" }}>
            {onlyRegistered ? "No hardware devices registered yet. Use “Register device” to add one." : "No sensors found."}
          </div>
        ) : (
          <div className="tg-scroll-x"><table className="tg-table">
            <thead>
              <tr>
                <th scope="col">Machine</th><th scope="col">Sensor</th><th scope="col">Device ID</th><th scope="col">MQTT topic</th>
                <th scope="col">Status</th><th scope="col">Last seen</th><th scope="col">Rejected (1h)</th><th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const hw = d.data_source === "hardware";
                return (
                  <tr key={d.sensor_id}>
                    <td>{d.machine_name}</td>
                    <td>{SENSOR_LABELS[d.sensor_type] || d.sensor_type}</td>
                    <td className="mono">{hw ? d.device_id : <span style={{ color: "var(--text-tertiary)" }}>not registered</span>}</td>
                    <td className="mono" style={{ color: hw ? undefined : "var(--text-tertiary)" }}>{d.mqtt_topic || "—"}</td>
                    <td><DeviceStatusPill status={d.device_status} />{d.unit_warning && <div title={d.unit_warning} style={{ fontSize: 10.5, color: "var(--accent-caution)", marginTop: 3 }}>⚠ units not converted</div>}{d.unit_status === "calibrated_index" && <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 3 }}>calibrated index</div>}</td>
                    <td title={absTime(d.last_seen_at)}>{hw ? (d.last_seen_at ? relSeconds(d.seconds_since_seen) : "never") : "—"}</td>
                    <td className="mono" style={{ color: d.problems_last_hour ? "var(--accent-caution)" : undefined }}>{hw ? d.problems_last_hour : "—"}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        {hw ? (
                          <>
                            <button className="tg-btn" disabled={testing === d.sensor_id} onClick={() => runTest(d)} aria-label={`Test connection for ${d.device_id}`}>
                              {testing === d.sensor_id ? "Testing…" : "Test connection"}
                            </button>
                            <button className="tg-btn" onClick={() => remove(d)} aria-label={`Unregister ${d.device_id}`}>Unregister</button>
                          </>
                        ) : (
                          <button
                            className="tg-btn"
                            onClick={() => { setPrefill({ machine_id: d.machine_id, sensor_type: d.sensor_type, unit: "" }); setShowForm(true); window.scrollTo?.({ top: 0 }); }}
                          >
                            Register…
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        )}
      </section>

      <section aria-label="Ingestion problems" style={{ ...card, padding: 0, overflowX: "auto" }}>
        <div style={{ ...heading, padding: "14px 16px 0" }}>RECENT INGESTION PROBLEMS (REJECTED, DELAYED, MISSING, OUT OF RANGE)</div>
        {events.length === 0 ? (
          <div style={{ padding: 16, fontSize: 13, color: "var(--text-tertiary)" }}>No problems recorded. Every message received so far was clean.</div>
        ) : (
          <div className="tg-scroll-x"><table className="tg-table">
            <thead><tr><th scope="col">When</th><th scope="col">Type</th><th scope="col">Result</th><th scope="col">Device</th><th scope="col">Detail</th></tr></thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td title={absTime(e.created_at)}>{relTime(e.created_at)}</td>
                  <td className="mono">{e.event_type}</td>
                  <td>{e.accepted ? "Stored with warning" : "Rejected"}</td>
                  <td className="mono">{e.device_id || "—"}</td>
                  <td>{e.detail}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}
