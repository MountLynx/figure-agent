// 左侧栏：项目/图列表 + 建图

import { useState } from "react";
import type { ProjectInfo, TemplateInfo } from "../types";

export interface SidebarProps {
  projects: ProjectInfo[];
  templates: TemplateInfo[];
  current: { project: string; figure: string } | null;
  onSelect: (project: string, figure: string) => void;
  onCreate: (project: string, name: string, template: string) => void;
  onRefresh: () => void;
}

export function Sidebar(props: SidebarProps) {
  const { projects, templates, current, onSelect, onCreate, onRefresh } = props;
  const [newName, setNewName] = useState("");
  const [template, setTemplate] = useState(templates[0]?.id ?? "bar-groups");
  const [project, setProject] = useState(projects[0]?.name ?? "demo");

  return (
    <div className="sidebar">
      <h2>
        图列表 <button className="small" onClick={onRefresh}>刷新</button>
      </h2>
      {projects.length === 0 && <div className="hint">工作区为空。用下方表单从模板建图。</div>}
      {projects.map((p) => (
        <div key={p.name}>
          <div style={{ fontWeight: 600, margin: "8px 4px 4px", fontSize: 13 }}>📁 {p.name}</div>
          {p.figures.map((f) => (
            <div
              key={f.name}
              className={`fig-item ${current?.project === p.name && current?.figure === f.name ? "active" : ""}`}
              onClick={() => onSelect(p.name, f.name)}
            >
              <span>📊 {f.name}</span>
              {f.opCount > 0 && <span className="badge">{f.opCount} 微调</span>}
            </div>
          ))}
        </div>
      ))}

      <h2>从模板建图</h2>
      <div className="section" style={{ padding: "0 4px", gap: 6 }}>
        <select value={project} onChange={(e) => setProject(e.target.value)}>
          {projects.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
          {projects.length === 0 && <option value="demo">demo</option>}
        </select>
        <select value={template} onChange={(e) => setTemplate(e.target.value)}>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
            </option>
          ))}
        </select>
        <div style={{ display: "flex", gap: 6 }}>
          <input
            type="text"
            placeholder="图名称"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button
            className="primary"
            disabled={!newName.trim()}
            onClick={() => {
              onCreate(project.trim() || "demo", newName.trim(), template);
              setNewName("");
            }}
          >
            创建
          </button>
        </div>
      </div>
    </div>
  );
}
