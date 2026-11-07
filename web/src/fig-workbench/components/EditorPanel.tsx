// 右栏面板（当前选区 + 元素树）与底层面板（轻编辑 + 微调 patch）。
// 自 figure-agent EditorPanel.tsx 移植裁剪；轻编辑/patch 拆出供工作台底部横排。

import * as React from "react";
import type { Op, SelectionJSON, VerifyResponse } from "../../shared/types";
import type { ElementNode } from "./Viewer";

export interface EditorPanelProps {
  selections: SelectionJSON[];
  ops: Op[];
  elements: ElementNode[];
  onSelectElement: (path: string) => void;
  onAddOps: (ops: Op[]) => void;
  onCopySelection: () => void;
}

export interface LightEditPanelProps {
  selections: SelectionJSON[];
  ops: Op[];
  canUndo: boolean;
  canRedo: boolean;
  lastVerify: VerifyResponse | null;
  onAddOps: (ops: Op[]) => void;
  onUpdateOp: (id: string, patch: Partial<Op>) => void;
  onDeleteOp: (id: string) => void;
  onUndo: () => void;
  onRedo: () => void;
}

const FONT_FAMILIES = [
  "DejaVu Sans",
  "Arial",
  "Helvetica",
  "Times New Roman",
  "SimHei",
  "Microsoft YaHei",
  "Noto Sans CJK SC",
  "sans-serif",
  "serif",
];

let opCounter = 0;

