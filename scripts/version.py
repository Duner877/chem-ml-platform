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
    ("memory/__init__.py", "__version__"),
    ("node_sdk/python/chemml_sdk/__init__.py", "__version__"),
]

#: Modules that legitimately keep a literal (no monorepo import available) but
#: whose literal must still equal ``VERSION``.  Kept explicit so an omission is
#: a visible choice rather than an oversight.
PY_LITERAL_TARGETS: List[Tuple[str, str]] = [
    ("nodes/report.py", r'version\s*=\s*"([0-9][^"]*)"'),
]

#: (label, relative path, regex with exactly one capture group for the version)
TEXT_TARGETS: List[Tuple[str, str, str]] = [
    ("README title", "README.md", r"^#\s*Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)"),
    ("本地安装说明 title", "本地安装说明.md", r"^#\s*Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)"),
    ("本地安装说明 version line", "本地安装说明.md", r"版本：\*\*v?([0-9]+\.[0-9]+\.[0-9]+)\*\*"),
    ("requirements header", "requirements.txt", r"^#\s*Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)"),
    ("Python SDK README", "node_sdk/python/README.md", r"Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)"),
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

    # 7. CHANGELOG must document the version.
    changelog = ROOT / "CHANGELOG.md"
    if changelog.exists() and f"[{VERSION}]" not in _read(changelog):
        drift.append(f"CHANGELOG.md: no '[{VERSION}]' section")
    else:
        # and the *first* documented release must be this one (no stale "latest")
        first = re.search(r"^##\s*\[[^\]]*?([0-9]+\.[0-9]+\.[0-9]+)", _read(changelog), re.M)
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
        if changed:
            print("note: README / CHANGELOG / requirements / SDK headers need a manual edit")
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
