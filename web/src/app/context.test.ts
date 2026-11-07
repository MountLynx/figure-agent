// /api/context 拉取单测：唯一输入 ?dir=、相对路径、字段契约、失败不白屏。
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchContext, readDirParam } from "./context";

interface Call {
  url: string;
}

function stubFetch(
  body: unknown,
  over: { ok?: boolean; status?: number; statusText?: string; jsonThrows?: boolean } = {}
): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL) => {
      calls.push({ url: String(url) });
      return Promise.resolve({
        ok: over.ok ?? true,
        status: over.status ?? 200,
        statusText: over.statusText ?? "OK",
        json: () => (over.jsonThrows ? Promise.reject(new Error("no body")) : Promise.resolve(body)),
      } as unknown as Response);
    })
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readDirParam", () => {
  it("取 ?dir= 的值（去空白）", () => {
    expect(readDirParam("?dir=C%3A%5Cwork%5Cdemo")).toBe("C:\\work\\demo");
    expect(readDirParam("?panel=ai&dir=/tmp/a%20b")).toBe("/tmp/a b");
  });

  it("缺省 / 空白 → null（页面显示「请从 Index 打开」）", () => {
    expect(readDirParam("")).toBeNull();
    expect(readDirParam("?panel=ai")).toBeNull();
    expect(readDirParam("?dir=")).toBeNull();
    expect(readDirParam("?dir=%20%20")).toBeNull();
  });

  it("接受 URLSearchParams", () => {
    expect(readDirParam(new URLSearchParams("dir=/tmp/x"))).toBe("/tmp/x");
  });
});

describe("fetchContext", () => {
  it("GET /api/context?dir=<编码>（同源相对路径）并解析三字段", async () => {
    const calls = stubFetch({ dir: "/tmp/demo", name: "demo", has_figure: true });
    const got = await fetchContext("/tmp/demo");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`/api/context?dir=${encodeURIComponent("/tmp/demo")}`);
    expect(calls[0].url.startsWith("/")).toBe(true);
    expect(calls[0].url).not.toMatch(/^https?:/);
    expect(got).toEqual({ dir: "/tmp/demo", name: "demo", has_figure: true });
  });

  it("有图标志为 false 时原样返回（走建图流）", async () => {
    stubFetch({ dir: "/tmp/empty", name: "empty", has_figure: false });
    await expect(fetchContext("/tmp/empty")).resolves.toEqual({
      dir: "/tmp/empty",
      name: "empty",
      has_figure: false,
    });
  });

  it("name 缺失时用目录末段兜底", async () => {
    stubFetch({ dir: "C:\\work\\demo", has_figure: false });
    const got = await fetchContext("C:\\work\\demo");
    expect(got.name).toBe("demo");
  });

  it("非 2xx：抛出 status + 服务端 detail", async () => {
    stubFetch(
      { detail: "工作目录不存在：/nope" },
      { ok: false, status: 400, statusText: "Bad Request" }
    );
    await expect(fetchContext("/nope")).rejects.toThrow("400: 工作目录不存在：/nope");
  });

  it("响应形状不对（缺 dir / 缺 has_figure）→ 抛错而不是白屏", async () => {
    stubFetch({ name: "x", has_figure: true });
    await expect(fetchContext("/x")).rejects.toThrow("缺少 dir");
    stubFetch({ dir: "/x", name: "x" });
    await expect(fetchContext("/x")).rejects.toThrow("缺少 has_figure");
  });
});
