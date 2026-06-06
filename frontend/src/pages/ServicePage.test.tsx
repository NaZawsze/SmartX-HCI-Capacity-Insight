import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { formatVersionForDisplay } from "./ServicePage";
import { ServicePage } from "./ServicePage";

const apiMock = vi.hoisted(() => ({
  upgradeVersion: vi.fn(),
  componentUpgradeVersion: vi.fn(),
  upgradeHistory: vi.fn(),
  componentUpgradeHistory: vi.fn(),
  upgradeVerification: vi.fn(),
  importMigration: vi.fn()
}));

vi.mock("../services/api", async () => ({
  api: apiMock,
  formatBytes: (value: number | null | undefined) => `${value ?? 0} B`
}));

function mockServicePageBootstrap() {
  apiMock.upgradeVersion.mockResolvedValue({ version: "v0.4.1" });
  apiMock.componentUpgradeVersion.mockResolvedValue({ component: "upgrade-runner", version: "v0.2.2" });
  apiMock.upgradeHistory.mockResolvedValue([]);
  apiMock.componentUpgradeHistory.mockResolvedValue([]);
  apiMock.upgradeVerification.mockResolvedValue({
    app_version: "v0.4.1",
    runner_version: "v0.2.2",
    compose_project: "smartx-capacity-insight",
    compose_file: "docker-compose.offline.yml",
    package: null,
    services: []
  });
}

describe("formatVersionForDisplay", () => {
  it("displays canonical prefixed software versions", () => {
    expect(formatVersionForDisplay("v0.4.0")).toBe("v0.4.0");
  });

  it("keeps existing v prefix unchanged", () => {
    expect(formatVersionForDisplay("v0.1.0")).toBe("v0.1.0");
  });

  it("keeps empty display placeholder unchanged", () => {
    expect(formatVersionForDisplay("-")).toBe("-");
  });
});

describe("ServicePage migration overwrite mode", () => {
  it("requires explicit confirmation before overwrite import can start", async () => {
    mockServicePageBootstrap();
    apiMock.importMigration.mockResolvedValue({
      ok: true,
      restored: ["smartx_db"],
      message: "导入完成"
    });
    const addTask = vi.fn();
    const updateTask = vi.fn();
    render(<ServicePage addTask={addTask} updateTask={updateTask} />);

    fireEvent.click(screen.getByRole("button", { name: "数据迁移" }));
    await waitFor(() => expect(screen.getByText("迁移包导入")).toBeInTheDocument());

    const file = new File(["migration"], "migration.tar.gz", { type: "application/gzip" });
    const input = document.querySelector<HTMLInputElement>('input[type="file"][accept*=".tar.gz"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files: [file] } });

    fireEvent.click(screen.getByRole("button", { name: "覆盖导入" }));
    const importButton = screen.getByRole("button", { name: /导入迁移包/ });
    expect(importButton).toBeDisabled();
    expect(apiMock.importMigration).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("我确认覆盖当前系统数据"));
    expect(importButton).not.toBeDisabled();
    fireEvent.click(importButton);

    await waitFor(() => {
      expect(apiMock.importMigration).toHaveBeenCalledWith(file, "overwrite", true, expect.any(Function));
    });
    expect(addTask).toHaveBeenCalledWith(expect.objectContaining({ kind: "import", title: "导入迁移包" }));
  });
});
