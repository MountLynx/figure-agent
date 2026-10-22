// AI 面板：造图/改造表单 + 选区指令 + 回写 + run 事件时间线。
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AiStatus, AiRunResult, ProjectInfo, RunEvent, SelectionJSON } from "../types";

interface Props {
  projects: ProjectInfo[];
  current: { project: string; figure: string } | null;
  selections: SelectionJSON[];
  patchOpCount: number;
  runEvents: RunEvent[];
  runActive: boolean;
  wsOnline: boolean;
  onRunStart: () => void;
  onRunEnd: () => void;
  onFigureReady: (project: string, figure: string) => void;
  onFigureChanged: () => void;
  showToast: (msg: string, error?: boolean) => void;
}

export function AIPanel(props: Props) {
  const { projects, current, selections, patchOpCount, runEvents, runActive, wsOnline,
          onRunStart, onRunEnd, onFigureReady, onFigureChanged, showToast } = props;
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [project, setProject] = useState("");
  const [name, setName] = useState("");
  const [requirements, setRequirements] = useState("");
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [scriptFile, setScriptFile] = useState<File | null>(null);
  const [instruction, setInstruction] = useState("");
  const [showAdapt, setShowAdapt] = useState(false);

  // 取状态可复调：WS 重连（wsOnline 翻转）时重试——首次失败会永久停在"未配置"，
  // 重连后再取一次可自愈。catch 时仍 setStatus（configured:false），UI 显示未配置但保留可重试。
  const refreshStatus = () => {
    api.aiStatus().then(setStatus).catch(() => setStatus({ configured: false, provider: "", model: "", mock: false }));
  };

  useEffect(() => {
    refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsOnline]);

  useEffect(() => {
    if (!project && projects.length > 0) setProject(projects[0].name);
  }, [projects, project]);

  const disabled = runActive || !status?.configured;

  const handleCreate = async () => {
    if (!project || !name || !dataFile) return;
    onRunStart();
    try {
      const r: AiRunResult = await api.createFigureAi(project, name, requirements, dataFile);
      showToast(r.ok ? `造图完成（${r.rounds} 轮）` : `造图失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
      onFigureReady(project, name);
    } catch (e) {
      showToast(`造图失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
      // fetch settle 即代表服务端 run 已结束（含 400 等未进 run_workflow 的早失败），
      // 先于 WS run_end 复位无害且幂等；否则 WS 丢事件时面板永久锁死
      onRunEnd();
    }
  };

  const handleAdapt = async () => {
    if (!project || !name || !dataFile || !scriptFile) return;
    onRunStart();
    try {
      const r = await api.adaptFigure(project, name, requirements, dataFile, scriptFile);
      showToast(r.ok ? `改造完成（${r.rounds} 轮）` : `改造失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
      onFigureReady(project, name);
    } catch (e) {
      showToast(`改造失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
      onRunEnd();
    }
  };

  const handleInstruct = async () => {
    if (!current || !instruction.trim()) return;
    onRunStart();
    try {
      const payload = selections.length === 1 ? selections[0] : selections;
      const r = await api.instruct(current.project, current.figure, instruction, payload);
      showToast(r.ok ? "修改完成" : `修改失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
    } catch (e) {
      showToast(`修改失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
      onRunEnd();
    }
  };

  const handleWriteback = async () => {
    if (!current) return;
    onRunStart();
    try {
      const r = await api.writebackPatch(current.project, current.figure);
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
        <h4>AI 造图</h4>
        <select value={project} onChange={(e) => setProject(e.target.value)} disabled={disabled}>
          {projects.map((p) => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
        <input placeholder="图名" value={name} onChange={(e) => setName(e.target.value)} disabled={disabled} />
        <textarea placeholder="绘图要求（自然语言）" value={requirements}
                  onChange={(e) => setRequirements(e.target.value)} disabled={disabled} />
        <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xls,.json"
               onChange={(e) => setDataFile(e.target.files?.[0] ?? null)} disabled={disabled} />
        <button onClick={handleCreate} disabled={disabled || !name || !dataFile}>生成图表</button>
        <button className="link" onClick={() => setShowAdapt((v) => !v)}>
          {showAdapt ? "收起脚本改造" : "改为脚本改造（数据 + 现成脚本）"}
        </button>
        {showAdapt && (
          <div className="adapt-form">
            <input type="file" accept=".py" onChange={(e) => setScriptFile(e.target.files?.[0] ?? null)} disabled={disabled} />
            <button onClick={handleAdapt} disabled={disabled || !name || !dataFile || !scriptFile}>改造脚本</button>
          </div>
        )}
      </section>

      {current && (
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
      )}

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
