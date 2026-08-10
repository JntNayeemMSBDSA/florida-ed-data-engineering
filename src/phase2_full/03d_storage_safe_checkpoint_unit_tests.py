#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/03d_storage_safe_checkpoint_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic fail-closed tests for model audit, compaction, and postmodel QA.

These tests use no Florida encounter data and produce no real-data estimates.
They exercise the production scripts in a disposable workspace before large
model matrices can be compacted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROVIDER_VERSION = "provider_master_v2_full_name_race_v1"
MEMMAPS = (
    "raw_design.float64.mmap",
    "model_outcomes.float64.mmap",
    "fe_codes.uint64.mmap",
    "cluster_codes.uint64.mmap",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def run_script(
    script: Path,
    arguments: list[str],
    expect_success: bool,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    succeeded = result.returncode == 0
    if succeeded != expect_success:
        raise RuntimeError(
            f"Unexpected return code from {script.name}: {result.returncode}\n"
            f"STDOUT:\n{result.stdout[-4000:]}\n"
            f"STDERR:\n{result.stderr[-4000:]}"
        )
    return result


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    details: Any = None,
) -> None:
    checks.append(
        {
            "check_id": check_id,
            "passed": bool(passed),
            "details": details,
        }
    )
    if not passed:
        raise RuntimeError(f"Synthetic unit check failed: {check_id}")


def create_fake_auditor(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
def audit_cohort(
    phase2,
    matrix_root,
    primary_scratch,
    cohort,
    row_chunk,
    matrix_id=None,
    results_root=None,
    scratch_id=None,
):
    return (
        [
            {
                "cohort": cohort,
                "matrix_id": matrix_id,
                "analysis_sample_policy": "los_outcome",
                "eligibility_policy": "primary",
                "audit_check": "synthetic_independent_recomputation",
                "value": 0,
                "tolerance": 0,
                "passed": True,
                "details": "No real data used.",
            }
        ],
        {
            "synthetic_fixture": True,
            "row_chunk": row_chunk,
            "scratch_id": scratch_id,
        },
    )
""".lstrip(),
        encoding="utf-8",
    )


def checkpoint_compaction_tests(
    source_phase2: Path,
    fixture_phase2: Path,
    workspace: Path,
    checks: list[dict[str, Any]],
) -> None:
    scripts = source_phase2 / "scripts"
    qa = fixture_phase2 / "qa"
    matrix_root = fixture_phase2 / "analysis_data" / "model_matrices"
    matrix_id = "race__los"
    matrix_folder = matrix_root / matrix_id
    scratch_root = (
        workspace
        / "tmp"
        / "florida_ed_concordance_analysis_20260726"
        / "synthetic_model_scratch"
    )
    scratch_folder = scratch_root / "race"
    results_root = (
        fixture_phase2 / "results" / "outcome_specific_primary" / "los"
    )
    result_folder = results_root / "race"
    provider_gate = qa / "pre_estimation_measurement_gate.json"
    cohort_gate = qa / "cohort_validation_report.json"
    gender_checkpoint = qa / "provider_gender_measurement_checkpoint.json"
    write_json(provider_gate, {"status": "PASS", "synthetic": True})
    write_json(cohort_gate, {"status": "PASS", "synthetic": True})
    write_json(gender_checkpoint, {"status": "PASS", "synthetic": True})
    gate_hashes = {
        "provider_gate_sha256": sha256_file(provider_gate),
        "cohort_gate_sha256": sha256_file(cohort_gate),
        "gender_checkpoint_sha256": sha256_file(gender_checkpoint),
    }

    matrix_folder.mkdir(parents=True, exist_ok=True)
    matrix_manifest = {
        "cohort": "race",
        "matrix_id": matrix_id,
        "analysis_sample_policy": "los_outcome",
        "eligibility_policy": "primary",
        "primary_outcomes": ["los_hours_primary_0_168"],
        "outcomes": ["los_hours_primary_0_168"],
        "outcome_specific_sample": True,
        "outcome_specific_confirmatory_sample": True,
        "confirmatory_designated": True,
        "provider_measurement_version": PROVIDER_VERSION,
        "provider_gate_path": str(provider_gate.resolve()),
        "cohort_gate_path": str(cohort_gate.resolve()),
        "gender_checkpoint_path": str(gender_checkpoint.resolve()),
        **gate_hashes,
    }
    write_json(matrix_folder / "matrix_manifest.json", matrix_manifest)
    for index, name in enumerate(MEMMAPS, start=1):
        (matrix_folder / name).write_bytes(bytes([index]) * 64)
    scratch_folder.mkdir(parents=True, exist_ok=True)
    (scratch_folder / "synthetic_scratch.bin").write_bytes(b"scratch")

    result_folder.mkdir(parents=True, exist_ok=True)
    result_manifest = {
        "cohort": "race",
        "matrix_id": matrix_id,
        "analysis_sample_policy": "los_outcome",
        "eligibility_policy": "primary",
        "outcome_specific_sample": True,
        "outcome_specific_confirmatory_sample": True,
        "confirmatory_designated": True,
        "provider_measurement_version": PROVIDER_VERSION,
        **gate_hashes,
    }
    write_json(result_folder / "primary_models_manifest.json", result_manifest)
    coefficients = result_folder / "primary_model_coefficients.csv"
    original_coefficients = "term,estimate\nsynthetic_interaction,0.125\n"
    coefficients.write_text(original_coefficients, encoding="utf-8")
    create_fake_auditor(
        fixture_phase2 / "scripts" / "30_independent_primary_results_audit.py"
    )

    audit_id = "synthetic_outcome_specific_race_los"
    checkpoint_args = [
        "--phase2",
        str(fixture_phase2),
        "--matrix-root",
        str(matrix_root),
        "--matrix-id",
        matrix_id,
        "--primary-scratch",
        str(scratch_root),
        "--scratch-id",
        "race",
        "--results-root",
        str(results_root),
        "--cohort",
        "race",
        "--audit-id",
        audit_id,
        "--expected-analysis-sample",
        "los_outcome",
        "--expected-eligibility-policy",
        "primary",
        "--expected-outcome",
        "los_hours_primary_0_168",
        "--expected-confirmatory",
        "true",
        "--row-chunk",
        "17",
    ]
    run_script(
        scripts / "30e_checkpoint_primary_matrix_audit.py",
        checkpoint_args,
        expect_success=True,
    )
    checkpoint_path = qa / "model_audit_checkpoints" / f"{audit_id}.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    add_check(
        checks,
        "checkpoint_passes_and_binds_live_gates",
        checkpoint.get("all_passed") is True
        and checkpoint.get("live_gate_hashes") == gate_hashes,
        checkpoint.get("live_gate_hashes"),
    )

    compact_base_args = [
        "--phase2",
        str(fixture_phase2),
        "--checkpoint-json",
        str(checkpoint_path),
        "--matrix-root",
        str(matrix_root),
        "--matrix-id",
        matrix_id,
        "--scratch-dir",
        str(scratch_folder),
    ]
    run_script(
        scripts / "32_compact_validated_model_intermediates.py",
        compact_base_args,
        expect_success=False,
    )
    add_check(
        checks,
        "compaction_requires_explicit_execute",
        all((matrix_folder / name).exists() for name in MEMMAPS)
        and scratch_folder.exists(),
    )

    coefficients.write_text(
        original_coefficients + "tampered,9.99\n", encoding="utf-8"
    )
    run_script(
        scripts / "32_compact_validated_model_intermediates.py",
        [*compact_base_args, "--execute"],
        expect_success=False,
    )
    add_check(
        checks,
        "result_tamper_blocks_compaction_without_deletion",
        all((matrix_folder / name).exists() for name in MEMMAPS)
        and scratch_folder.exists(),
    )
    coefficients.write_text(original_coefficients, encoding="utf-8")

    run_script(
        scripts / "32_compact_validated_model_intermediates.py",
        [*compact_base_args, "--execute"],
        expect_success=True,
    )
    compaction_path = (
        qa / "model_intermediate_compaction" / f"{matrix_id}.json"
    )
    compaction = json.loads(compaction_path.read_text(encoding="utf-8"))
    add_check(
        checks,
        "validated_compaction_removes_only_intermediates",
        compaction.get("compaction_passed") is True
        and not any((matrix_folder / name).exists() for name in MEMMAPS)
        and not scratch_folder.exists()
        and (matrix_folder / "matrix_manifest.json").exists()
        and coefficients.exists(),
        compaction,
    )

    aggregate_args = [
        "--phase2",
        str(fixture_phase2),
        "--expected-audit-ids",
        audit_id,
        "--output-stem",
        "synthetic_aggregate_audit",
        "--audit-id",
        "synthetic_aggregate_v1",
    ]
    run_script(
        scripts / "30f_aggregate_model_audit_checkpoints.py",
        aggregate_args,
        expect_success=True,
    )
    aggregate = json.loads(
        (qa / "synthetic_aggregate_audit.json").read_text(encoding="utf-8")
    )
    add_check(
        checks,
        "aggregate_revalidates_checkpoint_results_and_compaction",
        aggregate.get("all_passed") is True,
        aggregate,
    )

    original_gate = provider_gate.read_text(encoding="utf-8")
    write_json(provider_gate, {"status": "PASS", "synthetic": "changed"})
    run_script(
        scripts / "30f_aggregate_model_audit_checkpoints.py",
        aggregate_args,
        expect_success=False,
    )
    failed_aggregate = json.loads(
        (qa / "synthetic_aggregate_audit.json").read_text(encoding="utf-8")
    )
    add_check(
        checks,
        "live_gate_change_invalidates_aggregate",
        failed_aggregate.get("all_passed") is False,
    )
    provider_gate.write_text(original_gate, encoding="utf-8")


def common_artifact_definitions(
    fixture_phase2: Path,
) -> list[dict[str, Any]]:
    results = fixture_phase2 / "results"
    return [
        {
            "cohort": "race",
            "manifest": (
                results
                / "race_sensitivities"
                / "race_threshold_probability_manifest.json"
            ),
            "csvs": [
                "race_threshold_probability_coefficients.csv",
                "race_threshold_probability_interactions.csv",
            ],
        },
        *[
            {
                "cohort": cohort,
                "manifest": (
                    results
                    / "heterogeneity"
                    / cohort
                    / "heterogeneity_manifest.json"
                ),
                "csvs": [
                    "heterogeneity_model_coefficients.csv",
                    "heterogeneity_interaction_differences.csv",
                    "heterogeneity_model_manifest.csv",
                ],
            }
            for cohort in ("race", "sex_gender")
        ],
        *[
            {
                "cohort": cohort,
                "manifest": (
                    results
                    / "classified_subjectivity"
                    / cohort
                    / "classified_subjectivity_manifest.json"
                ),
                "csvs": [
                    "classified_subjectivity_model_coefficients.csv",
                    "classified_subjectivity_interaction_differences.csv",
                ],
            }
            for cohort in ("race", "sex_gender")
        ],
        {
            "cohort": "race",
            "manifest": (
                results / "intersectional" / "intersectional_manifest.json"
            ),
            "csvs": [
                "intersectional_model_coefficients.csv",
                "intersectional_16_cell_descriptive.csv",
            ],
        },
        {
            "cohort": "race",
            "manifest": (
                results
                / "race_proxy_multiple_imputation"
                / "race_proxy_mi_manifest.json"
            ),
            "csvs": [
                "race_proxy_mi_interaction_estimates.csv",
                "race_proxy_mi_pooled_results.csv",
            ],
        },
        *[
            {
                "cohort": cohort,
                "manifest": (
                    results
                    / "negative_control"
                    / cohort
                    / "negative_control_manifest.json"
                ),
                "csvs": ["negative_control_coefficients.csv"],
            }
            for cohort in ("race", "sex_gender")
        ],
        *[
            {
                "cohort": cohort,
                "manifest": (
                    results
                    / "outcome_appropriate_glm"
                    / cohort
                    / "_SUCCESS.json"
                ),
                "csvs": ["outcome_appropriate_glm_sensitivities.csv"],
            }
            for cohort in ("race", "sex_gender")
        ],
        *[
            {
                "cohort": cohort,
                "manifest": (
                    results
                    / "leave_one_year_out"
                    / cohort
                    / "leave_one_year_out_manifest.json"
                ),
                "csvs": [
                    "leave_one_year_out_interactions.csv",
                    "leave_one_year_out_summary.csv",
                ],
            }
            for cohort in ("race", "sex_gender")
        ],
        *[
            {
                "cohort": cohort,
                "manifest": (
                    results
                    / "exact_subset_sensitivities"
                    / cohort
                    / "exact_subset_sensitivities_manifest.json"
                ),
                "csvs": ["exact_subset_interactions.csv"],
            }
            for cohort in ("race", "sex_gender")
        ],
        *[
            {
                "cohort": cohort,
                "manifest": (
                    results
                    / "influential_facility"
                    / cohort
                    / "influential_facility_exact_refits_manifest.json"
                ),
                "csvs": [
                    "influential_facility_candidates.csv",
                    "influential_facility_exact_refits.csv",
                    "influential_facility_exact_refit_summary.csv",
                ],
            }
            for cohort in ("race", "sex_gender")
        ],
        {
            "cohort": "race",
            "manifest": (
                results
                / "payer_category_heterogeneity"
                / "payer_category_heterogeneity_manifest.json"
            ),
            "csvs": [
                "payer_category_heterogeneity_coefficients.csv",
                "payer_category_interaction_differences.csv",
                "payer_category_heterogeneity_diagnostics.csv",
            ],
        },
    ]


def common_postmodel_tests(
    source_phase2: Path,
    fixture_phase2: Path,
    checks: list[dict[str, Any]],
) -> None:
    scripts = source_phase2 / "scripts"
    qa = fixture_phase2 / "qa"
    matrix_root = fixture_phase2 / "analysis_data" / "model_matrices"
    provider_gate = qa / "pre_estimation_measurement_gate.json"
    cohort_gate = qa / "cohort_validation_report.json"
    gender_checkpoint = qa / "provider_gender_measurement_checkpoint.json"
    write_json(provider_gate, {"status": "PASS", "synthetic": True})
    write_json(cohort_gate, {"status": "PASS", "synthetic": True})
    write_json(gender_checkpoint, {"status": "PASS", "synthetic": True})
    gate_hashes = {
        "provider_gate_sha256": sha256_file(provider_gate),
        "cohort_gate_sha256": sha256_file(cohort_gate),
        "gender_checkpoint_sha256": sha256_file(gender_checkpoint),
    }
    bindings: dict[str, dict[str, Any]] = {}
    for cohort in ("race", "sex_gender"):
        manifest_path = matrix_root / cohort / "matrix_manifest.json"
        payload = {
            "cohort": cohort,
            "matrix_id": cohort,
            "analysis_sample_policy": "common_primary",
            "eligibility_policy": "primary",
            "outcome_specific_sample": False,
            "confirmatory_designated": False,
            "provider_measurement_version": PROVIDER_VERSION,
            "provider_gate_path": str(provider_gate.resolve()),
            "cohort_gate_path": str(cohort_gate.resolve()),
            "gender_checkpoint_path": str(gender_checkpoint.resolve()),
            **gate_hashes,
        }
        write_json(manifest_path, payload)
        bindings[cohort] = {
            "provider_measurement_version": PROVIDER_VERSION,
            "matrix_id": cohort,
            "analysis_sample_policy": "common_primary",
            "eligibility_policy": "primary",
            "provider_gate_path": str(provider_gate.resolve()),
            "provider_gate_sha256": gate_hashes["provider_gate_sha256"],
            "cohort_gate_path": str(cohort_gate.resolve()),
            "cohort_gate_sha256": gate_hashes["cohort_gate_sha256"],
            "gender_checkpoint_path": str(gender_checkpoint.resolve()),
            "gender_checkpoint_sha256": gate_hashes[
                "gender_checkpoint_sha256"
            ],
            "matrix_manifest_path": str(manifest_path.resolve()),
            "matrix_manifest_sha256": sha256_file(manifest_path),
        }

    artifacts = common_artifact_definitions(fixture_phase2)
    for item in artifacts:
        manifest_path = Path(item["manifest"])
        write_json(
            manifest_path,
            {"status": "PASS", **bindings[str(item["cohort"])]},
        )
        for csv_name in item["csvs"]:
            csv_path = manifest_path.parent / csv_name
            csv_path.write_text(
                "term,estimate\nsynthetic,0.0\n", encoding="utf-8"
            )

    arguments = [
        "--phase2",
        str(fixture_phase2),
        "--matrix-root",
        str(matrix_root),
    ]
    run_script(
        scripts / "33_audit_common_postmodels.py",
        arguments,
        expect_success=True,
    )
    audit_path = qa / "independent_common_postmodel_results_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    add_check(
        checks,
        "common_postmodel_complete_binding_inventory_passes",
        audit.get("all_passed") is True
        and int(audit.get("failed_checks", -1)) == 0,
        {
            "checks": audit.get("checks"),
            "inventory": len(audit.get("artifact_inventory", [])),
        },
    )

    tampered_manifest = Path(artifacts[0]["manifest"])
    original = tampered_manifest.read_text(encoding="utf-8")
    tampered = json.loads(original)
    tampered["provider_gate_sha256"] = "tampered"
    write_json(tampered_manifest, tampered)
    run_script(
        scripts / "33_audit_common_postmodels.py",
        arguments,
        expect_success=False,
    )
    failed_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    add_check(
        checks,
        "common_postmodel_binding_tamper_fails_closed",
        failed_audit.get("all_passed") is False
        and int(failed_audit.get("failed_checks", 0)) >= 1,
    )
    tampered_manifest.write_text(original, encoding="utf-8")
    run_script(
        scripts / "33_audit_common_postmodels.py",
        arguments,
        expect_success=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()

    source_phase2 = args.phase2.resolve()
    required_scripts = [
        source_phase2 / "scripts" / name
        for name in (
            "30e_checkpoint_primary_matrix_audit.py",
            "32_compact_validated_model_intermediates.py",
            "30f_aggregate_model_audit_checkpoints.py",
            "33_audit_common_postmodels.py",
        )
    ]
    missing = [str(path) for path in required_scripts if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing production scripts: {missing}")

    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="p2ut_",
    ) as temporary:
        workspace = Path(temporary) / "workspace"
        fixture_phase2 = (
            workspace / "outputs" / "florida_ed_concordance_analysis_20260726"
        )
        checkpoint_compaction_tests(
            source_phase2, fixture_phase2, workspace, checks
        )
        common_postmodel_tests(source_phase2, fixture_phase2, checks)

    payload = {
        "created_utc": now_utc(),
        "test_id": "storage_safe_checkpoint_unit_tests_v1",
        "synthetic_only": True,
        "real_data_estimates_generated": False,
        "checks": len(checks),
        "passed_checks": sum(int(item["passed"]) for item in checks),
        "failed_checks": sum(int(not item["passed"]) for item in checks),
        "all_passed": all(item["passed"] for item in checks),
        "check_results": checks,
        "production_scripts": [
            {
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for path in required_scripts
        ],
    }
    output = source_phase2 / "qa" / "storage_safe_checkpoint_unit_tests.json"
    atomic_json(output, payload)
    print(json.dumps(payload, indent=2))
    if not payload["all_passed"]:
        raise RuntimeError("Storage-safe checkpoint unit tests failed")


if __name__ == "__main__":
    main()
