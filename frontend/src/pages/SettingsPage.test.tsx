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
});
