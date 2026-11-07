# Iris 散点图模板（figure-agent）
# 契约：模块级构建图形并存入变量 fig；关键 artist 用 set_gid("fa:…") 命名。
import matplotlib.pyplot as plt

# 内嵌数据（每物种 15 个样本，避免外部依赖）
DATA = {
    "setosa": [
        (1.4, 0.2), (1.4, 0.2), (1.3, 0.2), (1.5, 0.2), (1.4, 0.2),
        (1.7, 0.4), (1.4, 0.3), (1.5, 0.2), (1.4, 0.2), (1.5, 0.1),
        (1.5, 0.2), (1.6, 0.2), (1.4, 0.1), (1.1, 0.1), (1.2, 0.2),
    ],
    "versicolor": [
        (4.7, 1.4), (4.5, 1.5), (4.9, 1.5), (4.0, 1.3), (4.6, 1.5),
        (4.5, 1.3), (4.7, 1.6), (3.3, 1.0), (4.6, 1.3), (3.9, 1.4),
        (3.5, 1.0), (4.2, 1.5), (4.0, 1.0), (4.7, 1.4), (3.6, 1.3),
    ],
    "virginica": [
        (6.0, 2.5), (5.1, 1.9), (5.9, 2.1), (5.6, 1.8), (5.8, 2.2),
        (6.6, 2.1), (4.5, 1.7), (6.3, 1.8), (5.8, 1.8), (6.1, 2.5),
        (5.1, 2.0), (5.3, 1.9), (5.5, 2.1), (5.0, 2.0), (5.1, 2.4),
    ],
}

COLORS = {"setosa": "#4477aa", "versicolor": "#ee7733", "virginica": "#228833"}

fig, ax = plt.subplots(figsize=(5.2, 3.9))

for name, pts in DATA.items():
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    sc = ax.scatter(xs, ys, s=28, c=COLORS[name], label=name, alpha=0.85, edgecolors="none")
    sc.set_gid(f"fa:{name}")

ax.set_xlabel("花瓣长度 (cm)")
ax.set_ylabel("花瓣宽度 (cm)")
ax.set_title("Iris 花瓣散点图")
ax.legend(frameon=False)

fig.tight_layout()
