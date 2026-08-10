#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/31_independent_historical_results_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently audit gated historical race and AMI result artifacts."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


RACE_OUTCOMES = {
    "length_of_stay_days",
    "total_charge_reported_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "routine_discharge_flag",
    "transfer_flag",
    "mortality_flag",
}
RACE_SPECIFICATIONS = {
    "primary_prior_t50",
    "primary_prior_t70",
    "primary_prior_t80",
    "primary_prior_t90",
    "population_prior_t50",
    "primary_probability_bw",
}
AMI_OUTCOMES = {
    "mortality_flag",
    "length_of_stay_days",
    "total_charge_reported_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "routine_discharge_flag",
    "transfer_flag",
}
AMI_DEFINITIONS = {
    "principal_strict_410x1",
    "principal_broad_410x0_or_410x1",
    "anylisted_strict_410x1",
    "anylisted_broad_410x0_or_410x1",
}
AMI_SPECIFICATIONS = {
    "m2_facility_yq_adjusted",
    "m3_physician_facility_yq",
}
SEX_GENDER_OUTCOMES = RACE_OUTCOMES
SEX_GENDER_SAMPLE_VARIANTS = {
    "recorded_sources",
    "recorded_sources_no_nppes_cms_conflict",
}
PROVIDER_VERSION = "provider_master_v2_full_name_race_v1"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    evidence: Any,
) -> None:
    checks.append(
        {
            "check_id": check_id,
            "passed": bool(passed),
            "evidence": evidence,
        }
    )


