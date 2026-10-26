"""Vendor adapter base class and shared feature extraction.

A vendor adapter is the bridge between a proprietary container and the
universal data layer.  The pipeline required by the specification is::

    Instrument -> Parser -> Vendor Adapter -> Scientific Object -> Feature Extraction

``Parser``      :func:`workflow_engine.parsers.load_spectra`
``Vendor Adapter``  this package (thermo / waters / agilent / bruker / shimadzu)
``Scientific Object``  :class:`workflow_engine.objects.Spectrum`
``Feature Extraction`` :meth:`VendorAdapter.extract_features`

Design contract (see the platform rules in the README):

* an adapter **never raises** for a file it cannot fully decode -- it returns
  what it could read and records the reason in ``metadata["fallback"]``;
* the engine that produced the data is always recorded, so a spectrum obtained
  from a real vendor file is distinguishable from one produced by a simulator;
* features are computed from the *centroided* peak list, never from the raw
  profile, because that is what a spectroscopist would do by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from data_layer.adapters import DataSourceAdapter, GenericSpectrumAdapter, sniff_format
from data_layer.metadata import VENDOR_FORMATS
from data_layer.objects import ScientificDataObject
from workflow_engine.objects import Peak, Spectrum, Table
from workflow_engine.processing import find_peaks

__all__ = [
    "VendorAdapter",
    "extract_features",
    "centroid",
    "to_wavenumber",
    "VENDOR_ADAPTERS",
]


# --------------------------------------------------------------------------- #
# Signal processing helpers shared by every vendor adapter
# --------------------------------------------------------------------------- #
def centroid(
    x: List[float],
    y: List[float],
    width: float = 0.0,
    invert: bool = False,
    height: float = 0.05,
    prominence: float = 0.05,
) -> List[Dict[str, float]]:
    """Profile -> centroid conversion.

    Apexes are located with the platform peak picker
    (:func:`workflow_engine.processing.find_peaks`); each apex is then replaced
    by the intensity weighted centroid of the points around it, which is what
    a mass spectrometer's centroid mode and a spectrometer's band integration
    both do.

    ``invert`` flips the signal first, so a *transmittance* / *reflectance*
    spectrum (bands pointing down) is treated like an absorbance spectrum.
    ``height`` and ``prominence`` are fractions of the maximum intensity; 5 %
    is the default because spectral baselines ripple at a few percent and
    anything smaller reports the noise as peaks.
    """
    if not x or not y or len(x) != len(y):
        return []
    signal = [float(value) for value in y]
    if invert:
        top = max(signal)
        signal = [top - value for value in signal]
    apexes = find_peaks(
        x,
        signal,
        height=height,
        prominence=prominence,
        max_peaks=400,
    )
    if not apexes:
        return []

    peaks: List[Dict[str, float]] = []
    for apex in apexes:
        position = float(apex.x)
        index = min(range(len(x)), key=lambda i: abs(x[i] - position))
        # Collect the contiguous run of points above half height.
        half = 0.5 * float(apex.y)
        lo = index
        while lo > 0 and signal[lo - 1] >= half:
            lo -= 1
        hi = index
        while hi < len(signal) - 1 and signal[hi + 1] >= half:
            hi += 1
        area = 0.0
        if hi > lo:
            weight = sum(signal[lo + 1 : hi])
            if weight > 0:
                position = sum(x[j] * signal[j] for j in range(lo + 1, hi)) / weight
            # Trapezoidal integration of the window above half height.
            area = 0.0
            for j in range(lo, hi):
                dx = float(x[j + 1]) - float(x[j])
                area += 0.5 * (signal[j] + signal[j + 1]) * dx
        else:
            area = float(apex.y)
        peaks.append({"x": float(position), "y": float(apex.y), "area": area})

    if width > 0 and len(peaks) > 1:
        merged: List[Dict[str, float]] = []
        for peak in sorted(peaks, key=lambda item: item["x"]):
            if merged and abs(peak["x"] - merged[-1]["x"]) < width:
                previous = merged[-1]
                total = previous["area"] + peak["area"]
                if total <= 0:
                    continue
                previous["x"] = (
                    previous["x"] * previous["area"] + peak["x"] * peak["area"]
                ) / total
                previous["y"] = max(previous["y"], peak["y"])
                previous["area"] = total
            else:
                merged.append(dict(peak))
        peaks = merged
    return peaks


def to_wavenumber(wavelength_nm: float) -> float:
    """Convert a wavelength in nm to a wavenumber in cm^-1."""
    if wavelength_nm <= 0:
        return 0.0
    return 1.0e7 / wavelength_nm


def extract_features(spectrum: Spectrum) -> Dict[str, Any]:
    """Feature extraction stage: the numbers an analyst would tabulate.

    Returns a plain dictionary so the result can be attached to a data object
    or rendered as a table without further conversion.
    """
    features: Dict[str, Any] = {
        "points": int(getattr(spectrum, "size", 0) or 0),
        "x_unit": str(getattr(spectrum, "x_unit", "") or ""),
        "y_unit": str(getattr(spectrum, "y_unit", "") or ""),
        "peaks": len(getattr(spectrum, "peaks", []) or []),
    }
    if spectrum.x:
        features["x_min"] = round(float(spectrum.x[0]), 4)
        features["x_max"] = round(float(spectrum.x[-1]), 4)
    peaks = list(spectrum.peaks or [])
    if peaks:
        base = max(peaks, key=lambda peak: float(peak.y))
        features["base_peak_x"] = round(float(base.x), 4)
        features["base_peak_y"] = round(float(base.y), 4)
        total = sum(float(peak.y) for peak in peaks) or 1.0
        features["top_peaks"] = [
            {
                "x": round(float(peak.x), 4),
                "y": round(float(peak.y), 4),
                "relative": round(float(peak.y) / total * 100.0, 2),
                "assignment": str(getattr(peak, "assignment", "") or ""),
            }
            for peak in sorted(peaks, key=lambda item: -float(item.y))[:10]
        ]
        positions = [float(peak.x) for peak in peaks]
        features["spacing_mean"] = round(
            sum(
                positions[index + 1] - positions[index]
                for index in range(len(positions) - 1)
            )
            / max(1, len(positions) - 1),
            4,
        )
    return features


def features_to_table(features: Dict[str, Any], name: str = "features") -> Table:
    """Render :func:`extract_features` as a two column table."""
    rows: List[List[Any]] = []
    for key in sorted(features):
        value = features[key]
        if isinstance(value, (list, dict)):
            continue
        rows.append([key, value])
    for index, peak in enumerate(features.get("top_peaks", []), start=1):
        rows.append([f"peak_{index}", f"x={peak['x']} rel={peak['relative']}% {peak['assignment']}"])
    return Table(name=name, columns=["feature", "value"], rows=rows)


# --------------------------------------------------------------------------- #
# Base adapter
# --------------------------------------------------------------------------- #
class VendorAdapter(DataSourceAdapter):
    """Common behaviour of the instrument vendor adapters.

    Subclasses declare the containers they own and implement
    :meth:`read_vendor`.  The base :meth:`read` then:

    1. collects vendor metadata from sidecar files (``acqus``, ``procs``,
       method exports, ...) -- always available because they are text;
    2. calls :meth:`read_vendor` for the spectral payload;
    3. falls back to the generic adapter when the binary cannot be decoded,
       recording ``metadata["fallback"]`` so the provenance stays honest;
    4. runs feature extraction and attaches it to every returned object.
    """

    #: Vendor key used by :data:`data_layer.metadata.VENDORS`.
    vendor = "generic"
    #: Directory names that mark a vendor data folder (``.d`` style).
    directory_markers: List[str] = []
    #: Text sidecar files whose ``key = value`` pairs become metadata.
    sidecar_files: List[str] = []

    # -- discovery ----------------------------------------------------------- #
    def can_handle(self, path: str | Path) -> bool:
        target = Path(path)
        if target.is_dir():
            return self._directory_score(target) > 0
        suffix = target.suffix.lower()
        if suffix in self.extensions:
            return True
        return sniff_format(target) in self.formats

    def _directory_score(self, target: Path) -> int:
        """How strongly this adapter recognises a directory container."""
        try:
            names = {entry.name.lower() for entry in target.iterdir()}
        except OSError:
            return 0
        score = sum(1 for marker in self.directory_markers if marker in names)
        return score

    # -- reading ------------------------------------------------------------- #
    def read(self, path: str | Path, **kwargs: Any) -> List[ScientificDataObject]:
        target = Path(path)
        if not target.exists():
            return []
        sidecar = self.read_sidecars(target)
        objects = self.read_vendor(target, sidecar=sidecar, **kwargs)
        if not objects:
            # Fallback: the generic parser understands several of the exports
            # a vendor toolchain produces (mzML, JCAMP-DX, two column ASCII).
            objects = GenericSpectrumAdapter().read(target, **kwargs)
            if objects:
                for obj in objects:
                    obj.source = self.vendor
                    obj.metadata.setdefault("fallback", "generic adapter")
                    obj.metadata.setdefault("vendor", self.vendor)
                    if sidecar:
                        obj.metadata.setdefault("extras", {}).update(sidecar)
        for obj in objects:
            obj.metadata.setdefault("vendor", self.vendor)
            if sidecar:
                extras = obj.metadata.setdefault("extras", {})
                for key, value in sidecar.items():
                    extras.setdefault(key, value)
            payload = obj.to_scientific_object()
            if isinstance(payload, Spectrum):
                features = extract_features(payload)
                obj.metadata.setdefault("extras", {})["features"] = features
        return objects

    def read_vendor(
        self,
        target: Path,
        sidecar: Dict[str, Any],
        **kwargs: Any,
    ) -> List[ScientificDataObject]:
        """Read the spectral payload.  Returns ``[]`` when undecodable."""
        return []

    # -- sidecars ------------------------------------------------------------ #
    def read_sidecars(self, target: Path) -> Dict[str, Any]:
        """Collect ``key = value`` metadata from vendor text sidecars.

        Three dialects are understood::

            ##$SW = 12.019          Bruker acqus / procs
            key: value              Waters _HEADER.TXT
            key = value             Agilent .M / .INF

        Bruker lines carry the ``##$`` prefix, so the prefix is stripped before
        the ``=`` test rather than being used to skip the line.
        """
        found: Dict[str, Any] = {}
        candidates: List[Path] = []
        if target.is_dir():
            for name in self.sidecar_files:
                direct = target / name
                if direct.exists():
                    candidates.append(direct)
                # Vendor nesting: <exp>/<no>/acqus, pdata/<n>/procs, ...
                for child in sorted(target.glob(f"**/{name}")):
                    candidates.append(child)
        else:
            candidates.append(target)
        for candidate in candidates:
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                separator = "=" if "=" in stripped else (":" if ":" in stripped else "")
                if not separator:
                    continue
                key, _, value = stripped.partition(separator)
                key = key.strip().lstrip("#$").strip()
                value = value.strip()
                if not key or key in found:
                    continue
                found[key] = _coerce_sidecar_value(value)
        return found


def _coerce_sidecar_value(value: str) -> Any:
    """Turn a sidecar string into int / float / list / str."""
    if value.startswith("<") and value.endswith(">"):
        inner = value[1:-1].strip()
        return [_coerce_sidecar_value(token.strip()) for token in inner.split(",") if token.strip()]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


#: Adapters registered on import, in priority order.
VENDOR_ADAPTERS: List[type] = []


def register_vendor_adapter(cls: type) -> type:
    """Class decorator: publish an adapter in :data:`VENDOR_ADAPTERS`."""
    VENDOR_ADAPTERS.append(cls)
    return cls
