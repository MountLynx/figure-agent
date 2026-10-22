// 右侧面板：选区信息、元素、四项编辑手势、op 列表、回写校验、快照、导出、代码只读展示

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Op, SelectionJSON, SnapshotInfo, VerifyResponse } from "../types";
import type { ElementNode } from "./Viewer";

export interface EditorPanelProps {
  selections: SelectionJSON[];
  ops: Op[];
  dirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  lastVerify: VerifyResponse | null;
  snapshots: SnapshotInfo[];
  code: string | null;
  busy: boolean;
  elements: ElementNode[];
  onSelectElement: (path: string) => void;

  onAddOps: (ops: Op[]) => void;
  onUpdateOp: (id: string, patch: Partial<Op>) => void;
  onDeleteOp: (id: string) => void;
  onUndo: () => void;
  onRedo: () => void;
  onSave: () => void;
  onVerify: () => void;
  onExportPng: () => void;
  onExportSvg: () => void;
  onSnapshot: (note: string) => void;
  onCopySelection: () => void;
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
    selections, ops, dirty, canUndo, canRedo, lastVerify, snapshots, code, busy,
    elements, onSelectElement,
    onAddOps, onUpdateOp, onDeleteOp, onUndo, onRedo, onSave, onVerify,
    onExportPng, onExportSvg, onSnapshot, onCopySelection,
  } = props;

  const [dx, setDx] = useState("5");
  const [dy, setDy] = useState("0");
  const [scalePct, setScalePct] = useState("120");
  const [fontSize, setFontSize] = useState("12");
  const [fontFamily, setFontFamily] = useState(FONT_FAMILIES[0]);
  const [snapNote, setSnapNote] = useState("");
  const [showCode, setShowCode] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const treeRef = useRef<HTMLDivElement | null>(null);

  // 当前选中的语义路径 → 元素行高亮
  const selectedPaths = new Set(selections.map((s) => s.semanticPath).filter(Boolean));
  const selKey = [...selectedPaths].join("|");

  // 选中变化：展开被折叠的祖先 + 滚动到首个选中行
  useEffect(() => {
    if (selectedPaths.size === 0) return;
    setCollapsed((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const p of prev) {
        if ([...selectedPaths].some((s) => s.startsWith(p + "/"))) {
          next.delete(p);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    const first = [...selectedPaths][0];
    const raf = requestAnimationFrame(() => {
      treeRef.current
        ?.querySelector(`[data-element-path="${cssEscape(first)}"]`)
        ?.scrollIntoView({ block: "nearest" });
    });
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selKey]);

  const toggleCollapsed = (path: string) => {
    setCollapsed((prev) => {
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

  const renderElement = (n: ElementNode, depth: number): ReactNode => {
    const hasKids = n.children.length > 0;
    const isCollapsed = collapsed.has(n.path);
    const isActive = selectedPaths.has(n.path);
    return (
      <div key={n.path}>
        <div
          className={`element-row ${n.hidden ? "element-hidden" : ""} ${isActive ? "element-active" : ""}`}
          style={{ paddingLeft: 4 + depth * 14 }}
          data-element-path={n.path}
        >
          {hasKids ? (
            <button className="small element-caret" onClick={() => toggleCollapsed(n.path)}>
              {isCollapsed ? "▸" : "▾"}
            </button>
          ) : (
            <span className="element-caret" />
          )}
          <span
            className="element-name"
            title={n.hidden ? `${n.path}（已隐藏）` : n.path}
            onClick={() => !n.hidden && onSelectElement(n.path)}
          >
            {n.label}
          </span>
          <span style={{ flex: 1 }} />
          <button className="small element-btn" title="移到最上层（回写 set_zorder）" onClick={() => reorderElement(n, "front")}>
            ⬆
          </button>
          <button className="small element-btn" title="移到最下层（回写 set_zorder）" onClick={() => reorderElement(n, "back")}>
            ⬇
          </button>
          <button className="small element-btn" title={n.hidden ? "显示（回写 set_visible(True)）" : "隐藏（回写 set_visible(False)）"} onClick={() => toggleVisible(n)}>
            {n.hidden ? "🚫" : "👁"}
          </button>
        </div>
        {hasKids && !isCollapsed && n.children.map((c) => renderElement(c, depth + 1))}
      </div>
    );
  };

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
    <div className="rightpanel">
      {/* 选区信息 */}
      <div className="section">
        <h3>当前选区</h3>
        {!primary && <div className="hint">在图形上单击或拖框选择元素。Shift+点击多选；空格/Alt+拖动平移；滚轮缩放。框选只选中完全落在框内的元素；开启精确模式后拖框用真实几何判定（排除 clip-path 隐藏元素）。</div>}
        {primary && (
          <div className="sel-info">
            <div><b>{primary.elementId ?? "(无 id)"}</b></div>
            <div>{primary.semanticPath}</div>
            {primary.userSpaceBBox && (
              <div>
                bbox: ({primary.userSpaceBBox.x}, {primary.userSpaceBBox.y}) {primary.userSpaceBBox.w}×{primary.userSpaceBBox.h}
              </div>
            )}
            {primary.style?.fill && <div>fill: <span style={{ display: "inline-block", width: 10, height: 10, background: primary.style.fill, borderRadius: 2, verticalAlign: "middle" }} /> {primary.style.fill}</div>}
            {primary.text?.content && <div>文本: “{primary.text.content}” / {primary.text.fontFamily} {primary.text.fontSize}</div>}
            {primary.fingerprint && <div>指纹: {primary.fingerprint}</div>}
            {primary.nearby && primary.nearby.length > 0 && <div>附近: {primary.nearby.slice(0, 3).join("；")}</div>}
            {primary.warnings && primary.warnings.length > 0 && <div className="sel-lost">{primary.warnings.join("；")}</div>}
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
        <div className="section">
          <h3>元素</h3>
          <div className="element-tree" ref={treeRef}>{elements.map((n) => renderElement(n, 0))}</div>
          <div className="hint">眼睛切换显隐、⬆⬇ 调整绘制层级，都会生成 patch op，可通过回写收敛进代码（set_visible / set_zorder）。</div>
        </div>
      )}

      {/* 四项编辑手势 */}
      {primary && (
        <div className="section">
          <h3>轻编辑（{selections.length} 个目标）</h3>
          <div className="edit-grid">
            <label>填充</label>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="color" defaultValue="#2563eb" onChange={(e) => setFill(e.target.value)} />
              <button className="small" onClick={() => setFill("none")}>无填充</button>
            </div>

            <label>描边</label>
            <input type="color" defaultValue="#1c2733" onChange={(e) => setStroke(e.target.value)} />

            <label>字体 / 字号</label>
            <div style={{ display: "flex", gap: 6 }}>
              <select value={fontFamily} onChange={(e) => setFontFamily(e.target.value)}>
                {FONT_FAMILIES.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
              <input type="number" style={{ width: 64 }} value={fontSize} onChange={(e) => setFontSize(e.target.value)} />
              <button className="small" onClick={setFont}>应用</button>
            </div>

            <label>位置</label>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="number" style={{ width: 64 }} value={dx} onChange={(e) => setDx(e.target.value)} />
              <input type="number" style={{ width: 64 }} value={dy} onChange={(e) => setDy(e.target.value)} />
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
              <input type="number" style={{ width: 64 }} value={scalePct} onChange={(e) => setScalePct(e.target.value)} />
              <span className="hint">%</span>
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
                    if (e.target.value !== primary.text?.content) setText(e.target.value);
                  }}
                />
              </>
            )}
          </div>
        </div>
      )}

      {/* op 列表 */}
      <div className="section">
        <h3>
          微调 patch（{ops.length}）
          <button className="small" style={{ float: "right" }} disabled={!canUndo || busy} onClick={onUndo}>撤销</button>
          <button className="small" style={{ float: "right", marginRight: 4 }} disabled={!canRedo || busy} onClick={onRedo}>重做</button>
        </h3>
        {dirty && <div className="dirty-banner">有未保存的修改。保存后服务端才会生成 final.svg（ZCode/MCP 才能看到）。</div>}
        {ops.length === 0 && <div className="hint">还没有手动微调。微调以 patch 形式叠加在渲染结果上，代码重跑不丢失。</div>}
        {ops.map((op) => {
          const vr = lastVerify?.results.find((r) => r.opId === op.id);
          const status = op.status === "lost" ? "lost" : vr?.status ?? op.status;
          return (
            <div className="op-item" key={op.id}>
              <div className="op-head">
                <span className={`status-badge status-${status}`}>{status}</span>
                <b>{op.id}</b>
                <span className="op-desc">{describe(op)}</span>
                <span style={{ flex: 1 }} />
                <button className="small" onClick={() => onDeleteOp(op.id)}>删</button>
              </div>
              <input
                type="text"
                value={op.intent}
                onChange={(e) => onUpdateOp(op.id, { intent: e.target.value })}
                style={{ fontSize: 12, border: "1px dashed var(--border)" }}
              />
              {vr?.status === "active" && vr.detail && <div className="op-desc">差异：{vr.detail}</div>}
              {status === "lost" && <div className="sel-lost">目标丢失：代码变化后找不到元素，请重新选择。</div>}
            </div>
          );
        })}
        <div style={{ display: "flex", gap: 6 }}>
          <button className="primary" style={{ flex: 1 }} disabled={!dirty || busy} onClick={onSave}>
            保存 patch
          </button>
          <button disabled={busy} onClick={onVerify}>回写校验</button>
        </div>
        {lastVerify && (
          <div className="hint">
            {lastVerify.cleared
              ? "✅ patch 已收敛清空：所有微调都已表达进代码。"
              : `剩余 ${lastVerify.remainingOps} 个 op 未收敛。在 ZCode 里说“把 patch 回写进代码”，或手动改代码后重跑。`}
          </div>
        )}
      </div>

      {/* 快照 + 导出 */}
      <div className="section">
        <h3>快照 / 导出</h3>
        <div style={{ display: "flex", gap: 6 }}>
          <input type="text" placeholder="快照备注" value={snapNote} onChange={(e) => setSnapNote(e.target.value)} />
          <button
            className="small"
            onClick={() => {
              onSnapshot(snapNote);
              setSnapNote("");
            }}
          >
            快照
          </button>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="small" style={{ flex: 1 }} onClick={onExportPng}>导出 PNG</button>
          <button className="small" style={{ flex: 1 }} onClick={onExportSvg}>导出 SVG</button>
        </div>
        {snapshots.length > 0 && (
          <div className="hint">
            历史：{snapshots.slice(0, 5).map((s) => `${s.id}${s.note ? `（${s.note}）` : ""}`).join("、")}
          </div>
        )}
      </div>

      {/* 代码只读展示 */}
      <div className="section">
        <h3>
          plot.py（只读，代码在 ZCode/编辑器里改）
          <button className="small" style={{ float: "right" }} onClick={() => setShowCode((v) => !v)}>
            {showCode ? "收起" : "展开"}
          </button>
        </h3>
        {showCode && code && <pre className="code">{code}</pre>}
      </div>
    </div>
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
