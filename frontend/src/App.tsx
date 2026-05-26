import { useCallback, useEffect, useRef, useState } from "react";
import { AppLayout } from "./components/AppLayout";
import { useTheme } from "./hooks/useTheme";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { VmsPage } from "./pages/VmsPage";
import { AUTH_CHANGED_EVENT, api, getToken, setToken } from "./services/api";
import type { DashboardScope, DashboardSummary, PageKey } from "./types";

export default function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(getToken()));
  const [activePage, setActivePage] = useState<PageKey>("dashboard");
  const { theme, setTheme, actualTheme } = useTheme();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [scope, setScope] = useState<DashboardScope>({ type: "all" });
  const [selectedVmId, setSelectedVmId] = useState("");
  const [selectedVmName, setSelectedVmName] = useState("");
  const [dataRefreshKey, setDataRefreshKey] = useState(0);
  const completedRunKeyRef = useRef("");

  const handleSummary = useCallback((result: DashboardSummary) => {
    setSummary(result);
    const run = result.latest_run;
    if (!run || run.status === "running") return;
    const runKey = `${run.id}:${run.status}:${run.finished_at || ""}`;
    if (runKey === completedRunKeyRef.current) return;
    completedRunKeyRef.current = runKey;
    setDataRefreshKey((current) => current + 1);
  }, []);

  const refreshSummary = useCallback(async () => {
    const result = await api.summary(scope);
    handleSummary(result);
  }, [handleSummary, scope]);

  useEffect(() => {
    if (authenticated) {
      refreshSummary().catch(() => undefined);
    }
  }, [authenticated, refreshSummary]);

  useEffect(() => {
    if (!authenticated) return;
    const timer = window.setInterval(() => {
      refreshSummary().catch(() => undefined);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [authenticated, refreshSummary]);

  useEffect(() => {
    function syncAuthState() {
      setAuthenticated(Boolean(getToken()));
    }
    window.addEventListener(AUTH_CHANGED_EVENT, syncAuthState);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, syncAuthState);
  }, []);

  if (!authenticated) {
    return <LoginPage onLoggedIn={() => setAuthenticated(true)} />;
  }

  function logout() {
    setToken(null);
    setAuthenticated(false);
  }

  function openVm(vmId: string, vmName?: string) {
    setSelectedVmId(vmId);
    setSelectedVmName(vmName || vmId);
    setActivePage("vms");
  }

  return (
    <AppLayout activePage={activePage} theme={theme} onThemeChange={setTheme} onNavigate={setActivePage} onLogout={logout} summary={summary} scope={scope} onScopeChange={setScope} onSummary={handleSummary}>
      {activePage === "dashboard" && <DashboardPage actualTheme={actualTheme} summary={summary} scope={scope} onSummary={handleSummary} onSelectVm={openVm} />}
      {activePage === "vms" && (
        <VmsPage
          refreshKey={dataRefreshKey}
          scope={scope}
          selectedVmId={selectedVmId}
          selectedVmName={selectedVmName}
          onSelectedVmChange={(vmId) => {
            setSelectedVmId(vmId);
            setSelectedVmName("");
          }}
        />
      )}
      {activePage === "reports" && <ReportsPage actualTheme={actualTheme} summary={summary} scope={scope} refreshKey={dataRefreshKey} onSelectVm={openVm} />}
      {activePage === "settings" && <SettingsPage />}
    </AppLayout>
  );
}
