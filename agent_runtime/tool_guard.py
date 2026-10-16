"""Agent tool guard (v0.7.3).

Adapted from the tool-guard idea in Tencent's `Octop
<https://github.com/TencentCloud/Octop>`_, which keeps per-tool allow / deny
rules under ``~/.octop/security/tool_guard/`` and routes every tool call through
them before execution.

What is borrowed
----------------
* **One chokepoint.**  A tool call is classified *before* it runs, not after it
  has already touched the filesystem.  Octop routes every surface (Web, IM,
  cron) through a single processor; here every surface (agent node, agent REST
  endpoint, workflow run) reaches the same :func:`check_tool_call`.
* **Risk classes, not a boolean.**  ``allow`` / ``approval`` / ``deny`` -- a
  delete and a read are not the same decision, and collapsing them into
  "allowed or not" forces the caller to re-derive the distinction anyway.
* **Rules are data.**  Patterns live in a JSON file the user can edit, so the
  policy is inspectable without reading Python.

What is deliberately *not* borrowed
-----------------------------------
Octop is a multi-user server with JWT isolation and interactive approval UI.  A
single-user desktop workflow engine has no second party to approve anything, so
``approval`` here means "the caller must pass ``approved=True``", and the agent
node surfaces that as an explicit refusal rather than silently proceeding.
Inventing a fake approval dialog would be worse than saying no.

The rule set is applied to *node types*, not to shell strings: the platform
already refuses to build shell commands (``simulations/controlled.py``), so the
guard's job is the coarser question of whether a given node may run at all.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "GuardDecision",
    "ToolRule",
    "ToolGuard",
    "DEFAULT_RULES",
    "get_guard",
    "check_tool_call",
]

#: verdicts, ordered from least to most restrictive
VERDICTS = ("allow", "approval", "deny")

#: Repository root, so the policy file is found no matter where the app starts.
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GuardDecision:
    """Why a tool call was allowed, gated or refused.

    ``reason`` is required rather than optional: a guard that returns a bare
    boolean leaves the caller guessing, and the answer ends up in a log nobody
    reads.  ``matched_rule`` names the pattern that decided it (``None`` only
    when the default was used).
    """

    verdict: str
    reason: str
    matched_rule: Optional[str] = None
    #: Populated when ``verdict == "approval"`` -- what the caller must do.
    requires_approval: bool = False

    @property
    def allowed(self) -> bool:
        return self.verdict != "deny"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True)
class ToolRule:
    """One glob rule over node types.

    ``pattern`` is matched with ``fnmatch`` semantics against the **class name**
    (``ORCANode``) and the **type id** (``quantum.orca``), so a rule can be
    written against either without knowing which spelling a caller uses.

    ``forward_looking`` marks a rule that guards a *category* rather than a
    node that exists today -- there is no delete or upload node in the catalogue
    at the moment, but ``ExternalToolNotAllowed`` and the storage router mean one
    could appear.  Such a rule is legitimate; what is not legitimate is writing
    a pattern that looks like it covers something and quietly matches nothing
    (``*Submit*`` does not match ``Submission``).  The flag makes the
    distinction checkable instead of a matter of trust.
    """

    pattern: str
    verdict: str
    reason: str = ""
    forward_looking: bool = False

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(
                f"unknown verdict {self.verdict!r}; expected one of {VERDICTS}"
            )

    def matches(self, *candidates: str) -> bool:
        return any(fnmatch.fnmatch(str(c), self.pattern) for c in candidates if c)


#: Shipped defaults.  Read-only data sources are open; anything that writes to
#: disk, shells out or reaches the network needs an explicit decision.
DEFAULT_RULES: Sequence[ToolRule] = (
    # -- refuse outright ---------------------------------------------------- #
    ToolRule(
        "*Controlled*",
        "deny",
        "受控外部程序执行需显式开启，禁止由 Agent 自主触发。/ "
        "Controlled external-program execution must be enabled explicitly; "
        "an agent may not trigger it on its own.",
        forward_looking=True,
    ),
    ToolRule(
        "*Delete*",
        "deny",
        "删除类节点不可由 Agent 自主运行。/ Delete nodes may not be run by an agent.",
        forward_looking=True,
    ),
    ToolRule(
        "*Upload*",
        "deny",
        "上传类节点会向外部发送数据，需人工确认。/ "
        "Upload nodes send data outward and need a human decision.",
        forward_looking=True,
    ),
    ToolRule(
        # Dotted form for a possible ``category.verb`` type id; see *.export*.
        "*.upload*",
        "deny",
        "上传类节点会向外部发送数据，需人工确认。/ "
        "Upload nodes send data outward and need a human decision.",
        forward_looking=True,
    ),
    # -- needs an explicit approval ---------------------------------------- #
    ToolRule(
        "*Write*",
        "approval",
        "写入类节点改变磁盘状态。/ Write nodes change state on disk.",
        forward_looking=True,
    ),
    ToolRule(
        "*Export*",
        "approval",
        "导出类节点会在工作目录外写出文件。/ "
        "Export nodes write files outside the working directory.",
    ),
    ToolRule(
        # Dotted form: covers a ``category.verb`` type id if one is ever
        # introduced.  Today every node's type id *is* its class name, so this
        # matches nothing -- hence forward_looking.
        "*.export*",
        "approval",
        "导出类节点会在工作目录外写出文件。/ "
        "Export nodes write files outside the working directory.",
        forward_looking=True,
    ),
    ToolRule(
        # ``Submission`` is s-u-b-m-i-s-s-i-o-n: it does not contain the
        # substring "Submit", so the obvious ``*Submit*`` silently matches
        # nothing and lets deliverable-overwriting nodes run unguarded.
        "*Submission*",
        "approval",
        "提交赛题产物会覆盖既有结果。/ "
        "Submission nodes overwrite existing deliverables.",
    ),
    # -- capability rules ---------------------------------------------------- #
    # Matched against the node's declared capabilities, which the caller passes
    # as ``extra_names``.  Grading by capability rather than by class name is
    # what makes these two rules survive a rename or a new node: ORCA, VASP,
    # LLM, PubChem and everything else that shells out or reaches the network
    # are covered without listing them, and a node added tomorrow inherits the
    # decision from what it needs rather than from what it is called.
    ToolRule(
        "*requires_external_software*",
        "approval",
        "外部程序执行节点会启动本机已安装的第三方程序，"
        "耗时、失败原因与授权范围都超出本平台控制。/ "
        "External-program nodes launch third-party software whose runtime, "
        "failure modes and licences are outside this platform's control.",
    ),
    ToolRule(
        "*requires_network*",
        "approval",
        "联网节点会把请求发送到外部服务。/ "
        "Network nodes send requests to external services.",
    ),
    # -- open ---------------------------------------------------------------- #
    ToolRule(
        "*",
        "allow",
        "默认放行只读计算节点。/ Read-only compute nodes are allowed by default.",
    ),
)


class ToolGuard:
    """Evaluates tool calls against an ordered rule list.

    Order matters and is documented rather than emergent: the **first** match
    wins.  A user adding a rule to the top of their file expects it to override
    the shipped defaults, and "most specific match wins" would quietly ignore
    them instead.
    """

    def __init__(self, rules: Optional[Sequence[ToolRule]] = None) -> None:
        self.rules: List[ToolRule] = list(rules if rules is not None else DEFAULT_RULES)

    # -- loading ------------------------------------------------------------ #
    @classmethod
    def from_file(cls, path: Path) -> "ToolGuard":
        """Read rules from JSON, falling back to the defaults on any problem.

        A malformed policy file must not brick the agent: falling back to the
        shipped rules is safer than either crashing or, worse, silently
        treating the file as empty (which would allow everything).
        """
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            raw = payload.get("rules") if isinstance(payload, dict) else payload
            if not isinstance(raw, list):
                raise ValueError("expected a list of rules")
            rules = [
                ToolRule(
                    pattern=str(item["pattern"]),
                    verdict=str(item["verdict"]),
                    reason=str(item.get("reason", "")),
                    forward_looking=bool(item.get("forward_looking", False)),
                )
                for item in raw
            ]
        except (OSError, ValueError, KeyError, TypeError):
            return cls()
        return cls(rules)

    def to_file(self, path: Path) -> Path:
        """Persist the current rules, creating the directory if needed."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "pattern": r.pattern,
                            "verdict": r.verdict,
                            "reason": r.reason,
                            "forward_looking": r.forward_looking,
                        }
                        for r in self.rules
                    ]
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return target

    # -- evaluation ---------------------------------------------------------- #
    def check(
        self,
        node_type: str,
        *,
        approved: bool = False,
        extra_names: Sequence[str] = (),
    ) -> GuardDecision:
        """Classify one call.

        ``extra_names`` lets a caller add context-specific spellings (a workflow
        node's label, an action verb) without the rule author having to guess
        which identifier will be passed.
        """
        candidates = [str(node_type), *[str(n) for n in extra_names if n]]
        for rule in self.rules:
            if not rule.matches(*candidates):
                continue
            if rule.verdict == "approval" and approved:
                return GuardDecision(
                    verdict="allow",
                    reason=(
                        "调用方已显式批准该节点。/ The caller explicitly approved "
                        "this node."
                    ),
                    matched_rule=rule.pattern,
                )
            if rule.verdict == "approval":
                return GuardDecision(
                    verdict="approval",
                    reason=rule.reason
                    or (
                        "该节点需要显式批准。/ This node requires explicit approval."
                    ),
                    matched_rule=rule.pattern,
                    requires_approval=True,
                )
            return GuardDecision(
                verdict=rule.verdict,
                reason=rule.reason or f"matched rule {rule.pattern!r}",
                matched_rule=rule.pattern,
            )
        # Unreachable with the shipped defaults (they end in a catch-all), but a
        # user-supplied file may not -- and an unmatched call must not be a
        # silent allow by accident.
        return GuardDecision(
            verdict="deny",
            reason=(
                "没有规则匹配该节点，默认拒绝。/ No rule matched this node; "
                "denied by default."
            ),
        )

    def describe(self) -> List[Dict[str, str]]:
        return [
            {
                            "pattern": r.pattern,
                            "verdict": r.verdict,
                            "reason": r.reason,
                            "forward_looking": r.forward_looking,
                        }
            for r in self.rules
        ]


