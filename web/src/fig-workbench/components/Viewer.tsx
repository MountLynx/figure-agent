// Viewer：SVG 注入 + viewBox 平移缩放 + 选中 overlay + SelectionLayer 编排
// （自 figure-agent Viewer.tsx 移植；React 直接 import，类名 fig- 前缀）

import * as React from "react";
import type { Op, SelectionJSON } from "../../shared/types";
import { applyOpsToDom } from "../../shared/applyClient";
import {
  isSemantic,
  mergeCollapse,
  nearestSemanticAncestor,
  selectionUnit,
  semanticPath,
} from "../../shared/semantics";
import { buildSelectionJson } from "../../shared/buildJson";
import { SelectionLayer } from "./SelectionLayer";

export interface ViewerProps {
  baseSvg: string | null;
  ops: Op[];
  showBase: boolean;
  preciseMode: boolean;
  selectionPaths: string[];
  /** 每个选中元素一条选区 JSON（多选时每条独立描述自己的 bbox/style/text） */
  onSelection: (jsons: SelectionJSON[]) => void;
  onClearSelection: () => void;
  version: number; // 图切换代数
  /** SVG DOM 重建/ops 应用后上报语义元素树（文档顺序，含隐藏态） */
  onElements?: (elements: ElementNode[]) => void;
  /** 元素面板点击行 → 定位并选中该元素 */
  selectRequest?: { path: string; nonce: number } | null;
}

export interface ElementNode {
  id: string;
  path: string; // semanticPath
  label: string;
  hidden: boolean;
  children: ElementNode[];
}

function isHiddenEl(el: Element): boolean {
  const st = (el as SVGElement).style;
  return st?.display === "none" || el.getAttribute("display") === "none";
}

/** 语义元素树：文档顺序，parent = 最近语义祖先。 */
export function buildElementTree(svg: SVGSVGElement): ElementNode[] {
  const nodes = new Map<string, ElementNode>();
  const parentOf = new Map<string, string | null>();
  svg.querySelectorAll("*").forEach((el) => {
    if (!isSemantic(el)) return;
    const path = semanticPath(el);
    const anc = nearestSemanticAncestor(el); // 从 el.parent 起向上找（el 自身是语义元素）
    nodes.set(path, {
      id: el.id,
      path,
      label: (el.id || "").replace(/^fa:/, "") || path.split("/").pop() || "元素",
      hidden: isHiddenEl(el),
      children: [],
    });
    parentOf.set(path, anc ? semanticPath(anc) : null);
  });
  const roots: ElementNode[] = [];
  parentOf.forEach((parent, path) => {
    const node = nodes.get(path)!;
    if (parent && nodes.has(parent)) nodes.get(parent)!.children.push(node);
    else roots.push(node);
  });
  return roots;
}

interface VB {
  x: number;
  y: number;
  w: number;
  h: number;
}

function parseVB(attr: string | null): VB | null {
  if (!attr) return null;
  const [x, y, w, h] = attr.split(/[\s,]+/).map(Number);
  if ([x, y, w, h].some((v) => !Number.isFinite(v))) return null;
  return { x, y, w, h };
}

