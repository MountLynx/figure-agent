// 语义层：fa: gid / matplotlib 自动 id 判定、标签、语义路径、选中归并。
// label/semanticPath 必须与 server 端 svgkit/semantics.py 保持同一算法。

export const SEMANTIC_ID_RE = /^(fa:.+|[A-Za-z][\w.]*_\d+)$/;

export function isSemantic(el: Element): boolean {
  const id = el.id;
  return !!id && SEMANTIC_ID_RE.test(id);
}

export function isFa(el: Element): boolean {
  return (el.id || "").startsWith("fa:");
}

export function localName(el: Element): string {
  return el.tagName.includes(":") ? el.tagName.split(":").pop()! : el.tagName.toLowerCase();
}

/** 同 tag 兄弟中的 1-based 序号（与 Python 端一致）。 */
export function tagIndex(el: Element): number {
  const tag = el.tagName;
  let i = 0;
  let sib = el.previousElementSibling;
  while (sib) {
    if (sib.tagName === tag) i++;
    sib = sib.previousElementSibling;
  }
  return i + 1;
}

export function label(el: Element): string {
  if (el.id) return el.id;
  return `${localName(el)}[${tagIndex(el)}]`;
}

/** semanticPath：从 <svg> 根（不含）到自身的标签序列。 */
export function semanticPath(el: Element): string {
  const parts: string[] = [];
  let cur: Element | null = el;
  while (cur) {
    const parent: Element | null = cur.parentElement;
    if (!parent || parent.tagName.toLowerCase() === "svg") {
      parts.push(label(cur));
      break;
    }
    parts.push(label(cur));
    cur = parent;
  }
  return parts.reverse().join("/");
}

export function nearestSemanticAncestor(el: Element | null): Element | null {
  let cur = el?.parentElement ?? null;
  while (cur) {
    if (isSemantic(cur)) return cur;
    cur = cur.parentElement;
  }
  return null;
}

/** 选区单位：命中原语向上归并到的语义元素（原语自身也带语义 id 时取自身）。 */
export function selectionUnit(el: Element): Element | null {
  if (isSemantic(el)) return el;
  return nearestSemanticAncestor(el);
}

/** 语义元素之间的直接语义子。 */
/** 语义元素之间的直接语义子（按 semanticPath 作 key，避免跨查询的元素身份问题）。 */
export function directSemanticChildren(root: Element | SVGElement): Map<string, string[]> {
  const out = new Map<string, string[]>();
  const parentOf = new Map<string, string>(); // childPath -> parentPath
  root.querySelectorAll("*").forEach((el) => {
    if (!isSemantic(el)) return;
    const p = semanticPath(el);
    out.set(p, []);
    const anc = nearestSemanticAncestor(el); // 从 el.parent 起向上找（el 自身是语义元素）
    if (anc) parentOf.set(p, semanticPath(anc));
  });
  parentOf.forEach((parentPath, childPath) => {
    out.get(parentPath)?.push(childPath);
  });
  return out;
}

export function collectSelectables(root: Element | SVGElement): Element[] {
  const out: Element[] = [];
  root.querySelectorAll("*").forEach((el) => {
    if (isSemantic(el)) out.push(el);
  });
  return out;
}

export interface ScreenRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** 框选容差（px）：抵消描边宽度/取整误差，贴边框选也能命中。 */
export const MARQUEE_TOLERANCE = 1;

/** 元素包围盒完全落在拖框内才算框选命中（相交不选）。 */
export function fullyInsideRect(el: Element, rect: ScreenRect, tol = MARQUEE_TOLERANCE): boolean {
  const b = el.getBoundingClientRect();
  return b.left >= rect.x0 - tol && b.right <= rect.x1 + tol && b.top >= rect.y0 - tol && b.bottom <= rect.y1 + tol;
}

/**
 * 选中归并（§8）：
 * 1. 若某语义组的全部直接语义子都被选中 → 收拢为该组（如框选整个图例）；
 * 2. 剩下的“祖先与后代同时在场”去掉祖先（拖框掠过 axes 大框时不误选 axes）。
 */
export function mergeCollapse(hit: Element[]): Element[] {
  if (hit.length === 0) return [];
  const root = hit[0]?.closest?.("svg") as SVGElement | null;
  if (!root) return [...new Set(hit)];
  const childMap = directSemanticChildren(root);

  // 在 path 空间里做收拢与祖先剪枝（元素包装对象跨查询不稳定，path 稳定）
  const pathOf = new Map<string, Element>();
  const set = new Set<string>();
  for (const el of hit) {
    const p = semanticPath(el);
    pathOf.set(p, el);
    set.add(p);
  }

  let changed = true;
  while (changed) {
    changed = false;
    for (const [parent, children] of childMap) {
      if (!set.has(parent) || children.length === 0) continue;
      if (children.every((c) => set.has(c))) {
        children.forEach((c) => set.delete(c));
        set.add(parent);
        changed = true;
      }
    }
  }
  // 祖先剪枝：拖框的 AABB 会命中祖先容器；凡拥有更具体后代在选中集的祖先都丢弃
  const arr = [...set];
  const result: Element[] = [];
  for (const p of arr) {
    const prefix = p + "/";
    const dominated = arr.some((q) => q !== p && q.startsWith(prefix));
    if (!dominated) {
      const el = pathOf.get(p);
      if (el) result.push(el);
    }
  }
  return result;
}
