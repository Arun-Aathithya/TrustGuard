import { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar";
import { fetchAllDashboards } from "./api/client";
import { useLiveDashboards } from "./hooks/useLiveDashboard";
import { useHardware } from "./hooks/useHardware";
import AddMachine from "./pages/AddMachine";
import Dashboard from "./pages/Dashboard";
import HardwareManagement from "./pages/HardwareManagement";
import Overview from "./pages/Overview";
import SecurityBanner from "./components/SecurityBanner";

export default function App() {
  const { dashboards, error, setDashboards, mode, lastSyncAt } = useLiveDashboards();
  const [selectedId, setSelectedId] = useState(null);
  const [view, setView] = useState("overview"); // overview | machine | hardware | add
  const hardware = useHardware(5000, { withDetails: view === "hardware" });

  useEffect(() => {
    if (selectedId === null && dashboards.length > 0) {
      setSelectedId(dashboards[0].machine.id);
    }
  }, [dashboards, selectedId]);

  const selected = dashboards.find((d) => d.machine.id === selectedId);
  const loaded = lastSyncAt !== null; // at least one successful push or poll, so an empty list really means "no machines"
  const noMachines = loaded && dashboards.length === 0;

  // Re-read the list right after the user adds or removes a machine instead of waiting for the next push.
  const refresh = async () => {
    const data = await fetchAllDashboards();
    setDashboards(data);
    return data;
  };
  const handleCreated = async (machine) => {
    await refresh();
    setSelectedId(machine.id);
    setView("machine");
  };
  const handleRemoved = async () => {
    setSelectedId(null);
    setView("overview");
    await refresh();
  };

  const handleSimulationResult = (results) => {
    setDashboards((prev) => {
      const byId = new Map(prev.map((d) => [d.machine.id, d]));
      results.forEach((r) => byId.set(r.machine.id, r));
      return Array.from(byId.values());
    });
  };

  return (
    <div className="tg-app">
      <a href="#main" className="tg-skip">Skip to main content</a>
      <Sidebar
        dashboards={dashboards}
        selectedId={selectedId}
        onSelect={(id) => { setSelectedId(id); setView("machine"); }}
        mode={mode}
        lastSyncAt={lastSyncAt}
        view={view}
        onView={setView}
      />
      <main id="main" tabIndex={-1} className="tg-main">
        <SecurityBanner broker={hardware.broker} onOpenHardware={() => setView("hardware")} />
        {error && dashboards.length === 0 && (
          <div role="alert" style={{ padding: 28, color: "var(--text-secondary)" }}>
            <div style={{ fontSize: 15, marginBottom: 6, color: "var(--accent-fault)" }}>
              Can't reach the TrustGuard API
            </div>
            <div style={{ fontSize: 13 }}>
              Make sure the backend is running at the URL in your <code className="mono">.env</code> file
              (default <code className="mono">http://localhost:8000</code>).
            </div>
          </div>
        )}
        {!error && !loaded && (
          <div role="status" style={{ padding: 28, color: "var(--text-secondary)", fontSize: 13 }}>Loading…</div>
        )}
        {(view === "add" || (noMachines && view !== "hardware")) && (
          <AddMachine empty={noMachines} onCreated={handleCreated} onOpenHardware={() => setView("hardware")} />
        )}
        {view === "overview" && dashboards.length > 0 && (
          <Overview
            dashboards={dashboards}
            hardware={hardware}
            onOpenMachine={(id) => { setSelectedId(id); setView("machine"); }}
            onOpenHardware={() => setView("hardware")}
          />
        )}
        {view === "hardware" && <HardwareManagement dashboards={dashboards} hardware={hardware} />}
        {view === "machine" && selected && <Dashboard key={selected.machine.id} dashboard={selected} onSimulationResult={handleSimulationResult} onOpenHardware={() => setView("hardware")} onRemoved={handleRemoved} onChanged={refresh} />}
      </main>
    </div>
  );
}
