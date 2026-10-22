// 左栏：搜索 + 分组树（多级、拖拽入组）+ 扁平标签。删除均为两击确认。

import { useState } from "react";
import type { GroupInfo, TagInfo } from "../../types";

interface Props {
  groups: GroupInfo[];
  tags: TagInfo[];
  q: string;
  onSearch: (q: string) => void;
  activeGroupId: number | null;
  activeTagId: number | null;
  onSelectGroup: (id: number | null) => void;
  onSelectTag: (id: number | null) => void;
  onCreateGroup: (name: string, parentId: number | null) => void;
  onRenameGroup: (id: number, name: string) => void;
  onDeleteGroup: (id: number) => void;
  onDropItem: (itemId: string, groupId: number) => void;
  onCreateTag: (name: string) => void;
  onDeleteTag: (id: number) => void;
}

export function GroupSidebar(props: Props) {
  const [newGroup, setNewGroup] = useState("");
  const [newTag, setNewTag] = useState("");
  const roots = props.groups.filter((g) => g.parentId === null);

  return (
    <div className="gsidebar">
      <input
        type="text"
        className="search"
        placeholder="搜索图…"
        value={props.q}
        onChange={(e) => props.onSearch(e.target.value)}
      />

      <h2>分组</h2>
      <div className="group-node">
        <div
          className={`group-row ${props.activeGroupId === null ? "active" : ""}`}
          onClick={() => props.onSelectGroup(null)}
        >
          全部 / 未分组
        </div>
      </div>
      {roots.map((g) => (
        <GroupNode key={g.id} group={g} {...props} depth={0} />
      ))}
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <input
          type="text"
          placeholder="新建分组"
          value={newGroup}
          onChange={(e) => setNewGroup(e.target.value)}
        />
        <button
          className="small"
          disabled={!newGroup.trim()}
          onClick={() => {
            props.onCreateGroup(newGroup.trim(), null);
            setNewGroup("");
          }}
        >
          ＋
        </button>
      </div>

      <h2>标签</h2>
      {props.tags.map((t) => (
        <TagRow
          key={t.id}
          tag={t}
          active={props.activeTagId === t.id}
          onSelect={() => props.onSelectTag(props.activeTagId === t.id ? null : t.id)}
          onDelete={() => props.onDeleteTag(t.id)}
        />
      ))}
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <input
          type="text"
          placeholder="新建标签"
          value={newTag}
          onChange={(e) => setNewTag(e.target.value)}
        />
        <button
          className="small"
          disabled={!newTag.trim()}
          onClick={() => {
            props.onCreateTag(newTag.trim());
            setNewTag("");
          }}
        >
          ＋
        </button>
      </div>
    </div>
  );
}

function GroupNode(props: Props & { group: GroupInfo; depth: number }) {
  const { group } = props;
  const [renaming, setRenaming] = useState(false);
  const [addingChild, setAddingChild] = useState(false);
  const [name, setName] = useState(group.name);
  const [confirmDel, setConfirmDel] = useState(false);
  const [drop, setDrop] = useState(false);
  const kids = props.groups.filter((g) => g.parentId === group.id);

  return (
    <div className="group-node">
      <div
        className={`group-row ${props.activeGroupId === group.id ? "active" : ""} ${drop ? "drop" : ""}`}
        onClick={() => props.onSelectGroup(group.id)}
        draggable={false}
        onDragOver={(e) => {
          e.preventDefault();
          setDrop(true);
        }}
        onDragLeave={() => setDrop(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrop(false);
          const itemId = e.dataTransfer.getData("text/plain");
          if (itemId) props.onDropItem(itemId, group.id);
        }}
      >
        📁 {renaming ? (
          <input
            autoFocus
            value={name}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              setRenaming(false);
              if (name.trim() && name !== group.name) props.onRenameGroup(group.id, name.trim());
            }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        ) : (
          <span>{group.name}</span>
        )}
        <span className="spacer" />
        <button className="gbtn" title="重命名" onClick={(e) => { e.stopPropagation(); setRenaming(true); }}>✎</button>
        <button className="gbtn" title="加子分组" onClick={(e) => { e.stopPropagation(); setAddingChild(true); }}>＋</button>
        <button
          className="gbtn"
          title="删除分组"
          onClick={(e) => {
            e.stopPropagation();
            if (confirmDel) props.onDeleteGroup(group.id);
            else {
              setConfirmDel(true);
              window.setTimeout(() => setConfirmDel(false), 2000);
            }
          }}
        >
          {confirmDel ? "确认?" : "🗑"}
        </button>
      </div>
      {addingChild && (
        <div className="group-kids">
          <input
            autoFocus
            placeholder="子分组名"
            onBlur={(e) => {
              if (e.target.value.trim()) props.onCreateGroup(e.target.value.trim(), group.id);
              setAddingChild(false);
            }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        </div>
      )}
      {kids.length > 0 && (
        <div className="group-kids">
          {kids.map((k) => (
            <GroupNode key={k.id} {...props} group={k} depth={props.depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function TagRow(props: { tag: TagInfo; active: boolean; onSelect: () => void; onDelete: () => void }) {
  const [confirmDel, setConfirmDel] = useState(false);
  return (
    <div className={`group-row ${props.active ? "active" : ""}`} onClick={props.onSelect}>
      🏷 <span>{props.tag.name}</span>
      <span className="spacer" />
      <button
        className="gbtn"
        onClick={(e) => {
          e.stopPropagation();
          if (confirmDel) props.onDelete();
          else {
            setConfirmDel(true);
            window.setTimeout(() => setConfirmDel(false), 2000);
          }
        }}
      >
        {confirmDel ? "确认?" : "🗑"}
      </button>
    </div>
  );
}
