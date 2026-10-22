// @vitest-environment happy-dom
// 回归测试：SVG 注入容器绝不能与 React 管理的兄弟节点混在同一个 innerHTML 容器里。
// 症状：点选元素 → React commit insertBefore NotFoundError。
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { Viewer } from "./Viewer";
import type { Op, SelectionJSON } from "../types";

// DragSelect 在 happy-dom 里不可用，桩掉（本测试关注 React DOM 所有权，不关注 DS）
vi.mock("dragselect", () => {
  class FakeDragSelect {
    opts: unknown;
    constructor(opts: unknown) {
      this.opts = opts;
    }
    subscribe() {
      return 1;
    }
    clearSelection() {}
    setSettings() {}
    stop() {}
  }
  return { default: FakeDragSelect };
});

// overlay 的 rAF 跟踪循环在测试里关掉
vi.stubGlobal("requestAnimationFrame", () => 0);
vi.stubGlobal("cancelAnimationFrame", () => {});

const SVG_A = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80">
  <g id="figure_1"><g id="axes_1"><g id="patch_3"><path id="p3" d="M 0 0 L 10 10"/></g></g></g>
</svg>`;
const SVG_B = SVG_A.replace('d="M 0 0 L 10 10"', 'd="M 0 0 L 12 9"');

function makeProps(over: Partial<Parameters<typeof Viewer>[0]> = {}): Parameters<typeof Viewer>[0] {
  return {
    baseSvg: SVG_A,
    ops: [] as Op[],
    showBase: false,
    preciseMode: false,
    selectionPaths: [],
    onSelection: (els: Element[], primary: SelectionJSON) => {},
    onClearSelection: () => {},
    version: 0,
    ...over,
  };
}

describe("Viewer DOM 所有权回归", () => {
  let host: HTMLDivElement;
  let root: Root | null = null;

  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
  });

  afterEach(() => {
    root?.unmount();
    host.remove();
  });

  it("注入 SVG 后再改变选区/重新注入，React commit 不抛 insertBefore 错误", async () => {
    root = createRoot(host);
    const props = makeProps();

    // 1) 初始渲染（注入 SVG）
    await act(async () => {
      root!.render(createElement(Viewer, props));
    });
    const wrap = host.querySelector(".viewer-wrap") as HTMLElement;
    expect(wrap).toBeTruthy();

    // 2) 模拟点选：selectionPaths 变化 → 插入 overlay box（旧实现在这里崩）
    await act(async () => {
      root!.render(createElement(Viewer, makeProps({ selectionPaths: ["figure_1/axes_1/patch_3"] })));
    });
    expect(host.querySelectorAll(".overlay-box").length).toBe(1);
    // SVG 必须住在注入容器里，而不是和 overlay 混在同一层
    const svg = wrap.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg!.parentElement).not.toBe(wrap); // 有自己的注入容器
    expect(svg!.parentElement!.parentElement).toBe(wrap);

    // 3) 模拟改代码重渲染：baseSvg 变化 → 重新 innerHTML 注入（旧实现在这里擦掉 overlay）
    await act(async () => {
      root!.render(createElement(Viewer, makeProps({ baseSvg: SVG_B, selectionPaths: ["figure_1/axes_1/patch_3"] })));
    });

    // 4) 选区清空 → React 要卸载 overlay（旧实现在这里对已消失的节点 removeChild 崩）
    await act(async () => {
      root!.render(createElement(Viewer, makeProps({ baseSvg: SVG_B })));
    });
    expect(host.querySelectorAll(".overlay-box").length).toBe(0);

    // 5) 再来一轮选中/取消，确保状态机稳定
    await act(async () => {
      root!.render(createElement(Viewer, makeProps({ baseSvg: SVG_B, selectionPaths: ["figure_1/axes_1/patch_3"] })));
    });
    expect(host.querySelectorAll(".overlay-box").length).toBe(1);
  });
});
