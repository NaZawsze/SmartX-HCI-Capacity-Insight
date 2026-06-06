import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";

Object.defineProperty(window, "scrollTo", {
  value: vi.fn(),
  writable: true
});

afterEach(() => {
  cleanup();
});
