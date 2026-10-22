// 客户端 patch 预览：把 ops 应用到注入的 SVG DOM 上（与服务端 apply_patch 同语义）。
// 手动微调的本地预览不经过服务器；保存后由服务端生成 final.svg 权威版本。

import type { Op } from "../types";

const STYLE_ATTRS = new Set(["fill", "stroke", "font-family", "font-size", "opacity"]);

function locate(root: SVGSVGElement, target: Op["target"]): Element | null {
  if (target.id) {
    const el = root.querySelector(`[id="${cssEscape(target.id)}"]`);
    if (el) return el;
  }
  if (target.semanticPath) {
    const el = walkSemanticPath(root, target.semanticPath);
    if (el) return el;
  }
  return null;
}

function cssEscape(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function walkSemanticPath(root: Element, path: string): Element | null {
  let cur: Element = root;
  for (const part of path.split("/")) {
    let next: Element | null = null;
    const kids = cur.children;
    for (let i = 0; i < kids.length; i++) {
      if (labelOf(kids[i]) === part) {
        next = kids[i];
        break;
      }
    }
    if (!next) return null;
    cur = next;
  }
  return cur;
}

function tagIndex(el: Element): number {
  let i = 0;
  let sib = el.previousElementSibling;
  while (sib) {
    if (sib.tagName === el.tagName) i++;
    sib = sib.previousElementSibling;
  }
  return i + 1;
}

function labelOf(el: Element): string {
  if (el.id) return el.id;
  const tag = el.tagName.toLowerCase();
  return `${tag}[${tagIndex(el)}]`;
}

function parseStyle(style: string): Map<string, string> {
  const props = new Map<string, string>();
  (style || "").split(";").forEach((part) => {
    const idx = part.indexOf(":");
    if (idx > 0) props.set(part.slice(0, idx).trim().toLowerCase(), part.slice(idx + 1).trim());
  });
  return props;
}

function serializeStyle(props: Map<string, string>): string {
  return [...props.entries()].map(([k, v]) => `${k}: ${v}`).join("; ");
}

function declares(el: Element, attr: string): boolean {
  const props = parseStyle((el as SVGElement).getAttribute("style") || "");
  if (props.has(attr)) return true;
  return el.getAttribute(attr) !== null;
}

function setStyleProp(el: Element, attr: string, value: string | null) {
  const svgEl = el as SVGElement;
  const props = parseStyle(svgEl.getAttribute("style") || "");
  if (value === null) props.delete(attr);
  else props.set(attr, value);
  if (props.size > 0) svgEl.setAttribute("style", serializeStyle(props));
  else svgEl.removeAttribute("style");
}

function quoteFontFamily(v: string): string {
  return v
    .split(",")
    .map((f) => {
      const t = f.trim().replace(/^['"]|['"]$/g, "");
      return t.includes(" ") && !t.startsWith("'") ? `'${t}'` : t;
    })
    .join(", ");
}

function firstTextEl(el: Element): Element | null {
  if (el.tagName.toLowerCase() === "text" || el.tagName.toLowerCase() === "tspan") return el;
  return el.querySelector("text, tspan");
}

function fmt(v: number): string {
  const s = v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return s === "" || s === "-0" ? "0" : s;
}

/** 把所有 active op 应用到 DOM（就地修改，调用方负责先重置为纯净 base）。 */
export function applyOpsToDom(root: SVGSVGElement, ops: Op[]): void {
  for (const op of ops) {
    if (op.status === "lost") continue;
    const el = locate(root, op.target);
    if (!el) continue;
    if (op.kind === "set_style" && op.attr && STYLE_ATTRS.has(op.attr)) {
      const attr: string = op.attr;
      const v = String(op.value ?? "").trim();
      const styled = attr === "font-family" ? quoteFontFamily(v) : v;
      const targets: Element[] = [];
      if (declares(el, attr)) targets.push(el);
      el.querySelectorAll("*").forEach((d) => {
        if (declares(d, attr)) targets.push(d);
      });
      if (targets.length > 0) targets.forEach((t) => setStyleProp(t, attr, styled));
      else setStyleProp(el, attr, styled);
    } else if (op.kind === "set_text") {
      const t = firstTextEl(el);
      if (t) {
        t.querySelectorAll("*").forEach((c) => c.remove());
        t.textContent = String(op.value ?? "");
      }
    } else if (op.kind === "set_visible") {
      if (op.value) setStyleProp(el, "display", null);
      else setStyleProp(el, "display", "none");
    } else if (op.kind === "reorder") {
      const parent = el.parentElement;
      const to = op.value?.to;
      if (parent && (to === "front" || to === "back")) {
        if (to === "front") parent.appendChild(el);
        else parent.insertBefore(el, parent.firstElementChild);
      }
    } else if (op.kind === "transform") {
      const pieces: string[] = [];
      const value = op.value ?? {};
      if (Array.isArray(value.translate)) {
        pieces.push(`translate(${fmt(value.translate[0])} ${fmt(value.translate[1])})`);
      }
      if (Array.isArray(value.scale)) {
        const [sx, sy = sx] = value.scale;
        const c = op.pre?.center ?? [0, 0];
        pieces.push(
          `translate(${fmt(c[0])} ${fmt(c[1])}) scale(${fmt(sx)} ${fmt(sy)}) translate(${fmt(-c[0])} ${fmt(-c[1])})`
        );
      }
      if (pieces.length > 0) {
        const existing = (el as SVGElement).getAttribute("transform");
        (el as SVGElement).setAttribute(
          "transform",
          [...pieces, ...(existing ? [existing] : [])].join(" ")
        );
      }
    }
  }
}
