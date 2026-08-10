#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/45_independent_primary_ami_results_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Fail-closed independent audit of the 2010-2024 ED-only AMI extension."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests


DEFINITIONS = ("primary_principal", "broad_principal", "primary_anylisted")
OUTCOMES = (
    "mortality_flag",
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
    "any_procedure_flag",
    "routine_discharge_flag",
)
SPECIFICATIONS = (
    "m2_facility_yq_adjusted",
    "m3_physician_facility_yq",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def strict_bool_series(series: pd.Series) -> pd.Series:
    """Parse booleans without treating the string ``False`` as truthy."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    normalized = series.astype("string").str.strip().str.lower()
    if not normalized.dropna().isin(("true", "false")).all():
        raise ValueError("Non-Boolean value found in a required Boolean field")
    return normalized.eq("true").fillna(False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    result_root = phase2 / "results" / "ami"
    qa = phase2 / "qa"
    manifest_path = result_root / "ami_analysis_manifest.json"
    adjusted_path = result_root / "ami_model_results_adjusted.csv"
    required_paths = (
        manifest_path,
        result_root / "ami_model_interaction_results.csv",
        qa / "ami_model_diagnostics.csv",
        qa / "ami_validation_report.json",
        qa / "ami_validation_checks.csv",
        result_root / "ami_internal_reconciliation.csv",
        adjusted_path,
    )
    if not all(path.is_file() for path in required_paths):
        raise SystemExit("Primary AMI audit input missing")
    manifest = load_json(manifest_path)
    if (
        manifest.get("status") != "PASS"
        or manifest.get("validation_status")
        != "PASS_FOR_ED_ONLY_EXTENSION_NOT_REPLICATION"
        or manifest.get("required_models_expected") != 30
        or manifest.get("required_model_failures") != 0
        or manifest.get("required_models_completed") != 30
        or manifest.get("required_models_converged") != 24
        or manifest.get(
            "required_models_non_estimable_constant_outcome"
        )
        != 6
    ):
        raise SystemExit("Primary AMI manifest gate failed")

    binding_checks = []
    for path_key, status_key, hash_key in (
        ("provider_gate_path", "provider_gate_status", "provider_gate_sha256"),
        ("cohort_gate_path", "cohort_gate_status", "cohort_gate_sha256"),
        (
            "gender_checkpoint_path",
            "gender_checkpoint_status",
            "gender_checkpoint_sha256",
        ),
    ):
        path = Path(manifest[path_key])
        actual = sha256_file(path) if path.is_file() else ""
        passed = (
            actual == manifest[hash_key]
            and manifest[status_key] == "PASS"
            and load_json(path).get("status") == "PASS"
        )
        binding_checks.append(
            {
                "binding": path_key,
                "path": str(path),
                "expected_sha256": manifest[hash_key],
                "actual_sha256": actual,
                "passed": passed,
            }
        )
    benchmark_path = Path(manifest["external_benchmark_source_manifest"])
    binding_checks.append(
        {
            "binding": "external_benchmark",
            "path": str(benchmark_path),
            "expected_sha256": manifest[
                "external_benchmark_source_manifest_sha256"
            ],
            "actual_sha256": (
                sha256_file(benchmark_path)
                if benchmark_path.is_file()
                else ""
            ),
            "passed": (
                benchmark_path.is_file()
                and sha256_file(benchmark_path)
                == manifest["external_benchmark_source_manifest_sha256"]
            ),
        }
    )
    script_path = Path(manifest["analysis_script_path"])
    binding_checks.append(
        {
            "binding": "analysis_script",
            "path": str(script_path),
            "expected_sha256": manifest["analysis_script_sha256"],
            "actual_sha256": (
                sha256_file(script_path) if script_path.is_file() else ""
            ),
            "passed": (
                script_path.is_file()
                and sha256_file(script_path)
                == manifest["analysis_script_sha256"]
            ),
        }
    )
    file_hash_checks = []
    for item in manifest["files"]:
        path = Path(item["path"])
        actual = sha256_file(path) if path.is_file() else ""
        file_hash_checks.append(
            {
                "path": str(path),
                "expected_sha256": item["sha256"],
                "actual_sha256": actual,
                "passed": (
                    actual == item["sha256"]
                    and path.stat().st_size == int(item["bytes"])
                )
                if path.is_file()
                else False,
            }
        )

    results = pd.read_csv(
        result_root / "ami_model_interaction_results.csv"
    )
    diagnostics = pd.read_csv(qa / "ami_model_diagnostics.csv")
    adjusted = pd.read_csv(adjusted_path)
    required_results = results.loc[
        results["specification_id"].isin(SPECIFICATIONS)
        & results["model_id"].astype(str).str.endswith("_lpm_or_ols")
    ].copy()
    required_diagnostics = diagnostics.loc[
        diagnostics["specification_id"].isin(SPECIFICATIONS)
        & diagnostics["model_id"].astype(str).str.endswith("_lpm_or_ols")
    ].copy()

    expected_grid = {
        (definition, outcome, specification)
        for definition in DEFINITIONS
        for outcome in OUTCOMES
        for specification in SPECIFICATIONS
    }
    actual_grid = set(
        zip(
            required_results["definition"],
            required_results["outcome"],
            required_results["specification_id"],
        )
    )
    duplicate_grid_rows = int(
        required_results.duplicated(
            ["definition", "outcome", "specification_id"], keep=False
        ).sum()
    )
    constant_rows = required_results.loc[
        required_results["inferential_status"].eq("NON_ESTIMABLE")
    ].copy()
    expected_constant_grid = {
        (definition, "any_procedure_flag", specification)
        for definition in DEFINITIONS
        for specification in SPECIFICATIONS
    }
    actual_constant_grid = set(
        zip(
            constant_rows["definition"],
            constant_rows["outcome"],
            constant_rows["specification_id"],
        )
    )
    constant_numeric = constant_rows[
        [
            "estimate",
            "standard_error",
            "ci95_low",
            "ci95_high",
            "p_value",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    constant_rows_valid = bool(
        actual_constant_grid == expected_constant_grid
        and constant_numeric.isna().all().all()
        and constant_rows["non_estimable_reason"].notna().all()
    )
    estimable = required_results.loc[
        required_results["inferential_status"].eq("ESTIMABLE")
    ].copy()
    estimable_numeric = estimable[
        [
            "estimate",
            "standard_error",
            "ci95_low",
            "ci95_high",
            "p_value",
        ]
    ].to_numpy(dtype=np.float64)
    estimable_finite = bool(np.isfinite(estimable_numeric).all())
    estimable_se_positive = bool(
        (estimable["standard_error"].to_numpy(dtype=float) > 0).all()
    )
    ci_order_valid = bool(
        (
            estimable["ci95_low"].to_numpy(dtype=float)
            <= estimable["estimate"].to_numpy(dtype=float)
        ).all()
        and (
            estimable["estimate"].to_numpy(dtype=float)
            <= estimable["ci95_high"].to_numpy(dtype=float)
        ).all()
    )
    p_range_valid = bool(
        estimable["p_value"].between(0, 1, inclusive="both").all()
    )
    order_verified = bool(
        required_results["physician_patient_order_verified"]
        .fillna(False)
        .astype(bool)
        .all()
        and required_results["term"].eq("sex_gender_interaction").all()
    )
    diagnostics_status_valid = bool(
        len(required_diagnostics) == 30
        and required_diagnostics["status"]
        .isin(["converged", "non_estimable_constant_outcome"])
        .all()
        and int(
            required_diagnostics["status"]
            .eq("non_estimable_constant_outcome")
            .sum()
        )
        == 6
    )

    adjusted_required = adjusted.loc[
        adjusted["specification_id"].isin(SPECIFICATIONS)
        & adjusted["model_id"].astype(str).str.endswith("_lpm_or_ols")
    ].copy()
    adjusted_grid = set(
        zip(
            adjusted_required["definition"],
            adjusted_required["outcome"],
            adjusted_required["specification_id"],
        )
    )
    adjusted_duplicate_grid_rows = int(
        adjusted_required.duplicated(
            ["definition", "outcome", "specification_id"], keep=False
        ).sum()
    )
    adjusted_raw_match = False
    if (
        len(adjusted) == len(results)
        and adjusted["model_id"].is_unique
        and results["model_id"].is_unique
        and set(adjusted["model_id"]) == set(results["model_id"])
    ):
        left = (
            results[
                [
                    "model_id",
                    "definition",
                    "specification_id",
                    "outcome",
                    "estimator",
                    "term",
                    "contrast",
                    "inferential_status",
                    "non_estimable_reason",
                    "estimate",
                    "standard_error",
                    "ci95_low",
                    "ci95_high",
                    "p_value",
                    "n",
                ]
            ]
            .sort_values("model_id")
            .reset_index(drop=True)
        )
        right = (
            adjusted[left.columns]
            .sort_values("model_id")
            .reset_index(drop=True)
        )
        try:
            pd.testing.assert_frame_equal(
                left,
                right,
                check_dtype=False,
                check_exact=True,
            )
            adjusted_raw_match = True
        except AssertionError:
            adjusted_raw_match = False
    multiplicity_mismatches = []
    for family, block in adjusted_required.groupby("testing_family"):
        expected_family = (
            "secondary_ami_"
            + block["definition"].astype(str)
            + "_"
            + block["estimator"].astype(str)
        )
        if not expected_family.eq(family).all():
            multiplicity_mismatches.append(f"{family}:family_definition")
            continue
        if not block["adjustment_method"].eq("fdr_bh").all():
            multiplicity_mismatches.append(f"{family}:method")
            continue
        valid = block["p_value"].notna()
        if not valid.any():
            continue
        expected_reject, expected, _, _ = multipletests(
            block.loc[valid, "p_value"].astype(float),
            alpha=0.05,
            method="fdr_bh",
        )
        actual = block.loc[valid, "adjusted_p_value"].astype(float)
        if not np.allclose(expected, actual, rtol=1e-12, atol=1e-14):
            multiplicity_mismatches.append(family)
        actual_reject = strict_bool_series(
            block.loc[valid, "reject_adjusted_alpha_0_05"]
        ).to_numpy()
        if not np.array_equal(expected_reject, actual_reject):
            multiplicity_mismatches.append(f"{family}:reject")
    nonestimable_adjusted = adjusted_required[
        "inferential_status"
    ].eq("NON_ESTIMABLE")
    if (
        pd.to_numeric(
            adjusted_required.loc[
                nonestimable_adjusted, "adjusted_p_value"
            ],
            errors="coerce",
        )
        .notna()
        .any()
    ):
        multiplicity_mismatches.append("nonestimable_rows_have_adjusted_p")

    validation_report = load_json(qa / "ami_validation_report.json")
    validation_checks = pd.read_csv(qa / "ami_validation_checks.csv")
    validation_valid = bool(
        validation_report.get("status")
        == "PASS_FOR_ED_ONLY_EXTENSION_NOT_REPLICATION"
        and strict_bool_series(validation_checks["passed"]).all()
    )
    reconciliation = pd.read_csv(
        result_root / "ami_internal_reconciliation.csv"
    )
    primary_period = reconciliation.loc[
        reconciliation["visit_year"].between(2010, 2024)
    ]
    reconciliation_valid = bool(
        len(primary_period) == 15
        and primary_period["source_all_fact_primary_principal"].notna().all()
        and primary_period["primary_principal_visits"].notna().all()
        and (
            primary_period["source_all_fact_primary_principal"].astype(int)
            == primary_period["primary_principal_visits"].astype(int)
        ).all()
    )

    checks = [
        ("live_bindings", all(item["passed"] for item in binding_checks)),
        ("manifest_files", all(item["passed"] for item in file_hash_checks)),
        ("required_grid_exact", actual_grid == expected_grid),
        ("required_grid_no_duplicates", duplicate_grid_rows == 0),
        (
            "required_status_partition",
            len(estimable) == 24
            and len(constant_rows) == 6
            and required_results["inferential_status"]
            .isin(("ESTIMABLE", "NON_ESTIMABLE"))
            .all(),
        ),
        ("constant_outcomes_explicit", constant_rows_valid),
        ("estimable_values_finite", estimable_finite),
        ("estimable_standard_errors_positive", estimable_se_positive),
        ("confidence_interval_order", ci_order_valid),
        ("p_value_range", p_range_valid),
        ("physician_patient_order", order_verified),
        ("diagnostic_grid_status", diagnostics_status_valid),
        (
            "adjusted_grid_exact",
            adjusted_grid == expected_grid
            and adjusted_duplicate_grid_rows == 0,
        ),
        ("adjusted_preserves_unadjusted_results", adjusted_raw_match),
        ("multiplicity_recomputed", not multiplicity_mismatches),
        ("validation_gate", validation_valid),
        ("source_count_reconciliation", reconciliation_valid),
        (
            "interpretation_scope",
            "ED-only" in manifest.get("interpretation", "")
            and "never label as a replication"
            in manifest.get("interpretation", ""),
        ),
    ]
    failures = [name for name, passed in checks if not passed]
    payload = {
        "audit_id": "independent_primary_ami_results_audit_v1",
        "created_utc": now_utc(),
        "status": "PASS" if not failures else "FAIL",
        "scope": (
            "2010-2024 standalone ED-only AMI extension; not inpatient "
            "Greenwood replication."
        ),
        "checks": [
            {"check_id": name, "passed": passed}
            for name, passed in checks
        ],
        "checks_passed": sum(bool(value) for _, value in checks),
        "checks_total": len(checks),
        "required_grid_rows": len(required_results),
        "estimable_required_rows": len(estimable),
        "non_estimable_constant_rows": len(constant_rows),
        "optional_rows": len(results) - len(required_results),
        "binding_checks": binding_checks,
        "file_hash_checks": file_hash_checks,
        "multiplicity_mismatches": multiplicity_mismatches,
        "failures": failures,
        "result_interpretation_authorized": not failures,
        "full_project_report_finalization_authorized": False,
        "association_language_required": True,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output = qa / "independent_primary_ami_results_audit.json"
    atomic_json(output, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "checks_passed": payload["checks_passed"],
                "checks_total": payload["checks_total"],
                "required_grid_rows": len(required_results),
                "non_estimable_constant_rows": len(constant_rows),
                "failures": failures,
                "result_values_emitted": False,
            },
            indent=2,
        )
    )
    if payload["status"] != "PASS":
        raise SystemExit("Independent primary AMI audit failed")


if __name__ == "__main__":
    main()
