import { DataSourceBadge, DeviceStatusPill } from "../components/StatusBadges";
import { relTime } from "../lib/format";

const card = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-hairline)",
  borderRadius: "var(--radius-md)",
  padding: "14px 16px",
};

function Metric({ label, value, sub, color }) {
  return (
    <div style={{ ...card, display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 11, letterSpacing: "0.04em", color: "var(--text-tertiary)" }}>{label.toUpperCase()}</div>
      <div className="mono" style={{ fontSize: 26, fontWeight: 600, color: color || "var(--text-primary)" }}>{value}</div>
      <div style={{ fontSize: 11.5, color: "var(--text-secondary)", lineHeight: 1.4 }}>{sub}</div>
    </div>
  );
}

const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const pct = (v) => (v == null ? "—" : `${Math.round(v)}%`);
const FAULT_TYPES = ["sensor_fault", "device_offline", "cross_disagreement"];

export default function Overview({ dashboards, hardware, onOpenMachine, onOpenHardware }) {
  const { summary, broker, error, loading } = hardware;
  const sensors = dashboards.flatMap((d) => d.sensors.map((s) => s.sensor));
  const stale = sensors.filter((s) => s.data_source === "hardware" && ["stale", "offline"].includes(s.device_status)).length;
  const faults = dashboards.flatMap((d) => d.open_alerts).filter((a) => FAULT_TYPES.includes(a.alert_type)).length;
  const preds = dashboards.map((d) => d.latest_prediction).filter(Boolean);
  const maxRisk = preds.length ? Math.max(...preds.map((p) => p.failure_risk)) : null;
  const avgRisk = avg(preds.map((p) => p.failure_risk));
  const avgConf = avg(preds.map((p) => p.prediction_confidence));
  const hasTrust = (d) => d.sensors.some((s) => s.trust); // overall_trust is a default 100 when nothing has been scored
  const avgTrust = avg(dashboards.filter(hasTrust).map((d) => d.overall_trust));
  const source = summary?.active_data_source || (sensors.some((s) => s.data_source === "hardware") ? "mixed" : "simulation");
  const riskColor = maxRisk >= 60 ? "var(--accent-fault)" : maxRisk >= 35 ? "var(--accent-caution)" : "var(--accent-trust)";

  return (
    <div className="tg-page" style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 1180 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", justifyContent: "space-between" }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>Fleet overview</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Active data source</span>
          <DataSourceBadge source={source} size="lg" />
        </div>
      </div>

      {error && (
        <div role="alert" style={{ ...card, borderColor: "var(--accent-caution)", fontSize: 13 }}>
          Hardware status unavailable: {error}. Dashboard data below is still shown.
        </div>
      )}
      {source !== "simulation" && summary && (
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
          MQTT broker: {summary.broker.connected ? "connected" : summary.broker.enabled ? "not connected" : "disabled"} ·{" "}
          {summary.hardware_sensors} hardware sensors, {summary.simulated_sensors} simulated.{" "}
          {summary.rejected_last_hour > 0 && <strong style={{ color: "var(--accent-caution)" }}>{summary.rejected_last_hour} rejected messages in the last hour. </strong>}
          <button className="tg-btn" onClick={onOpenHardware}>Open Hardware management</button>
        </div>
      )}

      <section aria-label="Connectivity and faults">
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10 }}>CONNECTIVITY &amp; FAULTS</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 12 }}>
          <Metric
            label="Connected devices"
            value={loading ? "…" : summary ? `${summary.devices_online + summary.devices_stale}/${summary.hardware_sensors}` : "—"}
            sub={summary ? `${summary.devices_online} online · ${summary.devices_stale} stale · ${summary.devices_offline} offline (hardware sensors)` : "Loading device status…"}
          />
          <Metric label="Stale sensors" value={stale} color={stale ? "var(--accent-caution)" : undefined} sub="Hardware sensors with delayed or no data" />
          <Metric label="Active faults" value={faults} color={faults ? "var(--accent-fault)" : undefined} sub="Open sensor-fault, offline and disagreement alerts" />
        </div>
      </section>

      <section aria-label="Three separate measures">
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10 }}>THREE SEPARATE MEASURES (NOT THE SAME THING)</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
          <Metric label="Sensor trust (data reliability)" value={pct(avgTrust)} color="var(--accent-trust)" sub="How reliable the incoming sensor data is. Average across machines." />
          <Metric label="Machine failure risk" value={pct(maxRisk)} color={maxRisk == null ? undefined : riskColor} sub={`Estimated chance of failure. Highest machine shown; fleet average ${pct(avgRisk)}.`} />
          <Metric label="Prediction confidence" value={pct(avgConf)} color="var(--accent-signal)" sub="How certain the model is, given data quality. Average across machines." />
        </div>
      </section>

      <section aria-label="Machines">
        <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10 }}>MACHINES</div>
        {dashboards.length === 0 ? (
          <div style={{ ...card, fontSize: 13, color: "var(--text-tertiary)" }}>No machines yet.</div>
        ) : (
          <div style={{ ...card, padding: 0, overflowX: "auto" }}>
            <table className="tg-table">
              <caption style={{ position: "absolute", left: -9999 }}>Machines with data source, risk, confidence and trust</caption>
              <thead>
                <tr>
                  <th scope="col">Machine</th><th scope="col">Data source</th><th scope="col">Failure risk</th>
                  <th scope="col">Confidence</th><th scope="col">Sensor trust</th><th scope="col">Open alerts</th><th scope="col">Last data</th>
                </tr>
              </thead>
              <tbody>
                {dashboards.map((d) => {
                  const p = d.latest_prediction;
                  const hwStale = d.sensors.some((s) => s.sensor.data_source === "hardware" && s.sensor.device_status !== "online");
                  const last = d.sensors.map((s) => s.sensor.last_data_at).filter(Boolean).sort().pop();
                  return (
                    <tr key={d.machine.id}>
                      <td>
                        <button className="tg-btn" style={{ border: "none", padding: 0, color: "var(--accent-signal)" }} onClick={() => onOpenMachine(d.machine.id)}>
                          {d.machine.name}
                        </button>
                      </td>
                      <td><DataSourceBadge source={d.data_source} /> {hwStale && <DeviceStatusPill status="stale" />}</td>
                      <td className="mono">{pct(p?.failure_risk)}</td>
                      <td className="mono">{pct(p?.prediction_confidence)}</td>
                      <td className="mono">{hasTrust(d) ? pct(d.overall_trust) : "—"}</td>
                      <td className="mono">{d.open_alerts.length}</td>
                      <td className="mono">{relTime(last)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
