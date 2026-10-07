import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";

const apiMock = vi.hoisted(() => ({
  towers: vi.fn(),
  createTower: vi.fn()
}));

vi.mock("../services/api", async () => ({
  api: apiMock
}));

describe("SettingsPage", () => {
  it("keeps settings focused on Tower configuration", async () => {
    apiMock.towers.mockResolvedValue([]);

    render(<SettingsPage />);

    expect(screen.getByText("新增 Tower")).toBeInTheDocument();
    expect(screen.getByText("Tower 列表")).toBeInTheDocument();
    await waitFor(() => expect(apiMock.towers).toHaveBeenCalled());
    expect(screen.queryByText("服务管理")).not.toBeInTheDocument();
    expect(screen.queryByText("系统升级")).not.toBeInTheDocument();
    expect(screen.queryByText("数据迁移")).not.toBeInTheDocument();
  });

  it("allows configuring collection retry defaults when creating a tower", async () => {
    apiMock.towers.mockResolvedValue([]);
    apiMock.createTower.mockResolvedValue({});

    render(<SettingsPage />);

    expect(screen.getByLabelText("启用采集失败重试")).toBeChecked();
    expect(screen.getByLabelText("重试间隔 - 分钟")).toHaveValue(15);
    expect(screen.getByLabelText("最大重试次数")).toHaveValue(3);

    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Tower A" } });
    fireEvent.change(screen.getByLabelText("地址"), { target: { value: "https://tower.example.com" } });
    fireEvent.change(screen.getByLabelText("重试间隔 - 分钟"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("最大重试次数"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /创建/ }));

    await waitFor(() => expect(apiMock.createTower).toHaveBeenCalled());
    expect(apiMock.createTower).toHaveBeenCalledWith(expect.objectContaining({
      collection_retry_enabled: true,
      collection_retry_interval_minutes: 30,
      collection_retry_max_attempts: 2
    }));
  });
  it("hides the stale indicator when the last successful collection is within 24 hours", async () => {
    // 20 小时前（UTC、无时区后缀）——既验证 ≤24h 不显示，也判别 UTC 解析（若按本地解析会变 28h → 误显示 ⚠ 1 天）
    const naiveUtc20hAgo = new Date(Date.now() - 20 * 3600_000).toISOString().replace("T", " ").slice(0, 19);
    apiMock.towers.mockResolvedValue([
      {
        id: 1,
        name: "SMTX_TEST",
        base_url: "https://10.20.11.101",
        verify_tls: false,
        clusters: [{ cluster_id: "c1", name: "SMTX_Test", enabled: true }],
        last_success_at: naiveUtc20hAgo
      }
    ]);

    render(<SettingsPage />);

    expect(await screen.findByText("SMTX_TEST")).toBeInTheDocument();
    expect(document.querySelector(".tower-health")).toBeNull();
  });

  it("shows a yellow stale indicator with day count only when the last success is older than 24 hours", async () => {
    // 25 小时前 → 超过 24 小时 → 「⚠ 1 天」（用户口径：超过 24 小时也就是 1 天才出现）
    const naiveUtc25hAgo = new Date(Date.now() - 25 * 3600_000).toISOString().replace("T", " ").slice(0, 19);
    const naiveUtc50hAgo = new Date(Date.now() - 50 * 3600_000).toISOString().replace("T", " ").slice(0, 19);
    apiMock.towers.mockResolvedValue([
      {
        id: 2,
        name: "CHINATOWER",
        base_url: "https://10.20.11.7:4433",
        verify_tls: false,
        clusters: [{ cluster_id: "c2", name: "SMARTX-TT-WW", enabled: true }],
        last_success_at: naiveUtc25hAgo
      },
      {
        id: 3,
        name: "OLD_TOWER",
        base_url: "https://10.20.11.60",
        verify_tls: true,
        clusters: [],
        last_success_at: naiveUtc50hAgo
      },
      {
        id: 4,
        name: "NEW_TOWER",
        base_url: "https://10.20.11.50",
        verify_tls: true,
        clusters: [],
        last_success_at: null
      }
    ]);

    render(<SettingsPage />);

    expect(await screen.findByText("1 天")).toBeInTheDocument();
    expect(screen.getByText("2 天")).toBeInTheDocument();
    expect(screen.getByText("未采集")).toBeInTheDocument();
    const staleNodes = document.querySelectorAll(".tower-health.stale");
    expect(staleNodes.length).toBe(3);
    // 不再出现旧的「✗ N 分钟前采集」字样
    expect(screen.queryByText(/分钟前采集/)).not.toBeInTheDocument();
    expect(screen.queryByText(/小时前采集/)).not.toBeInTheDocument();
  });

  it("shows Tower and SmartXOS versions under the base url", async () => {
    // 2026-10-07 用户要求：网址下面两行 —— Tower: v4.5.0 / SmartXOS: 6.1.1；
    // 没读到版本时显示 "-"；一塔多集群版本不同时并列展示。
    apiMock.towers.mockResolvedValue([
      {
        id: 1,
        name: "SMTX_TEST",
        base_url: "https://10.20.11.101",
        verify_tls: false,
        tower_version: "v4.5.0",
        clusters: [
          { cluster_id: "c1", name: "SMTX_Test", enabled: true, os_version: "6.1.1" },
          { cluster_id: "c2", name: "SMTX_Test2", enabled: true, os_version: "6.0.3" }
        ],
        last_success_at: null
      },
      {
        id: 2,
        name: "UNKNOWN_TOWER",
        base_url: "https://10.20.11.60",
        verify_tls: true,
        tower_version: null,
        clusters: [{ cluster_id: "c3", name: "C3", enabled: true }],
        last_success_at: null
      }
    ]);

    render(<SettingsPage />);

    expect(await screen.findByText("Tower: v4.5.0")).toBeInTheDocument();
    expect(screen.getByText("SmartXOS: 6.1.1 / 6.0.3")).toBeInTheDocument();
    expect(screen.getByText("Tower: -")).toBeInTheDocument();
    expect(screen.getByText("SmartXOS: -")).toBeInTheDocument();
  });

});