def numeric_result_checks(
    checks: list[dict[str, Any]],
    prefix: str,
    frame: pd.DataFrame,
    *,
    allow_explicit_nonestimable: bool = False,
) -> None:
    required = {
        "estimate",
        "standard_error",
        "ci95_low",
        "ci95_high",
        "p_value",
        "n",
    }
    add_check(
        checks,
        f"{prefix}_required_numeric_columns",
        required.issubset(frame.columns),
        sorted(frame.columns),
    )
    if not required.issubset(frame.columns):
        return
    finite_columns = [
        "estimate",
        "standard_error",
        "ci95_low",
        "ci95_high",
        "p_value",
        "n",
    ]
    if allow_explicit_nonestimable:
        status_required = {
            "inferential_status",
            "non_estimable_reason",
        }
        add_check(
            checks,
            f"{prefix}_explicit_estimability_columns",
            status_required.issubset(frame.columns),
            sorted(frame.columns),
        )
        if not status_required.issubset(frame.columns):
            return
        valid_status = frame["inferential_status"].isin(
            ["ESTIMABLE", "NON_ESTIMABLE"]
        )
        add_check(
            checks,
            f"{prefix}_valid_estimability_status",
            bool(valid_status.all()),
            frame.loc[
                ~valid_status, "inferential_status"
            ].value_counts(dropna=False).to_dict(),
        )
        estimable = frame["inferential_status"].eq("ESTIMABLE")
        non_estimable = frame["inferential_status"].eq("NON_ESTIMABLE")
        non_estimable_reason_present = (
            frame.loc[non_estimable, "non_estimable_reason"]
            .astype("string")
            .str.strip()
            .ne("")
            .fillna(False)
        )
        add_check(
            checks,
            f"{prefix}_nonestimable_reason_present",
            bool(non_estimable_reason_present.all()),
            int((~non_estimable_reason_present).sum()),
        )
        undefined_columns = [
            "estimate",
            "standard_error",
            "ci95_low",
            "ci95_high",
            "p_value",
        ]
        undefined_missing = frame.loc[
            non_estimable, undefined_columns
        ].isna()
        add_check(
            checks,
            f"{prefix}_nonestimable_inference_is_missing",
            bool(undefined_missing.to_numpy().all()),
            {
                column: int((~undefined_missing[column]).sum())
                for column in undefined_columns
            },
        )
        numeric_frame = frame.loc[estimable].copy()
    else:
        numeric_frame = frame

    finite = numeric_frame[finite_columns].map(
        lambda value: math.isfinite(float(value))
    )
    add_check(
        checks,
        f"{prefix}_finite_numeric_results",
        bool(finite.to_numpy().all()),
        {
            column: int((~finite[column]).sum())
            for column in finite_columns
        },
    )
    add_check(
        checks,
        f"{prefix}_standard_errors_nonnegative",
        bool((numeric_frame["standard_error"] >= 0).all()),
        int((numeric_frame["standard_error"] < 0).sum()),
    )
    ci_valid = (
        (numeric_frame["ci95_low"] <= numeric_frame["estimate"])
        & (numeric_frame["estimate"] <= numeric_frame["ci95_high"])
    )
    add_check(
        checks,
        f"{prefix}_confidence_intervals_contain_estimate",
        bool(ci_valid.all()),
        int((~ci_valid).sum()),
    )
    p_valid = numeric_frame["p_value"].between(
        0, 1, inclusive="both"
    )
    add_check(
        checks,
        f"{prefix}_p_values_in_unit_interval",
        bool(p_valid.all()),
        int((~p_valid).sum()),
    )
    add_check(
        checks,
        f"{prefix}_positive_sample_sizes",
        bool((frame["n"] > 0).all()),
        int((frame["n"] <= 0).sum()),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    qa = phase2 / "qa"
    documentation = phase2 / "documentation"
    historical_root = phase2 / "analysis_data" / "historical_provider_v2"
    race_root = phase2 / "results" / "historical_provider_v2_sensitivity"
    sex_gender_root = (
        phase2
        / "results"
        / "historical_provider_v2_sex_gender_sensitivity"
    )
    ami_root = phase2 / "results" / "historical_provider_v2_ami"

    paths = {
        "gate": qa / "historical_provider_v2_pre_estimation_gate.json",
        "build": historical_root / "historical_provider_v2_build_manifest.json",
        "race_manifest": race_root / "historical_analysis_manifest.json",
        "race_results": race_root / "historical_adjusted_race_sensitivities.csv",
        "race_diagnostics": (
            qa / "historical_provider_v2_race_model_diagnostics.csv"
        ),
        "sex_gender_manifest": (
            sex_gender_root / "historical_sex_gender_analysis_manifest.json"
        ),
        "sex_gender_results": (
            sex_gender_root
            / "historical_sex_gender_adjusted_interactions.csv"
        ),
        "sex_gender_diagnostics": (
            qa
            / "historical_provider_v2_sex_gender_model_diagnostics.csv"
        ),
        "ami_manifest": ami_root / "historical_ami_analysis_manifest.json",
        "ami_results": ami_root / "historical_ami_interaction_results.csv",
        "ami_diagnostics": qa / "historical_ami_model_diagnostics.csv",
        "ami_validation": qa / "historical_ami_validation_report.json",
        "reconciliation": (
            qa / "historical_provider_v2_phase1_reconciliation.csv"
        ),
        "comparability": (
            documentation / "Historical_2005_2008_Comparability_Matrix.csv"
        ),
    }
    missing = [
        f"{name}:{path}"
        for name, path in paths.items()
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError("; ".join(missing))

    gate = json.loads(paths["gate"].read_text(encoding="utf-8"))
    build = json.loads(paths["build"].read_text(encoding="utf-8"))
    race_manifest = json.loads(
        paths["race_manifest"].read_text(encoding="utf-8")
    )
    ami_manifest = json.loads(
        paths["ami_manifest"].read_text(encoding="utf-8")
    )
    sex_gender_manifest = json.loads(
        paths["sex_gender_manifest"].read_text(encoding="utf-8")
    )
    ami_validation = json.loads(
        paths["ami_validation"].read_text(encoding="utf-8")
    )
    race_results = pd.read_csv(paths["race_results"])
    race_diagnostics = pd.read_csv(paths["race_diagnostics"])
    sex_gender_results = pd.read_csv(paths["sex_gender_results"])
    sex_gender_diagnostics = pd.read_csv(
        paths["sex_gender_diagnostics"]
    )
    ami_results = pd.read_csv(paths["ami_results"])
    ami_diagnostics = pd.read_csv(paths["ami_diagnostics"])
    reconciliation = pd.read_csv(paths["reconciliation"])
    comparability = pd.read_csv(paths["comparability"])
    success_manifests = list(
        historical_root.glob(
            "visit_year=*/visit_quarter=*/_SUCCESS.json"
        )
    )

    checks: list[dict[str, Any]] = []
    add_check(
        checks,
        "historical_pre_estimation_gate_pass",
        (
            gate.get("status") == "PASS"
            and gate.get("historical_estimation_authorized") is True
            and gate.get("estimate_blind") is True
        ),
        {
            "status": gate.get("status"),
            "authorized": gate.get("historical_estimation_authorized"),
            "estimate_blind": gate.get("estimate_blind"),
        },
    )
    add_check(
        checks,
        "all_16_partitions_built_and_reconciled",
        (
            build.get("status") == "PASS"
            and build.get("partitions") == 16
            and gate.get("reconciled_partitions") == 16
            and len(success_manifests) == 16
            and len(reconciliation) == 16
            and reconciliation["passed"]
            .map(lambda value: str(value).strip().lower() == "true")
            .all()
        ),
        {
            "build_partitions": build.get("partitions"),
            "gate_partitions": gate.get("reconciled_partitions"),
            "success_manifests": len(success_manifests),
            "reconciliation_rows": len(reconciliation),
        },
    )
    add_check(
        checks,
        "exact_phase1_row_and_key_reconciliation",
        (
            gate.get("phase1_rows") == gate.get("historical_rows")
            and gate.get("missing_phase1_keys") == 0
            and gate.get("extra_historical_keys") == 0
            and gate.get("selected_field_mismatches") == 0
        ),
        {
            "phase1_rows": gate.get("phase1_rows"),
            "historical_rows": gate.get("historical_rows"),
            "missing_keys": gate.get("missing_phase1_keys"),
            "extra_keys": gate.get("extra_historical_keys"),
            "field_mismatches": gate.get("selected_field_mismatches"),
        },
    )
    add_check(
        checks,
        "hourly_los_never_constructed_or_analyzed",
        (
            gate.get("hourly_los_errors") == 0
            and race_manifest.get("hourly_los_used") is False
            and sex_gender_manifest.get("hourly_los_used") is False
            and ami_manifest.get("hourly_los_used") is False
            and not race_results["outcome"].astype(str).str.contains(
                "los_hours", case=False, regex=False
            ).any()
            and not ami_results["outcome"].astype(str).str.contains(
                "los_hours", case=False, regex=False
            ).any()
            and not sex_gender_results["outcome"].astype(str).str.contains(
                "los_hours", case=False, regex=False
            ).any()
        ),
        {
            "gate_hourly_errors": gate.get("hourly_los_errors"),
            "race_los_outcome": race_manifest.get("los_outcome"),
            "sex_gender_los_outcome": sex_gender_manifest.get(
                "los_outcome"
            ),
            "ami_los_outcome": ami_manifest.get("los_outcome"),
        },
    )
    add_check(
        checks,
        "historical_analyses_separate_and_never_pooled",
        (
            race_manifest.get("separate_analysis") is True
            and race_manifest.get("never_pooled_with_primary") is True
            and sex_gender_manifest.get("separate_analysis") is True
            and sex_gender_manifest.get("never_pooled_with_primary") is True
            and ami_manifest.get("separate_analysis") is True
            and ami_manifest.get("never_pooled_with_primary") is True
        ),
        {
            "race_separate": race_manifest.get("separate_analysis"),
            "race_never_pooled": race_manifest.get(
                "never_pooled_with_primary"
            ),
            "sex_gender_separate": sex_gender_manifest.get(
                "separate_analysis"
            ),
            "sex_gender_never_pooled": sex_gender_manifest.get(
                "never_pooled_with_primary"
            ),
            "ami_separate": ami_manifest.get("separate_analysis"),
            "ami_never_pooled": ami_manifest.get(
                "never_pooled_with_primary"
            ),
        },
    )
    add_check(
        checks,
        "provider_measurement_v2_applied",
        (
            race_manifest.get("provider_measurement_version")
                == PROVIDER_VERSION
            and sex_gender_manifest.get("provider_measurement_version")
                == PROVIDER_VERSION
            and ami_manifest.get("provider_measurement_version")
                == PROVIDER_VERSION
            and gate.get("invalid_md_do_rows") == 0
            and gate.get("direct_npi_rows") == 0
        ),
        {
            "race_version": race_manifest.get(
                "provider_measurement_version"
            ),
            "sex_gender_version": sex_gender_manifest.get(
                "provider_measurement_version"
            ),
            "ami_version": ami_manifest.get(
                "provider_measurement_version"
            ),
            "invalid_md_do_rows": gate.get("invalid_md_do_rows"),
            "direct_npi_rows": gate.get("direct_npi_rows"),
        },
    )
    add_check(
        checks,
        "historical_analysis_manifests_pass",
        (
            race_manifest.get("status") == "PASS"
            and sex_gender_manifest.get("status") == "PASS"
            and ami_manifest.get("status") == "PASS"
        ),
        {
            "race_status": race_manifest.get("status"),
            "sex_gender_status": sex_gender_manifest.get("status"),
            "ami_status": ami_manifest.get("status"),
        },
    )

    expected_race_pairs = {
        (specification, outcome)
        for specification in RACE_SPECIFICATIONS
        for outcome in RACE_OUTCOMES
    }
    observed_race_pairs = set(
        zip(
            race_results["race_specification"].astype(str),
            race_results["outcome"].astype(str),
        )
    )
    add_check(
        checks,
        "race_required_model_grid_complete",
        (
            observed_race_pairs == expected_race_pairs
            and len(race_results) == len(expected_race_pairs)
            and race_results["model_id"].is_unique
            and race_manifest.get("models_expected")
                == len(expected_race_pairs)
            and race_manifest.get("models_converged")
                == len(expected_race_pairs)
        ),
        {
            "expected": len(expected_race_pairs),
            "observed": len(race_results),
            "missing": sorted(expected_race_pairs - observed_race_pairs),
            "extra": sorted(observed_race_pairs - expected_race_pairs),
        },
    )
    add_check(
        checks,
        "race_diagnostics_all_converged",
        (
            len(race_diagnostics) == len(expected_race_pairs)
            and (race_diagnostics["status"] == "converged").all()
            and race_diagnostics["model_id"].is_unique
        ),
        race_diagnostics["status"].value_counts().to_dict(),
    )
    numeric_result_checks(checks, "race", race_results)

    observed_sex_gender_outcomes = set(
        sex_gender_results["outcome"].astype(str)
    )
    observed_sex_gender_samples = set(
        sex_gender_results["sample_id"].astype(str)
    )
    expected_sex_gender_models = (
        len(SEX_GENDER_OUTCOMES) * len(SEX_GENDER_SAMPLE_VARIANTS)
    )
    add_check(
        checks,
        "sex_gender_required_model_grid_complete",
        (
            observed_sex_gender_outcomes == SEX_GENDER_OUTCOMES
            and observed_sex_gender_samples
                == SEX_GENDER_SAMPLE_VARIANTS
            and len(sex_gender_results) == expected_sex_gender_models
            and sex_gender_results["model_id"].is_unique
            and sex_gender_manifest.get("models_expected")
                == expected_sex_gender_models
            and sex_gender_manifest.get("models_converged")
                == expected_sex_gender_models
        ),
        {
            "expected": expected_sex_gender_models,
            "observed": len(sex_gender_results),
            "missing": sorted(
                SEX_GENDER_OUTCOMES - observed_sex_gender_outcomes
            ),
            "extra": sorted(
                observed_sex_gender_outcomes - SEX_GENDER_OUTCOMES
            ),
            "expected_samples": sorted(SEX_GENDER_SAMPLE_VARIANTS),
            "observed_samples": sorted(observed_sex_gender_samples),
        },
    )
    add_check(
        checks,
        "sex_gender_diagnostics_all_converged",
        (
            len(sex_gender_diagnostics) == expected_sex_gender_models
            and (sex_gender_diagnostics["status"] == "converged").all()
            and sex_gender_diagnostics["model_id"].is_unique
        ),
        sex_gender_diagnostics["status"].value_counts().to_dict(),
    )
    numeric_result_checks(
        checks, "sex_gender", sex_gender_results
    )

    required_ami_grid = {
        (definition, outcome, specification)
        for definition in AMI_DEFINITIONS
        for outcome in AMI_OUTCOMES
        for specification in AMI_SPECIFICATIONS
    }
    required_ami_results = ami_results.loc[
        ami_results["model_id"].astype(str).str.endswith("_lpm_or_ols")
    ].copy()
    observed_ami_grid = set(
        zip(
            required_ami_results["cohort_definition"].astype(str),
            required_ami_results["outcome"].astype(str),
            required_ami_results["specification_id"].astype(str),
        )
    )
    required_ami_diagnostics = ami_diagnostics.loc[
        ami_diagnostics["required"].map(
            lambda value: str(value).strip().lower() == "true"
        )
    ]
    add_check(
        checks,
        "ami_required_model_grid_complete",
        (
            observed_ami_grid == required_ami_grid
            and len(required_ami_results) == len(required_ami_grid)
            and required_ami_results["model_id"].is_unique
            and ami_manifest.get("required_models_expected")
                == len(required_ami_grid)
            and ami_manifest.get("required_models_accounted_for")
                == len(required_ami_grid)
            and ami_manifest.get("required_model_failures") == 0
        ),
        {
            "expected": len(required_ami_grid),
            "observed": len(required_ami_results),
            "missing": sorted(required_ami_grid - observed_ami_grid),
            "extra": sorted(observed_ami_grid - required_ami_grid),
        },
    )
    add_check(
        checks,
        "ami_required_diagnostics_all_accounted_for",
        (
            len(required_ami_diagnostics) == len(required_ami_grid)
            and required_ami_diagnostics["status"].isin(
                ["converged", "non_estimable_constant_outcome"]
            ).all()
            and required_ami_diagnostics["model_id"].is_unique
            and int(
                (
                    required_ami_diagnostics["status"]
                    == "non_estimable_constant_outcome"
                ).sum()
            )
            == ami_manifest.get(
                "required_models_non_estimable_constant_outcome"
            )
            and int(
                (
                    required_ami_diagnostics["status"] == "converged"
                ).sum()
            )
            == ami_manifest.get("required_models_converged")
        ),
        required_ami_diagnostics["status"].value_counts().to_dict(),
    )
    non_estimable_result_ids = set(
        required_ami_results.loc[
            required_ami_results["inferential_status"].eq(
                "NON_ESTIMABLE"
            ),
            "model_id",
        ].astype(str)
    )
    non_estimable_diagnostic_ids = set(
        required_ami_diagnostics.loc[
            required_ami_diagnostics["status"].eq(
                "non_estimable_constant_outcome"
            ),
            "model_id",
        ].astype(str)
    )
    add_check(
        checks,
        "ami_nonestimable_result_diagnostic_alignment",
        non_estimable_result_ids == non_estimable_diagnostic_ids,
        {
            "result_only": sorted(
                non_estimable_result_ids
                - non_estimable_diagnostic_ids
            ),
            "diagnostic_only": sorted(
                non_estimable_diagnostic_ids
                - non_estimable_result_ids
            ),
            "aligned_count": len(
                non_estimable_result_ids
                & non_estimable_diagnostic_ids
            ),
        },
    )
    add_check(
        checks,
        "ami_code_and_setting_validation_pass",
        (
            ami_validation.get("status") == "PASS"
            and ami_validation.get(
                "greenwood_replication_claim_permitted"
            ) is False
            and ami_manifest.get(
                "greenwood_replication_claim_permitted"
            ) is False
        ),
        {
            "validation_status": ami_validation.get("status"),
            "replication_claim_permitted": ami_manifest.get(
                "greenwood_replication_claim_permitted"
            ),
        },
    )
    numeric_result_checks(
        checks,
        "ami",
        ami_results,
        allow_explicit_nonestimable=True,
    )

    required_comparability_variables = {
        "length_of_stay_days",
        "hourly LOS",
        "AMI cohort",
        "attending NPI",
        "physician full-name race proxy",
    }
    observed_comparability = set(
        comparability["variable_or_outcome"].astype(str)
    )
    add_check(
        checks,
        "comparability_matrix_covers_key_measurements",
        required_comparability_variables.issubset(
            observed_comparability
        ),
        sorted(
            required_comparability_variables - observed_comparability
        ),
    )

    status = "PASS" if all(item["passed"] for item in checks) else "FAIL"
    report = {
        "created_utc": now_utc(),
        "status": status,
        "audit_id": "independent_historical_results_audit_v2",
        "checks": checks,
        "checks_passed": sum(item["passed"] for item in checks),
        "checks_total": len(checks),
        "race_result_rows": len(race_results),
        "sex_gender_result_rows": len(sex_gender_results),
        "ami_result_rows": len(ami_results),
        "source_release_modified": False,
    }
    report_path = qa / "independent_historical_results_audit.json"
    report_path.write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    pd.DataFrame(checks).to_csv(
        qa / "independent_historical_results_audit_checks.csv",
        index=False,
    )
    failed = [item for item in checks if not item["passed"]]
    markdown = f"""# Independent historical results audit

Status: **{status}**

Generated: {report['created_utc']}

- Checks passed: {report['checks_passed']} of {report['checks_total']}
- Historical race interaction rows: {len(race_results)}
- Historical sex/gender interaction rows: {len(sex_gender_results)}
- Historical AMI interaction rows: {len(ami_results)}
- Phase 1 modified: no

The audit requires the estimate-blind 16-quarter reconciliation gate, exact
Phase 1 encounter preservation, provider master v2, no direct-NPI claims in
the historical era, no organizational/non-MD/DO physician eligibility,
complete prespecified model grids, converged required models, valid numeric
inference fields, separate-era labeling, and zero constructed or analyzed
hourly-LOS fields.

Failed checks:

{json.dumps(failed, indent=2, default=str) if failed else "None."}
"""
    (
        documentation / "Independent_Historical_Results_Audit.md"
    ).write_text(markdown, encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    if status != "PASS":
        raise SystemExit("Independent historical results audit failed")


if __name__ == "__main__":
    main()
