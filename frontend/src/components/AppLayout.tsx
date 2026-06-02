import { FormEvent, useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Bell, Building2, Check, ChevronDown, CircleCheck, ClipboardList, Database, HardDrive, KeyRound, LayoutDashboard, LogOut, Save, Server, Settings, SlidersHorizontal, UserRound, View, X } from "lucide-react";
import { api } from "../services/api";
import type { AppTask, Cluster, DashboardScope, DashboardSummary, PageKey, Tower } from "../types";

interface AppLayoutProps {
  activePage: PageKey;
  onNavigate: (page: PageKey) => void;
  onLogout: () => void;
  scope: DashboardScope;
  onScopeChange: (scope: DashboardScope) => void;
  onSummary: (summary: DashboardSummary) => void;
  summary?: DashboardSummary | null;
  tasks?: AppTask[];
  onClearTasks?: () => void;
  children: ReactNode;
}

const pageTitle: Record<PageKey, string> = {
  dashboard: "存储预测概览",
  vms: "虚拟机存储趋势",
  reports: "预测报表",
  settings: "Tower 设置",
  service: "服务管理"
};

const navItems: Array<{ key: PageKey; label: string; icon: ReactNode }> = [
  { key: "dashboard", label: "概览", icon: <LayoutDashboard size={16} /> },
  { key: "vms", label: "虚拟机", icon: <Server size={16} /> },
  { key: "reports", label: "报表", icon: <ClipboardList size={16} /> },
  { key: "settings", label: "设置", icon: <Settings size={16} /> },
  { key: "service", label: "服务管理", icon: <SlidersHorizontal size={16} /> }
];
const emptyTowers: Tower[] = [];
const defaultSidebarWidth = 224;
const minSidebarWidth = 190;
const maxSidebarWidth = 320;

const emptyPasswordForm = {
  current_password: "",
  new_password: "",
  confirm_password: ""
};

function scopeKey(scope: DashboardScope): string {
  if (scope.type === "cluster") return `cluster:${scope.towerId}:${scope.clusterId}`;
  if (scope.type === "tower") return `tower:${scope.towerId}`;
  return "all";
}

