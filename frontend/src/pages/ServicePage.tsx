import { Download, History, Power, Server, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import type { AppTask, ComponentInfo, UpgradeTask } from "../types";
import { CleanupSection } from "../components/service/CleanupSection";
import { ComponentUpgradeSection } from "../components/service/ComponentUpgradeSection";
import { HistorySection } from "../components/service/HistorySection";
import { MigrationSection } from "../components/service/MigrationSection";
import { PlatformUpgradeSection } from "../components/service/PlatformUpgradeSection";
import { RestartSection } from "../components/service/RestartSection";
import { defaultComponentInfos, scrollElementToTop, type ServiceSection } from "../components/service/shared";

export { displayUpgradeSteps, formatVersionForDisplay } from "../components/service/shared";

interface ServicePageProps {
  addTask: (task: Omit<AppTask, "createdAt" | "updatedAt">) => void;
  updateTask: (id: string, patch: Partial<Omit<AppTask, "id" | "createdAt">>) => void;
}

export function ServicePage({ addTask, updateTask }: ServicePageProps) {
  const [section, setSection] = useState<ServiceSection>("platform-upgrade");
  const [appVersion, setAppVersion] = useState("-");
  const [runnerVersion, setRunnerVersion] = useState("v0.1.0");
  const [componentInfos, setComponentInfos] = useState<ComponentInfo[]>(defaultComponentInfos);
  const [selectedComponentService, setSelectedComponentService] = useState("upgrade-runner");
  const [upgradeHistory, setUpgradeHistory] = useState<UpgradeTask[]>([]);
  const [componentHistory, setComponentHistory] = useState<UpgradeTask[]>([]);
  const [historySelection, setHistorySelection] = useState<UpgradeTask | null>(null);
  const upgradeRunTaskRef = useRef<Record<string, string>>({});
  const contentPanelRef = useRef<HTMLElement | null>(null);

  async function reloadUpgradeHistory() {
    setUpgradeHistory(await api.upgradeHistory());
  }

  async function reloadComponentHistory() {
    setComponentHistory(await api.componentUpgradeHistory());
  }

  async function reloadComponentInfos() {
    const result = await api.componentUpgradeComponents();
    if (result.components.length) {
      setComponentInfos(result.components);
      const selectedExists = result.components.some((component) => component.service === selectedComponentService);
      if (!selectedExists) setSelectedComponentService(result.components[0].service);
    }
  }

  function selectSection(nextSection: ServiceSection) {
    setSection(nextSection);
    resetServiceScroll();
  }

  function resetServiceScroll() {
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0 });
      scrollElementToTop(document.querySelector<HTMLElement>(".workspace"));
      scrollElementToTop(contentPanelRef.current);
    });
  }

  function loadHistoryItem(task: UpgradeTask) {
    setHistorySelection(task);
    setSection(task.kind === "component" ? "component-upgrade" : "platform-upgrade");
    resetServiceScroll();
  }

  useEffect(() => {
    resetServiceScroll();
  }, []);

  return (
    <div className="service-page-shell">
      <aside className="service-subnav">
        <div className="service-subnav-group">
          <span>系统运维</span>
          <button className={section === "migration" ? "active" : ""} type="button" onClick={() => selectSection("migration")}>
            <Download size={17} />
            数据迁移
          </button>
          <button className={section === "restart" ? "active" : ""} type="button" onClick={() => selectSection("restart")}>
            <Power size={17} />
            服务重启
          </button>
          <button className={section === "space-cleanup" ? "active" : ""} type="button" onClick={() => selectSection("space-cleanup")}>
            <Trash2 size={17} />
            空间清理
          </button>
        </div>
        <div className="service-subnav-group">
          <span>升级中心</span>
          <button className={section === "platform-upgrade" ? "active" : ""} type="button" onClick={() => selectSection("platform-upgrade")}>
            <Upload size={17} />
            平台升级
          </button>
          <button className={section === "component-upgrade" ? "active" : ""} type="button" onClick={() => selectSection("component-upgrade")}>
            <Server size={17} />
            组件升级
          </button>
          <button className={section === "history" ? "active" : ""} type="button" onClick={() => selectSection("history")}>
            <History size={17} />
            升级历史
          </button>
        </div>
      </aside>

      <main ref={contentPanelRef} className="service-content-panel auto-scrollbar">
        <MigrationSection active={section === "migration"} addTask={addTask} updateTask={updateTask} />
        <RestartSection active={section === "restart"} />
        <CleanupSection active={section === "space-cleanup"} addTask={addTask} updateTask={updateTask} />
        <PlatformUpgradeSection
          active={section === "platform-upgrade"}
          addTask={addTask}
          updateTask={updateTask}
          appVersion={appVersion}
          runnerVersion={runnerVersion}
          componentInfos={componentInfos}
          setAppVersion={setAppVersion}
          setRunnerVersion={setRunnerVersion}
          setComponentInfos={setComponentInfos}
          upgradeHistory={upgradeHistory}
          reloadUpgradeHistory={reloadUpgradeHistory}
          upgradeRunTaskRef={upgradeRunTaskRef}
          historySelection={historySelection}
          onConsumeHistorySelection={() => setHistorySelection(null)}
        />
        <ComponentUpgradeSection
          active={section === "component-upgrade"}
          addTask={addTask}
          updateTask={updateTask}
          runnerVersion={runnerVersion}
          componentInfos={componentInfos}
          selectedComponentService={selectedComponentService}
          setRunnerVersion={setRunnerVersion}
          setComponentInfos={setComponentInfos}
          setSelectedComponentService={setSelectedComponentService}
          componentHistory={componentHistory}
          setComponentHistory={setComponentHistory}
          reloadComponentHistory={reloadComponentHistory}
          reloadComponentInfos={reloadComponentInfos}
          upgradeRunTaskRef={upgradeRunTaskRef}
          historySelection={historySelection}
          onConsumeHistorySelection={() => setHistorySelection(null)}
        />
        <HistorySection
          active={section === "history"}
          upgradeHistory={upgradeHistory}
          componentHistory={componentHistory}
          reloadUpgradeHistory={reloadUpgradeHistory}
          reloadComponentHistory={reloadComponentHistory}
          onSelectHistoryItem={loadHistoryItem}
        />
      </main>
    </div>
  );
}
