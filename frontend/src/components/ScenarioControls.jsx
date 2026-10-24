import { useState } from "react";
import { errorMessage, runSimulationTick } from "../api/client";

const SCENARIOS = [
  { key: "normal", label: "Normal" },
  { key: "machine_fault", label: "Machine fault (simulated)" },
  { key: "noisy", label: "Inject noise" },
  { key: "drift", label: "Inject drift" },
  { key: "failure", label: "Inject sensor failure" },
  { key: "missing", label: "Inject missing data" },
];

export default function ScenarioControls({ machineId, onTick }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const trigger = async (scenario) => {
    setBusy(scenario);
    try {
      const results = await runSimulationTick(machineId, scenario);
      onTick?.(results);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "14px 16px",
      }}
    >
      <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10 }}>
        SIMULATE SENSOR SCENARIO
      </div>
      {error && <div role="alert" style={{ fontSize: 12, color: "var(--accent-fault)", marginBottom: 8 }}>{error}</div>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {SCENARIOS.map((s) => (
          <button
            key={s.key}
            onClick={() => trigger(s.key)}
            disabled={busy !== null}
            style={{
              background: busy === s.key ? "var(--bg-panel-raised)" : "var(--bg-inset)",
              border: "1px solid var(--border-strong)",
              color: "var(--text-primary)",
              borderRadius: "var(--radius-sm)",
              padding: "7px 12px",
              fontSize: 12,
              cursor: busy ? "default" : "pointer",
              opacity: busy && busy !== s.key ? 0.5 : 1,
            }}
          >
            {busy === s.key ? "Running…" : s.label}
          </button>
        ))}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 8, lineHeight: 1.4 }}>
        One tick per click. "Inject" options corrupt the temperature sensor only (an artificial sensor fault);
        "Machine fault" simulates a genuine machine problem seen by every sensor.
      </div>
    </div>
  );
}
