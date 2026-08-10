#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/33_audit_common_postmodels.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Audit all common-primary postmodel outputs before matrix compaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PROVIDER_VERSION = "provider_master_v2_full_name_race_v1"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def add_check(
    rows: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    details: Any,
    severity: str = "critical",
) -> None:
    rows.append(
        {
            "check_id": check_id,
            "severity": severity,
            "passed": bool(passed),
            "details": (
                details
                if isinstance(details, str)
                else json.dumps(details, sort_keys=True, default=str)
            ),
        }
    )


def binding_expected(
    matrix_manifest: dict[str, Any],
    matrix_manifest_path: Path,
) -> dict[str, Any]:
    return {
        "provider_measurement_version": PROVIDER_VERSION,
        "matrix_id": matrix_manifest["matrix_id"],
        "analysis_sample_policy": "common_primary",
        "eligibility_policy": "primary",
        "provider_gate_path": str(
            Path(matrix_manifest["provider_gate_path"]).resolve()
        ),
        "provider_gate_sha256": matrix_manifest["provider_gate_sha256"],
        "cohort_gate_path": str(
            Path(matrix_manifest["cohort_gate_path"]).resolve()
        ),
        "cohort_gate_sha256": matrix_manifest["cohort_gate_sha256"],
        "gender_checkpoint_path": str(
            Path(matrix_manifest["gender_checkpoint_path"]).resolve()
        ),
        "gender_checkpoint_sha256": matrix_manifest[
            "gender_checkpoint_sha256"
        ],
        "matrix_manifest_path": str(matrix_manifest_path.resolve()),
        "matrix_manifest_sha256": sha256_file(matrix_manifest_path),
    }


def manifest_passed(payload: dict[str, Any]) -> bool:
    if "status" in payload:
        return payload["status"] == "PASS"
    if "all_passed" in payload:
        return bool(payload["all_passed"])
    if "all_models_passed" in payload:
        return bool(payload["all_models_passed"])
    if "all_fitted_models_converged" in payload:
        return bool(payload["all_fitted_models_converged"])
    return False


