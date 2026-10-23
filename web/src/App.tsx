// App：双视图编排。管理视图（Index 三栏）/ 编辑器视图（画布+AI+微调）。
// 编辑器逻辑与旧版一致，仅寻址从 (project, figure) 改为 item id。

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Viewer, type ElementNode } from "./components/Viewer";
import { EditorPanel } from "./components/EditorPanel";
import { AIPanel } from "./components/AIPanel";
import { ManageView } from "./components/manage/ManageView";
import DogfoodApp from "./shell-dogfood/DogfoodApp";
import type { FigureDetail, Op, RunEvent, SelectionJSON, VerifyResponse } from "./types";

interface HistoryEntry {
  ops: Op[];
  label: string;
}

export default function App() {
  // ?view=shell：@index/shell-react 狗粮视图（其余入口不受影响）
  if (new URLSearchParams(window.location.search).get("view") === "shell") return <DogfoodApp />;
  return <IndexApp />;
}

function IndexApp() {
  const [target, setTarget] = useState<{ id: string; name: string } | null>(null);
  if (!target) return <ManageView onOpen={(id, name) => setTarget({ id, name })} />;
  return <EditorApp target={target} onBack={() => setTarget(null)} />;
}

function EditorApp({ target, onBack }: { target: { id: string; name: string }; onBack: () => void }) {
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
  const stateRef = useRef({ id: target.id, dirty: false });
  // dirty = 本地 ops 与服务器 patch 不一致（保存按钮/WS 自动刷新共用此语义）
  const dirty = JSON.stringify(ops) !== JSON.stringify(detail?.patch.ops ?? []);
  stateRef.current = { id: target.id, dirty };

  const showToast = useCallback((msg: string, error = false) => {
    setToast({ msg, error });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  // ---- 图详情加载 ----
  const loadFigure = useCallback(
    async (id: string, keepOps = false) => {
      try {
        const d = await api.getFigure(id);
        if (stateRef.current.id !== id) return; // 守卫：响应期间已切图 → 丢弃过期响应
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

  useEffect(() => {
    setSelections([]);
    setSelectionPaths([]);
    setElements([]);
    setVersion((v) => v + 1); // 图切换代数 +1：Viewer 据此重置内部缓存（与旧版 selectFigure 语义一致）
    loadFigure(target.id);
  }, [target.id, loadFigure]);

  // ---- WS 自动刷新 + 轮询降级 ----
  const detailRef = useRef<FigureDetail | null>(null);
  detailRef.current = detail;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let poll: number | null = null;
    let closed = false;

    const handleEvent = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "ai_run") {
          setAiEvents((prev) => [...prev.slice(-199), { at: Date.now(), ...data }]);
          if (data.phase === "run_end") {
            setRunActive(false);
            const id = stateRef.current.id;
            if (id && (!data.item || data.item === id)) {
              loadFigure(id, stateRef.current.dirty);
            }
          }
          return;
        }
        const id = stateRef.current.id;
        if (!id) return;
        if (data.type === "figure_updated" && data.item === id) {
          if (stateRef.current.dirty) setStaleServer(true);
          else loadFigure(id);
        }
        if (data.type === "figure_deleted" && data.item === id) {
          showToast("该图已被删除", true);
          onBack();
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
            const id = stateRef.current.id;
            if (!id) return;
            api
              .getFigure(id)
              .then((d) => {
                const fresh = JSON.stringify(d.patch) !== JSON.stringify(detailRef.current?.patch);
                if (fresh && !stateRef.current.dirty) loadFigure(id);
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
    setBusy(true);
    try {
      const baseHash = detail?.patch.baseHash ?? "";
      await api.putPatch(target.id, { baseHash, ops });
      await loadFigure(target.id);
      setHistory([{ ops, label: "已保存" }]);
      setHistIdx(0);
      showToast("patch 已保存");
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  }, [target, detail, ops, loadFigure, showToast]);

  const verify = useCallback(async () => {
    setBusy(true);
    try {
      const v = await api.verifyPatch(target.id);
      setLastVerify(v);
      await loadFigure(target.id);
      showToast(v.cleared ? "patch 已收敛清空" : `剩余 ${v.remainingOps} 个 op`);
    } catch (e) {
      showToast(`校验失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  }, [target, loadFigure, showToast]);

  const snapshot = useCallback(
    async (note: string) => {
      try {
        await api.snapshot(target.id, note);
        await loadFigure(target.id, true);
        showToast("快照已保存");
      } catch (e) {
        showToast(`快照失败：${(e as Error).message}`, true);
      }
    },
    [target, loadFigure, showToast]
  );

  // ---- 选区 ----
  const onSelection = useCallback(
    (jsons: SelectionJSON[]) => {
      if (jsons.length === 0) return;
      setSelectionPaths(jsons.map((j) => j.semanticPath));
      // 单选保持对象形状（兼容服务端旧契约），多选传数组
      const payload = jsons.length === 1 ? jsons[0] : jsons;
      api
        .enrichSelection(target.id, payload)
        .then((enriched) => setSelections(Array.isArray(enriched) ? enriched : [enriched]))
        .catch(() => setSelections(jsons));
    },
    [target]
  );

  const onClearSelection = useCallback(() => {
    setSelections([]);
    setSelectionPaths([]);
  }, []);

  // ---- 导出 ----
  const getExportSvg = useCallback(async (): Promise<{ text: string; w: number; h: number } | null> => {
    if (dirty) {
      await save();
    }
    const d = await api.getFigure(target.id);
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
  }, [target, dirty, save]);

  const exportSvg = useCallback(async () => {
    const out = await getExportSvg();
    if (!out) return;
    downloadBlob(new Blob([out.text], { type: "image/svg+xml" }), `${target.name}.svg`);
    showToast("SVG 已导出");
  }, [getExportSvg, target, showToast]);

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
        if (b) downloadBlob(b, `${target.name}.png`);
        showToast("PNG 已导出");
      }, "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      showToast("PNG 导出失败", true);
    };
    img.src = url;
  }, [getExportSvg, target, showToast]);

  const renderError = detail?.renderError;
  const current = { id: target.id, name: target.name };

  return (
    <div className="app editor">
      <div className="main">
        <div className="toolbar">
          <button onClick={onBack}>← 管理</button>
          <b>{target.name}</b>
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
              setBusy(true);
              try {
                const r = await api.run(target.id);
                showToast(r.ok ? "重渲染完成" : `渲染失败：${r.stderr.slice(0, 160)}`, !r.ok);
                await loadFigure(target.id, stateRef.current.dirty);
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || runActive}
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
              onClick={() => loadFigure(target.id)}
            >
              放弃本地修改并刷新
            </button>
          </div>
        )}

        {renderError && <div className="render-error">渲染失败：{renderError}</div>}

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
      </div>

      <AIPanel
        current={current}
        selections={selections}
        patchOpCount={detail?.patch.ops.length ?? 0}
        runEvents={aiEvents}
        runActive={runActive}
        wsOnline={wsOnline}
        onRunStart={() => setRunActive(true)}
        onRunEnd={() => setRunActive(false)}
        onFigureChanged={() => {
          // 经 ref 取最新 id：run 中途切图后，旧闭包里的 id 会把旧图
          // detail/ops 覆盖到新图上下文（再点保存就把旧图 ops 存进新图）
          loadFigure(stateRef.current.id, stateRef.current.dirty);
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
        busy={busy || runActive}
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
