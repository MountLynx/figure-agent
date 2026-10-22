// @vitest-environment happy-dom
// 悬停高亮：与单击同一语义归并（selectionUnit），虚线框预览选区单位。
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { Viewer } from "./Viewer";
import type { Op, SelectionJSON } from "../types";

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

vi.stubGlobal("requestAnimationFrame", () => 0);
vi.stubGlobal("cancelAnimationFrame", () => {});

const SVG_A = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80">
  <g id="figure_1"><g id="axes_1"><g id="patch_3"><path id="p3" d="M 0 0 L 10 10"/></g></g><g id="axes_2"><g id="patch_4"><path id="p4" d="M 20 0 L 30 10"/></g></g></g>
</svg>`;

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

function firePointerMove(el: Element) {
  el.dispatchEvent(new MouseEvent("pointermove", { bubbles: true }));
}

describe("Viewer 悬停高亮", () => {
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

  it("悬停无语义 id 的原语 → 归并到语义祖先，虚线框显示其名称", async () => {
    root = createRoot(host);
    await act(async () => {
      root!.render(createElement(Viewer, makeProps()));
    });
    const wrap = host.querySelector(".viewer-wrap") as HTMLElement;
    const p3 = host.querySelector("#p3") as Element;

    await act(async () => {
      firePointerMove(p3);
    });
    const boxes = host.querySelectorAll(".overlay-box.hover-box");
    expect(boxes.length).toBe(1);
    expect(boxes[0].textContent).toBe("patch_3");

    await act(async () => {
      wrap.dispatchEvent(new MouseEvent("pointerleave"));
    });
    expect(host.querySelectorAll(".overlay-box.hover-box").length).toBe(0);
  });

  it("悬停已选中的元素不叠加虚线框；移到别的元素恢复", async () => {
    root = createRoot(host);
    await act(async () => {
      root!.render(
        createElement(Viewer, makeProps({ selectionPaths: ["figure_1/axes_1/patch_3"] }))
      );
    });
    const p3 = host.querySelector("#p3") as Element;
    const p4 = host.querySelector("#p4") as Element;

    await act(async () => {
      firePointerMove(p3);
    });
    expect(host.querySelectorAll(".overlay-box.hover-box").length).toBe(0);
    // 选中实线框仍在
    expect(host.querySelectorAll(".overlay-box:not(.hover-box)").length).toBe(1);

    await act(async () => {
      firePointerMove(p4);
    });
    const boxes = host.querySelectorAll(".overlay-box.hover-box");
    expect(boxes.length).toBe(1);
    expect(boxes[0].textContent).toBe("patch_4");
  });

  it("悬停 svg 根/背景（无语义单位）不出现虚线框", async () => {
    root = createRoot(host);
    await act(async () => {
      root!.render(createElement(Viewer, makeProps()));
    });
    const svg = host.querySelector("svg") as SVGSVGElement;

    await act(async () => {
      firePointerMove(svg);
    });
    expect(host.querySelectorAll(".overlay-box.hover-box").length).toBe(0);
  });
});
