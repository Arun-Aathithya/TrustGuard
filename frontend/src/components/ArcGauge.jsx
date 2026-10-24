import { useId } from "react";

/**
 * A 270° arc dial with tick marks, styled after plant-floor instrumentation
 * rather than a generic radial progress ring. Value is 0-100.
 */
export default function ArcGauge({ value = 0, label, unit = "%", tone = "trust", size = 140 }) {
  const id = useId();
  const clamped = Math.max(0, Math.min(100, value));
  const startAngle = -225; // degrees
  const sweep = 270;
  const angle = startAngle + (clamped / 100) * sweep;

  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 14;

  const toXY = (deg) => {
    const rad = (deg * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
  };

  const [startX, startY] = toXY(startAngle);
  const [endX, endY] = toXY(startAngle + sweep);
  const [valX, valY] = toXY(angle);

  const largeArc = sweep > 180 ? 1 : 0;
  const valueArcFlag = clamped / 100 * sweep > 180 ? 1 : 0;

  const trackPath = `M ${startX} ${startY} A ${r} ${r} 0 ${largeArc} 1 ${endX} ${endY}`;
  const valuePath = `M ${startX} ${startY} A ${r} ${r} 0 ${valueArcFlag} 1 ${valX} ${valY}`;

  const toneColor = {
    trust: "var(--accent-trust)",
    caution: "var(--accent-caution)",
    fault: "var(--accent-fault)",
    signal: "var(--accent-signal)",
  }[tone];

  const ticks = Array.from({ length: 12 }, (_, i) => {
    const deg = startAngle + (i / 11) * sweep;
    const [x1, y1] = toXY(deg);
    const innerR = r - 8;
    const rad = (deg * Math.PI) / 180;
    const x2 = cx + innerR * Math.cos(rad);
    const y2 = cy + innerR * Math.sin(rad);
    return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--border-strong)" strokeWidth="1.5" />;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <filter id={`glow-${id}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {ticks}
        <path d={trackPath} fill="none" stroke="var(--bg-inset)" strokeWidth="8" strokeLinecap="round" />
        <path
          d={valuePath}
          fill="none"
          stroke={toneColor}
          strokeWidth="8"
          strokeLinecap="round"
          filter={`url(#glow-${id})`}
        />
        <text
          x={cx}
          y={cy - 2}
          textAnchor="middle"
          className="mono"
          fontSize={size * 0.19}
          fontWeight="600"
          fill="var(--text-primary)"
        >
          {Math.round(clamped)}
          <tspan fontSize={size * 0.11} fill="var(--text-secondary)">
            {unit}
          </tspan>
        </text>
      </svg>
      {label && (
        <div style={{ fontSize: 12, color: "var(--text-secondary)", letterSpacing: "0.02em" }}>{label}</div>
      )}
    </div>
  );
}
