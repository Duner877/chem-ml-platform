"""Refresh the Python payload inside an already-built ``win-unpacked`` app.

``electron-builder`` copies the sources listed in ``extraResources`` into
``resources/app/`` at build time.  When a source fix lands *after* the shell was
built, the packaged app keeps serving the stale snapshot -- the exact failure
this script exists to prevent (v0.7.2: the shipped ``win-unpacked`` ran a
pre-fix backend while the repo tree was already corrected).

Rebuilding the whole shell costs minutes and re-downloads nothing, but it is
unnecessary when only the Python payload changed.  This script performs exactly
the copy ``extraResources`` describes, and nothing more:

* every ``extraResources`` entry, honouring its ``filter`` globs,
* deletions included, so a file removed from the source tree also disappears
  from the snapshot (otherwise stale modules would linger and shadow fixes),
* a ``--verify`` mode that reports the snapshot's agreement with the source.

Usage::

    python scripts/refresh_desktop_payload.py            # refresh in place
    python scripts/refresh_desktop_payload.py --verify   # report only
    python scripts/refresh_desktop_payload.py --app PATH # explicit app dir
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
DEFAULT_APP = DESKTOP / "dist" / "win-unpacked" / "resources" / "app"


def _extra_resources() -> list[dict]:
    build = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))["build"]
    return list(build.get("extraResources") or [])


def _segment_matches(pattern_segment: str, path_segment: str) -> bool:
    """minimatch, not :mod:`fnmatch`, semantics for one path segment.

    In minimatch a wildcard does **not** match a leading dot unless the
    pattern itself has one there (``dot: false`` is the default, and it is what
    electron-builder uses).  This is why ``plugins/.gitkeep`` is *not* shipped
    by a filter of ``**/*`` -- electron-builder never copies it, and a tool that
    mirrors its behaviour must not pretend otherwise.
    """
    if path_segment.startswith(".") and not pattern_segment.startswith("."):
        return False
    return fnmatch.fnmatch(path_segment, pattern_segment)


def _segments_match(pattern_segments: list[str], path_segments: list[str]) -> bool:
    if not pattern_segments:
        return not path_segments
    head = pattern_segments[0]
    rest = pattern_segments[1:]
    if head == "**":
        # Globstar matches zero or more path segments, so ``**/*.py`` covers
        # both ``foo.py`` and ``a/b/foo.py`` (fnmatch's translation of the same
        # pattern requires a slash and silently rejects the bare filename).
        for index in range(len(path_segments) + 1):
            if _segments_match(rest, path_segments[index:]):
                return True
        return False
    if not path_segments:
        return False
    if not _segment_matches(head, path_segments[0]):
        return False
    return _segments_match(rest, path_segments[1:])


def _matches_any(rel: Path, patterns: list[str]) -> bool:
    """electron-builder glob semantics, not :mod:`fnmatch` semantics."""
    path_segments = rel.as_posix().split("/")
    return any(
        _segments_match(pattern.split("/"), path_segments) for pattern in patterns
    )


def _wanted(rel: Path, filters: list[str]) -> bool:
    """electron-builder semantics: positive globs include, ``!`` globs exclude."""
    positive = [p for p in filters if not p.startswith("!")]
    negative = [p[1:] for p in filters if p.startswith("!")]
    if positive and not _matches_any(rel, positive):
        return False
    if negative and _matches_any(rel, negative):
        return False
    return True


def _plan(app: Path) -> list[tuple[Path, Path]]:
    """(source, destination) pairs the builder would have produced.

    Destinations are resolved against ``app`` so the same plan can refresh the
    snapshot in this repository *or* in a deployed copy elsewhere.
    """
    app = app.resolve()
    pairs: list[tuple[Path, Path]] = []
    for entry in _extra_resources():
        src = (DESKTOP / entry["from"]).resolve()
        rel_dest = entry["to"]
        if rel_dest.startswith("app/"):
            dst = app / rel_dest[len("app/"):]
        else:
            # ``python-runtime`` sits beside ``app/`` inside resources/.
            dst = app.parent / rel_dest
        filters = entry.get("filter") or ["**/*"]
        if src.is_file():
            if _wanted(src.relative_to(src.parent), filters):
                pairs.append((src, dst))
            continue
        if not src.is_dir():
            continue
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            if _wanted(path.relative_to(src), filters):
                pairs.append((path, dst / path.relative_to(src)))
    return pairs


