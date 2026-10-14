"""Dataset metadata governance CLI (v0.7.1 task G).

Thin command line wrapper over :mod:`data_layer.quality` -- the same rules the
REST layer runs before analysis.

    python scripts/dataset_governance.py            # normalise + write
    python scripts/dataset_governance.py --check     # verify, exit 1 on problems
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_layer.quality import build, check, metadata_files, quality_report  # noqa: E402

DATASETS = ROOT / "datasets"


def main() -> int:
    parser = argparse.ArgumentParser(description="Dataset metadata governance")
    parser.add_argument("--check", action="store_true", help="verify, do not write")
    args = parser.parse_args()

    if args.check:
        ok, problems = check(DATASETS)
        if ok:
            print(f"OK: {len(metadata_files(DATASETS))} dataset metadata records are consistent")
            return 0
        for problem in problems:
            print(f"PROBLEM: {problem['path']}: {problem['issue']}")
        return 1

    written = build(DATASETS)
    print(f"normalised {len(written)} metadata file(s)")
    for path in written:
        print("  updated:", path.relative_to(ROOT).as_posix())
    report = quality_report(DATASETS)
    print(f"verify: {'OK' if report['ok'] else str(report['problem_count']) + ' problem(s)'}")
    for problem in report["problems"][:20]:
        print(f"  PROBLEM: {problem['path']}: {problem['issue']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
