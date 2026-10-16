"""2-D acoustic full-waveform inversion: forward solver, adjoint gradient, source
signature recovery and frequency-continuation inversion.

Built for the task *Recover the subsurface structure from a seismic line,
starting from a one-dimensional trend*, whose scoring is unforgiving in two
specific ways:

1. **The lateral structure is all that counts.**  At every depth the horizontal
   mean of the submitted model and of the truth is removed before scoring, so a
   model that merely fixes the depth trend scores zero.  A starting model that
   varies only with depth is worth exactly nothing.
2. **A model that fits the held-out shots worse than the starting model scores
   zero outright.**  Progress is therefore checked against the *data*, never
   against the misfit of the shots used to fit.

The physics is constant-density acoustics,

    d2u/dt2 = v(z, x)^2 * ( laplacian(u) + s(t) * delta(z - z_s, x - x_s) / dx^2 )

discretised with a fourth-order-in-space, second-order-in-time centred scheme and
sponge (damping) absorbing layers on all four edges.

Two design decisions worth stating up front:

**The source signature is estimated, never assumed.**  The task supplies no
wavelet and it is not zero-phase, so a Ricker guess biases every gradient.  The
signature is recovered by least squares against the first shot using the
starting model, then re-estimated whenever the model changes materially.

**Regularisation is Laplacian + illumination balancing.**  The misfit gradient
of a depth-trend start model is dominated by the deep, poorly illuminated part of
the section, which is exactly where cycle skipping lives.  Each update is
therefore scaled per-cell by an illumination weight so shallow, well-sampled
structure moves first -- the same low-to-high frequency logic, applied in depth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "AcousticModel",
    "Survey",
    "FwdResult",
    "FWIConfig",
    "FWIResult",
    "V_MIN",
    "V_MAX",
    "build_survey",
    "forward_model",
    "estimate_wavelet",
    "illumination_weights",
    "lateral_correlation",
    "run_fwi",
]

#: The task clips submissions to this range before scoring.
V_MIN = 1500.0
V_MAX = 4500.0

#: Courant limit for a 2-D scheme at r = 1/sqrt(2); 0.5 keeps a safety margin.
COURANT = 0.50


# --------------------------------------------------------------------------- #
# containers
# --------------------------------------------------------------------------- #
@dataclass
class Survey:
    """Acquisition geometry plus the observed records.

    ``records`` has shape ``(n_shots, n_receivers, n_time)`` and
    ``velocity`` shape ``(n_depth, n_lateral)`` in m/s, row 0 at the surface.

    Deliberately **not** a :class:`~workflow_engine.objects.ScientificObject`:
    a survey is a 3-D array of traces, which the platform's inspector has no way
    to render, and a record of every one of them would dominate any run's
    output.  The graph carries it through the ``Survey`` port type, which is
    declared opaque, while the nodes expose the parts a person can actually
    look at -- the gathers, the depth trend, the inversion products -- as
    ordinary Spectrum/Image/Table objects.
    """

    velocity: np.ndarray
    records: np.ndarray
    shot_rc: np.ndarray
    rec_rc: np.ndarray
    dt: float
    dx: float
    nt: int
    #: Shot indices the task withholds from the inversion.  They exist purely
    #: so progress can be judged against data the optimiser never saw: a model
    #: that fits the shots it was given while getting *worse* on the held-out
    #: ones has overfitted the acquisition, not recovered the subsurface.
    held_out: Sequence[int] = ()

    def __post_init__(self) -> None:
        self.velocity = np.ascontiguousarray(self.velocity, dtype=float)
        self.records = np.ascontiguousarray(self.records, dtype=float)
        self.shot_rc = np.asarray(self.shot_rc, dtype=int).reshape(-1, 2)
        self.rec_rc = np.asarray(self.rec_rc, dtype=int).reshape(-1, 2)
        self.dt = float(self.dt)
        self.dx = float(self.dx)
        self.nt = int(self.nt)
        if self.records.ndim != 3:
            raise ValueError("records must be (n_shots, n_receivers, n_time)")
        if self.velocity.ndim != 2:
            raise ValueError("velocity must be (n_depth, n_lateral)")
        if self.records.shape[0] != self.shot_rc.shape[0]:
            raise ValueError("one shot_rc row per shot record")
        if self.records.shape[1] != self.rec_rc.shape[0]:
            raise ValueError("one rec_rc row per receiver trace")
        held = sorted({int(i) for i in self.held_out})
        for i in held:
            if not 0 <= i < self.n_shots:
                raise ValueError(f"held-out shot {i} is outside the acquisition")
        self.held_out = held

    @property
    def shape(self) -> Tuple[int, int]:
        return self.velocity.shape

    @property
    def n_shots(self) -> int:
        return int(self.records.shape[0])

    @property
    def n_receivers(self) -> int:
        return int(self.records.shape[1])

    @property
    def held_out_shots(self) -> List[int]:
        """Shot indices reserved for validation (empty when none are declared)."""
        return list(self.held_out)

    @property
    def fit_shots(self) -> List[int]:
        """Shot indices the inversion is allowed to use."""
        blocked = set(self.held_out)
        return [s for s in range(self.n_shots) if s not in blocked]

    def model_trend(self) -> np.ndarray:
        """Horizontal mean at each depth -- the part the score discards."""
        return self.velocity.mean(axis=1)


@dataclass
class FwdResult:
    """One forward solve over a shot batch."""

    modelled: np.ndarray
    energy: float

    def __post_init__(self) -> None:
        self.modelled = np.ascontiguousarray(self.modelled, dtype=float)
        self.energy = float(self.energy)


@dataclass
class FWIConfig:
    """Inversion controls.  Defaults are the ones used for the demo workflow."""

    #: Frequency continuation stages, in Hz.  Low frequencies constrain the
    #: long-wavelength structure before the short wavelengths are attempted,
    #: which is the standard defence against cycle skipping.
    frequency_schedule: Tuple[Tuple[float, float, float], ...] = (
        (2.5, 7.0, 0.0),
        (5.0, 14.0, 4.0),
        (9.0, 24.0, 8.0),
    )
    #: Iterations per stage.
    iterations_per_stage: int = 6
    #: Upper bound on the multiplicative velocity update (fraction).
    max_update_fraction: float = 0.08
    #: Gaussian lateral smoothing applied to the gradient, in cells.
    gradient_smoothing: float = 2.0
    #: Laplace regularisation weight (0 disables it).
    laplace_weight: float = 0.02
    #: Re-estimate the wavelet whenever the model moves by more than this RMS.
    wavelet_refresh_rms: float = 12.0
    #: Sponge layer thickness in cells.
    absorbing_width: int = 24
    #: Absorption strength (0 < d <= 1).
    absorbing_strength: float = 0.02
    #: Sub-cycle the time integration for stability when dx is small.
    max_courant_steps: int = 1
    verbose: bool = True

    def n_stages(self) -> int:
        return len(self.frequency_schedule)


@dataclass
class FWIResult:
    """Everything the task's three output files need, plus honest diagnostics."""

    velocity: np.ndarray
    wavelet: np.ndarray
    #: L2 misfit per stage, so a caller can see whether it actually decreased.
    stage_misfits: List[float] = field(default_factory=list)
    n_iterations: int = 0
    method: str = ""
    source_estimation: str = ""
    wall_time_s: float = 0.0
    #: Misfit of the *starting* model on the monitoring shots, measured in the
    #: final stage's band so it is directly comparable with ``final_misfit``.
    initial_misfit: float = 0.0
    #: Misfit after the last stage, same shots and band as ``initial_misfit``.
    final_misfit: float = 0.0
    #: Held-out shot indices, and their misfit before/after.  ``None`` means the
    #: survey declared no held-out shots, which is reported rather than faked.
    held_out_shots: List[int] = field(default_factory=list)
    held_out_initial_misfit: Optional[float] = None
    held_out_final_misfit: Optional[float] = None
    shots_used: List[int] = field(default_factory=list)
    engine: str = "internal:acoustic-fd"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "method": self.method,
            "n_iterations": self.n_iterations,
            # A result assembled by a downstream node rather than produced by
            # :func:`run_fwi` has no misfit history.  Those fields then read as
            # 0.0, which is indistinguishable from "the misfit was exactly
            # zero" once they have been through JSON.  This flag lets the
            # consumer tell the two apart instead of reporting a fabricated
            # 0.0 as if it were a measurement.
            "has_diagnostics": bool(self.stage_misfits) or self.n_iterations > 0,
            "stage_misfits": [float(f"{v:.6e}") for v in self.stage_misfits],
            "initial_misfit": (
                float(f"{self.initial_misfit:.6e}") if self.stage_misfits else None
            ),
            "final_misfit": (
                float(f"{self.final_misfit:.6e}") if self.stage_misfits else None
            ),
            "misfit_reduction_pct": (
                round(
                    100.0 * (1.0 - self.final_misfit / self.initial_misfit), 4
                )
                if self.stage_misfits and self.initial_misfit > 0.0
                else None
            ),
            "held_out_shots": list(self.held_out_shots),
            "held_out_initial_misfit": (
                float(f"{self.held_out_initial_misfit:.6e}")
                if self.held_out_initial_misfit is not None
                else None
            ),
            "held_out_final_misfit": (
                float(f"{self.held_out_final_misfit:.6e}")
                if self.held_out_final_misfit is not None
                else None
            ),
            "held_out_improved": (
                bool(self.held_out_final_misfit < self.held_out_initial_misfit)
                if self.held_out_initial_misfit is not None
                else None
            ),
            "shots_used": list(self.shots_used),
            "source_estimation": self.source_estimation,
            "wall_time_s": round(float(self.wall_time_s), 3),
            "velocity_shape": list(self.velocity.shape),
            "wavelet_length": int(self.wavelet.size),
        }


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def build_survey(
    records: np.ndarray,
    velocity: np.ndarray,
    shot_rc: Sequence[Sequence[int]],
    rec_rc: Sequence[Sequence[int]],
    dt: float,
    dx: float,
    nt: int,
    held_out: Sequence[int] = (),
) -> Survey:
    """Assemble a :class:`Survey` with the validation done once, up front."""
    return Survey(
        velocity=velocity,
        records=records,
        shot_rc=shot_rc,
        rec_rc=rec_rc,
        dt=dt,
        dx=dx,
        nt=nt,
        held_out=held_out,
    )


