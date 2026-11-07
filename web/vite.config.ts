import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// 独立应用：产物由 Python 服务在 `/` 静态托管，所以资源引用必须是相对路径
// （base: "./"）。dev 时把 `/api` 与 `/ws` 代理到本地 figures 服务。
const BACKEND = "http://127.0.0.1:8801";

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": BACKEND,
      "/ws": { target: BACKEND.replace(/^http/, "ws"), ws: true },
    },
  },
  build: { outDir: "dist" },
  test: {
    setupFiles: ["./src/test-setup.ts"],
  },
});
