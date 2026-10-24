import { useEffect, useRef, useState } from "react";
import { WS_URL, fetchAllDashboards } from "../api/client";

/**
 * Subscribes to the backend's live dashboard websocket. Falls back to
 * periodic REST polling if the socket can't connect (e.g. during local dev
 * before the backend is up).
 */
export function useLiveDashboards() {
  const [dashboards, setDashboards] = useState([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const [lastSyncAt, setLastSyncAt] = useState(null); // ms of the last successful push or poll
  const pollRef = useRef(null);

  useEffect(() => {
    let socket;
    let cancelled = false;

    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(async () => {
        try {
          const data = await fetchAllDashboards();
          if (!cancelled) {
            setDashboards(data);
            setError(null);
            setLastSyncAt(Date.now());
          }
        } catch (e) {
          if (!cancelled) setError(e.message);
        }
      }, 5000);
      fetchAllDashboards()
        .then((data) => { if (!cancelled) { setDashboards(data); setError(null); setLastSyncAt(Date.now()); } })
        .catch((e) => !cancelled && setError(e.message));
    };

    try {
      socket = new WebSocket(WS_URL);
      socket.onopen = () => {
        if (cancelled) return;
        setConnected(true);
        setError(null);
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      };
      socket.onmessage = (event) => {
        if (cancelled) return;
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === "dashboard_update") {
            setDashboards(payload.machines);
            setLastSyncAt(Date.now());
          }
        } catch {
          // ignore malformed frame
        }
      };
      socket.onerror = () => {
        if (!cancelled) {
          setConnected(false);
          startPolling();
        }
      };
      socket.onclose = () => {
        if (!cancelled) {
          setConnected(false);
          startPolling();
        }
      };
    } catch {
      startPolling();
    }

    return () => {
      cancelled = true;
      if (socket) socket.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // live    = websocket open (server pushes updates)
  // polling = websocket down, REST polling works (updates every 5 s)
  // offline = neither works: what is on screen is the last data we managed to fetch
  // connecting = nothing has succeeded or failed yet
  const mode = connected ? "live" : error ? "offline" : lastSyncAt ? "polling" : "connecting";

  return { dashboards, connected, error, setDashboards, mode, lastSyncAt };
}
