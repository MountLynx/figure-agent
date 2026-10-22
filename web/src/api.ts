// REST API 客户端（Index 仓库模式）

import type {
  AiRunResult,
  AiStatus,
  FieldInfo,
  FileInfo,
  FigureDetail,
  GroupInfo,
  ItemInfo,
  PatchDoc,
  RenderResult,
  RepoInfo,
  SelectionJSON,
  TagInfo,
  TemplateInfo,
  TypeInfo,
  VerifyResponse,
} from "./types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${resp.status}: ${detail}`);
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

export const api = {
  // ---- 仓库
  repoInfo: () => fetch("/api/repo/info").then((r) => json<RepoInfo>(r)),
  getRepoState: () =>
    fetch("/api/repo/state").then((r) => json<Record<string, unknown>>(r)),
  putRepoState: (patch: Record<string, unknown>) =>
    fetch("/api/repo/state", req("PUT", patch)).then((r) => json<Record<string, unknown>>(r)),

  // ---- 条目
  listItems: (params: { q?: string; groupId?: number | null; tagId?: number | null } = {}) => {
    const sp = new URLSearchParams();
    if (params.q) sp.set("q", params.q);
    if (params.groupId != null) sp.set("groupId", String(params.groupId));
    if (params.tagId != null) sp.set("tagId", String(params.tagId));
    const qs = sp.toString();
    return fetch(`/api/items${qs ? `?${qs}` : ""}`).then((r) => json<ItemInfo[]>(r));
  },
  createItem: (body: { name: string; groupId?: number | null; template?: string | null; origin?: string }) =>
    fetch("/api/items", req("POST", body)).then((r) =>
      json<{ id: string; name: string; ok: boolean; stderr: string }>(r)
    ),
  patchItem: (id: string, body: { name?: string; properties?: Record<string, string> }) =>
    fetch(`/api/items/${id}`, req("PATCH", body)).then((r) => json<ItemInfo>(r)),
  deleteItem: (id: string) =>
    fetch(`/api/items/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  bindItemGroup: (id: string, groupId: number) =>
    fetch(`/api/items/${id}/groups`, req("POST", { id: groupId })).then((r) => json<{ ok: boolean }>(r)),
  unbindItemGroup: (id: string, groupId: number) =>
    fetch(`/api/items/${id}/groups?id=${groupId}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  bindItemTag: (id: string, tagId: number) =>
    fetch(`/api/items/${id}/tags`, req("POST", { id: tagId })).then((r) => json<{ ok: boolean }>(r)),
  unbindItemTag: (id: string, tagId: number) =>
    fetch(`/api/items/${id}/tags?id=${tagId}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),

  // ---- 分组 / 标签 / 类型
  listGroups: () => fetch("/api/groups").then((r) => json<GroupInfo[]>(r)),
  createGroup: (body: { name: string; parentId?: number | null; position?: number }) =>
    fetch("/api/groups", req("POST", body)).then((r) => json<GroupInfo>(r)),
  updateGroup: (id: number, body: { name?: string; parentId?: number | null; position?: number }) =>
    fetch(`/api/groups/${id}`, req("PATCH", body)).then((r) => json<GroupInfo>(r)),
  deleteGroup: (id: number) =>
    fetch(`/api/groups/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  listTags: () => fetch("/api/tags").then((r) => json<TagInfo[]>(r)),
  createTag: (body: { name: string }) =>
    fetch("/api/tags", req("POST", body)).then((r) => json<TagInfo>(r)),
  deleteTag: (id: number) =>
    fetch(`/api/tags/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  listTypes: () => fetch("/api/types").then((r) => json<TypeInfo[]>(r)),
  createType: (body: { name: string; icon?: string }) =>
    fetch("/api/types", req("POST", body)).then((r) => json<TypeInfo>(r)),
  deleteType: (id: number) =>
    fetch(`/api/types/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  addField: (typeId: number, body: { name: string; fieldType?: string; label?: string }) =>
    fetch(`/api/types/${typeId}/fields`, req("POST", body)).then((r) => json<FieldInfo>(r)),
  updateField: (typeId: number, fieldId: number, body: { name?: string; fieldType?: string; label?: string; position?: number }) =>
    fetch(`/api/types/${typeId}/fields/${fieldId}`, req("PATCH", body)).then((r) => json<{ ok: boolean }>(r)),
  removeField: (typeId: number, fieldId: number) =>
    fetch(`/api/types/${typeId}/fields/${fieldId}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),

  // ---- 图内容
  listTemplates: () => fetch("/api/templates").then((r) => json<TemplateInfo[]>(r)),
  listFiles: (id: string) => fetch(`/api/figures/${id}/files`).then((r) => json<FileInfo[]>(r)),
  getFigure: (id: string) => fetch(`/api/figures/${id}`).then((r) => json<FigureDetail>(r)),
  putCode: (id: string, code: string) =>
    fetch(`/api/figures/${id}/code`, req("PUT", { code })).then((r) => json<RenderResult>(r)),
  run: (id: string) =>
    fetch(`/api/figures/${id}/run`, { method: "POST" }).then((r) => json<RenderResult>(r)),
  putPatch: (id: string, patch: PatchDoc) =>
    fetch(`/api/figures/${id}/patch`, req("PUT", patch)).then((r) => json<{ ok: boolean }>(r)),
  verifyPatch: (id: string) =>
    fetch(`/api/figures/${id}/verify-patch`, { method: "POST" }).then((r) => json<VerifyResponse>(r)),
  snapshot: (id: string, note: string) =>
    fetch(`/api/figures/${id}/snapshot`, req("POST", { note })).then((r) => json<{ id: string }>(r)),
  listRuns: (id: string) => fetch(`/api/figures/${id}/runs`).then((r) => json<unknown[]>(r)),

  // ---- AI
  aiStatus: () => fetch("/api/ai/status").then((r) => json<AiStatus>(r)),
  createFigureAi: (name: string, requirements: string, groupId: number | null, data: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("requirements", requirements);
    if (groupId != null) fd.append("groupId", String(groupId));
    fd.append("data", data);
    return fetch("/api/figures/ai", { method: "POST", body: fd }).then((r) => json<AiRunResult>(r));
  },
  adaptFigure: (name: string, requirements: string, groupId: number | null, data: File, script: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("requirements", requirements);
    if (groupId != null) fd.append("groupId", String(groupId));
    fd.append("data", data);
    fd.append("script", script);
    return fetch("/api/figures/adapt", { method: "POST", body: fd }).then((r) => json<AiRunResult>(r));
  },
  instruct: (id: string, instruction: string, selection: object | object[]) =>
    fetch(`/api/figures/${id}/instruct`, req("POST", { instruction, selection })).then((r) =>
      json<AiRunResult>(r)
    ),
  writebackPatch: (id: string) =>
    fetch(`/api/figures/${id}/writeback`, { method: "POST" }).then((r) => json<AiRunResult>(r)),
  enrichSelection: (id: string, selection: object | object[]) =>
    fetch(`/api/figures/${id}/enrich-selection`, req("POST", { selection })).then((r) =>
      json<SelectionJSON>(r)
    ),
};
