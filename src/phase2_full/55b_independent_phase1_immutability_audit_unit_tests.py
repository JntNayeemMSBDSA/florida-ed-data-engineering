#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/55b_independent_phase1_immutability_audit_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic fail-closed tests for the Phase 1 immutability audit."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name(
    "55_independent_phase1_immutability_audit.py"
)
SPEC = importlib.util.spec_from_file_location(
    "independent_phase1_immutability_audit",
    SCRIPT,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to import Phase 1 immutability audit")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(root: Path) -> tuple[Path, Path]:
    phase1 = root / "florida_ed_full_build_20260724"
    phase2 = root / "florida_ed_concordance_analysis_20260726"
    (phase1 / "data").mkdir(parents=True)
    (phase1 / "documentation").mkdir(parents=True)
    (phase2 / "qa").mkdir(parents=True)
    frozen = (
        phase2
        / "audit_history"
        / "report_deferral_20260727T083046Z"
        / "r"
        / "ledgers"
    )
    frozen.mkdir(parents=True)

    listed_paths = []
    for index in range(573):
        path = phase1 / "data" / f"file_{index:03d}.bin"
        path.write_bytes(f"fixture-{index}".encode("utf-8"))
        listed_paths.append(path)
    manifest = phase1 / "documentation" / "file_manifest_sha256.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["relative_path", "size_bytes", "sha256"],
        )
        writer.writeheader()
        for path in listed_paths:
            writer.writerow(
                {
                    "relative_path": path.relative_to(phase1).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": digest(path),
                }
            )
    build = phase1 / "build_manifest_final.json"
    build.write_text('{"status":"fixture"}\n', encoding="utf-8")
    source_manifest = {
        "sources": [
            {
                "workspace_relative_path": (
                    "outputs/florida_ed_full_build_20260724/"
                    "documentation/file_manifest_sha256.csv"
                ),
                "sha256": digest(manifest),
            }
        ]
    }
    (frozen / "Report_Source_Manifest.json").write_text(
        json.dumps(source_manifest),
        encoding="utf-8",
    )
    (phase2 / "qa" / "release_audit.json").write_text(
        json.dumps(
            {
                "read_only_audit_passed": True,
                "release_manifest_sha256": digest(build),
            }
        ),
        encoding="utf-8",
    )
    return phase1, phase2


def main() -> None:
    tests: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(
        prefix="phase1_immutability_unit_"
    ) as temporary:
        root = Path(temporary)
        phase1, phase2 = make_fixture(root)

        clean, clean_rows = MODULE.run_audit(phase1, phase2, workers=2)
        tests.append(
            {
                "test": "clean_release_passes",
                "passed": clean["status"] == "PASS"
                and len(clean_rows) == 573
                and clean["checksum_validation"]["files_failed"] == 0,
            }
        )

        tampered = phase1 / "data" / "file_012.bin"
        tampered.write_bytes(b"tampered")
        tamper_result, _ = MODULE.run_audit(
            phase1,
            phase2,
            workers=2,
        )
        tests.append(
            {
                "test": "content_tampering_fails",
                "passed": tamper_result["status"] == "FAIL"
                and "data/file_012.bin"
                in tamper_result["checksum_validation"]["failed_paths"],
            }
        )
        tampered.write_bytes(b"fixture-12")

        extra = phase1 / "unexpected.bin"
        extra.write_bytes(b"unexpected")
        unexpected_result, _ = MODULE.run_audit(
            phase1,
            phase2,
            workers=2,
        )
        tests.append(
            {
                "test": "unexpected_release_file_fails",
                "passed": unexpected_result["status"] == "FAIL"
                and "unexpected.bin"
                in unexpected_result["release_inventory"][
                    "unexpected_paths"
                ],
            }
        )
        extra.unlink()

        frozen_path = (
            phase2
            / "audit_history"
            / "report_deferral_20260727T083046Z"
            / "r"
            / "ledgers"
            / "Report_Source_Manifest.json"
        )
        frozen_payload = json.loads(frozen_path.read_text(encoding="utf-8"))
        frozen_payload["sources"][0]["sha256"] = "0" * 64
        frozen_path.write_text(
            json.dumps(frozen_payload),
            encoding="utf-8",
        )
        frozen_result, _ = MODULE.run_audit(
            phase1,
            phase2,
            workers=2,
        )
        tests.append(
            {
                "test": "frozen_manifest_hash_mismatch_fails",
                "passed": frozen_result["status"] == "FAIL"
                and not frozen_result["file_manifest"]["hash_match"],
            }
        )

    passed = sum(bool(test["passed"]) for test in tests)
    payload = {
        "status": "PASS" if passed == len(tests) else "FAIL",
        "tests_passed": passed,
        "tests_total": len(tests),
        "tests": tests,
    }
    output = (
        SCRIPT.parents[1]
        / "qa"
        / "independent_phase1_immutability_audit_unit_tests.json"
    )
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
