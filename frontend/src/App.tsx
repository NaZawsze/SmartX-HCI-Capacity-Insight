import { useCallback, useEffect, useRef, useState } from "react";
import { AppLayout } from "./components/AppLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ServicePage } from "./pages/ServicePage";
import { VmsPage } from "./pages/VmsPage";
import { AUTH_CHANGED_EVENT, api, getToken, setToken } from "./services/api";
import type { AppTask, DashboardScope, DashboardSummary, PageKey, ServerTask } from "./types";

export default function App() {
  const [authenticated, setAuthenticated] = useState(Boolean(getToken()));
  const [activePage, setActivePage] = useState<PageKey>("dashboard");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [scope, setScope] = useState<DashboardScope>({ type: "all" });
  const [selectedVmId, setSelectedVmId] = useState("");
  const [selectedVmName, setSelectedVmName] = useState("");
  const [dataRefreshKey, setDataRefreshKey] = useState(0);
  const [tasks, setTasks] = useState<AppTask[]>([]);
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

  const refreshTasks = useCallback(async () => {
    const serverTasks = await api.tasks();
    setTasks((current) => mergeTasks(current, serverTasks.map(serverTaskToAppTask)).slice(0, 30));
  }, []);
  const addTask = useCallback((task: Omit<AppTask, "createdAt" | "updatedAt">) => {
    const now = Date.now();
    setTasks((current) => [{ ...task, createdAt: now, updatedAt: now }, ...current].slice(0, 30));
  }, []);

  const updateTask = useCallback((id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => {
    setTasks((current) => current.map((task) => (task.id === id ? { ...task, ...patch, updatedAt: Date.now() } : task)));
  }, []);

  const clearTasks = useCallback(() => {
    api.clearFinishedTasks().catch(() => undefined);
    setTasks((current) => current.filter((task) => task.status === "running"));
  }, []);


  useEffect(() => {
    if (authenticated) {
      refreshSummary().catch(() => undefined);
      refreshTasks().catch(() => undefined);
    }
  }, [authenticated, refreshSummary, refreshTasks]);

  useEffect(() => {
    if (!authenticated) return;
    const timer = window.setInterval(() => {
      refreshSummary().catch(() => undefined);
      refreshTasks().catch(() => undefined);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [authenticated, refreshSummary, refreshTasks]);

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
    <AppLayout activePage={activePage} onNavigate={setActivePage} onLogout={logout} summary={summary} scope={scope} onScopeChange={setScope} onSummary={handleSummary} tasks={tasks} onClearTasks={clearTasks}>
      {activePage === "dashboard" && <DashboardPage summary={summary} scope={scope} onSummary={handleSummary} onSelectVm={openVm} />}
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
      {activePage === "reports" && <ReportsPage summary={summary} scope={scope} refreshKey={dataRefreshKey} onSelectVm={openVm} addTask={addTask} updateTask={updateTask} />}
      {activePage === "settings" && <SettingsPage />}
      {activePage === "service" && <ServicePage addTask={addTask} updateTask={updateTask} />}
    </AppLayout>
  );
}

function mergeTasks(localTasks: AppTask[], serverTasks: AppTask[]): AppTask[] {
  const byId = new Map<string, AppTask>();
  for (const task of [...serverTasks, ...localTasks]) {
    const existing = byId.get(task.id);
    if (!existing || task.updatedAt >= existing.updatedAt || existing.status === "running") {
      byId.set(task.id, { ...existing, ...task });
    }
  }
  return [...byId.values()].sort((left, right) => right.updatedAt - left.updatedAt);
}

function serverTaskToAppTask(task: ServerTask): AppTask {
  return {
    id: task.id,
    kind: task.kind || "download",
    title: task.title,
    detail: task.detail || task.message || "",
    status: task.status === "success" ? "succeeded" : task.status === "failed" || task.status === "cancelled" ? "failed" : "running",
    progress: task.progress,
    links: task.links,
    logs: task.logs,
    createdAt: task.created_at ? Date.parse(task.created_at) : Date.now(),
    updatedAt: task.updated_at ? Date.parse(task.updated_at) : Date.now()
  };
}
