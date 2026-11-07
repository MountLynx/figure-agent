// 选区 JSON 构造（§8 定位 JSON）：基于真实 DOM（getBBox + CTM）。
// fingerprint 由服务端富化，前端不重复实现。

import { semanticPath } from "./semantics";
import type { SelectionJSON } from "./types";

export interface UserBBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** 元素在 SVG 根用户坐标系（viewBox 坐标系）中的 bbox。 */
export function userSpaceBBox(el: Element, svgRoot: SVGSVGElement): UserBBox {
  const bb = (el as SVGGraphicsElement).getBBox();
  // el.getCTM(): el 本地 → 屏幕；svgRoot.getCTM(): 根用户空间 → 屏幕
  const toScreen = (el as SVGGraphicsElement).getCTM();
  const rootToScreen = svgRoot.getCTM();
  if (!toScreen || !rootToScreen) {
    return { x: bb.x, y: bb.y, w: bb.width, h: bb.height };
  }
  const rootInv = rootToScreen.inverse();
  const m = rootInv.multiply(toScreen); // el 本地 → 根用户空间
  const pts: DOMPoint[] = [
    new DOMPoint(bb.x, bb.y).matrixTransform(m),
    new DOMPoint(bb.x + bb.width, bb.y).matrixTransform(m),
    new DOMPoint(bb.x, bb.y + bb.height).matrixTransform(m),
    new DOMPoint(bb.x + bb.width, bb.y + bb.height).matrixTransform(m),
  ];
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}

/** 子树内第一个显式声明某表现属性的元素的值；否则用解析后的计算值。 */
function declaredStyle(el: Element, prop: string): string | null {
  if (el instanceof HTMLElement || el instanceof SVGElement) {
    const inline = (el as SVGElement).style?.getPropertyValue(prop);
    if (inline) return inline;
  }
  const all = el.querySelectorAll("*");
  for (const d of all) {
    const inline = (d as SVGElement).style?.getPropertyValue(prop);
    if (inline) return inline;
    const attrVal = d.getAttribute(prop);
    if (attrVal) return attrVal;
  }
  const cs = getComputedStyle(el as Element);
  const v = cs.getPropertyValue(prop);
  return v || null;
}

function textInfo(el: Element): SelectionJSON["text"] {
  const texts: string[] = [];
  el.querySelectorAll("text, tspan").forEach((t) => {
    const s = t.textContent?.trim();
    if (s) texts.push(s);
  });
  if (texts.length === 0 && (el.tagName.toLowerCase() === "text" || el.tagName.toLowerCase() === "tspan")) {
    const s = el.textContent?.trim();
    if (s) texts.push(s);
  }
  if (texts.length === 0) return { content: null, fontFamily: null, fontSize: null };
  const first = el.querySelector("text, tspan") ?? el;
  const cs = getComputedStyle(first);
  return {
    content: texts.join(" / "),
    fontFamily: cs.fontFamily || null,
    fontSize: cs.fontSize || null,
  };
}

export function buildSelectionJson(
  semanticEl: Element,
  svgRoot: SVGSVGElement,
  nearby: string[] = []
): SelectionJSON {
  const bb = userSpaceBBox(semanticEl, svgRoot);
  return {
    elementId: semanticEl.id || null,
    semanticPath: semanticPath(semanticEl),
    userSpaceBBox: {
      x: Math.round(bb.x * 100) / 100,
      y: Math.round(bb.y * 100) / 100,
      w: Math.round(bb.w * 100) / 100,
      h: Math.round(bb.h * 100) / 100,
    },
    style: {
      fill: declaredStyle(semanticEl, "fill"),
      stroke: declaredStyle(semanticEl, "stroke"),
    },
    text: textInfo(semanticEl),
    nearby,
  };
}
