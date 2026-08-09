"""Create a portable ZIP with standard forward-slash member paths."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def create_portable(source: Path, output: Path) -> Path:
    source = source.resolve(strict=True)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() != ".zip":
        raise ValueError("Portable archive must use the .zip extension")
    created = Path(
        shutil.make_archive(
            str(output.with_suffix("")),
            "zip",
            root_dir=source,
        )
    ).resolve(strict=True)
    if created != output:
        raise RuntimeError(f"Archive created at unexpected path: {created}")
    return created


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    archive = create_portable(args.source, args.output)
    print(f"Created portable archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
