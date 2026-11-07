// AI 面板：指令修改 / 回写 patch / 实时运行时间线（WS 自连，按 dir 过滤事件）。
// 独立应用里由应用状态回答「有没有图」（原来靠 ctx.selectedItem）：无图时只显示
// 引导文案，有图才渲染操作控件。（自 itemmanage figurePlugins/fig-ai 移植）

import * as React from "react";
import { api } from "../shared/api";
import { wsUrl } from "../shared/ws";
import type { AiStatus, RunEvent, SelectionJSON } from "../shared/types";

export interface AIPanelProps {
  /** figure API 的路径标识（独立应用固定占位，服务端按 dir 定位工作目录）。 */
  itemId: string;
  /** 工作目录（服务端 /api/context 的规范值）：WS 事件按它过滤。 */
  dir: string;
  /** 应用状态：null = 还在探测，false = 无 plot.py，true = 有图可用。 */
  hasFigure: boolean | null;
  /** 当前选区（工作台内传入；独立 AI 页签无选区时为空）。 */
  selection?: SelectionJSON[];
  /** 运行结束后把最新的「是否有图」写回应用状态。 */
  onHasFigure?: (hasFigure: boolean) => void;
  /** 图内容变化（AI 改完代码）后通知工作台重新加载。 */
  onFigureChanged?: () => void;
}

