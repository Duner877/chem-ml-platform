"""Regression tests for the 0.7.4 software-update endpoints.

A version check that lies is worse than no version check at all, because the
user acts on it: they skip a release that fixes a data bug, or they install a
build they did not need.  Four properties are locked here.

1. **The comparison is numeric, not lexical.**  ``0.7.10`` is newer than
   ``0.7.9``; comparing the strings says the opposite.  This is asserted with
   exactly that pair, because it is the pair a string comparison gets wrong
   and a hand-written version check almost never happens to test.

2. **"Cannot check" is not "up to date".**  A network failure answers with
   ``check_failed=True`` and ``update_available=False``.  Asserting only the
   latter would pass for both a real "you are current" and a total outage.

3. **The offline path never raises.**  The GUI polls this endpoint at start-up;
   an exception there would surface as a broken top bar rather than as
   "could not reach the server".

4. **The GUI has a visible entry point.**  The top-bar badge and the dock tab
   are the difference between "there is a feature" and "there is a feature you
   can find".  A static check keeps them from being dropped silently.
"""

from __future__ import annotations

import asyncio
import urllib.error
from pathlib import Path

import pytest

from backend.routers import update as update_router

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend" / "src"


# --------------------------------------------------------------------------- #
# 1. Version comparison
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        ("0.7.4", "0.7.3", True),
        ("0.7.3", "0.7.3", False),
        ("0.7.2", "0.7.3", False),
        # The pair a string comparison gets wrong.
        ("0.7.10", "0.7.9", True),
        ("0.8.0", "0.7.99", True),
        ("1.0.0", "0.7.3", True),
        # The ``v`` prefix GitHub tags carry.
        ("v0.7.4", "0.7.3", True),
        ("v0.7.3", "0.7.3", False),
        # Unparseable input is treated as older, never as "newer".
        ("", "0.7.3", False),
        ("not-a-version", "0.7.3", False),
        # A malformed *current* version makes everything look newer, which is
        # the safe direction: offer the download rather than hide it.
        ("0.7.4", "broken", True),
    ],
)
def test_version_comparison_is_numeric(candidate, current, expected):
    assert update_router.is_newer(candidate, current) is expected


def test_parse_version_handles_the_ten_case():
    assert update_router.parse_version("0.7.10") == (0, 7, 10)
    assert update_router.parse_version("v0.7.10") == (0, 7, 10)
    assert update_router.parse_version("garbage") == (0, 0, 0)


def test_the_check_endpoint_is_registered():
    """The route must actually be mounted -- an unmounted router is a 404.

    The route list is read from the OpenAPI document rather than from
    ``app.routes``: the application wraps its routers, and walking
    ``app.routes`` yields wrapper objects that have no ``path``.
    """
    from backend.app import create_app

    paths = set(create_app().openapi()["paths"])
    assert "/api/update/check" in paths
    assert "/api/update/current" in paths
    assert "/api/update/download" in paths


# --------------------------------------------------------------------------- #
# 2 & 3. The offline path
# --------------------------------------------------------------------------- #
class _FakeHTTPError(Exception):
    """Stand-in for ``urllib.error.HTTPError`` (which wants a real response)."""

    def __init__(self, code: int):
        super().__init__(f"HTTP {code}")
        self.code = code


def test_a_network_failure_is_reported_as_a_failure_not_as_up_to_date(monkeypatch):
    def boom():
        raise OSError("network is unreachable")

    monkeypatch.setattr(update_router, "_fetch_latest_release", boom)

    result = asyncio.run(update_router.check())
    assert result.check_failed is True
    assert result.update_available is False
    assert result.message


def test_a_404_means_no_release_yet_not_a_failure(monkeypatch):
    """A repository with no release is a *fact*, not an outage.

    Reporting it as ``check_failed`` would make the GUI say "could not check"
    on every fresh repository, which is both wrong and alarming.
    """

    def not_found():
        raise urllib.error.HTTPError(
            "https://api.github.com/x", 404, "Not Found", {}, None
        )

    monkeypatch.setattr(update_router, "_fetch_latest_release", not_found)

    result = asyncio.run(update_router.check())
    assert result.check_failed is False
    assert result.update_available is False


