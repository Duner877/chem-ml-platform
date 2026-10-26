"""为 ``custom_nodes/`` 的每个设备分组生成 ``__init__.py``。

为什么需要生成器而不是手写
--------------------------
21 个分组、101 个节点类，手写 21 个 ``__init__.py`` 意味着 21 次「复制粘贴
节点类名」的机会。抄错一个名字，症状是「某个节点在界面上不见了」或者
「import 那个模块时报 ImportError」——都不是编译期能发现的。

生成器从源码 AST 里读出真正带 ``@register_node`` 的类，再写 ``__init__.py``，
所以导出列表和实现永远一致。**新增一个节点类后重跑本脚本即可。**

每个 ``__init__.py`` 做三件事：

1. 文档字符串 —— 说明这个设备组包含什么、对应什么仪器；
2. 重新导出该组的节点类 —— 让 ``from custom_nodes.mass_spectrometry import
   LCMSNode`` 这种写法可用；
3. 声明 ``__all__`` —— 明确这个包对外暴露什么。

用法::

    python scripts/generate_custom_node_packages.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
CUSTOM = ROOT / "custom_nodes"

#: 分组 -> (中文名, 说明)
GROUP_DOCS: Dict[str, tuple] = {
    "mass_spectrometry": (
        "质谱",
        "液相 / 气相 / 元素 / 飞行时间质谱，以及碎片化路径解析。",
    ),
    "spectroscopy": (
        "光谱",
        "紫外-可见、荧光、红外、拉曼、核磁共振，以及光谱成像与高光谱。",
    ),
    "surface_characterization": (
        "表面与物性",
        "XPS、XAS 仿真、粒径与 BET 表面积。",
    ),
    "thermal_analysis": (
        "热分析",
        "热重、差示扫描量热、动态力学分析。",
    ),
    "microscopy": (
        "显微成像",
        "扫描电镜、透射电镜、原子力显微镜。",
    ),
    "diffraction": (
        "衍射",
        "粉末 X 射线衍射与单晶 X 射线衍射。",
    ),
    "electrochemistry": (
        "电化学",
        "循环伏安与电化学阻抗谱。",
    ),
    "seismic": (
        "地震",
        "地震采集、正演模拟与全波形反演。",
    ),
    "battery_materials": (
        "电池材料",
        "硬碳预脱溶剂、双 SEI 能量学与电解液老化。",
    ),
    "quantum_chemistry": (
        "量子化学",
        "ORCA、Gaussian、Psi4、CP2K 的分子性质计算。",
    ),
    "materials_simulation": (
        "材料计算",
        "ABACUS、VASP、Quantum ESPRESSO 的晶体与能带计算。",
    ),
    "molecular_dynamics": (
        "分子动力学",
        "GROMACS、LAMMPS、OpenMM 的分子与固体力学模拟。",
    ),
    "databases": (
        "数据库",
        "谱库、化学数据库与材料数据库的检索节点。",
    ),
    "foundation_models": (
        "基座模型",
        "ChemBERTa、GROVER、Graphormer、Uni-Mol 化学基础模型。",
    ),
    "ai_ml": (
        "AI / 机器学习",
        "大语言模型、视觉模型、性质预测与模型训练。",
    ),
    "data_io": (
        "数据输入输出",
        "谱图、表格、图像、分子与材料的文件读写。",
    ),
    "analysis": (
        "通用分析",
        "基线校正、平滑、寻峰、归一化、描述符与相似度。",
    ),
    "reporting": (
        "报告与出图",
        "报告构建、汇总表、文档导出与产物图绘制。",
    ),
    "agent": (
        "科学智能体",
        "自主规划、工具调用与推理。",
    ),
    "questions": (
        "科学问题",
        "顶层科学问题节点：这是什么化合物、该合成什么材料。",
    ),
    "gpu": (
        "GPU 计算",
        "PyTorch 张量运算、模型推理与 GPU 设备探测。",
    ),
    "_shared": (
        "共享基础设施",
        "节点基类与厂商谱图适配器，不直接提供节点。",
    ),
}


def registered_classes(path: Path) -> List[str]:
    """Return the node classes in ``path`` that carry ``@register_node``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    found: List[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for dec in node.decorator_list:
            if "register_node" in ast.dump(dec):
                found.append(node.name)
                break
    return found


def collect_group(group_dir: Path) -> Dict[str, List[str]]:
    """Map module name -> node classes for one device group."""
    modules: Dict[str, List[str]] = {}
    for f in sorted(group_dir.rglob("*.py")):
        if "__pycache__" in f.parts or f.name == "__init__.py":
            continue
        classes = registered_classes(f)
        if classes:
            rel = f.relative_to(group_dir)
            dotted = ".".join(rel.with_suffix("").parts)
            modules[dotted] = classes
    return modules


def preserved_exports(group_dir: Path) -> List[tuple]:
    """Re-export statements already present in the group's ``__init__.py``.

    Why this exists
    ---------------
    The generator used to *overwrite* ``__init__.py`` unconditionally.  The
    agent group is the proof that this is wrong: its ``__init__.py`` also
    re-exported the planner functions (``Plan``, ``Planner``, ``RECIPES``,
    ...), the tool registry and ``__version__`` -- none of which carry a
    ``@register_node`` decorator, so the AST scan never saw them and the
    regeneration silently deleted them.  ``backend/routers/agent.py`` then
    failed at import time with ``cannot import name 'plan_question' from
    'nodes.agent'``.

    The failure was invisible in the source tree (the package still
    imported, the node still registered) and only appeared in the *packaged*
    payload, where the module layout differs.  A generator that can delete
    hand-written exports is a generator that will do so again.

    So: read the existing file, keep every ``from ... import (...)`` name
    that is not already covered by the AST scan, and re-emit them.  The
    result is that running the generator is idempotent and non-destructive.
    """
    init = group_dir / "__init__.py"
    if not init.exists():
        return []
    try:
        tree = ast.parse(init.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []

    statements: List[tuple] = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        # ``from __future__ import annotations`` is a *directive*, not a
        # re-export: it binds no name and must never be copied into the
        # generated file, where it would also be a syntax error (a future
        # import has to be the first statement in the module).
        if node.module == "__future__":
            continue
        names = [alias.name for alias in node.names]
        if not names:
            continue
        statements.append((node.module or "", node.level, names))
    return statements


def preserved_version_block(group_dir: Path) -> str:
    """The ``__version__`` fallback block, if the group declares one.

    ``scripts/version.py`` checks ``custom_nodes/agent/__init__.py`` for a
    ``__version__`` that follows the platform version.  The AST scan cannot
    see it (it is an assignment, not a decorated class), so the generator
    has to carry it over or the version sweep reports a missing file.
    """
    init = group_dir / "__init__.py"
    if not init.exists():
        return ""
    try:
        source = init.read_text(encoding="utf-8")
    except OSError:
        return ""
    if "__version__" not in source:
        return ""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, ast.Try) and "__version__" in ast.dump(node):
            return ast.get_source_segment(source, node) or ""
    return ""


HEADER = '''"""{zh}节点分组。

{desc}

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.{group} import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

'''


def main() -> int:
    written = 0
    for group_dir in sorted(CUSTOM.iterdir()):
        if not group_dir.is_dir():
            continue
        if group_dir.name.startswith("."):
            continue
        group = group_dir.name
        zh, desc = GROUP_DOCS.get(group, (group, ""))

        modules = collect_group(group_dir)
        preserved = preserved_exports(group_dir)
        version_block = preserved_version_block(group_dir)

        lines = [HEADER.format(zh=zh, desc=desc, group=group)]
        exported: List[str] = []
        for dotted, classes in modules.items():
            lines.append(f"from custom_nodes.{group}.{dotted} import (\n")
            for cls in classes:
                lines.append(f"    {cls},\n")
            lines.append(")\n")
            exported.extend(classes)

        # Names already covered by the AST scan must not be imported twice.
        known = set(exported)
        for module, level, names in preserved:
            wanted = [n for n in names if n not in known]
            if not wanted:
                continue
            if level:
                # Relative import inside the package: keep it relative.
                dots = "." * level
                lines.append(f"from {dots}{module or ''} import (\n")
            else:
                lines.append(f"from {module} import (\n")
            for name in wanted:
                lines.append(f"    {name},\n")
            lines.append(")\n")
            exported.extend(wanted)
            known.update(wanted)

        if version_block:
            lines.append("\n")
            lines.append(version_block)
            lines.append("\n")
            if "__version__" not in exported:
                exported.append("__version__")

        if not modules and group == "_shared":
            # No node classes here: still needs to be a valid package so that
            # ``import custom_nodes._shared.x`` works.
            lines.append("from custom_nodes._shared import _base  # noqa: F401\n")
            lines.append(
                "from custom_nodes._shared import vendor_adapters  # noqa: F401\n"
            )

        lines.append("\n__all__ = [\n")
        for name in exported:
            lines.append(f'    "{name}",\n')
        lines.append("]\n")

        (group_dir / "__init__.py").write_text("".join(lines), encoding="utf-8")
        total = sum(len(c) for c in modules.values())
        if total:
            print(f"  {group}: {total} 个节点，{len(modules)} 个模块")
        else:
            print(f"  {group}: 包骨架（无节点类）")
        written += 1

    print(f"\n共生成 {written} 个包的 __init__.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
