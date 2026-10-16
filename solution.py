"""XAS-Sim2Real 双向 XANES 谱域映射 —— 赛题提交入口。

用法（赛题规定接口）::

    python /root/solution.py --input queries.npz --output predictions.npz

实现委托给 :mod:`models.xas_sim2real`，那里存放全部契约校验、确定性保证与
降级逻辑。本文件只负责让评测环境能直接 `python /root/solution.py` 运行：
把仓库根目录加入 ``sys.path``，这样即使从任意工作目录调用也能导入平台模块。
"""

from __future__ import annotations

import os
import sys

# 无论从哪个目录调用，都能找到 models 包。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir))
for _candidate in (_ROOT, _HERE):
    if os.path.isdir(os.path.join(_candidate, "models")) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from models.xas_sim2real import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())