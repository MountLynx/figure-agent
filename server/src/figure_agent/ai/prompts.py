"""AI 工作流 prompt 资产（唯一来源）。

三层 prompt 约定：本文件的 *_CORE 是 Layer 1（任务定义+输出格式约束），
契约文本（RENDER_CONTRACT 等）注册时直接拼入 prompt_core 尾部；
运行时输入（数据画像/要求/选区/stderr）经 task inputs 的具名 bind 与
{spec.xxx} 常量注入 {placeholder}。
注意：占位符正则是 \\{\\w+\\}——prompt 里 JSON 示例必须用带引号的键
（如 {"code": ...}），否则花括号会被当占位符吞掉。
AGENTS.md 面向人、本文件面向 harness，两者须一致，此处为准。
"""

RENDER_CONTRACT = """\
## 渲染契约（必须遵守）
1. 模块级构建图形并存入变量 fig，例如 `fig, ax = plt.subplots(...)`；服务端执行后取 fig 存为 SVG。
2. 不要调用 plt.show()。
3. 不要设置 plt.rcParams["svg.fonttype"] 与 ["svg.hashsalt"]（服务端强制，覆盖会被改回）。
4. 结尾调用 fig.tight_layout()（如适用）。"""

GID_CONVENTION = """\
## gid 约定（必须遵守）
对每个"用户可能想单独选中/修改"的 artist 调 set_gid("fa:名字")，gid 会成为 SVG 元素 id，
是选区定位与微调回写的基础：
- 一组柱子逐根命名：`for i, b in enumerate(bars): b.set_gid(f"fa:treatment-bar-{i}")`
- 整个散点系列：`sc = ax.scatter(...)` 然后 `sc.set_gid("fa:setosa")`
- 标题/轴标签：`t = ax.set_title("...")` 然后 `t.set_gid("fa:title")`
命名建议 fa:<语义>-<序号>。没有 fa: gid 的元素只能靠脆弱的自动 id 匹配。"""

SAFE_FONTS = """\
## 安全字体（只用以下字体）
DejaVu Sans / Arial / Helvetica / Times New Roman / SimHei / Microsoft YaHei / Noto Sans CJK SC"""

DATA_RULE = """\
## 数据读取约定
数据文件是脚本同目录下的 data.csv（UTF-8）。用 pandas 读取：
`import pandas as pd` + `df = pd.read_csv("data.csv")`。
不要在代码里硬编码数据值；不要读其他路径。"""

CONTRACT = "\n\n".join([RENDER_CONTRACT, GID_CONVENTION, SAFE_FONTS, DATA_RULE])

#: 契约文本代码示例中的花括号（如 f"fa:...-{i}"）会被占位符正则匹配，
#: 但 SpecModule 渲染时未匹配的 key 保留原样，示例会原样呈现给 LLM，无害。
CONTRACT_PLACEHOLDERS = {"i"}

STANDARDIZE_CORE = """你是数据标准化专家。把「原始表格文本」整理为规范 CSV：
- 列名单行规范（合并重复/多级表头、去空白）；行列完整；数值列不混入单位文字
- 缺失值留空；不编造、不删除数据行
- 同时产出数据画像 profile：columns 每列含 name/dtype(text|number|datetime)/unit(可空)/desc(中文语义)；
  顶层 shape=[行,列]、notes=数据背景一句话
只输出 JSON 对象，键为 "csv"（规范 CSV 全文）、"profile"（画像对象）、"notes"（整理取舍说明，中文）。

原始表格文本：
{data}"""

GEN_CODE_CORE = """你是绘图代码生成器。根据「数据画像」与「绘图要求」写一个完整的 matplotlib plot.py。
只输出 JSON 对象，键为 "code"（plot.py 全文）与 "notes"（实现说明；要求无法满足时在此说明，禁止编造数据）。

数据画像：
{profile}

绘图要求：
{requirements}"""

ADAPT_CODE_CORE = """你是绘图脚本改造器。把「原始脚本」改造为符合契约的 plot.py：
保留原脚本的图表类型、数据映射与视觉风格；数据来源改为读 data.csv（按数据画像对应列名）；
补齐契约要求的 fig 变量、fa: gid、安全字体。原脚本与数据冲突时以数据为准，差异写进 notes。
只输出 JSON 对象，键为 "code"（plot.py 全文）与 "notes"（改造说明：改了什么、为什么）。

数据画像：
{profile}

绘图要求（可能为空）：
{requirements}

原始脚本：
{script_text}"""

FIX_CODE_CORE = """你是绘图代码修复器。「当前代码」渲染失败，按「渲染结果」里的报错修复：
保持既有视觉设计不变，只修导致报错的问题。
只输出 JSON 对象，键为 "code"（修复后 plot.py 全文）与 "notes"（修复说明）。

当前代码与渲染结果：
{render}"""

EDIT_CODE_CORE = """你是绘图代码修改器。根据「用户指令」与「选区 JSON」定点修改「当前代码」：
- 选区 JSON 的 elementId 对应代码里 set_gid("fa:…") 的 artist；多选为数组，逐项处理
- 只做指令要求的修改；改 artist 属性时优先改对应 matplotlib 参数
只输出 JSON 对象，键为 "code"（修改后 plot.py 全文）与 "notes"（修改说明）。

当前代码：
{code}

选区 JSON：
{selection}

用户指令：
{instruction}"""

TRANSLATE_PATCH_CORE = """你是微调回写器。把「翻译材料」里 ops 的每条手动微调翻译进 code，让代码直接表达它：
- 改色/样式 → 对应 color/linestyle/linewidth 参数
- 文本/字号 → set_title/set_xlabel 等字符串或 fontsize 参数
- 位移/缩放 → 改数据或 offset
- 隐藏 → artist.set_visible(False)；置顶/置底 → artist.set_zorder(大值/小值)
op 的 target.id 形如 "fa:xxx"，对应 code 里 set_gid("fa:xxx") 的 artist，据此定位；intent 是语义意图。
无法合理表达的 op 不要硬改，保留给 patch 覆盖层，并在 notes 说明。给新增/被改动的 artist 补 set_gid("fa:…")。
只输出 JSON 对象，键为 "code"（回写后 plot.py 全文）与 "notes"（逐条 op 处理结果）。

翻译材料（ops=patch 操作列表；code=当前代码；verify=上轮校验结果，首轮为 null）：
{material}"""
