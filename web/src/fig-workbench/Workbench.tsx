// 工作台编排：无图 → 建图流；有图 → 编辑器（Viewer + 底栏 + 右侧属性/AI 页签）。
// 自 itemmanage figurePlugins/fig-workbench 移植：布局与交互（侧栏自动收起、
// 点击元素后的元素列表）原样保留；只把宿主注入的 ctx 换成独立应用的 props
// （dir / name / 固定占位 id），并把 AI 面板合进右栏（`?panel=ai` 为后续拆分预留）。

import * as React from "react";
import { api } from "../shared/api";
import { wsUrl } from "../shared/ws";
import type {
  AiRunResult,
  FigureResponse,
  Op,
  RunEvent,
  SelectionJSON,
  VerifyResponse,
} from "../shared/types";
import { AIPanel } from "../fig-ai/AIPanel";
import { Viewer, type ElementNode } from "./components/Viewer";
import { EditorPanel, LightEditPanel } from "./components/EditorPanel";
import { CreateFlow } from "./CreateFlow";

interface HistoryEntry {
  ops: Op[];
  label: string;
}

export interface WorkbenchProps {
  /** figure API 路径里的固定占位（独立应用没有条目 id，服务端按 dir 定位）。 */
  itemId: string;
  /** 工作目录（`/api/context` 返回的规范路径）：WS 事件按它过滤。 */
  dir: string;
  /** 目录名：标题 / 建图流标题 / 导出文件名。 */
  name: string;
  /** 应用状态里的「是否有图」（detail 还没加载时给 AI 页签用）。 */
  hasFigure?: boolean | null;
  /** 图状态变化上报（App 用它回答「有没有图」→ AI 面板是否可用）。 */
  onFigureStateChange?: (hasFigure: boolean) => void;
}

