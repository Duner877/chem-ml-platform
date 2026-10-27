#!/usr/bin/env python
"""Third-party licence, NOTICE and SBOM generator (v0.7.1 task K).

The v0.7.1 task specification requires an *auditable* open-source distribution
record: dependency lists, licence reports and an SBOM generated from the **real**
installed / locked dependency metadata rather than a hardcoded list.

This script inventories four ecosystems and writes three artefacts:

===============  ==========================================================
inventory        source of truth
===============  ==========================================================
Python runtime   ``requirements.txt`` resolved through ``importlib.metadata``
Frontend         ``frontend/package-lock.json`` (real locked versions + licence)
External tools   ``simulations.controlled.TOOL_ALLOWLIST`` (never bundled)
Sample data      ``datasets/**/*.metadata.json`` (source, generator, licence)
===============  ==========================================================

Outputs (all relative to the repository root):

* ``sbom.json``                  -- CycloneDX-flavoured component inventory
* ``NOTICE``                     -- third-party notices required for distribution
* ``docs/THIRD_PARTY_LICENSES.md`` -- human readable licence report

It also runs a distribution-cleanliness scan (secrets, private data, build
caches, duplicated assets) so ``--check`` can act as a release gate.

Usage
-----
    python scripts/license_report.py                 # write the artefacts
    python scripts/license_report.py --check         # non-zero exit on a problem
    python scripts/license_report.py --print         # also print the summary
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chemml_version import VERSION as _VERSION  # noqa: E402

PROJECT_NAME = "Chem ML Platform"
#: Single source of truth (spec P0-04).  v0.7.1 hard-coded this and the NOTICE
#: shipped with the previous version number.
PROJECT_VERSION = _VERSION
PROJECT_LICENSE = "Apache-2.0"

#: Copyright holder.  This used to be the literal string
#: ``"{PROJECT_NAME} contributors"``, which named nobody -- an Apache-2.0
#: NOTICE whose holder is a placeholder tells a reader who may redistribute
#: this and under what name exactly nothing, and the LICENSE shipped the
#: template's own ``[yyyy] [name of copyright owner]`` for the same reason.
#: Set here so the two files cannot drift apart again.
#:
#: v0.7.4: the holder is the project author.  The GitHub *account* is
#: ``Duner877`` (it is the owner of the repository the code lives in, and it
#: appears in clone URLs); the *name* the software is published under is
#: ``Duner``.  Keeping the two apart is deliberate: renaming the account would
#: break every clone URL and the update checker's owner lookup, neither of
#: which is what a copyright notice is for.
COPYRIGHT_HOLDER = "Duner"

#: licences that require a human review before distribution (strong copyleft)
_REVIEW_LICENCES = ("GPL", "AGPL", "SSPL", "CC-BY-NC", "BUSL", "Commons Clause")

#: Upstream projects whose *approach* is reimplemented in this codebase.
#:
#: Apache-2.0 requires attribution only for redistributed Apache-2.0 material,
#: and nothing upstream is redistributed here -- so this table is not a licence
#: obligation, it is a traceability record.  It is nevertheless the kind of
#: thing that is expensive to reconstruct later and cheap to state now: a
#: reader who finds ``agent_runtime/tool_guard.py`` and recognises the design
#: should be able to read what was taken and what was not, instead of guessing
#: whether the omission is carelessness or an accident.  The ``borrowed`` /
#: ``not_taken`` split is the useful half: "adapted from X" on its own tells a
#: reader nothing about whether the strict parts survived.
UPSTREAM_ATTRIBUTIONS: Tuple[Dict[str, str], ...] = (
    {
        "module": "agent_runtime/tool_guard.py, agent_runtime/tasks.py",
        "upstream": "TencentCloud/Octop <https://github.com/TencentCloud/Octop>",
        "license": "MIT",
        "borrowed": (
            "the tool-guard shape -- one chokepoint every tool call passes "
            "through before it runs, risk classes (allow / approval / deny) "
            "rather than a boolean, and rules held in an editable data file"
        ),
        "not_taken": (
            "the multi-user server machinery: JWT isolation, the interactive "
            "approval UI, and the ~/.octop storage layout.  Here `approval` "
            "means the caller must pass approved=True"
        ),
    },
)

#: patterns that must never appear in a release package
_SECRET_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI-style API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----", "private key"),
    (r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']", "inline credential"),
)
_SECRET_ALLOW_FILES = {
    "config/ai.example.json",
    # v0.7.3: the two scanners necessarily *contain* the shapes they look for.
    # ``package.py`` defines the archive's secret patterns and
    # ``license_report.py`` defines these ones; flagging them would mean the
    # build fails every time someone hardens the scanner, and the fix people
    # reach for under that pressure is to weaken the pattern -- which is the
    # exact opposite of the intent.  The exemption is by explicit path, so a
    # real key pasted into either file is still caught by
    # ``scripts/package.py``'s own scan, which does not exempt them.
    "scripts/package.py",
    "scripts/license_report.py",
}

#: cleanliness buckets that are informational and never block a release.
#: ``pyc`` / ``pycache`` are included because ``scripts/package.py`` already
#: excludes them from the archive; their presence in a working tree (regenerated
#: by every test run) is reported but must not fail the licence gate.  The
#: authoritative release check is ``check_release_cleanliness`` which applies the
#: real packager rule.
_INFO_KEYS = {"generated_assets", "runtime_data", "pyc", "pycache"}

#: Every cleanliness bucket, in the order the report lists them.
#:
#: The list is fixed rather than derived from the scan result.  A bucket that
#: only appears when the scan hits it (``runtime_data``, ``generated_assets``)
#: would make the *number of lines* in the licence report depend on the state
#: of the machine that generated it -- so a CI runner and a developer machine
#: would produce documents of different lengths and the release check would
#: report drift for a file nobody had touched.
_CLEANLINESS_BUCKETS = (
    "pyc",
    "pycache",
    "secrets",
    "private_data",
    "duplicate_assets",
    "runtime_data",
    "generated_assets",
)


# --------------------------------------------------------------------------- #
# Python inventory
# --------------------------------------------------------------------------- #
def _parse_requirement(line: str) -> Optional[str]:
    """Return the distribution name declared on ``line`` (``None`` for comments)."""
    text = line.split("#", 1)[0].strip()
    if not text:
        return None
    text = text.split(";", 1)[0].strip()  # drop environment markers
    match = re.match(r"([A-Za-z0-9_.\-]+)", text)
    return match.group(1) if match else None


#: A dependency line, as opposed to the prose that surrounds it in a comment.
#: Requires a version specifier or an environment marker, so
#: "The platform runs with the packages below" is not mistaken for a package.
_PIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[^\]]*\])?\s*[<>=!~;]")


def _expand_requirements(path: Path, seen: Optional[set] = None) -> List[Tuple[str, bool]]:
    """Expand a requirements file, following ``-r`` includes.

    ``requirements.txt`` is a *manifest of groups* (spec P0-04): it contains only
    ``-r`` lines.  Reading it literally made the licence report resolve two
    packages named ``-r requirements.runtime.txt`` and report them as unresolved,
    so the include syntax has to be followed properly.

    Returns ``(line, optional)`` where ``optional`` marks entries that are
    declared for information only (the optional accelerator group).
    """
    seen = seen if seen is not None else set()
    resolved = path.resolve()
    if resolved in seen or not path.exists():
        return []
    seen.add(resolved)

    out: List[Tuple[str, bool]] = []
    # ``requirements.optional.txt`` entries degrade capability rather than gate
    # startup, so they are reported as not-declared-required.
    informational = "optional" in path.name
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # A commented-out pin (e.g. ``# faiss-cpu>=1.8``) is still a real
            # candidate component worth listing -- but only when it actually
            # looks like a requirement.
            candidate = line.lstrip("#").strip()
            if _PIN_RE.match(candidate):
                out.append((candidate, True))
            continue
        if line.startswith("-r"):
            out.extend(_expand_requirements(path.parent / line[2:].strip(), seen))
            continue
        if line.startswith("-"):
            continue
        if not _PIN_RE.match(line):
            continue
        out.append((line, informational))
    return out


def declared_requirements() -> List[Tuple[str, bool]]:
    """Every declared dependency, with the include syntax expanded.

    The optional group is listed explicitly: those components are not required
    to run and are not redistributed by this project, but a reader auditing the
    dependency surface still needs to see them (spec P1-08 #4).
    """
    groups = ["requirements.txt", "requirements.optional.txt"]
    out: List[Tuple[str, bool]] = []
    for group in groups:
        out.extend(_expand_requirements(ROOT / group))
    return out


def python_components() -> List[Dict[str, Any]]:
    """Resolve the declared Python dependencies against installed metadata."""
    from importlib import metadata

    components: List[Dict[str, Any]] = []
    seen: set = set()
    for line, optional in declared_requirements():
        name = _parse_requirement(line)
        if not name or name in seen:
            continue
        seen.add(name)
        entry: Dict[str, Any] = {
            "ecosystem": "python",
            "name": name,
            "version": "",
            "license": "",
            "homepage": "",
            "declared": not optional,
            "optional": optional,
            "installed": False,
        }
        try:
            dist = metadata.distribution(name)
            entry["installed"] = True
            entry["version"] = dist.version
            meta = dist.metadata
            # PEP 639 ``License-Expression`` is authoritative when present;
            # fall back to the legacy ``License`` field and classifiers.
            entry["license"] = _normalise_license(
                meta.get("License-Expression")
                or meta.get("License")
                or "",
                meta.get_all("Classifier") or [],
            )
            entry["homepage"] = meta.get("Home-page") or _project_url(meta) or ""
        except metadata.PackageNotFoundError:
            entry["license"] = ""
        components.append(entry)
    return components


def python_license_texts() -> Dict[str, str]:
    """Return ``{distribution: license-file-count}`` for bundled licence texts."""
    from importlib import metadata

    counts: Dict[str, str] = {}
    for line, _optional in declared_requirements():
        name = _parse_requirement(line)
        if not name or name in counts:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        files = dist.metadata.get_all("License-File") or []
        counts[name] = str(len(files))
    return counts


def _project_url(meta: Any) -> str:
    for value in meta.get_all("Project-URL") or []:
        if "," in value:
            label, url = value.split(",", 1)
            if label.strip().lower() in {"homepage", "source", "repository", "documentation"}:
                return url.strip()
    return ""


def _normalise_license(raw: str, classifiers: List[str]) -> str:
    """Turn free-form licence metadata into a short SPDX-ish identifier."""
    text = (raw or "").strip()
    # PEP 639 expressions ("Apache-2.0 AND MIT") are compact and authoritative.
    if text and "\n" not in text and len(text) <= 200:
        return text
    for classifier in classifiers:
        if "License ::" in classifier:
            tail = classifier.split("::")[-1].strip()
            if tail and tail.lower() not in {"osi approved", "other/proprietary license"}:
                return tail
    if text and "\n" not in text:
        return text
    # many projects dump the whole licence text into ``License`` -- fall back to
    # an explicit "unknown" instead of a wall of text.
    for classifier in classifiers:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "UNKNOWN"


# --------------------------------------------------------------------------- #
# Frontend inventory
# --------------------------------------------------------------------------- #
def frontend_components() -> List[Dict[str, Any]]:
    """Read the locked frontend dependency graph (versions + licences)."""
    lock_path = ROOT / "frontend" / "package-lock.json"
    if not lock_path.exists():
        return []
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    root_name = lock.get("name", "")
    components: List[Dict[str, Any]] = []
    for path, info in packages.items():
        if not path.startswith("node_modules/") or info.get("link"):
            continue
        name = path.split("node_modules/", 1)[1]
        components.append(
            {
                "ecosystem": "npm",
                "name": name,
                "version": str(info.get("version", "")),
                "license": _normalise_license(str(info.get("license", "")), []),
                "homepage": str(info.get("resolved", "")).split("/-/")[0],
                "declared": False,
                "installed": (ROOT / "frontend" / path).exists(),
            }
        )
    # flag the direct dependencies pulled from package.json
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    direct = set(pkg.get("dependencies", {})) | set(pkg.get("devDependencies", {}))
    for component in components:
        if component["name"] in direct:
            component["declared"] = True
    return sorted(components, key=lambda item: item["name"])


# --------------------------------------------------------------------------- #
# External scientific software + sample data
# --------------------------------------------------------------------------- #
def external_components() -> List[Dict[str, Any]]:
    """External programs the platform can launch -- never redistributed."""
    try:
        from simulations.controlled import describe_tools
    except Exception:  # pragma: no cover - defensive
        return []
    components: List[Dict[str, Any]] = []
    for tool in describe_tools():
        components.append(
            {
                "ecosystem": "external",
                "name": tool.get("key") or tool.get("executable", ""),
                "version": tool.get("version", "") or "",
                "license": tool.get("license", "") or "UNKNOWN",
                "homepage": tool.get("homepage", ""),
                "declared": True,
                "installed": bool(tool.get("available") or tool.get("installed")),
                "note": "External program; detected on PATH, never bundled or redistributed.",
            }
        )
    return components


#: Sample-data metadata comes in two naming conventions, and a report that
#: only recognises one of them silently drops datasets from the SBOM.
#:
#: A dataset metadata document is recognised by the fields it carries, not by
#: the name it happens to have.
#:
#: The flat demo datasets use ``<name>.metadata.json`` next to the data file.
#: The Bruker NMR sample is a *vendor* directory (``sample_01.d/``) whose
#: metadata file is simply called ``metadata.json`` -- the vendor layout
#: dictates the name, and the file ends up nested one level deeper than the
#: ``*.metadata.json`` pattern reaches.
#:
#: Matching on the name therefore breaks in both directions.  The old glob
#: (``*.metadata.json``) dropped the Bruker spectrum from the SBOM, from
#: NOTICE and from the licence report even though it is a shipped dataset;
#: adding ``*.parser.json`` to the name list over-corrected and pulled the
#: nine *parser configurations* in as datasets, because those files sit next to
#: the metadata they describe and are named in the same family.
#:
#: So the question is asked of the content instead: a dataset metadata
#: document carries a ``license`` and a ``source``; a parser configuration
#: carries a ``parser`` and describes how to read a file, never where it came
#: from or under what terms.  That distinction is the same one
#: ``data_layer.quality`` leans on when it validates a dataset.

#: Fields a dataset metadata document must carry to be inventoried.
_METADATA_FIELDS = ("license", "source")


def _is_metadata_file(path: Path) -> bool:
    """True when ``path`` is a dataset metadata document.

    The check is made on the parsed JSON, not on the file name: see
    ``_METADATA_FIELDS``.
    """
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(meta, dict):
        return False
    return all(field in meta for field in _METADATA_FIELDS)


def _dataset_metadata_files() -> List[Path]:
    """Every dataset metadata document under ``datasets/``."""
    root = ROOT / "datasets"
    if not root.is_dir():
        return []
    candidates = root.rglob("*.json")
    return [path for path in sorted(candidates) if _is_metadata_file(path)]


def dataset_components() -> List[Dict[str, Any]]:
    """Sample-data provenance and licence."""
    components: List[Dict[str, Any]] = []
    for path in sorted(_dataset_metadata_files()):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        source = meta.get("source") or {}
        components.append(
            {
                "ecosystem": "dataset",
                "name": meta.get("name") or path.parent.name,
                "version": str(meta.get("data_type", "")),
                "license": str(meta.get("license", "")) or "UNKNOWN",
                "homepage": str(source.get("reference", "") if isinstance(source, dict) else ""),
                "declared": True,
                "installed": True,
                "note": f"{path.relative_to(ROOT).as_posix()} · kind={source.get('kind', '?')}"
                if isinstance(source, dict)
                else path.relative_to(ROOT).as_posix(),
            }
        )
    return components


def bundled_assets() -> List[Dict[str, Any]]:
    """Pre-built JS/CSS assets shipped in the repository."""
    assets: List[Dict[str, Any]] = []
    for directory in (ROOT / "frontend" / "dist", ROOT / "static"):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                assets.append(
                    {
                        "path": path.relative_to(ROOT).as_posix(),
                        "bytes": path.stat().st_size,
                        "generated_from": "frontend/ (vite build of the locked npm graph)",
                    }
                )
    return assets


# --------------------------------------------------------------------------- #
# Cleanliness scan
# --------------------------------------------------------------------------- #
#: Directories that are pruned from the walk before any file is opened.
#:
#: These hold thousands of files that are never opened by the scan itself
#: (``node_modules``) or that are never part of a release package at all
#: (``output/`` holds the results of previous runs, ``workspace/`` holds the
#: user's uploads).  Pruning them is not an optimisation of convenience: the
#: scan exists to answer "would a secret ship?", and a file that never ships
#: cannot answer that question -- it can only make the answer depend on how
#: many runs this particular machine happened to do.
_PRUNED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".vite",
    "output",
    "workspace",
    "artifacts",
    ".tmp",
    "venv",
    ".venv",
    "env",
}


def _iter_scannable_files(root: Path):
    """Yield every file under *root* that a release package could contain.

    The walk is pruned and the packager's own rule decides the rest, so the
    scan sees exactly the set of files the archive would contain.  Two
    consequences, both wanted:

    * a secret hiding in a file that never ships is not reported as a release
      blocker -- it is not one;
    * the scan's cost stops depending on how much runtime state the machine
      happens to have accumulated.
    """
    packager = _load_packager()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PRUNED_DIRS]
        base = Path(dirpath)
        for filename in filenames:
            path = base / filename
            if packager is not None:
                try:
                    rel = path.relative_to(root)
                except ValueError:  # pragma: no cover - defensive
                    continue
                if packager.should_skip(rel):
                    continue
            yield path


def _load_packager():
    """Load ``scripts/package.py`` if it is available (it defines the rules).

    The packager is the authority on what ships.  If it cannot be loaded the
    scan falls back to "scan everything reachable", which is slower but still
    correct -- it can only ever report *more* problems, never fewer.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "chemml_packager", ROOT / "scripts" / "package.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # pragma: no cover - defensive
        return None


def cleanliness_scan() -> Dict[str, List[str]]:
    """Detect files that must not ship in a release package.

    Secret scanning skips ``tests/`` because the redaction test suite
    deliberately embeds *synthetic* credentials to prove they are stripped from
    error messages; those values are not real secrets.
    """
    problems: Dict[str, List[str]] = {
        "pyc": [],
        "pycache": [],
        "secrets": [],
        "private_data": [],
        "duplicate_assets": [],
    }
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    for path in ROOT.rglob("*.pyc"):
        if "node_modules" not in path.parts:
            problems["pyc"].append(path.relative_to(ROOT).as_posix())
    for path in ROOT.rglob("__pycache__"):
        if "node_modules" not in path.parts and path.is_dir():
            problems["pycache"].append(path.relative_to(ROOT).as_posix())

    # secrets: scan small text files only (tests are intentionally excluded)
    for path in _iter_scannable_files(ROOT):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("tests/") or rel in _SECRET_ALLOW_FILES:
            continue
        if rel.endswith((".png", ".jpg", ".spc", ".docx", ".zip", ".json")):
            continue
        try:
            if path.stat().st_size > 400_000:
                continue
        except OSError:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pattern, label in _SECRET_PATTERNS:
            if re.search(pattern, text):
                problems["secrets"].append(f"{rel} ({label})")
                break

    ignored = {
        line.strip().rstrip("/").lstrip("!")
        for line in gitignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for candidate in ("config/ai.json", ".env", "output/runs", "memory/agent_memory.json"):
        if not (ROOT / candidate).exists():
            continue
        top = candidate.split("/", 1)[0]
        if candidate in ignored or top in ignored or f"{top}/" in gitignore:
            problems.setdefault("runtime_data", []).append(
                f"{candidate} (runtime only: gitignored and excluded from release packages)"
            )
        else:
            problems["private_data"].append(candidate)

    dist_assets = {p.name for p in (ROOT / "frontend" / "dist" / "assets").glob("*")} \
        if (ROOT / "frontend" / "dist" / "assets").exists() else set()
    static_assets = {p.name for p in (ROOT / "static" / "assets").glob("*")} \
        if (ROOT / "static" / "assets").exists() else set()
    static_generated = any(line.strip().rstrip("/") == "static" for line in gitignore.splitlines())
    if dist_assets and static_assets and dist_assets == static_assets:
        if static_generated:
            problems.setdefault("generated_assets", []).append(
                "static/ mirrors frontend/dist and is gitignored + generated at runtime "
                "(single source = frontend/dist)"
            )
        else:
            problems["duplicate_assets"].append(
                "static/assets mirrors frontend/dist/assets but static/ is NOT gitignored "
                "(single-source violation)"
            )
    return problems


# --------------------------------------------------------------------------- #
# Artefact builders
# --------------------------------------------------------------------------- #
def _license_review(components: List[Dict[str, Any]]) -> List[str]:
    """The components that need a human licence review before distribution.

    Only *redistributed* components are reviewed -- the same membership rule
    the NOTICE uses (see ``build_notice``).  A strong-copyleft package that
    the user installs for themselves (an optional accelerator) is not shipped
    with the application, so it creates no obligation, and listing it here
    would make the section's content depend on which optional packages happen
    to be present on the machine that generated the report.

    The rule this section states in its own text is "依赖被分发"; the code
    used to review *every* component, which contradicted it.

    The licence is matched on the *precise identifiers* it denotes rather
    than on the raw metadata string, so an upstream project that renames its
    licence metadata (``GPL-3.0`` versus ``GNU General Public License v3``)
    does not make a package appear in -- or vanish from -- this list.
    """
    flagged = []
    for component in components:
        if not (component.get("declared") or component.get("ecosystem") == "npm"):
            continue
        identifiers = set()
        for branch in _licence_branches(str(component.get("license", ""))):
            for atom in branch:
                identifiers |= set(atom)
        licence_text = " ".join(sorted(identifiers)).upper()
        if any(token in licence_text for token in _REVIEW_LICENCES):
            flagged.append(
                f"{component['ecosystem']}:{component['name']} "
                f"({_licence_display(str(component.get('license', '')))})"
            )
    return sorted(set(flagged))


def build_sbom(
    python_deps: List[Dict[str, Any]],
    npm_deps: List[Dict[str, Any]],
    external: List[Dict[str, Any]],
    datasets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    components: List[Dict[str, Any]] = []
    for item in python_deps:
        components.append(_component(item, purl=f"pkg:pypi/{item['name'].lower()}"))
    for item in npm_deps:
        components.append(_component(item, purl=f"pkg:npm/{item['name'].replace('@', '%40')}"))
    for item in external:
        components.append(_component(item, purl=""))
    for item in datasets:
        components.append(_component(item, purl=""))
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": PROJECT_NAME,
                "version": PROJECT_VERSION,
                "licenses": [{"license": {"id": PROJECT_LICENSE}}],
            },
            "tools": [{"name": "scripts/license_report.py", "version": PROJECT_VERSION}],
        },
        "components": components,
    }


