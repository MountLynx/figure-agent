// 类型管理：字段增删改标签；新建类型（预设型保护由服务端兜底）。

import { useState } from "react";
import { api } from "../../api";
import type { TypeInfo } from "../../types";

interface Props {
  types: TypeInfo[];
  onChanged: () => void;
  showToast: (msg: string) => void;
}

const FIELD_TYPES = ["text", "checkbox", "date", "number", "dropdown", "item"] as const;

export function TypePanel(props: Props) {
  const [newType, setNewType] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [fieldKind, setFieldKind] = useState<string>("text");

  return (
    <div className="detail">
      {props.types.map((t) => (
        <section key={t.id}>
          <h4>{t.icon === "chart-bar" ? "📊" : "📄"} {t.name} {t.id <= 2 && <span className="hint">（预设）</span>}</h4>
          {t.fields.map((f) => (
            <div key={f.id} className="figrow" style={{ padding: "4px 8px" }}>
              <span>{f.name}</span>
              <span className="meta">{f.fieldType}</span>
              <span className="spacer" />
              <button
                className="small"
                onClick={() =>
                  api.removeField(t.id, f.id).then(props.onChanged).catch((e) => props.showToast((e as Error).message))}
              >
                删除
              </button>
            </div>
          ))}
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <input
              placeholder="新字段名"
              value={fieldName}
              onChange={(e) => setFieldName(e.target.value)}
            />
            <select value={fieldKind} onChange={(e) => setFieldKind(e.target.value)}>
              {FIELD_TYPES.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <button
              className="small"
              disabled={!fieldName.trim()}
              onClick={() =>
                api.addField(t.id, { name: fieldName.trim(), fieldType: fieldKind })
                  .then(() => setFieldName(""))
                  .then(props.onChanged)
                  .catch((e) => props.showToast((e as Error).message))}
            >
              ＋ 字段
            </button>
          </div>
          {t.id > 2 && (
            <button
              className="small"
              style={{ marginTop: 6 }}
              onClick={() => api.deleteType(t.id).then(props.onChanged).catch((e) => props.showToast((e as Error).message))}
            >
              删除该类型
            </button>
          )}
        </section>
      ))}
      <section>
        <h4>新建类型</h4>
        <div style={{ display: "flex", gap: 6 }}>
          <input placeholder="类型名" value={newType} onChange={(e) => setNewType(e.target.value)} />
          <button
            className="small"
            disabled={!newType.trim()}
            onClick={() => api.createType({ name: newType.trim() }).then(() => setNewType("")).then(props.onChanged)}
          >
            创建
          </button>
        </div>
      </section>
    </div>
  );
}