export function Workbench(props: WorkbenchProps) {
  const { itemId, dir, name } = props;
  // 右栏页签：属性（选区 + 元素树 + 信息）/ AI（原 fig-ai 面板）
  const [rightTab, setRightTab] = React.useState<"props" | "ai">("props");
  const rightColRef = React.useRef<HTMLDivElement | null>(null);
  // 切页签回到顶部：两个页签共用同一个滚动容器，不重置会停在上一页的位置
  React.useEffect(() => {
    rightColRef.current?.scrollTo({ top: 0 });
  }, [rightTab]);
  const [detail, setDetail] = React.useState<FigureResponse | null>(null);
  const [ops, setOps] = React.useState<Op[]>([]);
  const [history, setHistory] = React.useState<HistoryEntry[]>([]);
  const [histIdx, setHistIdx] = React.useState(-1);
  const [selections, setSelections] = React.useState<SelectionJSON[]>([]);
  const [selectionPaths, setSelectionPaths] = React.useState<string[]>([]);
  const [preciseMode, setPreciseMode] = React.useState(false);
  const [showBase, setShowBase] = React.useState(false);
  const [lastVerify, setLastVerify] = React.useState<VerifyResponse | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [toast, setToast] = React.useState<{ msg: string; error?: boolean } | null>(null);
  const [version, setVersion] = React.useState(0);
  const [wsOnline, setWsOnline] = React.useState(false);
  const [staleServer, setStaleServer] = React.useState(false);
  const [elements, setElements] = React.useState<ElementNode[]>([]);
  const [selectReq, setSelectReq] = React.useState<{ path: string; nonce: number } | null>(null);
  const [aiEvents, setAiEvents] = React.useState<RunEvent[]>([]);
  const [runActive, setRunActive] = React.useState(false);
  const [showCode, setShowCode] = React.useState(false);
  const [snapNote, setSnapNote] = React.useState("");
  const stateRef = React.useRef({ id: itemId, dirty: false });
  // dirty = 本地 ops 与服务器 patch 不一致（保存按钮/WS 自动刷新共用此语义）
  const dirty = JSON.stringify(ops) !== JSON.stringify((detail as any)?.patch?.ops ?? []);
  stateRef.current = { id: itemId, dirty };

  const showToast = React.useCallback((msg: string, error = false) => {
    setToast({ msg, error });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  // ---- 图详情加载 ----
  // 回调经 ref 调用：App 传入的 setState 是稳定的，但避免把 loadFigure 的依赖搅乱
  const onFigureStateChangeRef = React.useRef(props.onFigureStateChange);
  onFigureStateChangeRef.current = props.onFigureStateChange;

  const loadFigure = React.useCallback(
    async (id: string, keepOps = false) => {
      try {
        const d = await api.getFigure(id);
        if (stateRef.current.id !== id) return; // 守卫：响应期间已切图 → 丢弃过期响应
        setDetail(d);
        onFigureStateChangeRef.current?.(d.hasFigure);
        if (!keepOps && d.hasFigure) {
          setOps(d.patch.ops ?? []);
          setHistory([{ ops: d.patch.ops ?? [], label: "服务器版本" }]);
          setHistIdx(0);
          setLastVerify(null);
        }
        setStaleServer(false);
      } catch (e) {
        showToast(`加载失败：${(e as Error).message}`, true);
      }
    },
    [showToast]
  );

  React.useEffect(() => {
    setSelections([]);
    setSelectionPaths([]);
    setElements([]);
    setVersion((v: number) => v + 1); // 图切换代数 +1：Viewer 据此重置内部缓存
    loadFigure(itemId);
  }, [itemId, loadFigure]);

  // ---- WS 自动刷新 + 轮询降级 ----
  const detailRef = React.useRef<FigureResponse | null>(null);
  detailRef.current = detail;

  React.useEffect(() => {
    let ws: WebSocket | null = null;
    let poll: number | null = null;
    let closed = false;

    const handleEvent = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data);
        // 独立应用只有一个工作目录：事件按 dir 匹配（旧 item 字段兼容保留）
        const ours = !data.dir || data.dir === dir;
        if (data.type === "ai_run") {
          if (ours) {
            setAiEvents((prev: RunEvent[]) => [...prev.slice(-199), { at: Date.now(), ...data }]);
          }
          if (data.phase === "run_end") {
            setRunActive(false);
            if (ours) {
              loadFigure(itemId, stateRef.current.dirty);
            }
          }
          return;
        }
        if (data.type === "figure_updated" && ours) {
          if (stateRef.current.dirty) setStaleServer(true);
          else loadFigure(itemId);
        }
        if (data.type === "figure_deleted" && ours) {
          loadFigure(itemId); // 回到建图流
        }
      } catch {
        /* ignore */
      }
    };

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        setWsOnline(true);
        setRunActive(false);
        if (poll) {
          window.clearInterval(poll);
          poll = null;
        }
      };
      ws.onmessage = handleEvent;
      ws.onclose = () => {
        setWsOnline(false);
        if (!closed && !poll) {
          // 降级轮询（WS 断连）
          poll = window.setInterval(() => {
            api
              .getFigure(itemId)
              .then((d) => {
                const fresh =
                  JSON.stringify(d.hasFigure ? (d as any).patch : null) !==
                  JSON.stringify(detailRef.current?.hasFigure ? (detailRef.current as any).patch : null);
                if (fresh && !stateRef.current.dirty) loadFigure(itemId);
              })
              .catch(() => undefined);
          }, 3000);
        }
        if (!closed) window.setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (poll) window.clearInterval(poll);
      ws?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemId, dir]);

  // ---- ops 编辑（undo/redo 栈）----
  const histIdxRef = React.useRef(0);
  histIdxRef.current = histIdx;

  const pushHistory = React.useCallback((next: Op[], _label: string) => {
    setHistory((h: HistoryEntry[]) => {
      const trimmed = h.slice(0, histIdxRef.current + 1);
      return [...trimmed, { ops: next, label: _label }];
    });
    setHistIdx((i: number) => i + 1);
    setOps(next);
  }, []);

  const addOps = React.useCallback(
    (newOps: Op[]) => {
      // set_visible / reorder 是状态型 op：同目标同 kind 的新 op 替换旧 op，不堆积
      const replaceable = new Set(["set_visible", "reorder"]);
      const incoming = new Set(newOps.filter((o) => replaceable.has(o.kind)).map((o) => `${o.kind}|${o.target.id}`));
      const kept = ops.filter((o) => !(replaceable.has(o.kind) && incoming.has(`${o.kind}|${o.target.id}`)));
      pushHistory([...kept, ...newOps], "edit");
    },
    [ops, pushHistory]
  );

  const updateOp = React.useCallback(
    (id: string, patch: Partial<Op>) => {
      const next = ops.map((o) => (o.id === id ? { ...o, ...patch } : o));
      // 意图编辑不进 undo 栈（避免每次按键一条）
      setOps(next);
      setHistory((h: HistoryEntry[]) => {
        const h2 = [...h];
        h2[histIdx] = { ops: next, label: "edit" };
        return h2;
      });
    },
    [ops, histIdx]
  );

  const deleteOp = React.useCallback(
    (id: string) => {
      pushHistory(
        ops.filter((o) => o.id !== id),
        "delete"
      );
    },
    [ops, pushHistory]
  );

  const undo = React.useCallback(() => {
    if (histIdx > 0) {
      setHistIdx((i: number) => i - 1);
      setOps(history[histIdx - 1].ops);
    }
  }, [histIdx, history]);

  const redo = React.useCallback(() => {
    if (histIdx < history.length - 1) {
      setHistIdx((i: number) => i + 1);
      setOps(history[histIdx + 1].ops);
    }
  }, [histIdx, history]);

  // ---- 保存 / 校验 / 快照 / 渲染 ----
  const save = React.useCallback(async () => {
    setBusy(true);
    try {
      const baseHash = (detail as any)?.patch?.baseHash ?? "";
      await api.putPatch(itemId, { baseHash, ops });
      await loadFigure(itemId);
      setHistory([{ ops, label: "已保存" }]);
      setHistIdx(0);
      showToast("patch 已保存");
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  }, [itemId, detail, ops, loadFigure, showToast]);

  const verify = React.useCallback(async () => {
    setBusy(true);
    try {
      const v = await api.verifyPatch(itemId);
      setLastVerify(v);
      await loadFigure(itemId);
      showToast(v.cleared ? "patch 已收敛清空" : `剩余 ${v.remainingOps} 个 op`);
    } catch (e) {
      showToast(`校验失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  }, [itemId, loadFigure, showToast]);

  const snapshot = React.useCallback(
    async (note: string) => {
      try {
        await api.snapshot(itemId, note);
        await loadFigure(itemId, true);
        showToast("快照已保存");
      } catch (e) {
        showToast(`快照失败：${(e as Error).message}`, true);
      }
    },
    [itemId, loadFigure, showToast]
  );

  const rerender = React.useCallback(async () => {
    setBusy(true);
    try {
      const r = await api.run(itemId);
      showToast(r.ok ? "重渲染完成" : `渲染失败：${r.stderr.slice(0, 160)}`, !r.ok);
      await loadFigure(itemId, stateRef.current.dirty);
    } finally {
      setBusy(false);
    }
  }, [itemId, loadFigure, showToast]);

  // ---- 选区 ----
  const onSelection = React.useCallback(
    (jsons: SelectionJSON[]) => {
      if (jsons.length === 0) return;
      setSelectionPaths(jsons.map((j) => j.semanticPath));
      // 单选保持对象形状（兼容服务端契约），多选传数组
      const payload = jsons.length === 1 ? jsons[0] : jsons;
      api
        .enrichSelection(itemId, payload)
        .then((enriched) => setSelections(Array.isArray(enriched) ? enriched : [enriched]))
        .catch(() => setSelections(jsons));
    },
    [itemId]
  );

  const onClearSelection = React.useCallback(() => {
    setSelections([]);
    setSelectionPaths([]);
  }, []);

  // ---- 导出 ----
  const getExportSvg = React.useCallback(async (): Promise<{ text: string; w: number; h: number } | null> => {
    if (dirty) {
      await save();
    }
    const d = await api.getFigure(itemId);
    const text = d.hasFigure ? d.finalSvg ?? d.baseSvg : null;
    if (!text) return null;
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    const svg = doc.documentElement;
    const vb = svg.getAttribute("viewBox")?.split(/[\s,]+/).map(Number);
    let w = parseFloat(svg.getAttribute("width") || "");
    let h = parseFloat(svg.getAttribute("height") || "");
    if ((!Number.isFinite(w) || !Number.isFinite(h)) && vb) {
      w = vb[2];
      h = vb[3];
    }
    return { text, w: w || 400, h: h || 300 };
  }, [itemId, dirty, save]);

  const exportSvg = React.useCallback(async () => {
    const out = await getExportSvg();
    if (!out) return;
    downloadBlob(new Blob([out.text], { type: "image/svg+xml" }), `${detail?.name ?? name}.svg`);
    showToast("SVG 已导出");
  }, [getExportSvg, detail, name, showToast]);

  const exportPng = React.useCallback(async () => {
    const out = await getExportSvg();
    if (!out) return;
    const scale = 2;
    const blob = new Blob([out.text], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(out.w * scale);
      canvas.height = Math.round(out.h * scale);
      const c2d = canvas.getContext("2d")!;
      c2d.fillStyle = "#ffffff";
      c2d.fillRect(0, 0, canvas.width, canvas.height);
      c2d.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((b) => {
        if (b) downloadBlob(b, `${detail?.name ?? name}.png`);
        showToast("PNG 已导出");
      }, "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      showToast("PNG 导出失败", true);
    };
    img.src = url;
  }, [getExportSvg, detail, itemId, showToast]);

  // ---- 建图流完成 ----
  const onFigureCreated = React.useCallback(
    (_r: AiRunResult) => {
      setAiEvents([]);
      loadFigure(itemId);
    },
    [itemId, loadFigure]
  );

  const renderError = detail?.hasFigure ? detail.renderError : null;
  const code = detail?.hasFigure ? detail.code : null;

  // ---- 无图：建图流 ----
  if (detail && !detail.hasFigure) {
    return (
      <div className="fig-scope" style={{ height: "100%", overflow: "auto" }}>
        <CreateFlow itemId={itemId} itemName={detail.name ?? name} onCreated={onFigureCreated} showToast={showToast} />
      </div>
    );
  }

  return (
    <div className="fig-scope fig-workbench-root">
      <div className="fig-header">
        <b>{detail?.hasFigure ? detail.name ?? name : name}</b>
        <span className="fig-ws-state">{wsOnline ? "WS 已连接" : "WS 断开（轮询中）"}</span>
        <span style={{ flex: 1 }} />
        <label className="toggle">
          <input type="checkbox" checked={preciseMode} onChange={(e) => setPreciseMode((e.target as HTMLInputElement).checked)} />
          精确模式
        </label>
        <label className="toggle">
          <input type="checkbox" checked={showBase} onChange={(e) => setShowBase((e.target as HTMLInputElement).checked)} />
          查看原始 base
        </label>
      </div>

      {staleServer && (
        <div className="fig-dirty-banner" style={{ margin: "8px 10px 0" }}>
          服务器上的图已更新（AI 或手动渲染）。本地有未保存的微调，未自动刷新；保存或撤销后刷新。
          <button className="small" style={{ marginLeft: 8 }} onClick={() => loadFigure(itemId)}>
            放弃本地修改并刷新
          </button>
        </div>
      )}

      {renderError && <div className="fig-notice error">渲染失败：{renderError}</div>}

      <div className="fig-main">
        <div className="fig-col-left">
          <Viewer
            baseSvg={detail?.hasFigure ? detail.baseSvg : null}
            ops={ops}
            showBase={showBase}
            preciseMode={preciseMode}
            selectionPaths={selectionPaths}
            onSelection={onSelection}
            onClearSelection={onClearSelection}
            version={version}
            onElements={setElements}
            selectRequest={selectReq}
          />

          {/* 底栏：渲染 / 保存 / 验证patch / 快照 / 导出 / 代码 */}
          <div className="fig-bottombar">
            <button disabled={busy || runActive} onClick={rerender}>渲染</button>
            <button className="primary" disabled={!dirty || busy || runActive} onClick={save}>
              保存 patch{dirty ? " ●" : ""}
            </button>
            <button disabled={busy || runActive} onClick={verify}>验证 patch</button>
            <input
              type="text"
              placeholder="快照备注"
              style={{ width: 120 }}
              value={snapNote}
              onChange={(e) => setSnapNote((e.target as HTMLInputElement).value)}
            />
            <button
              className="small"
              onClick={() => {
                snapshot(snapNote);
                setSnapNote("");
              }}
              disabled={busy}
            >
              快照
            </button>
            <button className="small" disabled={busy} onClick={exportPng}>导出 PNG</button>
            <button className="small" disabled={busy} onClick={exportSvg}>导出 SVG</button>
            <button className="small" onClick={() => setShowCode((v) => !v)}>{showCode ? "收起代码" : "代码"}</button>
            <span className="spacer" />
            <span className="fig-hint">AI 指令 / 回写请用右栏「AI」页签</span>
          </div>

          {showCode && (
            <div style={{ padding: "0 10px 10px" }}>
              <pre className="fig-code">{code ?? "（plot.py 尚未生成）"}</pre>
            </div>
          )}
        </div>

        <div className="fig-col-right" ref={rightColRef}>
          <div className="fig-tabs" role="tablist" aria-label="右栏面板">
            <button
              role="tab"
              aria-selected={rightTab === "props"}
              className={rightTab === "props" ? "active" : ""}
              onClick={() => setRightTab("props")}
            >
              属性
            </button>
            <button
              role="tab"
              aria-selected={rightTab === "ai"}
              className={rightTab === "ai" ? "active" : ""}
              onClick={() => setRightTab("ai")}
            >
              AI
            </button>
          </div>
          {rightTab === "props" ? (
            <>
              <EditorPanel
                selections={selections}
                ops={ops}
                elements={elements}
                onSelectElement={(path) => setSelectReq({ path, nonce: Date.now() })}
                onAddOps={addOps}
                onCopySelection={() => {
                  if (selections.length === 0) return;
                  const payload = selections.length === 1 ? selections[0] : selections;
                  navigator.clipboard
                    .writeText(JSON.stringify(payload, null, 2))
                    .then(() =>
                      showToast(selections.length === 1 ? "选区 JSON 已复制" : `已复制 ${selections.length} 个元素的选区 JSON`)
                    );
                }}
              />
              <SideInfo itemId={itemId} dir={dir} detail={detail} />
            </>
          ) : (
            <AIPanel
              itemId={itemId}
              dir={dir}
              hasFigure={detail === null ? props.hasFigure ?? null : detail.hasFigure}
              selection={selections}
              onHasFigure={(hasFigure) => onFigureStateChangeRef.current?.(hasFigure)}
              onFigureChanged={() => loadFigure(itemId, stateRef.current.dirty)}
            />
          )}
        </div>
      </div>

      {/* 底层面板：轻编辑 / 微调 patch / 运行记录 */}
      <div className="fig-bottompanel">
        <LightEditPanel
          selections={selections}
          ops={ops}
          canUndo={histIdx > 0}
          canRedo={histIdx < history.length - 1}
          lastVerify={lastVerify}
          onAddOps={addOps}
          onUpdateOp={updateOp}
          onDeleteOp={deleteOp}
          onUndo={undo}
          onRedo={redo}
        />
        <RunEventsPanel aiEvents={aiEvents} />
      </div>

      {toast && <div className={`fig-toast ${toast.error ? "error" : ""}`}>{toast.msg}</div>}
    </div>
  );
}

/** 底层面板：AI 运行事件流。 */
export function RunEventsPanel({ aiEvents }: { aiEvents: RunEvent[] }) {
  return (
    <div className="fig-section">
      <h3>运行记录</h3>
      {aiEvents.length === 0 && <div className="fig-hint">尚无 AI 运行事件（指令修改 / 回写在右栏「AI」页签发起）。</div>}
      <ul className="fig-runlist">
        {aiEvents.slice(-30).map((ev, i) => (
          <li key={i} className={`fig-run-ev fig-run-ev-${ev.phase}`}>
            {new Date(ev.at).toLocaleTimeString()} {ev.phase}
            {ev.node ? ` · ${ev.node}` : ""}
            {ev.detail ? ` · ${ev.detail}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 右侧信息栏：工作目录 / 快照历史 / 文件列表（独立应用没有条目属性）。 */
function SideInfo(props: {
  itemId: string;
  dir: string;
  detail: FigureResponse | null;
}) {
  const { itemId, dir, detail } = props;
  const [files, setFiles] = React.useState<any>(null);
  const [filesOpen, setFilesOpen] = React.useState(false);

  React.useEffect(() => {
    if (!filesOpen) return;
    api
      .listFiles()
      .then(setFiles)
      .catch(() => setFiles(null));
  }, [itemId, filesOpen]);

  const snapshots = detail?.hasFigure ? detail.snapshots ?? [] : [];
  const properties = detail?.hasFigure ? detail.properties ?? {} : {};

  const renderFileTree = (node: any, depth = 0): any => {
    const kids: any[] = node.children ?? [];
    return kids.map((c) => (
      <div key={c.name + depth}>
        <div style={{ paddingLeft: depth * 12 }}>
          {c.is_dir ? "▸ " : ""}
          {c.name}
          {c.is_dir ? "/" : ""}
        </div>
        {c.is_dir && renderFileTree(c, depth + 1)}
      </div>
    ));
  };

  return (
    <>
      <div className="fig-section">
        <h3>目录属性</h3>
        <div className="fig-kv">
          <span className="k">目录</span>
          <span className="v">{dir || "—"}</span>
          <span className="k">有图</span>
          <span className="v">{detail?.hasFigure ? "是（plot.py）" : detail ? "否" : "加载中…"}</span>
          {Object.entries(properties).map(([k, v]) => (
            <React.Fragment key={k}>
              <span className="k">{k}</span>
              <span className="v">{String(v)}</span>
            </React.Fragment>
          ))}
        </div>
      </div>

      <div className="fig-section">
        <h3>快照历史</h3>
        {snapshots.length === 0 && <div className="fig-hint">尚无快照。底栏「快照」保存当前 base+patch+代码。</div>}
        {snapshots.slice(0, 8).map((s) => (
          <div key={s.dir} className="fig-hint">
            {s.createdAt.replace("T", " ")}
            {s.note ? ` · ${s.note}` : ""}
          </div>
        ))}
      </div>

      <div className="fig-section">
        <h3>
          文件列表
          <button className="small" style={{ float: "right" }} onClick={() => setFilesOpen((v) => !v)}>
            {filesOpen ? "收起" : "展开"}
          </button>
        </h3>
        {filesOpen && (
          <div className="fig-filelist">{files ? renderFileTree(files) : "（加载失败或为空）"}</div>
        )}
        {filesOpen && <div className="fig-hint">文件放在工作目录里；plot.py/data.csv 等为图表保留名。</div>}
      </div>
    </>
  );
}

function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
