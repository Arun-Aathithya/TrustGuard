export function relTime(isoOrDate) {
  if (!isoOrDate) return "never";
  // Backend datetimes may come without a timezone suffix; they are UTC.
  const s = typeof isoOrDate === "string" && !/[zZ]|[+-]\d\d:?\d\d$/.test(isoOrDate) ? `${isoOrDate}Z` : isoOrDate;
  const sec = Math.max(0, (Date.now() - new Date(s).getTime()) / 1000);
  return relSeconds(sec);
}

export function relSeconds(sec) {
  if (sec == null) return "never";
  if (sec < 5) return "just now";
  if (sec < 60) return `${Math.round(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

export function absTime(iso) {
  if (!iso) return "—";
  const s = !/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? `${iso}Z` : iso;
  return new Date(s).toLocaleString();
}

export const SENSOR_LABELS = {
  temperature: "Temperature",
  vibration: "Vibration / accelerometer",
  pressure: "Pressure",
  current: "Current",
  rpm: "RPM",
};

/** The only sensor types a user can add (mirrors backend/services/sensor_catalog.py). */
export const SUPPORTED_SENSOR_TYPES = [
  { value: "temperature", label: "Temperature", model: "DS18B20", unit: "°C" },
  { value: "vibration", label: "Vibration", model: "MPU6050", unit: "m/s²" },
];

/** The user's custom name, or the type label for sensors created before names existed. */
export function sensorName(sensor) {
  return sensor.display_name || sensor.name || SENSOR_LABELS[sensor.sensor_type] || sensor.sensor_type;
}

/** Precise age for freshness displays: "45s", "2m 14s", "1h 05m", "3d 2h". */
export function formatAge(sec) {
  if (sec == null || !Number.isFinite(sec)) return "never";
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

/** Backend datetimes may lack a timezone suffix; they are UTC. Returns epoch ms or null. */
export function parseUtcMs(iso) {
  if (!iso) return null;
  const s = typeof iso === "string" && !/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? `${iso}Z` : iso;
  const t = new Date(s).getTime();
  return Number.isFinite(t) ? t : null;
}
