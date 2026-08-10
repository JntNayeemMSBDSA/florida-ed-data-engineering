#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/55_independent_phase1_immutability_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Recompute every immutable Phase 1 release-file checksum.

The audit writes only to Phase 2. It validates the original 573-row Phase 1
file manifest against the hash preserved in the pre-deferral report-source
snapshot, verifies the independently frozen top-level build-manifest hash,
rejects missing or unexpected release files, and recomputes every listed file
size and SHA-256 digest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FILE_MANIFEST_RELATIVE_PATH = "documentation/file_manifest_sha256.csv"
BUILD_MANIFEST_RELATIVE_PATH = "build_manifest_final.json"
EXPECTED_NON_MANIFEST_FILES = {
    FILE_MANIFEST_RELATIVE_PATH,
    BUILD_MANIFEST_RELATIVE_PATH,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def normalized_relative_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    candidate = Path(normalized)
    if (
        not normalized
        or candidate.is_absolute()
        or ".." in candidate.parts
        or normalized.startswith("/")
    ):
        raise ValueError(f"Unsafe manifest path: {value!r}")
    return normalized


def load_file_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {"relative_path", "size_bytes", "sha256"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Phase 1 file manifest schema is invalid")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        relative = normalized_relative_path(str(row["relative_path"]))
        key = relative.lower()
        if key in seen:
            raise ValueError(f"Duplicate manifest path: {relative}")
        seen.add(key)
        expected_size = int(row["size_bytes"])
        expected_sha = str(row["sha256"]).strip().lower()
        if expected_size < 0:
            raise ValueError(f"Negative expected size: {relative}")
        if not SHA256_PATTERN.fullmatch(expected_sha):
            raise ValueError(f"Invalid SHA-256: {relative}")
        parsed.append(
            {
                "relative_path": relative,
                "expected_size_bytes": expected_size,
                "expected_sha256": expected_sha,
            }
        )
    return parsed


def find_frozen_manifest_hash(
    report_source_manifest_path: Path,
    phase1_name: str,
) -> str:
    payload = json.loads(
        report_source_manifest_path.read_text(encoding="utf-8")
    )
    candidates: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            path_value = value.get("workspace_relative_path")
            hash_value = value.get("sha256")
            if isinstance(path_value, str) and isinstance(hash_value, str):
                normalized = path_value.replace("\\", "/").lower()
                suffix = (
                    f"outputs/{phase1_name}/"
                    f"{FILE_MANIFEST_RELATIVE_PATH}"
                ).lower()
                if normalized.endswith(suffix):
                    candidates.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    if len(candidates) != 1:
        raise ValueError(
            "Expected exactly one frozen Phase 1 file-manifest source entry; "
            f"observed {len(candidates)}"
        )
    value = str(candidates[0]["sha256"]).lower()
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError("Frozen file-manifest hash is invalid")
    return value


def check_one(
    phase1: Path,
    row: dict[str, Any],
) -> dict[str, Any]:
    path = phase1 / row["relative_path"]
    exists = path.is_file()
    actual_size = path.stat().st_size if exists else -1
    size_passed = exists and actual_size == row["expected_size_bytes"]
    actual_sha = sha256_file(path) if exists else ""
    sha_passed = exists and actual_sha == row["expected_sha256"]
    return {
        **row,
        "exists": exists,
        "actual_size_bytes": actual_size,
        "size_passed": size_passed,
        "actual_sha256": actual_sha,
        "sha256_passed": sha_passed,
        "passed": exists and size_passed and sha_passed,
    }


def run_audit(
    phase1: Path,
    phase2: Path,
    workers: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = time.perf_counter()
    phase1 = phase1.resolve()
    phase2 = phase2.resolve()
    file_manifest = phase1 / FILE_MANIFEST_RELATIVE_PATH
    build_manifest = phase1 / BUILD_MANIFEST_RELATIVE_PATH
    frozen_report_source = (
        phase2
        / "audit_history"
        / "report_deferral_20260727T083046Z"
        / "r"
        / "ledgers"
        / "Report_Source_Manifest.json"
    )
    phase2_release_audit_path = phase2 / "qa" / "release_audit.json"
    for required in (
        file_manifest,
        build_manifest,
        frozen_report_source,
        phase2_release_audit_path,
    ):
        if not required.is_file():
            raise FileNotFoundError(required)

    manifest_rows = load_file_manifest(file_manifest)
    current_file_manifest_sha = sha256_file(file_manifest)
    frozen_file_manifest_sha = find_frozen_manifest_hash(
        frozen_report_source,
        phase1.name,
    )
    phase2_release_audit = json.loads(
        phase2_release_audit_path.read_text(encoding="utf-8")
    )
    current_build_manifest_sha = sha256_file(build_manifest)
    frozen_build_manifest_sha = str(
        phase2_release_audit.get("release_manifest_sha256", "")
    ).lower()

    expected_paths = {
        row["relative_path"].lower() for row in manifest_rows
    } | {value.lower() for value in EXPECTED_NON_MANIFEST_FILES}
    observed_paths = {
        path.relative_to(phase1).as_posix().lower()
        for path in phase1.rglob("*")
        if path.is_file()
    }
    missing_paths = sorted(expected_paths - observed_paths)
    unexpected_paths = sorted(observed_paths - expected_paths)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        checks = list(
            executor.map(
                lambda row: check_one(phase1, row),
                manifest_rows,
            )
        )
    checks.sort(key=lambda row: row["relative_path"].lower())
    failed_checks = [
        row["relative_path"] for row in checks if not row["passed"]
    ]
    total_bytes = sum(
        int(row["actual_size_bytes"])
        for row in checks
        if row["actual_size_bytes"] >= 0
    )
    passed = (
        len(manifest_rows) == 573
        and current_file_manifest_sha == frozen_file_manifest_sha
        and bool(frozen_build_manifest_sha)
        and current_build_manifest_sha == frozen_build_manifest_sha
        and phase2_release_audit.get("read_only_audit_passed") is True
        and not missing_paths
        and not unexpected_paths
        and not failed_checks
    )
    payload = {
        "status": "PASS" if passed else "FAIL",
        "created_utc": utc_now(),
        "audit_version": "independent_phase1_immutability_v1_20260727",
        "phase1_path": str(phase1),
        "phase2_output_only": True,
        "phase1_write_operations": 0,
        "file_manifest": {
            "path": str(file_manifest),
            "rows_expected": 573,
            "rows_observed": len(manifest_rows),
            "current_sha256": current_file_manifest_sha,
            "frozen_pre_deferral_sha256": frozen_file_manifest_sha,
            "hash_match": (
                current_file_manifest_sha == frozen_file_manifest_sha
            ),
        },
        "build_manifest": {
            "path": str(build_manifest),
            "current_sha256": current_build_manifest_sha,
            "frozen_phase2_sha256": frozen_build_manifest_sha,
            "hash_match": (
                current_build_manifest_sha == frozen_build_manifest_sha
            ),
        },
        "release_inventory": {
            "expected_file_count": len(expected_paths),
            "observed_file_count": len(observed_paths),
            "missing_paths": missing_paths,
            "unexpected_paths": unexpected_paths,
        },
        "checksum_validation": {
            "files_checked": len(checks),
            "files_passed": sum(bool(row["passed"]) for row in checks),
            "files_failed": len(failed_checks),
            "failed_paths": failed_checks,
            "bytes_hashed": total_bytes,
            "workers": max(1, workers),
        },
        "phase2_prior_read_only_release_audit_passed": (
            phase2_release_audit.get("read_only_audit_passed") is True
        ),
        "source_release_modified": not passed,
        "phase1_modified": not passed,
        "elapsed_seconds": time.perf_counter() - started,
    }
    return payload, checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase1", required=True, type=Path)
    parser.add_argument(
        "--phase2",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    output_json = phase2 / "qa" / "final_phase1_immutability_audit.json"
    output_csv = (
        phase2 / "qa" / "final_phase1_immutability_file_checks.csv"
    )
    try:
        payload, checks = run_audit(
            args.phase1,
            phase2,
            args.workers,
        )
        atomic_csv(
            output_csv,
            checks,
            [
                "relative_path",
                "expected_size_bytes",
                "actual_size_bytes",
                "size_passed",
                "expected_sha256",
                "actual_sha256",
                "sha256_passed",
                "exists",
                "passed",
            ],
        )
        payload["file_check_table"] = {
            "path": str(output_csv.resolve()),
            "sha256": sha256_file(output_csv),
        }
        payload["audit_script"] = {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        }
        atomic_json(output_json, payload)
        print(json.dumps(payload, indent=2))
        if payload["status"] != "PASS":
            raise SystemExit(1)
    except Exception as exc:
        if isinstance(exc, SystemExit):
            raise
        failure = {
            "status": "FAIL",
            "created_utc": utc_now(),
            "audit_version": "independent_phase1_immutability_v1_20260727",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "phase2_output_only": True,
            "phase1_write_operations": 0,
            "source_release_modified": True,
            "phase1_modified": True,
        }
        atomic_json(output_json, failure)
        print(json.dumps(failure, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
