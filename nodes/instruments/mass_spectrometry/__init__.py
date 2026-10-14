"""Mass spectrometry node family, re-organised per the v0.5.3 specification.

The specification asks for a dedicated ``mass_spectrometry`` package holding
``lcms`` / ``gcms`` / ``maldi`` / ``icpms`` plus a ``parsers`` sub-package.
The node classes themselves already exist in :mod:`nodes.instruments.ms` and
are re-exported here, so nothing is duplicated or deleted -- the package adds
the missing half of the pipeline::

    Instrument -> Parser -> Vendor Adapter -> Scientific Object -> Feature Extraction

* :class:`VendorSpectrumNode` reads a *raw* vendor file (SPC, Bruker ``.d``,
  Thermo / Waters / Agilent folders) through the data layer and returns the
  universal Spectrum object.
* :class:`ProfileCentroidNode` turns a profile spectrum into its centroided
  peak list, which is the operation a spectrometrist performs before any
  identification step.

Both nodes are registered, so they appear in the catalogue next to the four
virtual instruments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Peak, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes._helpers import peaks_to_table
from nodes.instruments._base import InstrumentNode, find_spectrum, sample_items
from nodes.instruments.ms import (  # re-exported: no functionality is removed
    GCMSNode,
    ICPMSNode,
    LCMSNode,
    MALDINode,
    MassSpectrometryNode,
)
from nodes.instruments.vendor_adapters import (
    centroid,
    extract_features,
    features_to_table,
)

__all__ = [
    "MassSpectrometryNode",
    "LCMSNode",
    "GCMSNode",
    "MALDINode",
    "ICPMSNode",
    "VendorSpectrumNode",
    "ProfileCentroidNode",
]


@register_node
class VendorSpectrumNode(InstrumentNode):
    """Read a raw instrument file of any supported vendor into a Spectrum.

    The node is the workflow-visible entry point of the data layer: it routes
    the path through the vendor adapter that owns the container, so a Bruker
    experiment folder, a Shimadzu SPC export or an open mzML file all arrive
    as the same scientific object.  The vendor, the format and the engine that
    decoded the file are recorded in the object metadata, which keeps the
    provenance auditable.
    """

    name = "Load Vendor Spectrum"
    category = "IO"
    description = (
        "读取厂商原始数据（Bruker .d / 1r、Shimadzu SPC/QGD/LCD、Thermo/Waters/Agilent "
        "文件夹）或开放格式（mzML/mzXML/MGF/MSP/JCAMP-DX/XY），返回统一的 Spectrum 对象。"
    )
    version = "0.7.1"
    tags = ["io", "vendor", "thermo", "waters", "agilent", "bruker", "shimadzu", "spc", "mzml"]
    icon = "VS"

    input_ports: List[Port] = []
    output_ports = [
        Port("spectrum", "Spectrum", "厂商适配器解码后的谱图"),
        Port("table", "Table", "特征提取结果表"),
        Port("text", "Text", "数据来源与 provenance 说明"),
    ]

    parameters = [
        ParameterSpec(
            "path", "file", "", "原始数据路径（文件或 .d / .raw 文件夹）", unit="path"
        ),
        ParameterSpec("index", "integer", 0, "读取第几条数据（多数据集时）", min=0),
        ParameterSpec("name", "string", "", "对象名称（留空则用文件名）"),
        ParameterSpec("features", "boolean", True, "输出特征提取表"),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Spectrum:
        from data_layer import ingest
        from data_layer.registry import registry as data_registry

        raw = str(self.get_param("path", "") or "").strip()
        if not raw:
            from workflow_engine.errors import NodeInputError

            raise NodeInputError("VendorSpectrumNode: parameter 'path' is empty")
        path = Path(raw)
        if not path.exists():
            candidate = Path(__file__).resolve().parents[2] / raw
            if candidate.exists():
                path = candidate
            else:
                raise FileNotFoundError(f"VendorSpectrumNode: no such file: {raw}")

        # Importing the vendor adapters registers them in the data layer.
        from nodes.instruments import vendor_adapters  # noqa: F401

        adapter = data_registry.adapter_for(path)
        objects = data_registry.ingest(path)
        if not objects:
            reason = data_registry.explain(path)
            raise NodeInputError(f"VendorSpectrumNode: cannot read {raw} ({reason})")

        index = max(0, min(int(self.get_param("index", 0) or 0), len(objects) - 1))
        obj = objects[index]
        payload = obj.to_scientific_object()
        if not isinstance(payload, Spectrum):
            # The adapter could only report the container (e.g. a Thermo RAW
            # folder).  That is still useful provenance, so surface it.
            self.log(
                f"{path.name}: {adapter.name if adapter else 'no adapter'} reported "
                "metadata only -- export the acquisition to mzML / JCAMP-DX "
                "to load the spectral payload."
            )
            raise NodeInputError(
                f"VendorSpectrumNode: {path.name} is a proprietary container; "
                "no spectrum could be decoded. Export to mzML / SPC / JCAMP-DX."
            )

        spectrum = payload
        if not spectrum.name:
            spectrum.name = str(self.get_param("name") or path.stem)
        else:
            spectrum.name = str(self.get_param("name"))
        spectrum.metadata.setdefault("source_file", str(path))
        spectrum.metadata["vendor_adapter"] = adapter.name if adapter else "generic"
        spectrum.metadata["data_id"] = obj.id
        self.log(
            f"loaded {path.name} via {adapter.name if adapter else 'generic'}: "
            f"{spectrum.summary()}"
        )
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        features = self._features(spectrum)
        table = peaks_to_table(spectrum, limit=40, name="vendor spectrum peaks")
        vendor = str(spectrum.metadata.get("vendor", "") or "generic")
        adapter = str(spectrum.metadata.get("vendor_adapter", "") or "generic")
        lines = [
            f"File         : {spectrum.metadata.get('source_file', '')}",
            f"Vendor       : {vendor}",
            f"Adapter      : {adapter}",
            f"Technique    : {spectrum.technique or spectrum.mode}",
            f"Data points  : {spectrum.size}",
            f"Peaks        : {len(spectrum.peaks)}",
        ]
        if spectrum.x:
            lines.append(
                f"Axis         : {spectrum.x[0]:.4f} .. {spectrum.x[-1]:.4f} "
                f"{spectrum.x_unit}"
            )
        if spectrum.peaks:
            base = spectrum.max_peak()
            lines.append(f"Base peak    : {base.x:.4f} {spectrum.x_unit}")
        return {
            "table": table,
            "text": Text(name="vendor spectrum", text="\n".join(lines)),
            "features": features,
        }

    def _features(self, spectrum: Spectrum) -> Table:
        from nodes.instruments.vendor_adapters import extract_features, features_to_table

        return features_to_table(
            extract_features(spectrum), name="extracted features"
        )


#: Y-axis units whose bands are dips rather than peaks.
_DOWNWARD_UNITS = ("transmittance", "reflectance", "log(1/r)", "log(1/r)")


def _bands_point_down(spectrum: Spectrum) -> bool:
    """True when the spectrum's bands point *down* (transmittance / reflectance).

    A peak picker looks for maxima by definition, so these spectra must be
    inverted first -- otherwise the "peaks" it reports are the flat parts of
    the baseline, which is exactly what a spectroscopist would call wrong.
    """
    unit = str(getattr(spectrum, "y_unit", "") or "").lower()
    return any(token in unit for token in _DOWNWARD_UNITS)


@register_node
class ProfileCentroidNode(InstrumentNode):
    """Convert a profile spectrum into its centroided peak list.

    Profile mode stores every detector sample; centroid mode stores one
    intensity weighted position per peak.  Every downstream identification
    step (library search, formula assignment, isotope modelling) expects the
    centroided form, which is what this node produces.
    """

    name = "Profile to Centroid"
    category = "Analysis"
    description = (
        "把连续谱（profile）转换为峰列表（centroid）：每个峰用半高宽内的强度加权位置表示，"
        "并输出峰面积与相对强度。"
    )
    version = "0.7.1"
    tags = ["analysis", "ms", "centroid", "profile", "peak"]
    icon = "PC"

    input_ports = [
        Port("sample", "Any", "上游谱图", optional=True, multi=True)
    ]
    output_ports = [
        Port("spectrum", "Spectrum", "仅含 centroid 峰的谱图"),
        Port("table", "Table", "峰表（位置 / 强度 / 面积 / 相对%）"),
        Port("text", "Text", "转换摘要"),
    ]

    parameters = [
        ParameterSpec(
            "min_height", "number", 0.02, "最小相对峰高", min=0.0, max=1.0, step=0.001
        ),
        ParameterSpec("merge_width", "number", 0.0, "合并间距（x 单位，0 = 自动）"),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Spectrum:
        from nodes.instruments._base import find_spectrum, sample_items

        source = find_spectrum(sample_items(inputs))
        if source is None:
            from workflow_engine.errors import NodeInputError

            raise NodeInputError(
                "ProfileCentroidNode: connect a spectrum to the 'sample' port"
            )
        width = float(self.get_param("merge_width", 0.0) or 0.0)
        if width <= 0 and source.x and len(source.x) > 1:
            width = abs(float(source.x[1]) - float(source.x[0]))
        min_height = float(self.get_param("min_height", 0.02) or 0.02)
        peaks = centroid(
            source.x,
            source.y,
            width=width,
            invert=_bands_point_down(source),
            height=min_height,
            prominence=min_height,
        )
        from workflow_engine.objects import Peak

        base = max((peak["y"] for peak in peaks), default=0.0) or 1.0
        spectrum = Spectrum(
            mode=source.mode,
            technique=source.technique,
            name=f"{source.name} (centroided)" if source.name else "centroided spectrum",
            x=[round(peak["x"], 4) for peak in peaks],
            y=[round(peak["y"], 4) for peak in peaks],
            x_unit=source.x_unit,
            y_unit=source.y_unit,
            peaks=[
                Peak(
                    x=round(peak["x"], 4),
                    y=round(peak["y"], 4),
                    intensity=round(peak["y"], 4),
                    area=round(peak["area"], 4),
                    relative=round(peak["y"] / base * 100.0, 2),
                    label="",
                )
                for peak in peaks
            ],
            metadata=dict(source.metadata),
        )
        spectrum.metadata["centroided_from"] = "profile"
        spectrum.metadata["centroid_peaks"] = len(peaks)
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        from workflow_engine.objects import Peak  # noqa: F401

        base = max((float(peak.y) for peak in spectrum.peaks), default=0.0) or 1.0
        rows = [
            [
                round(float(peak.x), 4),
                round(float(peak.y), 4),
                round(float(peak.area or 0.0), 4),
                round(float(peak.y) / base * 100.0, 2),
            ]
            for peak in spectrum.peaks[:100]
        ]
        table = Table(
            name="centroided peaks",
            columns=["position", "intensity", "area", "relative %"],
            rows=rows,
        )
        lines = [
            f"Profile points -> {len(spectrum.peaks)} centroids",
            f"Base peak      : {max(spectrum.peaks, key=lambda p: p.y).x if spectrum.peaks else 0:.4f}",
        ]
        return {"table": table, "text": Text(name="centroid", text="\n".join(lines))}

