"""Version consistency tool (spec task P0-04).

A release is only trustworthy when **every** artefact agrees on one version.
``chemml_version.py`` is the single source of truth; this script either proves
all the derived artefacts agree with it (``--check``) or stamps the ones it can
safely rewrite (``--write``).

Coverage is deliberately broad.  v0.7.1 proved the failure mode: a version that
lives in a dozen files *will* drift, and a release report quoting a version no
artefact carries cannot be traced.  The sweep below therefore reaches the
backend, the registry, the engine, the memory store, both Node SDKs, the
Electron shell, the frontend bundle (via a Vite define, not a literal), the
workflow fixtures and the human-facing documents.

Usage::

    python scripts/version.py --check     # exit 1 on any drift
    python scripts/version.py --write     # stamp package.json + JSON artefacts
    python scripts/version.py --show      # print the resolved version + commit
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chemml_version import VERSION, build_metadata  # noqa: E402

#: Modules that must *import* the version rather than restate it.  A literal is
#: tolerated only when it sits next to that import, as a package-standalone
#: fallback (e.g. ``node_sdk`` installed without the monorepo on ``sys.path``).
PY_IMPORT_TARGETS: List[Tuple[str, str]] = [
    ("backend/app.py", "VERSION|_*version_*"),
    ("node_registry/__init__.py", "__version__|_*version_*"),
    ("workflow_engine/__init__.py", "__version__"),
    ("workflow_engine/node_base.py", "_PLATFORM_VERSION"),
    ("custom_nodes/agent/__init__.py", "__version__"),
    ("memory/__init__.py", "__version__"),
    ("node_sdk/python/chemml_sdk/__init__.py", "__version__"),
]

#: Modules that legitimately keep a literal (no monorepo import available) but
#: whose literal must still equal ``VERSION``.  Kept explicit so an omission is
#: a visible choice rather than an oversight.
#:
#: v0.7.2 (ISSUE-18): ``nodes/report.py`` was removed from this list.  It used
#: to carry ``version = "0.7.2"`` on three classes; nodes now inherit the
#: platform version from ``workflow_engine.node_base``, so there is no literal
#: left to pin and keeping an entry here only produced a false alarm.
PY_LITERAL_TARGETS: List[Tuple[str, str]] = []

#: (label, relative path, regex with exactly one capture group for the version)
TEXT_TARGETS: List[Tuple[str, str, str]] = [
    ("README title", "README.md", r"^#\s*Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)"),
    ("本地安装说明 title", "本地安装说明.md", r"^#\s*Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)"),
    ("本地安装说明 version line", "本地安装说明.md", r"版本：\*\*v?([0-9]+\.[0-9]+\.[0-9]+)\*\*"),
    ("requirements header", "requirements.txt", r"^#\s*Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)"),
    ("Python SDK README", "node_sdk/python/README.md", r"Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)"),
]

#: (label, relative path, regex, required) -- **every** match of ``regex`` must
#: equal ``VERSION``, not just the first one.
#:
#: Added in v0.7.2 (ISSUE-18).  The released package was found to print
#: ``Chem ML Platform v0.6.0`` on the launcher banner and to title the browser
#: tab ``v0.7.1`` while the product reported ``0.7.2`` -- and this script said
#: ``OK``, because none of these files was in the sweep.  A version assertion
#: that only inspects the places you remembered is worse than none: it converts
#: an unknown state into a false clean bill of health.
#:
#: ``required=False`` marks build output that legitimately may be absent from a
#: source checkout (the frontend bundle), so a fresh clone still checks clean.
ALL_TEXT_TARGETS: List[Tuple[str, str, str, bool]] = [
    ("launcher banner (browser)", "start-platform.bat", r"Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("launcher banner (desktop)", "start-desktop.bat", r"Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("launcher banner (installer)", "install.bat", r"Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("browser tab title", "frontend/index.html", r"Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("browser tab title (built)", "frontend/dist/index.html", r"Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)", False),
    ("docker README heading", "docker/README.md", r"^#\s*部署：Docker（v([0-9]+\.[0-9]+\.[0-9]+)）", True),
    ("docker README image section", "docker/README.md", r"^##\s*镜像内容（v([0-9]+\.[0-9]+\.[0-9]+)）", True),
    ("docker README health sample", "docker/README.md", r'"version"\s*:\s*"([0-9]+\.[0-9]+\.[0-9]+)"', True),
    ("docker README image tag", "docker/README.md", r"chem-ml-platform:([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("root compose header", "docker-compose.yml", r"^#\s*Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("root compose image tag", "docker-compose.yml", r"chem-ml-platform:([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("docker compose header", "docker/docker-compose.yml", r"^#\s*Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("docker compose image tag", "docker/docker-compose.yml", r"chem-ml-platform:([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("Electron shell description", "desktop/package.json", r"Platform v([0-9]+\.[0-9]+\.[0-9]+)", True),
    # v0.7.3 audit P1-3: the release documents are versioned claims about the
    # current build, and they drifted silently -- ``docs/PROVENANCE.md`` still
    # titled itself v0.7.2 while the product reported 0.7.3, and this script
    # said ``OK`` because the file was not in the sweep.  Same failure mode as
    # ISSUE-18: a version assertion that only inspects the places you
    # remembered converts an unknown state into a false clean bill of health.
    ("provenance record", "docs/PROVENANCE.md", r"来源与许可证记录（v([0-9]+\.[0-9]+\.[0-9]+)", True),
    ("provenance version table", "docs/PROVENANCE.md", r"\|\s*版本\s*\|\s*([0-9]+\.[0-9]+\.[0-9]+)", True),
    # Only the *first* changelog entry is a claim about the current build;
    # older ones are history and must keep their own numbers, so this target
    # is checked separately (see CHANGELOG_TOP below) rather than swept.
    ("release report", "docs/V07_4_RELEASE_REPORT.md", r"^\s*-\s*\*\*版本\*\*.*?([0-9]+\.[0-9]+\.[0-9]+)", False),
]

#: (label, relative path, regex) checked against the **first** match only.
#:
#: Used for documents that legitimately quote several versions -- a changelog's
#: newest entry is a claim about the build being released, while its older
#: entries are history that must keep its own numbers.  Sweeping every match
#: would demand the project delete its own past.
CHANGELOG_TOP: List[Tuple[str, str, str]] = [
    ("changelog top entry", "CHANGELOG.md", r"^##\s*\[([0-9]+\.[0-9]+\.[0-9]+)\]"),
]

#: (label, relative path, json path) -- the value at ``json path`` must equal VERSION.
JSON_TARGETS: List[Tuple[str, str, Tuple[Any, ...]]] = [
    ("desktop package", "desktop/package.json", ("version",)),
    ("frontend package", "frontend/package.json", ("version",)),
    ("frontend lock (root)", "frontend/package-lock.json", ("version",)),
    ("frontend lock (packages)", "frontend/package-lock.json", ("packages", "", "version")),
    ("nodejs SDK package", "node_sdk/nodejs/package.json", ("version",)),
]

#: Files whose *description* string embeds the version in prose.  Checked so the
#: published metadata does not advertise a version the code does not report.
DESCRIPTION_TARGETS: List[Tuple[str, str, str]] = [
    ("desktop description", "desktop/package.json", r"v([0-9]+\.[0-9]+\.[0-9]+)"),
    ("frontend description", "frontend/package.json", r"v([0-9]+\.[0-9]+\.[0-9]+)"),
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _dig(data: Any, path: Tuple[Any, ...]) -> Any:
    for key in path:
        if isinstance(data, dict):
            if key not in data:
                return None
            data = data[key]
        elif isinstance(data, list):
            if not isinstance(key, int) or key >= len(data):
                return None
            data = data[key]
        else:
            return None
    return data


def _set_dig(data: Any, path: Tuple[Any, ...], value: Any) -> bool:
    for key in path[:-1]:
        if not isinstance(data, dict) or key not in data:
            return False
        data = data[key]
    if not isinstance(data, dict) or path[-1] not in data:
        return False
    if data[path[-1]] == value:
        return False
    data[path[-1]] = value
    return True


def collect_drift() -> List[str]:
    """Every place a version string disagrees with ``chemml_version``."""
    drift: List[str] = []

    # 1. Python modules must *import* the version, not restate it.
    for rel, key in PY_IMPORT_TARGETS:
        path = ROOT / rel
        if not path.exists():
            drift.append(f"{rel}: missing file")
            continue
        text = _read(path)
        if re.search(rf'^\s*(?:{key})\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"', text, re.M):
            if "chemml_version" not in text:
                drift.append(
                    f"{rel}: hard-codes a version literal instead of importing chemml_version"
                )

    # 2. Literal-carrying Python modules.
    for rel, pattern in PY_LITERAL_TARGETS:
        path = ROOT / rel
        if not path.exists():
            drift.append(f"{rel}: missing file")
            continue
        match = re.search(pattern, _read(path), re.M)
        if not match:
            drift.append(f"{rel}: no version found by pattern {pattern!r}")
        elif match.group(1) != VERSION:
            drift.append(f"{rel}: {match.group(1)} != {VERSION}")

    # 3. Free-text artefacts.
    for label, rel, pattern in TEXT_TARGETS:
        path = ROOT / rel
        if not path.exists():
            drift.append(f"{label}: missing file {rel}")
            continue
        match = re.search(pattern, _read(path), re.M)
        if not match:
            drift.append(f"{label}: no version found by pattern {pattern!r}")
        elif match.group(1) != VERSION:
            drift.append(f"{label}: {match.group(1)} != {VERSION}")

    # 3b. Files where *every* occurrence must agree (v0.7.2, ISSUE-18).
    for label, rel, pattern, required in ALL_TEXT_TARGETS:
        path = ROOT / rel
        if not path.exists():
            if required:
                drift.append(f"{label}: missing file {rel}")
            continue
        found = re.findall(pattern, _read(path), re.M)
        if not found:
            drift.append(f"{label}: no version found by pattern {pattern!r}")
            continue
        stale = sorted({value for value in found if value != VERSION})
        if stale:
            drift.append(
                f"{label} ({rel}): {', '.join(stale)} != {VERSION} "
                f"({len(stale)} distinct of {len(found)} occurrence(s))"
            )

    # 3c. Documents where only the *first* match must agree (v0.7.3, audit P1-3).
    for label, rel, pattern in CHANGELOG_TOP:
        path = ROOT / rel
        if not path.exists():
            drift.append(f"{label}: missing file {rel}")
            continue
        match = re.search(pattern, _read(path), re.M)
        if not match:
            drift.append(f"{label}: no version found by pattern {pattern!r}")
        elif match.group(1) != VERSION:
            drift.append(f"{label}: {match.group(1)} != {VERSION}")

    # 4. JSON manifests.
    for label, rel, jpath in JSON_TARGETS:
        path = ROOT / rel
        if not path.exists():
            drift.append(f"{label}: missing file {rel}")
            continue
        try:
            data = json.loads(_read(path))
        except ValueError as exc:
            drift.append(f"{label}: unparsable JSON ({exc})")
            continue
        found = _dig(data, jpath)
        if found is None:
            drift.append(f"{label}: no version at {'.'.join(str(p) for p in jpath)}")
        elif str(found) != VERSION:
            drift.append(f"{label}: {found} != {VERSION}")

    # 5. Prose descriptions that advertise a version.
    for label, rel, pattern in DESCRIPTION_TARGETS:
        path = ROOT / rel
        if not path.exists():
            continue
        match = re.search(pattern, _read(path))
        if match and match.group(1) != VERSION:
            drift.append(f"{label}: advertises v{match.group(1)} != v{VERSION}")

    # 6. Shipped workflow artefacts.
    for path in sorted((ROOT / "workflows").glob("*.json")):
        try:
            data = json.loads(_read(path))
        except ValueError:
            continue
        found = str(data.get("version", ""))
        if found and found != VERSION:
            drift.append(f"workflows/{path.name}: {found} != {VERSION}")

    # 6b. The node catalogue (v0.7.2, ISSUE-18).  Every node used to restate the
    # platform version as a class literal, so the generated catalogue advertised
    # 0.7.1 next to a product reporting 0.7.2.  Nodes now inherit the version
    # from ``workflow_engine.node_base``; this asserts the generated artefact
    # agrees, so a future reintroduction of the literal is caught here.
    registry = ROOT / "node_registry" / "registry.json"
    if registry.exists():
        try:
            reg = json.loads(_read(registry))
        except ValueError:
            drift.append("node_registry/registry.json: unparsable JSON")
        else:
            nodes = reg.get("nodes") or []
            if not nodes:
                drift.append("node_registry/registry.json: no nodes recorded")
            stale_nodes = sorted(
                {
                    str(n.get("version", ""))
                    for n in nodes
                    if str(n.get("version", "")) not in {"", VERSION}
                }
            )
            if stale_nodes:
                drift.append(
                    f"node_registry/registry.json: node versions {', '.join(stale_nodes)} "
                    f"!= {VERSION} (regenerate with `python -m node_registry --write`)"
                )
    else:
        drift.append("node_registry/registry.json: missing file")

    # 7. CHANGELOG must document the version.
    #
    # v0.7.2 (ISSUE-18): this block used to read CHANGELOG.md from the ``else``
    # branch unconditionally, so a missing changelog raised FileNotFoundError
    # instead of being reported as drift.  A checker that crashes on the very
    # condition it exists to report is a checker you cannot trust.
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.exists():
        drift.append("CHANGELOG.md: missing file")
    else:
        text = _read(changelog)
        if f"[{VERSION}]" not in text:
            drift.append(f"CHANGELOG.md: no '[{VERSION}]' section")
        else:
            # and the *first* documented release must be this one (no stale "latest")
            first = re.search(r"^##\s*\[[^\]]*?([0-9]+\.[0-9]+\.[0-9]+)", text, re.M)
            if first and first.group(1) != VERSION:
                drift.append(f"CHANGELOG.md: newest section is {first.group(1)}, expected {VERSION}")

    return drift


def stamp() -> List[str]:
    """Rewrite the machine-writable artefacts to carry ``VERSION``."""
    changed: List[str] = []

    for label, rel, jpath in JSON_TARGETS:
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            data = json.loads(_read(path))
        except ValueError:
            continue
        if _set_dig(data, jpath, VERSION):
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            changed.append(f"{rel}::{'.'.join(str(p) for p in jpath)}")

    for path in sorted((ROOT / "workflows").glob("*.json")):
        text = _read(path)
        new = re.sub(r'("version"\s*:\s*")[^"]*(")', rf"\g<1>{VERSION}\g<2>", text, count=1)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(f"workflows/{path.name}")

    # v0.7.2 (ISSUE-18): rewrite the user-visible version strings too.  Only the
    # captured group is substituted inside the full match, so surrounding prose
    # (``Chem ML Platform v``, ``chem-ml-platform:``, ``（v``) is preserved.
    for label, rel, pattern, required in ALL_TEXT_TARGETS:
        path = ROOT / rel
        if not path.exists():
            continue
        # A build artefact is regenerated by its own tool, never stamped here.
        if not required:
            continue
        text = _read(path)
        new = re.sub(
            pattern,
            lambda m: m.group(0).replace(m.group(1), VERSION),
            text,
            flags=re.M,
        )
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(f"{rel} [{label}]")

    # v0.7.3: ``TEXT_TARGETS`` used to be checked by ``collect_drift`` but never
    # written by ``stamp``, so the README title, the local-install guide, the
    # requirements header and the Python SDK README were reported as drift and
    # then left untouched by the very command advertised as fixing them --
    # "stamped 0 artefact(s)" while nine items were on the list.  A repair tool
    # that cannot repair half of what it reports is a trap: the obvious next
    # step is to hand-edit five files, and the next one after that is to stop
    # trusting the check.
    for label, rel, pattern in TEXT_TARGETS:
        path = ROOT / rel
        if not path.exists():
            continue
        text = _read(path)
        new = re.sub(
            pattern,
            lambda m: m.group(0).replace(m.group(1), VERSION),
            text,
            flags=re.M,
        )
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(f"{rel} [{label}]")

    # The package ``description`` fields embed the version in prose and were
    # checked but never stamped, for the same reason as ``TEXT_TARGETS``.
    for label, rel, pattern in DESCRIPTION_TARGETS:
        path = ROOT / rel
        if not path.exists():
            continue
        text = _read(path)
        new = re.sub(
            pattern,
            lambda m: m.group(0).replace(m.group(1), VERSION),
            text,
            flags=re.M,
        )
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(f"{rel} [{label}]")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Chem ML Platform version tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="fail on any version drift")
    group.add_argument("--write", action="store_true", help="stamp derived artefacts")
    group.add_argument("--show", action="store_true", help="print version + commit")
    parser.add_argument("--json", help="write the drift report as JSON to this path")
    args = parser.parse_args()

    if args.show:
        meta = build_metadata()
        print(f"{meta['version']} ({meta['codename']}) commit={meta['commit']}")
        return 0

    if args.write:
        changed = stamp()
        print(f"stamped {len(changed)} artefact(s): {', '.join(changed) or 'none'}")
        # What ``stamp`` genuinely cannot fix, so the message names it instead of
        # gesturing at a list the reader has to guess at.
        remaining = collect_drift()
        if remaining:
            print("still needs a manual edit:")
            for item in remaining:
                print(f"  - {item}")
        return 0

    drift = collect_drift()
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {"version": VERSION, "commit": build_metadata()["commit"], "drift": drift},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if drift:
        print(f"VERSION DRIFT: {VERSION}")
        for item in drift:
            print(f"  - {item}")
        return 1
    print(f"OK: every artefact agrees on {VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
