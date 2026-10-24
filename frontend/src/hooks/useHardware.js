import { useCallback, useEffect, useState } from "react";
import { errorMessage, fetchBroker, fetchDevices, fetchHardwareEvents, fetchHardwareSummary } from "../api/client";

/** Polls hardware summary, broker state, devices and ingestion problems. */
export function useHardware(intervalMs = 5000, { withDetails = false } = {}) {
  const [state, setState] = useState({ summary: null, broker: null, devices: [], events: [], loading: true, error: null });

  const load = useCallback(async () => {
    try {
      const [summary, broker, devices, events] = await Promise.all([
        fetchHardwareSummary(),
        fetchBroker(),
        withDetails ? fetchDevices() : Promise.resolve([]),
        withDetails ? fetchHardwareEvents(50) : Promise.resolve([]),
      ]);
      setState({ summary, broker, devices, events, loading: false, error: null });
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: errorMessage(e) }));
    }
  }, [withDetails]);

  useEffect(() => {
    load();
    const id = setInterval(load, intervalMs);
    return () => clearInterval(id);
  }, [load, intervalMs]);

  return { ...state, reload: load };
}
