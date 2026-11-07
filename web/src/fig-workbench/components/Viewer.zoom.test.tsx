// @vitest-environment happy-dom
// 回归测试：画布缩放/平移/视图重置。
// 症状：Ctrl+滚轮时灵时不灵（vb 初始 null 时全部 no-op）；换图后旧 viewBox 套在新图上只显示一角；
// SVG 固有尺寸不填满 viewer，缩放平移被裁剪在小区域里。
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { Viewer } from "./Viewer"
import type { Op, SelectionJSON } from "../../shared/types";

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
  <g id="figure_1"><g id="axes_1"><g id="patch_3"><path id="p3" d="M 0 0 L 10 10"/></g></g></g>
</svg>`;
// 换图：不同 viewBox（模拟另一张尺寸不同的图）
const SVG_B = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 90">
  <g id="figure_1"><g id="axes_1"><g id="patch_3"><path id="p3" d="M 0 0 L 12 9"/></g></g></g>
</svg>`;

// happy-dom 无布局：给 svg 一个 200×160 的假视口（viewBox 100×80 → scale=2）
const RECT = {
  x: 0, y: 0, left: 0, top: 0, right: 200, bottom: 160,
  width: 200, height: 160, toJSON() {},
} as DOMRect;

function makeProps(over: Partial<Parameters<typeof Viewer>[0]> = {}): Parameters<typeof Viewer>[0] {
  return {
    baseSvg: SVG_A,
    ops: [] as Op[],
    showBase: false,
    preciseMode: false,
    selectionPaths: [],
    onSelection: (jsons: SelectionJSON[]) => {},
    onClearSelection: () => {},
    version: 0,
    ...over,
  };
}

function parseVB(attr: string | null): number[] | null {
  if (!attr) return null;
  return attr.split(/[\s,]+/).map(Number);
}

function fireWheel(el: Element, deltaY: number, deltaMode = 0, clientX = 100, clientY = 80) {
  // happy-dom 的 WheelEvent 不支持 clientX 初始化，用 MouseEvent + defineProperty 保证字段齐全
  const m = new MouseEvent("wheel", { cancelable: true, bubbles: true, clientX, clientY });
  Object.defineProperty(m, "deltaY", { value: deltaY });
  Object.defineProperty(m, "deltaMode", { value: deltaMode });
  el.dispatchEvent(m);
}

describe("Viewer 缩放/平移/视图重置", () => {
  let host: HTMLDivElement;
  let root: Root | null = null;

  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
  });

  afterEach(() => {
    if (root) act(() => root!.unmount());
    root = null;
    host.remove();
  });

  async function mount(over: Partial<Parameters<typeof Viewer>[0]> = {}) {
    root = createRoot(host);
    await act(async () => {
      root!.render(createElement(Viewer, makeProps(over)));
    });
    const svg = host.querySelector("svg") as SVGSVGElement;
    svg.getBoundingClientRect = () => RECT;
    return svg;
  }

  it("挂载后未点过『适应』，Ctrl+滚轮即可缩放（vb 自动初始化）", async () => {
    const svg = await mount();
    const wrap = host.querySelector(".fig-viewer-wrap") as HTMLElement;

    await act(async () => {
      fireWheel(wrap, -120); // 向上滚 = 放大
    });

    const vb = parseVB(svg.getAttribute("viewBox"))!;
    expect(vb).not.toBeNull();
    const [x, y, w, h] = vb;
    expect(Number.isFinite(x) && Number.isFinite(y)).toBe(true);
    expect(w).toBeGreaterThan(80);
    expect(w).toBeLessThan(90); // 100 / exp(120*0.0015) ≈ 83.5
    expect(h).toBeCloseTo(w * 0.8, 5); // 等比
    // 光标(100,80)在视口中心 → 中心不动
    expect(x + w / 2).toBeCloseTo(50, 5);
    expect(y + h / 2).toBeCloseTo(40, 5);
  });

  it("中键按下拖动即可平移", async () => {
    const svg = await mount();
    const wrap = host.querySelector(".fig-viewer-wrap") as HTMLElement;

    await act(async () => {
      wrap.dispatchEvent(new MouseEvent("pointerdown", { button: 1, clientX: 100, clientY: 80, bubbles: true }));
    });
    await act(async () => {
      wrap.dispatchEvent(new MouseEvent("pointermove", { clientX: 150, clientY: 140, bubbles: true }));
    });
    await act(async () => {
      wrap.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    });

    const vb = parseVB(svg.getAttribute("viewBox"))!;
    // 50px/60px ÷ scale 2 → 25/30 用户单位
    expect(vb[0]).toBeCloseTo(-25, 5);
    expect(vb[1]).toBeCloseTo(-30, 5);
    expect(vb[2]).toBeCloseTo(100, 5);
    expect(vb[3]).toBeCloseTo(80, 5);
  });

  it("换图（baseSvg/version 变化）后视图重置为新图的 fit，不套用旧图 viewBox", async () => {
    const svgA = await mount();
    const wrap = host.querySelector(".fig-viewer-wrap") as HTMLElement;
    await act(async () => {
      fireWheel(wrap, -120);
    });
    const zoomed = parseVB(svgA.getAttribute("viewBox"))!;
    expect(zoomed[2]).toBeLessThan(100); // 确认已缩放

    await act(async () => {
      root!.render(createElement(Viewer, makeProps({ baseSvg: SVG_B, version: 1 })));
    });
    const svgB = host.querySelector("svg") as SVGSVGElement;
    expect(svgB.getAttribute("viewBox")).toBe("0 0 120 90");
  });

  it("仅 ops/showBase 变化（重新注入）时保留用户当前视图", async () => {
    const svg = await mount();
    const wrap = host.querySelector(".fig-viewer-wrap") as HTMLElement;
    await act(async () => {
      fireWheel(wrap, -120);
    });
    const zoomed = svg.getAttribute("viewBox")!;
    expect(parseVB(zoomed)![2]).toBeLessThan(100);

    await act(async () => {
      root!.render(createElement(Viewer, makeProps({ showBase: true })));
    });
    const svg2 = host.querySelector("svg") as SVGSVGElement;
    expect(svg2.getAttribute("viewBox")).toBe(zoomed);
  });
});
