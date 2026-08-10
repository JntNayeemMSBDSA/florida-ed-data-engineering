# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/49_complete_analysis_release_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PRIMARY_OUTCOMES = [
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
]

ALL_DIRECTIONAL_OUTCOMES = [
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "high_procedure_flag",
    "em_acuity_proxy_level",
    "em_critical_care_flag",
    "routine_discharge_flag",
    "transfer_flag",
    "hospice_flag",
    "mortality_flag",
    "left_discontinued_care_flag",
    "aneschgs_real_2024",
    "cardiochgs_real_2024",
    "erchgs_real_2024",
    "gastrochgs_real_2024",
    "labchgs_real_2024",
    "lithochgs_real_2024",
    "medchgs_real_2024",
    "obserchgs_real_2024",
    "oprmchgs_real_2024",
    "othchgs_real_2024",
    "pharmchgs_real_2024",
    "radchgs_real_2024",
    "recovchgs_real_2024",
    "traumachgs_real_2024",
    "higher_discretion_procedure_count",
    "lower_discretion_procedure_count",
    "ambiguous_discretion_procedure_count",
    "any_higher_discretion_candidate_flag",
    "any_lower_discretion_candidate_flag",
    "higher_minus_lower_discretion_procedure_count",
    "any_higher_minus_any_lower_discretion_candidate",
]

DIRECTIONAL_FAMILIES = [
    "gender_dyads",
    "race_dyads",
    "intersectional_dyads",
]

EXPECTED_SAP_DEVIATION_IDS = [
    f"DEV-{number:03d}" for number in range(1, 20)
]


@dataclass(frozen=True)
class RequiredAudit:
    audit_id: str
    relative_path: str
    expected_status: str = "PASS"


