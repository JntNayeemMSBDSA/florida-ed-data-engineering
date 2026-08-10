#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/10b_historical_ami_greenwood_analysis.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Run the gated, separate 2005-2008 ED-only AMI/Greenwood extension."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyfixest as pf


OUTCOMES = [
    "mortality_flag",
    "length_of_stay_days",
    "total_charge_reported_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "routine_discharge_flag",
    "transfer_flag",
]
BINARY_OUTCOMES = {
    "mortality_flag",
    "any_procedure_flag",
    "routine_discharge_flag",
    "transfer_flag",
}
REQUIRED_DEFINITIONS = (
    "principal_strict_410x1",
    "principal_broad_410x0_or_410x1",
    "anylisted_strict_410x1",
    "anylisted_broad_410x0_or_410x1",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def safe_float(value: Any) -> float:
    return float(value) if value is not None else math.nan


def tidy_interaction(
    fit: Any,
    model_id: str,
    specification_id: str,
    outcome: str,
    definition: str,
    estimator: str,
    n: int,
) -> dict[str, Any]:
    term = "sex_gender_interaction"
    interval = fit.confint().loc[term]
    return {
        "model_id": model_id,
        "specification_id": specification_id,
        "cohort_definition": definition,
        "outcome": outcome,
        "term": term,
        "contrast": (
            "female_patient:female_physician interaction; difference-in-differences "
            "across the four recorded patient sex-physician gender cells"
        ),
        "estimator": estimator,
        "estimate": safe_float(fit.coef().get(term)),
        "standard_error": safe_float(fit.se().get(term)),
        "ci95_low": safe_float(interval.iloc[0]),
        "ci95_high": safe_float(interval.iloc[1]),
        "p_value": safe_float(fit.pvalue().get(term)),
        "n": int(n),
        "inferential_status": "ESTIMABLE",
        "non_estimable_reason": None,
    }


def non_estimable_interaction(
    *,
    model_id: str,
    specification_id: str,
    outcome: str,
    definition: str,
    estimator: str,
    n: int,
    reason: str,
) -> dict[str, Any]:
    """Retain a required model-grid cell without inventing inference."""

    return {
        "model_id": model_id,
        "specification_id": specification_id,
        "cohort_definition": definition,
        "outcome": outcome,
        "term": "sex_gender_interaction",
        "contrast": (
            "female_patient:female_physician interaction; "
            "difference-in-differences across the four recorded patient "
            "sex-physician gender cells"
        ),
        "estimator": estimator,
        "estimate": math.nan,
        "standard_error": math.nan,
        "ci95_low": math.nan,
        "ci95_high": math.nan,
        "p_value": math.nan,
        "n": int(n),
        "inferential_status": "NON_ESTIMABLE",
        "non_estimable_reason": reason,
        "fixef_tol": math.nan,
        "fixef_maxiter": math.nan,
        "demeaning_fallback_used": False,
        "demeaning_attempt_number": 0,
        "initial_demeaning_error": None,
    }


def feols_with_documented_demeaning_fallback(
    *,
    formula: str,
    data: pd.DataFrame,
    vcov: dict[str, str],
) -> tuple[Any, dict[str, Any]]:
    """Fit the same HDFE model with a numerical-only MAP fallback.

    The initial fit preserves the original strict 1e-8 fixed-effect
    tolerance.  Only an explicit alternating-projection nonconvergence is
    retried, using pyfixest's standard 1e-6 tolerance and a larger iteration
    ceiling.  No formula, sample, fixed effects, clustering, or contrast
    changes are permitted by this fallback.
    """

    attempts = (
        {
            "fixef_tol": 1e-8,
            "fixef_maxiter": 10_000,
            "demeaning_fallback_used": False,
        },
        {
            "fixef_tol": 1e-6,
            "fixef_maxiter": 50_000,
            "demeaning_fallback_used": True,
        },
    )
    first_error: str | None = None
    for attempt_number, attempt in enumerate(attempts, start=1):
        try:
            fit = pf.feols(
                formula,
                data=data,
                vcov=vcov,
                demeaner=pf.MapDemeaner(
                    fixef_tol=attempt["fixef_tol"],
                    fixef_maxiter=attempt["fixef_maxiter"],
                    backend="rust",
                ),
                lean=True,
            )
            return fit, {
                **attempt,
                "demeaning_attempt_number": attempt_number,
                "initial_demeaning_error": first_error,
            }
        except ValueError as error:
            if (
                attempt_number == 1
                and "Demeaning failed" in str(error)
            ):
                first_error = repr(error)
                continue
            raise
    raise RuntimeError("Unreachable demeaning fallback state")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    args.temp.mkdir(parents=True, exist_ok=True)
    gate_path = phase2 / "qa" / "historical_provider_v2_pre_estimation_gate.json"
    if not gate_path.exists():
        raise SystemExit(
            "Historical provider-v2 gate is missing; AMI estimation is blocked"
        )
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if (
        gate.get("status") != "PASS"
        or gate.get("historical_estimation_authorized") is not True
        or gate.get("reconciled_partitions") != 16
        or gate.get("hourly_los_errors") != 0
    ):
        raise SystemExit(
            "Historical provider-v2 gate did not authorize AMI estimation"
        )

    historical_glob = (
        phase2
        / "analysis_data"
        / "historical_provider_v2"
        / "visit_year=*"
        / "visit_quarter=*"
        / "historical_provider_v2_core.parquet"
    )
    results = phase2 / "results" / "historical_provider_v2_ami"
    qa = phase2 / "qa"
    documentation = phase2 / "documentation"
    results.mkdir(parents=True, exist_ok=True)
    qa.mkdir(parents=True, exist_ok=True)
    documentation.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(args.temp)}'")
    source = f"read_parquet('{qpath(historical_glob)}', hive_partitioning=false)"
    elix_flags = sorted(
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM {source}"
        ).fetchall()
        if row[0].startswith("elix_") and row[0].endswith("_flag")
    )

    validation = con.execute(
        f"""
        SELECT
            count(*) AS universe_rows,
            count(DISTINCT visit_key) AS distinct_keys,
            count(*) FILTER (
                WHERE sex_gender_historical_eligible_flag
            ) AS sex_gender_eligible_rows,
            count(*) FILTER (
                WHERE ami_icd9_principal_strict_flag
            ) AS principal_strict_rows,
            count(*) FILTER (
                WHERE ami_icd9_principal_broad_flag
            ) AS principal_broad_rows,
            count(*) FILTER (
                WHERE ami_icd9_anylisted_strict_flag = 1
            ) AS anylisted_strict_rows,
            count(*) FILTER (
                WHERE ami_icd9_anylisted_broad_flag = 1
            ) AS anylisted_broad_rows,
            count(*) FILTER (
                WHERE ami_icd9_principal_strict_flag
                  AND NOT ami_icd9_principal_broad_flag
            ) AS strict_not_broad_errors,
            count(*) FILTER (
                WHERE ami_icd9_anylisted_strict_flag = 1
                  AND ami_icd9_anylisted_broad_flag <> 1
            ) AS anylisted_strict_not_broad_errors,
            count(*) FILTER (
                WHERE hourly_los_available_flag
                   OR ed_discharge_hour IS NOT NULL
                   OR los_hours_clock_raw IS NOT NULL
                   OR los_hours_primary_0_168 IS NOT NULL
            ) AS hourly_los_errors
        FROM {source}
        """
    ).fetchone()
    counts = con.execute(
        f"""
        SELECT
            visit_year,
            count(*) FILTER (
                WHERE ami_icd9_principal_strict_flag
            ) AS principal_strict_all,
            count(*) FILTER (
                WHERE ami_icd9_principal_strict_flag
                  AND sex_gender_historical_eligible_flag
            ) AS principal_strict_sex_gender_eligible,
            count(*) FILTER (
                WHERE ami_icd9_principal_broad_flag
            ) AS principal_broad_all,
            count(*) FILTER (
                WHERE ami_icd9_principal_broad_flag
                  AND sex_gender_historical_eligible_flag
            ) AS principal_broad_sex_gender_eligible,
            count(*) FILTER (
                WHERE ami_icd9_anylisted_strict_flag = 1
            ) AS anylisted_strict_all,
            count(*) FILTER (
                WHERE ami_icd9_anylisted_strict_flag = 1
                  AND sex_gender_historical_eligible_flag
            ) AS anylisted_strict_sex_gender_eligible,
            count(*) FILTER (
                WHERE ami_icd9_anylisted_broad_flag = 1
            ) AS anylisted_broad_all,
            count(*) FILTER (
                WHERE ami_icd9_anylisted_broad_flag = 1
                  AND sex_gender_historical_eligible_flag
            ) AS anylisted_broad_sex_gender_eligible,
            count(*) FILTER (
                WHERE ami_icd9_principal_strict_flag
                  AND sex_gender_historical_eligible_flag
                  AND mortality_flag
            ) AS principal_strict_ed_deaths
        FROM {source}
        GROUP BY visit_year
        ORDER BY visit_year
        """
    ).fetchdf()
    counts.to_csv(results / "historical_ami_counts_by_year.csv", index=False)

    validation_passed = bool(
        validation[0] == validation[1]
        and validation[7] == 0
        and validation[8] == 0
        and validation[9] == 0
        and gate["phase1_rows"] == int(validation[0])
    )
    validation_report = {
        "created_utc": now_utc(),
        "status": "PASS" if validation_passed else "FAIL",
        "universe_rows": int(validation[0]),
        "distinct_keys": int(validation[1]),
        "sex_gender_eligible_rows": int(validation[2]),
        "principal_strict_rows": int(validation[3]),
        "principal_broad_rows": int(validation[4]),
        "anylisted_strict_rows": int(validation[5]),
        "anylisted_broad_rows": int(validation[6]),
        "strict_not_broad_errors": int(validation[7]),
        "anylisted_strict_not_broad_errors": int(validation[8]),
        "hourly_los_errors": int(validation[9]),
        "setting": "standalone ED encounters",
        "greenwood_replication_claim_permitted": False,
        "interpretation": (
            "Separate ED-only historical extension inspired by Greenwood et al.; "
            "not an inpatient replication and not pooled with 2010-2024."
        ),
    }
    validation_path = qa / "historical_ami_validation_report.json"
    validation_path.write_text(
        json.dumps(validation_report, indent=2), encoding="utf-8"
    )
    if not validation_passed:
        con.close()
        raise SystemExit(
            "Historical AMI validation failed; models were not estimated"
        )

    elix_projection = ",\n            ".join(elix_flags)
    frame = con.execute(
        f"""
        SELECT
            visit_year,
            visit_quarter,
            facility_ahca_id,
            facility_year_quarter_id,
            attending_selected_npi,
            patient_sex_category,
            physician_gender_category,
            race_ethnicity_historical_label,
            age_years,
            payer_group,
            patient_zip_rurality_3level,
            weekend_flag,
            off_hours_flag,
            arrival_time_band,
            elixhauser_condition_count,
            attending_ed_specialist_flag,
            attending_years_since_medical_school,
            attending_quarter_volume_all_ed,
            mortality_flag,
            length_of_stay_days,
            total_charge_reported_real_2024,
            procedure_count_analysis,
            any_procedure_flag,
            routine_discharge_flag,
            transfer_flag,
            {elix_projection},
            ami_icd9_principal_strict_flag
                AS principal_strict_410x1,
            ami_icd9_principal_broad_flag
                AS principal_broad_410x0_or_410x1,
            (ami_icd9_anylisted_strict_flag = 1)
                AS anylisted_strict_410x1,
            (ami_icd9_anylisted_broad_flag = 1)
                AS anylisted_broad_410x0_or_410x1
        FROM {source}
        WHERE sex_gender_historical_eligible_flag
          AND ami_icd9_anylisted_broad_flag = 1
        """
    ).fetchdf()
    con.close()

    frame["physician_female"] = (
        frame["physician_gender_category"] == "Female"
    ).astype(float)
    frame["patient_female"] = (
        frame["patient_sex_category"] == "Female"
    ).astype(float)
    frame["sex_gender_interaction"] = (
        frame["physician_female"] * frame["patient_female"]
    )
    age = pd.to_numeric(frame["age_years"], errors="coerce")
    frame["age_missing"] = age.isna().astype(float)
    frame["age"] = age.fillna(age.median()).clip(0, 120)
    frame["age_gt45"] = (frame["age"] - 45).clip(lower=0)
    frame["age_gt65"] = (frame["age"] - 65).clip(lower=0)
    frame["age_gt80"] = (frame["age"] - 80).clip(lower=0)
    experience = pd.to_numeric(
        frame["attending_years_since_medical_school"], errors="coerce"
    ).where(lambda values: values.between(0, 80))
    frame["experience_missing"] = experience.isna().astype(float)
    frame["experience"] = experience.fillna(experience.median())
    volume = pd.to_numeric(
        frame["attending_quarter_volume_all_ed"], errors="coerce"
    )
    frame["log_physician_volume"] = np.log1p(
        volume.fillna(0).clip(lower=0)
    )
    frame["ed_specialist"] = (
        frame["attending_ed_specialist_flag"].fillna(False).astype(float)
    )
    frame["weekend"] = frame["weekend_flag"].fillna(False).astype(float)
    frame["off_hours"] = frame["off_hours_flag"].fillna(False).astype(float)
    dummies = pd.get_dummies(
        frame[
            [
                "payer_group",
                "patient_zip_rurality_3level",
                "arrival_time_band",
                "race_ethnicity_historical_label",
            ]
        ].fillna("<MISSING>"),
        prefix=[
            "payer",
            "rurality",
            "arrival",
            "historical_race_ethnicity",
        ],
        drop_first=True,
        dtype=float,
    )
    dummies.columns = [
        "".join(
            character if character.isalnum() else "_"
            for character in name
        )
        for name in dummies.columns
    ]
    frame = pd.concat([frame, dummies], axis=1)
    for flag in elix_flags:
        frame[flag] = (
            pd.to_numeric(frame[flag], errors="coerce")
            .fillna(0)
            .astype(float)
        )
    patient_risk_terms = [
        "physician_female",
        "patient_female",
        "sex_gender_interaction",
        "age",
        "age_gt45",
        "age_gt65",
        "age_gt80",
        "age_missing",
        "elixhauser_condition_count",
        "weekend",
        "off_hours",
        *dummies.columns.tolist(),
        *elix_flags,
    ]
    fully_adjusted_terms = [
        *patient_risk_terms,
        "ed_specialist",
        "experience",
        "experience_missing",
        "log_physician_volume",
    ]
    physician_fe_terms = [
        term
        for term in patient_risk_terms
        if term != "physician_female"
    ] + ["log_physician_volume"]
    model_specs = {
        "m2_facility_yq_adjusted": {
            "terms": fully_adjusted_terms,
            "fixed_effects": "facility_year_quarter_id",
        },
        "m3_physician_facility_yq": {
            "terms": physician_fe_terms,
            "fixed_effects": (
                "attending_selected_npi + facility_year_quarter_id"
            ),
        },
    }
    definitions = {
        definition: frame[definition].astype(bool)
        for definition in REQUIRED_DEFINITIONS
    }

    model_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for definition, mask in definitions.items():
        block = frame.loc[mask].copy()
        for outcome in OUTCOMES:
            model_frame = block.loc[block[outcome].notna()].copy()
            model_frame[outcome] = model_frame[outcome].astype(float)
            outcome_distinct_values = int(model_frame[outcome].nunique())
            for specification_id, specification in model_specs.items():
                formula_rhs = " + ".join(specification["terms"])
                model_id = (
                    f"historical_ami_{definition}_{outcome}_"
                    f"{specification_id}_lpm_or_ols"
                )
                if outcome_distinct_values < 2:
                    reason = (
                        "Outcome has no within-sample variation "
                        f"(distinct_values={outcome_distinct_values}); "
                        "a standard error and p-value are undefined."
                    )
                    model_rows.append(
                        non_estimable_interaction(
                            model_id=model_id,
                            specification_id=specification_id,
                            outcome=outcome,
                            definition=definition,
                            estimator=(
                                "linear_probability"
                                if outcome in BINARY_OUTCOMES
                                else "ols"
                            ),
                            n=len(model_frame),
                            reason=reason,
                        )
                    )
                    diagnostics.append(
                        {
                            "model_id": model_id,
                            "specification_id": specification_id,
                            "required": True,
                            "status": "non_estimable_constant_outcome",
                            "n": len(model_frame),
                            "events": (
                                int(model_frame[outcome].sum())
                                if outcome in BINARY_OUTCOMES
                                else None
                            ),
                            "outcome_distinct_values": (
                                outcome_distinct_values
                            ),
                            "distinct_physicians": int(
                                model_frame[
                                    "attending_selected_npi"
                                ].nunique()
                            ),
                            "distinct_facilities": int(
                                model_frame["facility_ahca_id"].nunique()
                            ),
                            "non_estimable_reason": reason,
                            "demeaning_fallback_used": False,
                            "demeaning_attempt_number": 0,
                        }
                    )
                    continue
                try:
                    fit, numerical_metadata = (
                        feols_with_documented_demeaning_fallback(
                            formula=(
                                f"{outcome} ~ {formula_rhs} | "
                                f"{specification['fixed_effects']}"
                            ),
                            data=model_frame,
                            vcov={
                                "CRV1": (
                                    "attending_selected_npi + "
                                    "facility_ahca_id"
                                )
                            },
                        )
                    )
                    result_row = tidy_interaction(
                        fit,
                        model_id,
                        specification_id,
                        outcome,
                        definition,
                        (
                            "linear_probability"
                            if outcome in BINARY_OUTCOMES
                            else "ols"
                        ),
                        len(model_frame),
                    )
                    result_row.update(numerical_metadata)
                    model_rows.append(result_row)
                    diagnostics.append(
                        {
                            "model_id": model_id,
                            "specification_id": specification_id,
                            "required": True,
                            "status": "converged",
                            "n": len(model_frame),
                            "outcome_distinct_values": (
                                outcome_distinct_values
                            ),
                            "events": (
                                int(model_frame[outcome].sum())
                                if outcome in BINARY_OUTCOMES
                                else None
                            ),
                            "distinct_physicians": int(
                                model_frame[
                                    "attending_selected_npi"
                                ].nunique()
                            ),
                            "distinct_facilities": int(
                                model_frame["facility_ahca_id"].nunique()
                            ),
                            **numerical_metadata,
                        }
                    )
                except Exception as error:
                    diagnostics.append(
                        {
                            "model_id": model_id,
                            "specification_id": specification_id,
                            "required": True,
                            "status": "failed",
                            "n": len(model_frame),
                            "error": repr(error),
                        }
                    )

        mortality = block.loc[block["mortality_flag"].notna()].copy()
        mortality["mortality_flag"] = mortality["mortality_flag"].astype(float)
        mortality_events = int(mortality["mortality_flag"].sum())
        if mortality_events >= 100:
            logit_specification_id = "m2_facility_yq_adjusted"
            logit_rhs = " + ".join(fully_adjusted_terms)
            model_id = (
                f"historical_ami_{definition}_mortality_"
                f"{logit_specification_id}_logit"
            )
            try:
                fit = pf.feglm(
                    (
                        f"mortality_flag ~ {logit_rhs} | "
                        "facility_year_quarter_id"
                    ),
                    data=mortality,
                    family="logit",
                    vcov={
                        "CRV1": (
                            "attending_selected_npi + facility_ahca_id"
                        )
                    },
                    iwls_tol=1e-8,
                    iwls_maxiter=100,
                    lean=True,
                )
                model_rows.append(
                    tidy_interaction(
                        fit,
                        model_id,
                        logit_specification_id,
                        "mortality_flag",
                        definition,
                        "fixed_effect_logit_log_odds",
                        len(mortality),
                    )
                )
                diagnostics.append(
                    {
                        "model_id": model_id,
                        "specification_id": logit_specification_id,
                        "required": False,
                        "status": "converged",
                        "n": len(mortality),
                        "events": mortality_events,
                    }
                )
            except Exception as error:
                diagnostics.append(
                    {
                        "model_id": model_id,
                        "specification_id": logit_specification_id,
                        "required": False,
                        "status": "failed",
                        "n": len(mortality),
                        "events": mortality_events,
                        "error": repr(error),
                    }
                )

    model_results = pd.DataFrame(model_rows)
    model_diagnostics = pd.DataFrame(diagnostics)
    model_results.to_csv(
        results / "historical_ami_interaction_results.csv", index=False
    )
    model_diagnostics.to_csv(
        qa / "historical_ami_model_diagnostics.csv", index=False
    )
    required_failures = [
        item
        for item in diagnostics
        if item["required"]
        and item["status"]
        not in {"converged", "non_estimable_constant_outcome"}
    ]
    expected_required = (
        len(REQUIRED_DEFINITIONS) * len(OUTCOMES) * len(model_specs)
    )
    required_converged = sum(
        item["required"] and item["status"] == "converged"
        for item in diagnostics
    )
    required_non_estimable = sum(
        item["required"]
        and item["status"] == "non_estimable_constant_outcome"
        for item in diagnostics
    )
    required_accounted_for = required_converged + required_non_estimable
    status = (
        "PASS"
        if not required_failures
        and required_accounted_for == expected_required
        else "FAIL"
    )
    manifest = {
        "created_utc": now_utc(),
        "status": status,
        "analysis_id": "historical_provider_v2_ami_greenwood_extension_v1",
        "historical_pre_estimation_gate": str(gate_path),
        "historical_pre_estimation_gate_status": gate["status"],
        "separate_analysis": True,
        "never_pooled_with_primary": True,
        "greenwood_replication_claim_permitted": False,
        "provider_measurement_version": "provider_master_v2_full_name_race_v1",
        "cohort_definitions": list(REQUIRED_DEFINITIONS),
        "outcomes": OUTCOMES,
        "hourly_los_used": False,
        "los_outcome": "length_of_stay_days",
        "required_models_expected": expected_required,
        "required_models_converged": required_converged,
        "required_models_non_estimable_constant_outcome": (
            required_non_estimable
        ),
        "required_models_accounted_for": required_accounted_for,
        "required_model_failures": len(required_failures),
        "required_model_specifications": list(model_specs),
        "required_models_using_demeaning_fallback": sum(
            bool(item.get("demeaning_fallback_used"))
            for item in diagnostics
            if item["required"] and item["status"] == "converged"
        ),
        "non_estimability_policy": (
            "Required model-grid cells with fewer than two observed outcome "
            "values are retained and explicitly marked NON_ESTIMABLE. "
            "Estimate, standard error, confidence interval, and p-value "
            "remain missing; zeros are never substituted for undefined "
            "inference."
        ),
        "demeaning_numerical_policy": {
            "initial": {
                "method": "MAP alternating projections, rust backend",
                "fixef_tol": 1e-8,
                "fixef_maxiter": 10_000,
            },
            "fallback_only_after_explicit_demeaning_nonconvergence": {
                "method": "identical MAP model, rust backend",
                "fixef_tol": 1e-6,
                "fixef_maxiter": 50_000,
            },
            "substantive_model_changes_permitted": False,
        },
        "historical_race_ethnicity_adjusted": True,
        "elixhauser_indicator_count": len(elix_flags),
        "optional_model_failures": sum(
            not item["required"] and item["status"] != "converged"
            for item in diagnostics
        ),
        "limitations": [
            "Standalone ED encounters; no inpatient mortality follow-up.",
            "Unique Florida-license linkage rather than direct source NPI.",
            "Day-level LOS only; hourly LOS is structurally unavailable.",
            (
                "Current provider attributes do not prove historical "
                "employment, affiliation, privilege, specialty, or identity."
            ),
        ],
    }
    manifest_path = results / "historical_ami_analysis_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    methods = f"""# Historical 2005-2008 AMI/Greenwood extension

