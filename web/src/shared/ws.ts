// 同源 WS 地址（原 shared/base.ts 的 `__FIG_BASE__` / `__FIG_READY__` 机制整块删除）。
//
// 页面由 Python 服务同源托管，`/ws` 就是同源路径；`vite dev` 由 vite 代理到
// 127.0.0.1:8801。基址不再可配置，所以这里没有 async 版本。

export function wsUrl(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}
