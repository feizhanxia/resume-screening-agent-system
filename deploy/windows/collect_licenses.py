"""Collect license and notice files shipped in installed wheel metadata."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

LICENSE_NAME = re.compile(r"^(license|licence|copying|notice)(?:$|[._-])", re.IGNORECASE)
MINIMUM_LICENSE_FILES = 5


def collect_licenses(site_packages: Path, destination: Path) -> int:
    site_packages = site_packages.resolve(strict=True)
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0

    for package_info in sorted(site_packages.glob("*.dist-info")):
        package_root = package_info.resolve(strict=True)
        for source in sorted(package_info.rglob("*")):
            if not source.is_file() or not LICENSE_NAME.match(source.name):
                continue
            resolved_source = source.resolve(strict=True)
            if not resolved_source.is_relative_to(package_root):
                continue
            relative = source.relative_to(package_info)
            target = destination / package_info.name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved_source, target)
            copied += 1

    if copied < MINIMUM_LICENSE_FILES:
        raise RuntimeError(
            "Dependency license collection is incomplete: "
            f"only {copied} files found under {site_packages}"
        )
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site_packages", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    count = collect_licenses(args.site_packages, args.destination)
    print(f"Collected {count} dependency license files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