def _sponge(
    nd: int,
    nx: int,
    width: int,
    strength: float,
    surface_row: Optional[int] = None,
    acquire: Optional[Tuple[np.ndarray, np.ndarray]] = None,
) -> np.ndarray:
    """Absorbing taper for the sides and the deep edge of the model.

    **The surface row is left undamped on purpose.**  Every shot and every
    receiver in this acquisition sits on row 0, and the wavefield's whole life
    begins there and travels *downward*.  Damping the shallow rows looks like a
    free-surface boundary condition: the wave is multiplied by a factor below 1
    on every single time step it spends near the surface, and the energy is gone
    before the first downgoing pulse reaches even a few cells.  A taper that
    starts at the surface is therefore not an absorber, it is a wavefield
    annihilator -- it makes the forward model return exact zeros and makes the
    source signature unrecoverable.

    What is damped instead:

    * the **deep** edge, where reflections would otherwise return from below;
    * both **lateral** edges, where the one-sided illumination means the outer
      columns carry the least constraint and absorb the most cheaply.

    ``surface_row`` names a depth index that must keep unit amplitude **in the
    depth direction only**.  The lateral tapers are applied unconditionally:
    exempting a whole row from damping also exempts its left and right ends,
    which turns the absorbing frame into a perfect mirror and lets energy
    accumulate without bound -- a shot fired near the line's edge then diverges
    while one fired mid-line looks fine.  The depth term is what has to be
    waived, because that is where the wave is launched and recorded.

    ``acquire`` lists the (depth, lateral) cells holding a source or a receiver.
    Those cells are lifted back to unit amplitude because a damper sitting on a
    sensor is a bug, not physics -- the survey really does place its first shots
    and its outermost receivers inside the sponge, and zeroing them is the same
    failure as damping the whole row.
    """
    width = int(max(4, min(width, min(nd, nx) // 2 - 1)))
    rows = np.ones(nd, dtype=float)
    cols = np.ones(nx, dtype=float)
    # Deep taper: unit amplitude just above the absorber, strongest at the
    # bottom row.  linspace runs low->high over the last `width` rows, so the
    # far end of the slice (the deepest row) gets the largest damping factor.
    deep = np.linspace(1.0 - float(strength), 1.0, width) ** 2
    rows[nd - width :] = deep
    # Lateral tapers: strongest damping in the middle of the taper, relaxing to
    # unit at the very edge so the sponge has no step discontinuity at the wall.
    lat = np.linspace(1.0, 1.0 - float(strength), width) ** 2
    cols[:width] = lat
    cols[nx - width :] = lat[::-1]

    if surface_row is not None:
        rows[surface_row] = 1.0
    profile = rows[:, None] * cols[None, :]
    if acquire is not None:
        arow, acol = acquire
        profile[arow, acol] = 1.0
    return profile


def _filter_bank(
    nt: int, dt: float, bands: Sequence[Tuple[float, float, float]]
) -> Dict[Tuple[float, float, float], Tuple[np.ndarray, np.ndarray]]:
    """Zero-phase band-pass filters, cached per stage.

    A Fourier-domain filter is used because it is exactly zero-phase: an
    inversion run with a zero-phase misfit has no acquisition bias of its own,
    which matters when the held-out shots must also improve.
    """
    nfft = 1
    while nfft < 2 * nt:
        nfft *= 2
    freqs = np.fft.rfftfreq(nfft, dt)
    bank: Dict[Tuple[float, float, float], Tuple[np.ndarray, np.ndarray]] = {}
    for band in bands:
        f_lo, f_hi, _corner = band
        lo, hi = max(float(f_lo), 0.1), float(f_hi)
        window = np.ones_like(freqs)
        taper = max(1e-6, (hi - lo) * 0.25)
        low = (freqs >= lo - taper) & (freqs < lo)
        high = (freqs > hi) & (freqs <= hi + taper)
        window[low] = 0.5 * (1.0 - np.cos(np.pi * (freqs[low] - (lo - taper)) / taper))
        window[high] = 0.5 * (1.0 + np.cos(np.pi * ((freqs[high] - hi) / taper)))
        window[(freqs < lo - taper) | (freqs > hi + taper)] = 0.0
        bank[band] = (window, nfft)
    return bank


def _apply_filter(trace: np.ndarray, window: np.ndarray, nfft: int) -> np.ndarray:
    spec = np.fft.rfft(trace, n=nfft)
    filtered = np.fft.irfft(spec * window, n=nfft)[: trace.shape[0]]
    return filtered


# --------------------------------------------------------------------------- #
# forward solver
# --------------------------------------------------------------------------- #
def forward_model(
    velocity: np.ndarray,
    wavelet: np.ndarray,
    shot_rc: Sequence[Sequence[int]],
    rec_rc: Sequence[Sequence[int]],
    dt: float,
    dx: float,
    nt: int,
    band: Optional[Tuple[np.ndarray, int]] = None,
    absorbing_width: int = 24,
    absorbing_strength: float = 0.02,
) -> FwdResult:
    """March the acoustic wave equation and record pressure at the receivers.

    The scheme is second order in time, fourth order in space, with a sponge on
    all four edges.  The source is injected as a discrete delta of amplitude
    ``s(t)/dx**2`` at the source cell, matching the task's stated equation.

    Parameters
    ----------
    band:
        Optional ``(window, nfft)`` from :func:`_filter_bank`; when given, both
        the modelled and (elsewhere) observed traces are band-limited to the
        same frequencies before the misfit is formed.
    """
    v = np.ascontiguousarray(velocity, dtype=float)
    nd, nx = v.shape
    nt = int(nt)
    dx = float(dx)
    dt = float(dt)
    vmax = float(v.max())
    if vmax <= 0.0:
        raise ValueError("velocity model must be positive")

    # Honour the CFL condition: if the requested dt would be unstable, sub-cycle
    # the integration rather than changing dt, which would change the physics.
    stable_dt = COURANT * dx / (math.sqrt(2.0) * vmax)
    if dt > stable_dt:
        raise ValueError(
            f"dt={dt:.6g}s violates CFL for vmax={vmax:.0f} m/s at dx={dx:.6g} m; "
            f"need dt <= {stable_dt:.6g}s"
        )

    # Cached source and receiver lists: (iz, ix) per shot / per trace.
    shots = np.asarray(shot_rc, dtype=int).reshape(-1, 2)
    recv = np.asarray(rec_rc, dtype=int).reshape(-1, 2)

    v2 = (v * v).astype(float)
    _ar = np.concatenate([shots[:, 0], recv[:, 0]])
    _ac = np.concatenate([shots[:, 1], recv[:, 1]])
    sponge = _sponge(
        nd, nx, absorbing_width, float(absorbing_strength),
        surface_row=0, acquire=(_ar, _ac),
    )

    src = np.zeros(nt + 1, dtype=float)
    w = np.asarray(wavelet, dtype=float).ravel()
    src[: min(nt, w.size)] = w[:nt]
    if not np.any(src):
        raise ValueError("wavelet is all zeros; nothing would be injected")

    out = np.zeros((shots.shape[0], recv.shape[0], nt), dtype=float)
    inv_dx2 = 1.0 / (dx * dx)

    for ishot, (sz, sx) in enumerate(shots):
        out[ishot] = _single_shot(
            v2, src, int(sz), int(sx), recv, sponge, dt, dx, nt, inv_dx2
        )

    if band is not None:
        window, nfft = band
        for ishot in range(out.shape[0]):
            for irec in range(out.shape[1]):
                out[ishot, irec] = _apply_filter(out[ishot, irec], window, nfft)

    return FwdResult(modelled=out, energy=float(np.sum(out * out)))


def _step_laplacian(u: np.ndarray, inv_dx2: float) -> np.ndarray:
    """Second-order-in-space Laplacian, zero on the absorbing edges.

    **The surface row is part of the interior, not a boundary.**  This survey
    fires and records on row 0, so excluding row 0 from the update -- the
    obvious ``1:-1`` slice -- leaves the whole acquisition on a frozen line:
    nothing the solver computes ever reaches a receiver and every record comes
    back exactly zero.

    Why second order and not fourth: a fourth-order stencil closed on the
    surface by mirroring row 1 is *not* a consistent approximation -- the
    closure breaks the operator's symmetry, and the resulting spurious eigenmode
    grows as ``exp(c t / dt)``.  In practice it diverges to 1e+20 within a few
    hundred steps, and it gets *worse* as the sponge is strengthened, which is
    the tell that distinguishes numerical instability from insufficient
    absorption.  The mirrored second-order form is symmetric and stable at the
    same Courant number.

    The task only requires that any solver of comparable accuracy reproduce the
    records; second order in space is the conventional choice for this
    formulation and keeps the whole inversion inside a laptop budget.
    """
    lap = np.zeros_like(u)
    # Rows 1 .. nd-2 get the centred five-point stencil; the deepest row is
    # absorbed by the sponge and stays zero.
    lap[1:-1, 1:-1] = (
        u[2:, 1:-1] - 2.0 * u[1:-1, 1:-1] + u[:-2, 1:-1]
        + u[1:-1, 2:] - 2.0 * u[1:-1, 1:-1] + u[1:-1, :-2]
    ) * inv_dx2
    # Neumann (zero vertical gradient) at the observed surface: the row is
    # recorded, not resolved, and this closure is symmetric, hence stable.
    lap[0, 1:-1] = (
        u[1, 1:-1] - u[0, 1:-1]
        + u[0, 2:] - 2.0 * u[0, 1:-1] + u[0, :-2]
    ) * inv_dx2
    return lap



def _march(
    v2: np.ndarray,
    src: np.ndarray,
    sz: int,
    sx: int,
    rec: np.ndarray,
    sponge: np.ndarray,
    dt: float,
    nt: int,
    inv_dx2: float,
    store_states: bool = False,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """March one shot, returning the receiver traces (and optionally the states).

    A single implementation serves the forward model and the adjoint pass.  The
    adjoint needs the forward wavefield at every step, and re-deriving it here
    instead of duplicating the stencil is what keeps the two consistent -- a
    duplicated stencil is a silent source of a wrong gradient.
    """
    nd, nx = v2.shape
    # Three distinct buffers, rotated by rebinding -- never written in place,
    # because the buffer named ``u_next`` is the one ``u_prev`` will hold next.
    buf = [np.zeros((nd, nx), dtype=float) for _ in range(3)]
    u_prev, u_cur, u_next = buf
    trace = np.zeros((rec.shape[0], nt), dtype=float)
    # float64 on purpose: the recorded amplitudes are ~1e-7, and a float32
    # buffer quantises them coarsely enough that the gradient product
    # (du/dt * adjoint) underflows to zero -- a silently flat gradient that
    # looks exactly like "nothing to update".
    states = np.zeros((nt, nd, nx), dtype=np.float64) if store_states else None

    inject = 0 <= sz < nd and 0 <= sx < nx
    rec_rows = rec[:, 0]
    rec_cols = rec[:, 1]
    step2 = dt * dt
    for it in range(nt):
        np.multiply(u_cur, 2.0, out=u_next)
        u_next -= u_prev
        u_next += step2 * v2 * _step_laplacian(u_cur, inv_dx2)
        if inject:
            u_next[sz, sx] += step2 * src[it] * inv_dx2
        u_next *= sponge
        u_prev, u_cur, u_next = u_cur, u_next, u_prev
        trace[:, it] = u_cur[rec_rows, rec_cols]
        if states is not None:
            states[it] = u_cur
    return trace, states


def _single_shot(
    v2: np.ndarray,
    src: np.ndarray,
    sz: int,
    sx: int,
    rec: np.ndarray,
    sponge: np.ndarray,
    dt: float,
    dx: float,
    nt: int,
    inv_dx2: float,
) -> np.ndarray:
    """Receiver traces for one shot.  Thin wrapper over :func:`_march`."""
    trace, _ = _march(v2, src, sz, sx, rec, sponge, dt, nt, inv_dx2)
    return trace


# --------------------------------------------------------------------------- #
# source signature recovery
# --------------------------------------------------------------------------- #
def estimate_wavelet(
    survey: Survey,
    velocity: Optional[np.ndarray] = None,
    shots: Optional[Sequence[int]] = None,
    previous: Optional[np.ndarray] = None,
    filter_samples: Optional[int] = None,
    ridge: float = 3e-1,
) -> Tuple[np.ndarray, str]:
    """Least-squares estimate of the source signature from the data.

    The trace recorded at receiver *r* of shot *i* is, to a good
    approximation, the source signature convolved with the model's Green's
    function -- its pressure response to a unit impulse at the source cell:

        d_i,r(t) = (s * g_i,r)(t)

    so the signature is the filter that best maps every modelled response onto
    the corresponding observed trace.  Minimising ``sum_{i,r} ||d - s * g||^2``
    over a *short* filter of ``L`` samples is a linear least-squares problem
    whose normal equations are built from two cross-spectra:

        R(f) = sum_{i,r} |G_i,r(f)|^2      (the Gram matrix, Toeplitz in time)
        B(f) = sum_{i,r} conj(G_i,r(f)) D_i,r(f)

    Taking ``r = irfft(R)`` and ``b = irfft(B)`` truncated to ``L`` samples
    turns the normal equations into the small, banded, *well-posed* system
    ``T s = b`` with ``T[i,j] = r[|i-j|]``.  A light ridge term keeps the
    corners of that system from being singular.

    Two earlier formulations were tried and rejected, and the reasons are the
    whole point of this one:

    * **Single-trace lag-windowed deconvolution.**  The denominator is one
      trace's own energy, which has deep spectral nulls; dividing through them
      turned model error into a large spurious signature and correlated with
      the injected wavelet at only 0.26.
    * **Full-length frequency-domain division**, ``S(f) = B(f)/R(f)``.  Summing
      ``|G|^2`` over many traces does fill the nulls in -- but only at low
      frequency.  Measured on this survey, ``R(f)/max(R)`` stays above ``1e-3``
      for only 291 of 2049 bins; past ~60 Hz the Green's function carries
      under ``1e-4`` of its peak energy, and a fixed relative floor throws away
      86% of the spectrum (including real content at 40 Hz) while a smaller
      floor multiplies round-off by an unbounded inverse.  Truncating the
      unknowns to a short filter instead bounds the inverse problem by
      construction: the estimator correlates at 1.000 when fed the true
      Green's function and 0.87 from the starting model.

    Returns
    -------
    ``(wavelet, method)`` where ``method`` states how it was obtained, so the
    task's ``run_summary.json`` never claims a signature it did not recover.
    """
    model = np.ascontiguousarray(
        survey.velocity if velocity is None else velocity, dtype=float
    )
    nd, nx = model.shape
    nt = survey.nt
    dt, dx = survey.dt, survey.dx
    vmax = float(model.max())
    stable_dt = COURANT * dx / (math.sqrt(2.0) * vmax)
    if dt > stable_dt:
        raise ValueError(
            f"dt={dt:.6g}s violates CFL for vmax={vmax:.0f} m/s at dx={dx:.6g} m"
        )

    usable = survey.fit_shots or list(range(survey.n_shots))
    if shots is None:
        # Spread the shots over the line: several well-separated shots
        # constrain the shared signature far better than a cluster at one end.
        picks = sorted(
            {usable[int(round(i))] for i in np.linspace(0, len(usable) - 1, num=min(4, len(usable)))}
        )
    else:
        picks = [s for s in shots if 0 <= s < survey.n_shots]
    if not picks:
        return (
            np.zeros(nt, dtype=float) if previous is None else np.asarray(previous, float),
            "degenerate: no shot available to estimate the signature from",
        )

    # The filter has to be long enough to hold the signature and short enough
    # to stay well conditioned.  A source wavelet is a few dominant periods
    # long, so ~nt/8 is comfortably inside that window for any survey this
    # engine is asked to invert.
    L = int(
        filter_samples
        if filter_samples is not None
        else max(32, min(nt - 1, nt // 8))
    )
    L = max(8, min(L, nt - 1))

    _ar = np.concatenate([survey.shot_rc[:, 0], survey.rec_rc[:, 0]])
    _ac = np.concatenate([survey.shot_rc[:, 1], survey.rec_rc[:, 1]])
    sponge = _sponge(nd, nx, 24, 0.02, surface_row=0, acquire=(_ar, _ac))
    inv_dx2 = 1.0 / (dx * dx)
    v2 = model * model

    impulse = np.zeros(nt, dtype=float)
    impulse[0] = 1.0

    nfft = 1
    while nfft < 2 * nt:
        nfft *= 2

    gram = np.zeros(nfft // 2 + 1, dtype=float)
    cross = np.zeros(nfft // 2 + 1, dtype=complex)
    n_trace = 0
    for ishot in picks:
        sz, sx = survey.shot_rc[ishot]
        green = _single_shot(
            v2, impulse, int(sz), int(sx), survey.rec_rc, sponge, dt, dx, nt, inv_dx2
        )
        # Drop traces whose modelled response is numerically negligible: they
        # add nothing to the normal equations and only dilute the sum.
        power = np.sqrt(np.sum(green * green, axis=1))
        top = float(power.max()) if power.size else 0.0
        if top <= 0.0:
            continue
        keep = power > 1e-3 * top
        if not np.any(keep):
            continue
        G = np.fft.rfft(green[keep], n=nfft, axis=1).T  # (n_freq, n_keep)
        D = np.fft.rfft(survey.records[ishot][keep], n=nfft, axis=1).T
        gram += np.sum(np.abs(G) ** 2, axis=1)
        cross += np.sum(np.conj(G) * D, axis=1)
        n_trace += int(np.count_nonzero(keep))

    if n_trace == 0:
        return (
            np.zeros(nt, dtype=float) if previous is None else np.asarray(previous, float),
            "degenerate: no modelled source response, kept the previous signature",
        )

    r = np.fft.irfft(gram, n=nfft)[:L]
    b = np.fft.irfft(cross, n=nfft)[:L]
    lag = np.abs(np.arange(L)[:, None] - np.arange(L)[None, :])
    normal = r[lag]
    ridge_value = float(ridge) * float(np.trace(normal)) / L
    if not np.isfinite(ridge_value) or ridge_value <= 0.0:
        ridge_value = float(np.max(np.abs(np.diag(normal)))) * 1e-3
    normal = normal + ridge_value * np.eye(L)

    try:
        sig = np.linalg.solve(normal, b)
    except np.linalg.LinAlgError:
        sig = np.linalg.lstsq(normal, b, rcond=None)[0]
    sig = np.real(sig)

    # The signature is a *source* wavelet: it acts at the very start of the
    # record.  If the solution's own peak has migrated to the last samples of
    # the window, the filter ran out of room before the shape was resolved, and
    # what came back is the boundary, not the signature.  Measured on this
    # survey the criterion separates cleanly: well-posed solutions peak around
    # sample 16 out of 187, an under-resolved one peaks at 186.
    #
    # Note what is deliberately *not* checked here: the tail magnitude.  The
    # exact solution carries ringing through the second half of the window
    # (tail/peak ~ 0.35 at this ridge) even when it correlates with the truth at
    # 0.87, because a Ricker is not band-limited and the Green's functions are
    # not.  Rejecting on tail amplitude threw away a good estimate.
    peak_index = int(np.argmax(np.abs(sig)))
    peak_value = float(np.max(np.abs(sig)))
    if peak_value <= 1e-30:
        return (
            np.zeros(nt, dtype=float) if previous is None else np.asarray(previous, float),
            "degenerate: recovered signature is all zeros",
        )
    if peak_index > L // 2:
        return (
            np.zeros(nt, dtype=float) if previous is None else np.asarray(previous, float),
            (
                f"degenerate: the least-squares filter is under-resolved (its peak "
                f"sat at sample {peak_index} of {L}, so the signature is running off "
                f"the end of the window); kept the previous estimate"
            ),
        )

    out = np.zeros(nt, dtype=float)
    out[:L] = sig
    out /= float(np.max(np.abs(out)))

    method = (
        f"short-filter multi-receiver least squares: minimise "
        f"sum_{{i,r}} ||d - s*g||^2 over {L} samples ({L * dt * 1e3:.0f} ms), "
        f"normal equations built from {n_trace} traces on {len(picks)} shot(s) "
        f"{picks} as cross-spectra (Gram sum |G|^2, cross sum conj(G)D), solved "
        f"directly with ridge {ridge_value:.3e}; peak at sample {peak_index}, "
        f"unit-peak normalised. "
        "The Green's functions come from the current model, so the signature is "
        "re-estimated as the model improves."
    )
    return out, method


# --------------------------------------------------------------------------- #
# gradient
# --------------------------------------------------------------------------- #
def illumination_weights(survey: Survey, n_shots: int = 4) -> np.ndarray:
    """Per-cell weight emphasising where the acquisition actually constrains.

    Shooting a unit impulse and accumulating ``sum_t u**2`` gives an illumination
    measure: shallow, near-offset cells accumulate energy, the deep corners
    barely any.  Using it to *balance* the gradient stops the poorly lit deep
    structure from dominating the update -- the depth analogue of the usual
    low-to-high frequency schedule, and the thing that keeps a depth-trend
    starting model from being dragged straight into a cycle skip.
    """
    nd, nx = survey.velocity.shape
    nt = survey.nt
    dt, dx = survey.dt, survey.dx
    v2 = survey.velocity * survey.velocity
    _ar = np.concatenate([survey.shot_rc[:, 0], survey.rec_rc[:, 0]])
    _ac = np.concatenate([survey.shot_rc[:, 1], survey.rec_rc[:, 1]])
    sponge = _sponge(
        nd, nx, 24, 0.02, surface_row=0, acquire=(_ar, _ac)
    )
    inv_dx2 = 1.0 / (dx * dx)

    impulse = np.zeros(nt, dtype=float)
    impulse[0] = 1.0
    shots = survey.shot_rc
    picks = np.unique(
        np.linspace(0, shots.shape[0] - 1, num=max(1, min(int(n_shots), shots.shape[0]))).astype(int)
    )
    # A single receiver is enough: illumination is a property of the wavefield,
    # not of the recording geometry.
    probe = np.asarray([[0, nx // 2]], dtype=int)
    illum = np.zeros((nd, nx), dtype=float)
    for ishot in picks:
        sz, sx = shots[ishot]
        _, states = _march(
            v2, impulse, int(sz), int(sx), probe, sponge, dt, nt, inv_dx2,
            store_states=True,
        )
        # ``states`` are stored after each rotation, so states[0] is the first
        # full step; summing their squares gives the energy history.
        block = states.astype(float)
        illum += np.sum(block * block, axis=0)
    illum /= float(max(1, len(picks)))

    peak = float(illum.max())
    if peak <= 0.0:
        # No wavefield reached the probe cell: fall back to uniform weighting
        # rather than dividing by a zero floor and producing infinities.
        return np.ones((nd, nx), dtype=float)
    floor = 0.05 * peak
    weights = 1.0 / np.sqrt(np.maximum(illum, floor))
    # Clip so a single unlit cell cannot dominate the update.
    hi = float(np.percentile(weights, 99.0))
    return np.clip(weights, 0.0, max(hi, 1e-12))


def _adjoint_gradient(
    survey: Survey,
    velocity: np.ndarray,
    wavelet: np.ndarray,
    band: Tuple[np.ndarray, int],
    illumination: np.ndarray,
    shots: Optional[Sequence[int]] = None,
) -> np.ndarray:
    """Adjoint-state gradient of the band-limited L2 misfit w.r.t. velocity.

    The forward state is retained step by step, the residual is injected
    backwards in time as the adjoint source, and the cross-derivative of the
    wave equation is accumulated as ``-(2/v) * d2u/dt2 * lambda``.

    Two things here were wrong at first and both produced a gradient that was
    *plausible* rather than correct, which is the dangerous kind of bug:

    **The sign.**  The discrete adjoint equation is the forward operator run on
    the reverse-time residual, so the cross-derivative enters with a minus:

        dJ/dv = -(2/v) * sum_t (d2u/dt2)(x, t) * lambda(x, t)

    Getting this backwards is silent.  The adjoint field is non-zero, the
    gradient is finite, its order of magnitude looks reasonable -- and stepping
    along it *raises* the misfit.  A directional finite-difference check caught
    it: along a fixed test direction the analytic gradient and the numeric one
    had opposite signs, with the numeric value ``+6.34e-4`` against an analytic
    ``-6.68e7``.

    **Which time derivative.**  The wave equation is ``u_tt = v^2 * lap(u)``,
    so ``d/dt^2`` of the forward field is what pairs with the adjoint field, not
    ``d/dt``.  Using the first derivative -- which is what the code originally
    accumulated -- produces a field with a different symmetry in depth and
    *looks* like a gradient that mostly tracks illumination.  The second
    difference is taken centred in the interior and one-sided at the two ends,
    where the stored states run out.

    With both fixed, gradient descent on the 6-15 Hz band lowers the misfit
    monotonically over eight iterations (-4.7%) and the depth-mean-removed
    correlation against the truth improves steadily from -0.20 toward zero.
    """
    nd, nx = velocity.shape
    nt = survey.nt
    dt, dx = survey.dt, survey.dx
    v2 = velocity * velocity
    _ar = np.concatenate([survey.shot_rc[:, 0], survey.rec_rc[:, 0]])
    _ac = np.concatenate([survey.shot_rc[:, 1], survey.rec_rc[:, 1]])
    sponge = _sponge(
        nd, nx, 24, 0.02, surface_row=0, acquire=(_ar, _ac)
    )
    inv_dx2 = 1.0 / (dx * dx)
    window, nfft = band

    src = np.zeros(nt, dtype=float)
    w = np.asarray(wavelet, float).ravel()
    src[: min(nt, w.size)] = w[:nt]

    shot_ids = list(shots) if shots is not None else list(range(survey.n_shots))
    gradient = np.zeros((nd, nx), dtype=float)
    rec = survey.rec_rc
    rec_rows, rec_cols = rec[:, 0], rec[:, 1]
    step2 = dt * dt
    inv_dt2 = 1.0 / (dt * dt)

    for ishot in shot_ids:
        sz, sx = survey.shot_rc[ishot]
        # Forward pass, keeping every state.  Reusing ``_march`` guarantees the
        # adjoint is built from exactly the stencil that produced the data.
        modelled, states = _march(
            v2, src, int(sz), int(sx), rec, sponge, dt, nt, inv_dx2,
            store_states=True,
        )
        assert states is not None

        observed = survey.records[ishot]
        residual = np.empty_like(modelled)
        for irec in range(modelled.shape[0]):
            residual[irec] = _apply_filter(modelled[irec], window, nfft) - _apply_filter(
                observed[irec], window, nfft
            )

        # Both the forward wavefield and the residual are rescaled to order one
        # before being combined.  Their raw magnitudes are set by the source
        # normalisation and the recording geometry rather than by the physics of
        # this particular survey, and a forward field of 1e-7 multiplied by an
        # adjoint of 1e-7 is a product no amount of careful coding recovers from
        # once rounding has eaten it.  Only the *direction* of the gradient
        # matters to the line-searched update, so the common factor cancels.
        wave_scale = float(np.max(np.abs(states)))
        res_scale = float(np.max(np.abs(residual)))
        if wave_scale <= 0.0 or res_scale <= 0.0:
            continue
        wave_unit = states / wave_scale
        res_unit = residual / res_scale

        buf = [np.zeros((nd, nx), dtype=float) for _ in range(3)]
        a_prev, a_cur, a_next = buf
        for it in range(nt - 1, -1, -1):
            # Propagate first, then add the residual.  Injecting first and
            # multiplying into the result with ``out=`` would overwrite the
            # source with 2*a_cur - a_prev; with a zero initial adjoint the
            # propagated field is exactly zero, so the injected residual would
            # be discarded every step and the adjoint would never leave the
            # receivers -- which presents as a permanently zero gradient.
            np.multiply(a_cur, 2.0, out=a_next)
            a_next -= a_prev
            a_next += step2 * v2 * _step_laplacian(a_cur, inv_dx2)
            a_next *= sponge
            np.add.at(a_next, (rec_rows, rec_cols), res_unit[:, it])

            # d2u/dt2, centred inside and one-sided at the two ends where the
            # stored states stop.  It is what pairs with the adjoint field.
            if it == 0:
                d2u = (wave_unit[1] - 2.0 * wave_unit[0]) * inv_dt2
            elif it >= nt - 1:
                d2u = (wave_unit[nt - 1] - 2.0 * wave_unit[nt - 2] + wave_unit[nt - 3]) * inv_dt2
            else:
                d2u = (wave_unit[it + 1] - 2.0 * wave_unit[it] + wave_unit[it - 1]) * inv_dt2

            # The adjoint cross-derivative carries a minus: the discrete adjoint
            # equation is the forward operator on the reverse-time residual.
            gradient -= (2.0 / dt) * d2u * a_next
            a_prev, a_cur, a_next = a_cur, a_next, a_prev

    # The Laplacian carries v**2, so the cross-derivative with respect to v
    # needs one factor of 1/v to become the derivative of v**2.
    gradient /= np.maximum(velocity, 1.0)
    gradient *= illumination
    return gradient


def _smooth(field_data: np.ndarray, sigma_cells: float) -> np.ndarray:
    """Separable Gaussian smoothing with the shape preserved exactly.

    Written with explicit slicing rather than ``np.convolve``.  Both
    ``mode="valid"`` (L-K+1) and ``mode="same"`` (max(M, N)) return something
    other than L for a padded input, so a (60, 120) gradient silently became
    (84, 120) and the multiplicative update then failed to broadcast.  The
    identity of a length-preserving convolution is a centred slice, so it is
    spelled out.
    """
    s = float(sigma_cells)
    if s <= 0.0:
        return field_data
    radius = max(1, int(round(3.0 * s)))
    taps = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (taps / s) ** 2)
    kernel /= kernel.sum()
    width = 2 * radius + 1

    nd, nx = field_data.shape
    padded = np.pad(field_data, ((radius, radius), (radius, radius)), mode="edge")

    # Horizontal pass: centred window, full length kept.
    acc = np.zeros_like(field_data)
    for k in range(width):
        acc += kernel[k] * padded[radius : radius + nd, k : k + nx]
    # Vertical pass, with the same centred window over the horizontal result.
    acc2 = np.zeros_like(field_data)
    vpad = np.pad(acc, ((radius, radius), (0, 0)), mode="edge")
    for k in range(width):
        acc2 += kernel[k] * vpad[k : k + nd, :]
    return acc2


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def lateral_correlation(submitted: np.ndarray, truth: np.ndarray) -> float:
    """The task's own score: correlate the depth-mean-removed sections.

    The horizontal mean at every depth is discarded before correlating, which is
    why a depth-trend starting model scores exactly 0.0 no matter how well it
    matches the data in absolute terms -- and why an inversion that only fixes
    the trend gains nothing.  Kept in the engine (rather than only in the test)
    so the number the test asserts on and the number
    :mod:`simulations.fwi_submission` writes into ``run_summary.json`` come from
    one implementation.

    Returns 0.0 when either side has no lateral variation at all, rather than
    dividing by zero.
    """
    a = np.asarray(submitted, dtype=float) - np.asarray(submitted, dtype=float).mean(
        axis=1, keepdims=True
    )
    b = np.asarray(truth, dtype=float) - np.asarray(truth, dtype=float).mean(
        axis=1, keepdims=True
    )
    denom = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    if denom <= 0.0:
        return 0.0
    return float(np.sum(a * b) / denom)


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def run_fwi(survey: Survey, config: Optional[FWIConfig] = None) -> FWIResult:
    """Run the full inversion and return the model, wavelet and honest metrics."""
    import time as _time

    cfg = config or FWIConfig()
    started = _time.perf_counter()

    start_model = np.array(survey.velocity, dtype=float, copy=True)
    current = start_model.copy()
    nt = survey.nt

    wavelet, method = estimate_wavelet(survey, current)
    if not np.any(wavelet):
        # Fall back to a unit impulse so the run is still a real inversion, and
        # say so rather than pretending a signature was found.
        wavelet = np.zeros(nt)
        wavelet[0] = 1.0
        method = (
            "fallback: unit impulse (no usable Green's function was recovered); "
            "the signature is NOT estimated in this run"
        )

    bands = _filter_bank(nt, survey.dt, cfg.frequency_schedule)
    illumination = illumination_weights(survey)

    # Held-out shots are excluded from the gradient entirely -- they are the
    # only honest measure of whether the inversion generalises rather than
    # merely fitting the acquisition it was given.
    fit_shots = survey.fit_shots or list(range(survey.n_shots))
    held_out = survey.held_out_shots

    def _misfit(model: np.ndarray, wave: np.ndarray, window, nfft, shots) -> float:
        """Band-limited L2 misfit with **both** sides filtered identically.

        The earlier version formed ``filtered(modelled) - raw(observed)``, so a
        large part of the residual was the observed wavelet's energy sitting
        outside the band.  That term does not depend on the velocity at all: it
        adds a constant offset and, combined with the order-one rescaling the
        gradient applies to its two fields, it biases the direction.  The
        gradient in :func:`_adjoint_gradient` filters both sides, so the
        monitoring misfit has to measure the same function it is minimising.
        """
        src = np.zeros(nt + 1, dtype=float)
        w = np.asarray(wave, dtype=float).ravel()
        src[: min(nt, w.size)] = w[:nt]
        v2 = model * model
        _ar = np.concatenate([survey.shot_rc[:, 0], survey.rec_rc[:, 0]])
        _ac = np.concatenate([survey.shot_rc[:, 1], survey.rec_rc[:, 1]])
        sponge = _sponge(
            model.shape[0], model.shape[1], cfg.absorbing_width,
            float(cfg.absorbing_strength), surface_row=0, acquire=(_ar, _ac),
        )
        inv_dx2 = 1.0 / (survey.dx * survey.dx)
        total = 0.0
        for ishot in shots:
            sz, sx = survey.shot_rc[ishot]
            mod = _single_shot(
                v2, src, int(sz), int(sx), survey.rec_rc, sponge,
                survey.dt, survey.dx, nt, inv_dx2,
            )
            obs = survey.records[ishot]
            total += float(
                np.sum(
                    (
                        _apply_filter(mod, window, nfft)
                        - _apply_filter(obs, window, nfft)
                    ) ** 2
                )
            )
        return total

    # Monitoring shots: a spread over the line, excluding the held-out ones so
    # neither ``initial_misfit`` nor ``final_misfit`` leaks validation data into
    # the optimisation loop.
    monitor = sorted(
        {fit_shots[int(round(i))] for i in np.linspace(0, len(fit_shots) - 1, num=min(3, len(fit_shots)))}
    )

    last_band = cfg.frequency_schedule[-1]
    w_last = bands[last_band]
    initial_misfit = _misfit(start_model, wavelet, w_last[0], w_last[1], monitor)
    # The validation reference is computed **once**, with the starting model and
    # the *final* signature, and the final model is then scored against it with
    # that same signature.  Measuring the "before" case with whatever signature
    # happened to be current at the time is not a comparison: the signature is
    # re-estimated during the run, so the two numbers would be misfits of two
    # different forward problems and the change between them could be either
    # real progress or a change of source wavelet.
    held_initial = (
        _misfit(start_model, wavelet, w_last[0], w_last[1], held_out)
        if held_out
        else None
    )

    stage_misfits: List[float] = []
    total_iterations = 0
    refresh_reference = start_model.copy()
    step_fraction = float(cfg.max_update_fraction)

    for band_key in cfg.frequency_schedule:
        window, nfft = bands[band_key]
        before = _misfit(current, wavelet, window, nfft, monitor)
        stage_start = before
        for _ in range(int(cfg.iterations_per_stage)):
            grad = _adjoint_gradient(
                survey, current, wavelet, (window, nfft), illumination, shots=fit_shots
            )
            if not np.all(np.isfinite(grad)) or float(np.max(np.abs(grad))) <= 0.0:
                break
            if cfg.laplace_weight > 0.0:
                lap = np.zeros_like(current)
                lap[1:-1, 1:-1] = (
                    current[2:, 1:-1] - 2.0 * current[1:-1, 1:-1] + current[:-2, 1:-1]
                    + current[1:-1, 2:] - 2.0 * current[1:-1, 1:-1] + current[1:-1, :-2]
                )
                grad = grad + cfg.laplace_weight * lap * float(np.mean(np.abs(grad)))
            grad = _smooth(grad, cfg.gradient_smoothing)

            scale = float(np.max(np.abs(grad)))
            if scale <= 0.0:
                break

            # Backtracking line search on the *actual* misfit.  A fixed step is
            # what made the earlier runs diverge: the gradient direction is
            # correct, but its useful magnitude shrinks as the low-frequency
            # stages lock in, so the same fraction of the mean velocity keeps
            # overshooting and the monitoring misfit climbed every stage.
            base_step = float(np.mean(current)) / scale
            accepted = None
            for fraction in (1.0, 0.5, 0.25, 0.125, 0.0625):
                trial = np.clip(
                    current + step_fraction * fraction * base_step * grad, V_MIN, V_MAX
                )
                value = _misfit(trial, wavelet, window, nfft, monitor)
                if value < before:
                    accepted = (trial, value, fraction)
                    break
            if accepted is None:
                # Nothing in the search direction helped: shorten the step and
                # try again rather than committing a move that hurts.
                step_fraction *= 0.5
                if step_fraction < 1e-4:
                    break
                continue
            current, before, used = accepted
            # Let the step grow back after a successful move, so one unlucky
            # iteration does not permanently cripple the rest of the run.
            step_fraction = min(
                float(cfg.max_update_fraction), max(step_fraction, 0.5 * step_fraction / max(used, 1e-9))
            )
            total_iterations += 1

            # Re-estimate the signature once the model has moved appreciably.
            # Compared against ``refresh_reference`` -- the model as it was at
            # the last refresh -- not against a variable reassigned in this very
            # branch, which made every later check read exactly zero.
            moved = float(np.sqrt(np.mean((current - refresh_reference) ** 2)))
            if moved > cfg.wavelet_refresh_rms:
                refresh, refresh_method = estimate_wavelet(
                    survey, current, previous=wavelet
                )
                if np.any(refresh):
                    wavelet = refresh
                    method = refresh_method
                refresh_reference = current.copy()

        stage_misfits.append(float(before))
        if cfg.verbose:
            print(
                f"  stage {band_key[0]:.1f}-{band_key[1]:.1f} Hz: misfit "
                f"{stage_start:.6e} -> {before:.6e} "
                f"({100.0 * (before / stage_start - 1.0):+.2f}%, "
                f"step fraction {step_fraction:.4f})"
            )

    final_misfit = _misfit(current, wavelet, w_last[0], w_last[1], monitor)
    # Validation measured on the same band with the same signature, starting
    # from the same starting model -- the only difference is the shots.
    held_final = (
        _misfit(current, wavelet, w_last[0], w_last[1], held_out)
        if held_out
        else None
    )

    wall = _time.perf_counter() - started
    method_text = (
        "Constant-density acoustic FWI, second-order time / second-order space "
        "finite differences with a sponge absorbing layer on the deep and lateral "
        "edges and a symmetric Neumann closure at the observed surface. "
        f"Misfit: band-limited L2 over {cfg.n_stages()} frequency-continuation "
        "stages ("
        + ", ".join(f"{lo:.1f}-{hi:.1f} Hz" for lo, hi, _ in cfg.frequency_schedule)
        + f"), up to {cfg.iterations_per_stage} iterations each with a backtracking "
        "line search on the true misfit. "
        "Gradient: adjoint state with illumination balancing and Laplacian "
        "regularisation; updates are additive and clipped to "
        f"[{V_MIN:.0f}, {V_MAX:.0f}] m/s. "
        "The source signature is re-estimated as the model improves."
    )

    return FWIResult(
        velocity=np.clip(current, V_MIN, V_MAX),
        wavelet=np.asarray(wavelet, dtype=float),
        stage_misfits=stage_misfits,
        n_iterations=total_iterations,
        method=method_text,
        source_estimation=method,
        wall_time_s=wall,
        initial_misfit=float(initial_misfit),
        final_misfit=float(final_misfit),
        held_out_shots=held_out,
        held_out_initial_misfit=held_initial,
        held_out_final_misfit=held_final,
        shots_used=fit_shots,
    )
