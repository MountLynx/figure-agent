"""figservice：只服务 figures 的独立 FastAPI 应用（``python -m figureagent``）。

启动契约（Index 宿主握手依赖它，勿改）：

    python -m figureagent --dir <绝对路径> [--host 127.0.0.1] [--port 0]

端口绑定完成（lifespan 就绪）后向 stdout 依次打印两行：

    FIG_SERVICE_PORT=<实际端口>   # --port 0 时为系统分配的真实端口
    FIG_SERVICE_READY

能力边界：
- ``/api/figures/*``（figures 全套）+ ``/ws`` + ``/api/context`` + ``/api/health``；
- ``/`` 与其余 GET 路径托管前端产物 ``web/dist``（相对 server 包定位；
  目录不存在时返回一段提示 HTML，而不是 500）；
- 不挂 items/groups/types/repo 等任何其它域路由：``/api/items/list`` 必须 404。

CORS：生产同源（页面由本服务托管）不需要跨域；只为 dev 放行 vite 的两个
5173 origin。本机服务，绝不开 ``allow_origins=["*"]``。

进程收到 SIGTERM/SIGINT 时走 uvicorn 的优雅关闭，并以 0 退出。
"""

from __future__ import annotations

import argparse
import html
import signal
import sys
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import config
from .api import figures_api
from .api.deps import STATE_KEY, get_workdir
from .workdir import Workdir

#: dev 放行的页面 origin（vite dev server）。
ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

#: 宿主解析的端口行前缀与就绪标记（契约固定，勿改）。
PORT_MARKER = "FIG_SERVICE_PORT="
READY_MARKER = "FIG_SERVICE_READY"

#: ``app.state`` 上前端产物目录的键名。
WEB_DIST_STATE_KEY = "web_dist"

#: 静态资源前缀：这些路径永不由静态托管兜底（必须 404）。
_API_PREFIXES = ("api", "ws")

_FALLBACK_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>figure-agent · 前端尚未构建</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin: 0; padding: 48px 24px; font: 15px/1.7 system-ui, "Segoe UI",
         "Microsoft YaHei", sans-serif; }}
  main {{ max-width: 720px; margin: 0 auto; }}
  h1 {{ font-size: 20px; margin: 0 0 16px; }}
  code, pre {{ background: rgba(127,127,127,.15); border-radius: 6px; }}
  code {{ padding: 1px 5px; }}
  pre {{ padding: 12px 14px; overflow-x: auto; }}
  ul {{ padding-left: 20px; }}
  .muted {{ opacity: .7; }}
</style>
</head>
<body>
<main>
  <h1>figure-agent 服务已启动，但前端页面还没构建</h1>
  <p>静态产物目录不存在：<code>{dist}</code></p>
  <p>构建前端后刷新本页即可：</p>
  <pre>cd figure-agent/web
npm install
npm run build</pre>
  <p class="muted">工作目录：<code>{root}</code></p>
  <p>API 已可用：
    <a href="/api/context">/api/context</a> ·
    <a href="/api/health">/api/health</a> ·
    <a href="/api/figures/status">/api/figures/status</a> ·
    <a href="/api/figures/templates">/api/figures/templates</a>
  </p>
