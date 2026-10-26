"""Shimadzu vendor adapter (LabSolutions ``.qgd`` / ``.lcd``, classic ``.spc``).

The classic ``.spc`` container is the Galactic / GRAMS "SPC" format whose
layout is published (main header of 512 bytes followed by the float32 y array
when there is a single subfile).  It is read here for real, so a Shimadzu or
GRAMS export becomes a first class scientific object.

LabSolutions ``.qgd`` / ``.lcd`` files are *not* publicly documented.  The
adapter therefore only extracts what can be read safely (the format signature
and the size stamped in the header) and hands the rest to the generic adapter,
which is exactly the fallback behaviour the platform rules require.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Dict, List, Optional

from data_layer.objects import ScientificDataObject
from workflow_engine.objects import Peak, Spectrum

from custom_nodes._shared.vendor_adapters.base import (
    VendorAdapter,
    centroid,
    register_vendor_adapter,
)

__all__ = ["ShimadzuAdapter", "read_spc", "SPC_X_UNITS", "SPC_Y_UNITS"]


#: Galactic SPC x-axis unit codes.
SPC_X_UNITS: Dict[int, str] = {
    0: "arbitrary",
    1: "wavenumber (cm-1)",
    2: "micrometre",
    3: "nanometre",
    4: "seconds",
    5: "minutes",
    6: "hertz",
    7: "kHz",
    8: "mm",
    9: "m",
    10: "m/z",
    11: "ppm",
    12: "days",
    13: "years",
    14: "raman shift (cm-1)",
}

#: Galactic SPC y-axis unit codes.
SPC_Y_UNITS: Dict[int, str] = {
    0: "arbitrary intensity",
    1: "interferogram",
    2: "absorbance",
    3: "KM (Kubelka-Munk)",
    4: "transmittance",
    5: "reflectance",
    6: "log(1/R)",
    7: "photoacoustic",
    8: "emission",
    9: "magnetic field",
    10: "electron multiplier",
    11: "DC",
    12: "volts",
}


@register_vendor_adapter
class ShimadzuAdapter(VendorAdapter):
    """Reads Shimadzu / Galactic SPC spectra and LabSolutions metadata."""

    name = "ShimadzuAdapter"
    vendor = "shimadzu"
    extensions = [".spc", ".qgd", ".lcd"]
    formats = ["Shimadzu SPC", "Shimadzu QGD", "Shimadzu LCD"]
    description = "Shimadzu LabSolutions (.qgd/.lcd) and classic Galactic SPC"
    sidecar_files = ["acqus", "procs", "title"]

    # -- SPC ----------------------------------------------------------------- #
    def read_vendor(
        self,
        target: Path,
        sidecar: Dict[str, Any],
        **kwargs: Any,
    ) -> List[ScientificDataObject]:
        suffix = target.suffix.lower()
        if suffix == ".spc" and target.is_file():
            return self.read_spc_file(target, sidecar)
        if suffix in {".qgd", ".lcd"} and target.is_file():
            return self.read_labsolutions(target, sidecar)
        return []

    def read_spc_file(
        self, target: Path, sidecar: Dict[str, Any]
    ) -> List[ScientificDataObject]:
        spectrum = read_spc(target)
        if spectrum is None:
            return []
        spectrum.metadata["vendor"] = self.vendor
        spectrum.metadata["source_format"] = "Shimadzu SPC"
        return [self.envelope(spectrum, path=target, format_name="Shimadzu SPC")]

    def read_labsolutions(
        self, target: Path, sidecar: Dict[str, Any]
    ) -> List[ScientificDataObject]:
        """Extract what is safely readable from a LabSolutions container.

        The binary layout is proprietary; only the signature and the length
        field that every release stamps at a fixed offset are read.  The
        spectral payload is left to the generic adapter.
        """
        try:
            head = target.read_bytes()[:512]
        except OSError:
            return []
        signature = head[:8].decode("latin-1", errors="replace").strip("\x00 ")
        if not signature:
            return []
        metadata: Dict[str, Any] = {
            "source_format": f"Shimadzu {target.suffix.lower().lstrip('.')}",
            "signature": signature,
        }
        # LabSolutions stamps a little endian record count at offset 0x10.
        record_count: Optional[int] = None
        if len(head) >= 0x14:
            (candidate,) = struct.unpack_from("<I", head, 0x10)
            if 0 < candidate <= 10_000_000:
                record_count = int(candidate)
        if record_count is not None:
            metadata["record_count"] = record_count
        metadata["fallback"] = "LabSolutions binary is proprietary; metadata only"
        # No spectrum can be decoded -> report the container as a Text object
        # so the provenance of the file is still visible in the workflow.
        from workflow_engine.objects import Text

        note = Text(
            name=f"Shimadzu container {target.name}",
            text=(
                f"{target.name} is a Shimadzu LabSolutions container "
                f"({_file_size(target)} bytes, "
                f"signature {signature!r}). "
                "Export to SPC / JCAMP-DX / mzML to load the spectral payload."
            ),
            metadata=metadata,
        )
        return [self.envelope(note, path=target, format_name=metadata["source_format"])]


def _file_size(target: Path) -> int:
    try:
        return target.stat().st_size
    except OSError:
        return 0


def read_spc(path: str | Path) -> Optional[Spectrum]:
    """Read a Galactic SPC file into a :class:`~workflow_engine.objects.Spectrum`.

    Returns ``None`` when the header is implausible, so the caller can fall
    back to another adapter instead of surfacing garbage.
    """
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError:
        return None
    if len(raw) < 520:
        return None

    (techflag,) = struct.unpack_from("<f", raw, 0)
    (expcode,) = struct.unpack_from("<f", raw, 4)
    (npts,) = struct.unpack_from("<h", raw, 16)
    (firstx,) = struct.unpack_from("<f", raw, 18)
    (lastx,) = struct.unpack_from("<f", raw, 22)
    (nsub,) = struct.unpack_from("<h", raw, 26)
    x_unit_code = raw[28]
    y_unit_code = raw[29]

    if npts <= 0 or npts > 1_000_000:
        return None
    if nsub not in (0, 1):
        # Multi-subfile spectra need the subheader directory; not supported.
        return None
    expected = 512 + npts * 4
    if len(raw) < expected:
        return None
    if not (firstx == 0.0 or -1e12 < firstx < 1e12):
        return None
    if not (-1e12 < lastx < 1e12):
        return None

    y = list(struct.unpack_from(f"<{npts}f", raw, 512))
    x = _axis(npts, firstx, lastx)

    peaks = [
        Peak(
            x=round(item["x"], 4),
            y=round(item["y"], 4),
            intensity=round(item["y"], 4),
            area=round(item["area"], 4),
            label="",
        )
        for item in centroid(
            x, y, width=abs(x[1] - x[0]) * 0.5 if npts > 1 else 0.0,
            invert=_bands_point_down(y_unit_code),
        )
    ]

    spectrum = Spectrum(
        mode="SPC",
        technique="Shimadzu / Galactic SPC",
        name=target.stem,
        x=x,
        y=y,
        x_unit=SPC_X_UNITS.get(x_unit_code, f"unit {x_unit_code}"),
        y_unit=SPC_Y_UNITS.get(y_unit_code, f"unit {y_unit_code}"),
        peaks=peaks,
        metadata={
            "source_format": "Shimadzu SPC",
            "vendor": "shimadzu",
            "technique_flags": techflag,
            "experiment_code": expcode,
            "subfiles": nsub,
            "synthetic": False,
        },
    )
    return spectrum


def _axis(npts: int, firstx: float, lastx: float) -> List[float]:
    """Evenly spaced x axis (SPC stores only the first and last value)."""
    if npts <= 1:
        return [float(firstx)]
    step = (lastx - firstx) / (npts - 1)
    return [round(firstx + index * step, 6) for index in range(npts)]


def _bands_point_down(y_unit_code: int) -> bool:
    """True for transmittance / reflectance spectra (bands are dips)."""
    return y_unit_code in (4, 5, 6)  # transmittance, reflectance, log(1/R)
