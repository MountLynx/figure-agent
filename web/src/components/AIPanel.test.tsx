// @vitest-environment happy-dom
import { describe, expect, it, vi, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { AIPanel } from "./AIPanel";
import { api } from "../api";

vi.mock("../api", () => ({
  api: {
    aiStatus: () =>
      Promise.resolve({ configured: true, provider: "mock", model: "mock", mock: true }),
    instruct: vi.fn(),
    writebackPatch: vi.fn(),
  },
}));

describe("AIPanel", () => {
  let root: Root | null = null;
  let container: HTMLElement;

  const props = {
    current: { id: "abc123def456", name: "f1" },
    selections: [],
    patchOpCount: 2,
    runEvents: [{ runId: "r1", phase: "run_end" as const, node: "create", ok: true, at: 0 }],
    runActive: false,
    wsOnline: false,
    onRunStart: vi.fn(),
    onRunEnd: vi.fn(),
    onFigureChanged: vi.fn(),
    showToast: vi.fn(),
  };

  function render(over: Partial<Parameters<typeof AIPanel>[0]> = {}) {
    container = document.body.appendChild(document.createElement("div"));
    root = createRoot(container);
    act(() => root!.render(createElement(AIPanel, { ...props, ...over })));
  }

  afterEach(() => {
    root?.unmount();
    root = null;
  });

  it("渲染状态徽标，未输入指令时执行按钮禁用", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).toContain("mock");
    const buttons = [...container.querySelectorAll("button")];
    const exec = buttons.find((b) => b.textContent === "执行修改")!;
    expect(exec.disabled).toBe(true);
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

  it("请求失败（reject）后 onRunEnd 被调用，按钮不持续禁用", async () => {
    vi.mocked(api.writebackPatch).mockRejectedValueOnce(new Error("boom"));
    const onRunEnd = vi.fn();
    render({ onRunEnd });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    const wb = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("回写 patch")
    )!;
    expect(wb.disabled).toBe(false);
    await act(async () => {
      wb.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    // finally 里的 onRunEnd 是 runActive 锁的解锁契约：fetch settle 必须复位
    expect(onRunEnd).toHaveBeenCalledTimes(1);
    expect(wb.disabled).toBe(false);
  });
});