</main>
</body>
</html>
"""


def _web_dist(app: FastAPI) -> Path:
    return app.state.web_dist


def _fallback_html(app: FastAPI) -> str:
    workdir = getattr(app.state, STATE_KEY, None)
    return _FALLBACK_HTML.format(
        dist=html.escape(str(_web_dist(app))),
        root=html.escape(str(workdir.root) if workdir is not None else "（未指定 --dir）"),
    )


def _index_or_fallback(app: FastAPI) -> FileResponse | HTMLResponse:
    """``web/dist/index.html`` 在就托管它，不在就给一段提示 HTML（200，不是 500）。"""
    index = _web_dist(app) / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html")
    return HTMLResponse(_fallback_html(app), status_code=200)


def create_app(workdir: Workdir | str | None = None,
               web_dist: Path | str | None = None) -> FastAPI:
    """构造独立 figures app。

    ``workdir`` 为 None 时不绑定目录（端点 400，等 ``?dir=`` 首次绑定）；
    ``web_dist`` 为 None 时按 ``../web/dist`` 相对 server 包定位。
    """
    resolved = workdir if isinstance(workdir, Workdir) or workdir is None else Workdir(workdir)

    app = FastAPI(title="figure-agent", version="0.1.0")
    setattr(app.state, STATE_KEY, resolved)
    app.state.web_dist = Path(web_dist) if web_dist is not None else config.web_dist_dir()

    # 本机服务：只放行 dev 页面 origin 的 preflight（请求带 Content-Type: application/json）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(figures_api.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/context")
    def api_context(workdir: Workdir = Depends(get_workdir)):
        """前端启动时取一次的上下文：目录、目录名、是否有图。"""
        return {
            "dir": str(workdir.root),
            "name": workdir.name(),
            "has_figure": workdir.has_figure(),
        }

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _index_or_fallback(app)

    @app.get("/{full_path:path}")
    def static_files(full_path: str):
        """静态托管 + SPA 兜底；``/api/*`` 与 ``/ws`` 一律 404（路由边界）。"""
        head = full_path.split("/", 1)[0]
        if head in _API_PREFIXES:
            raise HTTPException(status_code=404, detail="Not Found")
        dist = _web_dist(app)
        if full_path:
            dist_root = dist.resolve()
            target = (dist_root / full_path).resolve()
            if not target.is_relative_to(dist_root):
                raise HTTPException(status_code=404, detail="Not Found")
            if target.is_file():
                return FileResponse(target)
            if Path(full_path).suffix:
                # 具名资源缺失就老实 404，不要把 index.html 当 js/css 发出去
                raise HTTPException(status_code=404, detail="Not Found")
        return _index_or_fallback(app)

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        # 引擎 ValueError 统一 400（中文 detail），不要 500
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


def _bound_port(server: uvicorn.Server) -> int:
    """从已绑定的监听 socket 读实际端口（--port 0 时由系统分配）。"""
    for listener in getattr(server, "servers", None) or []:
        for sock in getattr(listener, "sockets", None) or []:
            try:
                return int(sock.getsockname()[1])
            except OSError:  # pragma: no cover - 已关闭的 socket
                continue
    return int(server.config.port)  # pragma: no cover - 理论上不可达


class _FigServer(uvicorn.Server):
    """绑定成功（startup 返回）后向 stdout 报出实际端口与就绪标记。"""

    async def startup(self, sockets=None) -> None:  # type: ignore[override]
        await super().startup(sockets=sockets)
        if self.should_exit:  # pragma: no cover - 启动即被要求退出
            return
        # flush=True：stdout 接管道时是块缓冲，宿主侧要立刻读到
        print(f"{PORT_MARKER}{_bound_port(self)}", flush=True)
        print(READY_MARKER, flush=True)


def _ignore_signal(signum, frame) -> None:  # pragma: no cover - 仅信号路径
    """占位信号处理器：吞掉 uvicorn 关闭后的信号重发，让进程以 0 退出。"""


def serve(app: FastAPI, host: str, port: int) -> int:
    """启动 uvicorn；就绪行由 _FigServer.startup 打印，返回进程退出码。"""
    cfg = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        # access 日志默认写 stdout，会污染宿主解析的端口/就绪行，故关闭
        access_log=False,
    )
    server = _FigServer(cfg)
    # uvicorn 的 capture_signals 负责优雅关闭，但关闭后会把捕获到的信号原样
    # 重发；先装空处理器，让重发成为 no-op（否则 SIGTERM 会以信号退出）。
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _ignore_signal)
        except (OSError, ValueError):  # pragma: no cover - 非主线程/平台不支持
            pass
    try:
        server.run()
    except KeyboardInterrupt:  # pragma: no cover - 兜底，正常路径不会到这
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m figureagent",
        description="figure-agent 独立 figures 服务：只认一个目录，同时托管前端静态页",
    )
    parser.add_argument("--dir", default=None,
                        help="工作目录绝对路径（图内容落在该目录）")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址（默认 127.0.0.1，仅本机可访问）")
    parser.add_argument("--port", type=int, default=0,
                        help="监听端口；0 = 由系统分配，实际端口见 FIG_SERVICE_PORT 行")
    args = parser.parse_args(argv)

    workdir: Workdir | None = None
    if args.dir is None:
        print("figureagent: 未指定 --dir，端点将返回 400（可用 ?dir= 指定）",
              file=sys.stderr, flush=True)
    else:
        try:
            workdir = Workdir(args.dir)
        except ValueError as exc:
            print(f"figureagent: {exc}", file=sys.stderr, flush=True)
            return 2
    return serve(create_app(workdir), args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
