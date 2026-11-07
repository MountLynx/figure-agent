"""figureagent：只认一个目录的独立 figures 服务。

入口：``python -m figureagent --dir <绝对路径> [--port 0] [--host 127.0.0.1]``

本包不碰任何数据库：没有仓库、条目、类型、分组的概念。图内容全部落在工作目录
（``--dir``）的保留文件里——``plot.py`` 是真相源，「是否有图」= ``plot.py`` 存在。
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
