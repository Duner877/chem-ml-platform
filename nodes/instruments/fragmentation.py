"""Fragmentation pathway deduction node (v0.7.2).

Wraps :mod:`models.fragmentation` -- the deterministic rule engine -- into the
workflow graph, and optionally asks the AI runtime to *interpret* the result.

The division of labour is deliberate:

* the **rules engine** produces the pathway (which peaks, which cleavage, which
  confidence).  It needs no network and always answers;
* the **AI runtime** produces a narrative *about* that pathway.  When no
  provider is reachable the node still returns the pathway and says so in
  ``metadata["engine"]`` -- the deduction is never lost because a model was
  offline.

This mirrors the platform's existing honesty contract: the engine that actually
answered is always recorded, and an offline answer is never dressed up as an
online one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.fragmentation import (
    DEFAULT_TOLERANCE_PPM,
    build_prompt,
    deduce_pathway,
    deduce_without_structure,
    summarise_pathway,
)
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Molecule, ScientificObject, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

__all__ = ["FragmentationPathwayNode"]


def _first(items: Any) -> Any:
    """First element of a ``multi`` port value, whatever shape it arrived in.

    A single edge into a ``multi`` port delivers *one* object, not a list (see
    the v0.7.2 note in ``nodes/agent/agent.py``), and Pydantic models are
    iterable, so a naive ``next(iter(x))`` walks field pairs instead of the
    value.  Normalise all three shapes explicitly.
    """
    if items is None:
        return None
    if isinstance(items, ScientificObject) or isinstance(items, (str, bytes)):
        return items
    if isinstance(items, (list, tuple)):
        return items[0] if items else None
    return None


def _collect(items: Any) -> List[Any]:
    """Every object behind a ``multi`` port, for any of the three shapes."""
    if items is None:
        return []
    if isinstance(items, ScientificObject) or isinstance(items, (str, bytes, dict)):
        return [items]
    if isinstance(items, (list, tuple)):
        return list(items)
    return []


def _find_spectrum(value: Any) -> Optional[Spectrum]:
    for item in _collect(value):
        if isinstance(item, Spectrum):
            return item
    return None


def _find_molecule(value: Any) -> Optional[Molecule]:
    for item in _collect(value):
        if isinstance(item, Molecule):
            return item
    return None


@register_node
class FragmentationPathwayNode(ScientificNode):
    """Deduce the fragmentation pathway of a mass spectrum.

    Inputs
    ------
    ``spectrum``
        The measured (or simulated) mass spectrum.  Optional so the node can be
        dropped before a file has been loaded; it then fails with an honest
        ``NodeInputError`` instead of producing an empty pathway.
    ``molecule``
        Optional candidate structure.  **With** it the search proposes
        structure-specific bond cleavages; **without** it, only neutral-loss
        relationships between the observed peaks are reported -- the node never
        invents a structure.

    Outputs
    -------
    ``pathway``  Table  -- one row per deduced fragment
    ``steps``    Text   -- the rule-engine narrative
    ``text``     Text   -- the AI narrative when a model answered, else the same
                          rule-engine narrative with an explicit note
    """

    name = "Fragmentation Pathway"
    category = "Analysis/Mass Spectrometry"
    description = (
        "由实测质谱推导裂解链路：按 CID 规则枚举中性丢失与结构可行的键断裂位点，"
        "与观测峰按质量容差匹配并给出每步置信度；可再由 AI 助手解读证据链。"
    )
    tags = ["ms", "msms", "fragmentation", "cid", "pathway", "neutral-loss"]
    icon = "FP"
    capabilities = ["deduces_fragmentation_pathway"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports: List[Port] = [
        Port("spectrum", "Spectrum", "待解析的质谱图", optional=True, multi=True),
        Port("molecule", "Molecule", "候选结构（可选，决定是否做结构化推导）", optional=True, multi=True),
    ]
    output_ports = [
        Port("pathway", "Table", "裂解链路各步（规则 / 碎片式/ m/z / 误差 / 置信度）"),
        Port("steps", "Text", "规则引擎的推导说明"),
        Port("text", "Text", "AI 助手对证据链的解读（无模型时为规则引擎说明）"),
    ]

    parameters = [
        ParameterSpec(
            "adduct", "enum", "[M+H]+", "前体加合离子",
            options=["[M]+", "[M+H]+", "[M+Na]+", "[M+K]+", "[M+NH4]+", "[M-H]-", "[M+FA-H]-"],
        ),
        ParameterSpec(
            "tolerance_ppm", "number", DEFAULT_TOLERANCE_PPM, "质量匹配容差", unit="ppm",
            min=1.0, max=500.0, step=1.0,
        ),
        ParameterSpec("max_steps", "integer", 8, "最多输出几步", min=1, max=40),
        ParameterSpec(
            "max_depth", "integer", 2, "中性丢失阶梯的最大层数", min=1, max=4,
            advanced=True,
        ),
        ParameterSpec(
            "min_relative", "number", 0.01, "参与匹配的最小相对强度", min=0.0, max=1.0,
            step=0.005,
        ),
        ParameterSpec("use_ai", "boolean", True, "调用 AI 助手解读证据链（不可用时自动回退）"),
        ParameterSpec(
            "language", "enum", "zh", "解读语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectrum = _find_spectrum(inputs.get("spectrum"))
        if spectrum is None:
            raise NodeInputError(
                "FragmentationPathwayNode: connect a Spectrum to the 'spectrum' port"
            )

        molecule = _find_molecule(inputs.get("molecule"))
        smiles = str(getattr(molecule, "smiles", "") or "") if molecule else ""
        adduct = str(self.get_param("adduct", "[M+H]+"))
        language = str(self.get_param("language", "zh") or "zh")
        tolerance = float(self.get_param("tolerance_ppm", DEFAULT_TOLERANCE_PPM))
        max_steps = int(self.get_param("max_steps", 8))
        max_depth = int(self.get_param("max_depth", 2))
        min_relative = float(self.get_param("min_relative", 0.01))

        if smiles:
            pathway = deduce_pathway(
                spectrum,
                smiles,
                adduct=adduct,
                tolerance_ppm=tolerance,
                max_steps=max_steps,
                min_relative=min_relative,
                max_depth=max_depth,
            )
        else:
            # No structure: the honest, structure-free deduction.
            pathway = deduce_without_structure(
                spectrum, max_steps=max_steps, min_relative=min_relative
            )

        rules_text = summarise_pathway(dict(pathway), language=language)
        table = self._table(pathway)
        narrative, engine = self._narrative(pathway, rules_text, language)

        self.log(
            f"pathway: {pathway.get('matched_peaks', 0)}/"
            f"{pathway.get('observed_peaks', 0)} peaks matched, "
            f"confidence {pathway.get('confidence')}, engine {engine}"
        )
        if not pathway.get("ok"):
            self.log(f"no pathway: {pathway.get('reason', '')}")

        steps = Text(
            name="fragmentation pathway (rules)",
            text=rules_text,
            language=language,
            data=dict(pathway),
        )
        return {
            "pathway": table,
            "steps": steps,
            "text": Text(
                name="fragmentation pathway interpretation",
                text=narrative,
                language=language,
                data={"engine": engine, "confidence": pathway.get("confidence", 0.0)},
            ),
        }

    # -- helpers ------------------------------------------------------------ #
    def _table(self, pathway: Dict[str, Any]) -> Table:
        rows: List[List[Any]] = []
        for entry in pathway.get("steps", []):
            rows.append(
                [
                    entry.get("step", 0),
                    entry.get("rule", ""),
                    entry.get("fragment_formula", "") or entry.get("loss_da", ""),
                    entry.get("observed_mz", 0.0),
                    entry.get("loss_da", 0.0),
                    round(float(entry.get("relative_intensity", 0.0)) * 100.0, 2),
                    entry.get("mass_error_ppm", 0.0),
                    entry.get("confidence", 0.0),
                    entry.get("rationale", ""),
                ]
            )
        return Table(
            name="fragmentation pathway",
            columns=[
                "step",
                "rule",
                "fragment",
                "observed m/z",
                "loss (Da)",
                "rel. %",
                "error (ppm)",
                "confidence",
                "rationale",
            ],
            rows=rows,
            metadata={
                "engine": pathway.get("engine", "internal:fragmentation-rules"),
                "confidence": pathway.get("confidence", 0.0),
                "precursor_mz": pathway.get("precursor_mz"),
                "structure_known": pathway.get("structure_known", False),
            },
        )

    def _narrative(
        self, pathway: Dict[str, Any], rules_text: str, language: str
    ) -> tuple[str, str]:
        """AI interpretation, or the rule text when no model is reachable."""
        if not bool(self.get_param("use_ai", True)) or not pathway.get("ok"):
            return rules_text, str(pathway.get("engine", "internal:fragmentation-rules"))

        try:
            import ai_runtime

            completion = ai_runtime.complete(
                build_prompt(dict(pathway), language=language),
                family="auto",
                context=rules_text,
            )
        except Exception as exc:  # noqa: BLE001 - a model failure must not lose the pathway
            self.log(f"AI narrative unavailable ({exc}); keeping the rule-engine text")
            return rules_text, str(pathway.get("engine", "internal:fragmentation-rules"))

        text = str(getattr(completion, "text", "") or "").strip()
        engine = str(getattr(completion, "engine", "") or "offline")
        if not text:
            return rules_text, str(pathway.get("engine", "internal:fragmentation-rules"))

        # The offline provider answers with a generic string; when it does, the
        # engine label says "offline" and the rules text is still the real
        # content, so keep both.
        if engine in ("offline", "internal", ""):
            header = (
                "以下解读由内置规则引擎给出（当前无可用 AI 供应商）：\n\n"
                if language != "en"
                else "Interpretation from the built-in rule engine "
                "(no AI provider available):\n\n"
            )
            return header + rules_text, "internal:fragmentation-rules"

        label = f"[{engine}]" if language != "en" else f"[{engine}]"
        separator = "\n\n---\n\n" if language != "en" else "\n\n---\n\n"
        return (
            f"{label}\n{text}{separator}"
            + ("规则引擎原始推导：\n" if language != "en" else "Raw rule-engine derivation:\n")
            + rules_text,
            f"external:{engine}",
        )