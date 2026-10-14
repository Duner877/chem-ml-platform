"""Input / output nodes.

``nodes/io`` bridges the workflow graph and the file system.  Every importer
returns a :class:`~workflow_engine.objects.ScientificObject` (never a raw path)
so that downstream nodes stay file-format agnostic, and ``ExportNode`` writes
objects back to disk inside the run artefact folder.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List

from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Image, Molecule, ScientificObject, Spectrum, Table, Text
from workflow_engine.parsers import SUPPORTED_EXTENSIONS, load_spectra
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes._helpers import (
    build_material,
    build_molecule,
    collect,
    materialise,
    write_artifact,
)

__all__ = [
    "SpectrumFileNode",
    "TableFileNode",
    "ImageFileNode",
    "MoleculeInputNode",
    "MaterialInputNode",
    "TextInputNode",
    "ExportNode",
]

MODES = ["Generic", "MS", "NMR", "IR", "Raman", "UV-Vis", "XRD", "XPS", "XAS"]


# --------------------------------------------------------------------------- #
# Importers
# --------------------------------------------------------------------------- #
@register_node
class SpectrumFileNode(ScientificNode):
    """Read a spectrum from mzML / mzXML / MGF / MSP / JCAMP-DX / XY / Bruker."""

    name = "Load Spectrum"
    category = "IO"
    description = (
        "读取 mzML、mzXML、MGF、MSP、JCAMP-DX、XY 或 Bruker 目录中的谱图，"
        "返回统一的 Spectrum 科学对象。"
    )
    tags = ["io", "spectrum", "mzml", "mgf", "jcamp"]
    icon = "LS"

    input_ports: List[Port] = []
    output_ports = [Port("spectrum", "Spectrum", "解析后的谱图对象")]

    parameters = [
        ParameterSpec(
            "path", "file", "", "谱图文件路径（相对仓库根目录亦可）", unit="path"
        ),
        ParameterSpec(
            "mode", "enum", "Generic", "谱图类型标签", options=MODES
        ),
        ParameterSpec("index", "integer", 0, "读取第几条谱图", min=0),
        ParameterSpec("name", "string", "", "对象名称（留空则用文件名）"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        raw = str(self.get_param("path", "") or "").strip()
        if not raw:
            raise NodeInputError("SpectrumFileNode: parameter 'path' is empty")
        path = Path(raw)
        if not path.exists():
            candidate = Path(__file__).resolve().parents[1] / raw
            if candidate.exists():
                path = candidate
            else:
                raise FileNotFoundError(f"SpectrumFileNode: no such file: {raw}")

        mode = str(self.get_param("mode", "Generic"))
        index = int(self.get_param("index", 0) or 0)
        spectra = load_spectra(path, mode=mode)
        if not spectra:
            raise NodeInputError(f"SpectrumFileNode: no spectrum found in {path}")

        index = max(0, min(index, len(spectra) - 1))
        spectrum = spectra[index]
        if mode != "Generic":
            spectrum.mode = mode
        if not spectrum.name:
            spectrum.name = self.get_param("name") or path.stem
        if self.get_param("name"):
            spectrum.name = str(self.get_param("name"))
        spectrum.metadata.setdefault("source_file", str(path))
        spectrum.metadata.setdefault("spectrum_index", index)
        self.log(f"loaded {path.name}: {spectrum.summary()}")
        return {"spectrum": spectrum}


@register_node
class TableFileNode(ScientificNode):
    """Read a CSV / TSV file into a :class:`Table`."""

    name = "Load Table"
    category = "IO"
    description = "读取 CSV / TSV 表格文件，输出 Table 科学对象。"
    tags = ["io", "table", "csv"]
    icon = "LT"

    input_ports: List[Port] = []
    output_ports = [Port("table", "Table", "表格对象")]
    parameters = [
        ParameterSpec("path", "file", "", "CSV / TSV 文件路径", unit="path"),
        ParameterSpec("delimiter", "enum", "auto", "分隔符", options=["auto", ",", ";", "\t", "|"]),
        ParameterSpec("header", "boolean", True, "首行为表头"),
        ParameterSpec("name", "string", "", "表格名称"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        raw = str(self.get_param("path", "") or "").strip()
        if not raw:
            raise NodeInputError("TableFileNode: parameter 'path' is empty")
        path = Path(raw)
        if not path.exists():
            candidate = Path(__file__).resolve().parents[1] / raw
            if not candidate.exists():
                raise FileNotFoundError(f"TableFileNode: no such file: {raw}")
            path = candidate

        # ``utf-8-sig`` transparently strips a leading BOM, which would
        # otherwise corrupt the first column name ("﻿smiles").
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        delimiter = str(self.get_param("delimiter", "auto"))
        if delimiter == "auto":
            try:
                delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","

        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [row for row in reader if any(str(cell).strip() for cell in row)]
        if not rows:
            raise NodeInputError(f"TableFileNode: {path} is empty")

        if bool(self.get_param("header", True)):
            columns = [str(cell).strip() for cell in rows[0]]
            body = rows[1:]
        else:
            width = max(len(row) for row in rows)
            columns = [f"col_{i}" for i in range(width)]
            body = rows

        parsed: List[List[Any]] = []
        for row in body:
            cells: List[Any] = []
            for cell in row:
                value = str(cell).strip()
                try:
                    cells.append(float(value))
                except ValueError:
                    cells.append(value)
            parsed.append(cells)

        table = Table(
            name=str(self.get_param("name") or path.stem),
            columns=columns,
            rows=parsed,
            metadata={"source_file": str(path)},
        )
        self.log(f"loaded {path.name}: {table.summary()}")
        return {"table": table}


@register_node
class ImageFileNode(ScientificNode):
    """Read a microscopy image (PNG / TIFF / JPEG) into an Image object.

    Microscopy images enter the platform as real pixels, not as a file name:
    the node decodes the file, converts it to grayscale luminance and attaches
    the physical pixel size so downstream nodes can measure particle diameters
    in nanometres instead of pixels.

    Decoding prefers :mod:`PIL` when it is installed and falls back to a
    built-in reader for the PNG subset the instruments actually export
    (8 bit per channel, non-interlaced), so the node has no hard dependency.
    """

    name = "Load Image"
    category = "IO"
    description = (
        "读取 PNG / TIFF / JPEG 显微图像，转换为带物理像素尺寸的 Image 科学对象。"
    )
    tags = ["io", "image", "sem", "tem", "microscopy", "png"]
    icon = "LI"

    input_ports: List[Port] = []
    output_ports = [Port("image", "Image", "解码后的图像对象")]

    parameters = [
        ParameterSpec(
            "path", "file", "", "图像文件路径（相对仓库根目录亦可）", unit="path"
        ),
        ParameterSpec("pixel_size", "number", 1.0, "物理像素尺寸", min=1e-4),
        ParameterSpec("pixel_unit", "string", "nm", "像素尺寸单位"),
        ParameterSpec("name", "string", "", "对象名称（留空则用文件名）"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        raw = str(self.get_param("path", "") or "").strip()
        if not raw:
            raise NodeInputError("ImageFileNode: parameter 'path' is empty")
        path = Path(raw)
        if not path.exists():
            candidate = Path(__file__).resolve().parents[1] / raw
            if candidate.exists():
                path = candidate
            else:
                raise FileNotFoundError(f"ImageFileNode: no such file: {raw}")

        array, decoder = read_image_array(path)
        if array is None:
            raise NodeInputError(f"ImageFileNode: cannot decode {path}")

        image = Image.from_array(
            array,
            pixel_size=float(self.get_param("pixel_size", 1.0) or 1.0),
            pixel_unit=str(self.get_param("pixel_unit", "nm") or "nm"),
            name=str(self.get_param("name") or path.stem),
            metadata={"source_file": str(path), "decoder": decoder},
        )
        self.log(f"loaded {path.name}: {image.summary()} ({decoder})")
        return {"image": image}


def read_image_array(path: Path):
    """Decode ``path`` into a 2-D float array, or ``(None, reason)``.

    The first element is the array (``None`` when undecodable) and the second
    the name of the decoder that produced it.
    """
    # -- PIL first: it handles every real world container ------------------- #
    try:
        from PIL import Image as PILImage  # type: ignore

        with PILImage.open(path) as handle:
            grayscale = handle.convert("L")
            return (
                [[float(grayscale.getpixel((x, y))) for x in range(grayscale.width)]
                 for y in range(grayscale.height)],
                "PIL",
            )
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - a damaged file falls through to the
        # built-in reader only when PIL cannot make sense of it either.
        pass

    # -- built-in PNG reader (8 bit, non-interlaced) ------------------------ #
    array = _read_png(path)
    if array is not None:
        return array, "builtin-png"
    return None, "unsupported format"


@register_node
class MoleculeInputNode(ScientificNode):
    """Create a :class:`Molecule` from a SMILES string."""

    name = "Molecule Input"
    category = "IO"
    description = "由 SMILES 构建分子对象，自动计算分子式、精确质量与理化描述符。"
    tags = ["io", "molecule", "smiles"]
    icon = "MI"
    # v0.7.2 P0-05: known-answer verified -- ethanol resolves to C2H6O with
    # the monoisotopic mass 46.0419 and three heavy atoms.
    capability_status = "verified"
    execution_mode = "internal_approximation"
    validation_evidence = [
        "tests/test_v07_2_node_known_answers.py::TestMolecularFormulaKnownAnswer::test_ethanol_formula_and_exact_mass",
        "tests/test_v07_2_node_known_answers.py::TestMolecularFormulaKnownAnswer::test_heavy_atom_count_is_three",
    ]
    limitations = ["仅解析 SMILES；不处理立体化学歧义与互变异构。"]
    reproducibility_level = "deterministic"

    input_ports: List[Port] = []
    output_ports = [Port("molecule", "Molecule", "分子对象")]
    parameters = [
        ParameterSpec(
            "smiles",
            "text",
            "CN1C=NC2=C1C(=O)N(C)C(=O)N2C",
            "SMILES 结构式",
        ),
        ParameterSpec("name", "string", "", "分子名称"),
        ParameterSpec("compute_3d", "boolean", False, "生成三维坐标"),
        ParameterSpec("with_embedding", "boolean", True, "生成嵌入向量"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        molecule = build_molecule(
            str(self.get_param("smiles", "")),
            name=str(self.get_param("name") or ""),
            with_coords=bool(self.get_param("compute_3d", False)),
            with_embedding=bool(self.get_param("with_embedding", True)),
            source="MoleculeInputNode",
        )
        self.log(f"built {molecule.summary()}")
        return {"molecule": molecule}


@register_node
class MaterialInputNode(ScientificNode):
    """Create a :class:`Material` from a formula and unit cell parameters."""

    name = "Material Input"
    category = "IO"
    description = "由化学式与晶胞参数构建材料对象（用于电池 / 催化 / 半导体工作流）。"
    tags = ["io", "material", "crystal"]
    icon = "MT"

    input_ports: List[Port] = []
    output_ports = [Port("material", "Material", "材料对象")]
    parameters = [
        ParameterSpec("formula", "string", "LiFePO4", "化学式，如 LiFePO4"),
        ParameterSpec("name", "string", "", "材料名称"),
        ParameterSpec("a", "number", 0.0, "晶胞参数 a", unit="Å"),
        ParameterSpec("b", "number", 0.0, "晶胞参数 b", unit="Å"),
        ParameterSpec("c", "number", 0.0, "晶胞参数 c", unit="Å"),
        ParameterSpec("alpha", "number", 90.0, "晶胞角 α", unit="°"),
        ParameterSpec("beta", "number", 90.0, "晶胞角 β", unit="°"),
        ParameterSpec("gamma", "number", 90.0, "晶胞角 γ", unit="°"),
        ParameterSpec("spacegroup", "string", "P1", "空间群"),
        ParameterSpec("crystal_system", "string", "", "晶系"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        material = build_material(
            str(self.get_param("formula", "")),
            name=str(self.get_param("name") or ""),
            lattice={
                "a": float(self.get_param("a", 0.0) or 0.0),
                "b": float(self.get_param("b", 0.0) or 0.0),
                "c": float(self.get_param("c", 0.0) or 0.0),
                "alpha": float(self.get_param("alpha", 90.0) or 90.0),
                "beta": float(self.get_param("beta", 90.0) or 90.0),
                "gamma": float(self.get_param("gamma", 90.0) or 90.0),
            },
            spacegroup=str(self.get_param("spacegroup", "P1")),
            crystal_system=str(self.get_param("crystal_system", "")),
            source="MaterialInputNode",
        )
        self.log(f"built {material.summary()}")
        return {"material": material}


@register_node
class TextInputNode(ScientificNode):
    """Emit a free text payload (prompt, note, hypothesis, ...)."""

    name = "Text Input"
    category = "IO"
    description = "输出一段文本对象，可作为 LLM 节点的提示词或报告素材。"
    tags = ["io", "text", "prompt"]
    icon = "TI"

    input_ports: List[Port] = []
    output_ports = [Port("text", "Text", "文本对象")]
    parameters = [
        ParameterSpec("text", "text", "", "文本内容"),
        ParameterSpec("language", "enum", "en", "语言", options=["en", "zh"]),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        payload = Text(
            text=str(self.get_param("text", "") or ""),
            language=str(self.get_param("language", "en")),
            name="TextInput",
        )
        return {"text": payload}


# --------------------------------------------------------------------------- #
# Exporter
# --------------------------------------------------------------------------- #
@register_node
class ExportNode(ScientificNode):
    """Persist any scientific object into the run artefact folder."""

    name = "Export Result"
    category = "IO"
    description = "将任意科学对象导出为 JSON / CSV / PNG / Markdown / TXT 文件。"
    tags = ["io", "export", "artifact"]
    capabilities = ["writes_files"]
    icon = "EX"

    input_ports = [Port("data", "Any", "待导出的对象", optional=True, multi=True)]
    output_ports = [
        Port("text", "Text", "导出文件的路径与摘要"),
        Port("data", "Any", "透传的输入对象"),
    ]
    parameters = [
        ParameterSpec("filename", "string", "result", "文件名（不含扩展名）"),
        ParameterSpec(
            "format",
            "enum",
            "json",
            "导出格式",
            options=["json", "csv", "png", "md", "txt"],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        items = collect(inputs.get("data"))
        if not items:
            raise NodeInputError("ExportNode: nothing to export")

        fmt = str(self.get_param("format", "json")).lower()
        stem = str(self.get_param("filename", "result") or "result")
        from workflow_engine.utils import safe_filename

        stem = safe_filename(stem) or "result"
        written: List[str] = []

        for index, item in enumerate(items):
            suffix = f"_{index}" if len(items) > 1 else ""
            if fmt == "json":
                payload = (
                    item.to_dict()
                    if isinstance(item, ScientificObject)
                    else {"value": item}
                )
                target = write_artifact(
                    ctx, f"{stem}{suffix}.json", json.dumps(payload, indent=2, ensure_ascii=False)
                )
            elif fmt == "csv":
                table = item if isinstance(item, Table) else _as_table(item)
                target = write_artifact(ctx, f"{stem}{suffix}.csv", table.to_csv())
            elif fmt == "png":
                payload = _png_bytes(item)
                if payload is None:
                    target = write_artifact(
                        ctx,
                        f"{stem}{suffix}.txt",
                        f"PNG export is not available for {type(item).__name__}",
                    )
                else:
                    target = write_artifact(ctx, f"{stem}{suffix}.png", payload)
            elif fmt == "md":
                text = _as_markdown(item)
                target = write_artifact(ctx, f"{stem}{suffix}.md", text)
            else:
                text = _as_markdown(item) if isinstance(item, ScientificObject) else str(item)
                target = write_artifact(ctx, f"{stem}{suffix}.txt", text)
            written.append(target)

        summary = "\n".join(written)
        self.log(f"exported {len(written)} artefact(s)")
        return {
            "text": Text(
                name="export", text=summary, data={"paths": written, "format": fmt}
            ),
            "data": items[0] if len(items) == 1 else items,
        }


# --------------------------------------------------------------------------- #
# internal converters
# --------------------------------------------------------------------------- #
def _as_table(item: Any) -> Table:
    """Best effort conversion of an object into a :class:`Table`."""
    if isinstance(item, Table):
        return item
    if isinstance(item, Spectrum):
        from nodes._helpers import peaks_to_table

        return peaks_to_table(item)
    if isinstance(item, Molecule):
        return Table(
            name="molecule",
            columns=["property", "value"],
            rows=[[key, value] for key, value in item.properties.items()],
        )
    if isinstance(item, ScientificObject):
        payload = item.to_dict()
        return Table(
            name=item.type,
            columns=["key", "value"],
            rows=[[key, value] for key, value in payload.items()],
        )
    return Table(name="value", columns=["value"], rows=[[item]])


def _png_bytes(item: Any) -> Optional[bytes]:
    """Render ``item`` as PNG bytes (``None`` when it cannot be plotted)."""
    if isinstance(item, Image):
        return item.to_png_bytes()
    if isinstance(item, Spectrum):
        return _spectrum_png(item)
    return None


def _spectrum_png(spectrum: Spectrum) -> Optional[bytes]:
    """Plot a spectrum with matplotlib and return the PNG payload."""
    if not spectrum.x or not spectrum.y:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        figure, axes = plt.subplots(figsize=(7.0, 3.4), dpi=120)
        axes.plot(spectrum.x, spectrum.y, color="#1f6feb", linewidth=0.9)
        for peak in spectrum.peaks[:20]:
            axes.plot([peak.x], [peak.intensity or peak.y], "o", color="#d7263d", markersize=3)
        axes.set_title(spectrum.name or spectrum.mode)
        axes.set_xlabel(spectrum.x_unit or "x")
        axes.set_ylabel(spectrum.y_unit or "intensity")
        figure.tight_layout()
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        plt.close(figure)
        return buffer.getvalue()
    except Exception:  # pragma: no cover - matplotlib is optional at runtime
        return None


def _as_markdown(item: Any) -> str:
    """Render an object as Markdown."""
    if isinstance(item, ScientificReport):
        from nodes._helpers import render_report_markdown

        return render_report_markdown(item)
    if isinstance(item, Table):
        return item.to_csv()
    if isinstance(item, Text):
        return item.text
    if isinstance(item, ScientificObject):
        return item.summary()
    return str(item)


# --------------------------------------------------------------------------- #
# Minimal PNG decoder (dependency free fallback for ImageFileNode)
# --------------------------------------------------------------------------- #
def _read_png(path: Path) -> Optional[List[List[float]]]:
    """Decode an 8-bit, non-interlaced PNG into a 2-D grayscale array.

    Covers the subset the instruments and the platform itself export:
    colour types 0 (grayscale) and 2 (RGB), bit depth 8, no interlace.  Every
    other variant returns ``None`` so the caller can report "unsupported"
    instead of returning a half-decoded image.
    """
    import struct
    import zlib

    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None

    offset = 8
    width = height = bit_depth = color_type = 0
    idat = bytearray()
    while offset + 8 <= len(raw):
        (length,) = struct.unpack_from(">I", raw, offset)
        tag = raw[offset + 4 : offset + 8]
        body = raw[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack_from(">IIBB", body, 0)
        elif tag == b"IDAT":
            idat.extend(body)
        elif tag == b"IEND":
            break
    if not width or not height:
        return None
    if bit_depth != 8 or color_type not in (0, 2):
        return None
    channels = 1 if color_type == 0 else 3
    stride = width * channels

    try:
        data = zlib.decompress(bytes(idat))
    except zlib.error:
        return None

    # Undo the per-scanline filters (PNG spec section 9).
    rows: List[List[int]] = []
    previous = [0] * stride
    position = 0
    for _row in range(height):
        if position + 1 + stride > len(data):
            return None
        filter_type = data[position]
        line = list(data[position + 1 : position + 1 + stride])
        position += 1 + stride
        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                upper_left = previous[i - channels] if i >= channels else 0
                predictor = left + up - upper_left
                pa = abs(predictor - left)
                pb = abs(predictor - up)
                pc = abs(predictor - upper_left)
                nearest = left if (pa <= pb and pa <= pc) else (up if pb <= pc else upper_left)
                line[i] = (line[i] + nearest) & 0xFF
        else:
            return None
        rows.append(line)
        previous = line

    if channels == 1:
        return [[float(value) for value in row] for row in rows]
    # RGB -> luminance (ITU-R BT.601 weights, the same as PIL "L").
    return [
        [float(round(0.299 * row[i] + 0.587 * row[i + 1] + 0.114 * row[i + 2]))
         for i in range(0, stride, 3)]
        for row in rows
    ]
