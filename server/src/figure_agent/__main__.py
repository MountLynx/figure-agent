"""python -m figure_agent：启动本地服务。"""

from __future__ import annotations

import argparse

import uvicorn

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="figure-agent", description="figure-agent 本地服务")
    parser.add_argument("--port", type=int, default=config.port())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--workspace", default=None, help="工作区目录（默认 <repo>/workspace 或 $FA_WORKSPACE）")
    args = parser.parse_args()

    if args.workspace:
        import os

        os.environ["FA_WORKSPACE"] = str(args.workspace)

    uvicorn.run(
        "figure_agent.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
