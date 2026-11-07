// 应用上下文：独立视图的唯一输入是 URL 的 `?dir=<绝对路径>`。
//
// 启动时 GET /api/context 拿 `{dir, name, has_figure}`：
// - `dir`：服务端规范化后的工作目录（后续 /api 与 /ws 都用它）；
// - `name`：目录名 → 页面标题；
// - `has_figure`：是否有图（plot.py 存在）→ 决定走「建图」流程还是编辑器，
//   也是 AI 面板「有图才可用」的应用状态来源。
//
// 这里不 import 任何宿主（原插件的 ctx）、不发绝对地址请求：同源相对路径。

export interface WorkdirContext {
  /** 服务端规范化后的工作目录（绝对路径）。 */
  dir: string;
  /** 目录名（标题用；服务端没给时用 dir 的最后一段兜底）。 */
  name: string;
  /** 是否有图：plot.py 存在为 true。 */
  has_figure: boolean;
}

/** URL 里的 `?dir=`（去掉空白；缺省返回 null → 页面显示「请从 Index 打开」）。 */
export function readDirParam(search: string | URLSearchParams): string | null {
  const params = typeof search === "string" ? new URLSearchParams(search) : search;
  const dir = (params.get("dir") ?? "").trim();
  return dir || null;
}

/** 目录末尾一段：服务端未给 name 时的兜底标题。 */
function baseName(dir: string): string {
  const parts = dir.split(/[\\/]+/).filter(Boolean);
  return parts.at(-1) ?? dir;
}

async function errorDetail(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    return String(body?.detail ?? resp.statusText);
  } catch {
    return resp.statusText;
  }
}

/**
 * 拉取工作目录上下文。任何失败（非 2xx / 响应形状不对 / 网络错误）都抛 Error，
 * 由调用方渲染错误页——不允许白屏。
 *
 * `pageDir` 是可选提示（URL 的 `?dir=`）：服务端用 `--dir` 绑定目录时不需要它；
 * 只有 dev（服务没传 `--dir`）才靠它完成首次绑定。
 */
export async function fetchContext(pageDir?: string | null): Promise<WorkdirContext> {
  const query = pageDir ? `?dir=${encodeURIComponent(pageDir)}` : "";
  const resp = await fetch(`/api/context${query}`);
  if (!resp.ok) {
    throw new Error(`${resp.status}: ${await errorDetail(resp)}`);
  }
  const data: unknown = await resp.json();
  const obj = data as Partial<WorkdirContext> | null;
  if (!obj || typeof obj.dir !== "string" || !obj.dir.trim()) {
    throw new Error("/api/context 响应缺少 dir");
  }
  if (typeof obj.has_figure !== "boolean") {
    throw new Error("/api/context 响应缺少 has_figure");
  }
  const dir = obj.dir;
  const name = typeof obj.name === "string" && obj.name.trim() ? obj.name : baseName(dir);
  return { dir, name, has_figure: obj.has_figure };
}
