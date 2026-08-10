#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/56_finalize_analytical_release_status.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Finalize the split analytical/report release status without building reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def require_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase2",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--phase1", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    phase1 = args.phase1.resolve()

    complete_path = phase2 / "qa" / "complete_analysis_release_audit.json"
    multiplicity_path = (
        phase2 / "qa" / "independent_multiple_testing_audit.json"
    )
    immutability_path = (
        phase2 / "qa" / "final_phase1_immutability_audit.json"
    )
    deferral_path = (
        phase2
        / "qa"
        / "user_authorized_report_deferral_20260727T083046Z.json"
    )
    report_archive_path = (
        phase2
        / "audit_history"
        / "report_deferral_20260727T083046Z"
        / "ARCHIVE_MANIFEST.json"
    )
    supervisor_marker = (
        phase2
        / "qa"
        / "run_logs"
        / "post_canonical_supervisor"
        / "POST_CANONICAL_ANALYSIS_COMPLETE_PENDING_FINAL_RELEASE_AUDIT.log"
    )
    complete = require_json(complete_path)
    multiplicity = require_json(multiplicity_path)
    immutability = require_json(immutability_path)
    deferral = require_json(deferral_path)
    report_archive = require_json(report_archive_path)

    if complete.get("status") != "PASS":
        raise RuntimeError("Complete analytical release audit did not pass")
    if (
        not complete.get("checks_total")
        or complete.get("checks_passed") != complete.get("checks_total")
    ):
        raise RuntimeError("Complete release audit has a failing check")
    if multiplicity.get("status") != "PASS":
        raise RuntimeError("Independent global multiplicity audit did not pass")
    if immutability.get("status") != "PASS":
        raise RuntimeError("Final Phase 1 immutability audit did not pass")
    if (
        immutability.get("checksum_validation", {}).get("files_checked")
        != 573
        or immutability.get("checksum_validation", {}).get("files_failed")
        != 0
        or immutability.get("source_release_modified") is not False
    ):
        raise RuntimeError("Phase 1 file-level immutability proof is incomplete")
    release_status = deferral.get("release_status", {})
    if (
        release_status.get("REPORT_AND_PUBLIC_RELEASE")
        != "DEFERRED_BY_USER_BUDGET"
    ):
        raise RuntimeError("User-authorized report deferral is not active")
    if report_archive.get("status") != "PASS":
        raise RuntimeError("Frozen report-framework archive is not valid")
    if not supervisor_marker.is_file():
        raise FileNotFoundError(supervisor_marker)
    marker_text = supervisor_marker.read_text(encoding="utf-8")
    if "PASS corrected primary AMI and complete directional" not in marker_text:
        raise RuntimeError("Post-canonical completion marker is invalid")

    stable_patterns = [
        "Florida_ED_Technical_Project_Dossier.pdf",
        "Florida_ED_Technical_Project_Dossier.docx",
        "Florida_ED_Collaborator_Project_Report.pdf",
        "Florida_ED_Collaborator_Project_Report.docx",
    ]
    report_root = phase2 / "reports" / "report_production"
    stable_present = [
        name for name in stable_patterns if (report_root / name).is_file()
    ]
    if stable_present:
        raise RuntimeError(
            "Stable report files exist despite active deferral: "
            + ", ".join(stable_present)
        )

    phase1_build = phase1 / "build_manifest_final.json"
    phase2_release = require_json(phase2 / "qa" / "release_audit.json")
    phase1_build_sha = sha256_file(phase1_build)
    if phase1_build_sha != phase2_release.get("release_manifest_sha256"):
        raise RuntimeError("Phase 1 build-manifest hash changed")

    payload = {
        "status": "PASS",
        "created_utc": utc_now(),
        "status_version": "analytical_release_split_status_v1_20260727",
        "release_status": {
            "ANALYTICAL_RELEASE": "PASS_INDEPENDENTLY_AUDITED",
            "REPORT_AND_PUBLIC_RELEASE": "DEFERRED_BY_USER_BUDGET",
            "whole_project_complete": False,
        },
        "scope_statement": (
            "The frozen scientific analytical plan is complete and "
            "independently audited. Technical/collaborator reports and the "
            "public package remain user-deferred and are not part of this "
            "completed analytical release."
        ),
        "analytical_release_evidence": [
            {
                "path": str(complete_path),
                "sha256": sha256_file(complete_path),
                "status": complete.get("status"),
                "checks_passed": complete.get("checks_passed"),
                "checks_total": complete.get("checks_total"),
            },
            {
                "path": str(multiplicity_path),
                "sha256": sha256_file(multiplicity_path),
                "status": multiplicity.get("status"),
                "adjusted_datasets_verified": multiplicity.get(
                    "adjusted_datasets_verified"
                ),
            },
            {
                "path": str(immutability_path),
                "sha256": sha256_file(immutability_path),
                "status": immutability.get("status"),
                "files_checked": immutability.get(
                    "checksum_validation", {}
                ).get("files_checked"),
            },
            {
                "path": str(supervisor_marker),
                "sha256": sha256_file(supervisor_marker),
                "status": "PASS",
            },
        ],
        "phase1_immutability": {
            "build_manifest_sha256": phase1_build_sha,
            "files_rehashed": 573,
            "files_failed": 0,
            "phase1_write_operations": 0,
            "source_release_modified": False,
        },
        "report_deferral": {
            "authorization_checkpoint": str(deferral_path),
            "authorization_checkpoint_sha256": sha256_file(deferral_path),
            "preserved_report_archive_manifest": str(report_archive_path),
            "preserved_report_archive_manifest_sha256": sha256_file(
                report_archive_path
            ),
            "stable_report_files_present": stable_present,
            "reports_blocked_analytical_release": False,
        },
        "interpretation_controls": {
            "language": "association, not causation",
            "physician_race_measurement": (
                "algorithm-inferred full-name probability vector; not "
                "self-reported and not BISG"
            ),
            "partial_results_used_to_change_specifications": False,
        },
        "finalizer_script": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "source_release_modified": False,
        "phase1_modified": False,
    }
    output = (
        phase2
        / "qa"
        / "ANALYTICAL_RELEASE_COMPLETE_REPORTS_DEFERRED.json"
    )
    atomic_json(output, payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
