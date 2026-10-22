// @vitest-environment happy-dom
import { describe, expect, it, vi, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { ManageView } from "./ManageView";
import { api } from "../../api";

vi.mock("../../api", () => ({
  api: {
    listItems: vi.fn(() =>
      Promise.resolve([
        {
          id: "aaaabbbbcccc", name: "图A", typeName: "图", groupIds: [1],
          tags: ["重要"], properties: { 来源: "ai" },
          createdAt: "2026-01-01T00:00:00+00:00", updatedAt: "2026-01-02T00:00:00+00:00",
          hasBase: true, opCount: 2,
        },
      ])
    ),
    listGroups: vi.fn(() =>
      Promise.resolve([{ id: 1, parentId: null, name: "项目A", position: 0, boundItemId: null }])
    ),
    listTags: vi.fn(() => Promise.resolve([{ id: 1, name: "重要" }])),
    listTypes: vi.fn(() =>
      Promise.resolve([
        { id: 3, name: "图", icon: "chart-bar", fields: [
          { id: 1, name: "模板", fieldType: "text", position: 0, label: "", options: [] },
        ] },
      ])
    ),
    getRepoState: vi.fn(() => Promise.resolve({ theme: "light" })),
    putRepoState: vi.fn(() => Promise.resolve({})),
    listFiles: vi.fn(() => Promise.resolve([{ path: "plot.py", isDir: false }])),
    deleteItem: vi.fn(() => Promise.resolve({ ok: true })),
    bindItemGroup: vi.fn(() => Promise.resolve({ ok: true })),
  },
}));

describe("ManageView", () => {
  let root: Root | null = null;
  let container: HTMLElement;

  afterEach(() => {
    root?.unmount();
    root = null;
  });

  function render() {
    container = document.body.appendChild(document.createElement("div"));
    root = createRoot(container);
    return act(async () => {
      root!.render(createElement(ManageView, { onOpen: vi.fn() }));
      await new Promise((r) => setTimeout(r, 0));
    });
  }

  it("渲染图列表与分组树", async () => {
    await render();
    expect(container.textContent).toContain("图A");
    expect(container.textContent).toContain("项目A");
    expect(container.textContent).toContain("重要");
    expect(container.textContent).toContain("2 微调");
  });

  it("删除按钮两击确认后调用 api.deleteItem", async () => {
    await render();
    const del = [...container.querySelectorAll("button")].find((b) => b.textContent === "删除")!;
    await act(async () => {
      del.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(api.deleteItem).not.toHaveBeenCalled(); // 第一次只确认
    const confirmBtn = [...container.querySelectorAll("button")].find((b) => b.textContent === "确认删除?")!;
    await act(async () => {
      confirmBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(api.deleteItem).toHaveBeenCalledWith("aaaabbbbcccc");
  });
});