def csv_profile(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path)
    numeric = frame.select_dtypes(include="number")
    infinite = 0
    if not numeric.empty:
        infinite = int(
            numeric.isin([float("inf"), float("-inf")]).to_numpy().sum()
        )
    return {
        "rows": len(frame),
        "columns": frame.columns.tolist(),
        "infinite_numeric_values": infinite,
        "sha256": sha256_file(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    matrix_root = args.matrix_root.resolve()
    qa = phase2 / "qa"
    results = phase2 / "results"
    rows: list[dict[str, Any]] = []

    provider_gate_path = qa / "pre_estimation_measurement_gate.json"
    cohort_gate_path = qa / "cohort_validation_report.json"
    gender_checkpoint_path = (
        qa / "provider_gender_measurement_checkpoint.json"
    )
    live_gates: dict[str, dict[str, Any]] = {}
    for gate_id, path in (
        ("provider_gate", provider_gate_path),
        ("cohort_gate", cohort_gate_path),
        ("gender_checkpoint", gender_checkpoint_path),
    ):
        exists = path.is_file()
        payload = (
            json.loads(path.read_text(encoding="utf-8")) if exists else {}
        )
        passed = exists and payload.get("status") == "PASS"
        add_check(
            rows,
            f"{gate_id}_passes",
            passed,
            {"path": str(path), "status": payload.get("status")},
        )
        if exists:
            live_gates[gate_id] = {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
                "status": payload.get("status"),
            }

    matrices: dict[str, dict[str, Any]] = {}
    bindings: dict[str, dict[str, Any]] = {}
    for cohort in ("race", "sex_gender"):
        path = matrix_root / cohort / "matrix_manifest.json"
        exists = path.is_file()
        payload = (
            json.loads(path.read_text(encoding="utf-8")) if exists else {}
        )
        expected = {
            "cohort": cohort,
            "matrix_id": cohort,
            "analysis_sample_policy": "common_primary",
            "eligibility_policy": "primary",
            "outcome_specific_sample": False,
            "confirmatory_designated": False,
            "provider_measurement_version": PROVIDER_VERSION,
            "provider_gate_sha256": live_gates.get(
                "provider_gate", {}
            ).get("sha256"),
            "cohort_gate_sha256": live_gates.get("cohort_gate", {}).get(
                "sha256"
            ),
            "gender_checkpoint_sha256": live_gates.get(
                "gender_checkpoint", {}
            ).get("sha256"),
        }
        passed = exists and all(
            payload.get(key) == value for key, value in expected.items()
        )
        add_check(
            rows,
            f"{cohort}_common_matrix_live_binding",
            passed,
            {"path": str(path), "expected": expected},
        )
        if exists:
            matrices[cohort] = payload
            bindings[cohort] = binding_expected(payload, path)

    artifacts = [
        {
            "id": "race_threshold_probability",
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
                "id": f"heterogeneity_{cohort}",
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
                "id": f"classified_subjectivity_{cohort}",
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
            "id": "intersectional",
            "cohort": "race",
            "manifest": results
            / "intersectional"
            / "intersectional_manifest.json",
            "csvs": [
                "intersectional_model_coefficients.csv",
                "intersectional_16_cell_descriptive.csv",
            ],
        },
        {
            "id": "race_proxy_multiple_imputation",
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
                "id": f"negative_control_{cohort}",
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
                "id": f"outcome_appropriate_glm_{cohort}",
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
                "id": f"leave_one_year_out_{cohort}",
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
                "id": f"exact_subset_{cohort}",
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
                "id": f"influential_facility_{cohort}",
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
            "id": "payer_category_heterogeneity",
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

    inventory: list[dict[str, Any]] = []
    for item in artifacts:
        artifact_id = str(item["id"])
        cohort = str(item["cohort"])
        manifest_path = Path(item["manifest"])
        exists = manifest_path.is_file()
        payload = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if exists
            else {}
        )
        expected_binding = bindings.get(cohort, {})
        binding_passed = bool(expected_binding) and all(
            payload.get(key) == value
            for key, value in expected_binding.items()
        )
        add_check(
            rows,
            f"{artifact_id}_manifest_status_and_binding",
            exists and manifest_passed(payload) and binding_passed,
            {
                "path": str(manifest_path),
                "manifest_passed": manifest_passed(payload) if exists else False,
                "binding_passed": binding_passed,
            },
        )
        if exists:
            inventory.append(
                {
                    "artifact_id": artifact_id,
                    "relative_path": str(
                        manifest_path.relative_to(phase2)
                    ).replace("\\", "/"),
                    "bytes": manifest_path.stat().st_size,
                    "sha256": sha256_file(manifest_path),
                }
            )
        for name in item["csvs"]:
            csv_path = manifest_path.parent / name
            csv_exists = csv_path.is_file()
            profile = csv_profile(csv_path) if csv_exists else {}
            passed = (
                csv_exists
                and int(profile.get("rows", 0)) > 0
                and int(profile.get("infinite_numeric_values", 1)) == 0
            )
            add_check(
                rows,
                f"{artifact_id}_{Path(name).stem}_nonempty_finite",
                passed,
                {"path": str(csv_path), **profile},
            )
            if csv_exists:
                inventory.append(
                    {
                        "artifact_id": artifact_id,
                        "relative_path": str(csv_path.relative_to(phase2)).replace(
                            "\\", "/"
                        ),
                        "bytes": csv_path.stat().st_size,
                        "sha256": profile["sha256"],
                    }
                )

    checks = pd.DataFrame(rows)
    checks["passed"] = checks["passed"].map(bool)
    csv_path = qa / "independent_common_postmodel_results_audit.csv"
    checks.to_csv(csv_path, index=False)
    all_passed = bool(len(checks) > 0 and checks["passed"].all())
    payload = {
        "created_utc": now_utc(),
        "audit_id": "common_primary_postmodel_results_audit_v1",
        "status": "PASS" if all_passed else "FAIL",
        "checks": len(checks),
        "passed_checks": int(checks["passed"].sum()),
        "failed_checks": int((~checks["passed"]).sum()),
        "all_passed": all_passed,
        "live_gates": live_gates,
        "matrix_bindings": bindings,
        "artifact_inventory": inventory,
        "check_table": str(csv_path),
        "audit_scope": (
            "Independent structural, live-gate, provenance, completeness, "
            "finite-value, and file-hash audit of all common-primary "
            "postmodel artifacts before matrix compaction. Primary and payer "
            "coefficients are separately independently recomputed."
        ),
    }
    atomic_json(
        qa / "independent_common_postmodel_results_audit.json", payload
    )
    print(json.dumps(payload, indent=2))
    if not all_passed:
        raise RuntimeError("Common-primary postmodel audit failed")


if __name__ == "__main__":
    main()
