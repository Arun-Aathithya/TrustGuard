import { useEffect, useState } from "react";
import AlertsFeed from "../components/AlertsFeed";
import CrossSensorPanel from "../components/CrossSensorPanel";
import DemoGuide from "../components/DemoGuide";
import SensorDetail from "../components/SensorDetail";
import PredictionHistoryChart from "../components/PredictionHistoryChart";
import PredictionPanel from "../components/PredictionPanel";
import RecommendationBanner from "../components/RecommendationBanner";
import ScenarioControls from "../components/ScenarioControls";
import SensorCard from "../components/SensorCard";
import { DataSourceBadge } from "../components/StatusBadges";
import FreshnessBanner, { LastUpdateLine } from "../components/FreshnessBanner";
import { deleteMachine, deleteSensor, errorMessage } from "../api/client";
import AddSensorForm from "../components/AddSensorForm";
import { sensorName } from "../lib/format";

const STATUS_META = {
  operational: { label: "Operational", color: "var(--accent-trust)" },
  at_risk: { label: "At Risk", color: "var(--accent-caution)" },
  down: { label: "Down", color: "var(--accent-fault)" },
};

export default function Dashboard({ dashboard, onSimulationResult, onOpenHardware, onRemoved, onChanged }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const [detailId, setDetailId] = useState(null);
  const [localAlerts, setLocalAlerts] = useState(dashboard.open_alerts);
  const [removeError, setRemoveError] = useState(null);
  const [adding, setAdding] = useState(false);

  const handleSensorAdded = async () => {
    setAdding(false);
    await onChanged?.();
  };

  const handleRemoveSensor = async (sensor) => {
    if (!window.confirm(`Remove sensor "${sensorName(sensor)}" and all of its stored readings? This cannot be undone.`)) return;
    try {
      await deleteSensor(sensor.id);
      setRemoveError(null);
      if (detailId === sensor.id) setDetailId(null);
      await onChanged?.();
    } catch (e) {
      setRemoveError(errorMessage(e));
    }
  };

  const handleRemove = async () => {
    if (!window.confirm(`Remove "${dashboard.machine.name}" and all of its sensors, readings, alerts and predictions? This cannot be undone.`)) return;
    try {
      await deleteMachine(dashboard.machine.id);
      setRemoveError(null);
      await onRemoved?.();
    } catch (e) {
      setRemoveError(errorMessage(e));
    }
  };

  useEffect(() => {
    setLocalAlerts(dashboard.open_alerts);
  }, [dashboard.machine.id, dashboard.open_alerts]);

  const meta = STATUS_META[dashboard.machine.status] || STATUS_META.operational;
  const alerts = localAlerts;

  const hasHardware = dashboard.data_source !== "simulation";
  const hardwareOnly = dashboard.data_source === "hardware";

  const handleTick = (results) => {
    onSimulationResult?.(results);
    setRefreshKey((k) => k + 1);
  };

  const handleResolved = (alertId) => {
    setLocalAlerts((prev) => prev.filter((a) => a.id !== alertId));
  };

  return (
    <div className="tg-page" style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 1180 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>{dashboard.machine.name}</h1>
            {dashboard.sensors.length > 0 && <DataSourceBadge source={dashboard.data_source} size="lg" />}
            <span
              className="mono"
              style={{
                fontSize: 10.5,
                padding: "2px 8px",
                borderRadius: "var(--radius-sm)",
                color: meta.color,
                border: `1px solid ${meta.color}`,
              }}
            >
              {meta.label.toUpperCase()}
            </span>
          </div>
          <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 4 }}>
            {[dashboard.machine.machine_type, dashboard.machine.location].filter(Boolean).join(" · ")}
          </div>
          <LastUpdateLine sensors={dashboard.sensors.map((s) => s.sensor)} />
        </div>
        <button className="tg-btn" onClick={handleRemove}>Remove machine</button>
      </div>
      {removeError && <div role="alert" style={{ fontSize: 12.5, color: "var(--accent-fault)" }}>{removeError}</div>}

      {dashboard.sensors.length === 0 && (
        <div className="tg-panel" role="status" style={{ fontSize: 13, lineHeight: 1.55 }}>
          <strong>No sensors on this machine yet.</strong>{" "}
          <span style={{ color: "var(--text-secondary)" }}>
            No readings, risk or trust figures exist until a sensor is added and reports.
          </span>
        </div>
      )}
      {dashboard.sensors.length === 0 && !adding && <div><button className="tg-btn" onClick={() => setAdding(true)}>+ Add sensor</button></div>}
      {dashboard.sensors.length === 0 && adding && <AddSensorForm machineId={dashboard.machine.id} onDone={handleSensorAdded} onCancel={() => setAdding(false)} />}

      {dashboard.sensors.length > 0 && <FreshnessBanner sensors={dashboard.sensors.map((s) => s.sensor)} />}

      {dashboard.latest_prediction ? (
        <PredictionPanel dashboard={dashboard} />
      ) : dashboard.sensors.length > 0 && (
        <div className="tg-panel" role="status" style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          No prediction yet. Risk, confidence and trust appear only after sensor readings have been processed.
        </div>
      )}

      {dashboard.sensors.length > 0 && (
        <>
      <RecommendationBanner dashboard={dashboard} />

      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <div style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>SENSORS ({dashboard.sensors.length})</div>
          {!adding && <button className="tg-btn" onClick={() => setAdding(true)}>+ Add sensor</button>}
        </div>
        {adding && <div style={{ marginBottom: 12 }}><AddSensorForm machineId={dashboard.machine.id} onDone={handleSensorAdded} onCancel={() => setAdding(false)} /></div>}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12 }}>
          {dashboard.sensors.map((s) => (
            <SensorCard key={s.sensor.id} snapshot={s} onOpen={setDetailId} onRemove={handleRemoveSensor} />
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16, alignItems: "start" }}>
        <PredictionHistoryChart machineId={dashboard.machine.id} refreshKey={refreshKey} dataSource={dashboard.data_source} onTick={handleTick} onOpenHardware={onOpenHardware} />
        <CrossSensorPanel dashboard={dashboard} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16, alignItems: "start" }}>
        <AlertsFeed alerts={alerts} onResolved={handleResolved} />
        <section aria-label="Simulation controls" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ fontSize: 11.5, color: "var(--accent-signal)" }} className="mono">
            ◇ SIMULATION ONLY. {hasHardware ? "Never changes real hardware sensors; affects simulated sensors only." : "No hardware is connected to this machine."}
          </div>
          {!hardwareOnly && <DemoGuide machineId={dashboard.machine.id} onTick={handleTick} />}
          {hardwareOnly ? (
            <div style={{ fontSize: 12.5, color: "var(--text-tertiary)" }}>
              All sensors on this machine are real hardware, so there is nothing to simulate. Unregister a sensor on the Hardware page to simulate it.
            </div>
          ) : (
            <ScenarioControls machineId={dashboard.machine.id} onTick={handleTick} />
          )}
        </section>
      </div>
        </>
      )}
      {detailId !== null && dashboard.sensors.find((s) => s.sensor.id === detailId) && (
        <SensorDetail snapshot={dashboard.sensors.find((s) => s.sensor.id === detailId)} onClose={() => setDetailId(null)} />
      )}
    </div>
  );
}
