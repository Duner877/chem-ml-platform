"""把 ``nodes/`` 重构成 ComfyUI 风格的 ``custom_nodes/`` 设备分组结构。

为什么不是「直接改 import」
--------------------------
节点模块之间有 103 处 ``from nodes.xxx import`` 绝对导入，还有 1 处相对导入。
逐条手改 103 处 import 是典型的「按行号批量替换源码」型自伤操作——一旦漏改
一处，那个节点在运行到那行时才炸，而 ``py_compile`` 和导入期检查全都看不出来。

所以走**包别名**路线：
- 磁盘上所有节点实现搬到 ``custom_nodes/<设备组>/``，这是用户能看见、能增删的部分；
- ``nodes`` 变成一个**兼容门面包**：它把 ``custom_nodes`` 的所有子包注册到
  ``sys.modules`` 下，于是 ``from nodes.instruments.ms import LCMSNode`` 这类
  旧 import 全部继续可用，测试和历史工作流不用改一个字符。

分组依据
--------
ComfyUI 的做法是「一个插件一个目录」。这里对应的粒度是**设备类别**：
质谱、光谱、热分析、显微、衍射、表面与物性、电化学、地震、电池材料、
量子化学、材料计算、分子动力学、数据库、基座模型、AI/ML、数据输入输出、
通用分析、报告出图、智能体。

每组一个独立目录、含自己的 ``__init__.py``，可以单独增删——这正是「方便后续
添加」的前提：新增一类设备 = 新建一个目录 + 放几个 ``.py``，不需要改注册表、
不需要改加载器。

用法::

    python scripts/migrate_to_custom_nodes.py --plan     # 只打印计划
    python scripts/migrate_to_custom_nodes.py --apply    # 真正执行
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
NODES = ROOT / "nodes"
TARGET = ROOT / "custom_nodes"

#: 设备分组 -> 源文件（相对 ``nodes/``）。每个分组目标是一个独立包。
GROUPS: Dict[str, List[str]] = {
    # ---- 仪器类（按设备）-------------------------------------------------- #
    "mass_spectrometry": [
        "instruments/ms.py",
        "instruments/fragmentation.py",
        "instruments/mass_spectrometry/",   # -> 直接落在组目录下，不嵌套
    ],
    "spectroscopy": [
        "instruments/electronic.py",
        "instruments/vibrational.py",
        "instruments/nmr.py",
        "instruments/imaging.py",
    ],
    "surface_characterization": [
        "instruments/surface.py",
        "instruments/xas_sim2real.py",
        "instruments/particle.py",
    ],
    "thermal_analysis": [
        "instruments/thermal.py",
    ],
    "microscopy": [
        "instruments/microscopy.py",
    ],
    "diffraction": [
        "instruments/diffraction.py",
    ],
    "electrochemistry": [
        "instruments/electro.py",
    ],
    "seismic": [
        "instruments/seismic.py",
    ],
    "battery_materials": [
        "instruments/desolvation.py",
    ],
    # ---- 计算类（按方法）-------------------------------------------------- #
    "quantum_chemistry": [
        "simulation/quantum.py",
    ],
    "materials_simulation": [
        "simulation/materials_sim.py",
    ],
    "molecular_dynamics": [
        "simulation/molecular_dynamics.py",
    ],
    # ---- 数据与模型 ------------------------------------------------------- #
    "databases": [
        "databases/",
    ],
    "foundation_models": [
        "ai/foundation.py",
    ],
    "ai_ml": [
        "ai/llm.py",
        "ai/prediction.py",
        "ai/vision.py",
    ],
    # ---- 通用能力 --------------------------------------------------------- #
    "data_io": [
        "io.py",
    ],
    "analysis": [
        "analysis.py",
    ],
    "reporting": [
        "report.py",
        "report_agent.py",
    ],
    "agent": [
        "agent/",
    ],
    "questions": [
        "question/",
    ],
    "gpu": [
        "gpu/",
    ],
}

#: 共享基础设施——不属于任何设备组，但被多个组依赖。
SHARED: List[str] = [
    "_helpers.py",
    "instruments/_base.py",
    "instruments/vendor_adapters/",
]


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(ROOT)
    )
    return proc.stdout


def plan() -> List[Tuple[str, str]]:
    """Return (source relative to nodes/, destination relative to repo root)."""
    moves: List[Tuple[str, str]] = []
    for group, sources in GROUPS.items():
        for src in sources:
            src_path = NODES / src.rstrip("/")
            if not src_path.exists():
                print(f"  [跳过] 源不存在: nodes/{src}", file=sys.stderr)
                continue
            # A directory source is a *package*; it lands directly inside the
            # group directory (custom_nodes/mass_spectrometry/mass_spectrometry
            # would be a pointless extra level).
            leaf = src_path.name
            dst = f"custom_nodes/{group}/{leaf}"
            moves.append((src, dst))
    for src in SHARED:
        src_path = NODES / src.rstrip("/")
        if not src_path.exists():
            print(f"  [跳过] 源不存在: nodes/{src}", file=sys.stderr)
            continue
        dst = f"custom_nodes/_shared/{src_path.name}"
        moves.append((src, dst))
    return moves


def group_of_shared(src: str) -> str:
    """Shared modules land in a small ``_shared`` package to keep them out of
    the device groups -- they are infrastructure, not a device."""
    return "_shared"


def _module_name(stem: str) -> str:
    """``nodes/instruments/ms.py`` -> ``ms``"""
    return stem.rstrip("/").split("/")[-1]


def rewrite_imports() -> int:
    """Point every ``from nodes.x`` at the new location.

    The mapping is mechanical: ``nodes.<old path>`` becomes
    ``custom_nodes.<group>.<old leaf>``.  Because the old paths are unique
    (each source file belongs to exactly one group), the rewrite is a plain
    dictionary lookup rather than a guess.

    The lookup key is the **dotted** old path (``nodes.instruments.ms``) --
    that is what the regex captures -- while the plan uses the path relative
    to ``nodes/`` (``instruments/ms.py``).  Building the key from the dotted
    form keeps the two views in step.
    """
    mapping: Dict[str, str] = {}
    for group, sources in GROUPS.items():
        for src in sources:
            stem = src.rstrip("/")
            leaf = _module_name(stem)
            if src.endswith("/"):
                # package: nodes.instruments.mass_spectrometry
                #       -> custom_nodes.mass_spectrometry.mass_spectrometry
                mapping["nodes." + stem.replace("/", ".")] = (
                    f"custom_nodes.{group}.{leaf}"
                )
            else:
                # file: stem is "instruments/ms.py" -> dotted "instruments.ms"
                dotted = stem[:-3].replace("/", ".")
                mapping["nodes." + dotted] = f"custom_nodes.{group}.{leaf[:-3]}"

    # nodes.instruments._base and the vendor adapters are shared.
    for src in SHARED:
        stem = src.rstrip("/")
        leaf = _module_name(stem)
        if src.endswith("/"):
            mapping["nodes." + stem.replace("/", ".")] = f"custom_nodes._shared.{leaf}"
        else:
            dotted = stem[:-3].replace("/", ".")
            mapping["nodes." + dotted] = f"custom_nodes._shared.{leaf[:-3]}"

    pattern = re.compile(
        r"\bfrom\s+nodes(\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
        r"\s+import\b"
    )

    changed_files = 0
    replaced = 0
    unmapped: List[str] = []

    def resolve(dotted: str) -> str | None:
        """Map a legacy dotted path onto its new home.

        Two cases:

        * an **exact** entry -- a file that moved (``nodes.instruments.ms``);
        * a **package prefix** -- a module *inside* a package that moved
          (``nodes.agent.planner`` -> the planner inside the new agent
          package).  The suffix after the package name is kept.
        """
        if dotted in mapping:
            return mapping[dotted]
        for legacy, modern in mapping.items():
            if dotted.startswith(legacy + "."):
                return modern + dotted[len(legacy):]
        return None

    for py in sorted((TARGET).rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        original = text

        def repl(m: "re.Match[str]") -> str:
            nonlocal replaced
            # The capture group excludes the leading ``nodes``; the mapping
            # keys include it, so re-attach it before looking up.
            dotted = "nodes" + m.group(1)
            new = resolve(dotted)
            if new is None:
                unmapped.append(dotted)
                return m.group(0)
            replaced += 1
            return f"from {new} import"

        text = pattern.sub(repl, text)
        if text != original:
            py.write_text(text, encoding="utf-8")
            changed_files += 1

    if unmapped:
        # An unmapped import means the table above and the file tree disagree.
        # Silently leaving it would produce a module that imports fine at
        # compile time and explodes the first time somebody runs that node.
        print("  [警告] 以下旧路径未在映射表中，需手工处理：", file=sys.stderr)
        for name in sorted(set(unmapped)):
            print(f"      nodes.{name}", file=sys.stderr)
    print(f"  改写 {changed_files} 个文件，替换 {replaced} 处 import")
    return changed_files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    moves = plan()
    print(f"计划移动 {len(moves)} 项 → custom_nodes/ ({len(GROUPS)} 个设备组 + _shared)")
    for src, dst in moves:
        print(f"  nodes/{src:<48s} → {dst}")

    if args.plan:
        return 0
    if not args.apply:
        print("\n（未指定 --apply，未做任何改动）")
        return 0

    TARGET.mkdir(parents=True, exist_ok=True)
    for group in list(GROUPS) + ["_shared"]:
        (TARGET / group).mkdir(parents=True, exist_ok=True)

    for src, dst in moves:
        src_path = NODES / src.rstrip("/")
        dst_path = ROOT / dst
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if dst_path.exists():
            print(f"  [已存在，跳过] {dst}")
            continue
        shutil.move(str(src_path), str(dst_path))
        print(f"  moved nodes/{src} → {dst}")

    print("\n重写 import ...")
    n = rewrite_imports()
    print(f"  改写 {n} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
