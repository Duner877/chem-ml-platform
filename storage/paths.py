"""Path safety primitives (v0.7 -- spec section 8.2).

The rules implemented here are deliberately stricter than "string prefix
comparison":

* both the root and the candidate path are resolved through
  ``os.path.realpath`` so symlinks cannot smuggle access outside a root;
* containment is checked with :meth:`pathlib.PurePath.relative_to` on the
  *resolved* paths, not with ``str.startswith``;
* uploaded filenames are sanitised to a safe basename;
* Windows drive-absolute and UNC inputs are treated as escapes.
"""

from __future__ import annotations

import os
import re
import string
from pathlib import Path, PureWindowsPath
from typing import Union

__all__ = ["SafePathError", "is_within", "safe_join", "sanitize_filename"]

_UNSAFE_NAME = re.compile(r"[^\w.\- ]+", re.UNICODE)
_DRIVE_LETTERS = set(string.ascii_letters)


class SafePathError(ValueError):
    """Raised when a candidate path escapes its whitelisted root."""


def _real(path: Union[str, os.PathLike]) -> Path:
    """Resolve ``path`` as far as the filesystem allows.

    ``Path.resolve()`` on Python >= 3.6 resolves symlinks that exist and
    normalises the remaining segments, which is exactly what we need for
    paths that do not exist yet.
    """
    return Path(path).expanduser().resolve()


def is_within(root: Union[str, os.PathLike], candidate: Union[str, os.PathLike]) -> bool:
    """Return True when resolved ``candidate`` is inside resolved ``root``.

    Both arguments are resolved first, so a symlink pointing outside of the
    root is correctly rejected even though the raw textual path looks safe.
    """
    root_r = _real(root)
    cand_r = _real(candidate)
    try:
        cand_r.relative_to(root_r)
    except ValueError:
        return False
    return True


def safe_join(root: Union[str, os.PathLike], *parts: Union[str, os.PathLike]) -> Path:
    """Join ``parts`` onto ``root`` and guarantee the result stays inside.

    Raises :class:`SafePathError` when:

    * any part is absolute (POSIX ``/etc``, Windows ``C:\\x`` or ``\\\\share``),
    * any part contains a ``..`` segment that would escape,
    * the resolved result falls outside of the resolved root,
    * a symlink in the existing portion of the path leads outside.
    """
    root_r = _real(root)
    if not parts:
        return root_r

    cleaned: list[str] = []
    for part in parts:
        text = str(part)
        if not text:
            continue
        # Reject absolute forms outright -- Windows drive, UNC and POSIX root.
        if PureWindowsPath(text).is_absolute() or text.startswith("/") or text.startswith("\\"):
            raise SafePathError(f"absolute paths are not allowed: {text!r}")
        segments = [seg for seg in re.split(r"[\\/]+", text) if seg not in ("", ".")]
        if any(seg == ".." for seg in segments):
            raise SafePathError(f"path traversal ('..') is not allowed: {text!r}")
        # Windows device namespace (\\.\, \\?\) and reserved names.
        if text.startswith("\\\\.\\") or text.startswith("\\\\?\\"):
            raise SafePathError(f"device namespace paths are not allowed: {text!r}")
        cleaned.extend(segments)

    candidate = root_r.joinpath(*cleaned) if cleaned else root_r
    result = _real(candidate)
    if not is_within(root_r, result):
        raise SafePathError(
            f"resolved path escapes the whitelisted root: {result}"
        )
    return result


def sanitize_filename(filename: str, max_length: int = 180) -> str:
    """Reduce an uploaded filename to a safe basename.

    * strips directory components (``../evil``, ``C:\\temp\\evil``),
    * replaces control characters and filesystem-hostile punctuation,
    * keeps a reasonable length while preserving the extension,
    * never returns an empty string or a Windows-reserved device name.
    """
    if not filename:
        raise SafePathError("empty filename")
    # Flatten any directory component the client tried to send.
    base = PureWindowsPath(str(filename)).name
    base = os.path.basename(base.replace("\\", "/"))
    base = base.replace("\x00", "")
    cleaned = _UNSAFE_NAME.sub("_", base).strip(". ")
    if not cleaned:
        raise SafePathError(f"filename reduced to nothing: {filename!r}")
    # Windows reserved device names.
    stem = cleaned.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or stem in {
        f"COM{i}" for i in range(1, 10)
    } | {f"LPT{i}" for i in range(1, 10)}:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        suffix = Path(cleaned).suffix
        stem_part = cleaned[: max_length - len(suffix) - 8]
        cleaned = f"{stem_part}_{abs(hash(filename)) % 10**8}{suffix}"
    return cleaned
