import { useNow } from "../hooks/useNow";
import { formatAge } from "../lib/format";
import { summarizeFreshness } from "../lib/freshness";

const TONE = { ok: "var(--accent-trust)", warn: "var(--accent-caution)", bad: "var(--accent-fault)", off: "var(--text-tertiary)" };

function Row({ label, icon, tone, text, sub }) {
  return (
    <div style={{ display: "flex", gap: 7, alignItems: "flex-start" }}>
      <span aria-hidden="true" style={{ color: TONE[tone], fontSize: 10, lineHeight: "16px" }}>{icon}</span>
      <div style={{ minWidth: 0 }}>
        <div className="mono" style={{ fontSize: 10, letterSpacing: "0.05em", color: "var(--text-tertiary)" }}>{label}</div>
        <div className="mono" style={{ fontSize: 11.5, color: TONE[tone] }}>{text}</div>
        {sub && <div style={{ fontSize: 10.5, color: "var(--text-secondary)", marginTop: 1 }}>{sub}</div>}
      </div>
    </div>
  );
}

/**
 * Two independent statuses (they can disagree, which is the point):
 *   DASHBOARD  - is this page still receiving updates from the TrustGuard backend?
 *   SENSOR DATA - are the sensors themselves still reporting? (age of the newest reading per sensor)
 */
export default function ConnectionStatus({ dashboards, mode, lastSyncAt }) {
  const now = useNow(1000);
  const sensors = dashboards.flatMap((d) => d.sensors.map((s) => s.sensor));
  const f = summarizeFreshness(sensors, now);
  const syncAge = lastSyncAt ? (now - lastSyncAt) / 1000 : null;

  const dash = {
    live: { icon: "●", tone: "ok", text: "LIVE", sub: "Receiving pushed updates" },
    polling: { icon: "◐", tone: "warn", text: "POLLING", sub: `Live socket is down; refreshing every 5 s. Last sync ${formatAge(syncAge)} ago` },
    offline: { icon: "○", tone: "bad", text: "DISCONNECTED", sub: lastSyncAt ? `Backend unreachable. Showing data from ${formatAge(syncAge)} ago` : "Backend unreachable" },
    connecting: { icon: "◌", tone: "off", text: "CONNECTING", sub: "Waiting for the first update" },
  }[mode];

  let data;
  if (mode === "offline" || mode === "connecting") {
    // We cannot tell whether the sensors are fine: a growing age here would only reflect OUR lost connection.
    data = { icon: "?", tone: "off", text: "UNKNOWN", sub: mode === "offline" ? "Cannot check sensors while the dashboard is disconnected" : "Waiting for data" };
  } else if (sensors.length === 0) {
    data = { icon: "○", tone: "off", text: "NO SENSORS", sub: null };
  } else if (f.state === "fresh") {
    data = { icon: "●", tone: "ok", text: "FRESH", sub: `Newest reading ${formatAge(f.newestAgeS)} ago` };
  } else if (f.state === "stale") {
    data = { icon: "◐", tone: "warn", text: "STALE", sub: `${f.problems.length} of ${sensors.length} sensors late. Oldest last reading ${formatAge(f.stalestAgeS)} ago` };
  } else {
    data = { icon: "○", tone: "bad", text: f.state === "none" && f.newestMs == null ? "NO DATA" : "OLD DATA", sub: `${f.problems.length} of ${sensors.length} sensors silent or very old` };
  }

  return (
    <div role="group" aria-label="Connection and data status" style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 12 }}>
      <Row label="DASHBOARD CONNECTION" {...dash} />
      <Row label="SENSOR DATA" {...data} />
    </div>
  );
}
