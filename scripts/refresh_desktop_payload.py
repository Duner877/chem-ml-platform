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


#: Directories an installed copy writes into while the user works.  Files here
#: belong to the user, not to the build, so they are neither stale payload nor
#: anything this script may delete.
RUN_TIME_ROOTS = ("output", "memory", "config")

#: Directory names that are deliberately kept at an older version.  A backup
#: taken before an upgrade is *supposed* to disagree with the source, so
#: reporting it as stale would train the reader to ignore the report.
_BACKUP_MARKERS = (".bak", "backup", ".old")


def _is_run_time_artifact(rel: Path) -> bool:
    """True for files the running app produced, not for files the build copied."""
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in RUN_TIME_ROOTS:
        return True
    # ``config/`` ships with defaults but the app rewrites single files in it
    # (e.g. ``ai.json`` after an API key is entered), so treat the whole
    # directory as user state rather than risk deleting a saved setting.
    return False


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
        if dst == app / "BUILD_INFO.json":
            # Generated below, never copied: the beforeBuild hook leaves its own
            # stamp in the tree, and copying it over the payload's would fight
            # the stamp logic -- each run would flip the file between the two
            # versions and report two spurious updates forever.
            continue
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
    # drop it, or a deleted module keeps shadowing its replacement.  Run-time
    # output is exempt -- a user who ran workflows in the installed copy has
    # results in ``output/`` and ``memory/`` there, and this tool must not be
    # the thing that deletes them.
    wanted = {dst.relative_to(app) for _, dst in _inside(app, pairs)}
    wanted.add(Path("BUILD_INFO.json"))
    stale = sorted(
        rel
        for rel in _snapshot_files(app) - wanted
        if not _is_run_time_artifact(rel)
    )
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
    everything = _snapshot_files(app) - wanted
    runtime = sorted(rel for rel in everything if _is_run_time_artifact(rel))
    stale = sorted(rel for rel in everything if not _is_run_time_artifact(rel))
    stamp = app / "BUILD_INFO.json"
    print(f"payload entries expected : {len(pairs)}")
    print(f"missing from snapshot    : {len(missing)}")
    print(f"differing from source    : {len(differing)}")
    print(f"stale (not in plan)      : {len(stale)}")
    print(f"run-time output (kept)   : {len(runtime)}")
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


def _candidate_install_dirs() -> list[Path]:
    """Every ``resources/app`` a launcher on this machine could actually start.

    ``DEFAULT_APP`` is only the repo's own build output.  The app the user
    double-clicks lives somewhere else entirely -- in v0.7.2 the desktop
    shortcut pointed at ``Desktop/0.5/Chem ML Platform/``, a directory this
    script had never looked at, so it happily reported ``AGREES`` about a
    snapshot nobody was running.  A verification that cannot see the thing the
    user launches is worse than none, so candidates are discovered rather than
    assumed.
    """
    here = ROOT.parent
    seen: dict[str, Path] = {}

    def offer(path: Path) -> None:
        if not path.is_dir():
            return
        lowered = str(path).lower()
        if any(marker in lowered for marker in _BACKUP_MARKERS):
            return
        seen[lowered] = path

    def offer_always(path: Path) -> None:
        """Offer a path even when it does not exist yet.

        Used for the repository's own build output.  The function's contract
        says that output is *always* in the list, and it has to be: a fresh
        checkout has no ``desktop/dist/win-unpacked/resources/app`` yet, and
        a tool that silently omits it then reports "nothing found" instead of
        "not built yet".  Those are different answers and only one of them is
        useful -- the same reason a missing directory must be named rather
        than hidden.

        The backup filter still applies: a ``.bak`` copy is never the thing
        to report.
        """
        lowered = str(path).lower()
        if any(marker in lowered for marker in _BACKUP_MARKERS):
            return
        seen[lowered] = path

    # The repo lives inside a working folder (``Desktop/0.5 - 副本/``) while the
    # launcher often lives in a *sibling* of that folder (``Desktop/0.5/``).
    # Every ancestor is searched, not just the first two: a fixed depth silently
    # loses the installed copy the moment the repo is moved one level deeper,
    # and the symptom is a reassuring ``AGREES`` about a snapshot nobody runs --
    # which is the exact failure this function exists to prevent.  When that
    # regression bit, moving the repo into ``01-源码/v0.7.3-active/`` dropped the
    # user's install from the report without a single error.
    bases = [here, *here.parents]
    # ``here.parents`` runs all the way to the drive root; the desktop layout we
    # care about is never that deep, and each extra level costs a directory
    # listing.  Four levels covers a repo nested well inside a working folder.
    bases = bases[:4]
    for base in bases:
        # The repo's own build output and its install copy.
        for child in sorted(base.glob("*")):
            offer(child / "desktop" / "dist" / "win-unpacked" / "resources" / "app")
            # A plain unpacked install (what the NSIS installer writes).
            if child.is_dir():
                offer(child / "resources" / "app")
        # One level deeper, so ``Desktop/0.5/Chem ML Platform/`` is reachable.
        for child in sorted(base.glob("*/*")):
            if child.is_dir():
                offer(child / "resources" / "app")
    # The repo's own build output is always in the list -- whether or not it
    # has been built yet.
    offer_always(DEFAULT_APP)
    return [seen[key] for key in sorted(seen)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="report only, change nothing")
    parser.add_argument("--app", default=str(DEFAULT_APP), help="path to resources/app")
    parser.add_argument(
        "--all-installed",
        action="store_true",
        help="verify every installed resources/app found next to the repo",
    )
    parser.add_argument(
        "--refresh-all",
        action="store_true",
        help="refresh every installed resources/app found next to the repo",
    )
    args = parser.parse_args()

    if args.all_installed or args.refresh_all:
        targets = _candidate_install_dirs()
        if not targets:
            print("[ERROR] no packaged app found", file=sys.stderr)
            return 2
        print(f"found {len(targets)} installed app director(ies)\n")
        failures = 0
        checked = 0
        for target in targets:
            marker = "repo" if target.resolve() == DEFAULT_APP.resolve() else "installed"
            print(f"--- {marker}: {target}")
            if not target.is_dir():
                # A candidate that does not exist yet is not a stale snapshot --
                # it is an app that was never built.  Two reasons this must not
                # be swept up with the rest: ``refresh()`` would *create* the
                # directory tree and leave a half-populated app behind, and
                # ``verify()`` would call every payload file missing and report
                # STALE for something that was never shipped.  Name it, skip it.
                print("  not built yet -- nothing to verify or refresh")
                print()
                continue
            checked += 1
            if args.all_installed:
                failures += verify(target)
            else:
                copied, stale, total = refresh(target)
                print(f"  updated {copied}/{total}, removed {stale}")
            print()
        if failures:
            print(f"{failures} of {checked} snapshot(s) STALE")
            return 1
        return 0

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