_GUARD: Optional[ToolGuard] = None


def get_guard(refresh: bool = False) -> ToolGuard:
    """Process-wide guard, loaded from ``config/tool_guard.json`` when present.

    The path is anchored to the repository root rather than the process CWD:
    the backend is routinely started from the desktop install directory or a
    double-click shortcut, and a CWD-relative lookup would silently fall back
    to the default rules -- a security policy quietly reverting to defaults is
    worse than no policy file at all.
    """
    global _GUARD
    if _GUARD is None or refresh:
        path = ROOT / "config" / "tool_guard.json"
        _GUARD = ToolGuard.from_file(path) if path.exists() else ToolGuard()
    return _GUARD


def _capabilities_of(node_type: str) -> List[str]:
    """The capabilities the registry declares for ``node_type``, if any.

    Looked up here rather than passed in by every caller so that capability
    rules cannot be bypassed by a caller that forgets to supply them -- the
    guard is supposed to be *the* chokepoint, and a chokepoint that the caller
    can accidentally leave open is not one.
    """
    try:
        from nodes.loader import get_registry

        registry = get_registry()
        registry.discover_package("nodes")
        spec = next(
            (s for s in registry.specs() if s.get("type") == str(node_type)), None
        )
        if spec is None:
            return []
        caps = spec.get("capabilities") or []
        return [str(c) for c in caps if c]
    except Exception:
        # A guard that raises on an unknown node would turn "is this allowed?"
        # into a crash.  An empty answer falls through to the name rules.
        return []


def check_tool_call(
    node_type: str, *, approved: bool = False, extra_names: Sequence[str] = ()
) -> GuardDecision:
    """The single chokepoint every caller goes through.

    The node's declared capabilities are always added to the candidate names so
    the capability rules apply without the caller doing anything.
    """
    candidates = [*extra_names, *_capabilities_of(node_type)]
    return get_guard().check(node_type, approved=approved, extra_names=candidates)