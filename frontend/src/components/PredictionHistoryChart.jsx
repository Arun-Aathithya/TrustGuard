import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import { errorMessage, fetchPredictionHistory, runSimulationTick } from "../api/client";

const options = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: "index", intersect: false },
  plugins: {
    legend: {
      position: "top",
      align: "end",
      labels: { color: "#8a99a8", boxWidth: 10, boxHeight: 10, font: { size: 11 } },
    },
    tooltip: { backgroundColor: "#182029", borderColor: "#303e4c", borderWidth: 1 },
  },
  scales: {
    x: { grid: { color: "#1a222c" }, ticks: { color: "#566270", maxTicksLimit: 6, font: { size: 10 } } },
    y: {
      min: 0,
      max: 100,
      grid: { color: "#1a222c" },
      ticks: { color: "#566270", font: { size: 10 } },
    },
  },
  elements: { point: { radius: 0 }, line: { borderWidth: 2, tension: 0.3 } },
};

const MIN_POINTS = 2; // a line needs two points
const DEMO_TICKS = 10;

/** Shown instead of the chart until there are enough predictions: says why, and offers the way to fix it. */
function EmptyHistory({ count, dataSource, machineId, onTick, onOpenHardware, loadError }) {
  const [progress, setProgress] = useState(null); // null | number of ticks done
  const [error, setError] = useState(null);
  const canSimulate = dataSource !== "hardware";
  const running = progress !== null;

  const generate = async () => {
    setError(null);
    setProgress(0);
    let last = null;
    try {
      for (let i = 0; i < DEMO_TICKS; i++) {
        last = await runSimulationTick(machineId, "normal");
        setProgress(i + 1);
      }
      onTick?.(last);
    } catch (e) {
      setError(errorMessage(e));
      if (last) onTick?.(last);
    } finally {
      setProgress(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 12.5, color: "var(--text-secondary)" }}>
      <div>
        <strong style={{ color: "var(--text-primary)" }}>Not enough history to draw a chart yet</strong>{" "}
        <span className="mono">({count} of {MIN_POINTS} prediction{MIN_POINTS === 1 ? "" : "s"} needed)</span>
      </div>
      {loadError && <div role="alert" style={{ color: "var(--accent-fault)" }}>Could not load history: {loadError}</div>}
      <div>
        Every time the pipeline runs it stores one prediction (failure risk, confidence and trust). The chart appears once there are at least {MIN_POINTS}.
      </div>
      {canSimulate && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
          <button className="tg-btn" onClick={generate} disabled={running}>
            {running ? `Running simulation… ${progress}/${DEMO_TICKS}` : `Run ${DEMO_TICKS} simulation ticks`}
          </button>
          <span style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>
            Simulated data only (normal scenario){dataSource === "mixed" ? "; real hardware sensors are not touched" : ""}. You can also use the scenario buttons below.
          </span>
        </div>
      )}
      {dataSource !== "simulation" && (
        <div>
          {dataSource === "hardware" ? "All sensors on this machine are real hardware, so history builds up by itself: " : "For the hardware sensors: "}
          each reading from the ESP32 re-runs the pipeline (at most once every 2 s). With the sensor online and publishing every 5 s you get a chart within about a minute.
          If nothing is arriving, finish the hardware setup checklist.{" "}
          {onOpenHardware && <button className="tg-btn" onClick={onOpenHardware}>Open Hardware setup</button>}
        </div>
      )}
      {error && <div role="alert" style={{ color: "var(--accent-fault)" }}>Simulation stopped: {error}</div>}
    </div>
  );
}

export default function PredictionHistoryChart({ machineId, refreshKey, dataSource, onTick, onOpenHardware }) {
  const [rows, setRows] = useState([]);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchPredictionHistory(machineId, 60)
      .then((data) => { if (!cancelled) { setRows(data); setLoadError(null); } })
      .catch((e) => !cancelled && setLoadError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [machineId, refreshKey]);

  const labels = rows.map((r) => new Date(r.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));

  const data = {
    labels,
    datasets: [
      {
        label: "Failure Risk %",
        data: rows.map((r) => r.failure_risk),
        borderColor: "#de5a5a",
        fill: false,
      },
      {
        label: "Prediction Confidence %",
        data: rows.map((r) => r.prediction_confidence),
        borderColor: "#4a9fd8",
        fill: false,
      },
      {
        label: "Overall Trust %",
        data: rows.map((r) => r.overall_trust),
        borderColor: "#23c4a8",
        fill: false,
      },
    ],
  };

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "16px 18px",
      }}
    >
      <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10 }}>
        PREDICTION HISTORY
      </div>
      <div style={{ minHeight: 220 }}>
        {rows.length > 1 ? (
          <div role="img" aria-label="Failure risk, prediction confidence and overall trust over time" style={{ height: 220 }}><Line data={data} options={options} /></div>
        ) : (
          <EmptyHistory count={rows.length} dataSource={dataSource} machineId={machineId} onTick={onTick} onOpenHardware={onOpenHardware} loadError={loadError} />
        )}
      </div>
    </div>
  );
}
