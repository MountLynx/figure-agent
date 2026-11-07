// REST API 客户端（figures 域 + files 列表；自 itemmanage figurePlugins/shared/api.ts 移植）。
//
// 独立应用没有宿主注入的基址（原 shared/base.ts 的 `__FIG_BASE__` 机制整块删除）：
// 页面由 Python 服务同源托管，所有请求都是**相对路径** `/api/...`（dev 由 vite 代理）。
// 工作目录经 `?dir=` 传给服务端（服务端也可用 `--dir` 启动时忽略它）。

import type {
  AiRunResult,
  AiStatus,
  FigureResponse,
  PatchDoc,
  RenderResult,
  SelectionJSON,
  TemplateInfo,
  VerifyResponse,
} from "./types";

/** figure API 的路径标识：独立应用没有条目 id，服务端按 --dir 定位唯一工作目录，
 *  这一路径段只是保持 `/api/figures/{id}/...` 形状的占位（服务端忽略其值）。
 *  契约见 figure-agent/AGENTS.md：前端统一用字面量 `work`。 */
export const FIGURE_ID = "work";

/** 当前工作目录（App 拿到 /api/context 的规范 dir 后写入；同源相对路径之外唯一的状态）。 */
let apiDir = "";
export function setApiDir(dir: string): void {
  apiDir = dir;
}
export function getApiDir(): string {
  return apiDir;
}

/** `/api/...` → 带上工作目录查询参数（没有 dir 时原样返回，保持纯相对路径）。 */
export function apiUrl(path: string): string {
  if (!path.startsWith("/api/")) throw new Error(`API 路径必须是 /api/ 开头的相对路径：${path}`);
  if (!apiDir) return path;
  return `${path}${path.includes("?") ? "&" : "?"}dir=${encodeURIComponent(apiDir)}`;
}

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
  // ---- 图内容
  listTemplates: async () => fetch(apiUrl("/api/figures/templates")).then((r) => json<TemplateInfo[]>(r)),
  getFigure: async (id: string) =>
    fetch(apiUrl(`/api/figures/${id}`)).then((r) => json<FigureResponse>(r)),
  deleteFigure: async (id: string) =>
    fetch(apiUrl(`/api/figures/${id}`), { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  putCode: async (id: string, code: string) =>
    fetch(apiUrl(`/api/figures/${id}/code`), req("PUT", { code })).then((r) => json<RenderResult>(r)),
  run: async (id: string) =>
    fetch(apiUrl(`/api/figures/${id}/run`), { method: "POST" }).then((r) => json<RenderResult>(r)),
  putPatch: async (id: string, patch: PatchDoc) =>
    fetch(apiUrl(`/api/figures/${id}/patch`), req("PUT", patch)).then((r) => json<{ ok: boolean }>(r)),
  verifyPatch: async (id: string) =>
    fetch(apiUrl(`/api/figures/${id}/verify-patch`), { method: "POST" }).then((r) =>
      json<VerifyResponse>(r)
    ),
  snapshot: async (id: string, note: string) =>
    fetch(apiUrl(`/api/figures/${id}/snapshot`), req("POST", { note })).then((r) =>
      json<{ id: string }>(r)
    ),
  listRuns: async (id: string) =>
    fetch(apiUrl(`/api/figures/${id}/runs`)).then((r) => json<unknown[]>(r)),

  // ---- AI
  aiStatus: async () => fetch(apiUrl("/api/figures/status")).then((r) => json<AiStatus>(r)),
  createFigure: async (
    id: string,
    requirements: string,
    template: string,
    upload: File | null,
    existingFile = ""
  ) => {
    const fd = new FormData();
    fd.append("requirements", requirements);
    fd.append("template", template);
    if (existingFile) fd.append("existing_file", existingFile);
    else if (upload) fd.append("upload", upload);
    return fetch(apiUrl(`/api/figures/${id}/create`), { method: "POST", body: fd }).then((r) =>
      json<AiRunResult>(r)
    );
  },
  adaptFigure: async (
    id: string,
    script: File | null,
    upload: File | null,
    requirements: string,
    existingScript = "",
    existingData = ""
  ) => {
    const fd = new FormData();
    fd.append("requirements", requirements);
    if (existingScript) fd.append("existing_script", existingScript);
    else if (script) fd.append("script", script);
    if (existingData) fd.append("existing_data", existingData);
    else if (upload) fd.append("upload", upload);
    return fetch(apiUrl(`/api/figures/${id}/adapt`), { method: "POST", body: fd }).then((r) =>
      json<AiRunResult>(r)
    );
  },
  instruct: async (id: string, instruction: string, selection: object | object[]) =>
    fetch(apiUrl(`/api/figures/${id}/instruct`), req("POST", { instruction, selection })).then((r) =>
      json<AiRunResult>(r)
    ),
  writebackPatch: async (id: string) =>
    fetch(apiUrl(`/api/figures/${id}/writeback`), { method: "POST" }).then((r) =>
      json<AiRunResult>(r)
    ),
  enrichSelection: async (id: string, selection: object | object[]) =>
    fetch(apiUrl(`/api/figures/${id}/enrich-selection`), req("POST", { selection })).then((r) =>
      json<SelectionJSON>(r)
    ),

  // ---- 工作目录只读文件树（建图流选数据/脚本；工作台右栏文件列表）
  listFiles: async () =>
    fetch(apiUrl("/api/files")).then((r) => json<{ name: string; is_dir: boolean; children?: unknown[] }>(r)),
};

export interface FlatFile {
  /** 工作目录内相对路径（files 域 relPath 语义） */
  rel: string;
  size: number;
}

/** files/list 树 → 平铺文件清单（跳过目录与图表保留名；建图流选附件用）。 */
export function flattenItemFiles(node: { children?: unknown[] }, reserved: string[]): FlatFile[] {
  const out: FlatFile[] = [];
  const walk = (children: any[], prefix: string) => {
    for (const c of children ?? []) {
      if (c.is_dir) {
        walk(c.children ?? [], prefix ? `${prefix}/${c.name}` : c.name);
        continue;
      }
      const rel = prefix ? `${prefix}/${c.name}` : c.name;
      if (reserved.includes(c.name)) continue; // 保留名（根层同名即保留）
      out.push({ rel, size: Number(c.size ?? c.bytes ?? 0) });
    }
  };
  walk((node.children ?? []) as any[], "");
  return out;
}
