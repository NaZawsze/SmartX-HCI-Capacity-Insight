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
    setTasks((current) => {
      const existing = current.find((item) => item.id === task.id);
      const nextTask = { ...existing, ...task, createdAt: existing?.createdAt ?? now, updatedAt: now };
      return [nextTask, ...current.filter((item) => item.id !== task.id)].slice(0, 30);
    });
  }, []);

  const updateTask = useCallback((id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => {
    setTasks((current) => current.map((task) => (task.id === id ? { ...task, ...patch, updatedAt: Date.now() } : task)));
  }, []);

  const clearTasks = useCallback(() => {
    api.clearClearableTasks().catch(() => undefined);
    setTasks((current) => current.filter((task) => !task.clearable));
  }, []);

  const markTasksSeen = useCallback((taskIds: string[]) => {
    if (!taskIds.length) return;
    api.markTasksSeen(taskIds).catch(() => undefined);
    setTasks((current) => current.map((task) => (taskIds.includes(task.id) && task.severity === "info" ? { ...task, unhandled: false, clearable: true, seenAt: new Date().toISOString(), updatedAt: Date.now() } : task)));
  }, []);

  const acknowledgeTask = useCallback(async (task: AppTask) => {
    setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, detail: item.detail || "任务告警已确认", updatedAt: Date.now() } : item)));
    try {
      const updated = await api.acknowledgeTask(task.id);
      const mapped = serverTaskToAppTask(updated);
      setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, ...mapped } : item)));
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "确认任务失败";
      setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, detail: message, updatedAt: Date.now() } : item)));
    }
  }, []);

  const handleTaskAction = useCallback(async (task: AppTask) => {
    if (!isCancellableUpgradeTask(task) && isActiveTask(task)) return;
    setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, detail: isCancellableUpgradeTask(task) ? "正在取消等待任务" : "正在从任务中心移除", updatedAt: Date.now() } : item)));
    try {
      if (isCancellableUpgradeTask(task)) {
        if (task.title === "执行组件升级") {
          await api.cancelComponentUpgrade(task.id);
        } else {
          await api.cancelUpgrade(task.id);
        }
        setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, status: "cancelled", progress: 100, detail: "升级任务已取消", updatedAt: Date.now() } : item)));
      } else {
        await api.deleteTask(task.id);
        setTasks((current) => current.filter((item) => item.id !== task.id));
      }
      await refreshTasks();
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "取消任务失败";
      const notFound = message.includes("不存在");
      setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, status: notFound ? "cancelled" : item.status, progress: notFound ? 100 : item.progress, detail: notFound ? "升级任务已不存在，已从等待队列移除" : message, updatedAt: Date.now() } : item)));
    }
  }, [refreshTasks]);


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
    <AppLayout activePage={activePage} onNavigate={setActivePage} onLogout={logout} summary={summary} scope={scope} onScopeChange={setScope} onSummary={handleSummary} tasks={tasks} onClearTasks={clearTasks} onTasksSeen={markTasksSeen} onTaskAck={acknowledgeTask} onTaskAction={handleTaskAction}>
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
    if (!existing || task.updatedAt >= existing.updatedAt || (isActiveTask(existing) && isActiveTask(task))) {
      byId.set(task.id, { ...existing, ...task });
    }
  }
  return [...byId.values()].sort((left, right) => right.updatedAt - left.updatedAt);
}

function isActiveTask(task: AppTask): boolean {
  return task.status === "pending" || task.status === "running";
}

function isCancellableUpgradeTask(task: AppTask): boolean {
  return task.kind === "upgrade" && task.status === "pending" && (task.title === "执行系统升级" || task.title === "执行组件升级");
}

function serverTaskToAppTask(task: ServerTask): AppTask {
  return {
    id: task.id,
    kind: task.kind || "download",
    title: task.title,
    detail: task.detail || task.message || "",
    status: task.status === "success" ? "succeeded" : task.status === "failed" ? "failed" : task.status === "cancelled" ? "cancelled" : task.status === "pending" ? "pending" : "running",
    progress: task.progress,
    links: task.links,
    logs: task.logs,
    steps: task.steps,
    severity: task.severity || "info",
    seenAt: task.seen_at,
    acknowledgedAt: task.acknowledged_at,
    unhandled: Boolean(task.unhandled),
    clearable: Boolean(task.clearable),
    createdAt: task.created_at ? Date.parse(task.created_at) : Date.now(),
    updatedAt: task.updated_at ? Date.parse(task.updated_at) : Date.now()
  };
}