export function nextOpId(ops: Op[]): string {
  let max = 0;
  for (const op of ops) {
    const m = /^op-(\d+)$/.exec(op.id);
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  opCounter = Math.max(opCounter, max);
  return `op-${max + 1}`;
}

export function EditorPanel(props: EditorPanelProps) {
  const {
    selections, ops, elements, onSelectElement, onAddOps, onCopySelection,
  } = props;

  // 白名单模型：expanded 为空 = 全部折叠；展开的节点其子节点默认仍折叠
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const treeRef = React.useRef<HTMLDivElement | null>(null);

  // 当前选中的语义路径 → 元素行高亮
  const selectedPaths = new Set(selections.map((s) => s.semanticPath).filter(Boolean));
  const selKey = [...selectedPaths].join("|");

  // 选中不展开树：高亮其可见的折叠祖先（祖先全展开时即自身）
  const repPaths = new Set<string>();
  for (const s of selectedPaths) {
    const parts = s.split("/");
    let anc = "";
    let rep = s;
    for (let i = 0; i < parts.length - 1; i++) {
      anc = anc ? `${anc}/${parts[i]}` : parts[i];
      if (!expanded.has(anc)) {
        rep = anc;
        break;
      }
    }
    repPaths.add(rep);
  }

  // 选中变化：滚动到其可见代表行（折叠分支内为祖先行）
  React.useEffect(() => {
    if (selectedPaths.size === 0) return;
    const first = [...selectedPaths][0];
    const parts = first.split("/");
    let target = first;
    let anc = "";
    for (let i = 0; i < parts.length - 1; i++) {
      anc = anc ? `${anc}/${parts[i]}` : parts[i];
      if (!expanded.has(anc)) {
        target = anc;
        break;
      }
    }
    const raf = requestAnimationFrame(() => {
      treeRef.current
        ?.querySelector(`[data-element-path="${cssEscape(target)}"]`)
        ?.scrollIntoView({ block: "nearest" });
    });
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selKey]);

  const toggleExpanded = (path: string) => {
    setExpanded((prev: Set<string>) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const toggleVisible = (n: ElementNode) => {
    onAddOps([
      {
        id: nextOpId(ops),
        kind: "set_visible",
        target: { id: n.id, semanticPath: n.path, fingerprint: "" },
        value: n.hidden, // 可见→隐藏(false)；已隐藏→显示(true)
        intent: `${n.label} ${n.hidden ? "显示" : "隐藏"}`,
        origin: "manual",
        status: "active",
      },
    ]);
  };

  const reorderElement = (n: ElementNode, to: "front" | "back") => {
    onAddOps([
      {
        id: nextOpId(ops),
        kind: "reorder",
        target: { id: n.id, semanticPath: n.path, fingerprint: "" },
        value: { to },
        intent: `${n.label} ${to === "front" ? "置顶" : "置底"}`,
        origin: "manual",
        status: "active",
      },
    ]);
  };

  const renderElement = (n: ElementNode, depth: number): any => {
    const hasKids = n.children.length > 0;
    const isOpen = expanded.has(n.path);
    const isActive = selectedPaths.has(n.path) || repPaths.has(n.path);
    return (
      <div key={n.path}>
        <div
          className={`fig-element-row ${n.hidden ? "element-hidden" : ""} ${isActive ? "element-active" : ""}`}
          style={{ paddingLeft: 4 + depth * 14 }}
          data-element-path={n.path}
        >
          {hasKids ? (
            <button className="small fig-element-caret" onClick={() => toggleExpanded(n.path)}>
              {isOpen ? "▾" : "▸"}
            </button>
          ) : (
            <span className="fig-element-caret" />
          )}
          <span
            className="fig-element-name"
            title={n.hidden ? `${n.path}（已隐藏）` : n.path}
            onClick={() => !n.hidden && onSelectElement(n.path)}
          >
            {n.label}
          </span>
          <span style={{ flex: 1 }} />
          <button className="small fig-element-btn" title="移到最上层（回写 set_zorder）" onClick={() => reorderElement(n, "front")}>
            ⬆
          </button>
          <button className="small fig-element-btn" title="移到最下层（回写 set_zorder）" onClick={() => reorderElement(n, "back")}>
            ⬇
          </button>
          <button className="small fig-element-btn" title={n.hidden ? "显示（回写 set_visible(True)）" : "隐藏（回写 set_visible(False)）"} onClick={() => toggleVisible(n)}>
            {n.hidden ? "🚫" : "👁"}
          </button>
        </div>
        {hasKids && isOpen && n.children.map((c) => renderElement(c, depth + 1))}
      </div>
    );
  };

  const primary = selections[0];

  return (
    <>
      {/* 选区信息 */}
      <div className="fig-section">
        <h3>当前选区</h3>
        {!primary && <div className="fig-hint">在图形上单击或拖框选择元素。Shift+点击多选；空格/Alt+拖动平移；滚轮缩放。框选只选中完全落在框内的元素；开启精确模式后拖框用真实几何判定（排除 clip-path 隐藏元素）。</div>}
        {primary && (
          <div className="fig-sel-info">
            <div><b>{primary.elementId ?? "(无 id)"}</b></div>
            <div>{primary.semanticPath}</div>
            {primary.userSpaceBBox && (
              <div>
                bbox: ({primary.userSpaceBBox.x}, {primary.userSpaceBBox.y}) {primary.userSpaceBBox.w}×{primary.userSpaceBBox.h}
              </div>
            )}
            {primary.style?.fill && <div>fill: <span style={{ display: "inline-block", width: 10, height: 10, background: primary.style.fill, borderRadius: 2, verticalAlign: "middle" }} /> {primary.style.fill}</div>}
            {primary.text?.content && <div>文本: "{primary.text.content}" / {primary.text.fontFamily} {primary.text.fontSize}</div>}
            {primary.fingerprint && <div>指纹: {primary.fingerprint}</div>}
            {primary.nearby && primary.nearby.length > 0 && <div>附近: {primary.nearby.slice(0, 3).join("；")}</div>}
            {primary.warnings && primary.warnings.length > 0 && <div className="fig-sel-lost">{primary.warnings.join("；")}</div>}
            <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
              <button className="small" onClick={onCopySelection}>
                复制选区 JSON{selections.length > 1 ? `（${selections.length} 个）` : ""}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 元素（语义树：眼睛=显隐，⬆⬇=绘制层级） */}
      {elements.length > 0 && (
        <div className="fig-section">
          <h3>元素</h3>
          <div className="fig-element-tree" ref={treeRef}>{elements.map((n) => renderElement(n, 0))}</div>
          <div className="fig-hint">眼睛切换显隐、⬆⬇ 调整绘制层级，都会生成 patch op，可通过回写收敛进代码（set_visible / set_zorder）。</div>
        </div>
      )}
    </>
  );
}

export function LightEditPanel(props: LightEditPanelProps) {
  const {
    selections, ops, canUndo, canRedo, lastVerify,
    onAddOps, onUpdateOp, onDeleteOp, onUndo, onRedo,
  } = props;

  const [dx, setDx] = React.useState("5");
  const [dy, setDy] = React.useState("0");
  const [scalePct, setScalePct] = React.useState("120");
  const [fontSize, setFontSize] = React.useState("12");
  const [fontFamily, setFontFamily] = React.useState(FONT_FAMILIES[0]);

  const primary = selections[0];
  const hasText = !!primary?.text?.content;

  function buildOps(partial: (target: SelectionJSON, index: number) => Omit<Op, "id" | "target">): Op[] {
    return selections.map((sel, i) => {
      const base = partial(sel, i);
      return {
        id: nextOpId(ops) + (i > 0 ? `-${i}` : ""),
        target: {
          id: sel.elementId,
          semanticPath: sel.semanticPath,
          fingerprint: sel.fingerprint ?? "",
        },
        ...base,
      } as Op;
    });
  }

  const setFill = (hex: string) => {
    onAddOps(
      buildOps((sel) => ({
        kind: "set_style",
        attr: "fill",
        value: hex,
        intent: `${labelOf(sel)} 填充改为 ${hex}`,
        origin: "manual",
        status: "active",
      }))
    );
  };
  const setStroke = (hex: string) => {
    onAddOps(
      buildOps((sel) => ({
        kind: "set_style",
        attr: "stroke",
        value: hex,
        intent: `${labelOf(sel)} 描边改为 ${hex}`,
        origin: "manual",
        status: "active",
      }))
    );
  };
  const setFont = () => {
    onAddOps([
      ...buildOps((sel) => ({
        kind: "set_style",
        attr: "font-family",
        value: fontFamily,
        intent: `${labelOf(sel)} 字体改为 ${fontFamily}`,
        origin: "manual",
        status: "active",
      })),
      ...buildOps((sel) => ({
        kind: "set_style",
        attr: "font-size",
        value: `${parseFloat(fontSize)}px`,
        intent: `${labelOf(sel)} 字号改为 ${parseFloat(fontSize)}px`,
        origin: "manual",
        status: "active",
      })),
    ]);
  };
  const translate = (ddx: number, ddy: number) => {
    onAddOps(
      buildOps((sel) => ({
        kind: "transform",
        value: { translate: [ddx, ddy] },
        intent: `${labelOf(sel)} 平移 (${ddx}, ${ddy})`,
        origin: "manual",
        status: "active",
      }))
    );
  };
  const scale = () => {
    const s = parseFloat(scalePct) / 100;
    onAddOps(
      buildOps((sel) => {
        const bb = sel.userSpaceBBox;
        return {
          kind: "transform",
          value: { scale: [s, s] },
          pre: bb
            ? { center: [round2(bb.x + bb.w / 2), round2(bb.y + bb.h / 2)], size: [round2(bb.w), round2(bb.h)] }
            : undefined,
          intent: `${labelOf(sel)} 缩放到 ${scalePct}%`,
          origin: "manual",
          status: "active",
        };
      })
    );
  };
  const setText = (t: string) => {
    onAddOps(
      buildOps((sel) => ({
        kind: "set_text",
        value: t,
        intent: `${labelOf(sel)} 文本改为 "${t}"`,
        origin: "manual",
        status: "active",
      }))
    );
  };

  const step = 5;

  return (
    <>
      {/* 轻编辑手势 */}
      <div className="fig-section">
        <h3>轻编辑{primary ? `（${selections.length} 个目标）` : ""}</h3>
        {!primary && <div className="fig-hint">在图形上单击或拖框选择元素后，可在此微调填充 / 描边 / 字体 / 位置 / 大小。</div>}
        {primary && (
          <div className="fig-edit-grid">
            <label>填充</label>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="color" defaultValue="#2563eb" onChange={(e) => setFill((e.target as HTMLInputElement).value)} />
              <button className="small" onClick={() => setFill("none")}>无填充</button>
            </div>

            <label>描边</label>
            <input type="color" defaultValue="#1c2733" onChange={(e) => setStroke((e.target as HTMLInputElement).value)} />

            <label>字体 / 字号</label>
            <div style={{ display: "flex", gap: 6 }}>
              <select value={fontFamily} onChange={(e) => setFontFamily((e.target as HTMLSelectElement).value)}>
                {FONT_FAMILIES.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
              <input type="number" style={{ width: 64 }} value={fontSize} onChange={(e) => setFontSize((e.target as HTMLInputElement).value)} />
              <button className="small" onClick={setFont}>应用</button>
            </div>

            <label>位置</label>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="number" style={{ width: 64 }} value={dx} onChange={(e) => setDx((e.target as HTMLInputElement).value)} />
              <input type="number" style={{ width: 64 }} value={dy} onChange={(e) => setDy((e.target as HTMLInputElement).value)} />
              <button className="small" onClick={() => translate(num(dx), num(dy))}>平移</button>
            </div>
            <label />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 34px)", gap: 3 }}>
              <span />
              <button className="small" onClick={() => translate(0, -step)}>↑</button>
              <span />
              <button className="small" onClick={() => translate(-step, 0)}>←</button>
              <button className="small" onClick={() => translate(0, step)}>↓</button>
              <button className="small" onClick={() => translate(step, 0)}>→</button>
            </div>

            <label>大小</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input type="number" style={{ width: 64 }} value={scalePct} onChange={(e) => setScalePct((e.target as HTMLInputElement).value)} />
              <span className="fig-hint">%</span>
              <button className="small" onClick={scale}>缩放</button>
            </div>

            {hasText && (
              <>
                <label>文本</label>
                <input
                  type="text"
                  defaultValue={primary.text?.content ?? ""}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") setText((e.target as HTMLInputElement).value);
                  }}
                  onBlur={(e) => {
                    if ((e.target as HTMLInputElement).value !== primary.text?.content) setText((e.target as HTMLInputElement).value);
                  }}
                />
              </>
            )}
          </div>
        )}
      </div>

      {/* op 列表 */}
      <div className="fig-section">
        <h3>
          微调 patch（{ops.length}）
          <button className="small" style={{ float: "right" }} disabled={!canUndo} onClick={onUndo}>撤销</button>
          <button className="small" style={{ float: "right", marginRight: 4 }} disabled={!canRedo} onClick={onRedo}>重做</button>
        </h3>
        {ops.length === 0 && <div className="fig-hint">还没有手动微调。微调以 patch 形式叠加在渲染结果上，代码重跑不丢失。</div>}
        {ops.map((op) => {
          const vr = lastVerify?.results.find((r) => r.opId === op.id);
          const status = op.status === "lost" ? "lost" : vr?.status ?? op.status;
          return (
            <div className="fig-op-item" key={op.id}>
              <div className="fig-op-head">
                <span className={`fig-status-badge fig-status-${status}`}>{status}</span>
                <b>{op.id}</b>
                <span className="fig-op-desc">{describe(op)}</span>
                <span style={{ flex: 1 }} />
                <button className="small" onClick={() => onDeleteOp(op.id)}>删</button>
              </div>
              <input
                type="text"
                value={op.intent}
                onChange={(e) => onUpdateOp(op.id, { intent: (e.target as HTMLInputElement).value })}
                style={{ fontSize: 12, border: "1px dashed var(--border)" }}
              />
              {vr?.status === "active" && vr.detail && <div className="fig-op-desc">差异：{vr.detail}</div>}
              {status === "lost" && <div className="fig-sel-lost">目标丢失：代码变化后找不到元素，请重新选择。</div>}
            </div>
          );
        })}
      </div>
    </>
  );
}

function labelOf(sel: SelectionJSON): string {
  return sel.elementId?.replace(/^fa:/, "") ?? sel.semanticPath.split("/").pop() ?? "元素";
}

function cssEscape(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function num(s: string): number {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : 0;
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

export function describe(op: Op): string {
  if (op.kind === "set_style") return `${op.attr} = ${op.value}`;
  if (op.kind === "set_text") return `文本 = ${op.value}`;
  if (op.kind === "set_visible") return op.value ? "显示" : "隐藏";
  if (op.kind === "reorder") return op.value?.to === "front" ? "置顶" : "置底";
  const parts: string[] = [];
  if (op.value?.translate) parts.push(`平移(${op.value.translate[0]}, ${op.value.translate[1]})`);
  if (op.value?.scale) parts.push(`缩放(${op.value.scale[0]}, ${op.value.scale[1] ?? op.value.scale[0]})`);
  return parts.join(" ") || "transform";
}
