// AI 面板：选区指令 + 回写 + run 事件时间线（造图/改造在管理视图的新建对话框）。
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AiStatus, AiRunResult, RunEvent, SelectionJSON } from "../types";

interface Props {
  current: { id: string; name: string };
  selections: SelectionJSON[];
  patchOpCount: number;
  runEvents: RunEvent[];
  runActive: boolean;
  wsOnline: boolean;
  onRunStart: () => void;
  onRunEnd: () => void;
  onFigureChanged: () => void;
  showToast: (msg: string, error?: boolean) => void;
}

export function AIPanel(props: Props) {
  const { current, selections, patchOpCount, runEvents, runActive, wsOnline,
          onRunStart, onRunEnd, onFigureChanged, showToast } = props;
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [instruction, setInstruction] = useState("");

  // 取状态可复调：WS 重连（wsOnline 翻转）时重试——首次失败会永久停在"未配置"，
  // 重连后再取一次可自愈。
  const refreshStatus = () => {
    api.aiStatus().then(setStatus).catch(() => setStatus({ configured: false, provider: "", model: "", mock: false }));
  };

  useEffect(() => {
    refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsOnline]);

  const disabled = runActive || !status?.configured;

  const handleInstruct = async () => {
    if (!instruction.trim()) return;
    onRunStart();
    try {
      const payload = selections.length === 1 ? selections[0] : selections;
      const r: AiRunResult = await api.instruct(current.id, instruction, payload);
      showToast(r.ok ? "修改完成" : `修改失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
    } catch (e) {
      showToast(`修改失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
      // fetch settle 即代表服务端 run 已结束（含 400 等未进 run_workflow 的早失败），
      // 先于 WS run_end 复位无害且幂等；否则 WS 丢事件时面板永久锁死
      onRunEnd();
    }
  };

  const handleWriteback = async () => {
    onRunStart();
    try {
      const r = await api.writebackPatch(current.id);
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
      onFigureChanged();
      onRunEnd();
    }
  };

  return (
    <div className="ai-panel">
      <div className="ai-status">
        AI：
        {status === null ? "检测中…" : status.configured
          ? `${status.provider} / ${status.model}${status.mock ? "（mock）" : ""}`
          : `未配置${status.detail ? `（${status.detail}）` : ""}：仓库根放 config.json + .env（参考 config.example.json）`}
      </div>

      <section>
        <h4>指令修改 {selections.length > 0 && `（已附加 ${selections.length} 个选区元素）`}</h4>
        <textarea placeholder="例如：把选中的柱子改成主色蓝，字号统一 12" value={instruction}
                  onChange={(e) => setInstruction(e.target.value)} disabled={disabled} />
        <div>
          <button onClick={handleInstruct} disabled={disabled || !instruction.trim()}>执行修改</button>
          <button onClick={handleWriteback} disabled={disabled || patchOpCount === 0}>
            回写 patch（{patchOpCount} op）
          </button>
        </div>
      </section>

      <section>
        <h4>运行时间线</h4>
        {runEvents.length === 0 && <div className="hint">尚无 AI 运行</div>}
        <ul className="run-events">
          {runEvents.map((ev, i) => (
            <li key={i} className={`run-ev run-ev-${ev.phase}`}>
              {new Date(ev.at).toLocaleTimeString()} {ev.phase}
              {ev.node ? ` · ${ev.node}` : ""}
              {ev.detail ? ` · ${ev.detail}` : ""}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
