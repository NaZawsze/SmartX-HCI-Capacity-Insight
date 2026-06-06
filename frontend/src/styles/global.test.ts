import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync("src/styles/global.css", "utf8");

function blockFor(selector: string, source = css): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = source.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  return match?.[1] ?? "";
}

function blocksFor(selector: string, source = css): string[] {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return Array.from(source.matchAll(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, "g"))).map((match) => match[1]);
}

function mediaBlock(query: string): string {
  return mediaBlocks(query)[0] ?? "";
}

function mediaBlocks(query: string): string[] {
  const blocks: string[] = [];
  const start = css.indexOf(`@media ${query}`);
  if (start < 0) return blocks;
  let searchStart = start;
  while (searchStart >= 0) {
    let depth = 0;
    for (let index = searchStart; index < css.length; index += 1) {
      const char = css[index];
      if (char === "{") depth += 1;
      if (char === "}") {
        depth -= 1;
        if (depth === 0) {
          blocks.push(css.slice(searchStart, index + 1));
          searchStart = css.indexOf(`@media ${query}`, index + 1);
          break;
        }
      }
    }
    if (depth !== 0) break;
  }
  return blocks;
}

describe("global responsive styles", () => {
  it("keeps desktop dashboard metrics in one constrained row", () => {
    const dashboardMetrics = blockFor(".dashboard-metrics-row");

    expect(dashboardMetrics).toContain("grid-template-columns");
    expect(dashboardMetrics).toContain("0.20");
    expect(dashboardMetrics).toContain("0.40");
  });

  it("switches dense pages to single-column mobile layout", () => {
    const mobile = mediaBlock("(max-width: 960px)");

    expect(mobile).toContain(".dashboard-grid");
    expect(mobile).toContain(".metrics-row");
    expect(mobile).toContain("grid-template-columns: 1fr");
    expect(mobile).toContain(".workspace");
    expect(mobile).toContain("overflow: visible");
  });

  it("lets service navigation wrap and reduces service page padding on mobile", () => {
    const tablet = mediaBlocks("(max-width: 960px)").join("\n");
    const phone = mediaBlocks("(max-width: 760px)").join("\n");

    const serviceSubnav = blocksFor(".service-subnav", tablet).find((block) => block.includes("flex-direction: row")) ?? "";
    expect(serviceSubnav).toContain("flex-direction: row");
    expect(serviceSubnav).toContain("flex-wrap: wrap");

    const serviceMain = blockFor(".shell.service-focus .main", phone);
    expect(serviceMain).toContain("padding-left: 16px");
    expect(serviceMain).toContain("padding-right: 16px");
  });
});
