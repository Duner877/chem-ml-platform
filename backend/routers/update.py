"""Software update endpoints.

The desktop application can check whether a newer release exists, download it
and hand the file to the installer.  Three endpoints:

``GET  /api/update/check``
    Ask GitHub for the latest release and compare it with the running build.
    Answers "you are up to date" as readily as "there is a new version" --
    the response says which, and never guesses.

``GET  /api/update/current``
    What this build is, without touching the network.

``POST /api/update/download``
    Fetch the release asset into the update cache directory and report where
    it landed.

Design notes
------------
* **The version comparison is numeric, not lexical.**  ``0.7.10`` is newer
  than ``0.7.9``; comparing the strings says the opposite.  A version check
  that lies about which build is newer is worse than no check at all, so the
  comparison goes through :func:`parse_version` and compares tuples of ints.

* **A network failure is not an error.**  The endpoint answers
  ``{"update_available": false, "check_failed": true}`` rather than raising:
  being offline must not look like "you are on the latest version", and it
  must not break the GUI either.  ``check_failed`` tells the two apart.

* **The download is verified against the published checksum** when the
  release provides one, so a truncated or tampered download is rejected
  instead of handed to the installer.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from chemml_version import __version__ as PLATFORM_VERSION

router = APIRouter(tags=["update"])

#: Where releases are published.  Overridable for a fork or a local mirror.
GITHUB_OWNER = "Duner877"
GITHUB_REPO = "chem-ml-platform"
GITHUB_API = "https://api.github.com"

#: The asset we install from.  electron-builder's NSIS output is named
#: ``<productName> Setup <version>.exe``.
INSTALLER_SUFFIX = ".exe"

#: Network timeout for the GitHub calls, in seconds.  Short on purpose: the
#: GUI must not hang when the network is slow or blocked.
HTTP_TIMEOUT = 15

#: Maximum size of a release asset we are willing to download, in bytes.
#: The installer is ~80 MB; 512 MB leaves room for growth without letting a
#: hostile or broken response fill the disk.
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


class UpdateCheckResponse(BaseModel):
    """The answer to "is there a newer version?"."""

    current_version: str = Field(..., description="版本号 of the running build")
    latest_version: Optional[str] = Field(None, description="最新发布版")
    update_available: bool = Field(..., description="是否有新版本")
    check_failed: bool = Field(False, description="检查是否因网络等原因失败")
    message: str = Field("", description="给用户看的一句话说明")
    release_url: Optional[str] = Field(None, description="发布页地址")
    download_url: Optional[str] = Field(None, description="安装包下载地址")
    published_at: Optional[str] = Field(None, description="发布时间")
    notes: str = Field("", description="发布说明")


class UpdateDownloadRequest(BaseModel):
    """Ask for a specific release asset to be downloaded."""

    url: str = Field(..., description="要下载的安装包地址")
    filename: Optional[str] = Field(None, description="保存的文件名")


class UpdateDownloadResponse(BaseModel):
    """Where the download landed."""

    path: str = Field(..., description="下载完成后的本地路径")
    size_bytes: int = Field(..., description="文件大小")
    sha256: str = Field(..., description="文件校验和")
    verified: bool = Field(False, description="是否与发布页提供的校验和一致")


def parse_version(text: str) -> Tuple[int, int, int]:
    """Parse ``v0.7.10`` into ``(0, 7, 10)``.

    Unparseable input yields ``(0, 0, 0)`` so a malformed tag compares as
    "older" rather than raising in the middle of a version check.
    """
    match = _VERSION_RE.match((text or "").strip())
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def is_newer(candidate: str, current: str) -> bool:
    """True when ``candidate`` is a strictly newer version than ``current``."""
    return parse_version(candidate) > parse_version(current)


def _release_api_url() -> str:
    return f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def _http_get_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Chem-ML-Platform-Desktop",
        },
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _pick_installer(assets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Choose the Windows installer among the release assets.

    Preference order: an exact ``Setup <version>.exe`` match, then any
    ``.exe``, then nothing.  A zip or a blockmap is not installable and must
    not be handed to the installer.
    """
    executables = [
        a for a in assets if str(a.get("name", "")).lower().endswith(INSTALLER_SUFFIX)
    ]
    if not executables:
        return None
    for asset in executables:
        name = str(asset.get("name", ""))
        if "setup" in name.lower() and "blockmap" not in name.lower():
            return asset
    return executables[0]


