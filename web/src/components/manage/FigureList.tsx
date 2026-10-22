// 中栏：图列表。行内重命名、两击删除、双击打开；行可拖拽入分组。

import { useState } from "react";
import type { ItemInfo } from "../../types";

interface Props {
  items: ItemInfo[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpen: (item: ItemInfo) => void;
  onRename: (item: ItemInfo, name: string) => void;
  onDelete: (item: ItemInfo) => void;
}

export function FigureList(props: Props) {
  return (
    <div className="figlist">
      {props.items.length === 0 && <div className="hint">没有图。点右上「＋ 新建图」。</div>}
      {props.items.map((item) => (
        <FigRow key={item.id} item={item} {...props} />
      ))}
    </div>
  );
}

function FigRow(props: {
  item: ItemInfo;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpen: (item: ItemInfo) => void;
  onRename: (item: ItemInfo, name: string) => void;
  onDelete: (item: ItemInfo) => void;
}) {
  const { item } = props;
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(item.name);
  const [confirmDel, setConfirmDel] = useState(false);

  return (
    <div
      className={`figrow ${props.selectedId === item.id ? "active" : ""}`}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", item.id)}
      onClick={() => props.onSelect(item.id)}
      onDoubleClick={() => props.onOpen(item)}
    >
      <span title={item.id}>📊</span>
      {renaming ? (
        <input
          autoFocus
          value={name}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            setRenaming(false);
            if (name.trim() && name !== item.name) props.onRename(item, name.trim());
          }}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        />
      ) : (
        <b>{item.name}</b>
      )}
      {item.tags.map((t) => (
        <span key={t} className="chip">{t}</span>
      ))}
      {(item.opCount ?? 0) > 0 && <span className="chip">{item.opCount} 微调</span>}
      <span className="spacer" />
      <span className="meta">{item.hasBase === false ? "未渲染" : ""}</span>
      <button className="small" onClick={(e) => { e.stopPropagation(); props.onOpen(item); }}>打开</button>
      <button className="small" onClick={(e) => { e.stopPropagation(); setRenaming(true); }}>重命名</button>
      <button
        className="small"
        onClick={(e) => {
          e.stopPropagation();
          if (confirmDel) props.onDelete(item);
          else {
            setConfirmDel(true);
            window.setTimeout(() => setConfirmDel(false), 2000);
          }
        }}
      >
        {confirmDel ? "确认删除?" : "删除"}
      </button>
    </div>
  );
}
