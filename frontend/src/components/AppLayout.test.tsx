import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppLayout } from "./AppLayout";
import type { AppTask, DashboardScope, DashboardSummary, PageKey } from "../types";

const summary: DashboardSummary = {
  towers: [
    {
      id: 1,
      name: "Tower A",
      base_url: "https://tower-a",
      verify_tls: false,
      enabled: true,
      collection_hour: 2,
      collection_minute: 10,
      clusters: [{ cluster_id: "cluster-1", name: "Cluster 1", enabled: true }]
    }
  ],
  kpis: {
    tower_count: 1,
    cluster_count: 1,
    vm_count: 0,
    total_bytes: 0,
    used_bytes: 0,
    used_ratio: 0
  },
  top_vms: [],
  day_new_vms: [],
  clusters: []
};

const baseProps = {
  activePage: "dashboard" as PageKey,
  onNavigate: vi.fn(),
  onLogout: vi.fn(),
  scope: { type: "all" } as DashboardScope,
  onScopeChange: vi.fn(),
  onSummary: vi.fn(),
  summary,
  children: <div data-testid="outside-content">内容区</div>
};

function runningTask(): AppTask {
  return {
    id: "task-1",
    kind: "upgrade",
    title: "执行升级",
    detail: "正在加载镜像",
    status: "running",
    progress: 42,
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
}

function runningInfoTask(): AppTask {
  return {
    id: "task-running-info",
    kind: "export",
    title: "导出预测报表",
    detail: "正在生成 Word 和 Excel",
    status: "running",
    severity: "info",
    unhandled: true,
    progress: 35,
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
}

function failedTask(): AppTask {
  return {
    id: "task-failed",
    kind: "upgrade",
    title: "执行升级失败",
    detail: "升级失败：镜像 sha256 不匹配",
    status: "failed",
    severity: "critical",
    unhandled: true,
    clearable: false,
    progress: 100,
    steps: [
      { key: "manifest", title: "校验 manifest", status: "succeeded", message: "通过" },
      { key: "images", title: "校验镜像", status: "failed", message: "sha256 不匹配" }
    ],
    logs: ["manifest 格式正确", "镜像 sha256 不匹配：images/web-api.tar"],
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
}

function succeededInfoTask(): AppTask {
  return {
    id: "task-info",
    kind: "export",
    title: "导出预测报表",
    detail: "Word 和 Excel 报表已生成",
    status: "succeeded",
    severity: "info",
    unhandled: true,
    clearable: false,
    progress: 100,
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
}

function succeededDownloadTask(): AppTask {
  return {
    id: "task-download",
    kind: "export",
    title: "导出迁移包",
    detail: "迁移包已生成",
    status: "succeeded",
    severity: "info",
    unhandled: true,
    clearable: false,
    progress: 100,
    links: [
      { label: "迁移包", filename: "migration.tar.gz", url: "/api/download/migration.tar.gz", path: "/data/exports/migrations/migration.tar.gz" },
      { label: "整理前备份", filename: "sqlite-before.tar.gz", url: "/api/download/sqlite-before.tar.gz", path: "/data/backups/sqlite-before.tar.gz" }
    ],
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
}

function succeededReportDownloadTask(): AppTask {
  return {
    id: "task-report-download",
    kind: "export",
    title: "导出预测报表",
    detail: "Word 和 Excel 报表已生成",
    status: "succeeded",
    severity: "info",
    unhandled: true,
    clearable: false,
    progress: 100,
    links: [
      { label: "Word", filename: "storage-forecast.docx", url: "/api/admin/exports/reports/storage-forecast.docx", path: "/data/exports/reports/storage-forecast.docx" },
      { label: "Excel", filename: "storage-forecast.xlsx", url: "/api/admin/exports/reports/storage-forecast.xlsx", path: "/data/exports/reports/storage-forecast.xlsx" }
    ],
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
}

function pendingUpgradeTask(): AppTask {
  return {
    id: "upgrade-pending",
    kind: "upgrade",
    title: "执行系统升级",
    detail: "升级任务已提交，等待 upgrade-runner 执行",
    status: "pending",
    progress: 1,
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
}

function pendingCleanupTask(): AppTask {
  return {
    id: "cleanup-pending",
    kind: "upgrade",
    title: "空间清理",
    detail: "等待扫描清理文件",
    status: "pending",
    progress: 1,
    createdAt: Date.now(),
    updatedAt: Date.now()
  };
}

describe("AppLayout menus", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps service management as a main navigation item after settings", () => {
    const onNavigate = vi.fn();
    render(<AppLayout {...baseProps} onNavigate={onNavigate} />);

    const settings = screen.getByRole("button", { name: /设置/ });
    const service = screen.getByRole("button", { name: /服务管理/ });
    expect(settings.compareDocumentPosition(service) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(service);
    expect(onNavigate).toHaveBeenCalledWith("service");
  });

  it("closes the account menu when clicking outside", async () => {
    render(<AppLayout {...baseProps} />);

    fireEvent.click(screen.getByTitle("账号"));
    expect(screen.getByRole("menuitem", { name: /设置密码/ })).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByTestId("outside-content"));

    await waitFor(() => {
      expect(screen.queryByRole("menuitem", { name: /设置密码/ })).not.toBeInTheDocument();
    });
  });

  it("closes the task menu when clicking outside", async () => {
    render(<AppLayout {...baseProps} tasks={[runningTask()]} />);

    fireEvent.click(screen.getByTitle("任务"));
    expect(screen.getByText("执行升级")).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByTestId("outside-content"));

    await waitFor(() => {
      expect(screen.queryByText("执行升级")).not.toBeInTheDocument();
    });
  });

  it("shows failed task step and error summary in the task menu", () => {
    render(<AppLayout {...baseProps} tasks={[failedTask()]} />);

    fireEvent.click(screen.getByTitle("任务"));

    expect(screen.getByText("执行升级失败")).toBeInTheDocument();
    expect(screen.getByText("升级失败：镜像 sha256 不匹配")).toBeInTheDocument();
    expect(screen.getByText(/失败 校验镜像/)).toBeInTheDocument();
    expect(screen.getByText("镜像 sha256 不匹配：images/web-api.tar")).toBeInTheDocument();
  });

  it("shows a cancel button for pending upgrade tasks", () => {
    const onTaskAction = vi.fn();
    const task = pendingUpgradeTask();
    render(<AppLayout {...baseProps} tasks={[task]} onTaskAction={onTaskAction} />);

    fireEvent.click(screen.getByTitle("任务"));
    expect(screen.getByText("升级任务已提交，等待 upgrade-runner 执行")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("取消等待任务"));
    expect(onTaskAction).toHaveBeenCalledWith(task);
  });

  it("does not show the cancel button for non-upgrade pending tasks", () => {
    render(<AppLayout {...baseProps} tasks={[pendingCleanupTask()]} onTaskAction={vi.fn()} />);

    fireEvent.click(screen.getByTitle("任务"));
    expect(screen.queryByTitle("取消等待任务")).not.toBeInTheDocument();
  });

  it("shows a remove button for failed tasks", () => {
    const onTaskAction = vi.fn();
    const task = failedTask();
    render(<AppLayout {...baseProps} tasks={[task]} onTaskAction={onTaskAction} />);

    fireEvent.click(screen.getByTitle("任务"));
    fireEvent.click(screen.getByTitle("从任务中心移除"));

    expect(onTaskAction).toHaveBeenCalledWith(task);
  });

  it("uses unhandled notifications for the badge and marks info tasks seen after closing", async () => {
    const onTasksSeen = vi.fn();
    const { container } = render(<AppLayout {...baseProps} tasks={[succeededInfoTask(), runningTask()]} onTasksSeen={onTasksSeen} />);

    expect(screen.getByText("1")).toHaveClass("task-badge");

    fireEvent.click(screen.getByTitle("任务"));
    expect(container.querySelector(".task-state-icon.info")).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByTestId("outside-content"));

    await waitFor(() => {
      expect(onTasksSeen).toHaveBeenCalledWith(["task-info"]);
    });
  });

  it("keeps running info tasks badged and visible with progress until they finish", async () => {
    const onTasksSeen = vi.fn();
    render(<AppLayout {...baseProps} tasks={[runningInfoTask()]} onTasksSeen={onTasksSeen} />);

    expect(screen.getByText("1")).toHaveClass("task-badge");

    fireEvent.click(screen.getByTitle("任务"));
    expect(screen.getByText("导出预测报表")).toBeInTheDocument();
    expect(screen.getByText("正在生成 Word 和 Excel")).toBeInTheDocument();
    expect(screen.getByText("35%")).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByTestId("outside-content"));

    await waitFor(() => {
      expect(screen.queryByText("导出预测报表")).not.toBeInTheDocument();
    });
    expect(onTasksSeen).not.toHaveBeenCalled();
  });

  it("uses a unified download label for all task download links", () => {
    render(<AppLayout {...baseProps} tasks={[succeededDownloadTask()]} />);

    fireEvent.click(screen.getByTitle("任务"));

    const downloadButtons = screen.getAllByRole("button", { name: "下载" });
    expect(downloadButtons).toHaveLength(2);
    expect(downloadButtons[0]).toHaveAttribute("title", "/data/exports/migrations/migration.tar.gz");
    expect(downloadButtons[1]).toHaveAttribute("title", "/data/backups/sqlite-before.tar.gz");
  });

  it("keeps Word and Excel labels for report export download links", () => {
    render(<AppLayout {...baseProps} tasks={[succeededReportDownloadTask()]} />);

    fireEvent.click(screen.getByTitle("任务"));

    expect(screen.getByRole("button", { name: "Word" })).toHaveAttribute("title", "/data/exports/reports/storage-forecast.docx");
    expect(screen.getByRole("button", { name: "Excel" })).toHaveAttribute("title", "/data/exports/reports/storage-forecast.xlsx");
    expect(screen.queryByRole("button", { name: "下载" })).not.toBeInTheDocument();
  });

  it("shows all loaded tasks and enables clear for succeeded info tasks", () => {
    const onClearTasks = vi.fn();
    const tasks = Array.from({ length: 12 }, (_, index) => ({
      ...succeededInfoTask(),
      id: `task-info-${index}`,
      title: `信息任务 ${index + 1}`,
      unhandled: false,
      clearable: index === 0,
      updatedAt: Date.now() - index
    }));
    render(<AppLayout {...baseProps} tasks={tasks} onClearTasks={onClearTasks} />);

    fireEvent.click(screen.getByTitle("任务"));

    expect(screen.getByText("信息任务 1")).toBeInTheDocument();
    expect(screen.getByText("信息任务 12")).toBeInTheDocument();

    const clearButton = screen.getByRole("button", { name: "清空" });
    expect(clearButton).not.toBeDisabled();
    fireEvent.click(clearButton);
    expect(onClearTasks).toHaveBeenCalledTimes(1);
  });

  it("shows acknowledge and remove controls for failed warning or critical tasks", () => {
    const onTaskAck = vi.fn();
    const onTaskAction = vi.fn();
    const task = failedTask();
    render(<AppLayout {...baseProps} tasks={[task]} onTaskAck={onTaskAck} onTaskAction={onTaskAction} />);

    fireEvent.click(screen.getByTitle("任务"));
    fireEvent.click(screen.getByTitle("确认任务告警"));
    fireEvent.click(screen.getByTitle("从任务中心移除"));

    expect(onTaskAck).toHaveBeenCalledWith(task);
    expect(onTaskAction).toHaveBeenCalledWith(task);
  });

  it("only reveals auto scrollbars while the user is scrolling", () => {
    vi.useFakeTimers();
    render(<AppLayout {...baseProps} />);

    const workspace = document.querySelector<HTMLElement>(".workspace.auto-scrollbar");
    expect(workspace).toBeTruthy();
    expect(workspace).not.toHaveClass("is-scrolling");

    fireEvent.scroll(workspace!);
    expect(workspace).toHaveClass("is-scrolling");

    act(() => {
      vi.advanceTimersByTime(900);
    });

    expect(workspace).not.toHaveClass("is-scrolling");
  });
});
