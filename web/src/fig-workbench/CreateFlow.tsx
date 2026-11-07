// 建图流（吸收 figure-agent CreateDialog；独立应用只认一个工作目录 → 去掉图名/分组）。
// 三个入口：模板建图 / AI 造图（requirements+数据上传）/ AI 改造（脚本+数据）。

import { api, flattenItemFiles, type FlatFile } from "../shared/api";
import * as React from "react";
import type { AiRunResult, TemplateInfo } from "../shared/types";

const RESERVED = ["plot.py", "data.csv", "data_profile.json", "base.svg", "final.svg", "patch.json"];

type Tab = "template" | "ai" | "adapt";

interface Props {
  itemId: string;
  itemName: string;
  onCreated: (r: AiRunResult) => void;
  showToast: (msg: string, error?: boolean) => void;
}

export function CreateFlow(props: Props) {
  const [tab, setTab] = React.useState<Tab>("ai");
  const [templates, setTemplates] = React.useState<TemplateInfo[]>([]);
  const [template, setTemplate] = React.useState("");
  const [requirements, setRequirements] = React.useState("");
  const [dataFile, setDataFile] = React.useState<File | null>(null);
  const [scriptFile, setScriptFile] = React.useState<File | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  // 数据/脚本源：优先工作目录内已有文件（files 列表），没有再本地上传
  const [itemFiles, setItemFiles] = React.useState<FlatFile[] | null>(null);
  const [dataSrc, setDataSrc] = React.useState<"item" | "upload">("item");
  const [dataRel, setDataRel] = React.useState("");
  const [scriptRel, setScriptRel] = React.useState("");

  React.useEffect(() => {
    api
      .listTemplates()
      .then((ts) => {
        setTemplates(ts);
        if (ts[0]) setTemplate(ts[0].id);
      })
      .catch(() => undefined);
    api
      .listFiles()
      .then((tree) => {
        const files = flattenItemFiles(tree as any, RESERVED);
        setItemFiles(files);
        if (files.length === 0) setDataSrc("upload");
        setDataRel(files[0]?.rel ?? "");
        const py = files.find((f) => f.rel.toLowerCase().endsWith(".py"));
        setScriptRel(py?.rel ?? "");
      })
      .catch(() => setItemFiles([]));
  }, [props.itemId]);

  const useItemData = tab !== "template" && dataSrc === "item" && !!dataRel;
  const disabled =
    busy ||
    (tab === "template"
      ? !template
      : tab === "ai"
        ? !(useItemData || dataFile)
        : !((useItemData || dataFile) && (scriptRel || scriptFile)));

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      let r: AiRunResult;
      if (tab === "template") {
        // 模板快速路径：空 requirements → 服务端确定性建图（脚手架+渲染，无 LLM）
        r = await api.createFigure(props.itemId, "", template, null);
      } else if (tab === "ai" && (useItemData || dataFile)) {
        r = await api.createFigure(props.itemId, requirements, "", dataFile, useItemData ? dataRel : "");
      } else if (tab === "adapt" && (useItemData || dataFile) && (scriptRel || scriptFile)) {
        r = await api.adaptFigure(
          props.itemId,
          scriptFile,
          dataFile,
          requirements,
          scriptRel || "",
          useItemData ? dataRel : "",
        );
      } else {
        return;
      }
      if (r.ok) {
        props.showToast("图表已创建");
        props.onCreated(r);
      } else {
        setError(`创建失败：${(r.stderr || "").slice(0, 400) || "AI 运行未成功，可重试"}`);
      }
    } catch (e) {
      setError(`失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fig-create-flow">
      <h2>创建图表 · {props.itemName}</h2>
      <div className="fig-tabs">
        {(["ai", "adapt", "template"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "ai" ? "AI 造图" : t === "adapt" ? "AI 改造脚本" : "从模板"}
          </button>
        ))}
      </div>

      {tab !== "template" && (
        <label>
          数据来源
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
              <input
                type="radio"
                checked={dataSrc === "item"}
                disabled={!itemFiles || itemFiles.length === 0}
                onChange={() => setDataSrc("item")}
              />
              目录内文件
            </label>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
              <input type="radio" checked={dataSrc === "upload"} onChange={() => setDataSrc("upload")} />
              本地上传
            </label>
          </div>
        </label>
      )}
      {tab !== "template" && dataSrc === "item" && (
        <label>
          选择工作目录内的数据文件{itemFiles ? `（${itemFiles.length} 个）` : ""}
          {itemFiles && itemFiles.length > 0 ? (
            <select value={dataRel} onChange={(e) => setDataRel((e.target as HTMLSelectElement).value)}>
              {itemFiles.map((f) => (
                <option key={f.rel} value={f.rel}>
                  {f.rel}
                </option>
              ))}
            </select>
          ) : (
            <span className="fig-hint">工作目录里还没有文件。先把数据文件放进工作目录，或改用本地上传。</span>
          )}
        </label>
      )}
      {tab === "template" ? (
        <label>
          模板
          <select value={template} onChange={(e) => setTemplate((e.target as HTMLSelectElement).value)}>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <>
          <label>
            绘图要求（自然语言）
            <textarea
              placeholder="例如：用 dose 列做 x 轴、response 列画折线，标题「剂量响应」"
              value={requirements}
              onChange={(e) => setRequirements((e.target as HTMLTextAreaElement).value)}
            />
          </label>
          {dataSrc === "upload" && (
            <label>
              数据文件（csv/tsv/txt/xlsx/json）
              <input
                type="file"
                accept=".csv,.tsv,.txt,.xlsx,.xls,.json"
                onChange={(e) => setDataFile(e.target.files?.[0] ?? null)}
              />
            </label>
          )}
        </>
      )}
      {tab === "adapt" && (
        <>
          <label>
            现有绘图脚本（.py，matplotlib）
            {itemFiles && itemFiles.some((f) => f.rel.toLowerCase().endsWith(".py")) ? (
              <select value={scriptRel} onChange={(e) => setScriptRel((e.target as HTMLSelectElement).value)}>
                {itemFiles
                  .filter((f) => f.rel.toLowerCase().endsWith(".py"))
                  .map((f) => (
                    <option key={f.rel} value={f.rel}>
                      {f.rel}
                    </option>
                  ))}
              </select>
            ) : (
              <input type="file" accept=".py" onChange={(e) => setScriptFile(e.target.files?.[0] ?? null)} />
            )}
          </label>
          {scriptRel && (
            <div className="fig-hint">脚本取目录内 {scriptRel}；也可清空该文件后改用本地上传。</div>
          )}
        </>
      )}

      <div className="fig-hint">
        AI 造图会标准化数据为 data.csv、生成 plot.py（关键元素带 fa: 语义 id），渲染失败自动修复（最多 3 轮）。
      </div>

      {error && <div className="fig-create-error">{error}</div>}

      <div style={{ display: "flex", gap: 8 }}>
        <button className="primary" disabled={disabled} onClick={submit}>
          {busy ? "进行中…" : tab === "template" ? "创建" : "开始生成"}
        </button>
      </div>
    </div>
  );
}
