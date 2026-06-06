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
