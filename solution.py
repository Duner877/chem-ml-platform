"""XAS-Sim2Real 双向 XANES 谱域映射 —— 赛题提交入口。

用法（赛题规定接口）::

    python /root/solution.py --input queries.npz --output predictions.npz

两个模块直接按**文件路径**加载，而不是 ``import models.xas_sim2real``。

原因值得写下来：``models/__init__.py`` 会连带导入整个平台包
（descriptors / geometry / mpnn / registry …）。在评测环境里只投放
``solution.py`` 与赛题模块时，那个包初始化会直接抛
``ModuleNotFoundError: models.descriptors``，评测器看到的是"程序无法启动"，
而不是一次推理失败。按路径加载让本文件只依赖 numpy，两种布局都能跑。

所有契约校验、确定性保证与降级逻辑都在 :mod:`xas_sim2real` 里。
"""

from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(module_name: str, relative_path: str):
    """Load a sibling module by path, bypassing package ``__init__``."""
    path = os.path.join(_HERE, relative_path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"缺少模块文件 / missing module file: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"无法加载模块 / cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _locate(relative_path: str):
    """Find the module either beside this file or inside a ``models/`` package."""
    for candidate in (
        os.path.join(_HERE, relative_path),
        os.path.join(_HERE, "models", relative_path),
        os.path.join(_HERE, os.pardir, "models", relative_path),
    ):
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_HERE, relative_path)


# xas_sim2real imports xas_domain_map as a sibling module, so register it under
# the bare name first -- that keeps the platform-side ``models.xas_sim2real``
# import working unchanged while the task side avoids the package entirely.
_domain = _load("xas_domain_map", _locate("xas_domain_map.py"))
sys.modules.setdefault("models.xas_domain_map", _domain)

_sim2real = _load("xas_sim2real", _locate("xas_sim2real.py"))
main = _sim2real.main

if __name__ == "__main__":
    raise SystemExit(main())