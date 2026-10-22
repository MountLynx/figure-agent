# 分组柱状图模板（figure-agent）
# 契约：模块级构建图形并存入变量 fig；关键 artist 用 set_gid("fa:…") 命名。
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(5.2, 3.6))

groups = ["A", "B", "C"]
control = [2.1, 3.2, 2.8]
treatment = [3.4, 4.1, 3.9]

x = range(len(groups))
width = 0.36

bars_c = ax.bar([xi - width / 2 for xi in x], control, width=width, label="对照组", color="#8aa8c4")
bars_t = ax.bar([xi + width / 2 for xi in x], treatment, width=width, label="处理组", color="#d08770")

for i, b in enumerate(bars_c):
    b.set_gid(f"fa:control-bar-{i}")
for i, b in enumerate(bars_t):
    b.set_gid(f"fa:treatment-bar-{i}")

ax.set_xticks(list(x))
ax.set_xticklabels(groups)
ax.set_ylabel("表达量 (a.u.)")
ax.set_title("分组柱状图示例")
ax.set_ylim(0, 5)
ax.legend(frameon=False)

fig.tight_layout()
