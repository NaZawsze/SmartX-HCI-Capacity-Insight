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
    render(<AppLayout {...baseProps} tasks={[succeededInfoTask(), runningTask()]} onTasksSeen={onTasksSeen} />);

    expect(screen.getByText("1")).toHaveClass("task-badge");

    fireEvent.click(screen.getByTitle("任务"));
    fireEvent.pointerDown(screen.getByTestId("outside-content"));

    await waitFor(() => {
      expect(onTasksSeen).toHaveBeenCalledWith(["task-info"]);
    });
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
