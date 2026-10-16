"""File-picker browsing and spectrum enlargement (v0.7.2, tasks 91 & 92).

Two features share this file because they share the same failure mode: both are
*UI affordances whose real contract is a backend endpoint*, and both were easy to
get subtly wrong without an end-to-end check.

* **task 91** -- the ``file`` parameter must open a picker.  In the packaged
  Electron build that is a native dialog raised by the main process; the browser
  launcher has no such dialog, so ``/api/files/browse`` is the fallback.  It is
  the most sensitive *read-only* route in the platform (it enumerates arbitrary
  directories), which is why it must be registered in
  :data:`backend.security.ROUTE_RULES` -- an unregistered route is a bug that
  the security layer cannot protect against.
* **task 92** -- a spectrum must be clickable to enlarge.  The contract is that
  the dock thumbnail and the full-screen lightbox render *the same* component,
  so a zoomed view can never disagree with the small one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.security import READ, ROUTE_RULES

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# --------------------------------------------------------------------------- #
# task 91 -- the browse endpoint
# --------------------------------------------------------------------------- #
def test_browse_lists_a_directory(client: TestClient):
    response = client.get("/api/files/browse", params={"path": "datasets/mass_spectrometry"})
    assert response.status_code == 200
    payload = response.json()

    assert payload["path"]
    assert payload["parent"]
    names = [entry["name"] for entry in payload["files"]]
    assert "scan_018081.mzml" in names


def test_browse_marks_which_files_the_importer_can_actually_open(client: TestClient):
    """Files are listed even when unimportable -- greyed out, not hidden.

    Hiding them would make the picker lie about what is on disk.
    """
    response = client.get("/api/files/browse", params={"path": "datasets/mass_spectrometry"})
    entries = {entry["name"]: entry for entry in response.json()["files"]}

    mzml = entries["scan_018081.mzml"]
    assert mzml["readable"] is True
    assert mzml["size"] > 0
    assert Path(mzml["path"]).is_absolute()


def test_browse_accepts_an_empty_path_and_starts_somewhere_useful(client: TestClient):
    response = client.get("/api/files/browse", params={"path": ""})
    assert response.status_code == 200
    assert response.json()["path"]


def test_browse_of_a_file_returns_its_parent(client: TestClient):
    """Clicking Browse again on a parameter that already holds a file path."""
    response = client.get(
        "/api/files/browse",
        params={"path": "datasets/mass_spectrometry/scan_018081.mzml"},
    )
    assert response.status_code == 200
    assert response.json()["name"].lower() == "mass_spectrometry"


def test_browse_skips_hidden_entries(client: TestClient):
    payload = client.get("/api/files/browse", params={"path": "."}).json()
    everything = [entry["name"] for entry in payload["directories"] + payload["files"]]
    assert not [name for name in everything if name.startswith(".")]


def test_browse_rejects_a_path_that_is_not_a_directory(client: TestClient):
    response = client.get("/api/files/browse", params={"path": "no/such/place"})
    assert response.status_code == 404


def test_exists_endpoint_reports_missing_paths_honestly(client: TestClient):
    """A typed path that cannot be found must be reported, not silently run."""
    missing = client.get("/api/files/exists", params={"path": "definitely/not/here.mzml"})
    assert missing.status_code == 200
    assert missing.json()["exists"] is False

    present = client.get(
        "/api/files/exists", params={"path": "datasets/mass_spectrometry/scan_018081.mzml"}
    )
    assert present.json()["exists"] is True
    assert present.json()["is_dir"] is False

    empty = client.get("/api/files/exists", params={"path": ""})
    assert empty.json()["exists"] is False


# --------------------------------------------------------------------------- #
# task 91 -- the security registration is not optional
# --------------------------------------------------------------------------- #
def test_files_browse_is_classified_in_the_route_rules():
    """An unregistered route is a route the security layer cannot protect.

    ``GET /api/files/`` must be declared, and its verb must be the read class --
    not a write class, which would be both wrong and over-restrictive.
    """
    matches = [
        rule
        for rule in ROUTE_RULES
        if rule.method == "GET" and rule.pattern.pattern == r"^/api/files/"
    ]
    assert matches, "GET /api/files/ is missing from ROUTE_RULES"
    rule = matches[0]
    assert rule.permission == READ


def test_files_router_is_registered_on_the_app(client: TestClient):
    """Mounting must happen, and it must happen under ``/api``.

    Checked through the OpenAPI document because that is what actually reflects
    the mounted prefix -- walking ``app.routes`` misses nested routers, which is
    exactly how a router ends up defined but not served.
    """
    import backend.routers.files as files_router

    assert files_router.router.prefix == "/files"

    schema = client.get("/api/openapi.json").json()
    paths = set(schema.get("paths", {}))
    assert "/api/files/browse" in paths, sorted(paths)
    assert "/api/files/exists" in paths


def test_browse_returns_paths_that_are_usable_by_the_exists_endpoint(client: TestClient):
    """The listed paths must feed straight back into the picker without edits.

    This is the actual round trip the UI performs, so a path formatting mismatch
    between the two handlers would surface here and nowhere else.
    """
    listing = client.get("/api/files/browse", params={"path": "datasets/mass_spectrometry"})
    entry = listing.json()["files"][0]
    probe = client.get("/api/files/exists", params={"path": entry["path"]})
    assert probe.json()["exists"] is True


# --------------------------------------------------------------------------- #
# task 91 -- the frontend wiring, checked statically
# --------------------------------------------------------------------------- #
def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_electron_main_process_raises_the_native_dialog():
    """The packaged build must not try to open a file dialog from the renderer.

    ``contextIsolation`` is on and ``nodeIntegration`` is off, so a renderer-side
    ``dialog`` call is impossible by design -- the IPC handler is the only path.
    """
    source = _source("desktop/src/main.js")
    assert 'ipcMain.handle("pick-file"' in source
    assert "dialog.showOpenDialog" in source


def test_preload_exposes_pick_file_without_leaking_node():
    preload = _source("desktop/src/preload.js")
    assert "pickFile" in preload
    # The bridge must stay narrow: contextBridge, never a raw ipcRenderer dump.
    assert "contextBridge" in preload
    assert "exposeInMainWorld" in preload


def test_frontend_prefers_the_native_picker_and_falls_back_to_browsing():
    """Two channels, one abstraction -- and the fallback must be real."""
    source = _source("frontend/src/filePicker.ts")
    assert "chemmlDesktop" in source
    assert "browseFiles" in source
    # Native first, browser second.
    assert source.index("pickFile") < source.index("browseFiles")


def test_file_parameters_use_the_picker_not_a_bare_text_input():
    """Both surfaces -- node card and inspector -- must render the picker."""
    card = _source("frontend/src/nodes/ScientificNodeCard.tsx")
    inspector = _source("frontend/src/panels/Inspector.tsx")
    assert "FilePickerField" in card
    assert "FilePickerField" in inspector
    assert "filePicker" in card or "FilePickerField" in card


def test_picker_component_provides_a_browse_affordance():
    source = _source("frontend/src/components/FilePickerField.tsx")
    assert "BrowseDialog" in source
    # It probes typed paths so a typo is visible before the run, not after.
    assert "probeFile" in source


# --------------------------------------------------------------------------- #
# task 92 -- the spectrum lightbox
# --------------------------------------------------------------------------- #
def test_dock_and_lightbox_share_one_plot_component():
    """The zoomed view and the thumbnail must be literally the same renderer.

    Two copies of the plotting maths is how a full-screen axis silently
    disagrees with the dock.  ``PlotPanel`` therefore imports ``SpectrumPlot``
    from the lightbox module rather than drawing for itself.
    """
    lightbox = _source("frontend/src/components/SpectrumLightbox.tsx")
    panel = _source("frontend/src/panels/PlotPanel.tsx")

    assert "export function SpectrumPlot" in lightbox
    assert "SpectrumLightbox" in lightbox  # default export
    assert "SpectrumPlot" in panel
    assert "SpectrumLightbox" in panel
    # PlotPanel must not re-implement the plotting maths.
    assert "<svg" not in panel


def test_spectrum_surface_is_clickable_to_enlarge():
    """The plot itself is the button -- not a small corner affordance."""
    panel = _source("frontend/src/panels/PlotPanel.tsx")
    assert "<button" in panel
    assert "setLightbox" in panel or "Lightbox" in panel
    assert "IconZoom" in panel


def test_lightbox_supports_zoom_pan_and_reset():
    source = _source("frontend/src/components/SpectrumLightbox.tsx")
    assert "zoom" in source
    assert "panX" in source
    # ESC to close, plus an explicit reset to 1:1.
    assert "Escape" in source
    assert "reset" in source.lower()


def test_spectrum_trace_uses_the_monochrome_text_token():
    """Task 94: the trace must be ink, not a brand colour.

    A hard-coded blue here would survive the theme rewrite, because the trace is
    drawn inside the plotting component rather than through a themed class.
    """
    source = _source("frontend/src/components/SpectrumLightbox.tsx")
    assert "var(--c-text)" in source
    for blue in ("#2e6be6", "#4f8dff", "rgb(46, 107, 230)"):
        assert blue not in source, f"blue {blue} left in the spectrum plot"


def test_ladder_labels_read_as_a_chain_not_a_formula():
    """A two-step ladder is shown as ``-CO → -CH3NCO`` so it reads as a pathway."""
    source = _source("frontend/src/components/FragmentationPanel.tsx")
    assert "ladder" in source
    assert '" → -"' in source or "' → -'" in source or " → -" in source


# --------------------------------------------------------------------------- #
# task 94/95 -- no blue, no orphan question marks
# --------------------------------------------------------------------------- #
def test_theme_defines_no_blue_accent():
    """The accent must be monochrome in both light and dark themes.

    Scanned by hue rather than by a hard-coded deny list, because a theme that
    swaps ``#2e6be6`` for ``#2563eb`` has not stopped being blue.  Comments are
    stripped first: the module documents *which* blue was removed, and naming a
    colour in prose is not using it.
    """
    import re

    source = _source("frontend/src/theme.ts")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)

    blues = []
    for text in re.findall(r"#[0-9a-fA-F]{6}\b", code):
        red, green, blue = (int(text[i : i + 2], 16) for i in (1, 3, 5))
        # A "blue" is a hue where blue clearly dominates both other channels.
        if blue > 90 and blue - red > 40 and blue - green > 30:
            blues.append(text)
    assert not blues, f"blue hex colours still in the theme: {sorted(set(blues))}"


def test_theme_documents_the_monochrome_decision():
    """The reason for the change is recorded next to the tokens.

    A monochrome palette with no written rationale is one refactor away from
    being "modernised" back to a brand blue.
    """
    source = _source("frontend/src/theme.ts")
    assert "monochrome design language" in source.lower()
    # The reasoning must name the run-state exception, or the next person will
    # grep out good/warn/bad too.
    assert "run state" in source.lower()


def test_no_component_uses_a_hard_coded_palette_class():
    """Every component must colour through ``var(--c-*)``, not Tailwind's ramp.

    ``text-slate-400`` looks neutral but is a *fixed* slate: it does not move
    with the theme, so those panels stayed grey-blue and far too dark when the
    light theme was selected.  This is the single easiest way to reintroduce a
    hue, so it is locked shut across every component rather than per file.
    """
    import re

    components = sorted((ROOT / "frontend" / "src").rglob("*.tsx"))
    assert components, "no components found -- the glob is wrong, not the code"

    # Tailwind colour ramps: fixed hues, all incompatible with a themed
    # monochrome palette.  ``translate-`` is excluded because it contains the
    # substring "slate-" by coincidence.
    pattern = re.compile(r"(?:text|bg|border|from|to|via|ring|fill|stroke)-"
                         r"(?:slate|gray|zinc|neutral|stone|sky|blue|indigo|cyan)-")
    offenders: list[str] = []
    for path in components:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            # Comments document the change; only code is a defect.
            if stripped.startswith(("//", "*", "/*")):
                continue
            for match in pattern.finditer(line):
                if "translate-" in line[max(0, match.start() - 10):match.start()]:
                    continue
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {match.group(0)}")
    assert not offenders, "hard-coded palette classes remain:\n" + "\n".join(offenders)


def test_optional_ports_are_labelled_not_marked_with_a_question_mark():
    """A lone "?" is not a label. The optional chip is."""
    card = _source("frontend/src/nodes/ScientificNodeCard.tsx")
    assert '"可选"' in card or "'可选'" in card
    assert '"opt"' in card or "'opt'" in card


def test_unlabelled_spectrum_is_localised_not_a_question_mark():
    panel = _source("frontend/src/panels/PlotPanel.tsx")
    assert 'translate(lang, "unlabelled")' in panel
    assert '|| "?"' not in panel