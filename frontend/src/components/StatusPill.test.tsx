import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("maps the collection-side partial_failed status to 部分失败", () => {
    // `.14` 实测：后端"部分失败"取值是 partial_failed，前端曾只认 partial → 显示"未知"。
    render(<StatusPill status="partial_failed" />);
    expect(screen.getByText("部分失败")).toBeInTheDocument();
  });

  it("keeps partial / success / failed / running labels", () => {
    const cases: Array<[string, string]> = [
      ["partial", "部分失败"],
      ["success", "正常"],
      ["failed", "失败"],
      ["running", "采集中"],
    ];
    for (const [status, label] of cases) {
      const { unmount } = render(<StatusPill status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("falls back to 未知 only for genuinely unknown statuses", () => {
    render(<StatusPill status="something-else" />);
    expect(screen.getByText("未知")).toBeInTheDocument();
  });
});