export function Viewer(props: ViewerProps) {
  const { baseSvg, ops, showBase, preciseMode, selectionPaths, onSelection, onClearSelection, version, onElements, selectRequest } = props;
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const injectRef = React.useRef<HTMLDivElement>(null);
  const svgRef = React.useRef<SVGSVGElement | null>(null);
  const naturalVb = React.useRef<VB | null>(null);
  const [vb, setVb] = React.useState<VB | null>(null);
  const [domGen, setDomGen] = React.useState(0);
  const [hasSvg, setHasSvg] = React.useState(false);
  const [hoverPath, setHoverPath] = React.useState<string | null>(null);
  const hoverUnitRef = React.useRef<Element | null>(null);
  const panRef = React.useRef<{ x: number; y: number; vb: VB } | null>(null);
  const spaceRef = React.useRef(false);
  const lastFigureRef = React.useRef<{ baseSvg: string | null; version: number } | null>(null);
  const [, setOverlayTick] = React.useState(0);

  const opsKey = JSON.stringify(ops);
  const selectionPathsRef = React.useRef(selectionPaths);
  selectionPathsRef.current = selectionPaths;

  // ---- 注入 base + 应用 ops（单一 effect；DOM 每次重建后 domGen+1）----
  // 注意：SVG 注入到 injectRef 这个 React 不管理其子节点的内层 div，
  // overlay/按钮等 React 组件是它的兄弟节点 —— 绝不能让 innerHTML 擦掉
  // React 自己管理的 DOM（否则 commit 阶段 insertBefore 找不到锚点直接崩）。
  React.useEffect(() => {
    const host = injectRef.current;
    if (!host || !baseSvg) return;
    host.innerHTML = baseSvg;
    const svg = host.querySelector("svg");
    if (!svg) return;
    const root = svg as SVGSVGElement;
    svgRef.current = root;
    if (!showBase && ops.length > 0) applyOpsToDom(root, ops);
    const parsed = parseVB(root.getAttribute("viewBox"));
    const prevFig = lastFigureRef.current;
    const figureChanged = !prevFig || prevFig.baseSvg !== baseSvg || prevFig.version !== version;
    if (parsed) naturalVb.current = parsed;
    // 挂载/换图/重渲染 → 重置为新图 fit；仅 ops/showBase 变化 → 保留用户当前视图。
    if (parsed && (figureChanged || !vb)) setVb({ ...parsed });
    lastFigureRef.current = { baseSvg, version };
    if (vb && !figureChanged) root.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
    setHasSvg(true);
    setDomGen((g) => g + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseSvg, opsKey, showBase, version]);

  // ---- viewBox 应用 ----
  React.useEffect(() => {
    const svg = svgRef.current;
    if (svg && vb) svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  }, [vb]);

  const fit = React.useCallback(() => {
    if (naturalVb.current) setVb({ ...naturalVb.current });
  }, []);

  // ---- 滚轮缩放（光标为中心）----
  React.useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const onWheel = (e: WheelEvent) => {
      const svg = svgRef.current;
      if (!svg) return;
      e.preventDefault();
      // 行/页滚动模式归一化为像素：按行给值的设备（如 Firefox）deltaY≈±3
      const dyPx = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
      const factor = Math.exp(-dyPx * 0.0015);
      setVb((prev: VB | null) => {
        if (!prev) return prev;
        const rect = svg.getBoundingClientRect();
        const scale = Math.min(rect.width / prev.w, rect.height / prev.h);
        if (!(scale > 0) || !Number.isFinite(scale)) return prev;
        const px = prev.x + prev.w / 2 + (e.clientX - rect.left - rect.width / 2) / scale;
        const py = prev.y + prev.h / 2 + (e.clientY - rect.top - rect.height / 2) / scale;
        const newW = prev.w / factor;
        const newH = prev.h / factor;
        return {
          x: px - ((px - prev.x) / prev.w) * newW,
          y: py - ((py - prev.y) / prev.h) * newH,
          w: newW,
          h: newH,
        };
      });
    };
    wrap.addEventListener("wheel", onWheel, { passive: false });
    return () => wrap.removeEventListener("wheel", onWheel);
  }, []);

  // ---- 平移：中键 / Alt+左键 / 空格+左键 ----
  React.useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const down = (e: PointerEvent) => {
      if (!svgRef.current) return;
      if (!(e.button === 1 || e.altKey || spaceRef.current)) return;
      e.preventDefault();
      setVb((cur: VB | null) => {
        if (cur) panRef.current = { x: e.clientX, y: e.clientY, vb: cur };
        return cur;
      });
      try {
        wrap.setPointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    };
    const move = (e: PointerEvent) => {
      const p = panRef.current;
      const svg = svgRef.current;
      if (!p || !svg) return;
      const rect = svg.getBoundingClientRect();
      const scale = Math.min(rect.width / p.vb.w, rect.height / p.vb.h);
      if (!(scale > 0) || !Number.isFinite(scale)) return;
      const dx = (e.clientX - p.x) / scale;
      const dy = (e.clientY - p.y) / scale;
      setVb({ x: p.vb.x - dx, y: p.vb.y - dy, w: p.vb.w, h: p.vb.h });
    };
    const up = () => {
      panRef.current = null;
    };
    wrap.addEventListener("pointerdown", down);
    wrap.addEventListener("pointermove", move);
    wrap.addEventListener("pointerup", up);
    return () => {
      wrap.removeEventListener("pointerdown", down);
      wrap.removeEventListener("pointermove", move);
      wrap.removeEventListener("pointerup", up);
    };
  }, []);

  React.useEffect(() => {
    const kd = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.code === "Space" && !t?.matches?.("input, textarea, select")) spaceRef.current = true;
    };
    const ku = (e: KeyboardEvent) => {
      if (e.code === "Space") spaceRef.current = false;
    };
    window.addEventListener("keydown", kd);
    window.addEventListener("keyup", ku);
    return () => {
      window.removeEventListener("keydown", kd);
      window.removeEventListener("keyup", ku);
    };
  }, []);

  // ---- overlay 追踪（选中/悬停时以 rAF 跟随 pan/zoom/resize）----
  React.useEffect(() => {
    if (selectionPaths.length === 0 && !hoverPath) return;
    let raf = 0;
    const loop = () => {
      setOverlayTick((t: number) => t + 1);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [selectionPaths.length, hoverPath]);

  // ---- 悬停高亮：与单击同一套语义归并，虚线框预览"点下去会选中谁" ----
  React.useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const clear = () => {
      if (hoverUnitRef.current) {
        hoverUnitRef.current = null;
        setHoverPath(null);
      }
      wrap.style.cursor = "";
    };
    const move = (e: PointerEvent) => {
      const svg = svgRef.current;
      if (!svg) return;
      if (e.buttons !== 0) return; // 拖框/平移中不更新
      const target = e.target as Element | null;
      if (!target || !svg.contains(target)) {
        clear();
        return;
      }
      const unit = selectionUnit(target);
      if (!unit) {
        clear();
        return;
      }
      const path = semanticPath(unit);
      if (selectionPathsRef.current.includes(path)) {
        clear(); // 已选中：实线框在场，不叠加悬停框
        return;
      }
      if (unit !== hoverUnitRef.current) {
        hoverUnitRef.current = unit;
        setHoverPath(path);
      }
      wrap.style.cursor = "pointer";
    };
    wrap.addEventListener("pointermove", move);
    wrap.addEventListener("pointerleave", clear);
    return () => {
      wrap.removeEventListener("pointermove", move);
      wrap.removeEventListener("pointerleave", clear);
      wrap.style.cursor = "";
    };
  }, []);

  // ---- 元素树上报（SVG 重建 + ops 应用完成后）----
  const onElementsRef = React.useRef(onElements);
  onElementsRef.current = onElements;
  React.useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !onElementsRef.current) return;
    onElementsRef.current(buildElementTree(svg));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domGen]);

  // ---- 元素面板点击 → 定位并选中 ----
  const cbSelRef = React.useRef({ onSelection });
  cbSelRef.current = { onSelection };
  React.useEffect(() => {
    const svg = svgRef.current;
    if (!selectRequest || !svg) return;
    const el = locateByPath(svg, selectRequest.path);
    if (!el) return;
    const unit = selectionUnit(el);
    if (!unit) return;
    cbSelRef.current.onSelection([buildSelectionJson(unit, svg)]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectRequest?.nonce]);

  // ---- 选中元素定位 + 类标记 ----
  const svg = svgRef.current;
  const selectedEls: Element[] = [];
  if (svg) {
    for (const p of selectionPaths) {
      const el = locateByPath(svg, p);
      if (el) selectedEls.push(el);
    }
  }
  const hoverEl = svg && hoverPath ? locateByPath(svg, hoverPath) : null;

  React.useEffect(() => {
    const s = svgRef.current;
    if (!s) return;
    s.querySelectorAll(".fa-selected").forEach((el) => el.classList.remove("fa-selected"));
    selectedEls.forEach((el) => el.classList.add("fa-selected"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionPaths.join("|"), domGen]);

  const handleDS = React.useCallback(
    (items: Element[]) => {
      const s = svgRef.current;
      if (!s) return;
      const merged = mergeCollapse(items);
      if (merged.length === 0) return;
      onSelection(merged.map((el) => buildSelectionJson(el, s)));
    },
    [onSelection]
  );

  const handleClick = React.useCallback(
    (target: Element | null, additive: boolean) => {
      const s = svgRef.current;
      if (!s) return;
      if (!target || target === s) {
        onClearSelection();
        return;
      }
      const unit = selectionUnit(target);
      if (!unit) {
        onClearSelection();
        return;
      }
      if (additive) {
        const already = selectionPaths.includes(semanticPath(unit));
        let remaining: Element[];
        if (already) {
          remaining = selectedEls.filter((el) => el !== unit);
        } else {
          remaining = [...selectedEls, unit];
        }
        if (remaining.length === 0) {
          onClearSelection();
          return;
        }
        onSelection(remaining.map((el) => buildSelectionJson(el, s)));
        return;
      }
      onSelection([buildSelectionJson(unit, s)]);
    },
    [onSelection, onClearSelection, selectionPaths, selectedEls]
  );

  const wrapRect = wrapRef.current?.getBoundingClientRect();

  return (
    <div className="fig-viewer-wrap" ref={wrapRef}>
      {/* SVG 注入容器：React 只创建这个空 div，内部 DOM 全部归我们的 effect 管 */}
      <div className="fig-viewer-canvas" ref={injectRef} />
      {hasSvg && wrapRef.current && svgRef.current && (
        <SelectionLayer
          area={wrapRef.current}
          svg={svgRef.current}
          version={domGen}
          preciseMode={preciseMode}
          onDS={handleDS}
          onClick={handleClick}
        />
      )}
      {wrapRect &&
        selectedEls.map((el) => (
          <div key={semanticPath(el)} className="fig-overlay-box" style={boxStyle(el, wrapRect)}>
            <span className="fig-overlay-label">{(el.id || "").replace(/^fa:/, "") || "元素"}</span>
          </div>
        ))}
      {wrapRect && hoverEl && hoverPath && !selectionPaths.includes(hoverPath) && (
        <div key="fa-hover" className="fig-overlay-box hover-box" style={boxStyle(hoverEl, wrapRect)}>
          <span className="fig-overlay-label">{hoverEl.id.replace(/^fa:/, "")}</span>
        </div>
      )}
      <div className="fig-zoom">
        <button className="small" onClick={() => setVb((v: VB | null) => (v ? { ...v, w: v.w / 1.25, h: v.h / 1.25 } : v))}>
          放大
        </button>
        <button className="small" onClick={() => setVb((v: VB | null) => (v ? { ...v, w: v.w * 1.25, h: v.h * 1.25 } : v))}>
          缩小
        </button>
        <button className="small" onClick={fit}>
          适应
        </button>
      </div>
    </div>
  );
}

/** overlay 框定位：元素屏幕包围盒 → 相对 viewer-wrap，外扩 3px。 */
function boxStyle(el: Element, wrapRect: DOMRect): React.CSSProperties {
  const r = el.getBoundingClientRect();
  return {
    left: r.left - wrapRect.left - 3,
    top: r.top - wrapRect.top - 3,
    width: r.width + 6,
    height: r.height + 6,
  };
}

export function locateByPath(root: SVGSVGElement, path: string): Element | null {
  let cur: Element = root;
  for (const part of path.split("/")) {
    let next: Element | null = null;
    for (let i = 0; i < cur.children.length; i++) {
      const c = cur.children[i];
      const lab = c.id || `${c.tagName.toLowerCase()}[${siblingIndex(c)}]`;
      if (lab === part) {
        next = c;
        break;
      }
    }
    if (!next) return null;
    cur = next;
  }
  return cur;
}

function siblingIndex(el: Element): number {
  let i = 0;
  let sib = el.previousElementSibling;
  const tag = el.tagName.toLowerCase();
  while (sib) {
    if (sib.tagName.toLowerCase() === tag) i++;
    sib = sib.previousElementSibling;
  }
  return i + 1;
}
