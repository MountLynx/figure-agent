// @vitest-environment happy-dom
// App 入口：不带 ?dir= 也能直接打开（工作目录由服务端 --dir 绑定）。
import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import App from "./App";

const CONTEXT = {
  dir: "C:\\work\\demo",
  name: "demo",
  has_figure: true,
};

/** happy-dom 没有 WebSocket；Workbench 挂载时会连 /ws，给个惰性替身即可。 */
class FakeWebSocket {
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  constructor(public url: string) {}
  send() {}
  close() {}
}

function stubBrowserApis() {
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
}

function jsonOnce(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
  });
}

describe("App 入口", () => {
  let root: Root | null = null;
  let host: HTMLElement;

  afterEach(() => {
    if (root) act(() => root!.unmount());
    root = null;
    host?.remove();
    vi.unstubAllGlobals();
  });

  function mount() {
    host = document.body.appendChild(document.createElement("div"));
    root = createRoot(host);
    act(() => root!.render(createElement(App)));
  }

  it("无 ?dir=：裸调 /api/context，服务端绑定目录即可进入编辑器", async () => {
    stubBrowserApis();
    const fetchMock = jsonOnce(CONTEXT);
    vi.stubGlobal("fetch", fetchMock);
    mount();
    await act(async () => {});

    expect(fetchMock).toHaveBeenCalled();
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/context");
    expect(document.title).toBe("demo");
    expect(host.textContent).not.toContain("请从 Index 打开");
  });

  it("context 失败：渲染错误页而不是白屏", async () => {
    stubBrowserApis();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: async () => ({ detail: "工作目录不存在：X" }),
      }),
    );
    mount();
    await act(async () => {});

    expect(host.textContent).toContain("加载工作目录失败");
    expect(host.textContent).toContain("工作目录不存在");
  });
});
