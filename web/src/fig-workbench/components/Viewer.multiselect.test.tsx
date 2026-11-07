// @vitest-environment happy-dom
// 多选回归：Shift+点击多选时，onSelection 必须携带每个元素各自的选区 JSON
// （而不是只给第一个元素、其余靠克隆第一条伪造）。
import { describe, expect, it, vi, beforeEach, afterEach, beforeAll } from "vitest";
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

// happy-dom 没有 SVG 几何 API，桩成固定值（CTM 单位阵 → buildJson 走恒等变换）
beforeAll(() => {
  const protos: any[] = [SVGSVGElement.prototype, SVGGElement.prototype, SVGPathElement.prototype];
  for (const p of protos) {
    p.getBBox ??= () => ({ x: 0, y: 0, width: 10, height: 10 });
    p.getCTM ??= () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0, inverse: () => IDENTITY, multiply: () => IDENTITY });
    p.getScreenCTM ??= () => null;
  }
  (DOMPoint.prototype as any).matrixTransform ??= function (m: any) {
    const { a = 1, b = 0, c = 0, d = 1, e = 0, f = 0 } = m ?? {};
    const { x, y } = this;
    return new DOMPoint(a * x + c * y + e, b * x + d * y + f);
  };
});

const IDENTITY: any = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0, inverse: () => IDENTITY, multiply: () => IDENTITY };

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
    onSelection: (jsons: SelectionJSON[]) => {},
    onClearSelection: () => {},
    version: 0,
    ...over,
  };
}

function click(el: Element, additive: boolean) {
  // 与 SelectionLayer 的判定一致：additive 在 pointerdown 读取；坐标相同 → 未移动 → 单击路径
  const init: any = { bubbles: true, button: 0, clientX: 5, clientY: 5, shiftKey: additive, ctrlKey: additive };
  el.dispatchEvent(new MouseEvent("pointerdown", init));
  el.dispatchEvent(new MouseEvent("pointerup", init));
}

describe("Viewer 多选选区 JSON", () => {
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

  it("Shift+点击两个元素 → onSelection 收到 2 条各自独立的选区 JSON", async () => {
    root = createRoot(host);
    let received: SelectionJSON[][] = [];
    const props = makeProps({
      onSelection: (jsons: SelectionJSON[]) => {
        received.push(jsons);
      },
    });

    await act(async () => {
      root!.render(createElement(Viewer, props));
    });
    const p3 = host.querySelector("#p3") as Element;
    const p4 = host.querySelector("#p4") as Element;

    // 第一次 Shift+点击：选中 patch_3
    await act(async () => {
      click(p3, true);
    });
    expect(received.length).toBe(1);
    expect(received[0].length).toBe(1);
    expect(received[0][0].elementId).toBe("patch_3");

    // 模拟 App 回传 selectionPaths 后再 Shift+点击 patch_4
    received = [];
    await act(async () => {
      root!.render(
        createElement(
          Viewer,
          makeProps({
            selectionPaths: ["figure_1/axes_1/patch_3"],
            onSelection: (jsons: SelectionJSON[]) => {
              received.push(jsons);
            },
          })
        )
      );
    });
    await act(async () => {
      click(p4, true);
    });

    expect(received.length).toBe(1);
    expect(received[0].length).toBe(2);
    expect(received[0].map((j) => j.elementId)).toEqual(["patch_3", "patch_4"]);
    expect(received[0][0].semanticPath).toBe("figure_1/axes_1/patch_3");
    expect(received[0][1].semanticPath).toBe("figure_1/axes_2/patch_4");
    // 每条 JSON 必须独立描述自己的元素，而不是第一条的克隆
    expect(received[0][0]).not.toEqual(received[0][1]);
  });
});