def _component(item: Dict[str, Any], purl: str) -> Dict[str, Any]:
    component: Dict[str, Any] = {
        "type": "library" if item["ecosystem"] in {"python", "npm"} else "data",
        "name": item["name"],
        "version": item.get("version") or "0",
        "scope": "required" if item.get("declared") else "optional",
        "properties": [
            {"name": "chemml:ecosystem", "value": item["ecosystem"]},
            {"name": "chemml:installed", "value": str(item.get("installed", False)).lower()},
            # ``bundled`` must mean the same thing here as it means in NOTICE:
            # "this component is redistributed with the application".  The
            # python packages the *user* installs for themselves -- the
            # optional accelerators in ``requirements.optional.txt`` -- are not
            # redistributed, so they are not bundled.  Saying otherwise made
            # the SBOM claim a redistribution that the NOTICE does not list.
            {
                "name": "chemml:bundled",
                "value": str(
                    item["ecosystem"] == "npm" or bool(item.get("declared"))
                ).lower(),
            },
        ],
    }
    if purl:
        component["purl"] = purl
    license_id = item.get("license") or "UNKNOWN"
    component["licenses"] = [{"license": {"id": license_id if license_id != "UNKNOWN" else "NOASSERTION"}}]
    if item.get("homepage"):
        component["externalReferences"] = [{"type": "website", "url": item["homepage"]}]
    if item.get("note"):
        component["description"] = item["note"]
    return component


