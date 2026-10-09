import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

/**
 * 2026-10-09「请求超时」误报回归：
 * 采集是同步长请求（实测 .3 约 80s、.12 约 111s），不能被全局 30s 超时误杀；
 * 采集专用 240s 超时（< nginx proxy_read_timeout 300s），超时文案须诚实说明后台可能仍在执行。
 */
function neverResolvingFetch(): ReturnType<typeof vi.fn> {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      })
  );
}

describe("api request timeouts", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps the 30s default timeout for regular requests", async () => {
    vi.stubGlobal("fetch", neverResolvingFetch());

    const promise = api.summary({ type: "all" });
    const assertion = expect(promise).rejects.toThrow("请求超时");
    await vi.advanceTimersByTimeAsync(30_000);
    await assertion;
  });

  it("does not abort collection at the 30s default timeout, and reports honestly at 240s", async () => {
    vi.stubGlobal("fetch", neverResolvingFetch());

    let error: Error | null = null;
    const promise = api.runCollection("task-1").catch((exc) => {
      error = exc as Error;
    });
    await vi.advanceTimersByTimeAsync(35_000);
    expect(error).toBeNull(); // 35s 时采集请求仍在等待，未被误杀

    await vi.advanceTimersByTimeAsync(240_000);
    await promise;
    expect(error?.message).toContain("采集执行超过 4 分钟未返回");
    expect(error?.message).toContain("后台可能仍在执行");
  });
});
