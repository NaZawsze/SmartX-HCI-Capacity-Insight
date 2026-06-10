import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatVersionForDisplay } from "./ServicePage";
import { ServicePage } from "./ServicePage";

const apiMock = vi.hoisted(() => ({
  upgradeVersion: vi.fn(),
  componentUpgradeVersion: vi.fn(),
  componentUpgradeComponents: vi.fn(),
  upgradeHistory: vi.fn(),
  componentUpgradeHistory: vi.fn(),
  upgradeVerification: vi.fn(),
  precheckUpgrade: vi.fn(),
  startUpgrade: vi.fn(),
  continueUpgradeRecovery: vi.fn(),
  rollbackUpgradeRecovery: vi.fn(),
  failUpgradeRecovery: vi.fn(),
  importMigration: vi.fn(),
  startMigrationImport: vi.fn(),
  migrationImportStatus: vi.fn(),
  exportConfigMigration: vi.fn(),
  downloadSavedExport: vi.fn(),
  scanSpaceCleanup: vi.fn(),
  scanSqliteVacuum: vi.fn(),
  vacuumSqlite: vi.fn(),
  scanSqliteBackups: vi.fn(),
  deleteSqliteBackups: vi.fn(),
  localStorageUsage: vi.fn()
}));

vi.mock("../services/api", async () => ({
  api: apiMock,
  formatBytes: (value: number | null | undefined) => `${value ?? 0} B`
}));

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:service");
  URL.revokeObjectURL = vi.fn();
  HTMLAnchorElement.prototype.click = vi.fn();
});

function mockServicePageBootstrap() {
  apiMock.upgradeVersion.mockResolvedValue({ version: "v0.5.0" });
  apiMock.componentUpgradeVersion.mockResolvedValue({ component: "upgrade-runner", version: "v0.3.0" });
  apiMock.componentUpgradeComponents.mockResolvedValue({
    components: [
      {
        type: "runner",
        display_name: "升级中心组件",
        service: "upgrade-runner",
        version: "v0.3.0",
        executor: "web-api",
        upgradeable: true
      },
      {
        type: "observability",
        display_name: "观测组件",
        service: "prometheus",
        version: "v2.55.1",
        executor: "upgrade-runner",
        upgradeable: true
      }
    ]
  });
  apiMock.upgradeHistory.mockResolvedValue([]);
  apiMock.componentUpgradeHistory.mockResolvedValue([]);
  apiMock.upgradeVerification.mockResolvedValue({
    app_version: "v0.5.0",
    runner_version: "v0.3.0",
    prometheus_version: "v2.55.1",
    compose_project: "smartx-capacity-insight",
    compose_file: "docker-compose.offline.yml",
    package: null,
    service_status_error: null,
    services: []
  });
  apiMock.localStorageUsage.mockResolvedValue({
    path: "/data",
    total_bytes: 1000,
    used_bytes: 850,
    free_bytes: 150,
    used_ratio: 0.85,
    free_ratio: 0.15,
    total_label: "1000 B",
    used_label: "850 B",
    free_label: "150 B"
  });
  apiMock.scanSqliteVacuum.mockResolvedValue({
    ok: true,
    path: "/data/smartx.db",
    size: 1024,
    size_label: "1024 B",
    page_count: 10,
    freelist_count: 1,
    page_size: 1024,
    estimated_reclaimable: 1024,
    estimated_reclaimable_label: "1024 B",
    runtime_cache: {
      metric_snapshots: { keep: 1, delete_count: 0 },
      collection_runs: { retention_days: 7, delete_count: 1 },
      tasks: { retention_days: 30, delete_count: 2 }
    },
    message: "SQLite 当前大小 1024 B，预计可整理释放 1024 B。"
  });
  apiMock.scanSqliteBackups.mockResolvedValue({
    ok: true,
    items: [],
    total_count: 0,
    total_size: 0,
    total_size_label: "0 B",
    message: "发现 0 个 SQLite 数据库备份，可释放 0 B。"
  });
  apiMock.deleteSqliteBackups.mockResolvedValue({
    ok: true,
    deleted_count: 0,
    space_reclaimed: 0,
    space_reclaimed_label: "0 B",
    logs: ["没有删除 SQLite 备份"],
    message: "SQLite 备份清理完成，释放 0 B。"
  });
}

