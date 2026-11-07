// @vitest-environment happy-dom
// AI 面板测试（自 itemmanage figurePlugins/fig-ai 的 ctx 版适配：条目状态 → 应用 props）。
// 桩掉 api 与 WebSocket，断言同语义行为：有图才可用、回写计数、WS 时间线、运行锁复位。
import { describe, expect, it, vi, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { AIPanel, type AIPanelProps } from "./AIPanel";
import { api } from "../shared/api";

vi.mock("../shared/api", () => ({
  api: {
    aiStatus: vi.fn(() =>
      Promise.resolve({ configured: true, provider: "mock", model: "mock", mock: true })
    ),
    getFigure: vi.fn(),
    instruct: vi.fn(),
    writebackPatch: vi.fn(),
    listTemplates: vi.fn(),
  },
}));

class FakeWS {
  static instances: FakeWS[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(_url: string) {
    FakeWS.instances.push(this);
  }
  close() {}
  send() {}
}
vi.stubGlobal("WebSocket", FakeWS);

const FIGURE_WITH_OPS = {
  hasFigure: true,
  id: "figure",
  name: "demo",
  properties: {},
  code: "x = 1",
  baseSvg: "<svg/>",
  finalSvg: "<svg/>",
  patch: { baseHash: "h", ops: [{ id: "op-1" }, { id: "op-2" }] },
  snapshots: [],
};

const BASE_PROPS: AIPanelProps = {
  itemId: "figure",
  dir: "/tmp/demo",
  hasFigure: true,
};

describe("AI 面板", () => {
  let root: Root | null = null;
  let container: HTMLElement;

  function render(over: Partial<AIPanelProps> = {}) {
    container = document.body.appendChild(document.createElement("div"));
    root = createRoot(container);
    act(() => root!.render(createElement(AIPanel, { ...BASE_PROPS, ...over })));
  }

  function openWs() {
    const ws = FakeWS.instances.at(-1)!;
    act(() => ws.onopen?.());
    return ws;
  }

  afterEach(() => {
    if (root) act(() => root!.unmount());
    root = null;
    vi.clearAllMocks();
    FakeWS.instances = [];
    vi.mocked(api.aiStatus).mockImplementation(() =>
      Promise.resolve({ configured: true, provider: "mock", model: "mock", mock: true })
    );
  });

  it("渲染状态徽标；有图且有 op 时回写按钮可用并显示数量", async () => {
    vi.mocked(api.getFigure).mockResolvedValue(FIGURE_WITH_OPS as any);
    render();
    openWs();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    await act(() => new Promise((r) => setTimeout(r, 0)));

    expect(container.textContent).toContain("mock");
    const wb = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("回写 patch")
    )!;
    expect(wb.disabled).toBe(false);
    expect(wb.textContent).toContain("2 op");
    // 执行修改：指令为空时禁用
    const exec = [...container.querySelectorAll("button")].find(
      (b) => b.textContent === "执行修改"
    )!;
    expect(exec.disabled).toBe(true);
  });

  it("应用状态说无图时显示引导文案，不渲染操作按钮，也不查 op 数", async () => {
    render({ hasFigure: false });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).toContain("还没有图表");
    expect([...container.querySelectorAll("button")].length).toBe(0);
    expect(api.getFigure).not.toHaveBeenCalled();
  });

  it("应用状态未定时显示检测文案（不误判为无图）", async () => {
    render({ hasFigure: null });
    expect(container.textContent).toContain("正在检测");
    expect([...container.querySelectorAll("button")].length).toBe(0);
    // 让挂载时的 aiStatus 请求在 act 内落地（否则测试结束后 setStatus 会告警）
    await act(() => new Promise((r) => setTimeout(r, 0)));
  });

  it("WS figure_updated 让面板重新探测图状态并回写应用状态", async () => {
    vi.mocked(api.getFigure).mockResolvedValue(FIGURE_WITH_OPS as any);
    const onHasFigure = vi.fn();
    render({ hasFigure: false, onHasFigure });
    const ws = openWs();
    expect(container.textContent).toContain("还没有图表");
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "figure_updated", dir: "/tmp/demo" }),
      });
    });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(onHasFigure).toHaveBeenCalledWith(true);
  });

  it("WS ai_run 事件（dir 匹配）进入运行时间线", async () => {
    vi.mocked(api.getFigure).mockResolvedValue(FIGURE_WITH_OPS as any);
    render();
    const ws = openWs();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({
          type: "ai_run",
          dir: "/tmp/demo",
          runId: "r1",
          phase: "run_end",
          node: "create",
          ok: true,
        }),
      });
    });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).toContain("run_end");
  });

  it("其它目录的 ai_run 事件被丢弃", async () => {
    vi.mocked(api.getFigure).mockResolvedValue(FIGURE_WITH_OPS as any);
    render();
    const ws = openWs();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({
          type: "ai_run",
          dir: "/tmp/other",
          runId: "r2",
          phase: "run_end",
          node: "create",
        }),
      });
    });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).not.toContain("run_end");
  });

  it("回写请求 reject 后按钮不持续禁用（fetch settle 复位运行锁）", async () => {
    vi.mocked(api.getFigure).mockResolvedValue(FIGURE_WITH_OPS as any);
    vi.mocked(api.writebackPatch).mockRejectedValueOnce(new Error("boom"));
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    const wb = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("回写 patch")
    )!;
    expect(wb.disabled).toBe(false);
    await act(async () => {
      wb.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    // finally 复位 runActive/busy：按钮不得锁死
    expect(wb.disabled).toBe(false);
    expect(container.textContent).toContain("回写失败");
    // 刷新图状态的 promise 也在 act 内落地
    await act(() => new Promise((r) => setTimeout(r, 0)));
  });
});