def test_a_newer_release_is_reported_with_its_installer(monkeypatch):
    release = {
        "tag_name": "v0.9.0",
        "name": "v0.9.0",
        "html_url": "https://github.com/Duner877/chem-ml-platform/releases/tag/v0.9.0",
        "published_at": "2026-11-01T10:00:00Z",
        "body": "notes",
        "assets": [
            {"name": "Chem ML Platform Setup 0.9.0.exe.blockmap", "browser_download_url": "https://x/blockmap"},
            {"name": "Chem ML Platform Setup 0.9.0.exe", "browser_download_url": "https://x/setup.exe"},
        ],
    }
    monkeypatch.setattr(update_router, "_fetch_latest_release", lambda: release)

    result = asyncio.run(update_router.check())
    assert result.update_available is True
    assert result.latest_version == "0.9.0"
    assert result.download_url == "https://x/setup.exe"
    assert result.release_url.endswith("v0.9.0")


def test_the_blockmap_is_never_offered_as_the_installer(monkeypatch):
    """A blockmap is metadata, not a program.

    Handing it to the installer would fail at launch with an error that says
    nothing about the cause.
    """
    release = {
        "tag_name": "v0.9.0",
        "assets": [
            {"name": "Chem ML Platform Setup 0.9.0.exe.blockmap", "browser_download_url": "https://x/bm"},
        ],
    }
    monkeypatch.setattr(update_router, "_fetch_latest_release", lambda: release)

    result = asyncio.run(update_router.check())
    assert result.update_available is True
    assert result.download_url is None


def test_the_current_endpoint_does_not_touch_the_network(monkeypatch):
    def boom():
        raise AssertionError("the current-version endpoint must not use the network")

    monkeypatch.setattr(update_router, "_fetch_latest_release", boom)

    payload = asyncio.run(update_router.current())
    assert payload["version"] == update_router.PLATFORM_VERSION


def test_the_download_endpoint_refuses_a_non_https_url():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            update_router.download(
                update_router.UpdateDownloadRequest(url="http://x/setup.exe")
            )
        )
    assert excinfo.value.status_code == 400


# --------------------------------------------------------------------------- #
# 4. The GUI entry point
# --------------------------------------------------------------------------- #
def test_the_gui_has_a_visible_update_entry_point():
    """The badge in the top bar and the tab in the dock.

    A backend nobody can reach is not a feature.  These two are the whole
    difference between "the update endpoint exists" and "the user can update".
    """
    top_bar = (FRONTEND / "components" / "TopBar.tsx").read_text(encoding="utf-8")
    badge = (FRONTEND / "components" / "UpdateBadge.tsx").read_text(encoding="utf-8")
    dock = (FRONTEND / "panels" / "Dock.tsx").read_text(encoding="utf-8")
    panel = (FRONTEND / "panels" / "UpdatePanel.tsx").read_text(encoding="utf-8")

    assert "UpdateBadge" in top_bar, "the top bar must host the update badge"
    assert ".updateCheck()" in badge, "the badge must actually check"
    assert 'id: "update"' in dock, "the dock must offer the update tab"
    assert "UpdatePanel" in dock
    assert "api.updateDownload(" in panel, "the panel must be able to download"
    assert "installUpdate" in panel, "the panel must be able to start the install"


def test_the_gui_never_treats_a_failed_check_as_up_to_date():
    """The badge must not turn green (or claim currency) after a failure.

    This is the same property the backend enforces, asserted on the GUI side
    too: the two are separate code paths and either can regress alone.
    """
    badge = (FRONTEND / "components" / "UpdateBadge.tsx").read_text(encoding="utf-8")
    panel = (FRONTEND / "panels" / "UpdatePanel.tsx").read_text(encoding="utf-8")

    for source in (badge, panel):
        assert "check_failed" in source, (
            "the update surface must inspect check_failed; without it an "
            "outage is reported as 'you are up to date'"
        )


def test_the_preload_bridge_exposes_the_install_hand_off():
    preload = (REPO / "desktop" / "src" / "preload.js").read_text(encoding="utf-8")
    main = (REPO / "desktop" / "src" / "main.js").read_text(encoding="utf-8")

    assert "install-update" in preload
    assert "installUpdate" in preload
    assert 'ipcMain.handle("install-update"' in main