def build_notice(
    python_deps: List[Dict[str, Any]],
    npm_deps: List[Dict[str, Any]],
    external: List[Dict[str, Any]],
) -> str:
    lines = [
        f"{PROJECT_NAME} {PROJECT_VERSION}",
        f"Copyright (c) 2026 {COPYRIGHT_HOLDER}",
        "",
        f"This product is licensed under the {PROJECT_LICENSE} License; see LICENSE.",
        "",
        "This product includes the following third-party components.",
        "",
        "=" * 78,
        "BUNDLED SOFTWARE (distributed with the application)",
        "=" * 78,
        "",
    ]
    for ecosystem, deps in (("Python", python_deps), ("JavaScript", npm_deps)):
        # The bundled list is the set of components this product *ships*, so it
        # must be derived from the **declaration**, not from what happens to be
        # installed on the machine that ran the generator.
        #
        # The old filter was ``installed or ecosystem == "npm"``: a Python
        # component appeared only when the local interpreter happened to have
        # it, so the same commit produced a different NOTICE on a machine with
        # torch installed and on one without.  Since a NOTICE has to name every
        # redistributed component, the membership question is "is this declared
        # as part of the distribution", and that answer comes from the
        # requirements files -- the same answer everywhere.
        bundled = [dep for dep in deps if dep.get("declared") or dep["ecosystem"] == "npm"]
        if not bundled:
            continue
        lines.append(f"-- {ecosystem} dependency notice ({len(bundled)} components) --")
        lines.append("")
        for dep in bundled:
            licence = dep.get("license") or "UNKNOWN"
            home = f" <{dep['homepage']}>" if dep.get("homepage") else ""
            lines.append(f"  {dep['name']} {dep.get('version') or '(unresolved)'} — {licence}{home}")
        lines.append("")
    lines += [
        "=" * 78,
        "EXTERNAL PROGRAMS (NOT distributed with this product)",
        "=" * 78,
        "",
        "The platform can *launch* the programs below when they are already",
        "installed by the user. None of them are bundled or redistributed; the",
        "user must obtain their own licence. The platform falls back to internal",
        "approximations when a program is missing.",
        "",
    ]
    for tool in external:
        lines.append(f"  {tool['name']} — {tool['license']}{' <' + tool['homepage'] + '>' if tool.get('homepage') else ''}")
    lines += [
        "",
        "=" * 78,
        "UPSTREAM PROJECTS REFERENCED BY THIS CODEBASE (not redistributed)",
        "=" * 78,
        "",
        "The modules below reimplement an *approach* published by an upstream",
        "project.  No upstream source file is copied into this distribution.",
        "They are listed here because a reader comparing implementations should",
        "know where the idea came from, and because the upstream licences are",
        "recorded for traceability even though the borrowed material here is an",
        "architecture rather than code.",
        "",
    ]
    for item in UPSTREAM_ATTRIBUTIONS:
        lines += [
            f"  {item['module']}",
            f"      references : {item['upstream']} ({item['license']})",
            f"      borrowed   : {item['borrowed']}",
            f"      not taken  : {item['not_taken']}",
            "",
        ]
    lines.append(
        "Sample datasets under ``datasets/`` are generated by this project or"
    )
    lines.append(
        "shipped as CC0; each file states its own ``license`` and ``source``"
    )
    lines.append(
        "in its ``*.metadata.json``.  See section 4 of"
    )
    lines.append("``docs/THIRD_PARTY_LICENSES.md``.")
    lines.append("")
    return "\n".join(lines)


