#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/56b_finalize_analytical_release_status_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic fail-closed tests for the split analytical-release finalizer."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name(
    "56_finalize_analytical_release_status.py"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_fixture(root: Path) -> tuple[Path, Path]:
    phase1 = root / "florida_ed_full_build_20260724"
    phase2 = root / "florida_ed_concordance_analysis_20260726"
    phase1.mkdir(parents=True)
    (phase2 / "qa").mkdir(parents=True)

    build = phase1 / "build_manifest_final.json"
    build.write_text('{"release":"fixture"}\n', encoding="utf-8")
    write_json(
        phase2 / "qa" / "release_audit.json",
        {
            "read_only_audit_passed": True,
            "release_manifest_sha256": digest(build),
        },
    )
    write_json(
        phase2 / "qa" / "complete_analysis_release_audit.json",
        {
            "status": "PASS",
            "checks_passed": 10,
            "checks_total": 10,
        },
    )
    write_json(
        phase2 / "qa" / "independent_multiple_testing_audit.json",
        {
            "status": "PASS",
            "adjusted_datasets_verified": 17,
        },
    )
    write_json(
        phase2 / "qa" / "final_phase1_immutability_audit.json",
        {
            "status": "PASS",
            "checksum_validation": {
                "files_checked": 573,
                "files_failed": 0,
            },
            "source_release_modified": False,
        },
    )
    write_json(
        phase2
        / "qa"
        / "user_authorized_report_deferral_20260727T083046Z.json",
        {
            "release_status": {
                "ANALYTICAL_RELEASE": "IN_PROGRESS",
                "REPORT_AND_PUBLIC_RELEASE": "DEFERRED_BY_USER_BUDGET",
                "whole_project_complete": False,
            }
        },
    )
    write_json(
        phase2
        / "audit_history"
        / "report_deferral_20260727T083046Z"
        / "ARCHIVE_MANIFEST.json",
        {"status": "PASS"},
    )
    marker = (
        phase2
        / "qa"
        / "run_logs"
        / "post_canonical_supervisor"
        / "POST_CANONICAL_ANALYSIS_COMPLETE_PENDING_FINAL_RELEASE_AUDIT.log"
    )
    marker.parent.mkdir(parents=True)
    marker.write_text(
        "PASS corrected primary AMI and complete directional analysis/audits.\n",
        encoding="utf-8",
    )
    (phase2 / "reports" / "report_production").mkdir(parents=True)
    return phase1, phase2


def run_finalizer(
    phase1: Path,
    phase2: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--phase2",
            str(phase2),
            "--phase1",
            str(phase1),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    tests: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(
        prefix="split_release_finalizer_unit_"
    ) as temporary:
        phase1, phase2 = make_fixture(Path(temporary))
        result = run_finalizer(phase1, phase2)
        output = (
            phase2
            / "qa"
            / "ANALYTICAL_RELEASE_COMPLETE_REPORTS_DEFERRED.json"
        )
        payload = (
            json.loads(output.read_text(encoding="utf-8"))
            if output.is_file()
            else {}
        )
        tests.append(
            {
                "test": "complete_analytical_release_passes_with_reports_deferred",
                "passed": result.returncode == 0
                and payload.get("release_status", {}).get(
                    "ANALYTICAL_RELEASE"
                )
                == "PASS_INDEPENDENTLY_AUDITED"
                and payload.get("release_status", {}).get(
                    "REPORT_AND_PUBLIC_RELEASE"
                )
                == "DEFERRED_BY_USER_BUDGET"
                and payload.get("release_status", {}).get(
                    "whole_project_complete"
                )
                is False,
            }
        )

    with tempfile.TemporaryDirectory(
        prefix="split_release_finalizer_bad_audit_"
    ) as temporary:
        phase1, phase2 = make_fixture(Path(temporary))
        complete_path = (
            phase2 / "qa" / "complete_analysis_release_audit.json"
        )
        write_json(
            complete_path,
            {
                "status": "PASS",
                "checks_passed": 9,
                "checks_total": 10,
            },
        )
        result = run_finalizer(phase1, phase2)
        tests.append(
            {
                "test": "incomplete_release_audit_fails_closed",
                "passed": result.returncode != 0
                and "failing check" in result.stderr,
            }
        )

    with tempfile.TemporaryDirectory(
        prefix="split_release_finalizer_no_deferral_"
    ) as temporary:
        phase1, phase2 = make_fixture(Path(temporary))
        deferral_path = (
            phase2
            / "qa"
            / "user_authorized_report_deferral_20260727T083046Z.json"
        )
        write_json(
            deferral_path,
            {
                "release_status": {
                    "ANALYTICAL_RELEASE": "IN_PROGRESS",
                    "REPORT_AND_PUBLIC_RELEASE": "NOT_DEFERRED",
                }
            },
        )
        result = run_finalizer(phase1, phase2)
        tests.append(
            {
                "test": "missing_user_deferral_fails_closed",
                "passed": result.returncode != 0
                and "deferral is not active" in result.stderr,
            }
        )

    with tempfile.TemporaryDirectory(
        prefix="split_release_finalizer_report_present_"
    ) as temporary:
        phase1, phase2 = make_fixture(Path(temporary))
        stable = (
            phase2
            / "reports"
            / "report_production"
            / "Florida_ED_Technical_Project_Dossier.pdf"
        )
        stable.write_bytes(b"not-a-real-pdf")
        result = run_finalizer(phase1, phase2)
        tests.append(
            {
                "test": "stable_report_file_during_deferral_fails_closed",
                "passed": result.returncode != 0
                and "Stable report files exist" in result.stderr,
            }
        )

    passed = sum(bool(test["passed"]) for test in tests)
    payload = {
        "status": "PASS" if passed == len(tests) else "FAIL",
        "tests_passed": passed,
        "tests_total": len(tests),
        "finalizer_sha256": digest(SCRIPT),
        "tests": tests,
    }
    output = (
        SCRIPT.parents[1]
        / "qa"
        / "finalize_analytical_release_status_unit_tests.json"
    )
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
