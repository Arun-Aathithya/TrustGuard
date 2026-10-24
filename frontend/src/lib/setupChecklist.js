// Hardware bring-up checklist: MQTT broker connected -> device registered -> first reading received -> sensor online.
// Pure function so it can be tested without React.
import { formatAge } from "./format";

/**
 * @param broker  GET /api/hardware/broker (or null while loading)
 * @param device  one entry of GET /api/hardware/devices (or null if nothing is registered)
 * Each step: { id, title, done, detail, fix }. `current` is the first step that is not done.
 */
export function buildChecklist(broker, device) {
  const registered = Boolean(device && device.data_source === "hardware");
  const seen = registered && device.last_seen_at != null;
  const online = registered && device.device_status === "online";

  const steps = [
    {
      id: "broker",
      title: "MQTT broker connected",
      done: Boolean(broker?.connected),
      detail: !broker ? "Checking…" : broker.connected ? `Connected to ${broker.host}:${broker.port}` :
        !broker.enabled ? "MQTT is disabled (MQTT_ENABLED=false), so no hardware data can arrive over MQTT." :
        broker.last_error ? `Not connected: ${broker.last_error}` : "Enabled but not connected yet.",
      fix: !broker?.enabled ? "Set MQTT_ENABLED=true and the broker host, TLS and credentials in backend/.env, then restart the backend." :
        "Check the broker is running, the host/port/credentials in backend/.env, and the CA certificate path.",
    },
    {
      id: "registered",
      title: "Device registered",
      done: registered,
      detail: registered ? `${device.device_id} → ${device.machine_name} / ${device.sensor_type}` : "No device is mapped to a machine sensor yet.",
      fix: "Use “Register device” below (needs the admin key). The Device ID must match DEVICE_ID in the ESP32 firmware.",
    },
    {
      id: "first_reading",
      title: "First reading received",
      done: seen,
      detail: !registered ? "Waiting for a registered device." : seen ? `Last message ${formatAge(device.seconds_since_seen)} ago` : "No message has ever arrived for this device.",
      fix: "Power the ESP32, check Wi-Fi and the MQTT topic it publishes to, then look at “Recent ingestion problems” for rejected messages.",
    },
    {
      id: "online",
      title: "Sensor online",
      done: online,
      detail: !registered ? "Waiting for a registered device." : online ? "Messages are arriving on time." :
        seen ? `Status ${device.device_status}: last message ${formatAge(device.seconds_since_seen)} ago (online means under 30 s).` : "Waiting for the first reading.",
      fix: "Check the device is powered and in range, and that it publishes at least every 30 s.",
    },
  ];
  const current = steps.findIndex((s) => !s.done);
  return { steps, current, complete: current === -1, doneCount: steps.filter((s) => s.done).length };
}