export function AIPanel(props: AIPanelProps) {
  const { itemId, dir, hasFigure, selection = [] } = props;
  const selectionRef = React.useRef(selection);
  selectionRef.current = selection;

  const [status, setStatus] = React.useState<AiStatus | null>(null);
  const [instruction, setInstruction] = React.useState("");
  const [runEvents, setRunEvents] = React.useState<RunEvent[]>([]);
  const [runActive, setRunActive] = React.useState(false);
  const [wsOnline, setWsOnline] = React.useState(false);
  const [opCount, setOpCount] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ text: string; error?: boolean } | null>(null);

  const showToast = (text: string, error = false) => {
    setMsg({ text, error });
    window.setTimeout(() => setMsg(null), 3200);
  };

  // ---- 图状态跟随应用：有图才拉 op 数（回写按钮的计数）----
  React.useEffect(() => {
    setRunEvents([]);
    if (!hasFigure) {
      setOpCount(0);
      return;
    }
    let stale = false;
    api
      .getFigure(itemId)
      .then((d) => {
        if (stale) return;
        setOpCount(d.hasFigure ? d.patch.ops.length : 0);
      })
      .catch(() => undefined);
    return () => {
      stale = true;
    };
  }, [itemId, hasFigure]);

  // ---- 取 AI 状态（WS 重连自愈重取）----
  const refreshStatus = () => {
    api
      .aiStatus()
      .then(setStatus)
      .catch(() => setStatus({ configured: false, provider: "", model: "", mock: false }));
  };

  React.useEffect(() => {
    refreshStatus();
  }, [wsOnline]);

  // ---- WS 自连：独立应用只有一个工作目录，事件按 dir 过滤（无 dir 字段则视为本目录）----
  React.useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    const connect = () => {
      if (closed) return;
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        setWsOnline(true);
        setRunActive(false);
        refreshStatus();
      };
      ws.onmessage = (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.dir && data.dir !== dir) return;
          // 图内容在别处变了（建图 / 重渲染 / 删除）→ 重新探测「是否有图」
          if (data.type === "figure_updated" || data.type === "figure_deleted") {
            refreshFigureMeta();
            return;
          }
          if (data.type !== "ai_run") return;
          setRunEvents((prev: RunEvent[]) => [...prev.slice(-199), { at: Date.now(), ...data }]);
          if (data.phase === "run_end") {
            setRunActive(false);
            api
              .getFigure(itemId)
              .then((d) => {
                props.onHasFigure?.(d.hasFigure);
                setOpCount(d.hasFigure ? d.patch.ops.length : 0);
                props.onFigureChanged?.();
              })
              .catch(() => undefined);
          }
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        setWsOnline(false);
        if (!closed) window.setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      ws?.close();
    };
    // props 回调经 ref 语义使用：dir 变了才重连
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir, itemId]);

  const disabled = runActive || busy || !status?.configured || hasFigure !== true;

  const handleInstruct = async () => {
    if (!instruction.trim()) return;
    setRunActive(true);
    try {
      const sel = selectionRef.current;
      const r = await api.instruct(itemId, instruction, sel.length === 1 ? sel[0] : sel);
      showToast(r.ok ? "修改完成" : `修改失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
    } catch (e) {
      showToast(`修改失败：${(e as Error).message}`, true);
    } finally {
      // fetch settle 即代表服务端 run 已结束（含未进 run_workflow 的早失败），
      // 先于 WS run_end 复位无害且幂等；否则 WS 丢事件时面板永久锁死
      setRunActive(false);
      refreshFigureMeta();
    }
  };

  const handleWriteback = async () => {
    setRunActive(true);
    try {
      const r = await api.writebackPatch(itemId);
      showToast(
        r.cleared
          ? "patch 已收敛清空"
          : (r.remaining ?? -1) < 0
            ? "回写未收敛"
            : `回写未收敛：剩余 ${r.remaining} 个 op`,
        !r.cleared
      );
    } catch (e) {
      showToast(`回写失败：${(e as Error).message}`, true);
    } finally {
      setRunActive(false);
      refreshFigureMeta();
    }
  };

  const refreshFigureMeta = () => {
    api
      .getFigure(itemId)
      .then((d) => {
        props.onHasFigure?.(d.hasFigure);
        setOpCount(d.hasFigure ? d.patch.ops.length : 0);
        props.onFigureChanged?.();
      })
      .catch(() => undefined);
  };

  if (hasFigure === null) {
    return (
      <div className="fig-scope fig-ai-root">
        <div className="fig-ai-empty">正在检测这个目录的图表…</div>
      </div>
    );
  }

  if (hasFigure === false) {
    return (
      <div className="fig-scope fig-ai-root">
        <div className="fig-ai-empty">
          该目录还没有图表。
          <br />
          先在工作台建图（plot.py 生成）后，这里会显示 AI 操作面板。
        </div>
      </div>
    );
  }

  return (
    <div className="fig-scope fig-ai-root">
      <div className="fig-ai-status">
        AI：
        {status === null
          ? "检测中…"
          : status.configured
            ? `${status.provider} / ${status.model}${status.mock ? "（mock）" : ""}`
            : `未配置${status.detail ? `（${status.detail}）` : ""}：请在 ~/.figureagent/ 放 llm.json + .env，或设 FIGUREAGENT_MOCK=1 免 key 冒烟`}
      </div>

      <section>
        <h4>指令修改</h4>
        <textarea
          placeholder="例如：把选中的柱子改成主色蓝，字号统一 12（先在图表工作台选中元素效果更好）"
          value={instruction}
          onChange={(e) => setInstruction((e.target as HTMLTextAreaElement).value)}
          disabled={disabled}
        />
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={handleInstruct} disabled={disabled || !instruction.trim()}>
            执行修改
          </button>
          <button onClick={handleWriteback} disabled={disabled || opCount === 0}>
            回写 patch（{opCount} op）
          </button>
        </div>
      </section>

      <section>
        <h4>运行时间线 {wsOnline ? "" : "（WS 断开）"}</h4>
        {runEvents.length === 0 && <div className="fig-hint">尚无 AI 运行</div>}
        <ul className="fig-runlist">
          {runEvents.map((ev, i) => (
            <li key={i} className={`fig-run-ev fig-run-ev-${ev.phase}`}>
              {new Date(ev.at).toLocaleTimeString()} {ev.phase}
              {ev.node ? ` · ${ev.node}` : ""}
              {ev.detail ? ` · ${ev.detail}` : ""}
            </li>
          ))}
        </ul>
      </section>

      {msg && <div className={`fig-toast ${msg.error ? "error" : ""}`}>{msg.text}</div>}
    </div>
  );
}
