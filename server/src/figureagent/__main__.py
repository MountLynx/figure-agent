"""``python -m figureagent`` → 转调 figservice（本包只有 figures 能力）。"""

from __future__ import annotations

from .figservice import main

if __name__ == "__main__":
    raise SystemExit(main())
