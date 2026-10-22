// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { mergeCollapse, semanticPath, selectionUnit, collectSelectables, fullyInsideRect } from "./semantics";
import { applyOpsToDom } from "../editor/applyClient";
import type { Op } from "../types";

const FIXTURE = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 288 216">
  <g id="figure_1">
    <g id="axes_1">
      <g id="patch_1"><path id="p1" d="M 0 0 L 10 0 L 10 10 Z"/></g>
      <g id="patch_2"><path id="p2" d="M 0 0 L 10 0 L 10 10 Z" style="fill: #1f77b4"/></g>
      <g id="legend_1">
        <g id="patch_3"><path id="p3" d="M 1 1 L 2 2"/></g>
        <g id="text_1"><text>series-0</text></g>
        <g id="text_2"><text>series-1</text></g>
      </g>
    </g>
  </g>
</svg>`;

function dom(): Document {
  // happy-dom 对 image/svg+xml 支持不完整；HTML 解析器对 <svg> 内部保持外来内容规则
  return new DOMParser().parseFromString(FIXTURE, "text/html");
}

function svgRoot(): SVGSVGElement {
  return dom().querySelector("svg") as unknown as SVGSVGElement;
}

describe("semanticPath", () => {
  it("用 id 构造路径", () => {
    const doc = dom();
    const el = doc.querySelector("#p2")!;
    expect(semanticPath(el)).toBe("figure_1/axes_1/patch_2/p2");
  });

  it("无 id 元素带同 tag 序号", () => {
    const svg = svgRoot();
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const g2 = document.createElementNS("http://www.w3.org/2000/svg", "g");
    svg.appendChild(g);
    svg.appendChild(g2);
    // svg 层已有 figure_1 这个 <g>，所以新追加的是第 2、3 个 g
    expect(semanticPath(g)).toBe("g[2]");
    expect(semanticPath(g2)).toBe("g[3]");
  });
});

describe("selectionUnit", () => {
  it("原语向上归并到语义组", () => {
    const doc = dom();
    const path = doc.querySelector("#p1")!;
    expect(selectionUnit(path)!.id).toBe("patch_1");
  });

  it("语义元素取自身", () => {
    const doc = dom();
    const g = doc.querySelector("#legend_1")!;
    expect(selectionUnit(g)!.id).toBe("legend_1");
  });
});

describe("mergeCollapse", () => {
  it("框选整个图例：DS 会带 AABB 命中的祖先，收拢为 legend_1", () => {
    const doc = dom();
    const hits = [
      doc.querySelector("#patch_3")!,
      doc.querySelector("#text_1")!,
      doc.querySelector("#text_2")!,
      doc.querySelector("#legend_1")!, // AABB 命中
      doc.querySelector("#axes_1")!,
      doc.querySelector("#figure_1")!,
    ];
    const merged = mergeCollapse(hits);
    expect(merged).toHaveLength(1);
    expect(merged[0].id).toBe("legend_1");
  });

  it("部分选中时不收拢、剪掉祖先（拖框掠过一根柱子 → 只留 patch）", () => {
    const doc = dom();
    const hits = [
      doc.querySelector("#patch_2")!,
      doc.querySelector("#axes_1")!, // AABB 大框也会命中祖先
      doc.querySelector("#figure_1")!,
    ];
    const merged = mergeCollapse(hits);
    expect(merged).toHaveLength(1);
    expect(merged[0].id).toBe("patch_2");
  });
});

describe("collectSelectables", () => {
  it("返回全部语义元素", () => {
    const els = collectSelectables(svgRoot());
    expect(els.length).toBeGreaterThanOrEqual(8);
  });
});

describe("fullyInsideRect", () => {
  const RECT = { x0: 100, y0: 100, x1: 200, y1: 200 };

  function elWithBox(box: { left: number; right: number; top: number; bottom: number }): Element {
    const el = document.createElement("div");
    el.getBoundingClientRect = () =>
      ({
        left: box.left,
        right: box.right,
        top: box.top,
        bottom: box.bottom,
        x: box.left,
        y: box.top,
        width: box.right - box.left,
        height: box.bottom - box.top,
        toJSON: () => ({}),
      }) as DOMRect;
    return el;
  }

  it("完全在框内 → 选中", () => {
    expect(fullyInsideRect(elWithBox({ left: 110, right: 190, top: 120, bottom: 180 }), RECT)).toBe(true);
  });

  it("相交但任一边超出 → 不选", () => {
    expect(fullyInsideRect(elWithBox({ left: 90, right: 150, top: 120, bottom: 180 }), RECT)).toBe(false);
    expect(fullyInsideRect(elWithBox({ left: 110, right: 210, top: 120, bottom: 180 }), RECT)).toBe(false);
  });

  it("完全在框外 → 不选", () => {
    expect(fullyInsideRect(elWithBox({ left: 300, right: 350, top: 120, bottom: 180 }), RECT)).toBe(false);
  });

  it("贴边在容差（1px）内 → 选中", () => {
    expect(fullyInsideRect(elWithBox({ left: 99.5, right: 200.5, top: 100, bottom: 200 }), RECT)).toBe(true);
    // 超出容差则不行
    expect(fullyInsideRect(elWithBox({ left: 98, right: 200, top: 100, bottom: 200 }), RECT)).toBe(false);
  });
});

describe("applyOpsToDom", () => {
  it("set_style 命中声明处；set_text 改文本；transform 前置", () => {
    const svg = svgRoot();
    const doc = svg.ownerDocument!;
    const ops: Op[] = [
      {
        id: "op-1",
        kind: "set_style",
        target: { id: "patch_2", semanticPath: "", fingerprint: "" },
        attr: "fill",
        value: "#dd3322",
        intent: "改红",
        origin: "manual",
        status: "active",
      },
      {
        id: "op-2",
        kind: "set_text",
        target: { id: "text_1", semanticPath: "", fingerprint: "" },
        value: "对照",
        intent: "改文本",
        origin: "manual",
        status: "active",
      },
      {
        id: "op-3",
        kind: "transform",
        target: { id: "patch_1", semanticPath: "", fingerprint: "" },
        value: { translate: [5, -2] },
        intent: "平移",
        origin: "manual",
        status: "active",
      },
    ];
    applyOpsToDom(svg, ops);
    const p2 = doc.querySelector("#p2") as SVGElement;
    expect(p2.getAttribute("style")).toContain("#dd3322");
    expect(doc.querySelector("#text_1 text")!.textContent).toBe("对照");
    expect(doc.querySelector("#patch_1")!.getAttribute("transform")).toBe("translate(5 -2)");
  });

  it("字体族带空格时加引号", () => {
    const svg = svgRoot();
    const doc = svg.ownerDocument!;
    applyOpsToDom(svg, [
      {
        id: "op-1",
        kind: "set_style",
        target: { id: "text_1", semanticPath: "", fingerprint: "" },
        attr: "font-family",
        value: "DejaVu Sans",
        intent: "字体",
        origin: "manual",
        status: "active",
      },
    ]);
    const t = doc.querySelector("#text_1") as SVGElement;
    expect(t.getAttribute("style")).toContain("'DejaVu Sans'");
  });

  it("set_visible 隐藏/显示；reorder 移到末位", () => {
    const svg = svgRoot();
    const doc = svg.ownerDocument!;
    const visOp = (value: boolean): Op => ({
      id: "op-v",
      kind: "set_visible",
      target: { id: "legend_1", semanticPath: "", fingerprint: "" },
      value,
      intent: "显隐",
      origin: "manual",
      status: "active",
    });
    applyOpsToDom(svg, [visOp(false)]);
    const lg = doc.querySelector("#legend_1") as SVGElement;
    expect(lg.getAttribute("style")).toContain("display: none");
    applyOpsToDom(svg, [visOp(true)]);
    expect(lg.getAttribute("style") ?? "").not.toContain("display");

    const reorderOp: Op = {
      id: "op-r",
      kind: "reorder",
      target: { id: "patch_1", semanticPath: "", fingerprint: "" },
      value: { to: "front" },
      intent: "置顶",
      origin: "manual",
      status: "active",
    };
    const axes = doc.querySelector("#axes_1")!;
    const p1 = doc.querySelector("#patch_1")!;
    expect(axes.lastElementChild).not.toBe(p1);
    applyOpsToDom(svg, [reorderOp]);
    expect(axes.lastElementChild).toBe(p1);
  });
});
