"""WS 事件广播：图更新、渲染失败。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List

from fastapi import WebSocket

log = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self.clients: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, event: dict) -> None:
        text = json.dumps(event, ensure_ascii=False)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    def broadcast_threadsafe(self, event: dict) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            # fire-and-forget 任务持强引用（done 后自清），防中途被 GC 回收
            task = asyncio.create_task(self.broadcast(event))
            _bg_tasks.add(task)
            task.add_done_callback(_bg_tasks.discard)
        else:
            log.warning(
                "broadcast_threadsafe 在无事件循环线程被调用，事件丢弃: %s",
                event.get("type"),
            )


# broadcast 后台任务引用集（仅防 GC，不参与生命周期管理）
_bg_tasks: set = set()

hub = Hub()
