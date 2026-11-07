// API 客户端单测：相对路径（绝不发绝对地址）、?dir= 注入、错误处理、请求体形状。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, apiUrl, flattenItemFiles, FIGURE_ID, getApiDir, setApiDir } from "./api";

interface Call {
  url: string;
  init: RequestInit | undefined;
}

/** 桩 fetch：记录每次调用，返回给定 body（或错误响应）。 */
function stubFetch(
  body: unknown,
  over: { ok?: boolean; status?: number; statusText?: string; jsonThrows?: boolean } = {}
): Call[] {
  const calls: Call[] = [];
  const fn = vi.fn((url: string | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return Promise.resolve({
      ok: over.ok ?? true,
      status: over.status ?? 200,
      statusText: over.statusText ?? "OK",
      json: () =>
        over.jsonThrows ? Promise.reject(new Error("no body")) : Promise.resolve(body),
    } as unknown as Response);
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

describe("api 相对路径", () => {
  beforeEach(() => setApiDir(""));
  afterEach(() => {
    vi.unstubAllGlobals();
    setApiDir("");
  });

  it("默认（未设置 dir）只发 /api/ 相对路径", async () => {
    const calls = stubFetch([]);
    await api.listTemplates();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/figures/templates");
    expect(calls[0].url.startsWith("/")).toBe(true);
    expect(calls[0].url).not.toMatch(/^https?:/);
  });

  it("设置 dir 后每个请求都带 ?dir=（URL 编码）", async () => {
    setApiDir("C:\\work\\图 1");
    expect(getApiDir()).toBe("C:\\work\\图 1");
    const calls = stubFetch({ hasFigure: false });
    await api.getFigure(FIGURE_ID);
    await api.aiStatus();
    expect(calls[0].url).toBe(
      `/api/figures/${FIGURE_ID}?dir=${encodeURIComponent("C:\\work\\图 1")}`
    );
    expect(calls[1].url).toBe(`/api/figures/status?dir=${encodeURIComponent("C:\\work\\图 1")}`);
    for (const c of calls) expect(c.url).not.toMatch(/^https?:/);
  });

  it("apiUrl 拒绝绝对地址 / 非 /api/ 路径", () => {
    expect(() => apiUrl("http://127.0.0.1:8801/api/x")).toThrow();
    expect(() => apiUrl("/ws")).toThrow();
    expect(() => apiUrl("api/x")).toThrow();
  });

  it("已带查询串的路径用 & 续接 dir", () => {
    setApiDir("/w");
    expect(apiUrl("/api/x?foo=1")).toBe("/api/x?foo=1&dir=%2Fw");
  });
});

describe("api 错误处理", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setApiDir("");
  });

  it("非 2xx：抛出 status + 服务端 detail", async () => {
    stubFetch({ detail: "工作目录不存在" }, { ok: false, status: 400, statusText: "Bad Request" });
    await expect(api.getFigure(FIGURE_ID)).rejects.toThrow("400: 工作目录不存在");
  });

  it("非 2xx 且响应不是 JSON：退回 statusText", async () => {
    stubFetch(null, { ok: false, status: 502, statusText: "Bad Gateway", jsonThrows: true });
    await expect(api.aiStatus()).rejects.toThrow("502: Bad Gateway");
  });

  it("成功响应返回解析后的 JSON", async () => {
    stubFetch({ ok: true, cleared: true, remaining: 0 });
    await expect(api.verifyPatch(FIGURE_ID)).resolves.toMatchObject({ cleared: true });
  });
});

describe("请求方法与请求体", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("putPatch 发 PUT + JSON", async () => {
    const calls = stubFetch({ ok: true });
    const patch = { baseHash: "h", ops: [] };
    await api.putPatch(FIGURE_ID, patch);
    expect(calls[0].init?.method).toBe("PUT");
    expect(calls[0].init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(calls[0].init?.body).toBe(JSON.stringify(patch));
  });

  it("run / verifyPatch / writebackPatch 发 POST 无 body", async () => {
    const calls = stubFetch({ ok: true, stderr: "", results: [] });
    await api.run(FIGURE_ID);
    await api.verifyPatch(FIGURE_ID);
    await api.writebackPatch(FIGURE_ID);
    expect(calls.map((c) => c.init?.method)).toEqual(["POST", "POST", "POST"]);
    expect(calls[0].init?.body).toBeUndefined();
  });

  it("listFiles 走 GET /api/files（工作目录只读树，无请求体）", async () => {
    const calls = stubFetch({ name: "root", is_dir: true, children: [] });
    await api.listFiles();
    expect(calls[0].url).toBe("/api/files");
    expect(calls[0].init?.method ?? "GET").toBe("GET");
    expect(calls[0].init?.body).toBeUndefined();
  });
});

describe("flattenItemFiles", () => {
  it("平铺目录、跳过保留名", () => {
    const tree = {
      children: [
        { name: "data.csv", is_dir: false, size: 10 },
        { name: "plot.py", is_dir: false },
        { name: "uploads", is_dir: true, children: [{ name: "raw.xlsx", is_dir: false, bytes: 5 }] },
        { name: "base.svg", is_dir: false },
      ],
    };
    expect(flattenItemFiles(tree, ["plot.py", "base.svg"])).toEqual([
      { rel: "data.csv", size: 10 },
      { rel: "uploads/raw.xlsx", size: 5 },
    ]);
  });
});
