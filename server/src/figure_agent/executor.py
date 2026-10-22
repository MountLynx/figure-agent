"""渲染执行器：subprocess 跑 plot.py，注入渲染契约（§5）。

契约由独立的 runner 脚本在子进程里前置注入：
  matplotlib.use("Agg")、svg.fonttype="none"（命脉开关）、svg.hashsalt 固定。
plot.py 需在模块级把图形存进变量 fig；未找到时回退到最后一个打开的 figure。
渲染失败保留上一版 base.svg（由 store 层保证）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

RUNNER_PATH = Path(__file__).resolve().parent / "runner" / "render_once.py"

LINE_RE = re.compile(r'File "[^"]*", line (\d+)')


@dataclass
class RenderResult:
    ok: bool
    stderr: str
    error_line: Optional[int] = None
    duration_ms: int = 0
    timeout: bool = False


def render(plot_py: Path, out_svg: Path, timeout: float = 30.0, cwd: Optional[Path] = None) -> RenderResult:
    t0 = time.monotonic()
    cmd = [sys.executable, str(RUNNER_PATH), str(plot_py), str(out_svg)]
    # Windows 默认用 ANSI 代码页（中文系统 cp936）编解码子进程输出；
    # 强制 UTF-8 与 Linux 对齐，避免 traceback 里的特殊字符引发二次解码错误
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    duration = int((time.monotonic() - t0) * 1000)
    stderr = proc.stderr or ""
    error_line = None
    if proc.returncode != 0:
        for m in LINE_RE.finditer(stderr):
            error_line = int(m.group(1))
    return RenderResult(
        ok=proc.returncode == 0,
        stderr=stderr,
        error_line=error_line,
        duration_ms=duration,
    )


def render_with_timeout_guard(plot_py: Path, out_svg: Path, timeout: float = 30.0, cwd: Optional[Path] = None) -> RenderResult:
    try:
        return render(plot_py, out_svg, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        return RenderResult(
            ok=False,
            stderr=f"渲染超时（>{timeout:g}s），已终止。可在 plot.py 排查死循环或调大超时。",
            timeout=True,
        )
