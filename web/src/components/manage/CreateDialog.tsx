// 新建图对话框：模板 / AI 造图 / AI 改造 三个 tab。

import { useEffect, useState } from "react";
import { api } from "../../api";
import type { GroupInfo, TemplateInfo } from "../../types";

interface Props {
  groups: GroupInfo[];
  onClose: () => void;
  onCreated: (item: { id: string; name: string }, open: boolean) => void;
  showToast: (msg: string) => void;
}

type Tab = "template" | "ai" | "adapt";

export function CreateDialog(props: Props) {
  const [tab, setTab] = useState<Tab>("template");
  const [name, setName] = useState("");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [template, setTemplate] = useState("bar-groups");
  const [requirements, setRequirements] = useState("");
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [scriptFile, setScriptFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listTemplates().then((ts) => {
      setTemplates(ts);
      if (ts[0]) setTemplate(ts[0].id);
    }).catch(() => undefined);
  }, []);

  const disabled = busy || !name.trim() || (tab !== "template" && !dataFile);

  const finish = (r: { id?: string; ok: boolean; stderr: string }) => {
    if (r.id) {
      props.onCreated({ id: r.id, name: name.trim() }, r.ok);
      if (!r.ok) props.showToast(`已建图但渲染/AI 失败：${r.stderr.slice(0, 120)}`);
    } else {
      props.showToast(`失败：${r.stderr.slice(0, 160)}`);
    }
  };

  const submit = async () => {
    setBusy(true);
    try {
      if (tab === "template") {
        finish(await api.createItem({ name: name.trim(), template, groupId }));
      } else if (tab === "ai" && dataFile) {
        finish(await api.createFigureAi(name.trim(), requirements, groupId, dataFile));
      } else if (tab === "adapt" && dataFile && scriptFile) {
        finish(await api.adaptFigure(name.trim(), requirements, groupId, dataFile, scriptFile));
      }
    } catch (e) {
      props.showToast(`失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" onClick={props.onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="righttabs">
          {(["template", "ai", "adapt"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
              {t === "template" ? "模板" : t === "ai" ? "AI 造图" : "AI 改造"}
            </button>
          ))}
        </div>
        <label>
          图名
          <input style={{ width: "100%" }} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          分组
          <select
            value={groupId ?? ""}
            onChange={(e) => setGroupId(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">未分组</option>
            {props.groups.map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
        </label>
        {tab === "template" && (
          <label>
            模板
            <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
          </label>
        )}
        {tab !== "template" && (
          <>
            <textarea
              placeholder="绘图要求（自然语言）"
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
            />
            <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xls,.json"
                   onChange={(e) => setDataFile(e.target.files?.[0] ?? null)} />
          </>
        )}
        {tab === "adapt" && (
          <input type="file" accept=".py"
                 onChange={(e) => setScriptFile(e.target.files?.[0] ?? null)} />
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <button className="primary" disabled={disabled} onClick={submit}>
            {busy ? "进行中…" : tab === "template" ? "创建" : "开始生成"}
          </button>
          <button onClick={props.onClose}>取消</button>
        </div>
      </div>
    </div>
  );
}