function uploadedPlatformTask() {
  return {
    task_id: "upgrade-1",
    status: "uploaded",
    target_version: "v0.4.2",
    package_filename: "smartx-capacity-insight-upgrade-v0.4.2.tar.gz",
    restart_services: ["web-api", "collector-worker", "frontend"],
    database_migration: true,
    checks: [],
    steps: [],
    logs: []
  };
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
  it("renders service management subnav with migration restart upgrade and cleanup entries", async () => {
    mockServicePageBootstrap();
    render(<ServicePage addTask={vi.fn()} updateTask={vi.fn()} />);

    expect(await screen.findByText("平台状态")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "数据迁移" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "服务重启" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "空间清理" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "平台升级" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "组件升级" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "升级历史" })).toBeInTheDocument();
  });

  it("requires explicit confirmation before overwrite import can start", async () => {
    mockServicePageBootstrap();
    apiMock.startMigrationImport.mockResolvedValue({
      task_id: "migration-import-1",
      status: "succeeded",
      progress: 100,
      detail: "数据迁移导入完成",
      backup_path: "/data/backups/import-before-test.tar.gz",
      logs: ["导入完成"],
      steps: []
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
    expect(apiMock.startMigrationImport).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("我确认覆盖当前系统数据"));
    expect(importButton).not.toBeDisabled();
    fireEvent.click(importButton);

    await waitFor(() => {
      expect(apiMock.startMigrationImport).toHaveBeenCalledWith(file, "overwrite", true, expect.any(Function));
    });
    expect(addTask).toHaveBeenCalledWith(expect.objectContaining({ kind: "import", title: "导入迁移包" }));
  });

  it("exports a lightweight config migration package separately from the full migration package", async () => {
    mockServicePageBootstrap();
    apiMock.exportConfigMigration.mockResolvedValue({
      blob: new Blob(["config"]),
      filename: "smartx-config-migration-20260607120000.tar.gz",
      savedPath: "/data/exports/migrations/smartx-config-migration-20260607120000.tar.gz",
      downloadUrl: "/api/admin/exports/migrations/smartx-config-migration-20260607120000.tar.gz"
    });
    const addTask = vi.fn();
    const updateTask = vi.fn();
    render(<ServicePage addTask={addTask} updateTask={updateTask} />);

    fireEvent.click(screen.getByRole("button", { name: "数据迁移" }));
    fireEvent.click(await screen.findByRole("button", { name: "导出配置迁移包" }));

    await waitFor(() => expect(apiMock.exportConfigMigration).toHaveBeenCalled());
    expect(addTask).toHaveBeenCalledWith(expect.objectContaining({ kind: "export", title: "导出配置迁移包" }));
    expect(updateTask).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ status: "succeeded", detail: "smartx-config-migration-20260607120000.tar.gz" }));
  });

  it("renders artifact cleanup and sqlite cleanup with matching result and log panels", async () => {
    mockServicePageBootstrap();
    apiMock.scanSpaceCleanup.mockResolvedValue({
      ok: true,
      items: [],
      total_count: 0,
      total_size: 0,
      total_size_label: "0 B",
      message: "没有可清理文件"
    });

    render(<ServicePage addTask={vi.fn()} updateTask={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "空间清理" }));
    await waitFor(() => expect(screen.getByText("运行产物清理")).toBeInTheDocument());

    const cleanupSection = screen.getByText("运行产物清理").closest(".cleanup-module");
    const sqliteSection = screen.getByText("SQLite 清理并整理").closest(".cleanup-module");

    expect(cleanupSection).not.toBeNull();
    expect(sqliteSection).not.toBeNull();
    expect(cleanupSection).toContainElement(screen.getByRole("button", { name: "扫描" }));
    expect(cleanupSection).toContainElement(screen.getByRole("button", { name: "一键清理" }));
    expect(sqliteSection).toContainElement(screen.getByRole("button", { name: "扫描 SQLite" }));
    expect(sqliteSection).toContainElement(screen.getByRole("button", { name: "清理并整理 SQLite" }));
    fireEvent.click(screen.getByRole("button", { name: "扫描 SQLite" }));
    await waitFor(() => expect(screen.getByText("采集记录：1 条可清理")).toBeInTheDocument());
    expect(screen.getByText("任务记录：2 条可清理")).toBeInTheDocument();
    expect(cleanupSection!.querySelector(".cleanup-result-panel")).not.toBeNull();
    expect(sqliteSection!.querySelector(".cleanup-result-panel")).not.toBeNull();
    expect(cleanupSection!.querySelector(".cleanup-log")).not.toBeNull();
    expect(sqliteSection!.querySelector(".cleanup-log")).not.toBeNull();
    expect(screen.queryByText("可清理空间")).not.toBeInTheDocument();
  });

  it("scans sqlite backups and deletes only selected backup files", async () => {
    mockServicePageBootstrap();
    apiMock.scanSpaceCleanup.mockResolvedValue({
      ok: true,
      items: [],
      total_count: 0,
      total_size: 0,
      total_size_label: "0 B",
      message: "没有可清理文件"
    });
    apiMock.scanSqliteBackups
      .mockResolvedValueOnce({
        ok: true,
        items: [
          {
            filename: "sqlite-before-cleanup-20260607133053.db",
            path: "/data/backups/sqlite-before-cleanup-20260607133053.db",
            size: 33900000,
            size_label: "33.9 MB",
            modified_at: "2026-06-07T13:30:53+08:00"
          },
          {
            filename: "smartx-before-drop-legacy-volume-items.db",
            path: "/data/backups/smartx-before-drop-legacy-volume-items.db",
            size: 71700000,
            size_label: "71.7 MB",
            modified_at: "2026-06-07T09:27:49+08:00"
          }
        ],
        total_count: 2,
        total_size: 105600000,
        total_size_label: "105.6 MB",
        message: "发现 2 个 SQLite 数据库备份，可释放 105.6 MB。"
      })
      .mockResolvedValueOnce({
        ok: true,
        items: [
          {
            filename: "smartx-before-drop-legacy-volume-items.db",
            path: "/data/backups/smartx-before-drop-legacy-volume-items.db",
            size: 71700000,
            size_label: "71.7 MB"
          }
        ],
        total_count: 1,
        total_size: 71700000,
        total_size_label: "71.7 MB",
        message: "发现 1 个 SQLite 数据库备份，可释放 71.7 MB。"
      });
    apiMock.deleteSqliteBackups.mockResolvedValue({
      ok: true,
      deleted_count: 1,
      space_reclaimed: 33900000,
      space_reclaimed_label: "33.9 MB",
      logs: ["sqlite-before-cleanup-20260607133053.db：删除，释放 33.9 MB"],
      message: "SQLite 备份清理完成，释放 33.9 MB。"
    });
    const addTask = vi.fn();
    const updateTask = vi.fn();
    render(<ServicePage addTask={addTask} updateTask={updateTask} />);

    fireEvent.click(screen.getByRole("button", { name: "空间清理" }));
    await waitFor(() => expect(screen.getByText("SQLite 备份清理")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "扫描备份" }));

    expect(await screen.findByText("sqlite-before-cleanup-20260607133053.db")).toBeInTheDocument();
    expect(screen.getByText("smartx-before-drop-legacy-volume-items.db")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/sqlite-before-cleanup-20260607133053\.db/));
    fireEvent.click(screen.getByRole("button", { name: "删除选中" }));

    await waitFor(() => {
      expect(apiMock.deleteSqliteBackups).toHaveBeenCalledWith(["sqlite-before-cleanup-20260607133053.db"]);
    });
    expect(addTask).toHaveBeenCalledWith(expect.objectContaining({ kind: "upgrade", title: "SQLite 备份清理" }));
    expect(updateTask).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ status: "succeeded", detail: "SQLite 备份清理完成，释放 33.9 MB。" }));
  });

  it("uses the same header button sizing for migration actions", async () => {
    mockServicePageBootstrap();
    render(<ServicePage addTask={vi.fn()} updateTask={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "数据迁移" }));

    expect(await screen.findByRole("button", { name: "健康检查" })).toHaveClass("service-header-button");
    expect(screen.getByRole("button", { name: "导出配置迁移包" })).toHaveClass("service-header-button");
    expect(screen.getByRole("button", { name: "导出迁移包" })).toHaveClass("service-header-button");
  });

  it("loads local host storage usage on the space cleanup page and warns when free space is low", async () => {
    mockServicePageBootstrap();
    apiMock.scanSpaceCleanup.mockResolvedValue({
      ok: true,
      items: [],
      total_count: 0,
      total_size: 0,
      total_size_label: "0 B",
      message: "没有可清理文件"
    });

    render(<ServicePage addTask={vi.fn()} updateTask={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "空间清理" }));

    expect(await screen.findByText("本机空间使用量")).toBeInTheDocument();
    expect(apiMock.localStorageUsage).toHaveBeenCalled();
    expect(screen.getByText("已用 850 B / 总量 1000 B")).toBeInTheDocument();
    expect(screen.getAllByText("剩余 150 B").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByLabelText("本机空间使用率 85.0%")).toHaveClass("danger");
  });
});

