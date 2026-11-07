"""路由依赖：当前工作目录（启动参数 ``--dir``，缺省时可由 ``?dir=`` 首次绑定）。

没有仓库、没有数据库连接——只有那一个目录。
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..workdir import Workdir

#: ``app.state`` 上工作目录的键名。
STATE_KEY = "workdir"


def get_workdir(request: Request) -> Workdir:
    """取当前工作目录。

    ``--dir`` 给定时直接用它（``?dir=`` 被忽略）；未给定时允许**首次**请求的
    ``?dir=`` 绑进来（vite dev 代理场景）。都拿不到 → 400（而不是 500）。
    """
    workdir = getattr(request.app.state, STATE_KEY, None)
    if workdir is None:
        raw = request.query_params.get("dir")
        if raw:
            try:
                workdir = Workdir(raw)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            setattr(request.app.state, STATE_KEY, workdir)
    if workdir is None:
        raise HTTPException(
            status_code=400,
            detail="尚未指定工作目录：请用 --dir <绝对路径> 启动，或用 ?dir=<绝对路径> 指定",
        )
    return workdir