REQUIRED_AUDITS = [
    RequiredAudit(
        "phase1_independent_release_validation",
        "../florida_ed_full_build_20260724/qa/independent_release_validation.json",
    ),
    RequiredAudit("phase2_read_only_release_audit", "qa/release_audit.json"),
    RequiredAudit(
        "final_phase1_file_immutability_audit",
        "qa/final_phase1_immutability_audit.json",
    ),
    RequiredAudit(
        "phase1_file_immutability_audit_tests",
        "qa/independent_phase1_immutability_audit_unit_tests.json",
    ),
    RequiredAudit(
        "phase1_file_immutability_code_freeze",
        "documentation/Independent_Phase1_Immutability_Audit_Code_FROZEN.json",
    ),
    RequiredAudit(
        "provider_measurement_gate",
        "qa/pre_estimation_measurement_gate.json",
    ),
    RequiredAudit(
        "primary_cohort_gate",
        "qa/cohort_validation_report.json",
    ),
    RequiredAudit(
        "historical_pre_estimation_gate",
        "qa/historical_provider_v2_pre_estimation_gate.json",
    ),
    RequiredAudit(
        "historical_independent_results_audit",
        "qa/independent_historical_results_audit.json",
    ),
    RequiredAudit(
        "definition_unit_tests",
        "qa/definition_unit_tests.json",
    ),
    RequiredAudit(
        "outcome_specific_policy_tests",
        "qa/outcome_specific_policy_unit_tests.json",
    ),
    RequiredAudit(
        "matrix_gate_binding_tests",
        "qa/matrix_gate_binding_unit_tests.json",
    ),
    RequiredAudit(
        "storage_safe_checkpoint_tests",
        "qa/storage_safe_checkpoint_unit_tests.json",
    ),
    RequiredAudit(
        "inference_engine_tests",
        "qa/inference_engine_unit_tests.json",
    ),
    RequiredAudit(
        "hdfe_engine_validation",
        "qa/hdfe_engine_validation.json",
    ),
    RequiredAudit(
        "demeaning_fallback_tests",
        "qa/demeaning_fallback_unit_tests.json",
    ),
    RequiredAudit(
        "demeaning_policy_audit_tests",
        "qa/demeaning_policy_audit_unit_tests.json",
    ),
    RequiredAudit(
        "primary_results_independent_audit",
        "qa/independent_primary_results_audit.json",
    ),
    RequiredAudit(
        "common_primary_checkpoint_audit",
        "qa/independent_common_primary_checkpoint_audit.json",
    ),
    RequiredAudit(
        "outcome_specific_results_audit",
        "qa/independent_outcome_specific_results_audit.json",
    ),
    RequiredAudit(
        "cohort_definition_results_audit",
        "qa/independent_cohort_definition_results_audit.json",
    ),
    RequiredAudit(
        "payer_heterogeneity_audit",
        "qa/independent_payer_heterogeneity_audit.json",
    ),
    RequiredAudit(
        "common_postmodel_results_audit",
        "qa/independent_common_postmodel_results_audit.json",
    ),
    RequiredAudit(
        "primary_ami_results_audit",
        "qa/independent_primary_ami_results_audit.json",
    ),
    RequiredAudit(
        "directional_pre_estimation_gate",
        "qa/directional_dyad_extension_pre_estimation_gate.json",
    ),
    RequiredAudit(
        "directional_base_independent_audit",
        "qa/independent_directional_dyad_base_audit.json",
    ),
    RequiredAudit(
        "directional_support_independent_audit",
        "qa/independent_directional_cell_support_audit.json",
    ),
    RequiredAudit(
        "directional_model_implementation_gate",
        "qa/directional_model_implementation_pre_estimation_gate.json",
    ),
    RequiredAudit(
        "directional_model_definition_tests",
        "qa/directional_model_definition_tests.json",
    ),
    RequiredAudit(
        "directional_execution_code_gate",
        "qa/directional_execution_code_gate.json",
    ),
    RequiredAudit(
        "directional_inference_engine_tests",
        "qa/directional_inference_engine_tests.json",
    ),
    RequiredAudit(
        "directional_measurement_sensitivity_tests",
        "qa/directional_measurement_sensitivity_tests.json",
    ),
    RequiredAudit(
        "directional_gender_results_audit",
        "qa/independent_directional_gender_results_audit.json",
    ),
    RequiredAudit(
        "directional_race_results_audit",
        "qa/independent_directional_race_results_audit.json",
    ),
    RequiredAudit(
        "directional_intersectional_results_audit",
        "qa/independent_directional_intersectional_results_audit.json",
    ),
    RequiredAudit(
        "directional_family_aggregate_audit",
        "qa/independent_directional_family_aggregate_audit.json",
    ),
    RequiredAudit(
        "directional_measurement_sensitivity_audit",
        "qa/independent_directional_measurement_sensitivity_audit.json",
    ),
    RequiredAudit(
        "global_multiple_testing_reconstruction_audit",
        "qa/independent_multiple_testing_audit.json",
    ),
    RequiredAudit(
        "global_multiple_testing_reconstruction_tests",
        "qa/independent_multiple_testing_audit_unit_tests.json",
    ),
    RequiredAudit(
        "global_multiple_testing_code_freeze",
        "documentation/Independent_Global_Multiplicity_Audit_Code_FROZEN.json",
    ),
    RequiredAudit(
        "complete_release_audit_unit_tests",
        "qa/complete_release_audit_unit_tests.json",
    ),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp, path)


def audit_status(payload: dict[str, Any]) -> str | None:
    direct = payload.get("status")
    if direct is not None:
        return str(direct)
    if payload.get("read_only_audit_passed") is True:
        return "PASS"
    return None


