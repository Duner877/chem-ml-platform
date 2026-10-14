"""Reader for Bruker NMR directories.

Two entry points are supported:

``read_bruker_fid(directory)``
    Reads ``acqus`` (acquisition parameters) plus the raw ``fid``/``ser`` file
    and performs apodisation, zero filling, Fourier transform and first order
    phase correction.

``read_bruker_1r(directory)``
    Reads the already processed ``1r`` / ``1rr`` real spectrum together with
    ``procs`` (``SF``, ``SW``, ``OFFSET``).

If the directory does not contain Bruker files the module can synthesise a
time domain signal (see :func:`synthesize_fid`) so that demo workflows stay
reproducible on machines without instrument data.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..objects import Peak, Spectrum

__all__ = ["read_bruker_fid", "read_bruker_1r", "read_bruker", "synthesize_fid"]

_PARAM = re.compile(r"^##\$([A-Za-z0-9_]+)=\s*(.*)$")


# --------------------------------------------------------------------------- #
# Parameter files
# --------------------------------------------------------------------------- #
def _read_params(path: Path) -> Dict[str, Any]:
    """Parse a Bruker parameter file (``acqus``/``procs``)."""
    params: Dict[str, Any] = {}
    if not path.exists():
        return params
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _PARAM.match(line)
        if not match:
            index += 1
            continue
        key, value = match.group(1), match.group(2).strip()
        if value.startswith("(") and not value.rstrip().endswith(")"):
            # multi-line array
            buffer = [value]
            index += 1
            while index < len(lines) and not lines[index].strip().endswith(")"):
                buffer.append(lines[index].strip())
                index += 1
            if index < len(lines):
                buffer.append(lines[index].strip())
            joined = " ".join(buffer)
            inner = joined[joined.find("(") + 1 : joined.rfind(")")]
            params[key] = [
                token
                for token in re.split(r"[,\s]+", inner)
                if token not in {"", "<>", "<", ">"}
            ]
        else:
            params[key] = value.strip("<>\"'")
        index += 1
    return params


def _as_float(params: Dict[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    if isinstance(value, list):
        value = value[0] if value else default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Raw FID
# --------------------------------------------------------------------------- #
def read_bruker_fid(
    directory: str | Path,
    line_broadening: float = 0.3,
    zero_fill: int = 1,
    **kwargs: Any,
) -> Spectrum:
    """Read a Bruker FID and return the frequency domain :class:`Spectrum`."""
    base = Path(directory)
    params = _read_params(base / "acqus")

    sf = _as_float(params, "SF", 400.13)  # spectrometer frequency [MHz]
    sw_ppm = _as_float(params, "SW", 20.0)  # spectral width [ppm]
    o1 = _as_float(params, "O1", 0.0)  # offset [Hz]
    td = int(_as_float(params, "TD", 32768))

    fid_path = base / "fid"
    if not fid_path.exists():
        raise FileNotFoundError(f"No Bruker FID file found in {base}")

    raw = np.frombuffer(fid_path.read_bytes(), dtype=">i4").astype(float)
    if raw.size < td:
        td = raw.size // 2 * 2
    raw = raw[: td // 2 * 2]
    complex_fid = raw[0::2] + 1j * raw[1::2]

    return _process_fid(
        complex_fid,
        sf=sf,
        sw_ppm=sw_ppm,
        offset_hz=o1,
        line_broadening=line_broadening,
        zero_fill=zero_fill,
        name=base.name,
    )


def read_bruker_1r(directory: str | Path, **kwargs: Any) -> Spectrum:
    """Read a Bruker processed spectrum (``1r``/``1rr``)."""
    base = Path(directory)
    params = _read_params(base / "procs")

    sf = _as_float(params, "SF", 400.13)
    sw_ppm = _as_float(params, "SW_p", _as_float(params, "SW", 20.0))
    offset_ppm = _as_float(params, "OFFSET", 0.0)

    for candidate in ("1rr", "1r"):
        path = base / candidate
        if path.exists():
            data = np.frombuffer(path.read_bytes(), dtype="<i4").astype(float)
            break
    else:
        raise FileNotFoundError(f"No processed Bruker spectrum in {base}")

    size = int(data.size)
    ppm = np.linspace(
        offset_ppm + sw_ppm / 2.0, offset_ppm - sw_ppm / 2.0, size, endpoint=False
    )
    peaks = _pick_nmr_peaks(ppm, data)
    return Spectrum(
        mode="NMR",
        technique="1H NMR",
        name=base.name,
        x=[float(v) for v in ppm],
        y=[float(v) for v in data],
        x_unit="ppm",
        y_unit="intensity",
        peaks=peaks,
        metadata={"spectrometer_frequency_mhz": sf, "source": "Bruker processed"},
    )


def read_bruker(directory: str | Path, **kwargs: Any) -> Spectrum:
    """Read either the processed spectrum or the raw FID of a Bruker folder."""
    base = Path(directory)
    if (base / "1r").exists() or (base / "1rr").exists():
        return read_bruker_1r(base, **kwargs)
    return read_bruker_fid(base, **kwargs)


def _process_fid(
    fid: np.ndarray,
    sf: float,
    sw_ppm: float,
    offset_hz: float,
    line_broadening: float,
    zero_fill: int,
    name: str = "",
) -> Spectrum:
    """Apodise, zero fill, FT and phase a time domain signal."""
    size = int(fid.size)
    if size == 0:
        return Spectrum(mode="NMR", technique="1H NMR", name=name)

    # Spectral width in Hz and dwell time.
    sw_hz = sw_ppm * sf
    dwell = 1.0 / sw_hz
    time = np.arange(size) * dwell

    # Exponential apodisation (line broadening in Hz).
    apodisation = np.exp(-np.pi * line_broadening * time)

    # Zero filling to the next power of two (repeated ``zero_fill`` times).
    target = size
    for _ in range(max(0, int(zero_fill))):
        target = 1 << int(np.ceil(np.log2(max(2, target * 2))))
    padded = np.zeros(target, dtype=complex)
    padded[:size] = fid * apodisation

    spectrum = np.fft.fft(padded)
    spectrum = np.fft.fftshift(spectrum)

    # Frequency axis in ppm (descending, as stored by Bruker):
    #   delta = (O1 - f) / SF      [O1 in Hz, SF in MHz -> delta in ppm]
    frequency_hz = np.fft.fftshift(np.fft.fftfreq(target, d=dwell))
    ppm_axis = (offset_hz - frequency_hz) / max(1e-9, sf)

    # Zero and first order phase correction (maximise the real part).
    magnitude = np.abs(spectrum)
    strongest = int(np.argmax(magnitude))
    phase = np.angle(spectrum[strongest])
    spectrum = spectrum * np.exp(-1j * phase)

    real = np.real(spectrum)
    peaks = _pick_nmr_peaks(ppm_axis, real)
    return Spectrum(
        mode="NMR",
        technique="1H NMR",
        name=name,
        x=[float(v) for v in ppm_axis],
        y=[float(v) for v in real],
        x_unit="ppm",
        y_unit="intensity",
        peaks=peaks,
        metadata={
            "spectrometer_frequency_mhz": sf,
            "spectral_width_hz": sw_hz,
            "points": int(target),
            "source": "Bruker FID (apodised, zero filled, phased)",
        },
    )


def _pick_nmr_peaks(ppm: np.ndarray, intensity: np.ndarray) -> List[Peak]:
    """Pick the strongest NMR resonances with a simple local-maximum search."""
    from ..processing import find_peaks

    if ppm.size == 0:
        return []
    order = np.argsort(ppm)
    return find_peaks(ppm[order], intensity[order], prominence=0.05, distance=0.02)


# --------------------------------------------------------------------------- #
# Synthesis (offline fallback)
# --------------------------------------------------------------------------- #
def synthesize_fid(
    signals: List[Dict[str, float]],
    points: int = 16384,
    spectral_width_hz: float = 6000.0,
    spectrometer_mhz: float = 400.13,
    relaxation: float = 0.8,
    noise: float = 0.01,
) -> np.ndarray:
    """Build a synthetic FID from a list of ``{ppm, intensity, multiplicity}``.

    The time domain signal is ``sum_i I_i * exp(-t/T2) * cos(2*pi*f_i*t)``
    where ``f_i = ppm_i * spectrometer_mhz`` (in Hz).  Multiplicities are
    rendered as binomial J-multiplets.
    """
    rng = np.random.default_rng(20240521)
    time = np.arange(points) / spectral_width_hz
    fid = np.zeros(points, dtype=float)
    for signal in signals or [{"ppm": 1.0, "intensity": 1.0, "multiplicity": 1}]:
        frequency = float(signal.get("ppm", 0.0)) * spectrometer_mhz
        amplitude = float(signal.get("intensity", 1.0))
        multiplicity = max(1, int(signal.get("multiplicity", 1)))
        coupling = float(signal.get("j", 7.0))
        if multiplicity <= 1:
            offsets = [0.0]
            weights = [1.0]
        else:
            # binomial intensities, symmetric J splitting
            weights = [
                float(math.comb(multiplicity - 1, k)) for k in range(multiplicity)
            ]
            total = float(sum(weights)) or 1.0
            weights = [w / total for w in weights]
            offsets = [
                (k - (multiplicity - 1) / 2.0) * coupling for k in range(multiplicity)
            ]
        for offset, weight in zip(offsets, weights):
            fid += (
                amplitude
                * weight
                * np.exp(-time / max(1e-6, relaxation))
                * np.cos(2.0 * np.pi * (frequency + offset) * time)
            )
    if noise > 0:
        fid += rng.normal(0.0, noise, points)
    return fid


def fid_to_spectrum(
    fid: np.ndarray,
    sf: float = 400.13,
    sw_ppm: float = 20.0,
    offset_hz: float = 0.0,
    line_broadening: float = 0.3,
    zero_fill: int = 1,
    name: str = "",
) -> Spectrum:
    """Fourier transform a (real) FID into a :class:`Spectrum`."""
    return _process_fid(
        np.asarray(fid, dtype=float).astype(complex),
        sf=sf,
        sw_ppm=sw_ppm,
        offset_hz=offset_hz,
        line_broadening=line_broadening,
        zero_fill=zero_fill,
        name=name,
    )