## Scope and interpretation

This is a separately estimated, ED-only historical extension inspired by
Greenwood, Carnahan, and Huang (2018). It is **not** a replication of their
inpatient analysis. The Florida source captures standalone ED encounters and
does not provide inpatient survival after same-hospital admission.

The analysis ran only after the 16-quarter provider-v2 historical
pre-estimation gate passed. It is not pooled with 2010-2024.

## Cohort definitions

- Strict principal: ICD-9-CM `410.X1`.
- Broad principal: ICD-9-CM `410.X0` or `410.X1`.
- Strict any-listed: principal or secondary ICD-9-CM `410.X1`.
- Broad any-listed: principal or secondary ICD-9-CM `410.X0` or `410.X1`.
- ICD-9-CM `410.X2` is excluded.

All models require the recorded patient sex-physician gender historical
eligibility flag. Physician linkage is derived from a unique Florida-license
crosswalk and provider master v2.

## Models

The frozen sex/gender interaction is estimated in two specifications: an
adjusted facility-year-quarter fixed-effect model and a within-physician model
with attending-physician plus facility-year-quarter fixed effects. Both use
two-way physician/facility clustered standard errors. Adjustment includes age
splines, the historical combined patient race/ethnicity category, all available
Elixhauser-condition indicators and the condition count, weekend and off-hours
indicators, payer, patient rurality, arrival-time band, and physician-quarter
volume. The facility-year-quarter model also includes physician ED-specialist
status and experience with a missingness indicator; those time-invariant
physician attributes are absorbed in the physician fixed-effect model. Linear
probability models are used for binary outcomes and OLS for continuous/count
outcomes. Fixed-effect logistic mortality models are optional sensitivity
models when at least 100 ED mortality events are available.

