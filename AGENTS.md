# AGENTS.md — figure-agent 绘图代码约定

本仓库包含 figure-agent：一个"AI 写 matplotlib 代码 + 浏览器手动微调（patch）+ 微调回写收敛"的科研图表工具。

当你（AI 助手）在 `workspace/` 下编辑任何 `plot.py` 时，必须遵守以下契约。

## 渲染契约

1. **模块级构建图形，存入变量 `fig`**：

   ```python
   import matplotlib.pyplot as plt
   fig, ax = plt.subplots(...)
   ```

   服务端 exec 后取 `fig` 存成 base.svg。不要调用 `plt.show()`（无效但无意义）。

2. **不要碰 `svg.fonttype`**。服务端强制 `svg.fonttype = "none"`（文字保持 `<text>` 可选中可编辑，这是命脉）。你覆盖了也会被改回去并产生警告。

3. **不要手写 SVG id 冲突的代码**；渲染产物 base.svg 由服务管理，不要手工编辑。

## gid 约定（最重要）

对每个"用户可能想单独选中/修改"的 artist 调 `set_gid("fa:名字")`。gid 会成为 SVG 元素的 `id`，是选区回传和微调回写收敛的基础。没有 fa: gid 的元素只能靠脆弱的自动 id（`patch_3`、`text_1`，重渲染后会漂移）匹配。

```python
bars = ax.bar(x, y, label="处理组")
for i, b in enumerate(bars):
    b.set_gid(f"fa:treatment-bar-{i}")     # 单个柱子

scatter = ax.scatter(xs, ys, label="setosa")
scatter.set_gid("fa:setosa")               # 整个散点系列
```

命名建议：`fa:<语义>-<序号>`，如 `fa:treatment-bar-2`、`fa:y-label`、`fa:title`。标题/轴标签等文本 artist：

```python
t = ax.set_title("分组柱状图")
t.set_gid("fa:title")
```

## 微调回写工作流（ZCode 内）

用户说"把 patch 回写进代码"时：

1. `fa_get_patch` 读手动微调（每条 op 有 `intent` 意图 + 语义目标）；
2. `fa_get_figure` 读当前代码；
3. 修改 plot.py，让代码**直接表达**每条 op（改色 → 改 color 参数；位移 → 改数据/offset；字号 → 改 fontsize；隐藏 → `artist.set_visible(False)`；置顶/置底 → `artist.set_zorder(高值/低值)`），并给对应 artist 补 gid；
4. `fa_set_code` 写回并重渲染；
5. `fa_verify_patch` 做收敛判定——resolved 的 op 自动删除；重复 3–5 直到返回 `cleared: true`。

翻译错了也没关系：patch 覆盖层仍在，图不会坏，可以反复迭代。

## 安全字体

只用 DejaVu Sans / Arial / Helvetica / Times New Roman / SimHei / Microsoft YaHei / Noto Sans CJK SC，避免运行时与浏览器渲染漂移过大。
