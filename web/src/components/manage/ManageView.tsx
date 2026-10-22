// 管理视图：Index 风格三栏（左分组+标签 / 中图列表 / 右详情·类型）+ 顶栏。

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import type { FileInfo, GroupInfo, ItemInfo, TagInfo, TypeInfo } from "../../types";
import { CreateDialog } from "./CreateDialog";
import { DetailPanel } from "./DetailPanel";
import { FigureList } from "./FigureList";
import { GroupSidebar } from "./GroupSidebar";
import { TypePanel } from "./TypePanel";

interface Props {
  onOpen: (id: string, name: string) => void;
}

export function ManageView({ onOpen }: Props) {
  const [items, setItems] = useState<ItemInfo[]>([]);
  const [groups, setGroups] = useState<GroupInfo[]>([]);
  const [tags, setTags] = useState<TagInfo[]>([]);
  const [types, setTypes] = useState<TypeInfo[]>([]);
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [q, setQ] = useState("");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [tagId, setTagId] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<"detail" | "types">("detail");
  const [creating, setCreating] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2600);
  }, []);

  const reqSeq = useRef(0);
  const refresh = useCallback(() => {
    const seq = ++reqSeq.current;
    api.listItems({ q, groupId, tagId }).then((list) => {
      if (seq === reqSeq.current) setItems(list);
    }).catch(() => undefined);
  }, [q, groupId, tagId]);

  const refreshMeta = useCallback(() => {
    api.listGroups().then(setGroups).catch(() => undefined);
    api.listTags().then(setTags).catch(() => undefined);
    api.listTypes().then(setTypes).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);
  useEffect(() => {
    refreshMeta();
    api.getRepoState().then((s) => {
      const t = s.theme === "dark" ? "dark" : "light";
      document.documentElement.classList.toggle("dark", t === "dark");
      setTheme(t);
    }).catch(() => undefined);
  }, [refreshMeta]);

  useEffect(() => {
    if (!selected) {
      setFiles([]);
      return;
    }
    let stale = false;
    api.listFiles(selected).then((f) => {
      if (!stale) setFiles(f);
    }).catch(() => {
      if (!stale) setFiles([]);
    });
    return () => {
      stale = true;
    };
  }, [selected]);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    setTheme(next);
    api.putRepoState({ theme: next }).catch(() => undefined);
  };

  const selectedItem = items.find((i) => i.id === selected) ?? null;

  return (
    <div className="manage">
      <div className="topbar">
        <b>figure-agent</b>
        <span className="hint">{items.length} 张图</span>
        <span className="spacer" />
        <button className="primary" onClick={() => setCreating(true)}>＋ 新建图</button>
        <button onClick={toggleTheme}>{theme === "dark" ? "亮色" : "暗色"}</button>
      </div>
      <GroupSidebar
        groups={groups}
        tags={tags}
        q={q}
        onSearch={setQ}
        activeGroupId={groupId}
        activeTagId={tagId}
        onSelectGroup={(gid) => { setGroupId(gid); setTagId(null); }}
        onSelectTag={(tid) => { setTagId(tid); setGroupId(null); }}
        onCreateGroup={(name, parentId) =>
          api.createGroup({ name, parentId }).then(refreshMeta).then(refresh)}
        onRenameGroup={(id, name) => api.updateGroup(id, { name }).then(refreshMeta)}
        onDeleteGroup={(id) =>
          api.deleteGroup(id)
            .then(refreshMeta)
            .then(() => {
              if (groupId === id) setGroupId(null);
              return refresh();
            })}
        onDropItem={(itemId, gid) =>
          api.bindItemGroup(itemId, gid).then(refresh).then(() => showToast("已移入分组"))}
        onCreateTag={(name) => api.createTag({ name }).then(refreshMeta)}
        onDeleteTag={(id) => api.deleteTag(id).then(refreshMeta)}
      />
      <FigureList
        items={items}
        selectedId={selected}
        onSelect={setSelected}
        onOpen={(item) => onOpen(item.id, item.name)}
        onRename={(item, name) => api.patchItem(item.id, { name }).then(refresh)}
        onDelete={(item) => api.deleteItem(item.id).then(refresh).then(refreshMeta)}
      />
      <div className="rightcol">
        <div className="righttabs">
          <button className={rightTab === "detail" ? "active" : ""} onClick={() => setRightTab("detail")}>详情</button>
          <button className={rightTab === "types" ? "active" : ""} onClick={() => setRightTab("types")}>类型</button>
        </div>
        {rightTab === "detail" ? (
          <DetailPanel
            item={selectedItem}
            groups={groups}
            tags={tags}
            types={types}
            files={files}
            onChanged={refresh}
            onOpen={(item) => onOpen(item.id, item.name)}
            showToast={showToast}
          />
        ) : (
          <TypePanel types={types} onChanged={refreshMeta} showToast={showToast} />
        )}
      </div>
      {creating && (
        <CreateDialog
          groups={groups}
          onClose={() => setCreating(false)}
          onCreated={(item, open) => {
            setCreating(false);
            refresh();
            refreshMeta();
            if (open) onOpen(item.id, item.name);
          }}
          showToast={showToast}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
