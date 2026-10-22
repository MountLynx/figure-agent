// 右栏详情：行内重命名、按「图」字段渲染属性表单、分组/标签 chips、文件树。

import { useEffect, useState } from "react";
import { api } from "../../api";
import type { FileInfo, GroupInfo, ItemInfo, TagInfo, TypeInfo } from "../../types";

interface Props {
  item: ItemInfo | null;
  groups: GroupInfo[];
  tags: TagInfo[];
  types: TypeInfo[];
  files: FileInfo[];
  onChanged: () => void;
  onOpen: (item: ItemInfo) => void;
  showToast: (msg: string) => void;
}

export function DetailPanel(props: Props) {
  const { item } = props;
  const figureType = props.types.find((t) => t.name === "图");
  const [props_, setProps] = useState<Record<string, string>>({});

  useEffect(() => {
    setProps(item?.properties ?? {});
    // 仅在切换条目时同步：refresh（绑定/解绑等）不应冲掉未保存的属性输入
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id]);

  if (!item) {
    return (
      <div className="detail">
        <div className="hint">选中一张图查看详情。</div>
      </div>
    );
  }

  const saveProps = () => {
    api.patchItem(item.id, { properties: props_ })
      .then(props.onChanged)
      .then(() => props.showToast("属性已保存"))
      .catch((e) => props.showToast(`保存失败：${(e as Error).message}`));
  };

  const groupNames = item.groupIds
    .map((gid) => props.groups.find((g) => g.id === gid)?.name ?? `#${gid}`);
  const addableGroups = props.groups.filter((g) => !item.groupIds.includes(g.id));
  const addableTags = props.tags.filter((t) => !item.tags.includes(t.name));

  return (
    <div className="detail">
      <h3 style={{ margin: 0 }}>{item.name}</h3>
      <div className="hint" title={item.id}>{item.id} · 更新 {item.updatedAt.slice(0, 19)}</div>
      <button className="primary" onClick={() => props.onOpen(item)}>打开编辑器</button>

      <section>
        <h4>属性</h4>
        {(figureType?.fields ?? []).map((f) => (
          <label key={f.id} style={{ display: "block", marginBottom: 6 }}>
            {f.label || f.name}
            <input
              type="text"
              style={{ width: "100%" }}
              value={props_[f.name] ?? ""}
              onChange={(e) => setProps({ ...props_, [f.name]: e.target.value })}
            />
          </label>
        ))}
        <button className="small" onClick={saveProps}>保存属性</button>
      </section>

      <section>
        <h4>分组</h4>
        <div className="chips">
          {groupNames.map((name, i) => (
            <span key={i} className="chip">
              {name}
              <button
                onClick={() =>
                  api.unbindItemGroup(item.id, item.groupIds[i]).then(props.onChanged)}
              >
                ×
              </button>
            </span>
          ))}
          {addableGroups.map((g) => (
            <button key={g.id} className="small" onClick={() => api.bindItemGroup(item.id, g.id).then(props.onChanged)}>
              ＋{g.name}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h4>标签</h4>
        <div className="chips">
          {item.tags.map((name) => {
            const tag = props.tags.find((t) => t.name === name);
            return (
              <span key={name} className="chip">
                {name}
                <button onClick={() => tag && api.unbindItemTag(item.id, tag.id).then(props.onChanged)}>×</button>
              </span>
            );
          })}
          {addableTags.map((t) => (
            <button key={t.id} className="small" onClick={() => api.bindItemTag(item.id, t.id).then(props.onChanged)}>
              ＋{t.name}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h4>文件</h4>
        <div className="filetree">
          {props.files.map((f) => (
            <div key={f.path} style={{ paddingLeft: (f.path.split("/").length - 1) * 14 }}>
              {f.isDir ? "📁" : "📄"} {f.path.split("/").pop()}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
