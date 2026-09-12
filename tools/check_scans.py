"""Say which of a folder's photographs look wrong, without opening each one.

    .venv/bin/python tools/check_scans.py ~/Pictures/Photosplit

Every failure this project has had wrote files and reported success. This reads
them back and complains about the ones that are not photographs: blank, black,
blown out, crushed, or a fragment of the picture beside them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photosplit.review import review  # noqa: E402
from photosplit.split import SCAN_SUFFIXES  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check written photographs for problems.")
    parser.add_argument("folders", nargs="+", help="folders of crops, or single files")
    parser.add_argument("--dpi", type=float, help="override the resolution")
    parser.add_argument("-r", "--recursive", action="store_true")
    args = parser.parse_args()

    paths: list[Path] = []
    for name in args.folders:
        path = Path(name).expanduser()
        if path.is_dir():
            walk = path.rglob("*") if args.recursive else path.glob("*")
            paths += sorted(
                p for p in walk
                if p.suffix.lower() in SCAN_SUFFIXES and "-preview" not in p.stem
            )
        elif path.exists():
            paths.append(path)

    if not paths:
        print("nothing to check", file=sys.stderr)
        return 1

    findings = review(paths, args.dpi)
    for finding in findings:
        print(f"{finding.path}: {finding.detail}")

    clean = len(paths) - len(findings)
    print(f"\n{clean} of {len(paths)} look fine; {len(findings)} worth a look.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