For HDFE numerical convergence, each required OLS/LPM model is first fit with
MAP alternating projections at a fixed-effect tolerance of 1e-8 and a 10,000
iteration ceiling. Only an explicit demeaning nonconvergence is retried with
the identical sample, formula, fixed effects, clustering, and contrast at
pyfixest's standard 1e-6 tolerance and a 50,000 iteration ceiling. Every retry
is recorded in the result and diagnostic tables.

Before fitting, outcome variation is checked within each AMI definition and
outcome-specific sample. A required grid cell with fewer than two observed
outcome values is retained but marked `NON_ESTIMABLE`; its estimate, standard
error, confidence interval, and p-value remain missing. Undefined inference is
never represented as a zero effect or a zero standard error.

## LOS rule

Only `length_of_stay_days` is analyzed. No hourly LOS value is available or
imputed for 2005-2008.

## Measurement limitations

Provider master v2 current registry attributes do not establish historical
employment, affiliation, privilege, specialty, or gender identity. The
patient and physician fields are administrative/proxy measurements.

Gate: `{gate_path}`

Validation: `{validation_path}`
"""
    (
        documentation / "Historical_AMI_Greenwood_Extension.md"
    ).write_text(methods, encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    if status != "PASS":
        raise SystemExit("Required historical AMI models failed")


if __name__ == "__main__":
    main()
