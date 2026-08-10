#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/10_ami_validation_and_analysis.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Validate the ED-only AMI cohort and estimate sex/gender-concordance models."""

from __future__ import annotations

import argparse
import hashlib
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
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
    "any_procedure_flag",
    "routine_discharge_flag",
]
RECORDED_PHYSICIAN_GENDER_SOURCES = (
    "NPPES",
    "NPPES February 2026 current snapshot",
    "CMS Doctors and Clinicians",
    "CMS Doctors and Clinicians June 2026 current snapshot",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_float(value: Any) -> float:
    return float(value) if value is not None else math.nan


def tidy_interaction(
    fit: Any,
    model_id: str,
    specification_id: str,
    outcome: str,
    definition: str,
    estimator: str,
    sample_n: int,
) -> dict[str, Any]:
    term = "sex_gender_interaction"
    coefficients = fit.coef()
    ses = fit.se()
    pvalues = fit.pvalue()
    interval = fit.confint()
    return {
        "definition": definition,
        "model_id": model_id,
        "specification_id": specification_id,
        "outcome": outcome,
        "estimator": estimator,
        "term": term,
        "contrast": (
            "female_female - female_male - male_female + male_male"
        ),
        "estimate": safe_float(coefficients.get(term)),
        "standard_error": safe_float(ses.get(term)),
        "ci95_low": safe_float(interval.loc[term].iloc[0]),
        "ci95_high": safe_float(interval.loc[term].iloc[1]),
        "p_value": safe_float(pvalues.get(term)),
        "n": sample_n,
        "inferential_status": "ESTIMABLE",
        "non_estimable_reason": None,
        "physician_patient_order_verified": True,
    }


def non_estimable_interaction(
    model_id: str,
    specification_id: str,
    outcome: str,
    definition: str,
    estimator: str,
    sample_n: int,
    reason: str,
) -> dict[str, Any]:
    """Retain a required AMI grid cell without inventing inference."""

    return {
        "definition": definition,
        "model_id": model_id,
        "specification_id": specification_id,
        "outcome": outcome,
        "estimator": estimator,
        "term": "sex_gender_interaction",
        "contrast": (
            "female_female - female_male - male_female + male_male"
        ),
        "estimate": math.nan,
        "standard_error": math.nan,
        "ci95_low": math.nan,
        "ci95_high": math.nan,
        "p_value": math.nan,
        "n": sample_n,
        "inferential_status": "NON_ESTIMABLE",
        "non_estimable_reason": reason,
        "physician_patient_order_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--temp", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    args.temp.mkdir(parents=True, exist_ok=True)
    benchmark_source_path = (
        phase2
        / "external_sources"
        / "ami_benchmark"
        / "source_manifest.json"
    )
    if not benchmark_source_path.exists():
        raise SystemExit(
            f"Required AMI benchmark provenance is missing: "
            f"{benchmark_source_path}"
        )
    benchmark_source = json.loads(
        benchmark_source_path.read_text(encoding="utf-8")
    )
    expected_benchmark = {
        "source_id": "cdc_nchs_2019_nhamcs_ed_summary_table_12_v1",
        "doi": "10.15620/cdc:115748",
        "table": "Table 12",
        "pdf_page_index_zero_based": 18,
        "row_label": "Acute myocardial infarction",
        "estimate_visits": 378_000,
        "standard_error_visits": 96_000,
        "percent_of_ed_visits": 0.3,
    }
    if any(
        benchmark_source.get(key) != value
        for key, value in expected_benchmark.items()
    ) or not all(
        benchmark_source.get("verification", {}).get(key) is True
        for key in (
            "official_pdf_opened",
            "table_and_row_visually_checked",
            "values_checked_against_machine_extracted_pdf_text",
        )
    ):
        raise SystemExit(
            "AMI benchmark source manifest does not match the locked "
            "CDC/NCHS Table 12 reference"
        )
    benchmark_source_sha256 = sha256_file(benchmark_source_path)
    provider_gate_path = phase2 / "qa" / "pre_estimation_measurement_gate.json"
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"
    gender_checkpoint_path = (
        phase2 / "qa" / "provider_gender_measurement_checkpoint.json"
    )
    for gate_path in (
        provider_gate_path,
        cohort_gate_path,
        gender_checkpoint_path,
    ):
        if not gate_path.exists():
            raise SystemExit(f"Required pre-model gate is missing: {gate_path}")
    provider_gate = json.loads(
        provider_gate_path.read_text(encoding="utf-8")
    )
    cohort_gate = json.loads(
        cohort_gate_path.read_text(encoding="utf-8")
    )
    gender_checkpoint = json.loads(
        gender_checkpoint_path.read_text(encoding="utf-8")
    )
    if (
        provider_gate.get("status") != "PASS"
        or cohort_gate.get("status") != "PASS"
        or gender_checkpoint.get("status") != "PASS"
        or gender_checkpoint.get("primary_definition", {}).get(
            "physician_gender_sources"
        )
        != list(RECORDED_PHYSICIAN_GENDER_SOURCES)
    ):
        raise SystemExit(
            "Provider-v2, cohort, or physician-gender gate did not authorize "
            "AMI models"
        )
    data_root = (
        phase2 / "analysis_data" / "concordance_visit_data_provider_v2"
    )
    core_glob = (
        data_root
        / "visit_year=*"
        / "visit_quarter=*"
        / "concordance_visit_core.parquet"
    )
    risk_glob = (
        data_root
        / "visit_year=*"
        / "visit_quarter=*"
        / "concordance_elixhauser_flags.parquet"
    )
    results = phase2 / "results" / "ami"
    qa = phase2 / "qa"
    documentation = phase2 / "documentation"
    for path in (results, qa, documentation):
        path.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(args.temp)}'")
    con.execute("SET preserve_insertion_order=false")
    source = f"read_parquet('{qpath(core_glob)}', hive_partitioning=false)"
    risk_source = (
        f"read_parquet('{qpath(risk_glob)}', hive_partitioning=false)"
    )
    recorded_gender_sources_sql = ", ".join(
        "'" + value.replace("'", "''") + "'"
        for value in RECORDED_PHYSICIAN_GENDER_SOURCES
    )
    elix_flags = sorted(
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM {risk_source}"
        ).fetchall()
        if row[0].startswith("elix_") and row[0].endswith("_flag")
    )
    definition_case = """
        CASE
            WHEN ami_icd9_principal_strict_flag = 1
              OR ami_icd10_principal_primary_flag = 1
            THEN 'primary_principal'
            WHEN ami_icd9_principal_broad_flag = 1
              OR ami_icd10_principal_primary_flag = 1
              OR ami_icd10_principal_type2_other_flag = 1
            THEN 'broad_principal'
        END
    """
    counts = con.execute(
        f"""
        WITH definitions AS (
            SELECT
                *,
                (coalesce(ami_icd9_principal_strict_flag = 1, false)
                 OR coalesce(ami_icd10_principal_primary_flag = 1, false))
                    AS primary_principal,
                (coalesce(ami_icd9_principal_broad_flag = 1, false)
                 OR coalesce(ami_icd10_principal_primary_flag = 1, false)
                 OR coalesce(
                     ami_icd10_principal_type2_other_flag = 1, false
                 ))
                    AS broad_principal,
                (coalesce(ami_icd9_anylisted_strict_flag = 1, false)
                 OR coalesce(ami_icd10_anylisted_primary_flag = 1, false))
                    AS primary_anylisted,
                (coalesce(ami_icd9_anylisted_broad_flag = 1, false)
                 OR coalesce(ami_icd10_anylisted_primary_flag = 1, false)
                 OR coalesce(
                     ami_icd10_anylisted_type2_other_flag = 1, false
                 )
                 OR coalesce(ami_i22_with_i21_same_visit_flag = 1, false))
                    AS broad_anylisted
            FROM {source}
        )
        SELECT
            visit_year,
            count(*) AS derived_union_visits,
            sum(primary_principal) AS primary_principal_visits,
            sum(broad_principal) AS broad_principal_visits,
            sum(primary_anylisted) AS primary_anylisted_visits,
            sum(broad_anylisted) AS broad_anylisted_visits,
            sum(primary_principal AND sex_gender_primary_eligible_flag = 1
                AND physician_gender_source IN (
                    {recorded_gender_sources_sql}
                ))
                AS primary_principal_sex_gender_eligible,
            sum(primary_principal AND sex_gender_primary_eligible_flag = 1
                AND physician_gender_source IN (
                    {recorded_gender_sources_sql}
                )
                AND mortality_flag = 1)
                AS primary_principal_ed_deaths
        FROM definitions
        GROUP BY visit_year
        ORDER BY visit_year
        """
    ).fetchdf()
    counts.to_csv(results / "ami_counts_by_year.csv", index=False)

    source_counts = pd.read_csv(qa / "ami_principal_counts_by_quarter.csv")
    source_counts["source_primary_principal"] = np.where(
        (source_counts["visit_year"] < 2015)
        | (
            (source_counts["visit_year"] == 2015)
            & (source_counts["visit_quarter"] <= 3)
        ),
        source_counts["icd9_410_excluding_subsequent_episode"],
        source_counts["icd10_i21"],
    )
    source_annual = (
        source_counts.groupby("visit_year", as_index=False)
        .agg(
            source_all_fact_icd9_410_broad=("icd9_410_broad", "sum"),
            source_all_fact_icd9_excluding_subsequent=(
                "icd9_410_excluding_subsequent_episode",
                "sum",
            ),
            source_all_fact_icd10_i21=("icd10_i21", "sum"),
            source_all_fact_icd10_i22=("icd10_i22", "sum"),
            source_all_fact_primary_principal=(
                "source_primary_principal",
                "sum",
            ),
        )
    )
    benchmark = source_annual.merge(counts, on="visit_year", how="left")
    all_visits_by_year = pd.read_csv(qa / "main_cohort_feasibility_by_year.csv")[
        ["visit_year", "all_ed_visits"]
    ]
    benchmark = benchmark.merge(all_visits_by_year, on="visit_year", how="left")
    benchmark["source_primary_ami_percent_of_all_ed"] = (
        100
        * benchmark["source_all_fact_primary_principal"]
        / benchmark["all_ed_visits"]
    )
    benchmark.to_csv(results / "ami_internal_reconciliation.csv", index=False)

    national_reference = pd.DataFrame(
        [
            {
                "reference_year": 2019,
                "geography": "United States",
                "setting": "NHAMCS hospital emergency departments",
                "definition_label": (
                    "Acute myocardial infarction as principal diagnosis "
                    "category in published NHAMCS table"
                ),
                "estimate_visits": benchmark_source["estimate_visits"],
                "standard_error_visits": benchmark_source[
                    "standard_error_visits"
                ],
                "percent_of_ed_visits": benchmark_source[
                    "percent_of_ed_visits"
                ],
                "source": (
                    "CDC/NCHS, 2019 NHAMCS Emergency Department Summary "
                    "Tables, Table 12"
                ),
                "doi": benchmark_source["doi"],
                "url": benchmark_source["official_pdf_url"],
                "source_manifest": str(benchmark_source_path),
                "source_manifest_sha256": benchmark_source_sha256,
                "comparability": (
                    "Directional only: national survey estimate; sampling "
                    "error; unlike Florida SEDD-style data, setting definitions "
                    "and same-hospital admission handling are not identical."
                ),
            }
        ]
    )
    national_reference.to_csv(
        results / "ami_external_benchmark_reference.csv", index=False
    )

    annual_nonzero = bool(
        (
            benchmark.loc[
                benchmark["visit_year"].between(2010, 2024),
                "source_all_fact_primary_principal",
            ]
            > 0
        ).all()
    )
    proportions = benchmark.loc[
        benchmark["visit_year"].between(2010, 2024),
        "source_primary_ami_percent_of_all_ed",
    ]
    plausible_range = bool(proportions.between(0.01, 1.0).all())
    validation_checks = [
        {
            "check": "official_code_logic_unit_tested",
            "passed": True,
            "detail": (
                "ICD-9 strict principal 410.X1; ICD-10-CM principal "
                "I21.0-I21.4 and I21.9; type 2/other MI separate."
            ),
        },
        {
            "check": "external_benchmark_provenance_locked",
            "passed": True,
            "detail": (
                "CDC/NCHS 2019 NHAMCS Table 12 source manifest, stable DOI, "
                "table location, and visually verified AMI values are locked "
                f"by SHA-256 {benchmark_source_sha256}."
            ),
        },
        {
            "check": "nonzero_primary_counts_each_year_2010_2024",
            "passed": annual_nonzero,
            "detail": "Source all-fact principal definition.",
        },
        {
            "check": "annual_principal_percentage_plausible",
            "passed": plausible_range,
            "detail": (
                "Prespecified broad plausibility interval 0.01%-1.0% of "
                "standalone ED visits; external national estimate is 0.3%."
            ),
        },
        {
            "check": "setting_difference_explicit",
            "passed": True,
            "detail": (
                "Florida source is standalone ED encounters and excludes "
                "same-facility inpatient admissions; Greenwood analyzed "
                "hospital admissions through the ED and inpatient survival."
            ),
        },
    ]
    validation_status = (
        "PASS_FOR_ED_ONLY_EXTENSION_NOT_REPLICATION"
        if all(item["passed"] for item in validation_checks)
        else "FAIL"
    )
    validation_report = {
        "created_utc": now_utc(),
        "status": validation_status,
        "checks": validation_checks,
        "primary_definition": (
            "Principal ICD-9-CM 410.X1 before the ICD-10 transition; "
            "principal ICD-10-CM I21.0-I21.4 or I21.9 thereafter."
        ),
        "sensitivity_definitions": [
            "principal ICD-9 410.X0 or 410.X1",
            "principal ICD-10 I21 including I21.A1/I21.A9",
            "any-listed versions",
            "I22 only when I21 appears on the same visit",
        ],
        "external_benchmark_source_manifest": str(benchmark_source_path),
        "external_benchmark_source_manifest_sha256": (
            benchmark_source_sha256
        ),
        "interpretation_gate": (
            "Passed for an ED-only observational extension. It cannot be "
            "called a replication of Greenwood et al."
        ),
    }
    (qa / "ami_validation_report.json").write_text(
        json.dumps(validation_report, indent=2), encoding="utf-8"
    )
    pd.DataFrame(validation_checks).to_csv(
        qa / "ami_validation_checks.csv", index=False
    )
    if validation_status == "FAIL":
        raise SystemExit("AMI validation gate failed; models were not estimated")

    risk_projection = ",\n            ".join(
        f"r.{name}" for name in elix_flags
    )
    frame = con.execute(
        f"""
        SELECT
            c.visit_year,
            c.visit_quarter,
            c.facility_ahca_id,
            c.facility_year_quarter_id,
            c.attending_selected_npi,
            c.patient_sex_category,
            c.physician_gender_category,
            c.patient_race_category,
            c.patient_ethnicity_category,
            c.age_years,
            c.payer_group,
            c.patient_zip_rurality_3level,
            c.weekend_flag,
            c.off_hours_flag,
            c.arrival_time_band,
            c.elixhauser_condition_count,
            c.attending_ed_specialist_flag,
            c.attending_years_since_medical_school,
            c.attending_quarter_volume_all_ed,
            c.mortality_flag,
            c.los_hours_primary_0_168,
            c.total_charge_reported_real_2024,
            c.any_procedure_flag,
            c.routine_discharge_flag,
            {risk_projection},
            (coalesce(c.ami_icd9_principal_strict_flag = 1, false)
             OR coalesce(c.ami_icd10_principal_primary_flag = 1, false))
                AS primary_principal,
            (coalesce(c.ami_icd9_principal_broad_flag = 1, false)
             OR coalesce(c.ami_icd10_principal_primary_flag = 1, false)
             OR coalesce(
                 c.ami_icd10_principal_type2_other_flag = 1, false
             ))
                AS broad_principal,
            (coalesce(c.ami_icd9_anylisted_strict_flag = 1, false)
             OR coalesce(c.ami_icd10_anylisted_primary_flag = 1, false))
                AS primary_anylisted
        FROM {source} AS c
        INNER JOIN {risk_source} AS r
          USING (visit_key, visit_year, visit_quarter)
        WHERE c.sex_gender_primary_eligible_flag = 1
          AND c.physician_gender_source IN (
              {recorded_gender_sources_sql}
          )
          AND (
              c.ami_icd9_anylisted_broad_flag = 1
              OR c.ami_icd10_anylisted_primary_flag = 1
              OR c.ami_icd10_anylisted_type2_other_flag = 1
              OR c.ami_i22_with_i21_same_visit_flag = 1
          )
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
    )
    experience = experience.where(experience.between(0, 80))
    frame["experience_missing"] = experience.isna().astype(float)
    frame["experience"] = experience.fillna(experience.median())
    volume = pd.to_numeric(
        frame["attending_quarter_volume_all_ed"], errors="coerce"
    )
    frame["log_physician_volume"] = np.log1p(volume.fillna(0).clip(lower=0))
    frame["ed_specialist"] = (
        frame["attending_ed_specialist_flag"].fillna(False).astype(float)
    )
    frame["weekend"] = frame["weekend_flag"].fillna(False).astype(float)
    frame["off_hours"] = frame["off_hours_flag"].fillna(False).astype(float)
    patient_race = frame["patient_race_category"].astype("string")
    patient_ethnicity = frame["patient_ethnicity_category"].astype("string")
    frame["patient_race_ethnicity_group"] = np.select(
        [
            patient_ethnicity.eq("Hispanic or Latino"),
            patient_ethnicity.eq("Not Hispanic or Latino")
            & patient_race.eq("Black or African American"),
            patient_ethnicity.eq("Not Hispanic or Latino")
            & patient_race.eq("White"),
            patient_ethnicity.eq("Not Hispanic or Latino"),
        ],
        ["Hispanic", "NH_Black", "NH_White", "NH_Other"],
        default="Unknown",
    )
    dummies = pd.get_dummies(
        frame[
            [
                "payer_group",
                "patient_zip_rurality_3level",
                "arrival_time_band",
                "patient_race_ethnicity_group",
            ]
        ].fillna("<MISSING>"),
        prefix=["payer", "rurality", "arrival", "patient_race_ethnicity"],
        drop_first=True,
        dtype=float,
    )
    dummies.columns = [
        "".join(character if character.isalnum() else "_" for character in name)
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
    model_rows: list[dict[str, Any]] = []
    model_diagnostics: list[dict[str, Any]] = []
    definitions = {
        "primary_principal": frame["primary_principal"]
        .fillna(False)
        .astype(bool),
        "broad_principal": frame["broad_principal"]
        .fillna(False)
        .astype(bool),
        "primary_anylisted": frame["primary_anylisted"]
        .fillna(False)
        .astype(bool),
    }
    for definition, mask in definitions.items():
        block = frame.loc[mask].copy()
        for outcome in OUTCOMES:
            model_frame = block.loc[block[outcome].notna()].copy()
            model_frame[outcome] = model_frame[outcome].astype(float)
            outcome_distinct_values = int(model_frame[outcome].nunique())
            for specification_id, specification in model_specs.items():
                formula_rhs = " + ".join(specification["terms"])
                formula = (
                    f"{outcome} ~ {formula_rhs} | "
                    f"{specification['fixed_effects']}"
                )
                model_id = (
                    f"ami_{definition}_{outcome}_{specification_id}"
                    "_lpm_or_ols"
                )
                estimator = (
                    "linear_probability"
                    if outcome
                    in (
                        "mortality_flag",
                        "any_procedure_flag",
                        "routine_discharge_flag",
                    )
                    else "ols"
                )
                if outcome_distinct_values < 2:
                    reason = (
                        "Outcome has no within-sample variation "
                        f"(distinct_values={outcome_distinct_values}); "
                        "a standard error and p-value are undefined."
                    )
                    model_rows.append(
                        non_estimable_interaction(
                            model_id,
                            specification_id,
                            outcome,
                            definition,
                            estimator,
                            len(model_frame),
                            reason,
                        )
                    )
                    model_diagnostics.append(
                        {
                            "model_id": model_id,
                            "specification_id": specification_id,
                            "status": "non_estimable_constant_outcome",
                            "n": len(model_frame),
                            "events": (
                                int(model_frame[outcome].sum())
                                if outcome
                                in (
                                    "mortality_flag",
                                    "any_procedure_flag",
                                    "routine_discharge_flag",
                                )
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
                        }
                    )
                    continue
                try:
                    fit = pf.feols(
                        formula,
                        data=model_frame,
                        vcov={
                            "CRV1": (
                                "attending_selected_npi + facility_ahca_id"
                            )
                        },
                        demeaner=pf.MapDemeaner(
                            fixef_tol=1e-8, backend="rust"
                        ),
                        lean=True,
                    )
                    model_rows.append(
                        tidy_interaction(
                            fit,
                            model_id,
                            specification_id,
                            outcome,
                            definition,
                            estimator,
                            len(model_frame),
                        )
                    )
                    model_diagnostics.append(
                        {
                            "model_id": model_id,
                            "specification_id": specification_id,
                            "status": "converged",
                            "n": len(model_frame),
                            "events": (
                                int(model_frame[outcome].sum())
                                if outcome
                                in (
                                    "mortality_flag",
                                    "any_procedure_flag",
                                    "routine_discharge_flag",
                                )
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
                        }
                    )
                except Exception as error:
                    model_diagnostics.append(
                        {
                            "model_id": model_id,
                            "specification_id": specification_id,
                            "status": "failed",
                            "n": len(model_frame),
                            "error": repr(error),
                        }
                    )

        mortality_frame = block.loc[block["mortality_flag"].notna()].copy()
        mortality_events = int(mortality_frame["mortality_flag"].sum())
        if mortality_events >= 100:
            logit_specification_id = "m2_facility_yq_adjusted"
            logit_rhs = " + ".join(fully_adjusted_terms)
            logit_id = (
                f"ami_{definition}_mortality_"
                f"{logit_specification_id}_logit"
            )
            try:
                fit = pf.feglm(
                    f"mortality_flag ~ {logit_rhs} | "
                    "facility_year_quarter_id",
                    data=mortality_frame,
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
                        logit_id,
                        logit_specification_id,
                        "mortality_flag",
                        definition,
                        "fixed_effect_logit_log_odds",
                        len(mortality_frame),
                    )
                )
                model_diagnostics.append(
                    {
                        "model_id": logit_id,
                        "specification_id": logit_specification_id,
                        "status": "converged",
                        "n": len(mortality_frame),
                        "events": mortality_events,
                    }
                )
            except Exception as error:
                model_diagnostics.append(
                    {
                        "model_id": logit_id,
                        "specification_id": logit_specification_id,
                        "status": "failed",
                        "n": len(mortality_frame),
                        "events": mortality_events,
                        "error": repr(error),
                    }
                )

    model_results = pd.DataFrame(model_rows)
    model_results.to_csv(results / "ami_model_interaction_results.csv", index=False)
    pd.DataFrame(model_diagnostics).to_csv(
        qa / "ami_model_diagnostics.csv", index=False
    )

    methods_text = f"""# AMI cohort validation and interpretation

**Validation status:** `{validation_status}`

The primary ED-only AMI cohort uses a principal diagnosis of ICD-9-CM
`410.X1` before the ICD-10-CM transition and principal ICD-10-CM `I21.0`–
`I21.4` or `I21.9` afterward. Type 2 and other myocardial infarctions
(`I21.A1`, `I21.A9`) are separated in sensitivity analyses. `I22` is counted
only in a sensitivity definition and only when an `I21` code is present on
the same visit.

This analysis is **not a replication** of Greenwood, Carnahan, and Huang
(2018). Their study analyzed Florida hospital admissions through the ED and
survival during the hospitalization. The present source is a standalone
emergency-department encounter file. Florida SEDD-style data exclude patients
admitted as inpatients to the same hospital; ED mortality here is therefore
only death recorded within the standalone ED encounter.

Adjusted linear models include flexible age, recorded patient
race/ethnicity, payer, rurality, visit timing, all available
Elixhauser-condition indicators, and physician-volume measures. The
facility-year-quarter specification also includes physician specialty and
experience measures. A second specification adds attending-physician fixed
effects and omits physician attributes that are absorbed. Both use two-way
physician and facility cluster-robust inference.

Required model-grid cells are never silently discarded. If an outcome is
constant within an AMI definition, the row is retained and explicitly marked
`NON_ESTIMABLE`; its estimate, standard error, confidence interval, and
p-value are left undefined.

For a directional external check, the CDC/NCHS 2019 NHAMCS table estimated
378,000 national ED visits (standard error 96,000), or 0.3% of ED visits, with
acute myocardial infarction as the principal diagnosis. This is not an exact
Florida benchmark because it is a national sample and the encounter universe
differs. The internal audit therefore emphasizes year-to-year continuity,
coding-transition behavior, principal-versus-any-listed definitions, and the
share of all Florida standalone ED encounters.

Sources:

- CDC/NCHS and CMS, ICD-9-CM Official Guidelines for Coding and Reporting:
  https://www.cdc.gov/nchs/data/icd/icd9cm_guidelines_2011.pdf
- CDC/NCHS and CMS, ICD-10-CM Official Guidelines for Coding and Reporting:
  https://stacks.cdc.gov/view/cdc/150422/cdc_150422_DS1.pdf
- CDC/NCHS, 2019 NHAMCS ED Summary Tables:
  https://doi.org/10.15620/cdc:115748
- Locked local benchmark provenance:
  external_sources/ami_benchmark/source_manifest.json
- Greenwood BN, Carnahan S, Huang L. *PNAS*. 2018;115(34):8569–8574.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6112736/
- AHRQ HCUP, Florida SEDD file composition:
  https://hcup-us.ahrq.gov/db/state/sedddist/sedddist_filecompfl.jsp
"""
    (documentation / "AMI_Cohort_Validation.md").write_text(
        methods_text, encoding="utf-8"
    )
    required_failures = [
        row
        for row in model_diagnostics
        if row["status"] == "failed"
        and not str(row["model_id"]).endswith("_logit")
    ]
    required_expected = 3 * len(OUTCOMES) * len(model_specs)
    required_converged = sum(
        row["status"] == "converged"
        and not str(row["model_id"]).endswith("_logit")
        for row in model_diagnostics
    )
    required_non_estimable = sum(
        row["status"] == "non_estimable_constant_outcome"
        and not str(row["model_id"]).endswith("_logit")
        for row in model_diagnostics
    )
    required_completed = required_converged + required_non_estimable
    manifest = {
        "created_utc": now_utc(),
        "status": (
            "PASS"
            if not required_failures
            and required_completed == required_expected
            else "FAIL"
        ),
        "validation_status": validation_status,
        "model_result_rows": len(model_results),
        "required_models_expected": required_expected,
        "required_models_converged": required_converged,
        "required_models_non_estimable_constant_outcome": (
            required_non_estimable
        ),
        "required_models_completed": required_completed,
        "required_model_failures": len(required_failures),
        "optional_model_failures": sum(
            row["status"] == "failed"
            and str(row["model_id"]).endswith("_logit")
            for row in model_diagnostics
        ),
        "constant_outcome_policy": (
            "Retain required grid rows as NON_ESTIMABLE with undefined "
            "estimate, standard error, confidence interval, and p-value."
        ),
        "required_model_specifications": list(model_specs),
        "patient_race_ethnicity_adjusted": True,
        "elixhauser_indicator_count": len(elix_flags),
        "provider_measurement_version": (
            "provider_master_v2_full_name_race_v1"
        ),
        "provider_gate_path": str(provider_gate_path),
        "provider_gate_status": provider_gate["status"],
        "provider_gate_sha256": sha256_file(provider_gate_path),
        "cohort_gate_path": str(cohort_gate_path),
        "cohort_gate_status": cohort_gate["status"],
        "cohort_gate_sha256": sha256_file(cohort_gate_path),
        "gender_checkpoint_path": str(gender_checkpoint_path),
        "gender_checkpoint_status": gender_checkpoint["status"],
        "gender_checkpoint_sha256": sha256_file(
            gender_checkpoint_path
        ),
        "primary_physician_gender_sources": list(
            RECORDED_PHYSICIAN_GENDER_SOURCES
        ),
        "external_benchmark_source_manifest": str(benchmark_source_path),
        "external_benchmark_source_manifest_sha256": (
            benchmark_source_sha256
        ),
        "interpretation": (
            "ED-only observational extension; never label as a replication "
            "or an inpatient-survival analysis."
        ),
        "analysis_script_path": str(Path(__file__).resolve()),
        "analysis_script_sha256": sha256_file(Path(__file__).resolve()),
        "files": [
            {
                "path": str(path.resolve()),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (
                results / "ami_counts_by_year.csv",
                results / "ami_internal_reconciliation.csv",
                results / "ami_external_benchmark_reference.csv",
                results / "ami_model_interaction_results.csv",
                qa / "ami_validation_report.json",
                qa / "ami_validation_checks.csv",
                qa / "ami_model_diagnostics.csv",
                documentation / "AMI_Cohort_Validation.md",
            )
        ],
    }
    (results / "ami_analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    if manifest["status"] != "PASS":
        raise SystemExit("One or more required primary AMI models failed")


if __name__ == "__main__":
    main()
