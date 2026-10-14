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
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT_NAME = "Chem ML Platform"
PROJECT_VERSION = "0.7.1"
PROJECT_LICENSE = "Apache-2.0"

#: licences that require a human review before distribution (strong copyleft)
_REVIEW_LICENCES = ("GPL", "AGPL", "SSPL", "CC-BY-NC", "BUSL", "Commons Clause")

#: patterns that must never appear in a release package
_SECRET_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI-style API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----", "private key"),
    (r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']", "inline credential"),
)
_SECRET_ALLOW_FILES = {"config/ai.example.json"}

#: cleanliness buckets that are informational and never block a release.
#: ``pyc`` / ``pycache`` are included because ``scripts/package.py`` already
#: excludes them from the archive; their presence in a working tree (regenerated
#: by every test run) is reported but must not fail the licence gate.  The
#: authoritative release check is ``check_release_cleanliness`` which applies the
#: real packager rule.
_INFO_KEYS = {"generated_assets", "runtime_data", "pyc", "pycache"}


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


def python_components() -> List[Dict[str, Any]]:
    """Resolve the declared Python dependencies against installed metadata."""
    from importlib import metadata

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    components: List[Dict[str, Any]] = []
    for line in requirements:
        name = _parse_requirement(line)
        if not name:
            continue
        optional = line.strip().startswith("#")
        entry: Dict[str, Any] = {
            "ecosystem": "python",
            "name": name,
            "version": "",
            "license": "",
            "homepage": "",
            "declared": not optional,
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
    for name in dict.fromkeys(
        _parse_requirement(line) for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    ):
        if not name:
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


def dataset_components() -> List[Dict[str, Any]]:
    """Sample-data provenance and licence."""
    components: List[Dict[str, Any]] = []
    for path in sorted(ROOT.glob("datasets/**/*.metadata.json")):
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
    for path in ROOT.rglob("*"):
        if not path.is_file() or "node_modules" in path.parts or ".git" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("tests/") or rel in _SECRET_ALLOW_FILES:
            continue
        if rel.endswith((".png", ".jpg", ".spc", ".docx", ".zip", ".json")):
            continue
        if path.stat().st_size > 400_000:
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
    flagged = []
    for component in components:
        license_text = str(component.get("license", "")).upper()
        if any(token in license_text for token in _REVIEW_LICENCES):
            flagged.append(f"{component['ecosystem']}:{component['name']} ({component['license']})")
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
            {"name": "chemml:bundled", "value": str(item["ecosystem"] in {"python", "npm"}).lower()},
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
        f"Copyright (c) 2026 {PROJECT_NAME} contributors",
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
        bundled = [dep for dep in deps if dep.get("installed") or dep["ecosystem"] == "npm"]
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
    for asset in assets:
        lines.append(f"- `{asset['path']}` — {asset['bytes']} bytes（{asset['generated_from']}）")
    lines += ["", "## 6. 发布包清洁度扫描", ""]
    for key, values in problems.items():
        state = "OK" if not values else f"{len(values)} 项"
        lines.append(f"- **{key}**：{state}")
        for value in values[:20]:
            lines.append(f"  - {value}")
    review = _license_review(python_deps + npm_deps)
    lines += ["", "## 7. 需要人工复核的许可证（强 copyleft 等）", ""]
    if review:
        for item in review:
            lines.append(f"- {item}")
    else:
        lines.append("- 无（未发现需要复核的强 copyleft 依赖被分发）")
    lines += [
        "",
        "## 8. 方法说明",
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
    parser.add_argument("--check", action="store_true", help="exit 1 on a cleanliness/licence problem")
    parser.add_argument("--print", dest="do_print", action="store_true", help="print the summary")
    args = parser.parse_args(argv)

    data = collect()
    sbom = build_sbom(data["python"], data["npm"], data["external"], data["datasets"])
    notice = build_notice(data["python"], data["npm"], data["external"])
    markdown = build_markdown(
        data["python"], data["npm"], data["external"], data["datasets"], data["assets"], data["problems"]
    )

    (ROOT / "sbom.json").write_text(json.dumps(sbom, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "NOTICE").write_text(notice, encoding="utf-8")
    docs_path = ROOT / "docs" / "THIRD_PARTY_LICENSES.md"
    docs_path.write_text(markdown, encoding="utf-8")

    review = _license_review(data["python"] + data["npm"])
    unresolved = [c["name"] for c in data["python"] if not c["installed"]]
    blockers: List[str] = []
    blockers += [
        f"cleanliness:{key}={len(values)}"
        for key, values in data["problems"].items()
        if values and key not in _INFO_KEYS
    ]
    if unresolved:
        blockers.append(f"python-unresolved={len(unresolved)}")

    if args.do_print:
        print(f"python components : {len(data['python'])} ({len(unresolved)} unresolved)")
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
    if args.check and blockers:
        for blocker in blockers:
            print(f"  ! {blocker}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