def _snapshot_files(app: Path) -> set[Path]:
    app = app.resolve()
    return {
        p.relative_to(app)
        for p in app.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def _inside(app: Path, pairs: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Pairs whose destination lives inside ``app``.

    ``extraResources`` also copies ``resources/python-runtime``, which sits
    *beside* ``app/`` rather than inside it -- so it is payload, but not part of
    the ``app`` snapshot and must not take part in stale-file detection.
    """
    return [(src, dst) for src, dst in pairs if dst.is_relative_to(app)]


def refresh(app: Path = DEFAULT_APP) -> tuple[int, int, int]:
    app = app.resolve()
    pairs = _plan(app)
    copied = 0
    for src, dst in pairs:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            shutil.copy2(src, dst)
            copied += 1

    # Provenance: the shell runs resources/app, which is not a Git checkout, so
    # without a stamp the desktop build reports commit "unknown" -- the same
    # defect the source archive fixed.  Same fields, same code, same answer.
    sys.path.insert(0, str(DESKTOP.parent))
    from chemml_version import build_stamp

    stamp = app / "BUILD_INFO.json"
    try:
        existing = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    current = build_stamp("scripts/refresh_desktop_payload.py")
    # Only (re)stamp when there is nothing to keep or it names a different
    # commit.  The desktop beforeBuild hook writes this file too, with its own
    # produced_by/built_at; rewriting an agreeing stamp every run would make
    # the snapshot differ from a fresh build for no reason.
    if not isinstance(existing, dict) or existing.get("commit") != current["commit"]:
        text = json.dumps(current, indent=2) + "\n"
        if not stamp.exists() or stamp.read_text(encoding="utf-8") != text:
            stamp.write_text(text, encoding="utf-8")
            copied += 1

    # Anything the plan does not name is payload the builder never shipped:
    # drop it, or a deleted module keeps shadowing its replacement.
    wanted = {dst.relative_to(app) for _, dst in _inside(app, pairs)}
    wanted.add(Path("BUILD_INFO.json"))
    stale = sorted(_snapshot_files(app) - wanted)
    for rel in stale:
        (app / rel).unlink(missing_ok=True)
    for directory in sorted((p for p in app.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return copied, len(stale), len(pairs)


def verify(app: Path = DEFAULT_APP) -> int:
    app = app.resolve()
    pairs = _plan(app)
    missing, differing = [], []
    for src, dst in _inside(app, pairs):
        rel = dst.relative_to(app)
        if rel == Path("BUILD_INFO.json"):
            # A build-time stamp, not source: the beforeBuild hook and this
            # tool both write it with their own produced_by/built_at, so a
            # byte comparison would flag a difference that carries no
            # meaning.  What must agree is the commit it names -- checked
            # below against the tree this refresh would record.
            continue
        if not dst.exists():
            missing.append(str(rel))
        elif dst.read_bytes() != src.read_bytes():
            differing.append(str(rel))
    wanted = {dst.relative_to(app) for _, dst in _inside(app, pairs)}
    wanted.add(Path("BUILD_INFO.json"))
    stale = sorted(_snapshot_files(app) - wanted)
    stamp = app / "BUILD_INFO.json"
    print(f"payload entries expected : {len(pairs)}")
    print(f"missing from snapshot    : {len(missing)}")
    print(f"differing from source    : {len(differing)}")
    print(f"stale (not in plan)      : {len(stale)}")
    print(f"build stamp present      : {stamp.exists()}")
    for label, items in (("missing", missing), ("differing", differing), ("stale", stale)):
        for item in items[:10]:
            print(f"  {label}: {item}")
    stamp_agrees = stamp.exists() and _stamp_names_current_commit(stamp)
    ok = not (missing or differing or stale) and stamp_agrees
    if stamp.exists() and not stamp_agrees:
        print("  stamp names a different commit than this tree")
    print("AGREES" if ok else "STALE -- run without --verify to refresh")
    return 0 if ok else 1


def _stamp_names_current_commit(stamp: Path) -> bool:
    """True when the payload stamp records the commit this tree would stamp."""
    try:
        recorded = json.loads(stamp.read_text(encoding="utf-8")).get("commit", "")
    except (OSError, ValueError):
        return False
    if not recorded:
        return False
    sys.path.insert(0, str(DESKTOP.parent))
    from chemml_version import git_commit

    return recorded == git_commit(short=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="report only, change nothing")
    parser.add_argument("--app", default=str(DEFAULT_APP), help="path to resources/app")
    args = parser.parse_args()
    app = Path(args.app)
    if not app.is_dir():
        print(f"[ERROR] no packaged app at {app}", file=sys.stderr)
        return 2
    if args.verify:
        return verify(app)
    copied, stale, total = refresh(app)
    print(f"refreshed {app}")
    print(f"  updated : {copied} of {total} payload files")
    print(f"  removed : {stale} files no longer in the source tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