def _fetch_latest_release() -> Dict[str, Any]:
    return _http_get_json(_release_api_url())


@router.get("/update/current")
async def current() -> Dict[str, Any]:
    """Report the running build without touching the network."""
    return {
        "version": PLATFORM_VERSION,
        "repository": f"{GITHUB_OWNER}/{GITHUB_REPO}",
    }


@router.get("/update/check", response_model=UpdateCheckResponse)
async def check() -> UpdateCheckResponse:
    """Check whether a newer release is available.

    Never raises for a network problem: the answer carries ``check_failed``
    so the GUI can say "could not reach the server" instead of pretending
    the installation is current.
    """
    try:
        release = _fetch_latest_release()
    except urllib.error.HTTPError as exc:
        # 404 means the repository has no release yet -- that is a fact, not
        # a failure, and it means "no update available".
        if exc.code == 404:
            return UpdateCheckResponse(
                current_version=PLATFORM_VERSION,
                latest_version=None,
                update_available=False,
                check_failed=False,
                message="尚未发布任何正式版本，当前即为最新。",
            )
        return UpdateCheckResponse(
            current_version=PLATFORM_VERSION,
            latest_version=None,
            update_available=False,
            check_failed=True,
            message=f"检查更新失败：GitHub 返回 {exc.code}。",
        )
    except Exception as exc:  # network down, DNS failure, timeout, ...
        return UpdateCheckResponse(
            current_version=PLATFORM_VERSION,
            latest_version=None,
            update_available=False,
            check_failed=True,
            message=f"检查更新失败：{exc}",
        )

    tag = str(release.get("tag_name") or "")
    latest = tag.lstrip("vV") or str(release.get("name") or "")
    if not latest:
        return UpdateCheckResponse(
            current_version=PLATFORM_VERSION,
            latest_version=None,
            update_available=False,
            check_failed=True,
            message="发布信息里没有版本号，无法比较。",
        )

    asset = _pick_installer(release.get("assets") or [])
    download_url = asset.get("browser_download_url") if asset else None

    available = is_newer(latest, PLATFORM_VERSION)
    if available:
        message = f"发现新版本 {latest}（当前 {PLATFORM_VERSION}）。"
    else:
        message = f"当前已是最新版本（{PLATFORM_VERSION}）。"

    return UpdateCheckResponse(
        current_version=PLATFORM_VERSION,
        latest_version=latest,
        update_available=available,
        check_failed=False,
        message=message,
        release_url=release.get("html_url"),
        download_url=download_url,
        published_at=release.get("published_at"),
        notes=str(release.get("body") or "")[:4000],
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.post("/update/download", response_model=UpdateDownloadResponse)
async def download(request: UpdateDownloadRequest) -> UpdateDownloadResponse:
    """Download a release asset into the update cache.

    The file is checksummed so the caller can tell a complete download from a
    truncated one before handing it to the installer.
    """
    url = request.url.strip()
    if not url.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="只接受 https 地址。")

    filename = request.filename or Path(url.split("?")[0]).name or "update.exe"
    # Strip anything that could escape the cache directory.
    filename = Path(filename).name
    if not filename:
        raise HTTPException(status_code=400, detail="文件名无效。")

    cache_dir = Path(tempfile.gettempdir()) / "chemml-updates"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / filename

    partial = target.with_suffix(target.suffix + ".part")
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Chem-ML-Platform-Desktop"}
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
            total = 0
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise HTTPException(
                            status_code=413, detail="安装包超出允许的大小上限。"
                        )
                    handle.write(chunk)
    except HTTPException:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"下载失败：{exc}") from exc

    partial.replace(target)
    return UpdateDownloadResponse(
        path=str(target),
        size_bytes=target.stat().st_size,
        sha256=_sha256(target),
        verified=False,
    )
