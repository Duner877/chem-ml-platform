"""Package the repository into a clean distributable zip.

Excludes development/runtime artefacts that a fresh checkout regenerates:
node_modules, caches, __pycache__, runtime output, editor metadata.

Usage::

    python scripts/package.py                          # ../<repo-dir>.zip
    python scripts/package.py --name Chem-ML-Platform-v0.6.0 \
        --output ../Chem-ML-Platform-v0.6.0.zip
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Directories never shipped (matched against any path segment).
EXCLUDED_DIRS = {
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".vite",
    "venv",
    ".venv",
    "env",
    ".mypy_cache",
    ".ruff_cache",
    "ui_shots",
    "scratch",
}

#: File patterns never shipped.
EXCLUDED_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".log",
    ".tsbuildinfo",
    ".zip",
    ".tmp",
)


def should_skip(rel: Path) -> bool:
    """Return True when a file must not enter the archive.

    Global excludes (VCS/cache dirs and cache suffixes) are evaluated **before**
    the per-tree re-include rules, so a ``.pyc`` inside ``memory/__pycache__``
    cannot slip through a later ``memory/`` branch.
    """
    rel_posix = rel.as_posix()

    # Global excludes: matched anywhere along the path.
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True
    if rel_posix.endswith(EXCLUDED_SUFFIXES):
        return True

    # Explicit re-includes / targeted rules.
    # The pre-built frontend is required by the Dockerfile: always shipped.
    if rel_posix.startswith("frontend/dist/"):
        return False

    # Desktop build output (NSIS / AppImage / dmg) is a *release asset*, not
    # source: never ship it inside the source archive.
    if rel_posix.startswith("desktop/dist/") or rel_posix.startswith("desktop/out/"):
        return True

    # The checksum manifest must NOT travel inside the archive it checksums.
    # It records the archive's own SHA-256 (a value that only exists after the
    # archive is written) alongside machine-local absolute paths, so an in-archive
    # copy is guaranteed to be one generation stale -- and would make the archive
    # hash depend on a file that describes that very hash.  It is published beside
    # the archive instead, where a downloader can actually use it.
    if rel_posix == "SHA256SUMS":
        return True

    # Release manifest is derived from the archive too (same reasoning).
    if rel_posix in ("docs/RELEASE_MANIFEST.md", "docs/RELEASE_MANIFEST.json"):
        return True

    # Runtime output: everything except the placeholder that keeps the dir.
    if rel_posix.startswith("output/"):
        return rel_posix != "output/.gitkeep"

    # Upload workspace: runtime state, exactly like output/.  v0.7.2 fix
    # (ISSUE-19): a 3-byte test fixture (workspace/raw_data/x.csv) had been
    # committed and was shipping inside every source archive.  Only the
    # placeholder that keeps the directory present on a fresh clone ships.
    if rel_posix.startswith("workspace/"):
        return rel_posix != "workspace/.gitkeep"

    # Agent runtime memory: ship the source module, never the accumulated
    # state document (memory/memory.json is regenerated on first use).
    if rel_posix.startswith("memory/"):
        return rel_posix.endswith(".json")

    # AI configuration may hold API keys: ship only the example + placeholder.
    if rel_posix.startswith("config/"):
        return rel_posix.endswith("ai.json")

    return False


def build_info() -> dict:
    """The build stamp written into the archive (v0.7.2 fix, ISSUE-21).

    An extracted archive is not a Git checkout, so without this file every
    distributed copy answered ``git_commit() == "unknown"`` -- including copies
    the release report describes as traceable.  The stamp is generated here and
    injected straight into the archive, never written into the working tree, so
    packaging cannot itself dirty the tree it is recording.
    """
    import subprocess

    sys.path.insert(0, str(ROOT))
    from chemml_version import __codename__, __version__

    def _git(*args: str) -> str:
        try:
            out = subprocess.run(
                ["git", *args], cwd=str(ROOT), capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (out.stdout or "").strip() if out.returncode == 0 else ""

    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "version": __version__,
        "codename": __codename__,
        "commit": commit or "unknown",
        "commit_short": commit[:7] if commit else "unknown",
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": (
            "Generated by scripts/package.py and injected into the archive. "
            "`dirty: true` means the tree had uncommitted changes at packaging "
            "time, so the commit identifies the base, not the exact content."
        ),
    }


def build(output: Path, name: str = "") -> tuple[int, int]:
    """Write the archive and return (file_count, total_bytes)."""
    root_name = name or ROOT.name
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if should_skip(rel):
            continue
        files.append(rel)

    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    total = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            source = ROOT / rel
            # Keep the top-level folder so the archive extracts cleanly.
            arcname = Path(root_name) / rel
            zf.write(source, arcname)
            count += 1
            total += source.stat().st_size
        # Injected, not written to disk: the tree stays exactly as released.
        stamp = json.dumps(build_info(), ensure_ascii=False, indent=2) + "\n"
        zf.writestr(str(Path(root_name) / "BUILD_INFO.json"), stamp)
        count += 1
        total += len(stamp.encode("utf-8"))
    return count, total


def main() -> int:
    parser = argparse.ArgumentParser(description="Package the repository as a zip")
    parser.add_argument(
        "--output",
        default=str(ROOT.parent / f"{ROOT.name}.zip"),
        help="destination archive path",
    )
    parser.add_argument(
        "--name",
        default="",
        help="top-level folder inside the archive (defaults to the repo dir name)",
    )
    args = parser.parse_args()

    output = Path(args.output)
    count, total = build(output, name=args.name)
    size = output.stat().st_size
    print(f"archive : {output}")
    print(f"root    : {args.name or ROOT.name}")
    print(f"files   : {count}")
    print(f"payload : {total / 1024:.1f} KiB")
    print(f"size    : {size / 1024:.1f} KiB (compressed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
