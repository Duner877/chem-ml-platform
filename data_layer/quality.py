"""Dataset metadata quality checks (v0.7.1 task G, spec §G.2-G.5).

Shared by the CLI (``scripts/dataset_governance.py``) and the REST layer
(``GET /api/data/quality``) so the *same* rules run before analysis.  The layer
is deliberately dependency-free apart from the standard library.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "SCHEMA_VERSION",
    "FAMILY_DATA_TYPES",
    "REQUIRED_KEYS",
    "metadata_files",
    "sha256_file",
    "normalise_record",
    "build",
    "check",
    "quality_report",
]

SCHEMA_VERSION = "1.0"

#: Which data types each family directory may contain.
FAMILY_DATA_TYPES: Dict[str, set] = {
    "demo": {"Table", "MassSpectrum", "NMRSpectrum", "IRSpectrum", "XRDPattern"},
    "nmr": {"NMRSpectrum"},
    "xrd": {"XRDPattern"},
    "spectroscopy": {"IRSpectrum", "UVVisSpectrum", "RamanSpectrum", "NIRSpectrum"},
    "microscopy": {"SEMImage", "TEMImage", "MicroscopyImage", "AFMImage"},
    "mass_spectrometry": {"MassSpectrum"},
}

#: Required keys of a governed metadata record.
REQUIRED_KEYS = (
    "schema_version", "name", "family", "data_type", "format",
    "license", "source", "files",
)

_META_SUFFIXES = (".metadata.json", ".parser.json", "metadata.json", "parser.json")
_META_NAMES = {"example_workflow.json", "README.md"}

_FORMAT_NAMES = {
    ".csv": "CSV", ".tsv": "TSV", ".xy": "XY", ".txt": "plain text",
    ".json": "JSON", ".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF",
    ".jdx": "JCAMP-DX", ".dx": "JCAMP-DX", ".spc": "Galactic SPC",
    ".cif": "CIF", ".mzml": "mzML", ".mgf": "MGF",
}


def _repository_bytes(path: Path) -> Optional[bytes]:
    """The file's bytes *as the repository stores them*, or ``None``.

    A working tree does not necessarily hold the bytes the repository holds.
    Git's ``core.autocrlf`` rewrites LF to CRLF on checkout, so the same
    commit gives a Windows working tree a 6 823-byte ``caffeine_ms.xy`` and a
    Linux checkout a 6 420-byte one.  A checksum that depends on the reader's
    operating system does not answer "is this the same data?" -- it answers
    "is this the same data, on a machine like mine?", and nobody else can
    check it.

    So the repository's own bytes are the reference: ``git cat-file`` reads
    the blob as committed, with no smudge filter applied, and every machine
    gets the same answer.

    ``None`` means "this file is not tracked here" -- a dataset installed
    outside the repository, or a plain directory of files.  The caller then
    falls back to the bytes on disk, which is the only definition available.
    """
    try:
        root = Path(__file__).resolve().parents[1]
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    try:
        out = subprocess.run(
            ["git", "cat-file", "-p", f"HEAD:{rel}"],
            cwd=str(root),
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def sha256_file(path: Path) -> str:
    """SHA-256 of the data file, independent of the checkout's line endings.

    See :func:`_repository_bytes` for why the repository's bytes win over the
    working tree's when the file is tracked.
    """
    blob = _repository_bytes(path)
    if blob is not None:
        return hashlib.sha256(blob).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def metadata_files(root: Path) -> List[Path]:
    """Every dataset metadata record under ``root`` (``datasets/``)."""
    found: List[Path] = []
    for path in sorted(root.rglob("*.json")):
        name = path.name
        if name in _META_NAMES:
            continue
        if name.endswith(".metadata.json") or name == "metadata.json":
            found.append(path)
    return found


def _family_of(meta_path: Path, root: Path) -> str:
    rel = meta_path.relative_to(root)
    return rel.parts[0] if len(rel.parts) > 1 else ""


def _payload_files(meta_path: Path) -> List[Path]:
    stem = meta_path.name.split(".")[0]
    folder = meta_path.parent
    if folder.suffix == ".d":
        candidates = [p for p in sorted(folder.rglob("*")) if p.is_file()]
    else:
        candidates = [p for p in sorted(folder.glob(f"{stem}.*")) if p.is_file()]
        dot = folder / f"{stem}.d"
        if dot.is_dir():
            candidates += [p for p in sorted(dot.rglob("*")) if p.is_file()]
    payload: List[Path] = []
    for path in candidates:
        if path.name in _META_NAMES or path.name.endswith(_META_SUFFIXES):
            continue
        payload.append(path)
    return payload


def _file_records(meta_path: Path, root: Path) -> List[Dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in _payload_files(meta_path)
    ]


def _default_format(files: List[Dict[str, Any]]) -> str:
    for entry in files:
        suffix = Path(str(entry.get("path", ""))).suffix.lower()
        if suffix in _FORMAT_NAMES:
            return _FORMAT_NAMES[suffix]
    if files:
        return Path(str(files[0]["path"])).suffix.lstrip(".").upper() or "unknown"
    return "unknown"


def normalise_record(
    meta_path: Path, data: Dict[str, Any], root: Path
) -> Tuple[Dict[str, Any], bool]:
    """Return the governed record and whether it changed."""
    original = json.dumps(data, sort_keys=True, ensure_ascii=False)
    family = _family_of(meta_path, root)
    if family:
        data["family"] = family
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("created_at", date.today().isoformat())
    data.setdefault("license", "CC0 (generated by the platform)")
    source = data.get("source")
    if not isinstance(source, dict):
        source = {}
    source.setdefault("kind", "synthetic")
    source.setdefault("generator", "chem-ml-platform sample generator")
    source.setdefault("reference", "")
    data["source"] = source
    data["files"] = _file_records(meta_path, root)
    data.setdefault("format", _default_format(data["files"]))
    changed = json.dumps(data, sort_keys=True, ensure_ascii=False) != original
    return data, changed


def build(root: Path) -> List[Path]:
    """Normalise every record on disk; return the ones that changed."""
    written: List[Path] = []
    for meta_path in metadata_files(root):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        data, changed = normalise_record(meta_path, data, root)
        if changed:
            meta_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            written.append(meta_path)
    return written


def check(root: Path) -> Tuple[bool, List[Dict[str, str]]]:
    """Validate every record; return ``(ok, problems)``.

    Each problem is ``{"path": ..., "issue": ...}`` so the REST layer can show
    the user exactly which dataset is affected.
    """
    problems: List[Dict[str, str]] = []
    seen_hashes: Dict[str, str] = {}

    def flag(rel: str, issue: str) -> None:
        problems.append({"path": rel, "issue": issue})

    for meta_path in metadata_files(root):
        rel = meta_path.relative_to(root).as_posix()
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            flag(rel, f"invalid JSON ({exc})")
            continue

        for key in REQUIRED_KEYS:
            if key not in data:
                flag(rel, f"missing required key {key!r}")

        family = _family_of(meta_path, root)
        if family and data.get("family") != family:
            flag(rel, f"family {data.get('family')!r} does not match directory {family!r}")

        data_type = data.get("data_type")
        allowed = FAMILY_DATA_TYPES.get(family)
        if allowed and data_type not in allowed:
            flag(rel, f"data_type {data_type!r} not allowed for family {family!r} "
                      f"(allowed: {sorted(allowed)})")

        if isinstance(data_type, str) and data_type.endswith("Spectrum"):
            if not data.get("x_unit") or not data.get("y_unit"):
                flag(rel, "spectrum missing x_unit/y_unit")

        points, x_range = data.get("points"), data.get("x_range")
        if isinstance(points, int) and points <= 0:
            flag(rel, "points must be positive")
        if isinstance(x_range, list) and len(x_range) == 2 and x_range[0] >= x_range[1]:
            flag(rel, f"x_range not increasing ({x_range})")

        for entry in data.get("files", []) or []:
            target = root / str(entry.get("path", ""))
            if not target.is_file():
                flag(rel, f"listed file {entry.get('path')!r} is missing")
                continue
            actual = sha256_file(target)
            if entry.get("sha256") != actual:
                flag(rel, f"checksum mismatch for {entry.get('path')}")
            # The size must describe the same bytes as the checksum above.
            # Reading it from the disk instead would compare a CRLF working
            # tree against an LF recording and report a size mismatch for
            # data that was never modified.
            blob = _repository_bytes(target)
            size = len(blob) if blob is not None else target.stat().st_size
            if entry.get("bytes") != size:
                flag(rel, f"size mismatch for {entry.get('path')}")
            if actual in seen_hashes:
                flag(rel, f"duplicate content with {seen_hashes[actual]} ({entry.get('path')})")
            else:
                seen_hashes[actual] = f"{rel}:{entry.get('path')}"

        source = data.get("source")
        if not isinstance(source, dict) or not source.get("kind"):
            flag(rel, "source.kind is required")

    return (not problems), problems


def quality_report(root: Optional[Path] = None) -> Dict[str, Any]:
    """Structured quality report used by the REST layer and the CLI."""
    if root is None:
        root = Path(__file__).resolve().parents[1] / "datasets"
    files = metadata_files(root)
    ok, problems = check(root)
    return {
        "root": str(root),
        "datasets": len(files),
        "ok": ok,
        "problem_count": len(problems),
        "problems": problems,
        "checked": [p.relative_to(root).as_posix() for p in files],
    }
