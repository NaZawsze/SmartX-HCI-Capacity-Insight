import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";

const apiMock = vi.hoisted(() => ({
  towers: vi.fn()
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
});
