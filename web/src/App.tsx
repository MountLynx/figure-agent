// App：状态编排。图详情获取、WS 自动刷新（断连降级轮询）、undo/redo、导出。

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Viewer, type ElementNode } from "./components/Viewer";
import { Sidebar } from "./components/Sidebar";
import { EditorPanel } from "./components/EditorPanel";
import { AIPanel } from "./components/AIPanel";
import type { FigureDetail, Op, ProjectInfo, RunEvent, SelectionJSON, TemplateInfo, VerifyResponse } from "./types";

interface HistoryEntry {
  ops: Op[];
  label: string;
}

export default function App() {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [current, setCurrent] = useState<{ project: string; figure: string } | null>(null);
  const [detail, setDetail] = useState<FigureDetail | null>(null);
  const [ops, setOps] = useState<Op[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const [selections, setSelections] = useState<SelectionJSON[]>([]);
  const [selectionPaths, setSelectionPaths] = useState<string[]>([]);
  const [preciseMode, setPreciseMode] = useState(false);
  const [showBase, setShowBase] = useState(false);
  const [lastVerify, setLastVerify] = useState<VerifyResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ msg: string; error?: boolean } | null>(null);
  const [version, setVersion] = useState(0);
  const [wsOnline, setWsOnline] = useState(false);
  const [staleServer, setStaleServer] = useState(false);
  const [elements, setElements] = useState<ElementNode[]>([]);
  const [selectReq, setSelectReq] = useState<{ path: string; nonce: number } | null>(null);
  const [aiEvents, setAiEvents] = useState<RunEvent[]>([]);
  const [runActive, setRunActive] = useState(false);
  const stateRef = useRef({ current, dirty: false });
  // dirty = 本地 ops 与服务器 patch 不一致（保存按钮/WS 自动刷新共用此语义）
  const dirty = JSON.stringify(ops) !== JSON.stringify(detail?.patch.ops ?? []);
  stateRef.current = { current, dirty };

  const showToast = useCallback((msg: string, error = false) => {
    setToast({ msg, error });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const refreshProjects = useCallback(() => {
    api.listProjects().then(setProjects).catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshProjects();
    api.listTemplates().then(setTemplates).catch(() => undefined);
  }, [refreshProjects]);

  // ---- 图详情加载 ----
  const loadFigure = useCallback(
    async (project: string, figure: string, keepOps = false) => {
      try {
        const d = await api.getFigure(project, figure);
        setDetail(d);
        if (!keepOps) {
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

  const selectFigure = useCallback(
    (project: string, figure: string) => {
      setCurrent({ project, figure });
      setSelections([]);
      setSelectionPaths([]);
      setElements([]);
      setVersion((v) => v + 1);
      loadFigure(project, figure);
    },
    [loadFigure]
  );

  // ---- WS 自动刷新 + 轮询降级 ----
  useEffect(() => {
    let ws: WebSocket | null = null;
    let poll: number | null = null;
    let closed = false;

    const handleEvent = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "ai_run") {
          // AI run 事件不依赖当前选图（造图/改造可以在无选中图时发起），
          // 放在 early return 之前，保证 run_end 一定能复位 runActive。
          setAiEvents((prev) => [...prev.slice(-199), { ...data, at: Date.now() }]);
          if (data.phase === "run_end") {
            setRunActive(false);
            const cur = stateRef.current.current;
            if (cur && data.project === cur.project && data.figure === cur.figure) {
              loadFigure(cur.project, cur.figure, stateRef.current.dirty);
            }
            refreshProjects();
          }
          return;
        }
        const cur = stateRef.current.current;
        if (!cur) return;
        if (data.type === "figure_updated" && data.project === cur.project && data.figure === cur.figure) {
          if (stateRef.current.dirty) setStaleServer(true);
          else loadFigure(cur.project, cur.figure);
        }
      } catch {
        /* ignore */
      }
    };

    const connect = () => {
      if (closed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => {
        setWsOnline(true);
        if (poll) {
          window.clearInterval(poll);
          poll = null;
        }
      };
      ws.onmessage = handleEvent;
      ws.onclose = () => {
        setWsOnline(false);
        if (!closed && !poll) {
          // 降级轮询（§9 WS 断连）
          poll = window.setInterval(() => {
            const cur = stateRef.current.current;
            if (!cur) return;
            api
              .getFigure(cur.project, cur.figure)
              .then((d) => {
                const fresh = JSON.stringify(d.patch) !== JSON.stringify(detailRef.current?.patch);
                if (fresh && !stateRef.current.dirty) loadFigure(cur.project, cur.figure);
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
  }, []);

  const detailRef = useRef<FigureDetail | null>(null);
  detailRef.current = detail;

  // ---- ops 编辑（undo/redo 栈）----
  const pushHistory = useCallback((next: Op[], label: string) => {
    setHistory((h) => {
      const trimmed = h.slice(0, histIdxRef.current + 1);
      return [...trimmed, { ops: next, label }];
    });
    setHistIdx((i) => i + 1);
    setOps(next);
  }, []);

  const histIdxRef = useRef(0);
  histIdxRef.current = histIdx;

  const addOps = useCallback(
    (newOps: Op[]) => {
      // set_visible / reorder 是状态型 op：同目标同 kind 的新 op 替换旧 op，不堆积
      const replaceable = new Set(["set_visible", "reorder"]);
      const incoming = new Set(newOps.filter((o) => replaceable.has(o.kind)).map((o) => `${o.kind}|${o.target.id}`));
      const kept = ops.filter((o) => !(replaceable.has(o.kind) && incoming.has(`${o.kind}|${o.target.id}`)));
      pushHistory([...kept, ...newOps], "edit");
    },
    [ops, pushHistory]
  );

  const updateOp = useCallback(
    (id: string, patch: Partial<Op>) => {
      const next = ops.map((o) => (o.id === id ? { ...o, ...patch } : o));
      // 意图编辑不进 undo 栈（避免每次按键一条）
      setOps(next);
      setHistory((h) => {
        const h2 = [...h];
        h2[histIdx] = { ops: next, label: "edit" };
        return h2;
      });
    },
    [ops, histIdx]
  );

  const deleteOp = useCallback(
    (id: string) => {
      pushHistory(
        ops.filter((o) => o.id !== id),
        "delete"
      );
    },
    [ops, pushHistory]
  );

  const undo = useCallback(() => {
    if (histIdx > 0) {
      setHistIdx((i) => i - 1);
      setOps(history[histIdx - 1].ops);
    }
  }, [histIdx, history]);

  const redo = useCallback(() => {
    if (histIdx < history.length - 1) {
      setHistIdx((i) => i + 1);
      setOps(history[histIdx + 1].ops);
    }
  }, [histIdx, history]);

  // ---- 保存 / 校验 / 快照 ----
  const save = useCallback(async () => {
    if (!current) return;
    setBusy(true);
    try {
      const baseHash = detail?.patch.baseHash ?? "";
      await api.putPatch(current.project, current.figure, { baseHash, ops });
      await loadFigure(current.project, current.figure);
      setHistory([{ ops, label: "已保存" }]);
      setHistIdx(0);
      showToast("patch 已保存");
      refreshProjects();
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  }, [current, detail, ops, loadFigure, showToast, refreshProjects]);

  const verify = useCallback(async () => {
    if (!current) return;
    setBusy(true);
    try {
      const v = await api.verifyPatch(current.project, current.figure);
      setLastVerify(v);
      await loadFigure(current.project, current.figure);
      refreshProjects();
      showToast(v.cleared ? "patch 已收敛清空" : `剩余 ${v.remainingOps} 个 op`);
    } catch (e) {
      showToast(`校验失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  }, [current, loadFigure, showToast, refreshProjects]);

  const snapshot = useCallback(
    async (note: string) => {
      if (!current) return;
      try {
        await api.snapshot(current.project, current.figure, note);
        await loadFigure(current.project, current.figure, true);
        showToast("快照已保存");
      } catch (e) {
        showToast(`快照失败：${(e as Error).message}`, true);
      }
    },
    [current, loadFigure, showToast]
  );

  // ---- 选区 ----
  const onSelection = useCallback(
    (jsons: SelectionJSON[]) => {
      if (!current || jsons.length === 0) return;
      setSelectionPaths(jsons.map((j) => j.semanticPath));
      // 单选保持对象形状（兼容服务端/MCP 旧契约），多选传数组
      const payload = jsons.length === 1 ? jsons[0] : jsons;
      api
        .enrichSelection(current.project, current.figure, payload)
        .then((enriched) => setSelections(Array.isArray(enriched) ? enriched : [enriched]))
        .catch(() => setSelections(jsons));
    },
    [current]
  );

  const onClearSelection = useCallback(() => {
    setSelections([]);
    setSelectionPaths([]);
  }, []);

  // ---- 导出 ----
  const getExportSvg = useCallback(async (): Promise<{ text: string; w: number; h: number } | null> => {
    if (!current) return null;
    if (dirty) {
      await save();
    }
    const d = await api.getFigure(current.project, current.figure);
    const text = d.finalSvg ?? d.baseSvg;
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
  }, [current, dirty, save]);

  const exportSvg = useCallback(async () => {
    const out = await getExportSvg();
    if (!out) return;
    downloadBlob(new Blob([out.text], { type: "image/svg+xml" }), `${current?.figure ?? "figure"}.svg`);
    showToast("SVG 已导出");
  }, [getExportSvg, current, showToast]);

  const exportPng = useCallback(async () => {
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
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((b) => {
        if (b) downloadBlob(b, `${current?.figure ?? "figure"}.png`);
        showToast("PNG 已导出");
      }, "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      showToast("PNG 导出失败", true);
    };
    img.src = url;
  }, [getExportSvg, current, showToast]);

  // ---- 建图 ----
  const createFigure = useCallback(
    async (project: string, name: string, template: string) => {
      setBusy(true);
      try {
        const r = await api.createFigure(project, name, template);
        if (!r.ok) showToast(`建图渲染失败：${r.stderr.slice(0, 200)}`, true);
        await refreshProjects();
        selectFigure(project, name);
      } catch (e) {
        showToast(`建图失败：${(e as Error).message}`, true);
      } finally {
        setBusy(false);
      }
    },
    [refreshProjects, selectFigure, showToast]
  );

  const renderError = detail?.renderError;

  return (
    <div className="app">
      <Sidebar
        projects={projects}
        templates={templates}
        current={current}
        onSelect={selectFigure}
        onCreate={createFigure}
        onRefresh={refreshProjects}
      />

      <div className="main">
        <div className="toolbar">
          <b>{current ? `${current.project} / ${current.figure}` : "figure-agent"}</b>
          <span className="hint">{wsOnline ? "WS 已连接" : "WS 断开（轮询中）"}</span>
          <span className="spacer" />
          <label className="toggle">
            <input type="checkbox" checked={preciseMode} onChange={(e) => setPreciseMode(e.target.checked)} />
            精确模式
          </label>
          <label className="toggle">
            <input type="checkbox" checked={showBase} onChange={(e) => setShowBase(e.target.checked)} />
            查看原始 base
          </label>
          <button
            onClick={async () => {
              if (!current) return;
              setBusy(true);
              try {
                const r = await api.run(current.project, current.figure);
                showToast(r.ok ? "重渲染完成" : `渲染失败：${r.stderr.slice(0, 160)}`, !r.ok);
                await loadFigure(current.project, current.figure, stateRef.current.dirty);
                refreshProjects();
              } finally {
                setBusy(false);
              }
            }}
            disabled={!current || busy}
          >
            重渲染
          </button>
        </div>

        {staleServer && (
          <div className="dirty-banner" style={{ margin: "8px 12px 0" }}>
            服务器上的图已更新（AI 或手动渲染）。本地有未保存的微调，未自动刷新；保存或撤销后刷新。
            <button
              className="small"
              style={{ marginLeft: 8 }}
              onClick={() => current && loadFigure(current.project, current.figure)}
            >
              放弃本地修改并刷新
            </button>
          </div>
        )}

        {renderError && <div className="render-error">渲染失败：{renderError}</div>}

        {current ? (
          <Viewer
            baseSvg={detail?.baseSvg ?? null}
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
        ) : (
          <div style={{ display: "grid", placeItems: "center", flex: 1 }} className="hint">
            <div>
              <h2>figure-agent</h2>
              <p>从左侧选择一张图开始。没有图？从模板创建一张。</p>
            </div>
          </div>
        )}
      </div>

      <AIPanel
        projects={projects}
        current={current}
        selections={selections}
        patchOpCount={detail?.patch.ops.length ?? 0}
        runEvents={aiEvents}
        runActive={runActive}
        onRunStart={() => setRunActive(true)}
        onFigureReady={(p, f) => selectFigure(p, f)}
        onFigureChanged={() => {
          refreshProjects();
          if (current) loadFigure(current.project, current.figure, stateRef.current.dirty);
        }}
        showToast={showToast}
      />

      <EditorPanel
        selections={selections}
        ops={ops}
        dirty={dirty}
        canUndo={histIdx > 0}
        canRedo={histIdx < history.length - 1}
        lastVerify={lastVerify}
        snapshots={detail?.snapshots ?? []}
        code={detail?.code ?? null}
        busy={busy}
        elements={elements}
        onSelectElement={(path) => setSelectReq({ path, nonce: Date.now() })}
        onAddOps={addOps}
        onUpdateOp={updateOp}
        onDeleteOp={deleteOp}
        onUndo={undo}
        onRedo={redo}
        onSave={save}
        onVerify={verify}
        onExportPng={exportPng}
        onExportSvg={exportSvg}
        onSnapshot={snapshot}
        onCopySelection={() => {
          if (selections.length === 0) return;
          // 单选复制单个对象；多选复制数组，每条都是各自元素的完整 JSON
          const payload = selections.length === 1 ? selections[0] : selections;
          navigator.clipboard
            .writeText(JSON.stringify(payload, null, 2))
            .then(() =>
              showToast(selections.length === 1 ? "选区 JSON 已复制" : `已复制 ${selections.length} 个元素的选区 JSON`)
            );
        }}
      />

      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.msg}</div>}
    </div>
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
