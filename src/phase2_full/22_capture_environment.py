#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/22_capture_environment.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Capture software, script, configuration, and reference-data provenance."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PACKAGES = [
    "duckdb",
    "pyarrow",
    "pandas",
    "numpy",
    "scipy",
    "statsmodels",
    "pyfixest",
    "polars",
    "matplotlib",
    "seaborn",
    "jupyter",
    "nbformat",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    qa = phase2 / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    packages = []
    for name in PACKAGES:
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = None
        packages.append({"package": name, "version": version})
    pd.DataFrame(packages).to_csv(
        qa / "software_package_versions.csv", index=False
    )

    file_rows = []
    for folder in ("scripts", "config", "documentation"):
        for path in sorted((phase2 / folder).glob("*")):
            if path.is_file():
                file_rows.append(
                    {
                        "relative_path": path.relative_to(phase2).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
    pd.DataFrame(file_rows).to_csv(
        qa / "code_configuration_documentation_hashes.csv", index=False
    )
    environment = {
        "captured_utc": now_utc(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_implementation": platform.python_implementation(),
        "byteorder": sys.byteorder,
        "packages": {item["package"]: item["version"] for item in packages},
        "deterministic_seed": 20260726,
        "source_release_policy": "immutable_read_only",
    }
    (qa / "computational_environment.json").write_text(
        json.dumps(environment, indent=2), encoding="utf-8"
    )
    print(json.dumps(environment, indent=2))


if __name__ == "__main__":
    main()
