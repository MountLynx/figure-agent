// shell 平台适配：浏览器环境的窗口/对话框（无原生窗口条，dialog 走 prompt/confirm/alert）。

import type { ShellPlatform } from "@index/shell-react";

export const platform: ShellPlatform = {
  window: {
    minimize() {},
    toggleMaximize() {},
    close() {
      window.close();
    },
  },
  dialog: {
    open: async (options) => window.prompt((options?.title as string | undefined) ?? "输入路径"),
    save: async () => {
      throw new Error("shell dogfood: dialog.save 不支持");
    },
    ask: async (message) => window.confirm(message),
    message: async (message) => window.alert(message),
  },
};
