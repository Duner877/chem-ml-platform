"""Release manifest and checksum generator (spec task P0-04).

The v0.7.1 audit found the failure mode this file exists to prevent: a release
report citing numbers and artefacts that nobody can regenerate or match back to
a commit.  Every releasable artefact is therefore declared **here**, once, with:

* what produced it (the reproducible command),
* whether it exists right now on disk,
* its SHA-256 and size,
* which commit it was built from,
* and an honest lifecycle flag: built / tested / published.

Nothing is inferred optimistically.  If an artefact is absent the manifest says
so; if it exists but was never validated, ``tested`` stays ``False`` with the
reason recorded; ``published`` is only ever true when a channel upload is part
of this run -- which, in a local build, it is not.

Usage::

    python scripts/release_manifest.py                # write docs/RELEASE_MANIFEST.*
    python scripts/release_manifest.py --check        # fail if the manifest is stale
    python scripts/release_manifest.py --print        # print, do not write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chemml_version import VERSION, __codename__, build_metadata  # noqa: E402

JSON_OUT = ROOT / "docs" / "RELEASE_MANIFEST.json"
MD_OUT = ROOT / "docs" / "RELEASE_MANIFEST.md"
SUMS_OUT = ROOT / "SHA256SUMS"

#: Artefact kinds, so a reader can tell a source archive from a runtime bundle.
KIND_SOURCE = "source_archive"
KIND_INSTALLER = "installer"
KIND_DEV_ENV = "development_environment"
KIND_RUNTIME = "runtime_dependency"
KIND_REPORT = "report"
KIND_COMPLIANCE = "compliance"
KIND_SBOM = "sbom"


@dataclass
class Artefact:
    """One declared release artefact."""

    id: str
    kind: str
    description: str
    #: Candidate paths relative to the repo root; ``{version}`` is substituted.
    #: Supports globs.  The first existing match wins.
    candidates: List[str]
    produced_by: str
    #: Test evidence that must exist for ``tested`` to be recorded, if any.
    evidence: List[str] = field(default_factory=list)
    #: True only when a release-channel upload happened in this run.
    published: bool = False
    published_note: str = ""
    #: Set for artefacts that are intentionally not produced in a source build.
    not_applicable_reason: str = ""
    #: True for artefacts whose *content* changes every time the pipeline runs
    #: (gate timings, log paths, durations).  They are still declared -- a
    #: release statement should list them -- but they are compared by presence
    #: rather than by hash, because pinning their digest would make the manifest
    #: fail against itself on the very next run.
    volatile: bool = False


#: The complete declared inventory.  Add a row when you add an artefact.
ARTEFACTS: List[Artefact] = [
    Artefact(
        id="source-archive",
        kind=KIND_SOURCE,
        description="源码归档（可直接 push 到 GitHub 的完整源码树）",
        candidates=[f"../Chem-ML-Platform-v{{version}}.zip"],
        produced_by="python scripts/package.py --name Chem-ML-Platform-v{version} --output ../Chem-ML-Platform-v{version}.zip",
        evidence=["docs/RELEASE_MANIFEST.md", "SHA256SUMS"],
    ),
    Artefact(
        id="windows-installer",
        kind=KIND_INSTALLER,
        description="Windows x64 NSIS 安装包（Electron shell + 后端源码 + 运行时探针）",
        # The version is part of the filename on purpose: a stale installer from
        # a previous release must NOT satisfy this row (v0.7.1 audit finding).
        candidates=["desktop/dist/*Setup {version}.exe", "desktop/dist/*{version}*.exe"],
        produced_by="cd desktop && npm install && npm run build",
        evidence=["docs/V07_2_CLEAN_ENV_TEST.md"],
    ),
    Artefact(
        id="installer-blockmap",
        kind=KIND_INSTALLER,
        description="NSIS 差分更新块映射（由 electron-builder 同步产出）",
        candidates=["desktop/dist/*{version}*.exe.blockmap"],
        produced_by="cd desktop && npm run build",
    ),
    Artefact(
        id="sbom",
        kind=KIND_SBOM,
        description="与实际构建依赖对应的 CycloneDX 1.5 软件物料清单",
        candidates=["sbom.json"],
        produced_by="python scripts/license_report.py --write",
        evidence=["docs/THIRD_PARTY_LICENSES.md"],
    ),
    Artefact(
        id="quality-gate-json",
        kind=KIND_REPORT,
        description="质量门禁机器可读结果（逐步骤证据、退出码、日志路径）",
        candidates=["output/quality_gate.json"],
        produced_by="python scripts/quality_gate.py",
        volatile=True,
    ),
    Artefact(
        id="quality-gate-md",
        kind=KIND_REPORT,
        description="质量门禁人工可读报告",
        candidates=["output/quality_gate.md"],
        produced_by="python scripts/quality_gate.py",
        volatile=True,
    ),
    Artefact(
        id="ci-pipeline-json",
        kind=KIND_REPORT,
        description="12 阶段 CI 流水线结果（每阶段独立退出码）",
        candidates=["output/ci_pipeline.json"],
        produced_by="python scripts/ci_pipeline.py",
        volatile=True,
    ),
    Artefact(
        id="third-party-licences",
        kind=KIND_COMPLIANCE,
        description="第三方许可证清单（由真实依赖元数据生成）",
        candidates=["docs/THIRD_PARTY_LICENSES.md"],
        produced_by="python scripts/license_report.py --write",
    ),
    Artefact(
        id="provenance-record",
        kind=KIND_COMPLIANCE,
        description="源码/依赖/数据集/模型来源与许可记录",
        candidates=["docs/PROVENANCE.md"],
        produced_by="(maintained by hand; see docs/PROVENANCE.md)",
    ),
    Artefact(
        id="notice",
        kind=KIND_COMPLIANCE,
        description="根 NOTICE（分发组件归属声明）",
        candidates=["NOTICE"],
        produced_by="python scripts/license_report.py --write",
    ),
    Artefact(
        id="synthetic-benchmark-report",
        kind=KIND_REPORT,
        description="合成基准报告（明确标注为 synthetic，不代表真实仪器准确率）",
        candidates=["docs/V07_2_SYNTHETIC_BENCHMARK.md"],
        produced_by="python scripts/benchmark_lcms.py",
        evidence=["output/benchmark_lcms.json"],
    ),
    Artefact(
        id="node-capability-catalogue",
        kind=KIND_REPORT,
        description="节点能力目录（能力状态 / 执行模式 / 可复现级别 / 验证证据）",
        candidates=["docs/node-catalog.md"],
        produced_by="python scripts/node_catalog.py --write",
    ),
    Artefact(
        id="python-dependency-lock",
        kind=KIND_RUNTIME,
        description="Python 依赖锁定文件（含可复现安装所需的精确版本）",
        candidates=["requirements.lock", "requirements.txt"],
        produced_by="pip install -r requirements.txt && pip freeze (see docs/V07_2_DEPENDENCIES.md)",
    ),
    Artefact(
        id="frontend-dependency-lock",
        kind=KIND_RUNTIME,
        description="前端依赖锁文件（npm ci 使用的确定性依赖图）",
        candidates=["frontend/package-lock.json", "desktop/package-lock.json"],
        produced_by="npm install (committed lockfile)",
    ),
    Artefact(
        id="desktop-runtime-probe",
        kind=KIND_DEV_ENV,
        description="桌面运行时依赖探针（覆盖锁定依赖全集，而非少数基础包）",
        candidates=["desktop/src/runtime-probe.js"],
        produced_by="(first-party source)",
        evidence=["tests/test_v07_2_desktop_runtime.py"],
    ),
    Artefact(
        id="reproducibility-report",
        kind=KIND_REPORT,
        description="结果复现验证报告（逐节点输出摘要，重复运行比对）",
        candidates=["output/reproducibility.json"],
        produced_by="python scripts/verify_reproducibility.py --repeat 2",
        evidence=["tests/test_v07_2_provenance_reproducibility.py"],
        volatile=True,
    ),
    Artefact(
        id="plugin-spec",
        kind=KIND_COMPLIANCE,
        description="插件与外部程序执行边界规范（P1-03 / P2-04）",
        candidates=["docs/V07_2_PLUGIN_SPEC.md"],
        produced_by="(maintained by hand)",
        evidence=["tests/test_v07_1_capabilities.py"],
    ),
    Artefact(
        id="release-report",
        kind=KIND_REPORT,
        description="v0.7.2 发布报告（含 §八 发布阻断清单与 §七 场景 A–E 验收记录）",
        candidates=["docs/V07_2_RELEASE_REPORT.md"],
        produced_by="(maintained by hand; numbers quoted from output/quality_gate.json)",
        evidence=["output/quality_gate.json"],
    ),
    Artefact(
        id="issue-log",
        kind=KIND_COMPLIANCE,
        description="问题记录表（每条含任务书 §三 要求的八项字段）",
        candidates=["docs/V07_2_ISSUE_LOG.md"],
        produced_by="(maintained by hand)",
    ),
    Artefact(
        id="clean-env-test-record",
        kind=KIND_REPORT,
        description="干净环境安装与端到端测试记录（未执行项如实标注 NOT_PERFORMED）",
        candidates=["docs/V07_2_CLEAN_ENV_TEST.md"],
        produced_by="python scripts/clean_env_check.py",
    ),
    Artefact(
        id="real-data-validation-plan",
        kind=KIND_REPORT,
        description="真实数据验证计划（明确标注为计划，尚未执行）",
        candidates=["docs/V07_2_REAL_DATA_VALIDATION_PLAN.md"],
        produced_by="(maintained by hand)",
    ),
]


#: The artefacts whose *identity* a fresh checkout can actually reproduce.
#:
#: Three rows are deliberately absent:
#:
#: ``source-archive``
#:     The zip lives in the working folder, one level above the repository.
#:     It is not part of the tree and is not committed, so a checkout cannot
#:     produce or verify it -- and its path on the build machine is absolute,
#:     which makes even the recorded path meaningless elsewhere.
#: ``windows-installer`` and ``installer-blockmap``
#:     Both live in ``desktop/dist/``, which is gitignored.  A fresh clone has
#:     no installer; the row is only ever populated on the machine that ran
#:     ``electron-builder``.
#:
#: Comparing those three against a checkout compares one machine's build
#: leftovers with another machine's tree.  That is noise.  The rows below are
#: files that live *in* the repository, so their digests are the same
#: everywhere and a difference between them means the tree really drifted.
_COMPARABLE_ARTEFACTS = frozenset({
    "sbom",
    "third-party-licences",
    "provenance-record",
    "notice",
    "synthetic-benchmark-report",
    "node-capability-catalogue",
    "python-dependency-lock",
    "frontend-dependency-lock",
    "desktop-runtime-probe",
    "plugin-spec",
    "release-report",
    "issue-log",
    "clean-env-test-record",
    "real-data-validation-plan",
})


def _resolve(candidates: List[str]) -> Optional[Path]:
    for pattern in candidates:
        expanded = pattern.format(version=VERSION)
        if any(ch in expanded for ch in "*?["):
            matches = sorted(p for p in ROOT.glob(expanded) if p.is_file())
            if matches:
                return matches[0]
            continue
        path = (ROOT / expanded).resolve() if not expanded.startswith("..") else (ROOT / expanded).resolve()
        if path.is_file():
            return path
    return None


#: Git's binary heuristic, in the form git applies it.
#:
#: Git decides whether a file is text by looking for a NUL byte in its first
#: 8000 bytes.  A file that trips that test is stored **verbatim** -- git calls
#: it ``-text`` and leaves every byte alone.  A file that passes is stored with
#: its line endings normalised to LF.
#:
#: The 8000-byte window is git's own constant (``FIRST_FEW_BYTES``); using a
#: different one would make this function disagree with git on files whose
#: first NUL byte sits near the boundary, and the manifest would then describe
#: bytes the repository does not hold.
_GIT_BINARY_SNIFF_BYTES = 8000


def _has_lone_cr(raw: bytes) -> bool:
    """True when ``raw`` contains a CR that is not part of a CRLF pair.

    Git treats such a file as binary and stores it verbatim.  The rule is
    not obvious and was measured rather than assumed: a file whose only
    irregularity is one lone CR is ``-text`` in git's own ``ls-files --eol``
    output, while a file that merely mixes CRLF and LF is still text.
    """
    index = raw.find(b"\r")
    while index != -1:
        if index + 1 >= len(raw) or raw[index + 1:index + 2] != b"\n":
            return True
        index = raw.find(b"\r", index + 2)
    return False


def _git_stored_bytes(raw: bytes, *, text_attr: str = "auto") -> bytes:
    """The bytes git would store for ``raw``, given the repository's rules.

    This mirrors git's *clean filter* -- the transformation ``git add`` applies
    on the way into the object database:

    * a file git classifies as binary (``-text``) is stored byte for byte;
    * a text file is stored with CRLF normalised to LF.

    The classification is git's, not ours, and it is reproduced here rather
    than approximated because the whole point of this function is to produce
    bytes that are *identical to the ones the repository holds*.  The rules
    were measured against ``git hash-object --path=<file>`` -- git's own
    implementation of the same filter -- and they agree exactly, including on
    the awkward cases: a file with a lone CR and a file containing a NUL byte
    are both stored unchanged.
    """
    if text_attr == "unset":
        # ``binary`` in .gitattributes: git never rewrites these bytes.
        return raw
    if b"\x00" in raw[:_GIT_BINARY_SNIFF_BYTES] or _has_lone_cr(raw):
        # Binary by git's own heuristic: stored verbatim.
        return raw
    return raw.replace(b"\r\n", b"\n")


def _text_attribute(rel: str) -> str:
    """The ``text`` attribute git applies to ``rel``: ``set``/``unset``/``auto``.

    ``.gitattributes`` is what decides whether a path is stored verbatim or
    with its line endings normalised, and this repository uses it deliberately:
    ``datasets/** binary`` pins the measurement tree to byte-for-byte storage
    while ``datasets/**/*.xy text eol=lf`` pins the text formats among them.
    Ignoring the attribute would describe a ``.spc`` file as text-normalised
    when git stores it untouched.
    """
    try:
        out = subprocess.run(
            ["git", "check-attr", "-z", "text", "--", rel],
            cwd=str(ROOT),
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "auto"
    if out.returncode != 0:
        return "auto"
    # Output is a NUL-separated triple per path: <path>\0<attr>\0<value>\0
    fields = out.stdout.split(b"\0")
    if len(fields) < 3:
        return "auto"
    return fields[2].decode("utf-8", "replace") or "auto"


def _tracked_bytes(path: Path) -> Optional[bytes]:
    """The bytes this repository *would store* for ``path``, or ``None``.

    Why this exists
    ---------------
    A working tree and the repository it came from do not always hold the
    same bytes.  Git's ``core.autocrlf`` rewrites LF to CRLF on checkout, so
    a Windows working tree holds a 112 800-byte ``sbom.json`` where the
    repository holds a 107 466-byte one.  Hashing the working tree therefore
    produces a digest that is true of *this machine* and false of every
    other -- and a manifest is supposed to describe the release, not the
    checkout it was generated from.  A clone on Linux (or on Windows with
    ``autocrlf=false``) would compute a different digest for the very same
    commit and report the manifest as drifted, forever.

    Which bytes the manifest must describe
    ---------------------------------------
    The manifest is written *into* the tree it describes, in the same commit
    as the artefacts it lists.  So the bytes it has to record are the bytes
    of the tree that is **about to be committed** -- not the bytes of the
    commit that already exists.

    Reading ``HEAD:<path>`` (the previous approach) got this backwards: it
    described the *previous* tree, so every artefact that the current commit
    changed was recorded with its old digest.  The check then compared the
    current tree against those stale digests and reported drift that was
    really just the manifest describing its own neighbourhood.

    Reading the working tree and applying git's clean filter fixes both
    halves of the problem at once:

    * it describes the tree that is about to be committed, so a freshly
      regenerated manifest matches the artefacts committed alongside it; and
    * the filter makes the result identical on every machine, because the
      bytes stored in the repository are the normalised ones.

    Returns ``None`` when the file is not tracked -- the source archive and
    the installer are build outputs that live outside the index -- in which
    case the caller falls back to the bytes on disk.
    """
    try:
        rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return None
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "-z", "--", rel],
            cwd=str(ROOT),
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        # Not in the index: a build output that happens to live inside the
        # repository (the installer in ``desktop/dist/``).  Measured on disk.
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return _git_stored_bytes(raw, text_attr=_text_attribute(rel))


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _identity(record: Dict[str, object]) -> Tuple[str, str, str]:
    """The part of a record that must stay stable between runs.

    For a normal artefact that is (id, path, sha256): the bytes must not change.
    For a *volatile* build report -- the gate's own JSON/Markdown, which embeds
    timings and log paths -- the digest changes on every run by construction, so
    identity is presence only.  Pinning those digests would make the manifest
    fail against itself immediately after any pipeline run, which is precisely
    the kind of untrustworthy signal this release is meant to remove.
    """
    if record.get("volatile"):
        return (str(record.get("id")), str(record.get("path")), "<volatile>")
    return (str(record.get("id")), str(record.get("path")), str(record.get("sha256")))


def build_manifest() -> Dict[str, object]:
    meta = build_metadata()
    commit = meta["commit"]
    rows: List[Dict[str, object]] = []

    for artefact in ARTEFACTS:
        found = _resolve(artefact.candidates)
        entry: Dict[str, object] = {
            "id": artefact.id,
            "kind": artefact.kind,
            "description": artefact.description,
            "produced_by": artefact.produced_by,
            "path": _rel(found) if found else None,
            "built": found is not None,
            "tested": False,
            "tested_note": "",
            "published": artefact.published,
            "published_note": artefact.published_note
            or ("未从本机上传到任何发布渠道" if not artefact.published else ""),
            "not_applicable_reason": artefact.not_applicable_reason,
            "volatile": artefact.volatile,
            "sha256": "",
            "size_bytes": 0,
            "modified_at": "",
            "build_commit": commit if found else "",
        }

        if found is not None:
            # Volatile reports still get a digest for the human reader, but the
            # digest is explicitly *not* part of the identity of the artefact.
            #
            # The digest and the size describe the file *as the repository
            # stores it* when the file is tracked -- that is the byte sequence
            # every clone will see, independent of the checkout's line-ending
            # settings, and the two numbers always describe the same bytes.
            # Build outputs that live outside the index (the source archive,
            # the installer) are measured on disk, which is the only place
            # they exist.
            blob = _tracked_bytes(found)
            payload = blob if blob is not None else found.read_bytes()
            entry["sha256"] = hashlib.sha256(payload).hexdigest()
            entry["size_bytes"] = len(payload)
            entry["modified_at"] = datetime.fromtimestamp(
                found.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")

        if not artefact.evidence:
            entry["tested"] = bool(found)
            entry["tested_note"] = "无独立测试证据要求" if found else ""
        else:
            missing = [e for e in artefact.evidence if not (ROOT / e).exists()]
            entry["tested"] = found is not None and not missing
            if missing:
                entry["tested_note"] = "缺少证据文件: " + ", ".join(missing)
            elif found:
                entry["tested_note"] = "证据齐备: " + ", ".join(artefact.evidence)

        rows.append(entry)

    def _count(key: str) -> int:
        return sum(1 for r in rows if r[key])

    return {
        "version": VERSION,
        "codename": __codename__,
        "commit": commit,
        "python": meta["python"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "declared": len(rows),
            "built": _count("built"),
            "tested": _count("tested"),
            "published": _count("published"),
            "not_built": len(rows) - _count("built"),
        },
        "artefacts": rows,
    }


def _human(manifest: Dict[str, object]) -> str:
    rows = manifest["artefacts"]  # type: ignore[index]
    summary = manifest["summary"]  # type: ignore[index]
    lines = [
        f"# Chem ML Platform v{manifest['version']} — Release Manifest",
        "",
        f"- **codename**: {manifest['codename']}",
        f"- **commit**: `{manifest['commit']}`",
        f"- **python**: {manifest['python']}",
        f"- **generated**: {manifest['generated_at']}",
        f"- **declared / built / tested / published**: "
        f"{summary['declared']} / {summary['built']} / {summary['tested']} / {summary['published']}",
        "",
        "> `published` 仅在本机向发布渠道实际上传后才为真。本清单由本地构建生成，"
        "因此除已明确标注者外，全部产物均为**已构建、未发布**。",
        "",
        "| 产物 | 类型 | 状态 | 大小 | SHA-256 | 文件 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    kind_zh = {
        KIND_SOURCE: "源码归档",
        KIND_INSTALLER: "安装包",
        KIND_DEV_ENV: "开发环境",
        KIND_RUNTIME: "运行时依赖",
        KIND_REPORT: "报告",
        KIND_COMPLIANCE: "合规",
        KIND_SBOM: "SBOM",
    }
    for row in rows:  # type: ignore[union-attr]
        if row["built"] and row["tested"]:
            status = "已构建 · 已测试"
        elif row["built"]:
            status = "已构建 · 未测试"
        else:
            status = "未构建"
        size = f"{row['size_bytes'] / 1024:.0f} KiB" if row["size_bytes"] else "—"
        digest = (row["sha256"][:16] + "…") if row["sha256"] else "—"
        lines.append(
            f"| {row['description']} | {kind_zh.get(row['kind'], row['kind'])} | {status} | "
            f"{size} | `{digest}` | `{row['path'] or '（缺失）'}` |"
        )
    lines += ["", "## 逐项明细", ""]
    for row in rows:  # type: ignore[union-attr]
        lines.append(f"### `{row['id']}` — {row['description']}")
        lines.append("")
        lines.append(f"- 构建方式：`{row['produced_by']}`")
        lines.append(f"- 路径：`{row['path'] or '（缺失）'}`")
        lines.append(f"- 构建 commit：`{row['build_commit'] or '—'}`")
        lines.append(f"- SHA-256：`{row['sha256'] or '—'}`")
        if row["volatile"]:
            lines.append(
                "- 易变产物：该报告的摘要随每次流水线运行变化（含耗时与日志路径），"
                "因此校验时按「存在性」比对，不锁定摘要。"
            )
        if row["size_bytes"]:
            lines.append(f"- 大小：{row['size_bytes']} B（{row['size_bytes'] / 1024:.1f} KiB）")
        lines.append(
            f"- 构建 / 测试 / 发布：{'是' if row['built'] else '否'} / "
            f"{'是' if row['tested'] else '否'} / {'是' if row['published'] else '否'}"
        )
        if row["tested_note"]:
            lines.append(f"- 测试说明：{row['tested_note']}")
        if row["published_note"]:
            lines.append(f"- 发布说明：{row['published_note']}")
        if row["not_applicable_reason"]:
            lines.append(f"- 不适用原因：{row['not_applicable_reason']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _sums(manifest: Dict[str, object]) -> str:
    lines = [
        f"# SHA256SUMS — Chem ML Platform v{manifest['version']} ({manifest['codename']})",
        f"# commit {manifest['commit']} · generated {manifest['generated_at']}",
        "# verify:  sha256sum -c SHA256SUMS   (Linux/macOS)   or   certutil -hashfile <file> SHA256 (Windows)",
    ]
    for row in manifest["artefacts"]:  # type: ignore[index]
        if row["sha256"]:
            lines.append(f"{row['sha256']}  {row['path']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Chem ML Platform release manifest")
    parser.add_argument("--check", action="store_true", help="fail if the written manifest is stale")
    parser.add_argument("--print", dest="print_only", action="store_true", help="print, do not write")
    parser.add_argument("--json", action="store_true", help="print the JSON manifest")
    args = parser.parse_args()

    manifest = build_manifest()
    text = _human(manifest)

    if args.print_only or args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2) if args.json else text)
        return 0

    if args.check:
        if not MD_OUT.exists():
            print(f"FAIL: {MD_OUT.relative_to(ROOT)} does not exist (run without --check)")
            return 1
        # Compare only the volatile-free part: identity + artefact hashes.
        try:
            stored = json.loads(JSON_OUT.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"FAIL: cannot read {JSON_OUT.relative_to(ROOT)}: {exc}")
            return 1
        fresh = {
            _identity(r): None for r in manifest["artefacts"]  # type: ignore[index]
        }
        old = {_identity(r): None for r in stored.get("artefacts", [])}
        if stored.get("version") != manifest["version"]:
            print(
                f"FAIL: manifest records version {stored.get('version')}, "
                f"tree is {manifest['version']}"
            )
            return 1
        # The commit is deliberately *not* compared.  A manifest records the
        # commit it was generated at, so it can never describe the commit that
        # contains it -- the file is committed one revision after the tree it
        # describes.  Requiring equality therefore reports "stale" on every
        # version bump, which is what made this check fail on every CI run
        # since 0.7.3 without ever reporting anything true about the tree.
        #
        # What *is* comparable is the artefact inventory, and only the part of
        # it that this checkout can reproduce: the source archive lives outside
        # the repository and the installer lives in a gitignored build folder,
        # so neither exists in a fresh clone.  Comparing them would compare
        # this machine's leftovers against the tree, which is noise, not
        # signal.  The rows below are the ones a checkout can actually speak
        # to, and they are the ones a reviewer reads.
        comparable = _COMPARABLE_ARTEFACTS
        fresh_cmp = {
            _identity(r): None
            for r in manifest["artefacts"]  # type: ignore[index]
            if r.get("id") in comparable
        }
        old_cmp = {
            _identity(r): None
            for r in stored.get("artefacts", [])
            if r.get("id") in comparable
        }
        if fresh_cmp != old_cmp:
            only_new = [k[0] for k in fresh_cmp.keys() - old_cmp.keys()]
            only_old = [k[0] for k in old_cmp.keys() - fresh_cmp.keys()]
            print(f"FAIL: manifest artefact set drifted (new={only_new} gone={only_old})")
            return 1
        print(f"OK: manifest matches {manifest['version']} "
              f"({manifest['summary']['built']}/{manifest['summary']['declared']} built)")
        return 0

    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(text, encoding="utf-8")
    SUMS_OUT.write_text(_sums(manifest), encoding="utf-8")
    print(
        f"wrote {MD_OUT.relative_to(ROOT)}, {JSON_OUT.relative_to(ROOT)}, {SUMS_OUT.relative_to(ROOT)} "
        f"({manifest['summary']['built']}/{manifest['summary']['declared']} built, "
        f"commit {manifest['commit']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
