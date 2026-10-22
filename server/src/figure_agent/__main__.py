"""python -m figure_agent：启动本地服务 / 旧数据一次性迁移。"""

from __future__ import annotations

import argparse
import json

import uvicorn

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="figure-agent", description="figure-agent 本地服务")
    parser.add_argument("command", nargs="?", choices=["serve", "migrate"], default="serve",
                        help="serve=启动服务（默认）；migrate=旧 workspace 迁移为 Index 仓库")
    parser.add_argument("--port", type=int, default=config.port())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--workspace", default=None, help="工作区目录（默认 <repo>/workspace 或 $FA_WORKSPACE）")
    parser.add_argument("--archive", action="store_true",
                        help="migrate 时把旧项目目录归档到 _migrated_backup/ 而非删除")
    args = parser.parse_args()

    if args.workspace:
        import os

        os.environ["FA_WORKSPACE"] = str(args.workspace)

    if args.command == "migrate":
        from .migrate import migrate_workspace

        summary = migrate_workspace(config.workspace_dir(), archive=args.archive)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    uvicorn.run(
        "figure_agent.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
