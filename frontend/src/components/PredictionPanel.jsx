import ArcGauge from "./ArcGauge";

export default function PredictionPanel({ dashboard }) {
  const prediction = dashboard.latest_prediction;
  const risk = prediction?.failure_risk ?? 0;
  const confidence = prediction?.prediction_confidence ?? 100;
  const trust = dashboard.overall_trust ?? 100;

  const riskTone = risk >= 60 ? "fault" : risk >= 35 ? "caution" : "trust";
  const confTone = confidence >= 70 ? "trust" : confidence >= 45 ? "caution" : "fault";
  const trustTone = trust >= 80 ? "trust" : trust >= 50 ? "caution" : "fault";

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-hairline)",
        borderRadius: "var(--radius-md)",
        padding: "18px 20px",
        display: "flex",
        justifyContent: "space-around",
        flexWrap: "wrap",
        gap: 12,
      }}
    >
      <ArcGauge value={risk} label="FAILURE RISK" tone={riskTone} />
      <ArcGauge value={confidence} label="PREDICTION CONFIDENCE" tone={confTone} />
      <ArcGauge value={trust} label="OVERALL SENSOR TRUST" tone={trustTone} />
    </div>
  );
}
