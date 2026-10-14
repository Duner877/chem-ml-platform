"""Materials characterisation simulators.

Classical models behind the instrument nodes that deal with solids rather than
isolated molecules:

===============================  ==============================================
``simulate_xrd``                 Bragg law + kinematic structure factor with
                                 Cromer-Mann style form-factor decay, Lorentz-
                                 polarisation factor and Scherrer broadening
``simulate_xps``                 core level binding energies + Shirley background
``simulate_xas``                 ``arctan`` edge step + EXAFS ``chi(k)`` + FT
``simulate_dsc``                 Cp baseline + glass transition + melting peak
``simulate_tga``                 multi step Arrhenius decomposition kinetics
``simulate_dma``                 storage modulus decay + tan delta peak
``simulate_cv``                  1-D finite difference diffusion with
                                 Butler-Volmer electrode kinetics
``simulate_eis``                 Randles equivalent circuit (+ Warburg)
``simulate_dls``                 cumulant analysis of ``g1(tau)``
``simulate_bet``                 BET isotherm + linear regression
``simulate_map``                 hyperspectral datacube + matched filter map
===============================  ==============================================

They are *models*, not measurements -- every node sets ``synthetic: True`` in
the metadata of its output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from workflow_engine.objects import Image, Peak, Spectrum
from workflow_engine.processing import ATOMIC_WEIGHTS, formula_mass, parse_formula

__all__ = [
    "simulate_xrd",
    "simulate_xps",
    "simulate_xas",
    "simulate_dsc",
    "simulate_tga",
    "simulate_dma",
    "simulate_cv",
    "simulate_eis",
    "simulate_dls",
    "simulate_bet",
    "simulate_map",
    "ATOMIC_FORM_FACTOR",
    "ELECTRON_CONFIGURATION",
]

_R = 8.314462618e-3  # kJ/(mol K)


# --------------------------------------------------------------------------- #
# X-ray diffraction
# --------------------------------------------------------------------------- #
def _metric_tensor(a: float, b: float, c: float, alpha: float, beta: float, gamma: float):
    """Reciprocal metric tensor of the unit cell."""
    alpha = math.radians(alpha)
    beta = math.radians(beta)
    gamma = math.radians(gamma)
    volume = (
        a
        * b
        * c
        * math.sqrt(
            1.0
            - math.cos(alpha) ** 2
            - math.cos(beta) ** 2
            - math.cos(gamma) ** 2
            + 2.0 * math.cos(alpha) * math.cos(beta) * math.cos(gamma)
        )
    )
    s11 = (b * c * math.sin(alpha)) ** 2 / volume**2
    s22 = (a * c * math.sin(beta)) ** 2 / volume**2
    s33 = (a * b * math.sin(gamma)) ** 2 / volume**2
    s12 = (a * b * c**2) * (math.cos(alpha) * math.cos(beta) - math.cos(gamma)) / volume**2
    s23 = (a**2 * b * c) * (math.cos(beta) * math.cos(gamma) - math.cos(alpha)) / volume**2
    s13 = (a * b**2 * c) * (math.cos(gamma) * math.cos(alpha) - math.cos(beta)) / volume**2
    return s11, s22, s33, s12, s23, s13


def _atomic_form_factor(element: str, s: float) -> float:
    """Approximate X-ray atomic form factor ``f(s)`` with ``s = sin(theta)/lambda``."""
    table = {
        "H": 1, "Li": 3, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9, "Na": 11,
        "Mg": 12, "Al": 13, "Si": 14, "P": 15, "S": 16, "Cl": 17, "K": 19,
        "Ca": 20, "Ti": 22, "Mn": 25, "Fe": 26, "Co": 27, "Ni": 28, "Cu": 29,
        "Zn": 30, "Se": 34, "Br": 35, "I": 53,
    }
    electrons = float(table.get(str(element).capitalize(), 6))
    # single Gaussian decay: smooth, monotonic, correct limiting values
    return electrons * math.exp(-2.0 * (s / 1.2) ** 2)


ATOMIC_FORM_FACTOR = _atomic_form_factor

#: Rough number of valence electrons per element (used for structure factors).
ELECTRON_CONFIGURATION: Dict[str, int] = {
    "H": 1, "Li": 3, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9, "Na": 11,
    "Mg": 12, "Al": 13, "Si": 14, "P": 15, "S": 16, "Cl": 17, "K": 19,
    "Ca": 20, "Ti": 22, "Mn": 25, "Fe": 26, "Co": 27, "Ni": 28, "Cu": 29,
    "Zn": 30, "Se": 34, "Br": 35, "I": 53,
}


def simulate_xrd(
    lattice: Optional[Dict[str, float]] = None,
    sites: Optional[Sequence[Dict[str, Any]]] = None,
    wavelength: float = 1.5406,
    two_theta_max: float = 90.0,
    points: int = 3600,
    crystallite_size_nm: float = 40.0,
    rng: np.random.Generator | None = None,
) -> Spectrum:
    """Simulate a powder XRD pattern for a crystal structure.

    ``lattice`` accepts ``{"a","b","c","alpha","beta","gamma"}`` (Å/deg).
    ``sites`` is a list of ``{"element", "frac": [x, y, z]}``.
    """
    rng = rng or np.random.default_rng(2027)
    cell = {
        "a": float((lattice or {}).get("a", 4.0)),
        "b": float((lattice or {}).get("b", 4.0)),
        "c": float((lattice or {}).get("c", 4.0)),
        "alpha": float((lattice or {}).get("alpha", 90.0)),
        "beta": float((lattice or {}).get("beta", 90.0)),
        "gamma": float((lattice or {}).get("gamma", 90.0)),
    }
    atoms = [
        {"element": str(site.get("element", "C")), "frac": [float(v) for v in site.get("frac", [0, 0, 0])]}
        for site in (sites or [])
    ]
    if not atoms:
        atoms = [{"element": "Si", "frac": [0.0, 0.0, 0.0]}]

    s11, s22, s33, s12, s23, s13 = _metric_tensor(
        cell["a"], cell["b"], cell["c"], cell["alpha"], cell["beta"], cell["gamma"]
    )

    grid = np.linspace(0.0, float(two_theta_max), int(points))
    intensity = np.zeros_like(grid)

    for h in range(-6, 7):
        for k in range(-6, 7):
            for l in range(-6, 7):
                if h == 0 and k == 0 and l == 0:
                    continue
                q_squared = (
                    h * h * s11
                    + k * k * s22
                    + l * l * s33
                    + 2.0 * h * k * s12
                    + 2.0 * k * l * s23
                    + 2.0 * h * l * s13
                )
                if q_squared <= 0:
                    continue
                d_spacing = 1.0 / math.sqrt(q_squared)
                if 2.0 * d_spacing < wavelength:
                    continue
                ratio = wavelength / (2.0 * d_spacing)
                two_theta = math.degrees(2.0 * math.asin(min(1.0, ratio)))
                if two_theta > two_theta_max:
                    continue
                structure_factor = 0.0 + 0.0j
                for atom in atoms:
                    # s = sin(theta)/lambda  with theta = 2theta/2
                    scattering = math.sin(math.radians(two_theta / 2.0)) / float(wavelength)
                    form = _atomic_form_factor(atom["element"], scattering)
                    phase = 2.0 * math.pi * (
                        h * atom["frac"][0] + k * atom["frac"][1] + l * atom["frac"][2]
                    )
                    structure_factor += form * np.exp(1j * phase)
                weight = float(abs(structure_factor) ** 2)
                if weight <= 0:
                    continue
                # Scherrer broadening -> FWHM in degrees
                fwhm = math.degrees(0.9 * wavelength / (max(1.0, crystallite_size_nm) * 10.0 * math.cos(math.radians(two_theta / 2.0))))
                sigma = max(0.05, fwhm / 2.3548)
                intensity += weight * np.exp(-0.5 * ((grid - two_theta) / sigma) ** 2)

    # Lorentz-polarisation factor
    theta = np.radians(np.maximum(grid, 0.01) / 2.0)
    lp = (1.0 + np.cos(2.0 * theta) ** 2) / (
        np.maximum(np.sin(theta), 1e-3) ** 2 * np.maximum(np.cos(theta), 1e-3)
    )
    intensity = intensity * lp
    if float(np.max(intensity)) > 0:
        intensity = intensity / float(np.max(intensity)) * 100.0

    peaks: List[Peak] = []
    for index in range(1, len(grid) - 1):
        if intensity[index] > intensity[index - 1] and intensity[index] >= intensity[index + 1]:
            if intensity[index] > 1.0:
                peaks.append(
                    Peak(
                        x=round(float(grid[index]), 3),
                        y=round(float(intensity[index]), 2),
                        intensity=round(float(intensity[index]), 2),
                    )
                )
    peaks.sort(key=lambda item: -item.y)

    return Spectrum(
        mode="XRD",
        technique="powder XRD",
        name="simulated powder pattern",
        x=[float(value) for value in grid],
        y=[float(value) for value in intensity],
        x_unit="2theta (deg)",
        y_unit="intensity",
        peaks=peaks[:40],
        metadata={
            "wavelength_angstrom": wavelength,
            "crystallite_size_nm": crystallite_size_nm,
            "cell": cell,
            "synthetic": True,
        },
    )


# --------------------------------------------------------------------------- #
# XPS / XAS
# --------------------------------------------------------------------------- #
def simulate_xps(
    composition: Sequence[Dict[str, Any]],
    energy_step: float = 0.1,
    noise: float = 0.01,
    seed: int = 41,
) -> Spectrum:
    """Simulate an XPS survey scan with a Shirley-type background."""
    from .spectra import XPS_BINDING_ENERGIES

    rng = np.random.default_rng(seed)
    grid = np.linspace(1200.0, 0.0, int(1200 / energy_step) + 1)
    signal = np.zeros_like(grid)
    peaks: List[Peak] = []
    for entry in composition or []:
        element = str(entry.get("element", "")).capitalize()
        fraction = float(entry.get("fraction", 0.0) or 0.0)
        levels = XPS_BINDING_ENERGIES.get(element)
        if not levels or fraction <= 0:
            continue
        for level, energy in levels.items():
            width = 0.9 + 0.02 * energy
            signal += fraction * 100.0 * np.exp(
                -0.5 * ((grid - energy) / width) ** 2
            )
            peaks.append(
                Peak(
                    x=round(float(energy), 2),
                    y=round(fraction * 100.0, 2),
                    intensity=round(fraction * 100.0, 2),
                    assignment=f"{element} {level}",
                )
            )
    # Shirley-like background: monotonically increasing towards high BE
    background = 1.0 + 0.02 * (1200.0 - grid)
    signal = signal + background
    if noise > 0:
        signal += np.abs(rng.normal(0.0, noise * float(np.max(signal)), signal.shape))
    return Spectrum(
        mode="XPS",
        technique="XPS survey",
        name="simulated XPS survey",
        x=[float(value) for value in grid],
        y=[float(value) for value in signal],
        x_unit="eV",
        y_unit="counts (a.u.)",
        peaks=sorted(peaks, key=lambda item: -item.y)[:30],
        metadata={"synthetic": True, "composition": list(composition or [])},
    )


def simulate_xas(
    element: str,
    edge: str = "K",
    oxidation_state: float = 0.0,
    noise: float = 0.004,
    seed: int = 43,
) -> Spectrum:
    """Simulate a XANES/EXAFS scan for ``element``."""
    from .spectra import XAS_K_EDGES

    rng = np.random.default_rng(seed)
    energy_edge = float(XAS_K_EDGES.get(str(element).capitalize(), 500.0))
    if str(edge).upper().startswith("L"):
        energy_edge *= 0.12
    energy_edge += 1.6 * float(oxidation_state)

    grid = np.linspace(energy_edge - 50.0, energy_edge + 300.0, 900)
    step = 0.5 + (1.0 / math.pi) * np.arctan(0.5 * (grid - energy_edge))
    excess = np.maximum(grid - energy_edge, 0.0)
    k = np.sqrt(0.2625 * excess)
    oscillation = (
        np.exp(-0.02 * k**2) * np.sin(2.0 * k * 2.0 + 0.4) / np.maximum(k, 0.5)
    )
    white_line = 0.5 * np.exp(-0.5 * ((grid - (energy_edge + 5.0)) / 8.0) ** 2)
    signal = step + white_line + 0.3 * oscillation * (excess > 0.0)
    if noise > 0:
        signal += rng.normal(0.0, noise, signal.shape)

    peaks = [
        Peak(
            x=round(float(energy_edge + 5.0), 2),
            y=1.0,
            intensity=1.0,
            assignment=f"{str(element).capitalize()} {edge}-edge white line",
        )
    ]
    return Spectrum(
        mode="XAS",
        technique=f"{edge}-edge XANES",
        name=f"simulated {element} {edge}-edge",
        x=[float(value) for value in grid],
        y=[float(value) for value in signal],
        x_unit="eV",
        y_unit="normalized mu(E)",
        peaks=peaks,
        metadata={
            "synthetic": True,
            "element": str(element).capitalize(),
            "edge": edge,
            "oxidation_state": oxidation_state,
        },
    )


# --------------------------------------------------------------------------- #
# Thermal analysis
# --------------------------------------------------------------------------- #
def simulate_dsc(
    mass_mg: float = 5.0,
    heat_capacity: float = 1.2,
    glass_transition_c: float = 120.0,
    melting_point_c: float = 220.0,
    melting_enthalpy: float = 90.0,
    rate_c_per_min: float = 10.0,
    t_min: float = 25.0,
    t_max: float = 350.0,
    points: int = 700,
) -> Spectrum:
    """Simulate a DSC heating scan (mW)."""
    grid = np.linspace(float(t_min), float(t_max), int(points))
    # heat flow = m * cp * beta  (J/g/K * mg * K/min -> mW)
    baseline = float(mass_mg) * float(heat_capacity) * float(rate_c_per_min) / 60.0
    heat_flow = np.full_like(grid, baseline)

    # glass transition: sigmoidal step of cp
    delta_cp = 0.35 * float(heat_capacity) * float(mass_mg) * float(rate_c_per_min) / 60.0
    heat_flow += delta_cp / (1.0 + np.exp(-(grid - float(glass_transition_c)) / 8.0))

    # melting endotherm
    width = 12.0
    amplitude = float(mass_mg) * float(melting_enthalpy) * float(rate_c_per_min) / (
    60.0 * width * math.sqrt(2.0 * math.pi)
    )
    heat_flow += amplitude * np.exp(
        -0.5 * ((grid - float(melting_point_c)) / width) ** 2
    )
    return Spectrum(
        mode="DSC",
        technique="DSC",
        name="simulated DSC heating scan",
        x=[float(value) for value in grid],
        y=[float(value) for value in heat_flow],
        x_unit="degC",
        y_unit="mW",
        peaks=[
            Peak(
                x=float(glass_transition_c),
                y=float(baseline),
                intensity=float(baseline),
                width=8.0,
                area=0.0,
                label="Tg",
                assignment="Tg (onset step)",
            ),
            Peak(
                x=float(melting_point_c),
                y=float(amplitude),
                intensity=float(amplitude),
                width=float(width),
                area=0.0,
                label="Tm",
                assignment="Tm (melting)",
            ),
        ],
        metadata={"synthetic": True, "rate_c_per_min": rate_c_per_min},
    )


def simulate_tga(
    steps: Optional[Sequence[Dict[str, float]]] = None,
    rate_c_per_min: float = 10.0,
    t_min: float = 25.0,
    t_max: float = 800.0,
    points: int = 900,
) -> Spectrum:
    """Simulate a TGA curve from a list of decomposition steps.

    Each step is ``{"onset": T_onset, "mass_loss": percent, "Ea": kJ/mol,
    "A": pre-exponential (1/min)}``; the conversion follows the integral
    Arrhenius form ``alpha = 1 - exp(-(A/beta) ∫ exp(-Ea/RT) dT)``.
    """
    grid = np.linspace(float(t_min), float(t_max), int(points))
    mass = np.full_like(grid, 100.0)
    if not steps:
        steps = [
            {"onset": 120.0, "mass_loss": 5.0, "Ea": 70.0, "A": 1.0e7},
            {"onset": 380.0, "mass_loss": 45.0, "Ea": 160.0, "A": 1.0e11},
        ]
    for step in steps:
        onset = float(step.get("onset", 300.0))
        loss = float(step.get("mass_loss", 10.0))
        activation = float(step.get("Ea", 120.0))
        prefactor = float(step.get("A", 1.0e9))
        # temperature in kelvin, numerical integration of exp(-Ea/RT)
        kelvin = grid + 273.15
        exponent = np.exp(-activation / (_R * kelvin))
        integral = np.concatenate(
            ([0.0], np.cumsum(0.5 * (exponent[1:] + exponent[:-1]) * np.diff(kelvin)))
        )
        conversion = 1.0 - np.exp(-(prefactor / float(rate_c_per_min)) * integral)
        conversion = np.clip(conversion, 0.0, 1.0)
        mask = grid >= onset
        mass -= loss * conversion * mask
    return Spectrum(
        mode="TGA",
        technique="TGA",
        name="simulated TGA curve",
        x=[float(value) for value in grid],
        y=[float(value) for value in mass],
        x_unit="degC",
        y_unit="mass (%)",
        peaks=[],
        metadata={"synthetic": True, "steps": list(steps)},
    )


def simulate_dma(
    glassy_modulus_mpa: float = 2500.0,
    rubbery_modulus_mpa: float = 20.0,
    glass_transition_c: float = 110.0,
    width_c: float = 18.0,
    t_min: float = 0.0,
    t_max: float = 220.0,
    points: int = 500,
) -> Spectrum:
    """Simulate a DMA temperature sweep (storage modulus + tan delta)."""
    grid = np.linspace(float(t_min), float(t_max), int(points))
    transition = 1.0 / (1.0 + np.exp((grid - float(glass_transition_c)) / float(width_c)))
    storage = float(rubbery_modulus_mpa) + (
        float(glassy_modulus_mpa) - float(rubbery_modulus_mpa)
    ) * (1.0 - transition)
    tan_delta = 4.0 * transition * (1.0 - transition)
    return Spectrum(
        mode="DMA",
        technique="DMA temperature sweep",
        name="simulated DMA curve",
        x=[float(value) for value in grid],
        y=[float(value) for value in storage],
        x_unit="degC",
        y_unit="storage modulus (MPa)",
        peaks=[],
        metadata={"synthetic": True, "tan_delta": [float(v) for v in tan_delta]},
    )


# --------------------------------------------------------------------------- #
# Electrochemistry
# --------------------------------------------------------------------------- #
_F = 96485.332  # C/mol


def simulate_cv(
    e_start: float = -0.2,
    e_upper: float = 0.8,
    e_lower: float = -0.2,
    scan_rate_v_per_s: float = 0.1,
    area_cm2: float = 0.07,
    concentration_mol_per_cm3: float = 1.0e-5,
    diffusion_cm2_per_s: float = 1.0e-5,
    e0: float = 0.3,
    alpha: float = 0.5,
    k0: float = 0.01,
    n: int = 1,
    steps: int = 1200,
) -> Spectrum:
    """Simulate a cyclic voltammogram with an explicit diffusion model.

    The concentration profiles of the reduced (``C_R``) and oxidised
    (``C_O``) species are propagated with an explicit finite difference scheme
    on a 1-D semi-infinite grid; the flux at the electrode obeys
    Butler-Volmer kinetics.
    """
    grid_points = 200
    domain = 6.0 * math.sqrt(max(1e-12, diffusion_cm2_per_s) * 20.0)
    dx = domain / grid_points
    dt = min(0.4 * dx * dx / max(1e-12, diffusion_cm2_per_s), 1.0 / steps)

    c_reduced = np.ones(grid_points, dtype=float)
    c_oxidised = np.zeros(grid_points, dtype=float)

    # two linear sweeps: forward (start -> upper) and reverse (upper -> lower)
    potentials: List[float] = []
    currents: List[float] = []

    segments = [
        (float(e_start), float(e_upper)),
        (float(e_upper), float(e_lower)),
        (float(e_lower), float(e_start)),
    ]
    for start, end in segments:
        segment_steps = max(2, int(steps) // 3)
        for index in range(segment_steps):
            fraction = index / float(segment_steps)
            potential = start + (end - start) * fraction
            overpotential = float(n) * _F * (potential - float(e0)) / (8.314462618 * 298.15)
            k_oxidation = float(k0) * math.exp(float(alpha) * overpotential)
            k_reduction = float(k0) * math.exp(-(1.0 - float(alpha)) * overpotential)
            surface_reduced = c_reduced[0]
            surface_oxidised = c_oxidised[0]
            flux = k_oxidation * surface_reduced - k_reduction * surface_oxidised
            # diffusion update (explicit FTCS)
            interior = slice(1, grid_points - 1)
            c_reduced[interior] = c_reduced[interior] + (
                float(diffusion_cm2_per_s) * dt / (dx * dx)
            ) * (
                c_reduced[2:] - 2.0 * c_reduced[interior] + c_reduced[:-2]
            )
            c_oxidised[interior] = c_oxidised[interior] + (
                float(diffusion_cm2_per_s) * dt / (dx * dx)
            ) * (
                c_oxidised[2:] - 2.0 * c_oxidised[interior] + c_oxidised[:-2]
            )
            # electrochemical boundary condition
            c_reduced[0] = max(0.0, surface_reduced - flux * dt / dx)
            c_oxidised[0] = max(0.0, surface_oxidised + flux * dt / dx)
            potentials.append(float(potential))
            # i = n F A D (dC/dx)|_0   [A]
            gradient = (c_reduced[1] - c_reduced[0]) / dx
            currents.append(float(n) * _F * float(area_cm2) * float(diffusion_cm2_per_s) * gradient)

    order = np.argsort(potentials)
    return Spectrum(
        mode="CV",
        technique="cyclic voltammetry",
        name="simulated cyclic voltammogram",
        x=[float(potentials[i]) for i in order],
        y=[float(currents[i]) for i in order],
        x_unit="V",
        y_unit="A",
        peaks=[],
        metadata={"synthetic": True, "scan_rate_v_per_s": scan_rate_v_per_s},
    )


def simulate_eis(
    solution_resistance: float = 20.0,
    charge_transfer: float = 500.0,
    double_layer: float = 2.0e-5,
    warburg: float = 150.0,
    f_min: float = 1.0e-2,
    f_max: float = 1.0e6,
    points: int = 90,
) -> Spectrum:
    """Return the Nyquist plot of a Randles circuit (with Warburg element)."""
    frequencies = np.logspace(math.log10(f_min), math.log10(f_max), int(points))
    omega = 2.0 * math.pi * frequencies
    warburg_impedance = warburg * (1.0 - 1j) / np.sqrt(omega)
    faradaic = 1.0 / (
        1.0 / complex(charge_transfer, 0.0) + 1.0 / warburg_impedance
    )
    double_layer_impedance = 1.0 / (1j * omega * double_layer)
    parallel = 1.0 / (1.0 / faradaic + 1.0 / double_layer_impedance)
    total = complex(solution_resistance, 0.0) + parallel
    return Spectrum(
        mode="EIS",
        technique="electrochemical impedance spectroscopy",
        name="simulated Nyquist plot",
        x=[float(value) for value in total.real],
        y=[float(-value) for value in total.imag],
        x_unit="Zreal (ohm)",
        y_unit="-Zimag (ohm)",
        peaks=[],
        metadata={
            "synthetic": True,
            "circuit": "Randles + Warburg",
            "frequencies": [float(value) for value in frequencies],
        },
    )


# --------------------------------------------------------------------------- #
# Particle / surface analysis
# --------------------------------------------------------------------------- #
def simulate_dls(
    mean_diameter_nm: float = 120.0,
    polydispersity: float = 0.15,
    temperature_c: float = 25.0,
    viscosity_cp: float = 0.89,
    refractive_index: float = 1.33,
    wavelength_nm: float = 633.0,
    points: int = 160,
) -> Spectrum:
    """Simulate a DLS autocorrelation function and its cumulant fit.

    The field autocorrelation of a (log-normal) distribution of spheres is
    ``g1(tau) = exp(-Gamma tau)`` with ``Gamma = D q^2`` and
    ``D = k_B T / (3 pi eta d)`` (Stokes-Einstein).
    """
    rng = np.random.default_rng(51)
    kelvin = float(temperature_c) + 273.15
    boltzmann = 1.380649e-23
    viscosity = float(viscosity_cp) * 1.0e-3  # cP -> Pa s
    refractive = float(refractive_index)
    scattering_vector = (
        4.0 * math.pi * refractive / (float(wavelength_nm) * 1.0e-9)
    ) * math.sin(math.pi / 2.0)

    diameters = rng.lognormal(
        mean=math.log(max(1.0, float(mean_diameter_nm))),
        sigma=max(1e-3, float(polydispersity)),
        size=4000,
    )
    decay_rates = (
        boltzmann * kelvin * scattering_vector**2
    ) / (3.0 * math.pi * viscosity * diameters * 1.0e-9)
    tau = np.logspace(-6, 0, int(points))
    # g1(tau) = <exp(-Gamma tau)> averaged over the particle size distribution
    g1 = np.mean(np.exp(-decay_rates[:, None] * tau[None, :]), axis=0)
    maximum = float(np.max(g1)) if g1.size else 0.0
    if maximum > 0:
        g1 = g1 / maximum

    # cumulant fit: ln(g1) = -Gamma_bar * tau + mu2/2 * tau^2
    mask = g1 > 1e-3
    x_fit = tau[mask]
    y_fit = np.log(np.maximum(g1[mask], 1e-6))
    if x_fit.size >= 3:
        coefficients = np.polyfit(x_fit, y_fit, 2)
        gamma_bar = -float(coefficients[1])
        mu2 = 2.0 * float(coefficients[0])
    else:
        gamma_bar = float(np.mean(decay_rates))
        mu2 = 0.0
    pdi = mu2 / (gamma_bar**2) if gamma_bar > 0 else 0.0

    return Spectrum(
        mode="DLS",
        technique="dynamic light scattering",
        name="simulated autocorrelation",
        x=[float(value) for value in tau],
        y=[float(value) for value in g1],
        x_unit="s",
        y_unit="g1(tau)",
        peaks=[],
        metadata={
            "synthetic": True,
            "gamma_bar_per_s": gamma_bar,
            "pdi": round(float(pdi), 4),
            "z_average_nm": round(
                float(boltzmann * kelvin * scattering_vector**2)
                / (3.0 * math.pi * viscosity * max(1e-12, gamma_bar))
                * 1e9,
                2,
            ),
            "temperature_c": temperature_c,
        },
    )


def simulate_bet(
    specific_surface_area: float = 120.0,
    monolayer_capacity: float = 25.0,
    c_constant: float = 120.0,
    points: int = 60,
) -> Spectrum:
    """Simulate an N2 adsorption isotherm and fit the BET equation.

    The BET relation ``1/(V((P0/P)-1))`` vs ``P/P0`` is linear in the
    0.05-0.30 range; the slope/intercept give the monolayer capacity and the
    specific surface area using 0.162 nm² per N2 molecule.
    """
    relative_pressure = np.linspace(0.01, 0.99, int(points))
    bet_c = max(1.0, float(c_constant))
    volume = (
        float(monolayer_capacity)
        * bet_c
        * relative_pressure
        / ((1.0 - relative_pressure) * (1.0 + (bet_c - 1.0) * relative_pressure))
    )
    # linear BET transform in the recommended range
    mask = (relative_pressure >= 0.05) & (relative_pressure <= 0.30)
    if int(np.sum(mask)) >= 2:
        x = relative_pressure[mask]
        y = 1.0 / np.maximum(
            volume[mask] * (1.0 / np.maximum(x, 1e-9) - 1.0), 1e-12
        )
        slope, intercept = np.polyfit(x, y, 1)
        if abs(slope + intercept) > 1e-12:
            v_mono_fit = 1.0 / (slope + intercept)
        else:
            v_mono_fit = float(monolayer_capacity)
    else:
        v_mono_fit = float(monolayer_capacity)

    # 1 cm3(STP) N2 = 4.354e-7 mol ; 1 mol = 6.022e23 molecules ; 0.162 nm^2 each
    area_fit = v_mono_fit * 4.354e-7 * 6.022e23 * 0.162e-18  # m^2 per gram
    return Spectrum(
        mode="BET",
        technique="N2 physisorption (BET)",
        name="simulated isotherm",
        x=[float(value) for value in relative_pressure],
        y=[float(value) for value in volume],
        x_unit="P/P0",
        y_unit="cm3(STP)/g",
        peaks=[],
        metadata={
            "synthetic": True,
            "monolayer_capacity_cm3_g": round(float(v_mono_fit), 3),
            "bet_surface_area_m2_g": round(float(area_fit), 2),
            "c_constant": round(float(bet_c), 1),
        },
    )


def fit_bet(relative_pressure: Sequence[float], volume: Sequence[float]) -> Dict[str, float]:
    """Linear BET regression used by :func:`simulate_bet` and the BET node."""
    x = np.asarray(relative_pressure, dtype=float)
    y = np.asarray(volume, dtype=float)
    mask = (x > 0.0) & (x < 1.0) & (y > 0.0)
    if int(np.sum(mask)) < 2:
        return {"slope": 0.0, "intercept": 0.0, "monolayer_capacity": 0.0,
            "surface_area_m2_g": 0.0, "c_constant": 0.0}
    transform = 1.0 / (y[mask] * (1.0 / x[mask] - 1.0))
    slope, intercept = np.polyfit(x[mask], transform, 1)
    denominator = slope + intercept
    monolayer = 1.0 / denominator if abs(denominator) > 1e-12 else 0.0
    surface_area = monolayer * 4.354e-7 * 6.022e23 * 0.162e-18
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "monolayer_capacity": float(monolayer),
        "surface_area_m2_g": float(surface_area),
        "c_constant": float(slope / intercept + 1.0) if abs(intercept) > 1e-12 else 0.0,
    }


def simulate_map(
    kind: str = "raman",
    size: int = 64,
    phases: int = 2,
    seed: int = 61,
) -> Tuple[Image, Spectrum]:
    """Build a hyperspectral datacube and return ``(map_image, mean_spectrum)``."""
    rng = np.random.default_rng(seed)
    grid = np.linspace(0.0, 1.0, int(size))
    x, y = np.meshgrid(grid, grid)
    abundance = np.zeros((int(size), int(size), max(1, int(phases))))
    for index in range(max(1, int(phases))):
        centre_x = 0.25 + 0.5 * (index / max(1, phases - 1)) if phases > 1 else 0.5
        centre_y = 0.3 + 0.4 * (index / max(1, phases - 1)) if phases > 1 else 0.5
        distance = np.sqrt((x - centre_x) ** 2 + (y - centre_y) ** 2)
        abundance[..., index] = np.exp(-(distance**2) / 0.03)
    total = np.sum(abundance, axis=2, keepdims=True)
    abundance = abundance / np.maximum(total, 1e-9)

    channels = np.linspace(200.0, 2000.0, 120)
    endmembers = []
    for index in range(max(1, int(phases))):
        centre = 400.0 + 500.0 * index
        endmembers.append(
            np.exp(-0.5 * ((channels - centre) / 90.0) ** 2)
            + 0.4 * np.exp(-0.5 * ((channels - centre - 320.0) / 120.0) ** 2)
        )
    cube = np.tensordot(abundance, np.vstack(endmembers), axes=([2], [0]))
    cube += rng.normal(0.0, 0.01, cube.shape)

    mean_spectrum = np.mean(cube, axis=(0, 1))
    dominant = np.argmax(abundance, axis=2)
    image = Image.from_array(
        dominant.astype(float) / max(1.0, float(phases - 1)),
        pixel_size=1.0,
        pixel_unit="px",
        name=f"{kind} chemical map",
        metadata={"phases": int(phases), "synthetic": True},
    )
    spectrum = Spectrum(
        mode=kind.capitalize(),
        technique=f"{kind} imaging",
        name=f"{kind} mean spectrum",
        x=[float(value) for value in channels],
        y=[float(value) for value in mean_spectrum],
        x_unit="cm-1" if kind in {"raman", "ftir"} else "nm",
        y_unit="intensity",
        metadata={"synthetic": True, "cube_shape": list(cube.shape)},
    )
    return image, spectrum