def relative_to_workspace(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve_required_path(
    phase2: Path,
    relative_path: str,
) -> Path:
    return (phase2 / relative_path).resolve()


def collect_release_files(phase2: Path) -> list[Path]:
    files: set[Path] = set()
    self_generated_qa = {
        "complete_analysis_release_audit.json",
        "complete_analysis_release_audit_checks.csv",
        "complete_analysis_release_directional_grid.csv",
        "complete_analysis_release_measurement_grid.csv",
    }
    results = phase2 / "results"
    if results.is_dir():
        for path in results.rglob("*"):
            if path.is_file():
                files.add(path.resolve())

    qa = phase2 / "qa"
    if qa.is_dir():
        for path in qa.rglob("*"):
            if not path.is_file():
                continue
            if "run_logs" in path.parts:
                continue
            if path.name.lower() in self_generated_qa:
                continue
            if path.suffix.lower() not in {".json", ".csv", ".md"}:
                continue
            files.add(path.resolve())

    documentation = phase2 / "documentation"
    if documentation.is_dir():
        for path in documentation.iterdir():
            if not path.is_file():
                continue
            lower = path.name.lower()
            if (
                "sap" in lower
                or "frozen" in lower
                or "checkpoint" in lower
                or "manifest" in lower
                or "audit" in lower
            ):
                files.add(path.resolve())

    return sorted(files, key=lambda p: p.as_posix().lower())


def status_and_hash(
    path: Path,
) -> tuple[bool, str | None, str | None, str | None]:
    if not path.is_file():
        return False, None, None, "missing"
    try:
        payload = load_json(path)
    except Exception as exc:
        return True, None, sha256(path), f"unreadable: {exc}"
    return True, audit_status(payload), sha256(path), None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed independent structural audit of the complete Phase 2 "
            "analysis release. This script validates audit state and provenance "
            "without interpreting estimates."
        )
    )
    parser.add_argument(
        "--phase2",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--phase1",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    workspace = phase2.parents[1]
    phase1 = (
        args.phase1.resolve()
        if args.phase1 is not None
        else workspace / "outputs" / "florida_ed_full_build_20260724"
    )
    qa = phase2 / "qa"
    manifest_root = phase2 / "manifest"
    documentation = phase2 / "documentation"

    checks: list[dict[str, Any]] = []
    evidence_files: set[Path] = set()

    def add(
        check_id: str,
        passed: bool,
        evidence: Any,
        severity: str = "BLOCKING",
    ) -> None:
        checks.append(
            {
                "check_id": check_id,
                "passed": bool(passed),
                "severity": severity,
                "evidence": evidence,
            }
        )

    required_rows: list[dict[str, Any]] = []
    for spec in REQUIRED_AUDITS:
        path = resolve_required_path(phase2, spec.relative_path)
        exists, observed_status, file_sha, error = status_and_hash(path)
        if exists:
            evidence_files.add(path)
        passed = (
            exists
            and error is None
            and observed_status == spec.expected_status
        )
        row = {
            "audit_id": spec.audit_id,
            "path": relative_to_workspace(path, workspace),
            "expected_status": spec.expected_status,
            "observed_status": observed_status or "",
            "sha256": file_sha or "",
            "error": error or "",
            "passed": passed,
        }
        required_rows.append(row)
        add(f"required_audit__{spec.audit_id}", passed, row)

    phase1_manifest = phase1 / "build_manifest_final.json"
    release_audit_path = qa / "release_audit.json"
    phase1_independent_path = phase1 / "qa" / "independent_release_validation.json"
    phase1_manifest_sha = (
        sha256(phase1_manifest) if phase1_manifest.is_file() else ""
    )
    phase2_release = (
        load_json(release_audit_path)
        if release_audit_path.is_file()
        else {}
    )
    phase1_independent = (
        load_json(phase1_independent_path)
        if phase1_independent_path.is_file()
        else {}
    )
    add(
        "phase1_manifest_unchanged_from_phase2_freeze",
        bool(phase1_manifest_sha)
        and phase1_manifest_sha
        == phase2_release.get("release_manifest_sha256"),
        {
            "phase1_manifest": relative_to_workspace(
                phase1_manifest,
                workspace,
            ),
            "current_sha256": phase1_manifest_sha,
            "phase2_frozen_sha256": phase2_release.get(
                "release_manifest_sha256",
                "",
            ),
        },
    )
    add(
        "phase1_independent_release_still_passes",
        phase1_independent.get("status") == "PASS"
        and phase1_independent.get("required_release_artifacts_passed") is True,
        {
            "status": phase1_independent.get("status"),
            "required_release_artifacts_passed": phase1_independent.get(
                "required_release_artifacts_passed"
            ),
            "source_release_modified_by_phase2": False,
        },
    )

    primary_marker = qa / "run_logs" / "RUN_PHASE2_REMAINING_SAFE_COMPLETE.log"
    downstream_marker = (
        qa
        / "run_logs"
        / "post_canonical_supervisor"
        / "POST_CANONICAL_ANALYSIS_COMPLETE_PENDING_FINAL_RELEASE_AUDIT.log"
    )
    downstream_failure = (
        qa
        / "run_logs"
        / "post_canonical_supervisor"
        / "POST_CANONICAL_ANALYSIS_FAILED_CLOSED.log"
    )
    marker_pass = (
        primary_marker.is_file()
        and "completed successfully"
        in primary_marker.read_text(encoding="utf-8", errors="replace")
        and downstream_marker.is_file()
        and (
            not downstream_failure.is_file()
            or downstream_failure.stat().st_mtime
            < downstream_marker.stat().st_mtime
        )
    )
    add(
        "canonical_and_postcanonical_completion_markers",
        marker_pass,
        {
            "canonical_marker": relative_to_workspace(
                primary_marker,
                workspace,
            ),
            "canonical_marker_exists": primary_marker.is_file(),
            "postcanonical_marker": relative_to_workspace(
                downstream_marker,
                workspace,
            ),
            "postcanonical_marker_exists": downstream_marker.is_file(),
            "newer_failure_marker": (
                downstream_failure.is_file()
                and (
                    not downstream_marker.is_file()
                    or downstream_failure.stat().st_mtime
                    >= downstream_marker.stat().st_mtime
                )
            ),
        },
    )

    directional_audit_root = qa / "directional_result_audits"
    compaction_root = qa / "directional_compaction"
    directional_expected = [
        f"{family}__{outcome}"
        for family in DIRECTIONAL_FAMILIES
        for outcome in ALL_DIRECTIONAL_OUTCOMES
    ]
    directional_rows: list[dict[str, Any]] = []
    for stem in directional_expected:
        audit_path = directional_audit_root / f"{stem}.json"
        compact_path = compaction_root / f"{stem}.json"
        audit_payload: dict[str, Any] = {}
        compact_payload: dict[str, Any] = {}
        audit_error = ""
        compact_error = ""
        try:
            audit_payload = load_json(audit_path)
        except Exception as exc:
            audit_error = str(exc)
        try:
            compact_payload = load_json(compact_path)
        except Exception as exc:
            compact_error = str(exc)
        if audit_path.is_file():
            evidence_files.add(audit_path)
        if compact_path.is_file():
            evidence_files.add(compact_path)
        row_pass = (
            audit_payload.get("status") == "PASS"
            and compact_payload.get("status") == "EXECUTED"
        )
        directional_rows.append(
            {
                "result_set": stem,
                "result_audit_status": audit_payload.get("status", ""),
                "compaction_status": compact_payload.get("status", ""),
                "result_audit_sha256": (
                    sha256(audit_path) if audit_path.is_file() else ""
                ),
                "compaction_sha256": (
                    sha256(compact_path) if compact_path.is_file() else ""
                ),
                "error": "; ".join(
                    value
                    for value in [audit_error, compact_error]
                    if value
                ),
                "passed": row_pass,
            }
        )
    add(
        "complete_directional_result_and_compaction_grid",
        len(directional_rows) == 99
        and all(row["passed"] for row in directional_rows),
        {
            "expected_result_sets": 99,
            "observed_result_sets": len(directional_rows),
            "passing_result_sets": sum(
                row["passed"] for row in directional_rows
            ),
            "failed_or_missing": [
                row["result_set"]
                for row in directional_rows
                if not row["passed"]
            ],
        },
    )

    measurement_expected = [
        f"{family}__{outcome}"
        for family in ["race_dyads", "intersectional_dyads"]
        for outcome in PRIMARY_OUTCOMES
    ]
    measurement_root = (
        qa / "directional_measurement_sensitivity_audits"
    )
    measurement_rows: list[dict[str, Any]] = []
    for stem in measurement_expected:
        path = measurement_root / f"{stem}.json"
        payload: dict[str, Any] = {}
        error = ""
        try:
            payload = load_json(path)
        except Exception as exc:
            error = str(exc)
        if path.is_file():
            evidence_files.add(path)
        measurement_rows.append(
            {
                "result_set": stem,
                "status": payload.get("status", ""),
                "sha256": sha256(path) if path.is_file() else "",
                "error": error,
                "passed": payload.get("status") == "PASS",
            }
        )
    add(
        "complete_directional_measurement_sensitivity_grid",
        len(measurement_rows) == 4
        and all(row["passed"] for row in measurement_rows),
        {
            "expected_result_sets": 4,
            "observed_result_sets": len(measurement_rows),
            "passing_result_sets": sum(
                row["passed"] for row in measurement_rows
            ),
            "failed_or_missing": [
                row["result_set"]
                for row in measurement_rows
                if not row["passed"]
            ],
        },
    )

    frozen_execution_path = (
        documentation / "Directional_Dyad_Execution_Code_FROZEN.json"
    )
    frozen_execution = (
        load_json(frozen_execution_path)
        if frozen_execution_path.is_file()
        else {}
    )
    if frozen_execution_path.is_file():
        evidence_files.add(frozen_execution_path)
    code_binding_rows: list[dict[str, Any]] = []
    for item in frozen_execution.get("code_inventory", []):
        path = phase2 / item["path"]
        observed_sha = sha256(path) if path.is_file() else ""
        code_binding_rows.append(
            {
                "path": item["path"],
                "expected_sha256": item.get("sha256", ""),
                "observed_sha256": observed_sha,
                "passed": observed_sha == item.get("sha256", ""),
            }
        )
        if path.is_file():
            evidence_files.add(path)
    add(
        "directional_execution_code_hashes_remain_frozen",
        frozen_execution.get("status") == "FROZEN_ESTIMATE_BLIND_PASS"
        and len(code_binding_rows) == 14
        and all(row["passed"] for row in code_binding_rows),
        {
            "manifest_sha256": (
                sha256(frozen_execution_path)
                if frozen_execution_path.is_file()
                else ""
            ),
            "expected_code_files": 14,
            "observed_code_files": len(code_binding_rows),
            "mismatches": [
                row["path"]
                for row in code_binding_rows
                if not row["passed"]
            ],
        },
    )

    global_multiplicity_freeze_path = (
        documentation
        / "Independent_Global_Multiplicity_Audit_Code_FROZEN.json"
    )
    global_multiplicity_freeze = (
        load_json(global_multiplicity_freeze_path)
        if global_multiplicity_freeze_path.is_file()
        else {}
    )
    if global_multiplicity_freeze_path.is_file():
        evidence_files.add(global_multiplicity_freeze_path)
    global_multiplicity_code_rows: list[dict[str, Any]] = []
    for item in global_multiplicity_freeze.get("code_inventory", []):
        path = phase2 / item["path"]
        observed_sha = sha256(path) if path.is_file() else ""
        global_multiplicity_code_rows.append(
            {
                "path": item["path"],
                "expected_sha256": item.get("sha256", ""),
                "observed_sha256": observed_sha,
                "passed": observed_sha == item.get("sha256", ""),
            }
        )
        if path.is_file():
            evidence_files.add(path)
    global_test = global_multiplicity_freeze.get(
        "synthetic_validation", {}
    )
    global_test_path = phase2 / global_test.get("path", "")
    global_test_sha = (
        sha256(global_test_path) if global_test_path.is_file() else ""
    )
    if global_test_path.is_file():
        evidence_files.add(global_test_path)
    add(
        "global_multiplicity_audit_code_hashes_remain_frozen",
        global_multiplicity_freeze.get("status") == "PASS"
        and global_multiplicity_freeze.get("freeze_state")
        == "FROZEN_ESTIMATE_BLIND_PASS"
        and global_multiplicity_freeze.get("estimate_blind") is True
        and global_multiplicity_freeze.get("real_result_values_viewed") is False
        and len(global_multiplicity_code_rows) == 3
        and all(row["passed"] for row in global_multiplicity_code_rows)
        and global_test.get("status") == "PASS"
        and global_test.get("tests_passed") == global_test.get("tests_total")
        and global_test_sha == global_test.get("sha256", ""),
        {
            "manifest_sha256": (
                sha256(global_multiplicity_freeze_path)
                if global_multiplicity_freeze_path.is_file()
                else ""
            ),
            "expected_code_files": 3,
            "observed_code_files": len(global_multiplicity_code_rows),
            "code_mismatches": [
                row["path"]
                for row in global_multiplicity_code_rows
                if not row["passed"]
            ],
            "unit_test_expected_sha256": global_test.get("sha256", ""),
            "unit_test_observed_sha256": global_test_sha,
        },
    )

    phase1_immutability_freeze_path = (
        documentation
        / "Independent_Phase1_Immutability_Audit_Code_FROZEN.json"
    )
    phase1_immutability_freeze = (
        load_json(phase1_immutability_freeze_path)
        if phase1_immutability_freeze_path.is_file()
        else {}
    )
    if phase1_immutability_freeze_path.is_file():
        evidence_files.add(phase1_immutability_freeze_path)
    phase1_immutability_code_rows: list[dict[str, Any]] = []
    for item in phase1_immutability_freeze.get("code_inventory", []):
        path = phase2 / item["path"]
        observed_sha = sha256(path) if path.is_file() else ""
        phase1_immutability_code_rows.append(
            {
                "path": item["path"],
                "expected_sha256": item.get("sha256", ""),
                "observed_sha256": observed_sha,
                "passed": observed_sha == item.get("sha256", ""),
            }
        )
        if path.is_file():
            evidence_files.add(path)
    phase1_test = phase1_immutability_freeze.get(
        "synthetic_validation", {}
    )
    phase1_test_path = phase2 / phase1_test.get("path", "")
    phase1_test_sha = (
        sha256(phase1_test_path) if phase1_test_path.is_file() else ""
    )
    if phase1_test_path.is_file():
        evidence_files.add(phase1_test_path)
    phase1_roots = phase1_immutability_freeze.get(
        "frozen_phase1_roots", {}
    )
    frozen_file_manifest_path = (
        phase2 / phase1_roots.get("file_manifest_path", "")
    ).resolve()
    frozen_build_manifest_path = (
        phase2 / phase1_roots.get("build_manifest_path", "")
    ).resolve()
    frozen_file_manifest_sha = (
        sha256(frozen_file_manifest_path)
        if frozen_file_manifest_path.is_file()
        else ""
    )
    frozen_build_manifest_sha = (
        sha256(frozen_build_manifest_path)
        if frozen_build_manifest_path.is_file()
        else ""
    )
    phase1_source_binding = phase1_immutability_freeze.get(
        "independent_pre_deferral_source_binding", {}
    )
    phase1_source_binding_path = (
        phase2 / phase1_source_binding.get("path", "")
    ).resolve()
    phase1_source_binding_sha = (
        sha256(phase1_source_binding_path)
        if phase1_source_binding_path.is_file()
        else ""
    )
    add(
        "phase1_immutability_audit_code_and_roots_remain_frozen",
        phase1_immutability_freeze.get("status") == "PASS"
        and phase1_immutability_freeze.get("freeze_state")
        == "FROZEN_PRE_FINAL_AUDIT_PASS"
        and len(phase1_immutability_code_rows) == 2
        and all(row["passed"] for row in phase1_immutability_code_rows)
        and phase1_test.get("status") == "PASS"
        and phase1_test.get("tests_passed") == phase1_test.get("tests_total")
        and phase1_test_sha == phase1_test.get("sha256", "")
        and frozen_file_manifest_sha
        == phase1_roots.get("file_manifest_sha256", "")
        and phase1_roots.get("file_manifest_rows") == 573
        and frozen_build_manifest_sha
        == phase1_roots.get("build_manifest_sha256", "")
        and phase1_source_binding_sha
        == phase1_source_binding.get("sha256", "")
        and phase1_source_binding.get("phase1_file_manifest_sha256")
        == phase1_roots.get("file_manifest_sha256"),
        {
            "manifest_sha256": (
                sha256(phase1_immutability_freeze_path)
                if phase1_immutability_freeze_path.is_file()
                else ""
            ),
            "expected_code_files": 2,
            "observed_code_files": len(phase1_immutability_code_rows),
            "code_mismatches": [
                row["path"]
                for row in phase1_immutability_code_rows
                if not row["passed"]
            ],
            "file_manifest_expected_sha256": phase1_roots.get(
                "file_manifest_sha256", ""
            ),
            "file_manifest_observed_sha256": frozen_file_manifest_sha,
            "build_manifest_expected_sha256": phase1_roots.get(
                "build_manifest_sha256", ""
            ),
            "build_manifest_observed_sha256": frozen_build_manifest_sha,
            "pre_deferral_source_manifest_expected_sha256": (
                phase1_source_binding.get("sha256", "")
            ),
            "pre_deferral_source_manifest_observed_sha256": (
                phase1_source_binding_sha
            ),
        },
    )

    sap_path = documentation / "SAP_deviation_log.csv"
    sap_ids: list[str] = []
    if sap_path.is_file():
        evidence_files.add(sap_path)
        with sap_path.open("r", encoding="utf-8-sig", newline="") as stream:
            sap_ids = [
                str(row.get("deviation_id", "")).strip()
                for row in csv.DictReader(stream)
            ]
    add(
        "sap_deviation_history_complete_through_dev019",
        sap_ids == EXPECTED_SAP_DEVIATION_IDS,
        {
            "expected_ids": EXPECTED_SAP_DEVIATION_IDS,
            "observed_ids": sap_ids,
        },
    )

    source_release_modified_claims: list[dict[str, Any]] = []
    for path in sorted(evidence_files):
        if path.suffix.lower() != ".json":
            continue
        try:
            payload = load_json(path)
        except Exception:
            continue
        if "source_release_modified" in payload:
            source_release_modified_claims.append(
                {
                    "path": relative_to_workspace(path, workspace),
                    "value": payload["source_release_modified"],
                }
            )
    add(
        "all_audits_report_phase1_unmodified",
        bool(source_release_modified_claims)
        and all(
            row["value"] is False
            for row in source_release_modified_claims
        ),
        source_release_modified_claims,
    )

    release_files = collect_release_files(phase2)
    release_file_rows: list[dict[str, Any]] = []
    for path in release_files:
        release_file_rows.append(
            {
                "workspace_relative_path": relative_to_workspace(
                    path,
                    workspace,
                ),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    release_manifest = {
        "manifest_id": "florida_ed_complete_analysis_release_manifest_v1",
        "created_utc": utc_now(),
        "scope": (
            "Final aggregate results, QA/audit artifacts excluding run logs, "
            "and critical frozen/checkpoint documentation. Encounter-level "
            "data and model matrices are intentionally represented by their "
            "validated upstream manifests rather than re-inventoried here."
        ),
        "file_count": len(release_file_rows),
        "files": release_file_rows,
    }
    manifest_path = (
        manifest_root / "Complete_Analysis_Release_Manifest.json"
    )
    atomic_json(manifest_path, release_manifest)

    all_passed = all(check["passed"] for check in checks)
    audit = {
        "audit_id": "florida_ed_complete_analysis_release_audit_v1",
        "created_utc": utc_now(),
        "status": "PASS" if all_passed else "FAIL",
        "scope": (
            "Independent fail-closed structural, provenance, grid-completeness, "
            "and audit-chain validation. The audit does not interpret effect "
            "estimates."
        ),
        "phase1_path": relative_to_workspace(phase1, workspace),
        "phase2_path": relative_to_workspace(phase2, workspace),
        "checks_passed": sum(check["passed"] for check in checks),
        "checks_total": len(checks),
        "checks": checks,
        "required_audits": required_rows,
        "directional_result_sets_expected": 99,
        "directional_result_sets_passed": sum(
            row["passed"] for row in directional_rows
        ),
        "directional_measurement_sets_expected": 4,
        "directional_measurement_sets_passed": sum(
            row["passed"] for row in measurement_rows
        ),
        "release_manifest": relative_to_workspace(
            manifest_path,
            workspace,
        ),
        "release_manifest_sha256": sha256(manifest_path),
        "source_release_modified": False,
        "result_interpretation_performed": False,
        "report_finalization_authorized_by_this_audit": all_passed,
    }
    audit_path = qa / "complete_analysis_release_audit.json"
    atomic_json(audit_path, audit)

    checks_path = qa / "complete_analysis_release_audit_checks.csv"
    atomic_csv(
        checks_path,
        [
            {
                "check_id": row["check_id"],
                "passed": row["passed"],
                "severity": row["severity"],
                "evidence_json": json.dumps(
                    row["evidence"],
                    sort_keys=True,
                    ensure_ascii=False,
                ),
            }
            for row in checks
        ],
        ["check_id", "passed", "severity", "evidence_json"],
    )

    directional_path = (
        qa / "complete_analysis_release_directional_grid.csv"
    )
    atomic_csv(
        directional_path,
        directional_rows,
        list(directional_rows[0]),
    )

    measurement_path = (
        qa / "complete_analysis_release_measurement_grid.csv"
    )
    atomic_csv(
        measurement_path,
        measurement_rows,
        list(measurement_rows[0]),
    )

    summary_path = (
        documentation / "Complete_Analysis_Release_Audit.md"
    )
    failed = [row["check_id"] for row in checks if not row["passed"]]
    atomic_text(
        summary_path,
        "\n".join(
            [
                "# Complete Analysis Release Audit",
                "",
                f"- Created (UTC): `{audit['created_utc']}`",
                f"- Status: **{audit['status']}**",
                (
                    f"- Checks passed: {audit['checks_passed']} of "
                    f"{audit['checks_total']}"
                ),
                (
                    "- Directional result sets: "
                    f"{audit['directional_result_sets_passed']} of 99"
                ),
                (
                    "- Directional race-measurement sensitivity sets: "
                    f"{audit['directional_measurement_sets_passed']} of 4"
                ),
                (
                    "- Phase 1 modified by this workflow: "
                    f"`{audit['source_release_modified']}`"
                ),
                "",
                "This audit validates release structure, provenance, frozen "
                "code bindings, expected result grids, compaction records, and "
                "the complete independent-audit chain. It does not interpret "
                "effect estimates.",
                "",
                "## Blocking failures",
                "",
                *(
                    [f"- `{check_id}`" for check_id in failed]
                    if failed
                    else ["- None."]
                ),
                "",
                "The two reports may move from controlled outlines to findings "
                "production only when this audit reports `PASS` and the report "
                "production gate independently confirms every downstream report "
                "audit.",
                "",
            ]
        ),
    )

    print(
        json.dumps(
            {
                "status": audit["status"],
                "checks_passed": audit["checks_passed"],
                "checks_total": audit["checks_total"],
                "directional_result_sets_passed": audit[
                    "directional_result_sets_passed"
                ],
                "directional_measurement_sets_passed": audit[
                    "directional_measurement_sets_passed"
                ],
                "release_manifest_files": release_manifest["file_count"],
                "audit_path": str(audit_path),
            },
            indent=2,
        )
    )
    if not all_passed:
        raise SystemExit(
            "Complete analysis release audit failed closed; reports remain locked."
        )


if __name__ == "__main__":
    main()