describe("ServicePage upgrade center", () => {
  it("shows platform status and runtime verification in one section", async () => {
    mockServicePageBootstrap();
    apiMock.upgradeVerification.mockResolvedValue({
      app_version: "v0.5.0",
      runner_version: "v0.3.0",
      prometheus_version: "v2.55.1",
      compose_project: "smartx-capacity-insight",
      compose_file: "docker-compose.offline.yml",
      package: {
        task_id: "upgrade-ok",
        version: "v0.5.0",
        filename: "smartx-capacity-insight-upgrade-v0.5.0.tar.gz",
        sha256: "abcdef1234567890abcdef"
      },
      services: [
        {
          service: "web-api",
          container: "smartx-capacity-insight-web-api-1",
          status: "running",
          running: true,
          image: "nazawsze/smartx-hci-capacity-insight-web-api:v0.5.0",
          app_version: "v0.5.0",
          started_at: "2026-06-06T01:00:00+08:00"
        }
      ]
    });

    render(<ServicePage addTask={vi.fn()} updateTask={vi.fn()} />);

    expect(await screen.findByText("平台状态")).toBeInTheDocument();
    expect(screen.getByText("版本、升级包和当前运行服务集中展示。")).toBeInTheDocument();
    expect(screen.getByText("当前版本")).toBeInTheDocument();
    expect(screen.getByText("升级中心组件版本")).toBeInTheDocument();
    expect(screen.getByText("观测组件版本")).toBeInTheDocument();
    expect(screen.getAllByText("v0.5.0").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("最近成功包")).toBeInTheDocument();
    expect(screen.getByText(/smartx-capacity-insight-upgrade-v0\.5\.0/)).toBeInTheDocument();
    expect(screen.getByText("web-api")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.queryByText("服务运行核验")).not.toBeInTheDocument();
  });

  it("renders component upgrade as selectable runner and prometheus component cards", async () => {
    mockServicePageBootstrap();
    render(<ServicePage addTask={vi.fn()} updateTask={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "组件升级" }));

    expect(await screen.findByText("升级中心组件")).toBeInTheDocument();
    expect(screen.getByText("upgrade-runner")).toBeInTheDocument();
    expect(screen.getByText("观测组件")).toBeInTheDocument();
    expect(screen.getByText("prometheus")).toBeInTheDocument();
    expect(screen.getAllByText("v0.3.0").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("v2.55.1").length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole("button", { name: /观测组件.*prometheus/s }));

    expect(screen.getByText("组件名称")).toBeInTheDocument();
    expect(screen.getByText("观测组件 / prometheus")).toBeInTheDocument();
    expect(screen.getByText(/升级 Prometheus 观测组件/)).toBeInTheDocument();
  });

  it("shows precheck progress steps while platform precheck is running", async () => {
    mockServicePageBootstrap();
    apiMock.upgradeHistory.mockResolvedValue([uploadedPlatformTask()]);
    apiMock.precheckUpgrade.mockImplementation(
      () =>
        new Promise((resolve) => {
          window.setTimeout(() => resolve({ ...uploadedPlatformTask(), status: "prechecked", precheck_ok: true, checks: [{ name: "manifest", ok: true, message: "manifest 格式正确" }] }), 120);
        })
    );
    render(<ServicePage addTask={vi.fn()} updateTask={vi.fn()} />);

    fireEvent.click(await screen.findByText("v0.4.2"));
    fireEvent.click(screen.getByRole("button", { name: "预检查" }));

    expect(await screen.findByText("校验升级包结构")).toBeInTheDocument();
    expect(screen.getByText("检查 Docker 与升级执行器")).toBeInTheDocument();
    expect(screen.getByText("生成预检查结果")).toBeInTheDocument();
    expect(screen.getByText("执行中")).toBeInTheDocument();
    expect(screen.getAllByText("未执行").length).toBeGreaterThan(0);

    await waitFor(() => expect(apiMock.precheckUpgrade).toHaveBeenCalledWith("upgrade-1"));
  });

  it("uses the backend upgrade task id for the task center start task", async () => {
    mockServicePageBootstrap();
    apiMock.upgradeHistory.mockResolvedValue([{ ...uploadedPlatformTask(), status: "prechecked", precheck_ok: true }]);
    apiMock.startUpgrade.mockResolvedValue({ ...uploadedPlatformTask(), status: "pending", precheck_ok: true });
    const addTask = vi.fn();
    const updateTask = vi.fn();
    render(<ServicePage addTask={addTask} updateTask={updateTask} />);

    fireEvent.click(await screen.findByText("v0.4.2"));
    fireEvent.click(screen.getByRole("button", { name: "开始升级" }));

    await waitFor(() => expect(apiMock.startUpgrade).toHaveBeenCalledWith("upgrade-1"));
    expect(addTask).toHaveBeenCalledWith(expect.objectContaining({ id: "upgrade-1", kind: "upgrade", title: "执行系统升级" }));
    expect(updateTask).toHaveBeenCalledWith("upgrade-1", expect.objectContaining({ progress: expect.any(Number) }));
  });

  it("shows recovery controls and submits the selected recovery command", async () => {
    mockServicePageBootstrap();
    const recoveryTask = {
      ...uploadedPlatformTask(),
      status: "recovery_required",
      started_at: "2026-06-10T10:00:00Z",
      recovery_reason: "迁移脚本结果无法自动确认",
      available_recovery_actions: ["continue", "rollback", "fail"]
    };
    apiMock.upgradeHistory.mockResolvedValue([recoveryTask]);
    apiMock.continueUpgradeRecovery.mockResolvedValue({ ...recoveryTask, recovery_command: "continue" });
    render(<ServicePage addTask={vi.fn()} updateTask={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "升级历史" }));
    fireEvent.click(await screen.findByRole("button", { name: /平台升级.*v0\.4\.2/s }));

    expect(await screen.findByText("需要恢复处理")).toBeInTheDocument();
    expect(screen.getByText("迁移脚本结果无法自动确认")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "继续执行" }));
    await waitFor(() => expect(apiMock.continueUpgradeRecovery).toHaveBeenCalledWith("upgrade-1"));
  });
});
