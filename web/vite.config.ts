import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // shell-react 以 file: 链接进 web：强制 react/zustand 全树单实例，tabler 字体取 web 本地副本
    dedupe: ["react", "react-dom", "zustand"],
    alias: {
      "@tabler/icons-webfont": fileURLToPath(
        new URL("./node_modules/@tabler/icons-webfont", import.meta.url)
      ),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
  build: { outDir: "dist" },
});
