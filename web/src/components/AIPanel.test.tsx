// @vitest-environment happy-dom
import { describe, expect, it, vi, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { AIPanel } from "./AIPanel";

vi.mock("../api", () => ({
  api: {
    aiStatus: () =>
      Promise.resolve({ configured: true, provider: "mock", model: "mock", mock: true }),
    createFigureAi: vi.fn(() => Promise.resolve({ kind: "create", ok: true, rounds: 1, stderr: "" })),
    adaptFigure: vi.fn(),
    instruct: vi.fn(),
    writebackPatch: vi.fn(),
    enrichSelection: vi.fn(),
  },
}));

describe("AIPanel", () => {
  let root: Root | null = null;
  let container: HTMLElement;

  const props = {
    projects: [{ name: "demo", figures: [] }],
    current: { project: "demo", figure: "f1" },
    selections: [],
    patchOpCount: 2,
    runEvents: [{ runId: "r1", phase: "run_end" as const, node: "create", ok: true, at: 0 }],
    runActive: false,
    onRunStart: vi.fn(),
    onFigureReady: vi.fn(),
    onFigureChanged: vi.fn(),
    showToast: vi.fn(),
  };

  function render() {
    container = document.body.appendChild(document.createElement("div"));
    root = createRoot(container);
    act(() => root!.render(createElement(AIPanel, props)));
  }

  afterEach(() => {
    root?.unmount();
    root = null;
  });

  it("渲染状态徽标与造图表单，未选文件时生成按钮禁用", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).toContain("mock");
    expect(container.textContent).toContain("AI 造图");
    const buttons = [...container.querySelectorAll("button")];
    const gen = buttons.find((b) => b.textContent === "生成图表")!;
    expect(gen.disabled).toBe(true);
  });

  it("显示运行时间线事件", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).toContain("run_end");
  });

  it("有 patch op 时回写按钮可用并显示数量", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    const wb = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("回写 patch")
    )!;
    expect(wb.disabled).toBe(false);
    expect(wb.textContent).toContain("2 op");
  });
});
