"""渲染契约注入 runner（由 executor 以子进程运行）。

用法：python render_once.py <plot.py> <out.svg>

- 前置注入 Agg 后端、svg.fonttype=none、svg.hashsalt 固定；
- 用户代码覆盖 svg.fonttype 时警告并强制回 none；
- 退出码非 0 = 渲染失败，traceback（含 plot.py 行号）走 stderr。
"""

from __future__ import annotations

import contextlib
import io
import sys
import traceback

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["svg.fonttype"] = "none"      # 文字保持 <text>，可编辑——命脉开关
plt.rcParams["svg.hashsalt"] = "figure-agent"  # 输出确定性


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: render_once.py <plot.py> <out.svg>", file=sys.stderr)
        return 64
    plot_path, out_path = sys.argv[1], sys.argv[2]

    src = open(plot_path, encoding="utf-8").read()
    code = compile(src, plot_path, "exec")
    g = {"__name__": "__main__", "__file__": plot_path}

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, g)  # noqa: S102 - 设计如此：执行用户绘图代码
    except Exception:
        traceback.print_exc()
        return 1

    if plt.rcParams["svg.fonttype"] != "none":
        print(
            "WARNING: plot.py 覆盖了 svg.fonttype，已强制回 'none'"
            "（文字必须保持 <text> 才能被选中编辑）",
            file=sys.stderr,
        )
        plt.rcParams["svg.fonttype"] = "none"

    fig = g.get("fig")
    if fig is None:
        nums = plt.get_fignums()
        if not nums:
            print(
                "ERROR: plot.py 未产生图形。需在模块级构建图形并存入变量 fig。",
                file=sys.stderr,
            )
            return 2
        fig = plt.figure(nums[-1])
        print("NOTE: 未找到变量 fig，已使用最后一个打开的 figure。", file=sys.stderr)

    fig.savefig(out_path, format="svg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
