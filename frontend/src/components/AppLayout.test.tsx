import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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

describe("AppLayout menus", () => {
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
});
