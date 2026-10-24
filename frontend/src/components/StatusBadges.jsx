// One consistent vocabulary for status labels across the whole UI.
// Every badge carries a text label AND a shape/symbol, never colour alone.

const DEVICE = {
  online: { label: "Online", color: "var(--accent-trust)", icon: "●" },
  stale: { label: "Stale", color: "var(--accent-caution)", icon: "◐" },
  offline: { label: "Offline", color: "var(--accent-fault)", icon: "○" },
  simulated: { label: "Simulated", color: "var(--accent-signal)", icon: "◇" },
};

const SOURCE = {
  hardware: { label: "Real hardware", color: "var(--accent-trust)", icon: "▣" },
  simulation: { label: "Simulation", color: "var(--accent-signal)", icon: "◇" },
  mixed: { label: "Mixed: hardware + simulation", color: "var(--accent-caution)", icon: "◫" },
};

function pill(meta, size) {
  return (
    <span
      className="mono"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: size === "lg" ? 12 : 10.5,
        padding: size === "lg" ? "4px 10px" : "2px 7px",
        borderRadius: "var(--radius-sm)",
        color: meta.color,
        border: `1px solid ${meta.color}`,
        whiteSpace: "nowrap",
      }}
    >
      <span aria-hidden="true">{meta.icon}</span>
      {meta.label.toUpperCase()}
    </span>
  );
}

export function DeviceStatusPill({ status, size }) {
  return pill(DEVICE[status] || DEVICE.simulated, size);
}

export function DataSourceBadge({ source, size }) {
  return pill(SOURCE[source] || SOURCE.simulation, size);
}
