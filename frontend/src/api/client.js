import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});

export const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws/live";

export async function fetchAllDashboards() {
  const { data } = await api.get("/api/machines/dashboard/all");
  return data;
}

export async function fetchMachineDashboard(machineId) {
  const { data } = await api.get(`/api/machines/${machineId}/dashboard`);
  return data;
}

export async function fetchSensorReadings(sensorId, minutes = 60) {
  const { data } = await api.get("/api/readings", { params: { sensor_id: sensorId, minutes } });
  return data;
}

export async function fetchSensorTrustHistory(sensorId, minutes = 120) {
  const { data } = await api.get("/api/trust", { params: { sensor_id: sensorId, minutes } });
  return data;
}

export async function fetchPredictionHistory(machineId, limit = 50) {
  const { data } = await api.get("/api/predictions", { params: { machine_id: machineId, limit } });
  return data;
}

export async function fetchAlerts(machineId, onlyOpen = false) {
  const { data } = await api.get("/api/alerts", { params: { machine_id: machineId, only_open: onlyOpen } });
  return data;
}

export async function resolveAlert(alertId) {
  const { data } = await api.post(`/api/alerts/${alertId}/resolve`);
  return data;
}

export async function fetchMaintenance(machineId) {
  const { data } = await api.get("/api/maintenance", { params: { machine_id: machineId } });
  return data;
}

export async function updateMaintenance(id, payload) {
  const { data } = await api.patch(`/api/maintenance/${id}`, payload);
  return data;
}

export async function createMachine(payload) {
  const { data } = await api.post("/api/machines", payload);
  return data;
}

export async function deleteMachine(machineId) {
  await api.delete(`/api/machines/${machineId}`);
}

export async function createSensor(payload) {
  const { data } = await api.post("/api/sensors", payload);
  return data;
}

export async function deleteSensor(sensorId) {
  await api.delete(`/api/sensors/${sensorId}`);
}

export async function runSimulationTick(machineId, scenario) {
  const { data } = await api.post("/api/simulate/tick", { machine_id: machineId, scenario });
  return data;
}

// ---------------------------------------------------------------------------
// Admin key: entered by the operator at runtime and kept only in sessionStorage
// (cleared when the tab closes). It is NEVER bundled into the frontend code.
// ---------------------------------------------------------------------------
const ADMIN_KEY_STORAGE = "trustguard_admin_key";

export function getAdminKey() {
  try {
    return sessionStorage.getItem(ADMIN_KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setAdminKey(key) {
  try {
    if (key) sessionStorage.setItem(ADMIN_KEY_STORAGE, key);
    else sessionStorage.removeItem(ADMIN_KEY_STORAGE);
  } catch {
    /* storage unavailable - key just won't persist */
  }
}

api.interceptors.request.use((config) => {
  const key = getAdminKey();
  if (key && (config.method || "get").toLowerCase() !== "get") config.headers["X-API-Key"] = key;
  return config;
});

/** Turns an axios/FastAPI error into a short human-readable message. */
export function errorMessage(e) {
  if (e?.response?.status === 401) return "Admin key missing or incorrect. Enter it under 'Admin access'.";
  if (e?.response?.status === 503) return "The server has no admin key configured (production mode).";
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg).join("; ");
  if (d?.detail) return d.detail;
  if (e?.code === "ECONNABORTED" || e?.message === "Network Error") return "Cannot reach the TrustGuard API.";
  return e?.message || "Unexpected error.";
}

// ---- Hardware ----
export const fetchHardwareSummary = async () => (await api.get("/api/hardware/summary")).data;
export const fetchBroker = async () => (await api.get("/api/hardware/broker")).data;
export const fetchDevices = async () => (await api.get("/api/hardware/devices")).data;
export const fetchHardwareEvents = async (limit = 50) => (await api.get("/api/hardware/events", { params: { limit } })).data;
export const registerDevice = async (payload) => (await api.post("/api/hardware/devices/register", payload)).data;
export const unregisterDevice = async (sensorId) => (await api.post(`/api/hardware/devices/${sensorId}/unregister`)).data;
export const testDevice = async (sensorId) => (await api.post(`/api/hardware/devices/${sensorId}/test`)).data;

// ---- Telegram bot (status has no secrets; the test message needs the admin key) ----
export const fetchTelegramStatus = async () => (await api.get("/api/telegram/status")).data;
export const sendTelegramTest = async () => (await api.post("/api/telegram/test")).data;