def build_markdown(
    python_deps: List[Dict[str, Any]],
    npm_deps: List[Dict[str, Any]],
    external: List[Dict[str, Any]],
    datasets: List[Dict[str, Any]],
    assets: List[Dict[str, Any]],
    problems: Dict[str, List[str]],
) -> str:
    def table(rows: List[Dict[str, Any]], columns: Tuple[str, ...]) -> List[str]:
        out = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
        for row in rows:
            out.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
        return out

    lines = [
        f"# 第三方依赖与许可证清单（{PROJECT_NAME} {PROJECT_VERSION}）",
        "",
        f"> 生成脚本：`scripts/license_report.py`；所有条目均来自**真实**的安装 / 锁定元数据。",
        f"> 本项目自身许可：**{PROJECT_LICENSE}**（见根目录 `LICENSE`）。",
        "",
        "## 1. Python 运行时依赖",
        "",
    ]
    lines += table(python_deps, ("name", "version", "license", "declared", "installed"))
    lines += ["", "## 2. 前端（npm）依赖", ""]
    lines += table(npm_deps, ("name", "version", "license", "declared", "installed"))
    lines += ["", "## 3. 外部科研软件（**不随包分发**）", ""]
    lines += table(external, ("name", "license", "installed", "homepage"))
    lines += ["", "## 4. 样例数据来源与许可", ""]
    lines += table(datasets, ("name", "license", "note"))
    lines += ["", "## 5. 预构建前端资源", ""]
    # v0.7.2 fix: this section used to list each emitted file by name and byte
    # size, and later to print `len(assets)`.  Vite names bundles by *content
    # hash* (`index-BexXqvfv.js`) and the emitted file count depends on whether
    # a local `frontend/dist` happens to exist, so both variants changed on
    # every frontend build.  That made this document -- and any SHA-256 recorded
    # for it -- irreproducible, which defeats the point of pinning a licence
    # inventory (the release manifest flags the difference as "drift" and no
    # published digest can ever be re-derived).  What matters for licensing is
    # which *third-party* assets ship, and that is a policy statement, not a
    # property of the local working tree.
    lines.append(
        "- 发布包内的 `frontend/dist/` bundle 由 `frontend/` 本项目源码经 vite 构建"
        "（`npm run build`）生成，属于**本项目自有**代码与第 2 节所列 npm 依赖的组合产物；"
        "本项目不向发布包额外引入未在此列出的第三方前端资源。"
    )
    lines.append(
        "- bundle 的文件名含内容哈希、个数与字节数随构建波动，均与本清单的许可结论无关，"
        "故不逐条列出；如需逐个核对发布包内的实际文件，请以 `docs/RELEASE_MANIFEST.json` "
        "与 `SHA256SUMS` 为准（这两者随版本整体重新生成）。"
    )
    lines += ["", "## 6. 发布包清洁度扫描", ""]
    # v0.7.2 fix: the scan used to enumerate every offending path, then to print
    # a raw count.  Those paths are transient build/tooling state (`__pycache__`,
    # `output/runs`), so both variants churned as tests and builds ran, which
    # again made the document's SHA-256 irreproducible.  Presence still detects
    # the real problem (a cache accidentally shipped) while keeping the document
    # stable; and a genuinely dirty tree *should* make the recorded digest drift,
    # because then the release material and the tree no longer agree.
    #
    # v0.7.4 fix: the buckets were emitted by iterating the scan result, so the
    # *set* of lines depended on the machine -- ``runtime_data`` and
    # ``generated_assets`` only appeared when the scan happened to hit them.
    # A CI runner that has not run the test suite and a developer machine that
    # has would therefore produce documents with a different number of lines,
    # and the release check would report drift for a file nobody had touched.
    # The bucket list is fixed here; only the *value* of a blocking bucket
    # varies, and a blocking bucket is a release blocker in its own right.
    for key in _CLEANLINESS_BUCKETS:
        values = problems.get(key, [])
        if key in _INFO_KEYS:
            # Build/run-time state (`__pycache__`, `*.pyc`).  It is *expected* to
            # exist in a working tree and is never shipped, so the document must
            # not record whether it happens to be present right now -- that alone
            # would make the digest depend on when the report was generated.
            lines.append(
                f"- **{key}**：构建/运行期产物，**不进入发布包**，不计入许可结论"
                "（扫描命中与否仅供参考）。"
            )
        elif key == "duplicate_assets":
            lines.append(
                f"- **{key}**：{'未发现重复资源' if not values else '存在重复资源（阻断项）'}"
            )
        else:
            lines.append(f"- **{key}**：{'OK' if not values else '存在（阻断项，详见 `--print`）'}")
    review = _license_review(python_deps + npm_deps)
    lines += ["", "## 7. 需要人工复核的许可证（强 copyleft 等）", ""]
    if review:
        for item in review:
            lines.append(f"- {item}")
    else:
        lines.append("- 无（未发现需要复核的强 copyleft 依赖被分发）")
    lines += ["", "## 8. 上游项目引用（借鉴思路，**未复制代码**）", ""]
    lines += [
        "下表列出本仓库**重新实现了其思路**的上游项目。仓库内**没有复制任何上游源文件**，"
        "因此不构成 Apache-2.0 意义上的再分发义务；列出的目的是可追溯："
        "读者若认出了某个模块的设计，应能直接读到「借了什么、没借什么」，"
        "而不是去猜省略是疏忽还是意外。`MIT` 上游亦在表中记录以备核对。",
        "",
    ]
    lines += table(
        [dict(item) for item in UPSTREAM_ATTRIBUTIONS],
        ("module", "upstream", "license", "borrowed", "not_taken"),
    )
    lines += [
        "",
        "> 「借鉴了什么 / 明确没借鉴什么」这后半句才是有用信息。只写"
        "\"adapted from X\" 的读者无法判断严格的部分是否也一并沿用了。",
        "",
    ]
    lines += [
        "",
        "## 9. 方法说明",
        "",
        "- Python 依赖：解析 `requirements.txt` 的声明项，再用 `importlib.metadata` 读取真实版本与许可证。",
        "- 前端依赖：读取 `frontend/package-lock.json` 的锁定版本与许可证字段（含传递依赖）。",
        "- 外部软件：读取 `simulations.controlled.TOOL_ALLOWLIST`，仅记录检测状态，**不打包分发**。",
        "- 样例数据：读取 `datasets/**/*.metadata.json` 的 `license` / `source` 字段。",
        "- 本清单不替代各依赖自身的许可证全文；分发时应随包提供相应的许可证文本。",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
#: Licence strings that mean "this package's licence could not be determined
#: here".  A package that is not installed on the machine running the check
#: has no licence metadata, so the report records a placeholder.  That
#: placeholder must not be read as a licence change: the fact that a
#: distribution is *not installed here* is an environment fact, exactly like
#: the version it would have been.
_UNRESOLVED_LICENCES = frozenset({"", "UNKNOWN", "NOASSERTION"})


# --------------------------------------------------------------------------- #
# Licence identity
# --------------------------------------------------------------------------- #
#: Free-form licence spellings, and the precise SPDX identifiers each of them
#: can denote.
#:
#: Upstream projects rewrite the *spelling* of their licence metadata without
#: changing the licence: fastapi 0.110.0 ships ``License: MIT License`` while
#: 0.162.0 ships the PEP 639 expression ``MIT``; uvicorn went from ``BSD
#: License`` to ``BSD-3-Clause``; python-multipart from ``Apache Software
#: License`` to ``Apache-2.0``; matplotlib from ``PSF`` to ``Python Software
#: Foundation License``.  The licence is identical in every one of those
#: pairs -- only the metadata spelling moved -- so a gate that compares the
#: strings literally reports drift for a document nobody touched, on every
#: machine that resolved a different patch release than the one that wrote
#: the file.
#:
#: Each entry maps a spelling to the set of precise SPDX identifiers it can
#: denote.  The set holds more than one member only where the spelling is
#: genuinely ambiguous: the trove classifier ``License :: OSI Approved :: BSD
#: License`` covers the whole BSD family without saying which revision, so
#: it is compatible with any of them.  Two *precise* identifiers are never
#: compatible with each other unless they are equal -- ``BSD-3-Clause`` and
#: ``BSD-2-Clause`` are different licences, and a change between them is a
#: change worth reporting.
#:
#: The identifiers are SPDX short identifiers, and the table is deliberately
#: explicit rather than derived from a licence database: a database would make
#: the gate's verdict depend on the version of that database installed on the
#: machine running the check, which is the same class of machine-dependent
#: verdict this comparison exists to eliminate.
_LICENCE_ALIASES: Dict[str, Tuple[str, ...]] = {
    # -- MIT -------------------------------------------------------------- #
    "mit license": ("MIT",),
    "mit licence": ("MIT",),
    "the mit license": ("MIT",),
    # -- BSD: the bare name does not say which revision ------------------ #
    "bsd license": ("BSD-2-Clause", "BSD-3-Clause"),
    "bsd licence": ("BSD-2-Clause", "BSD-3-Clause"),
    "bsd": ("BSD-2-Clause", "BSD-3-Clause"),
    # -- Apache ----------------------------------------------------------- #
    "apache software license": ("Apache-2.0",),
    "apache software license 2.0": ("Apache-2.0",),
    "apache license": ("Apache-2.0",),
    "apache license 2.0": ("Apache-2.0",),
    "apache license, version 2.0": ("Apache-2.0",),
    "apache 2.0": ("Apache-2.0",),
    # -- Python Software Foundation --------------------------------------- #
    "python software foundation license": ("PSF-2.0",),
    "psf": ("PSF-2.0",),
    "psf license": ("PSF-2.0",),
    # -- ISC -------------------------------------------------------------- #
    "isc license": ("ISC",),
    "isc license (iscl)": ("ISC",),
    # -- Mozilla ---------------------------------------------------------- #
    "mozilla public license 2.0 (mpl 2.0)": ("MPL-2.0",),
    "mozilla public license 2.0": ("MPL-2.0",),
    # -- zlib ------------------------------------------------------------- #
    "zlib": ("Zlib",),
    "zlib license": ("Zlib",),
    "zlib/libpng license": ("Zlib",),
    # -- Boost ------------------------------------------------------------ #
    "boost software license 1.0": ("BSL-1.0",),
    "boost software license 1.0 (bsl-1.0)": ("BSL-1.0",),
    # -- PostgreSQL / Unlicense / WTFPL ----------------------------------- #
    "postgresql license": ("PostgreSQL",),
    "the unlicense (unlicense)": ("Unlicense",),
    "do what the f*ck you want to public license": ("WTFPL",),
    # -- The deprecated GNU spellings, and their current equivalents ------ #
    # SPDX retired ``GPL-3.0`` in favour of ``GPL-3.0-only``: the same
    # licence, renamed.  ``-or-later`` is a *different* grant (the user may
    # pick a later version), so it stays a separate identifier.
    "gpl-2.0": ("GPL-2.0-only",),
    "gpl-3.0": ("GPL-3.0-only",),
    "lgpl-2.1": ("LGPL-2.1-only",),
    "lgpl-3.0": ("LGPL-3.0-only",),
    "agpl-3.0": ("AGPL-3.0-only",),
    "gpl-2.0+": ("GPL-2.0-or-later",),
    "gpl-3.0+": ("GPL-3.0-or-later",),
    "gplv2+": ("GPL-2.0-or-later",),
    "gplv3+": ("GPL-3.0-or-later",),
    "lgpl-3.0+": ("LGPL-3.0-or-later",),
    "lgplv3+": ("LGPL-3.0-or-later",),
    # -- The trove classifier tails, which name the same licences --------- #
    "gnu general public license v2 (gplv2)": ("GPL-2.0-only",),
    "gnu general public license v3 (gplv3)": ("GPL-3.0-only",),
    "gnu lesser general public license v2 (lgplv2)": ("LGPL-2.1-only",),
    "gnu lesser general public license v3 (lgplv3)": ("LGPL-3.0-only",),
    "gnu affero general public license v3 (agplv3)": ("AGPL-3.0-only",),
    "gnu general public license v2 or later (gplv2+)": ("GPL-2.0-or-later",),
    "gnu general public license v3 or later (gplv3+)": ("GPL-3.0-or-later",),
    "gnu lesser general public license v2 or later (lgplv2+)": ("LGPL-2.1-or-later",),
    "gnu lesser general public license v3 or later (lgplv3+)": ("LGPL-3.0-or-later",),
    "gnu affero general public license v3 or later (agplv3+)": ("AGPL-3.0-or-later",),
    # -- Other classifier tails that name a precise licence --------------- #
    "artistic license 2.0": ("Artistic-2.0",),
    "academic free license (afl)": ("AFL-3.0",),
    "eclipse public license 1.0 (epl-1.0)": ("EPL-1.0",),
    "eclipse public license 2.0 (epl-2.0)": ("EPL-2.0",),
    "common development and distribution license 1.0 (cddl-1.0)": ("CDDL-1.0",),
    "common public license 1.0 (cpl-1.0)": ("CPL-1.0",),
}


def _split_top_level(text: str, keyword: str) -> List[str]:
    """Split ``text`` on ``keyword``, ignoring occurrences inside brackets.

    ``MIT AND (Apache-2.0 OR BSD-3-Clause)`` splits on ``OR`` into one part,
    because the ``OR`` sits inside brackets; it splits on ``AND`` into two.
    """
    tokens = text.split()
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    for token in tokens:
        if token == "(":
            depth += 1
            current.append(token)
            continue
        if token == ")":
            depth -= 1
            current.append(token)
            continue
        if token == keyword and depth == 0:
            parts.append(" ".join(current))
            current = []
            continue
        current.append(token)
    parts.append(" ".join(current))
    return [part for part in parts if part]


def _licence_atom(text: str) -> FrozenSet[str]:
    """One term of a licence expression: the identifiers it can denote."""
    value = " ".join((text or "").split())
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    alias = _LICENCE_ALIASES.get(value.casefold())
    if alias:
        return frozenset(alias)
    return frozenset({value})


def _licence_branches(text: str) -> List[Tuple[FrozenSet[str], ...]]:
    """The disjunctive normal form of a licence string.

    A licence is a set of alternatives, each of which is a set of terms that
    must all hold.  ``MIT`` is one alternative with one term; ``MIT AND
    Apache-2.0`` is one alternative with two terms; ``MIT OR Apache-2.0`` is
    two alternatives with one term each.  Reducing everything to this shape
    is what lets two spellings of the same licence be recognised as such
    without hand-writing a rule for every combination.
    """
    value = " ".join((text or "").split())
    if not value:
        return []
    branches: List[Tuple[FrozenSet[str], ...]] = []
    for alternative in _split_top_level(value, "OR"):
        # Each term of the conjunction may itself expand into several
        # alternatives (``MIT AND (Apache-2.0 OR BSD-3-Clause)``); the
        # conjunction is therefore the product of its terms.
        per_term: List[List[Tuple[FrozenSet[str], ...]]] = []
        for term in _split_top_level(alternative, "AND"):
            if term.startswith("(") and term.endswith(")"):
                per_term.append(_licence_branches(term[1:-1]))
            else:
                per_term.append([(_licence_atom(term),)])
        for combination in itertools.product(*per_term):
            merged: Tuple[FrozenSet[str], ...] = ()
            for conjunction in combination:
                merged = merged + conjunction
            branches.append(merged)
    return branches


def _atoms_compatible(
    left: List[FrozenSet[str]], right: List[FrozenSet[str]], _taken: Optional[set] = None
) -> bool:
    """Can every term on the left be paired with a different term on the right?

    A greedy pairing would be wrong in principle: ``BSD License`` is
    compatible with both ``BSD-2-Clause`` and ``BSD-3-Clause``, so pairing it
    with the wrong one could strand the other side.  The lists hold one entry
    per term, so the search space is tiny and a backtracking match is both
    exact and cheap.
    """
    if not left:
        return True
    taken = _taken or set()
    for index, atom in enumerate(left):
        for other, candidate in enumerate(right):
            if other in taken:
                continue
            if not (atom & candidate):
                continue
            taken.add(other)
            if _atoms_compatible(left[:index] + left[index + 1:], right, taken):
                return True
            taken.discard(other)
    return False


def _licences_compatible(left: str, right: str) -> bool:
    """Do two licence strings denote the same licence?

    Two licences agree when they share at least one alternative whose terms
    can all be matched.  ``MIT`` and ``MIT License`` agree; ``MIT`` and
    ``Apache-2.0`` do not; ``BSD License`` and ``BSD-3-Clause`` agree;
    ``BSD-2-Clause`` and ``BSD-3-Clause`` do not.
    """
    left_branches = _licence_branches(left)
    right_branches = _licence_branches(right)
    for left_branch in left_branches:
        for right_branch in right_branches:
            if len(left_branch) != len(right_branch):
                continue
            if _atoms_compatible(list(left_branch), list(right_branch)):
                return True
    return False


def _licence_display(text: str) -> str:
    """A stable rendering of a licence, for prose that is compared verbatim."""
    value = " ".join((text or "").split())
    alias = _LICENCE_ALIASES.get(value.casefold())
    if alias and len(alias) == 1:
        return alias[0]
    return value


def _licence_key(text: str) -> str:
    """Normalised licence, or the empty string when it is unresolved."""
    value = " ".join((text or "").split())
    if value.upper() in _UNRESOLVED_LICENCES:
        return ""
    return value


def _section_ecosystem(section: str) -> str:
    """The ecosystem a Markdown section inventories."""
    if section.startswith("1."):
        return "python"
    if section.startswith("2."):
        return "npm"
    if section.startswith("3."):
        return "external"
    return "dataset"


def _same_licence(left: Tuple[str, ...], right: Tuple[str, ...]) -> bool:
    """Do two licence sets agree?

    Two rules are at work here.

    **An unresolved licence is a wildcard.**  It means the machine running
    the comparison could not read the metadata, not that the licence changed.
    Comparing it literally would make the check fail on every machine where
    a declared-but-uninstalled component is absent -- which is every CI
    runner, because the optional accelerators are not installed there.

    **A licence is compared by what it denotes, not by how it is spelled.**
    Upstream projects rewrite the *spelling* of their licence metadata while
    keeping the licence itself: fastapi 0.110.0 says ``MIT License`` and
    0.162.0 says ``MIT``; uvicorn 0.29.0 says ``BSD License`` and 0.54.0
    says ``BSD-3-Clause``; matplotlib 3.8.0 says ``PSF`` and 3.11.2 says
    ``Python Software Foundation License``.  All of those pairs are within
    this project's declared ranges, so CI resolves them by whatever the
    current upstream release happens to spell it -- and a literal comparison
    then reports drift for a document nobody touched, saying nothing true
    about the release.  :func:`_licences_compatible` answers the question the
    gate actually asks: do these two strings denote the same licence?
    """
    left_set = {item for item in left if item}
    right_set = {item for item in right if item}
    if not left_set or not right_set:
        # At least one side could not resolve the licence.
        return True
    return _licence_sets_compatible(left_set, right_set)


def _licence_sets_compatible(
    left: set, right: set, _taken: Optional[set] = None
) -> bool:
    """Can every licence on the left be paired with a different one on the right?

    A greedy pairing would be wrong in principle: ``BSD License`` is
    compatible with both ``BSD-2-Clause`` and ``BSD-3-Clause``, so pairing it
    with the wrong one could strand the other side.  The sets hold one entry
    per component, so the search space is tiny and a backtracking match is
    both exact and cheap.
    """
    if not left:
        return True
    taken = _taken or set()
    for candidate in sorted(left):
        for other in sorted(right - taken):
            if not _licences_compatible(candidate, other):
                continue
            taken.add(other)
            if _licence_sets_compatible(left - {candidate}, right, taken):
                return True
            taken.discard(other)
    return False


# --------------------------------------------------------------------------- #
# Record-level comparison
# --------------------------------------------------------------------------- #
#: The field of a component entry that records its *version*.
#:
#: A version is a property of the environment that produced the artefact, not
#: of the release the artefact describes.  CI installs the declared ranges, so
#: it resolves to different patch releases than the machine that wrote the
#: committed file -- and a check that treats that difference as drift fails
#: on every runner while saying nothing true about the tree.
#:
#: Every *other* field of a component entry is part of the release's
#: statement: which packages ship, under which licence, required or optional.
#: Those are compared exactly.
_VERSION_FIELD = "version"


def _compare_entries(
    left: List[Tuple[str, Dict[str, str]]],
    right: List[Tuple[str, Dict[str, str]]],
) -> bool:
    """Do two sequences of component entries agree?

    The entries are compared *by position* rather than as a set: a document
    that lists the same packages in a different order is a different document,
    and so is one that lists an extra package.  Within an entry every field
    is compared exactly except the version, which is an environment fact.
    """
    if len(left) != len(right):
        return False
    for (left_name, left_fields), (right_name, right_fields) in zip(left, right):
        if left_name != right_name:
            return False
        for key, value in left_fields.items():
            if key == _VERSION_FIELD:
                continue
            if key == "licence":
                # An unresolved licence is a wildcard, not a change: it means
                # the machine reading the metadata could not find it.
                if not _same_licence(value, right_fields.get(key, ())):
                    return False
                continue
            if right_fields.get(key) != value:
                return False
    return True


def _normalise_newlines(text: str) -> str:
    """The text with every line ending normalised to ``\\n``.

    Git stores these files with LF endings, but a Windows checkout with
    ``core.autocrlf`` writes them back with CRLF.  The generator always
    produces LF, so without this normalisation the byte comparison reports
    every one of these three files as stale on every Windows machine -- and
    the file's content, which is what the check is about, is identical.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_normalised(path: Path) -> str:
    """The file's content with its line endings normalised."""
    return _normalise_newlines(path.read_text(encoding="utf-8"))


def _notices_entries(text: str) -> Optional[List[Tuple[str, Dict[str, str]]]]:
    """The component entries of a NOTICE, in document order.

    A NOTICE is prose with a few structured lines in it.  The prose is
    compared byte-for-byte elsewhere; this function extracts only the
    structured part, so that the prose is not silently ignored.
    """
    entries: List[Tuple[str, Dict[str, str]]] = []
    ecosystem = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        header = re.match(r"^--\s*(Python|JavaScript)\s+dependency notice", line)
        if header:
            ecosystem = "python" if header.group(1) == "Python" else "npm"
            continue
        if line.startswith("=") or line.startswith("BUNDLED") or line.startswith("EXTERNAL"):
            ecosystem = "" if line.startswith("=") else ecosystem
            continue
        if line.startswith("UPSTREAM"):
            ecosystem = ""
            continue
        match = re.match(r"^(\S+)\s+(\S+)\s+—\s+(.*)$", line)
        if match and ecosystem:
            name, version, rest = match.groups()
            licence = re.sub(r"\s*<.*$", "", rest).strip()
            entries.append(
                (
                    f"{ecosystem}:{name}",
                    {
                        "version": version,
                        "licence": (_licence_key(licence),),
                        "scope": "required",
                    },
                )
            )
            continue
        match = re.match(r"^(\S+)\s+—\s+(.*)$", line)
        if match:
            name, rest = match.groups()
            licence = re.sub(r"\s*<.*$", "", rest).strip()
            entries.append(
                (
                    f"external:{name}",
                    {
                        "version": "",
                        "licence": (_licence_key(licence),),
                        "scope": "required",
                    },
                )
            )
    return entries or None


def _markdown_entries(text: str) -> Optional[List[Tuple[str, Dict[str, str]]]]:
    """The component entries of the Markdown licence report, in document order."""
    entries: List[Tuple[str, Dict[str, str]]] = []
    section = ""
    header: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            header = []
            continue
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if not header:
            header = cells
            continue
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        name = row.get("name", "")
        if not name:
            continue
        ecosystem = _section_ecosystem(section)
        if ecosystem in {"python", "npm"}:
            scope = "required" if row.get("declared", "").lower() == "true" else "optional"
        else:
            scope = "required"
        entries.append(
            (
                f"{ecosystem}:{name}",
                {
                    "version": row.get("version", ""),
                    "licence": (_licence_key(row.get("license", "")),),
                    "scope": scope,
                },
            )
        )
    return entries or None


def _sbom_entries(text: str) -> Optional[List[Tuple[str, Dict[str, str]]]]:
    """The component entries of an SBOM, in document order."""
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    components = doc.get("components")
    if not isinstance(components, list):
        return None
    entries: List[Tuple[str, Dict[str, str]]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        name = str(component.get("name", ""))
        if str(component.get("type", "")) == "application":
            continue
        licences = []
        for entry in component.get("licenses") or []:
            if not isinstance(entry, dict):
                continue
            inner = entry.get("license")
            if isinstance(inner, dict):
                licences.append(str(inner.get("id") or inner.get("name") or ""))
            else:
                licences.append(str(entry.get("expression") or ""))
        ecosystem = ""
        bundled = ""
        for prop in component.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            if prop.get("name") == "chemml:ecosystem":
                ecosystem = str(prop.get("value", ""))
            elif prop.get("name") == "chemml:bundled":
                bundled = str(prop.get("value", ""))
        entries.append(
            (
                f"{ecosystem}:{name}",
                {
                    "version": str(component.get("version", "")),
                    "licence": tuple(sorted(_licence_key(item) for item in licences)),
                    "scope": str(component.get("scope", "")),
                    # The ecosystem and the redistribution flag are statements
                    # the release makes about itself, so they are compared.
                    # ``chemml:installed`` deliberately is not: whether a
                    # package happens to be importable on the machine running
                    # the check is an environment fact, not a release fact.
                    "ecosystem": ecosystem,
                    "bundled": bundled,
                },
            )
        )
    return entries or None


def _artefact_entries(text: str) -> Optional[List[Tuple[str, Dict[str, str]]]]:
    """The component entries of whichever artefact *text* is."""
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return _sbom_entries(text)
    if "BUNDLED SOFTWARE" in text:
        return _notices_entries(text)
    return _markdown_entries(text)


def _differs_only_in_versions(path: Path, expected: str) -> bool:
    """True when the two artefacts assert the same thing about the release.

    A byte comparison would call the on-disk file stale whenever the
    machine's installed versions differ from the ones recorded when it was
    generated -- which is every machine except the one that generated it.
    Comparing the dependency facts instead asks the question a release
    actually cares about: do these two documents ship the same packages under
    the same licences?

    The comparison is deliberately *narrower* than a component-set
    comparison.  An earlier implementation extracted a dictionary of
    components and compared the keys, which meant the prose around them --
    the copyright holder, the project licence, the section headers, the
    upstream attribution -- was never compared at all.  Editing any of those
    lines left the check reporting "up to date" while the shipped document
    said something different from what the generator produces.

    So the artefacts are compared as **records**: the text is split into the
    prose lines and the structured component entries, the prose is compared
    byte-for-byte, and the entries are compared positionally with only the
    version field exempted (see :data:`_VERSION_FIELD`).
    """
    try:
        actual_text = _read_normalised(path)
    except OSError:
        return False

    # 1. The prose must be identical.  Strip the structured entries from
    #    both documents and compare what is left byte-for-byte.
    if _prose_of(actual_text) != _prose_of(_normalise_newlines(expected)):
        return False

    # 2. The structured entries must agree, version aside.
    actual = _artefact_entries(actual_text)
    wanted = _artefact_entries(expected)
    if actual is None or wanted is None:
        return False
    return _compare_entries(actual, wanted)


def _prose_of(text: str) -> str:
    """The document with its structured component entries removed.

    What is left is the prose: the headings, the legal statements, the
    section structure, the upstream attribution.  None of it depends on the
    machine the artefact was generated on, so all of it must match exactly.
    """
    stripped = text.lstrip()
    if stripped.startswith("{"):
        # An SBOM is JSON: its prose is everything outside the component list.
        try:
            doc = json.loads(text)
        except ValueError:
            return text
        rest = {k: v for k, v in doc.items() if k != "components"}
        return json.dumps(rest, sort_keys=True, ensure_ascii=False)

    kept: List[str] = []
    ecosystem = ""
    in_table = False
    header: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # -- NOTICE ------------------------------------------------------- #
        if "BUNDLED SOFTWARE" in text:
            notice_header = re.match(r"^--\s*(Python|JavaScript)\s+dependency notice", line)
            if notice_header:
                ecosystem = "python" if notice_header.group(1) == "Python" else "npm"
                kept.append(line)
                continue
            if line.startswith("=") or line.startswith("BUNDLED") or line.startswith("EXTERNAL"):
                if line.startswith("="):
                    ecosystem = ""
                kept.append(line)
                continue
            if line.startswith("UPSTREAM"):
                ecosystem = ""
                kept.append(line)
                continue
            row = re.match(r"^(\S+)\s+(\S+)\s+—\s+(.*)$", line)
            if row and ecosystem:
                continue  # a bundled component entry
            row = re.match(r"^(\S+)\s+—\s+(.*)$", line)
            if row:
                continue  # an external component entry
            kept.append(line)
            continue

        # -- Markdown ----------------------------------------------------- #
        if line.startswith("## "):
            in_table = False
            header = []
            kept.append(line)
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                kept.append(line)
                continue
            if not header:
                header = cells
                kept.append(line)
                continue
            if len(cells) == len(header) and "name" in header:
                continue  # a component table row
            kept.append(line)
            continue
        kept.append(line)
    return "\n".join(kept)


def collect() -> Dict[str, Any]:
    python_deps = python_components()
    npm_deps = frontend_components()
    external = external_components()
    datasets = dataset_components()
    assets = bundled_assets()
    problems = cleanliness_scan()
    return {
        "python": python_deps,
        "npm": npm_deps,
        "external": external,
        "datasets": datasets,
        "assets": assets,
        "problems": problems,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "verify that the on-disk sbom.json / NOTICE / THIRD_PARTY_LICENSES.md are "
            "identical to what would be generated; exit 1 on drift or a licence problem. "
            "Never writes."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="(re)generate sbom.json, NOTICE and docs/THIRD_PARTY_LICENSES.md",
    )
    parser.add_argument("--print", dest="do_print", action="store_true", help="print the summary")
    parser.add_argument(
        "--out-dir",
        default=None,
        help=(
            "write the artefacts under this directory instead of the repository root. "
            "Used by the test suite so that exercising --write never touches the "
            "real sbom.json / NOTICE / THIRD_PARTY_LICENSES.md in the tree."
        ),
    )
    args = parser.parse_args(argv)

    out_root = Path(args.out_dir).resolve() if args.out_dir else ROOT

    data = collect()
    sbom = build_sbom(data["python"], data["npm"], data["external"], data["datasets"])
    notice = build_notice(data["python"], data["npm"], data["external"])
    markdown = build_markdown(
        data["python"], data["npm"], data["external"], data["datasets"], data["assets"], data["problems"]
    )

    sbom_text = json.dumps(sbom, indent=2, ensure_ascii=False)
    targets = [
        (out_root / "sbom.json", sbom_text),
        (out_root / "NOTICE", notice),
        (out_root / "docs" / "THIRD_PARTY_LICENSES.md", markdown),
    ]

    # v0.7.2 fix: this function used to write all three files *unconditionally*,
    # including in --check mode.  A check that rewrites the artefacts it is
    # supposed to check can never detect a stale or tampered one, and it made
    # the release manifest's recorded hashes drift on every gate run.  Writing
    # is now explicit; --check compares and refuses to touch anything.
    #
    # v0.7.4 fix: the comparison used to be byte-for-byte, which made the
    # check unpassable on any machine but the one that generated the files.
    # These artefacts record *installed* versions, and an installed version
    # is a property of the environment, not of the release: CI resolves
    # ``numpy>=1.26,<3.0`` to whatever was current that day, so the same
    # commit produced a different SBOM on every runner and the check
    # reported "stale" for a file nobody had touched.
    #
    # What a release actually asserts about its dependencies is *which*
    # packages it ships and under *which* licence -- that is what a
    # distributor needs to comply with, and it is stable across machines.
    # The exact version stays in the file for a human to read; it simply
    # does not decide whether the file is stale.
    drift: List[str] = []
    if args.check:
        for path, expected in targets:
            try:
                label = path.relative_to(ROOT).as_posix()
            except ValueError:
                # The artefact lives outside the repository (a test's temporary
                # output directory).  Its absolute path is the only honest label.
                label = path.as_posix()
            if not path.exists():
                drift.append(f"missing:{label}")
                continue
            if _read_normalised(path) != _normalise_newlines(expected):
                if _differs_only_in_versions(path, expected):
                    continue
                drift.append(f"stale:{label}")
    else:
        for path, expected in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")

    review = _license_review(data["python"] + data["npm"])
    # Only a *required* declared dependency being absent is a blocker.  An
    # absent optional connector (e.g. the commented-out `faiss-cpu`) degrades a
    # capability by design and must not fail the licence check.
    unresolved = [
        c["name"]
        for c in data["python"]
        if not c["installed"] and c.get("declared", True)
    ]
    optional_absent = [
        c["name"]
        for c in data["python"]
        if not c["installed"] and not c.get("declared", True)
    ]
    blockers: List[str] = []
    blockers += [
        f"cleanliness:{key}={len(values)}"
        for key, values in data["problems"].items()
        if values and key not in _INFO_KEYS
    ]
    if unresolved:
        blockers.append(f"python-unresolved={len(unresolved)}")
    # A stale or missing release artefact is itself a blocker: the whole point of
    # the check is that the shipped file matches the shipped dependencies.
    blockers += drift

    if args.do_print:
        print(f"python components : {len(data['python'])} ({len(unresolved)} required unresolved)")
        if optional_absent:
            print(f"  optional not installed (capability degraded by design): {optional_absent}")
        print(f"npm components    : {len(data['npm'])}")
        print(f"external programs : {len(data['external'])}")
        print(f"datasets          : {len(data['datasets'])}")
        print(f"bundled assets    : {len(data['assets'])}")
        for key, values in data["problems"].items():
            print(f"  cleanliness {key}: {len(values)}")
        print(f"licence review    : {len(review)}")
        for item in review:
            print(f"    ! {item}")

    print(f"[{'FAIL' if (args.check and blockers) else 'PASS'}] licence/SBOM report "
          f"({len(data['python'])} py / {len(data['npm'])} npm / {len(data['external'])} external)")
    if optional_absent:
        print(f"  note: optional components not installed: {optional_absent} "
              "(capability degradation, not a failure)")
    if args.check and blockers:
        for blocker in blockers:
            print(f"  ! {blocker}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
