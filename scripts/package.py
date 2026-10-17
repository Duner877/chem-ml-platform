"""Package the repository into a clean distributable zip.

Excludes development/runtime artefacts that a fresh checkout regenerates:
node_modules, caches, __pycache__, runtime output, editor metadata.

Release-blocking rule (v0.7.3 audit P0-1): *never ship user state*.  The
archive is public.  Anything that can hold a secret -- provider credentials,
the desktop session token, ``.env`` files, the Agent's long-term memory, a
user's private plugins, audit logs -- must be excluded by a **positive
allow-list**, not by "skip the one file I remembered".  A deny-list silently
stops protecting the moment somebody adds ``config/tokens.json``.

After the archive is written it is re-opened and scanned
(:func:`scan_archive`).  If any secret pattern or forbidden path survived into
the zip, the build fails loudly and the archive is removed -- shipping it is
worse than not shipping it.

Usage::

    python scripts/package.py                          # ../<repo-dir>.zip
    python scripts/package.py --name Chem-ML-Platform-v0.6.0 \
        --output ../Chem-ML-Platform-v0.6.0.zip
    python scripts/package.py --no-scan                # skip the secret scan
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

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

#: Top-level trees never shipped.  Matched on the **first** path segment only:
#: a user's private nodes live in ``plugins/``, but the tracked example node in
#: ``examples/plugins/`` is source and must keep shipping.  A segment-wise
#: match would delete the example along with the private one.
EXCLUDED_TOP_LEVEL = {
    "plugins",
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

#: The **only** paths under ``config/`` allowed into a public archive.
#:
#: v0.7.3 audit P0-1: this used to be ``return rel_posix.endswith("ai.json")``,
#: which reads like an allow-list but is a single deny-entry.  ``config/`` is
#: where the platform puts provider API keys (``credentials.json``) and the
#: desktop session token (``session.json``); both are plaintext.  The rule is
#: inverted so a *new* secret file is excluded by default and has to be argued
#: into the allow-list on purpose.
CONFIG_ALLOWLIST = {
    "config/.gitkeep",
    "config/ai.example.json",
    "config/ai.json.example",
}

#: Secret shapes that must never appear in a public archive.  These are
#: deliberately narrow: a pattern so loose that it matches documentation would
#: train everyone to ignore the scanner, which is worse than no scanner.
SECRET_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    (r"(?i)\bsk-[A-Za-z0-9]{20,}", "OpenAI-style secret key"),
    (r"(?i)\bsk-ant-[A-Za-z0-9_-]{20,}", "Anthropic-style secret key"),
    (r"(?i)\bAIza[0-9A-Za-z_-]{30,}", "Google API key"),
    (r"(?i)\bgh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"(?i)\bxox[abposr]-[A-Za-z0-9-]{20,}", "Slack token"),
    (r"(?i)\bAKIA[0-9A-Z]{16}\b", "AWS access key id"),
    (r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']",
     "inline credential assignment"),
)

#: Files whose content legitimately contains credential-*shaped* text (docs
#: describing the format, the example config, the pattern definitions
#: themselves).
SECRET_SCAN_ALLOWLIST = {
    "config/ai.example.json",
    ".env.example",
    # The scanners' own patterns are, necessarily, credential-shaped.  Every
    # file that greps for a secret has to spell that secret out to grep for it,
    # so each one lands here -- listed individually, never as a directory rule:
    # a directory exemption would wave through a real key stored next to it.
    "scripts/package.py",
    "scripts/license_report.py",
    "scripts/quality_gate.py",
    "LICENSE",
    "NOTICE",
    "CHANGELOG.md",
}

#: Directory prefixes whose files are exempt from the *content* scan (the path
#: rules still apply).  Test fixtures and documentation legitimately quote
#: ``sk-...`` / ``-----BEGIN PRIVATE KEY-----`` in order to assert that the
#: scanners catch them; scanning them would mean a false positive every time
#: somebody adds a regression test for the very thing being defended.
SECRET_SCAN_EXEMPT_PREFIXES = (
    "tests/",
    "docs/",
    "examples/",
)

#: Archive entries that must never exist, checked by path after the zip is
#: written.  Kept separate from :func:`should_skip` because this is the *last*
#: line of defence -- it catches a rule that silently stopped applying.
#:
#: ``config/`` is deliberately **absent** from this table: it is validated
#: against :data:`CONFIG_ALLOWLIST` in :func:`scan_archive` itself, so the rule
#: and its scan cannot drift apart the way a duplicated regex would.
FORBIDDEN_ARCHIVE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"(?:^|/)\.env(?:\.|$)", ".env file"),
    (r"(?:^|/)credentials\.json$", "credential store"),
    (r"(?:^|/)session\.json$", "desktop session token"),
    # Top-level only, for the same reason as EXCLUDED_TOP_LEVEL: the tracked
    # ``examples/plugins/melting_point_note.py`` is source, not a leak.
    (r"^plugins/", "private plugin"),
    (r"(?:^|/)memory/[^/]*\.json$", "agent memory state"),
    (r"(?:^|/)output/(?!$|\.gitkeep$)", "runtime output"),
    (r"(?:^|/)workspace/(?!$|\.gitkeep$)", "user workspace"),
    (r"\.pem$|\.key$|\.p12$|\.pfx$|\.keystore$", "private key container"),
    (r"(?:^|/)(?:id_rsa|id_ed25519)$", "ssh private key"),
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
    if rel_posix.startswith("desktop/dist/") or rel_posix.startswith("desktop/out/"):
        return True
    if rel.parts and rel.parts[0] in EXCLUDED_TOP_LEVEL:
        return True
    if rel_posix.endswith(EXCLUDED_SUFFIXES):
        return True

    # Dotenv files (root or nested): the canonical place a developer parks an
    # OPENAI_API_KEY.  ``.env.example`` is documentation and ships.
    name = rel.name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True

    # Key material.  These are in the *rule* and not only in the post-build
    # scan on purpose: excluding them here means they are never even read off
    # the disk into the archive, while the scan still catches them if a future
    # edit reorders the branches.
    if rel_posix.endswith((".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")):
        return True
    if name in ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"):
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

    # The build stamp is injected explicitly by build_info() below.  The
    # desktop beforeBuild hook also leaves one in the tree (so extraResources
    # can copy it); walking it in as well would put a second -- possibly older
    # -- stamp under the same archive name.
    if rel_posix == "BUILD_INFO.json":
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

    # config/ holds plaintext API keys and the desktop session token.
    # v0.7.3 audit P0-1: positive allow-list, not a one-entry deny-list.
    if rel_posix.startswith("config/"):
        return rel_posix not in CONFIG_ALLOWLIST

    return False


def _compiled_secret_patterns() -> Tuple[Tuple[re.Pattern[str], str], ...]:
    """Compile :data:`SECRET_PATTERNS` **once**, as a tuple.

    A tuple, not a generator on purpose: :func:`scan_archive` iterates this
    once per archive entry, and a generator would be exhausted after the first
    file -- so entry #2 onward would pass the content scan unexamined while
    looking exactly as thorough in the code.
    """
    return tuple((re.compile(pattern), label) for pattern, label in SECRET_PATTERNS)


def scan_archive(archive: Path, root_name: str = "") -> list[str]:
    """Return a list of problems found inside *archive* (empty == clean).

    This is deliberately a *separate* pass over the finished zip rather than a
    lookup into :func:`should_skip`: it re-derives the verdict from what was
    actually written, so a rule that stopped matching (renamed constant, new
    branch, reordering bug) surfaces here instead of shipping.
    """
    problems: list[str] = []
    patterns = _compiled_secret_patterns()
    prefix = f"{root_name}/" if root_name else ""

    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            arc = info.filename
            if arc.endswith("/"):
                continue
            rel = arc[len(prefix):] if prefix and arc.startswith(prefix) else arc

            for pattern, label in FORBIDDEN_ARCHIVE_PATTERNS:
                if re.search(pattern, rel):
                    problems.append(f"{rel} ({label})")

            # Same predicate as should_skip's config/ branch, reading the same
            # constant -- one rule, two enforcement points.
            if rel.startswith("config/") and rel not in CONFIG_ALLOWLIST:
                problems.append(f"{rel} (config/ file outside the allow-list)")

            if (
                rel in SECRET_SCAN_ALLOWLIST
                or rel.startswith(SECRET_SCAN_EXEMPT_PREFIXES)
                or info.file_size > 512 * 1024
            ):
                continue
            try:
                text = zf.read(info).decode("utf-8")
            except (UnicodeDecodeError, zipfile.BadZipFile):
                continue  # binary payload: the path rules above are the net
            for regex, label in patterns:
                if regex.search(text):
                    problems.append(f"{rel} ({label})")
    return problems


def build_info() -> dict:
    """The build stamp written into the archive (v0.7.2 fix, ISSUE-21).

    An extracted archive is not a Git checkout, so without this file every
    distributed copy answered ``git_commit() == "unknown"`` -- including copies
    the release report describes as traceable.  The stamp is generated here and
    injected straight into the archive, never written into the working tree, so
    packaging cannot itself dirty the tree it is recording.

    The fields come from :func:`chemml_version.build_stamp`, which the Electron
    payload refresh shares, so the archive and the desktop shell cannot describe
    the same build differently.
    """
    sys.path.insert(0, str(ROOT))
    from chemml_version import build_stamp

    return build_stamp("scripts/package.py")


def build(output: Path, name: str = "", scan: bool = True) -> tuple[int, int]:
    """Write the archive and return (file_count, total_bytes).

    When *scan* is true the finished archive is re-read and checked for leaked
    secrets; a hit removes the archive and raises.  An archive that contains an
    API key must not exist on disk, not even briefly, because the next
    ``cp *.zip somewhere`` is exactly how it would escape.
    """
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

    if scan:
        problems = scan_archive(output, root_name=root_name)
        if problems:
            output.unlink(missing_ok=True)
            listed = "\n  ".join(sorted(set(problems))[:40])
            raise SystemExit(
                f"REFUSING TO PUBLISH {output.name}: {len(set(problems))} "
                f"secret/leak finding(s) inside the archive:\n  {listed}\n"
                "The archive was deleted. Fix should_skip() / SECRET_PATTERNS "
                "before re-running."
            )
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
    parser.add_argument(
        "--no-scan",
        action="store_true",
        help="skip the post-build secret scan (never use for a public release)",
    )
    args = parser.parse_args()

    output = Path(args.output)
    count, total = build(output, name=args.name, scan=not args.no_scan)
    size = output.stat().st_size
    print(f"archive : {output}")
    print(f"root    : {args.name or ROOT.name}")
    print(f"files   : {count}")
    print(f"payload : {total / 1024:.1f} KiB")
    print(f"size    : {size / 1024:.1f} KiB (compressed)")
    if args.no_scan:
        print("scan    : SKIPPED (--no-scan)")
    else:
        print("scan    : clean (no secret patterns, no forbidden paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
