// EngineApi 适配器：把 @index/shell-react 的引擎协议映射到 figure-agent REST。
// shell 的协议对象（snake_case）在此由 REST 的驼峰 DTO 拼装；REST 不支持的
// 命令显式抛错（AppShell/stores 对部分命令自带 catch）。

import type {
  EngineApi,
  Field,
  FileNode,
  Group,
  GroupedItems,
  Item,
  ItemDetail,
  ItemType,
  Tag,
} from "@index/protocol";
import type { FieldInfo, FileInfo, GroupInfo, ItemInfo, TagInfo, TypeInfo } from "../types";

// ---- fetch 小工具（与 api.ts 同一套 json/req 惯用法，映射保持显式）----

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail: unknown = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    // FastAPI 校验错误的 detail 是数组，字符串化避免 "[object Object]"
    const text = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json() as Promise<T>;
}

function req(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

const get = <T,>(url: string) => fetch(url).then((r) => json<T>(r));
const post = <T,>(url: string, body?: unknown) => fetch(url, req("POST", body)).then((r) => json<T>(r));
const patch = <T,>(url: string, body?: unknown) => fetch(url, req("PATCH", body)).then((r) => json<T>(r));
const put = <T,>(url: string, body?: unknown) => fetch(url, req("PUT", body)).then((r) => json<T>(r));
const del = <T,>(url: string) => fetch(url, { method: "DELETE" }).then((r) => json<T>(r));

const unsupported = (method: string) => async () => {
  throw new Error(`shell dogfood: ${method} 不支持`);
};

// ---- 类型缓存：typeName → type_id 解析依赖 /api/types，类型变更后失效 ----

let typesPromise: Promise<TypeInfo[]> | null = null;

function loadTypes(): Promise<TypeInfo[]> {
  if (!typesPromise) {
    typesPromise = get<TypeInfo[]>("/api/types").catch((e) => {
      typesPromise = null;
      throw e;
    });
  }
  return typesPromise;
}

function invalidateTypes() {
  typesPromise = null;
}

// ---- 映射：figure-agent DTO → 协议对象 ----

// 注意：未知 typeName 会伪装成第一个类型（静默串型的隐患）；当前 shell 侧只有
// 受保护的 figure 单类型，此回退兜底可接受——新增可见类型时需重审
function resolveTypeIdSync(typeName: string, types: TypeInfo[]): number {
  const found = types.find((t) => t.name === typeName);
  return found?.id ?? types[0]?.id ?? 0;
}

function mapItem(info: ItemInfo, types: TypeInfo[]): Item {
  return {
    id: info.id,
    name: info.name,
    type_id: resolveTypeIdSync(info.typeName, types),
    properties: info.properties,
    namespace: "",
    created_at: info.createdAt,
    updated_at: info.updatedAt,
  };
}

function mapField(f: FieldInfo, typeId: number): Field {
  return {
    id: f.id,
    type_id: typeId,
    name: f.name,
    field_type: f.fieldType,
    icon: "",
    position: f.position,
    label: f.label,
    options: f.options,
  };
}

function mapType(type: TypeInfo): ItemType {
  return {
    id: type.id,
    name: type.name,
    icon: type.icon,
    namespace: "",
    fields: type.fields.map((f) => mapField(f, type.id)),
  };
}

function mapTag(t: TagInfo): Tag {
  return { id: t.id, name: t.name, namespace: "" };
}

function mapGroup(g: GroupInfo): Group {
  return {
    id: g.id,
    parent_id: g.parentId,
    name: g.name,
    position: g.position,
    bound_item_id: g.boundItemId != null ? String(g.boundItemId) : null,
    children: [],
  };
}

function buildGroupTree(flat: GroupInfo[]): Group[] {
  const nodes = new Map<number, Group>(flat.map((g) => [g.id, mapGroup(g)]));
  const roots: Group[] = [];
  for (const g of flat) {
    const node = nodes.get(g.id)!;
    const parent = g.parentId != null ? nodes.get(g.parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function flattenGroups(tree: Group[]): Map<number, Group> {
  const byId = new Map<number, Group>();
  const walk = (nodes: Group[]) => {
    for (const n of nodes) {
      byId.set(n.id, n);
      walk(n.children);
    }
  };
  walk(tree);
  return byId;
}

function buildFileTree(files: FileInfo[]): FileNode {
  const root: FileNode = { name: "", is_dir: true, children: [] };
  for (const f of files) {
    const segments = f.path.split(/[\\/]/).filter(Boolean);
    let cur = root;
    segments.forEach((name, i) => {
      let child = cur.children.find((c) => c.name === name);
      if (!child) {
        child = { name, is_dir: i < segments.length - 1 ? true : f.isDir, children: [] };
        cur.children.push(child);
      }
      cur = child;
    });
  }
  const sort = (node: FileNode) => {
    node.children.sort((a, b) =>
      a.is_dir === b.is_dir ? a.name.localeCompare(b.name) : a.is_dir ? -1 : 1
    );
    node.children.forEach(sort);
  };
  sort(root);
  return root;
}

// ---- ItemDetail 合成：REST 无单条详情端点，由列表 + 分组/标签/文件拼装 ----

interface DetailCtx {
  types: TypeInfo[];
  groupById: Map<number, Group>;
  tags: TagInfo[];
}

function buildDetail(info: ItemInfo, ctx: DetailCtx, files: FileNode): ItemDetail {
  const type = ctx.types.find((t) => t.name === info.typeName);
  const itemType = mapType(
    type ?? ctx.types[0] ?? { id: 0, name: info.typeName, icon: "", fields: [] }
  );
  return {
    item: mapItem(info, ctx.types),
    item_type: itemType,
    groups: info.groupIds
      .map((gid) => ctx.groupById.get(gid))
      .filter((g): g is Group => g != null),
    tags: info.tags
      .map((name) => ctx.tags.find((t) => t.name === name))
      .filter((t): t is TagInfo => t != null)
      .map(mapTag),
    files,
    bound_groups: [],
  };
}

async function fetchFiles(id: string): Promise<FileNode> {
  return buildFileTree(await get<FileInfo[]>(`/api/figures/${id}/files`));
}

async function loadDetailCtx(): Promise<{ ctx: DetailCtx; infos: ItemInfo[]; flat: GroupInfo[] }> {
  const [infos, types, groups, tags] = await Promise.all([
    get<ItemInfo[]>("/api/items"),
    loadTypes(),
    get<GroupInfo[]>("/api/groups"),
    get<TagInfo[]>("/api/tags"),
  ]);
  return {
    ctx: { types, groupById: flattenGroups(buildGroupTree(groups)), tags },
    infos,
    flat: groups,
  };
}

// ---- 适配器本体 ----

async function repoInfo() {
  const info = await get<{ path: string; itemCount: number; dbVersion: number }>("/api/repo/info");
  return { path: info.path, item_count: info.itemCount, db_version: info.dbVersion };
}

async function listInfos(groupId: number | null, tagId: number | null): Promise<ItemInfo[]> {
  const sp = new URLSearchParams();
  if (groupId != null) sp.set("groupId", String(groupId));
  if (tagId != null) sp.set("tagId", String(tagId));
  const qs = sp.toString();
  return get<ItemInfo[]>(`/api/items${qs ? `?${qs}` : ""}`);
}

function typeFilter(typeIds: number[] | null, types: TypeInfo[]) {
  if (!typeIds) return () => true;
  const wanted = new Set(typeIds);
  return (info: ItemInfo) => wanted.has(resolveTypeIdSync(info.typeName, types));
}

export const engineApi: EngineApi = {
  items: {
    async list(groupId, tagId, typeIds) {
      const [infos, types] = await Promise.all([listInfos(groupId, tagId), loadTypes()]);
      const keep = typeFilter(typeIds, types);
      return infos.filter(keep).map((i) => mapItem(i, types));
    },

    async listUngrouped(typeIds) {
      const [infos, types] = await Promise.all([listInfos(null, null), loadTypes()]);
      const keep = typeFilter(typeIds, types);
      return infos.filter((i) => i.groupIds.length === 0 && keep(i)).map((i) => mapItem(i, types));
    },

    async listTree(groupId, tagId, typeIds, _filter) {
      const { ctx, infos, flat } = await loadDetailCtx();
      // tagId 过滤走标签名（ItemInfo.tags 存名字）；未知标签与未知分组一样大声失败
      const tagInfo = tagId != null ? ctx.tags.find((t) => t.id === tagId) : null;
      if (tagId != null && !tagInfo) throw new Error(`shell dogfood: 标签 ${tagId} 不存在`);
      const keep = typeFilter(typeIds, ctx.types);
      const tagOk = (i: ItemInfo) => (tagInfo ? i.tags.includes(tagInfo.name) : true);

      // 以 groupId 为根的子树
      const tree = buildGroupTree(flat);
      const findRoot = (nodes: Group[]): Group | null => {
        for (const n of nodes) {
          if (n.id === groupId) return n;
          const found = findRoot(n.children);
          if (found) return found;
        }
        return null;
      };
      const root = findRoot(tree);
      if (!root) throw new Error(`shell dogfood: 分组 ${groupId} 不存在`);

      // 组 → 条目（bound_item 不吃 tag/type 过滤）
      const itemsByGroup = new Map<number, ItemInfo[]>();
      for (const i of infos) {
        if (!keep(i) || !tagOk(i)) continue;
        for (const gid of i.groupIds) {
          const list = itemsByGroup.get(gid) ?? [];
          list.push(i);
          itemsByGroup.set(gid, list);
        }
      }

      // 需要合成详情的条目（组成员 + 各组 bound_item），文件一次并发拉齐
      const byId = new Map(infos.map((i) => [i.id, i]));
      const wantedIds = new Set<string>();
      const collect = (node: Group) => {
        for (const i of itemsByGroup.get(node.id) ?? []) wantedIds.add(i.id);
        if (node.bound_item_id) wantedIds.add(node.bound_item_id);
        node.children.forEach(collect);
      };
      collect(root);
      const filesById = new Map<string, FileNode>();
      await Promise.all(
        [...wantedIds].map(async (id) => {
          const info = byId.get(id);
          if (!info) return;
          // 单个条目缺图目录不应拖垮整个分组视图：退化为空文件树
          filesById.set(id, await fetchFiles(id).catch(() => ({ name: "", is_dir: true, children: [] })));
        })
      );
      const detailOf = (id: string): ItemDetail | null => {
        const info = byId.get(id);
        const files = filesById.get(id);
        return info && files ? buildDetail(info, ctx, files) : null;
      };

      const build = (node: Group, depth: number): GroupedItems => ({
        group_id: node.id,
        group_name: node.name,
        depth,
        bound_item: node.bound_item_id ? detailOf(node.bound_item_id) : null,
        items: (itemsByGroup.get(node.id) ?? [])
          .map((i) => detailOf(i.id))
          .filter((d): d is ItemDetail => d != null),
        children: node.children.map((c) => build(c, depth + 1)),
      });
      return build(root, 0);
    },

    async get(id) {
      const { ctx, infos } = await loadDetailCtx();
      const info = infos.find((i) => i.id === id);
      if (!info) throw new Error(`shell dogfood: 条目 ${id} 不存在`);
      return buildDetail(info, ctx, await fetchFiles(id));
    },

    listBacklinks: async () => [],
    listSubRepos: async () => ({}),

    async create(typeId, name) {
      // 服务端无模板时不渲染、返回 ok:false + 空 stderr，但条目已建（store.py）——
      // 不能当失败抛，否则 NewItemDialog 无 catch + 条目已存在的重复数据陷阱
      const created = await post<{ id: string; name: string; ok: boolean; stderr: string }>("/api/items", {
        name,
        origin: "shell",
      });
      if (!created.ok) console.warn(`shell dogfood: 条目 ${created.id} ok:false stderr=${created.stderr}`);
      // REST 不接收 type：按 id 回查列表解析 type_id，缺失时回退请求的 typeId / 首个类型
      const [infos, types] = await Promise.all([listInfos(null, null), loadTypes()]);
      const info = infos.find((i) => i.id === created.id);
      if (info) return mapItem(info, types);
      return {
        id: created.id,
        name: created.name,
        type_id: typeId || types[0]?.id || 0,
        properties: {},
        namespace: "",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
    },

    async update(id, name, properties) {
      // properties 原样透传（协议值允许非字符串，服务端 ItemPatch.properties 是裸
      // dict，json.dumps 落库）——不在这里强行收窄成 Record<string, string>
      const body: { name?: string; properties?: Record<string, unknown> } = {};
      if (name != null) body.name = name;
      if (properties != null) body.properties = properties;
      const info = await patch<ItemInfo>(`/api/items/${id}`, body);
      return mapItem(info, await loadTypes());
    },

    remove: async (id) => {
      await del(`/api/items/${id}`);
    },

    changeType: unsupported("items.changeType"),
    query: unsupported("items.query"),
    createFolder: unsupported("items.createFolder"),
    hasFolder: unsupported("items.hasFolder"),
    openFolder: unsupported("items.openFolder"),
    createSubRepo: unsupported("items.createSubRepo"),
    deleteSubRepo: unsupported("items.deleteSubRepo"),
    migrateToSubRepo: unsupported("items.migrateToSubRepo"),
  },

  groups: {
    async list() {
      return buildGroupTree(await get<GroupInfo[]>("/api/groups"));
    },

    async create(name, parentId) {
      return mapGroup(await post<GroupInfo>("/api/groups", { name, parentId }));
    },

    async update(id, name) {
      return mapGroup(await patch<GroupInfo>(`/api/groups/${id}`, name != null ? { name } : {}));
    },

    remove: async (id) => {
      await del(`/api/groups/${id}`);
    },

    async move(id, parentId, position) {
      await patch(`/api/groups/${id}`, { parentId, position });
    },

    addItem: async (itemId, groupId) => {
      await post(`/api/items/${itemId}/groups`, { id: groupId });
    },

    removeItem: async (itemId, groupId) => {
      await del(`/api/items/${itemId}/groups?id=${groupId}`);
    },

    setBoundItem: unsupported("groups.setBoundItem"),
    clearBoundItem: unsupported("groups.clearBoundItem"),
  },

  tags: {
    async list() {
      return (await get<TagInfo[]>("/api/tags")).map(mapTag);
    },

    async create(name) {
      return mapTag(await post<TagInfo>("/api/tags", { name }));
    },

    remove: async (id) => {
      await del(`/api/tags/${id}`);
    },

    addItem: async (itemId, tagId) => {
      await post(`/api/items/${itemId}/tags`, { id: tagId });
    },

    removeItem: async (itemId, tagId) => {
      await del(`/api/items/${itemId}/tags?id=${tagId}`);
    },

    update: unsupported("tags.update"),
  },

  types: {
    async list() {
      return (await get<TypeInfo[]>("/api/types")).map(mapType);
    },

    async create(name, icon) {
      const type = await post<TypeInfo>("/api/types", icon != null ? { name, icon } : { name });
      invalidateTypes();
      return mapType(type);
    },

    remove: async (id) => {
      await del(`/api/types/${id}`);
      invalidateTypes();
    },

    update: unsupported("types.update"),

    async addField(typeId, name, fieldType, _icon, label, _options) {
      const f = await post<FieldInfo>(`/api/types/${typeId}/fields`, { name, fieldType, label });
      invalidateTypes();
      return mapField(f, typeId);
    },

    async updateField(id, name, fieldType, _icon, label, _options) {
      // REST 端点挂在类型下：先找字段所属类型
      const types = await loadTypes();
      const owner = types.find((t) => t.fields.some((f) => f.id === id));
      if (!owner) throw new Error(`shell dogfood: 字段 ${id} 不存在`);
      const old = owner.fields.find((f) => f.id === id)!;
      await patch(`/api/types/${owner.id}/fields/${id}`, { name, fieldType, label });
      invalidateTypes();
      const next: Field = {
        id,
        type_id: owner.id,
        name,
        field_type: fieldType as Field["field_type"],
        icon: "",
        position: old.position,
        label,
        options: old.options,
      };
      return next;
    },

    removeField: async (fieldId) => {
      const types = await loadTypes();
      const owner = types.find((t) => t.fields.some((f) => f.id === fieldId));
      if (!owner) throw new Error(`shell dogfood: 字段 ${fieldId} 不存在`);
      await del(`/api/types/${owner.id}/fields/${fieldId}`);
      invalidateTypes();
    },

    reorderFields: unsupported("types.reorderFields"),
    saveToLibrary: unsupported("types.saveToLibrary"),
    exportToFile: unsupported("types.exportToFile"),
    listLibrary: async () => [],
    readLibrary: unsupported("types.readLibrary"),
    deleteLibrary: unsupported("types.deleteLibrary"),
    importFromLibrary: unsupported("types.importFromLibrary"),
    importFromFile: unsupported("types.importFromFile"),
  },

  files: {
    list: (itemId) => fetchFiles(itemId),
    createFolder: unsupported("files.createFolder"),
    remove: unsupported("files.remove"),
    rename: unsupported("files.rename"),
    addAttachments: unsupported("files.addAttachments"),
    writeAttachment: unsupported("files.writeAttachment"),
    open: unsupported("files.open"),
  },

  notes: {
    list: async () => [],
    create: unsupported("notes.create"),
    update: unsupported("notes.update"),
    remove: unsupported("notes.remove"),
  },

  workspace: {
    list: async () => [],
    read: unsupported("workspace.read"),
    write: unsupported("workspace.write"),
    remove: unsupported("workspace.remove"),
  },

  plugins: {
    listInstalled: async () => [],
    listGlobal: async () => [],
    readFile: unsupported("plugins.readFile"),
    install: unsupported("plugins.install"),
    installToGlobal: unsupported("plugins.installToGlobal"),
    remove: unsupported("plugins.remove"),
    uninstallFromRepo: unsupported("plugins.uninstallFromRepo"),
    checkUsage: unsupported("plugins.checkUsage"),
    readCache: async () => ({}),
    writeCache: async () => undefined,
  },

  presets: {
    list: async () => [],
    install: unsupported("presets.install"),
    export: unsupported("presets.export"),
  },

  repo: {
    info: () => repoInfo(),
    // 服务端独占工作区：忽略 path，返回当前仓库信息
    open: async () => repoInfo(),
    getState: () => get<Record<string, unknown>>("/api/repo/state"),
    saveState: async (newState) => {
      await put("/api/repo/state", newState);
    },
    create: unsupported("repo.create"),
    close: unsupported("repo.close"),
    openSubRepoWindow: unsupported("repo.openSubRepoWindow"),
    getSubRepoPath: unsupported("repo.getSubRepoPath"),
  },

  marketplace: {
    fetchIndex: unsupported("marketplace.fetchIndex"),
    download: unsupported("marketplace.download"),
  },

  dashboard: {
    listRepos: async () => [],
    addRepo: unsupported("dashboard.addRepo"),
    removeRepo: unsupported("dashboard.removeRepo"),
    updateRepoIcon: unsupported("dashboard.updateRepoIcon"),
    openWindow: unsupported("dashboard.openWindow"),
  },
};