export function AppLayout({ activePage, onNavigate, onLogout, scope, onScopeChange, onSummary, summary, tasks = [], onClearTasks, children }: AppLayoutProps) {
  const towers = summary?.towers ?? emptyTowers;
  const selectedTower = scope.type === "tower" || scope.type === "cluster" ? towers.find((tower) => tower.id === scope.towerId) || towers[0] : towers[0];
  const totalClusterCount = towers.reduce((total, tower) => total + tower.clusters.length, 0);
  const selectedClusterCount = selectedTower?.clusters.length ?? 0;
  const selectedEnabledClusterCount = selectedTower?.clusters.filter((cluster) => cluster.enabled).length ?? 0;
  const selectedTowerStatus =
    selectedClusterCount === 0
      ? "暂无集群"
      : selectedEnabledClusterCount === selectedClusterCount
        ? "全部集群已连接"
        : `${selectedEnabledClusterCount}/${selectedClusterCount} 集群已连接`;
  const [viewMenuOpen, setViewMenuOpen] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [taskMenuOpen, setTaskMenuOpen] = useState(false);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  const [passwordForm, setPasswordForm] = useState(emptyPasswordForm);
  const [passwordMessage, setPasswordMessage] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(defaultSidebarWidth);
  const [resizingSidebar, setResizingSidebar] = useState(false);
  const [expandedTowerIds, setExpandedTowerIds] = useState<Set<number>>(new Set());
  const [editingCluster, setEditingCluster] = useState<{ towerId: number; clusterId: string; name: string } | null>(null);
  const shellBodyRef = useRef<HTMLDivElement | null>(null);
  const taskMenuRef = useRef<HTMLDivElement | null>(null);
  const accountMenuRef = useRef<HTMLDivElement | null>(null);
  const selectedScopeKey = scopeKey(scope);
  const serviceFocus = activePage === "service";
  const shellStyle = { "--sidebar-width": `${sidebarWidth}px` } as CSSProperties;
  const runningTaskCount = tasks.filter((task) => task.status === "running").length;
  const visibleTasks = [...tasks].sort((left, right) => right.updatedAt - left.updatedAt).slice(0, 8);

  const resetWorkspaceScroll = useCallback(() => {
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: 0 });
      document.querySelector<HTMLElement>(".workspace")?.scrollTo({ top: 0 });
    });
  }, []);

  useEffect(() => {
    if (serviceFocus) resetWorkspaceScroll();
  }, [resetWorkspaceScroll, serviceFocus]);

  useEffect(() => {
    const timers = new WeakMap<HTMLElement, number>();
    function handleScroll(event: Event) {
      const target = event.target;
      if (!(target instanceof HTMLElement) || !target.classList.contains("auto-scrollbar")) return;
      target.classList.add("is-scrolling");
      const previousTimer = timers.get(target);
      if (previousTimer) window.clearTimeout(previousTimer);
      timers.set(target, window.setTimeout(() => target.classList.remove("is-scrolling"), 900));
    }
    document.addEventListener("scroll", handleScroll, true);
    return () => document.removeEventListener("scroll", handleScroll, true);
  }, []);

  useEffect(() => {
    if (!taskMenuOpen && !accountMenuOpen) return undefined;
    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (taskMenuOpen && !taskMenuRef.current?.contains(target)) {
        setTaskMenuOpen(false);
      }
      if (accountMenuOpen && !accountMenuRef.current?.contains(target)) {
        setAccountMenuOpen(false);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [accountMenuOpen, taskMenuOpen]);

  useEffect(() => {
    setExpandedTowerIds((current) => {
      const next = new Set(current);
      if (!next.size) {
        for (const tower of towers) next.add(tower.id);
      }
      if (selectedTower) next.add(selectedTower.id);
      if (next.size === current.size && [...next].every((id) => current.has(id))) {
        return current;
      }
      return next;
    });
  }, [selectedTower?.id, towers]);

  useEffect(() => {
    if (!resizingSidebar) return;

    function updateSidebarWidth(event: PointerEvent) {
      const body = shellBodyRef.current;
      if (!body) return;
      const nextWidth = event.clientX - body.getBoundingClientRect().left;
      setSidebarWidth(Math.min(maxSidebarWidth, Math.max(minSidebarWidth, nextWidth)));
    }

    function stopResize() {
      setResizingSidebar(false);
    }

    document.body.classList.add("sidebar-resizing");
    window.addEventListener("pointermove", updateSidebarWidth);
    window.addEventListener("pointerup", stopResize);
    return () => {
      document.body.classList.remove("sidebar-resizing");
      window.removeEventListener("pointermove", updateSidebarWidth);
      window.removeEventListener("pointerup", stopResize);
    };
  }, [resizingSidebar]);

  function navigate(page: PageKey) {
    onNavigate(page);
    setViewMenuOpen(false);
    setAccountMenuOpen(false);
    setTaskMenuOpen(false);
    if (page === "service") resetWorkspaceScroll();
  }

  function openPasswordDialog() {
    setPasswordForm(emptyPasswordForm);
    setPasswordMessage("");
    setPasswordDialogOpen(true);
    setAccountMenuOpen(false);
  }

  async function submitPassword(event: FormEvent) {
    event.preventDefault();
    setPasswordMessage("");
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      setPasswordMessage("两次输入的新密码不一致");
      return;
    }
    setPasswordSaving(true);
    try {
      await api.changePassword(passwordForm);
      setPasswordForm(emptyPasswordForm);
      setPasswordMessage("平台密码已更新");
    } catch (exc) {
      setPasswordMessage(exc instanceof Error ? exc.message : "密码更新失败");
    } finally {
      setPasswordSaving(false);
    }
  }

  function closePasswordDialog() {
    if (passwordSaving) return;
    setPasswordDialogOpen(false);
    setPasswordForm(emptyPasswordForm);
    setPasswordMessage("");
  }

  function selectTower(towerId: number) {
    onScopeChange({ type: "tower", towerId });
    onNavigate("dashboard");
  }

  function selectCluster(towerId: number, clusterId: string) {
    onScopeChange({ type: "cluster", towerId, clusterId });
    onNavigate("dashboard");
  }

  function toggleTower(towerId: number) {
    setExpandedTowerIds((current) => {
      const next = new Set(current);
      if (next.has(towerId)) next.delete(towerId);
      else next.add(towerId);
      return next;
    });
  }

  function beginClusterEdit(towerId: number, cluster: Cluster) {
    setEditingCluster({ towerId, clusterId: cluster.cluster_id, name: cluster.name });
  }

  async function saveClusterName() {
    if (!editingCluster) return;
    const name = editingCluster.name.trim();
    if (!name) {
      setEditingCluster(null);
      return;
    }
    await api.updateCluster(editingCluster.towerId, editingCluster.clusterId, { name });
    setEditingCluster(null);
    onSummary(await api.summary(scope));
  }

  return (
    <div className={["shell", resizingSidebar ? "resizing-sidebar" : "", serviceFocus ? "service-focus" : ""].filter(Boolean).join(" ")} style={shellStyle}>
      <header className="shell-header">
        <div className="brand">
          <div className="brand-mark" />
          <span>SmartX</span>
        </div>
        <div className="topbar">
          <div className="topbar-actions">
            <button className="icon-button" title="通知" type="button">
              <Bell size={18} />
            </button>
            <div className="task-menu-wrap" ref={taskMenuRef}>
              <button className={taskMenuOpen ? "icon-button active" : "icon-button"} title="任务" type="button" onClick={() => setTaskMenuOpen((open) => !open)} aria-haspopup="menu" aria-expanded={taskMenuOpen}>
                <ClipboardList size={18} />
                {runningTaskCount > 0 && <span className="task-badge">{runningTaskCount}</span>}
              </button>
              {taskMenuOpen && (
                <div className="task-menu" role="menu">
                  <div className="task-menu-head">
                    <strong>任务</strong>
                    <button type="button" onClick={onClearTasks} disabled={!tasks.length}>清空</button>
                  </div>
                  {visibleTasks.length ? (
                    <div className="task-menu-list auto-scrollbar">
                      {visibleTasks.map((task) => (
                        <div className={`task-menu-item ${task.status}`} key={task.id}>
                          <span className="task-state-icon">{task.status === "succeeded" ? <Check size={14} /> : task.status === "failed" ? <X size={14} /> : <ClipboardList size={14} />}</span>
                          <div>
                            <strong>{task.title}</strong>
                            <small>{task.detail || taskStatusText(task.status)}</small>
                            <span className="task-progress" aria-label={`${task.progress}%`}>
                              <span style={{ width: `${task.progress}%` }} />
                            </span>
                          </div>
                          <em>{Math.round(task.progress)}%</em>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="task-menu-empty">暂无后台任务</div>
                  )}
                </div>
              )}
            </div>
            <div className="account-menu-wrap" ref={accountMenuRef}>
              <button className="avatar-button" type="button" onClick={() => setAccountMenuOpen((open) => !open)} aria-haspopup="menu" aria-expanded={accountMenuOpen} title="账号">
                <UserRound size={17} />
              </button>
              {accountMenuOpen && (
                <div className="account-menu" role="menu">
                  <button type="button" role="menuitem" onClick={openPasswordDialog}>
                    <KeyRound size={15} />
                    <span>设置密码</span>
                  </button>
                  <button type="button" role="menuitem" onClick={onLogout}>
                    <LogOut size={15} />
                    <span>登出</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {passwordDialogOpen && (
        <div className="modal-backdrop" role="presentation" onClick={closePasswordDialog}>
          <form className="password-dialog" role="dialog" aria-modal="true" aria-labelledby="password-dialog-title" onSubmit={submitPassword} onClick={(event) => event.stopPropagation()}>
            <div className="password-dialog-head">
              <div>
                <strong id="password-dialog-title">设置平台密码</strong>
                <span>更新当前登录账号的密码。</span>
              </div>
              <button className="icon-button" type="button" onClick={closePasswordDialog} disabled={passwordSaving} aria-label="关闭">
                <X size={16} />
              </button>
            </div>
            <label>
              当前密码
              <input type="password" value={passwordForm.current_password} onChange={(event) => setPasswordForm({ ...passwordForm, current_password: event.target.value })} required />
            </label>
            <label>
              新密码
              <input type="password" value={passwordForm.new_password} onChange={(event) => setPasswordForm({ ...passwordForm, new_password: event.target.value })} required />
            </label>
            <label>
              确认新密码
              <input type="password" value={passwordForm.confirm_password} onChange={(event) => setPasswordForm({ ...passwordForm, confirm_password: event.target.value })} required />
            </label>
            {passwordMessage && <div className="inline-message">{passwordMessage}</div>}
            <div className="password-dialog-actions">
              <button className="secondary-button" type="button" onClick={closePasswordDialog} disabled={passwordSaving}>
                取消
              </button>
              <button className="primary-button" type="submit" disabled={passwordSaving}>
                <Save size={15} />
                {passwordSaving ? "保存中" : "修改密码"}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="shell-body" ref={shellBodyRef}>
        <aside className="sidebar" aria-hidden={serviceFocus}>
          <div className="cluster-select">
            <span>集群</span>
            <ChevronDown size={16} />
          </div>
          <div className="resource-tree auto-scrollbar">
            {selectedTower && (
              <div className="sidebar-active-card">
                <div className="sidebar-active-title">
                  <Database size={17} />
                  <span>SmartX ZBS</span>
                </div>
                <div className="sidebar-active-status">
                  <CircleCheck size={12} />
                  <span>{selectedTowerStatus}</span>
                </div>
              </div>
            )}
            {towers.length ? (
              <>
                <div className="tree-list">
                  {towers.map((tower) => {
                    const isExpanded = expandedTowerIds.has(tower.id);
                    const towerSelected = selectedScopeKey === scopeKey({ type: "tower", towerId: tower.id });
                    return (
                      <div key={tower.id} className="tree-section">
                        <div className={towerSelected ? "tree-row tree-datacenter active" : "tree-row tree-datacenter"}>
                          <button className="tree-toggle" type="button" aria-label={isExpanded ? "收起数据中心" : "展开数据中心"} onClick={() => toggleTower(tower.id)}>
                            <ChevronDown className={isExpanded ? "tree-caret open" : "tree-caret"} size={13} />
                          </button>
                          <button className="tree-label-button" type="button" onClick={() => selectTower(tower.id)}>
                            <Building2 size={15} />
                            <span>{tower.name}</span>
                          </button>
                        </div>
                        {isExpanded && (
                          <div className="tree-children">
                            {tower.clusters.length ? (
                              tower.clusters.map((cluster) => {
                                const isEditing = editingCluster?.towerId === tower.id && editingCluster.clusterId === cluster.cluster_id;
                                const clusterSelected = selectedScopeKey === scopeKey({ type: "cluster", towerId: tower.id, clusterId: cluster.cluster_id });
                                return (
                                  <div className={clusterSelected ? "tree-row tree-cluster active" : "tree-row tree-cluster"} key={cluster.cluster_id}>
                                    <HardDrive size={14} />
                                    {isEditing ? (
                                      <input
                                        className="tree-edit-input"
                                        value={editingCluster.name}
                                        autoFocus
                                        onBlur={saveClusterName}
                                        onChange={(event) => setEditingCluster({ ...editingCluster, name: event.target.value })}
                                        onKeyDown={(event) => {
                                          if (event.key === "Enter") void saveClusterName();
                                          if (event.key === "Escape") setEditingCluster(null);
                                        }}
                                      />
                                    ) : (
                                      <button className="tree-label-button" type="button" onClick={() => selectCluster(tower.id, cluster.cluster_id)} onDoubleClick={() => beginClusterEdit(tower.id, cluster)}>
                                        <span>{cluster.name}</span>
                                      </button>
                                    )}
                                  </div>
                                );
                              })
                            ) : (
                              <div className="tree-node-empty">暂无集群</div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="tree-empty">未配置数据中心</div>
            )}
            <div className="tree-summary">
              {towers.length} 数据中心，{totalClusterCount} 集群
            </div>
          </div>
          <div className="sidebar-footer">
            <button
              className="view-options-button"
              type="button"
              aria-haspopup="menu"
              aria-expanded={viewMenuOpen}
              onClick={() => setViewMenuOpen((open) => !open)}
            >
              <View size={15} />
              <span>视图选项</span>
              <ChevronDown className={viewMenuOpen ? "chevron open" : "chevron"} size={14} />
            </button>
            {viewMenuOpen && (
              <div className="view-menu" role="menu">
                {navItems.map((item) => (
                  <button
                    key={item.key}
                    className={item.key === activePage ? "view-menu-item active" : "view-menu-item"}
                    type="button"
                    role="menuitem"
                    onClick={() => navigate(item.key)}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>
        <div
          className="sidebar-resizer"
          role="separator"
          aria-orientation="vertical"
          aria-label="调整左侧栏宽度"
          onPointerDown={(event) => {
            if (serviceFocus) return;
            event.preventDefault();
            setResizingSidebar(true);
          }}
        />

        <section className="workspace auto-scrollbar">
          <main className="main">
            <div className="page-heading">
              <h1>{pageTitle[activePage]}</h1>
              <nav className="tabs">
                {navItems.map((item) => (
                  <button
                    key={item.key}
                    className={item.key === activePage ? "tab active" : "tab"}
                    type="button"
                    onClick={() => navigate(item.key)}
                  >
                    {item.icon}
                    {item.label}
                  </button>
                ))}
              </nav>
            </div>
            {children}
          </main>
        </section>
      </div>
    </div>
  );
}


function taskStatusText(status: AppTask["status"]): string {
  const labels: Record<AppTask["status"], string> = {
    running: "执行中",
    succeeded: "已完成",
    failed: "失败"
  };
  return labels[status];
}
