// SelectionLayer：DragSelect 交互层 + 单击选择 + getIntersectionList 精确模式。
// 统一负责 selectables 的生命周期：SVG DOM 重建（version 变化）时重设。

import { useEffect, useRef } from "react";
import DragSelect from "dragselect";
import { collectSelectables, fullyInsideRect, selectionUnit, type ScreenRect } from "../selection/semantics";

export interface SelectionLayerProps {
  area: HTMLElement;
  svg: SVGSVGElement;
  version: number;
  preciseMode: boolean;
  onDS: (items: Element[]) => void;
  onClick: (target: Element | null, additive: boolean) => void;
}

export function SelectionLayer(props: SelectionLayerProps) {
  const { area, svg, version, preciseMode, onDS, onClick } = props;
  const dsRef = useRef<DragSelect<any> | null>(null);
  const preciseRef = useRef(preciseMode);
  const cbRef = useRef({ onDS, onClick });
  cbRef.current = { onDS, onClick };
  preciseRef.current = preciseMode;

  // ---- DragSelect 实例：DOM 重建时重建 ----
  useEffect(() => {
    dsRef.current?.stop(true, true, false);
    const ds = new DragSelect({
      area,
      selectables: collectSelectables(svg) as HTMLElement[],
      draggability: false,
      autoScrollSpeed: 0,
    });
    let startPt: { x: number; y: number } | null = null;

    ds.subscribe("DS:start", (d: any) => {
      startPt = { x: (d as any).event?.clientX ?? 0, y: (d as any).event?.clientY ?? 0 };
    });
    ds.subscribe("DS:end", (d: any) => {
      const end = { x: (d as any).event?.clientX ?? 0, y: (d as any).event?.clientY ?? 0 };
      const moved = !startPt || Math.hypot(end.x - startPt.x, end.y - startPt.y) > 3;
      const items = ((d as any).items ?? []) as Element[];
      ds.clearSelection(false);
      if (!moved) return; // 单击走自己的 elementFromPoint 逻辑
      if (preciseRef.current) return; // 精确模式在下面 pointer 监听里处理
      if (!startPt) {
        cbRef.current.onDS(items);
        return;
      }
      // 框选只收完全落在框内的元素（DS.items 是相交集，是包含集的超集，过滤即可）
      const rect: ScreenRect = {
        x0: Math.min(startPt.x, end.x),
        y0: Math.min(startPt.y, end.y),
        x1: Math.max(startPt.x, end.x),
        y1: Math.max(startPt.y, end.y),
      };
      startPt = null;
      cbRef.current.onDS(items.filter((el) => fullyInsideRect(el, rect)));
    });
    dsRef.current = ds;
    return () => {
      ds.stop(true, true, false);
      dsRef.current = null;
    };
  }, [area, svg, version]);

  // ---- 单击（elementFromPoint + 向上归并）与精确模式拖框 ----
  useEffect(() => {
    let downPt: { x: number; y: number; additive: boolean } | null = null;

    const isOurButton = (e: PointerEvent) => e.button === 0 && !e.altKey;

    const down = (e: PointerEvent) => {
      if (!isOurButton(e)) return;
      downPt = { x: e.clientX, y: e.clientY, additive: e.shiftKey || e.ctrlKey || e.metaKey };
    };

    const up = (e: PointerEvent) => {
      const d = downPt;
      downPt = null;
      if (!d || !isOurButton(e)) return;
      const moved = Math.hypot(e.clientX - d.x, e.clientY - d.y) > 3;

      if (!moved) {
        // 单击：优先用事件的直接目标（更准），否则 elementFromPoint
        const target = (e.target as Element) || document.elementFromPoint(e.clientX, e.clientY);
        cbRef.current.onClick(target, d.additive);
        return;
      }

      if (preciseRef.current) {
        // 精确模式：getIntersectionList（真实几何，识别 clip-path），再只留完全在框内的语义单位
        const rect = area.getBoundingClientRect();
        const x0 = Math.min(d.x, e.clientX) - rect.left;
        const y0 = Math.min(d.y, e.clientY) - rect.top;
        const x1 = Math.max(d.x, e.clientX) - rect.left;
        const y1 = Math.max(d.y, e.clientY) - rect.top;
        const hits = intersectList(svg, x0, y0, x1, y1);
        const units = new Set<Element>();
        hits.forEach((h) => {
          const u = selectionUnit(h);
          if (u) units.add(u);
        });
        const screenRect: ScreenRect = {
          x0: Math.min(d.x, e.clientX),
          y0: Math.min(d.y, e.clientY),
          x1: Math.max(d.x, e.clientX),
          y1: Math.max(d.y, e.clientY),
        };
        // 精确命中不做归并收拢，保持“所见即所得”，只做祖先剪枝
        const contained = [...units].filter((u) => fullyInsideRect(u, screenRect));
        if (contained.length > 0) {
          cbRef.current.onDS(preciseMerge(contained));
        }
      }
    };

    area.addEventListener("pointerdown", down);
    area.addEventListener("pointerup", up);
    return () => {
      area.removeEventListener("pointerdown", down);
      area.removeEventListener("pointerup", up);
    };
  }, [area, svg]);

  return null;
}

/** 屏幕坐标（相对 area）→ 根用户空间矩形 → getIntersectionList。 */
function intersectList(svg: SVGSVGElement, x0: number, y0: number, x1: number, y1: number): Element[] {
  const ctm = svg.getScreenCTM();
  if (!ctm) return [];
  const inv = ctm.inverse();
  const p0 = new DOMPoint(x0, y0).matrixTransform(inv);
  const p1 = new DOMPoint(x1, y1).matrixTransform(inv);
  const userRect = svg.createSVGRect();
  userRect.x = Math.min(p0.x, p1.x);
  userRect.y = Math.min(p0.y, p1.y);
  userRect.width = Math.max(Math.abs(p1.x - p0.x), 0.5);
  userRect.height = Math.max(Math.abs(p1.y - p0.y), 0.5);
  try {
    return Array.from(svg.getIntersectionList(userRect, svg));
  } catch {
    return getBBoxFallback(svg, userRect);
  }
}

/** getBBox 手动求交降级路径（§13 浏览器差异兜底）。 */
function getBBoxFallback(svg: SVGSVGElement, r: SVGRect): Element[] {
  const out: Element[] = [];
  svg.querySelectorAll("*").forEach((el) => {
    try {
      const bb = (el as SVGGraphicsElement).getBBox();
      const m = (el as SVGGraphicsElement).getScreenCTM();
      const rootM = svg.getScreenCTM();
      if (!m || !rootM) return;
      const t = rootM.inverse().multiply(m);
      const p = new DOMPoint(bb.x + bb.width / 2, bb.y + bb.height / 2).matrixTransform(t);
      if (p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height) out.push(el);
    } catch {
      /* ignore */
    }
  });
  return out;
}

/** 精确模式合并：仅祖先剪枝（所见即所得，不收拢子组）。 */
function preciseMerge(els: Element[]): Element[] {
  const set = new Set(els);
  return els.filter((el) => {
    let cur: Element | null = el.parentElement;
    while (cur) {
      const u = cur.id ? cur : selectionUnit(cur);
      if (u && u !== el && set.has(u)) return false;
      cur = cur.parentElement;
    }
    return true;
  });
}
