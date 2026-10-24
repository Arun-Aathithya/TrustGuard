import { useState } from "react";
import { errorMessage, runSimulationTick } from "../api/client";

const STEPS = [
  { key: "normal", n: 1, title: "Normal operation", kind: "SIMULATED", ticks: 3, text: "Stable readings, high trust, low risk." },
  { key: "drift", n: 2, title: "Sensor fault (injected)", kind: "INJECTED FAULT", ticks: 12, text: "Temperature sensor drifts while the others stay normal. Expect lower trust and confidence, a 'suspected sensor fault' explanation." },
  { key: "machine_fault", n: 3, title: "Machine failure (simulated)", kind: "SIMULATED", ticks: 4, text: "All sensors consistently show overheating, vibration and load. Expect high risk with high confidence." },
];

/** Guided 3-step demo. Everything here is simulated; it never touches real hardware sensors. */
export default function DemoGuide({ machineId, onTick }) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const run = async (step) => {
    setBusy(step.key); setError(null);
    try {
      let last = null;
      for (let i = 0; i < step.ticks; i++) last = await runSimulationTick(machineId, step.key);
      onTick?.(last); setDone(step.key);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(null); }
  };

  return (
    <section aria-label="Guided demo" className="tg-panel" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="mono" style={{ fontSize: 11.5, color: "var(--accent-signal)" }}>◇ GUIDED DEMO · SIMULATION ONLY (artificial data and faults, not real hardware)</div>
      {error && <div role="alert" style={{ fontSize: 12.5, color: "var(--accent-fault)" }}>{error}</div>}
      <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 10 }}>
        {STEPS.map((s) => (
          <li key={s.key} style={{ display: "flex", gap: 10, alignItems: "flex-start", flexWrap: "wrap" }}>
            <button className="tg-btn" disabled={busy !== null} onClick={() => run(s)} aria-describedby={`demo-${s.key}`} style={done === s.key ? { borderColor: "var(--accent-trust)" } : undefined}>
              {busy === s.key ? "Running…" : `${s.n}. ${s.title}`}
            </button>
            <div id={`demo-${s.key}`} style={{ flex: "1 1 220px", fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.45 }}>
              <span className="mono" style={{ color: "var(--accent-caution)" }}>{s.kind}</span> — {s.text}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
