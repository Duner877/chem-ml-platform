"""Regression tests for the mzML parser (v0.7.2 UI-merge round).

Two real-world defects were found when the user supplied an imzML-exported
single-scan mzML file (``datasets/mass_spectrometry/scan_018081.mzml``):

1. ``_decode_binary`` built ``struct`` formats from NumPy-style strings
   (``"<f8"``), which is not a valid ``struct`` format -- *every* binary array
   failed with ``struct.error``;
2. writers that place precision / compression / array-type cvParams inside
   ``<referenceableParamGroup>`` definitions (imzML converters do this) made
   the parser see neither the array type nor the precision.

The tests below lock both behaviours, plus the shipped demo dataset.
"""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import pytest

from workflow_engine.parsers.mzml import read_mzml

ROOT = Path(__file__).resolve().parents[1]

_MZML_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1">
  <run id="R1">
    <spectrumList count="1">
      <spectrum id="scan=1" index="0" defaultArrayLength="{length}">
        <cvParam cvRef="MS" accession="MS:1000579" name="MS1 spectrum" value=""/>
        <cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum" value=""/>
        <binaryDataArrayList count="2">
          <binaryDataArray encodedLength="0">
            {mz_header}
            <binary>{mz_b64}</binary>
          </binaryDataArray>
          <binaryDataArray encodedLength="0">
            {int_header}
            <binary>{int_b64}</binary>
          </binaryDataArray>
        </binaryDataArrayList>
      </spectrum>
    </spectrumList>
  </run>
</mzML>
"""

#: referenceable-group style headers (the shape the user's file uses)
_GROUP_REFS = """
            <referenceableParamGroupRef ref="mzArray"/>
"""
_GROUP_REFS_INT = """
            <referenceableParamGroupRef ref="intensityArray"/>
"""
#: group definitions block inserted before <run>
_GROUPS = """  <referenceableParamGroupList count="2">
    <referenceableParamGroup id="mzArray">
      <cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>
      <cvParam cvRef="MS" accession="MS:1000514" name="m/z array" value=""/>
      <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>
    </referenceableParamGroup>
    <referenceableParamGroup id="intensityArray">
      <cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>
      <cvParam cvRef="MS" accession="MS:1000515" name="intensity array" value=""/>
      <cvParam cvRef="MS" accession="MS:1000521" name="32-bit float" value=""/>
    </referenceableParamGroup>
  </referenceableParamGroupList>
"""

#: inline cvParam style headers
_INLINE_MZ = """<cvParam cvRef="MS" accession="MS:1000514" name="m/z array" value=""/>
            <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>"""
_INLINE_INT = """<cvParam cvRef="MS" accession="MS:1000515" name="intensity array" value=""/>
            <cvParam cvRef="MS" accession="MS:1000521" name="32-bit float" value=""/>"""


def _mzml(tmp_path: Path, *, groups: bool, zlib_compressed: bool) -> Path:
    mzs = [100.0, 200.5, 300.25]
    ints = [10.0, 999.5, 3.25]
    mz_raw = struct.pack(f"<{len(mzs)}d", *mzs)
    int_raw = struct.pack(f"<{len(ints)}f", *ints)
    if zlib_compressed:
        mz_raw = zlib.compress(mz_raw)
        int_raw = zlib.compress(int_raw)
    mz_comp = "zlib compression" if zlib_compressed else "no compression"
    int_comp = mz_comp
    if groups:
        mz_header = f'<referenceableParamGroupRef ref="mzArray"/>'
        int_header = f'<referenceableParamGroupRef ref="intensityArray"/>'
        group_defs = _GROUPS.replace('name="no compression"', f'name="{mz_comp}"')
        group_defs = _GROUPS  # compression stays "no compression" for the group file
        body = _MZML_TEMPLATE.format(
            length=len(mzs),
            mz_header=mz_header,
            mz_b64=base64.b64encode(mz_raw).decode(),
            int_header=int_header,
            int_b64=base64.b64encode(int_raw).decode(),
        )
        # inject the group list before <run>
        body = body.replace("  <run", _GROUPS + "  <run")
    else:
        comp = (
            '<cvParam cvRef="MS" accession="MS:1000574" name="zlib compression" value=""/>'
            if zlib_compressed
            else '<cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>'
        )
        mz_header = (
            f'<cvParam cvRef="MS" accession="MS:1000514" name="m/z array" value=""/>\n            {comp}\n'
            f'            <cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>'
        )
        int_header = (
            f'<cvParam cvRef="MS" accession="MS:1000515" name="intensity array" value=""/>\n            {comp}\n'
            f'            <cvParam cvRef="MS" accession="MS:1000521" name="32-bit float" value=""/>'
        )
        body = _MZML_TEMPLATE.format(
            length=len(mzs),
            mz_header=mz_header,
            mz_b64=base64.b64encode(mz_raw).decode(),
            int_header=int_header,
            int_b64=base64.b64encode(int_raw).decode(),
        )
    path = tmp_path / "tiny.mzml"
    path.write_text(body, encoding="utf-8")
    return path


class TestMzmlParser:
    def test_inline_params_decode(self, tmp_path):
        path = _mzml(tmp_path, groups=False, zlib_compressed=False)
        spectra = read_mzml(path)
        assert len(spectra) == 1
        spectrum = spectra[0]
        assert len(spectrum.x) == 3
        assert spectrum.x == pytest.approx([100.0, 200.5, 300.25])
        assert spectrum.y[1] == pytest.approx(999.5, abs=0.01)

    def test_referenceable_param_groups_decode(self, tmp_path):
        """imzML-style files: precision & array type live in the group."""
        path = _mzml(tmp_path, groups=True, zlib_compressed=False)
        spectra = read_mzml(path)
        assert len(spectra) == 1
        spectrum = spectra[0]
        assert len(spectrum.x) == 3
        assert spectrum.x == pytest.approx([100.0, 200.5, 300.25])
        # intensity array is 32-bit float
        assert spectrum.y[1] == pytest.approx(999.5, abs=0.05)

    def test_zlib_compressed_decode(self, tmp_path):
        path = _mzml(tmp_path, groups=False, zlib_compressed=True)
        spectra = read_mzml(path)
        assert spectra[0].x == pytest.approx([100.0, 200.5, 300.25])

    def test_shipped_dhb_dataset(self):
        """The user-supplied MALDI DHB scan ships as a governed dataset."""
        path = ROOT / "datasets" / "mass_spectrometry" / "scan_018081.mzml"
        spectra = read_mzml(path)
        assert len(spectra) == 1
        spectrum = spectra[0]
        assert len(spectrum.x) == 836
        assert spectrum.metadata.get("id") == "scan=18081"
        # DHB matrix markers: [M+H]+ at 155.0337 and its dehydration ion 137.0231
        xs = spectrum.x
        near_155 = min(xs, key=lambda v: abs(v - 155.0337))
        assert abs(near_155 - 155.0337) < 0.01
        near_137 = min(xs, key=lambda v: abs(v - 137.0231))
        assert abs(near_137 - 137.0231) < 0.01
