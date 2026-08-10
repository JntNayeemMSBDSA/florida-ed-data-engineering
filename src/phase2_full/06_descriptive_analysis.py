#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/06_descriptive_analysis.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Generate exact full-cohort descriptive and unadjusted concordance results."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import norm


RACE_PAIRS = ["black_black", "black_white", "white_black", "white_white"]
SEX_PAIRS = ["female_female", "female_male", "male_female", "male_male"]
CONTRAST_WEIGHTS = np.array([1.0, -1.0, -1.0, 1.0])

CORE_OUTCOMES = {
    "los_hours_primary_0_168": "continuous",
    "total_charge_reported_real_2024": "continuous",
    "total_charge_reported": "continuous",
    "total_charge_real_2024": "continuous",
    "component_charge_sum_real_2024": "continuous",
    "procedure_count_analysis": "continuous",
    "any_procedure_flag": "binary",
    "high_procedure_flag": "binary",
    "em_acuity_proxy_level": "continuous",
    "em_critical_care_flag": "binary",
    "routine_discharge_flag": "binary",
    "transfer_flag": "binary",
    "hospice_flag": "binary",
    "mortality_flag": "binary",
    "left_discontinued_care_flag": "binary",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def save_query(
    con: duckdb.DuckDBPyConnection, sql: str, output_path: Path
) -> pd.DataFrame:
    frame = con.execute(sql).fetchdf()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return frame


def summarize_pairs(
    con: duckdb.DuckDBPyConnection,
    source_sql: str,
    eligibility: str,
    pair_column: str,
    pairs: list[str],
    cohort_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    outcome_parts = []
    for outcome in CORE_OUTCOMES:
        numeric_outcome = f"cast({outcome} AS DOUBLE)"
        outcome_parts.append(
            f"""
            SELECT
                '{cohort_id}' AS cohort_id,
                '{outcome}' AS outcome,
                {pair_column} AS pair_category,
                count(*) AS eligible_pair_visits,
                count({outcome}) AS outcome_nonmissing_n,
                count(*) - count({outcome}) AS outcome_missing_n,
                avg({numeric_outcome}) AS mean,
                stddev_samp({numeric_outcome}) AS sd,
                quantile_cont({numeric_outcome}, 0.01) AS p01,
                quantile_cont({numeric_outcome}, 0.25) AS p25,
                quantile_cont({numeric_outcome}, 0.50) AS median,
                quantile_cont({numeric_outcome}, 0.75) AS p75,
                quantile_cont({numeric_outcome}, 0.99) AS p99,
                min({numeric_outcome}) AS minimum,
                max({numeric_outcome}) AS maximum
            FROM {source_sql}
            WHERE {eligibility}
            GROUP BY {pair_column}
            """
        )
    summary = con.execute(" UNION ALL ".join(outcome_parts)).fetchdf()
    summary["pair_category"] = pd.Categorical(
        summary["pair_category"], categories=pairs, ordered=True
    )
    summary = summary.sort_values(["outcome", "pair_category"]).reset_index(
        drop=True
    )

    contrast_rows = []
    for outcome, block in summary.groupby("outcome", observed=True):
        block = block.set_index("pair_category").reindex(pairs)
        if block["mean"].isna().any():
            continue
        means = block["mean"].to_numpy(dtype=float)
        counts = block["outcome_nonmissing_n"].to_numpy(dtype=float)
        sds = block["sd"].to_numpy(dtype=float)
        estimate = float(CONTRAST_WEIGHTS @ means)
        # The four visit cells are mutually exclusive. This is the exact
        # conventional unclustered variance for a contrast of sample means;
        # clustered inference is provided by the regression models.
        variance = float(np.sum((CONTRAST_WEIGHTS**2) * (sds**2 / counts)))
        se = math.sqrt(variance)
        z_value = estimate / se if se > 0 else math.nan
        p_value = (
            float(2 * norm.sf(abs(z_value))) if math.isfinite(z_value) else math.nan
        )
        overall = con.execute(
            f"""
            SELECT avg(cast({outcome} AS DOUBLE))
            FROM {source_sql}
            WHERE {eligibility} AND {outcome} IS NOT NULL
            """
        ).fetchone()[0]
        contrast_rows.append(
            {
                "cohort_id": cohort_id,
                "outcome": outcome,
                "contrast_definition": (
                    f"{pairs[0]} - {pairs[1]} - {pairs[2]} + {pairs[3]}"
                ),
                "estimate_absolute": estimate,
                "standard_error_unclustered_descriptive": se,
                "ci95_low_unclustered_descriptive": estimate - 1.95996398454 * se,
                "ci95_high_unclustered_descriptive": estimate + 1.95996398454 * se,
                "z_value_unclustered_descriptive": z_value,
                "p_value_unclustered_descriptive": p_value,
                "eligible_outcome_n": int(np.sum(counts)),
                "eligible_outcome_mean": float(overall),
                "contrast_percent_of_eligible_mean": (
                    100 * estimate / overall if overall not in (None, 0) else math.nan
                ),
                "ci95_low_percent_of_eligible_mean": (
                    100 * (estimate - 1.95996398454 * se) / overall
                    if overall not in (None, 0)
                    else math.nan
                ),
                "ci95_high_percent_of_eligible_mean": (
                    100 * (estimate + 1.95996398454 * se) / overall
                    if overall not in (None, 0)
                    else math.nan
                ),
                "inference_note": (
                    "Descriptive-only independent-cell standard error; use the "
                    "multiway-clustered adjusted model for confirmatory inference."
                ),
            }
        )
    return summary, pd.DataFrame(contrast_rows)


def standardized_balance_contrasts(balance: pd.DataFrame) -> pd.DataFrame:
    comparisons = {
        "race_primary_t50": [
            (
                "patient_race_within_black_physician",
                "black_black",
                "black_white",
            ),
            (
                "patient_race_within_white_physician",
                "white_black",
                "white_white",
            ),
            (
                "physician_race_within_black_patient",
                "black_black",
                "white_black",
            ),
            (
                "physician_race_within_white_patient",
                "black_white",
                "white_white",
            ),
        ],
        "sex_gender_primary": [
            (
                "patient_sex_within_female_physician",
                "female_female",
                "female_male",
            ),
            (
                "patient_sex_within_male_physician",
                "male_female",
                "male_male",
            ),
            (
                "physician_gender_within_female_patient",
                "female_female",
                "male_female",
            ),
            (
                "physician_gender_within_male_patient",
                "female_male",
                "male_male",
            ),
        ],
    }
    rows: list[dict[str, object]] = []
    indexed = balance.set_index(
        ["cohort_id", "variable", "pair_category"]
    )
    for cohort_id, cohort_comparisons in comparisons.items():
        variables = balance.loc[
            balance["cohort_id"] == cohort_id, "variable"
        ].unique()
        for variable in variables:
            for comparison_id, numerator, denominator in cohort_comparisons:
                try:
                    first = indexed.loc[(cohort_id, variable, numerator)]
                    second = indexed.loc[(cohort_id, variable, denominator)]
                except KeyError:
                    continue
                n1 = float(first["nonmissing_n"])
                n0 = float(second["nonmissing_n"])
                sd1 = float(first["sd"])
                sd0 = float(second["sd"])
                denominator_df = n1 + n0 - 2
                pooled_sd = (
                    math.sqrt(
                        ((n1 - 1) * sd1**2 + (n0 - 1) * sd0**2)
                        / denominator_df
                    )
                    if denominator_df > 0
                    else math.nan
                )
                mean_difference = float(first["mean"] - second["mean"])
                smd = (
                    mean_difference / pooled_sd
                    if pooled_sd > 0 and math.isfinite(pooled_sd)
                    else math.nan
                )
                rows.append(
                    {
                        "cohort_id": cohort_id,
                        "variable": variable,
                        "comparison_id": comparison_id,
                        "numerator_pair": numerator,
                        "denominator_pair": denominator,
                        "numerator_n": int(n1),
                        "denominator_n": int(n0),
                        "numerator_mean": float(first["mean"]),
                        "denominator_mean": float(second["mean"]),
                        "mean_difference": mean_difference,
                        "pooled_sd": pooled_sd,
                        "standardized_mean_difference": smd,
                        "absolute_standardized_mean_difference": abs(smd),
                        "absolute_smd_ge_0_10": (
                            abs(smd) >= 0.10 if math.isfinite(smd) else False
                        ),
                        "interpretation": (
                            "Descriptive imbalance diagnostic only; not a "
                            "test of exchangeability or causal identification."
                        ),
                    }
                )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--temp", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    data_root = (
        phase2 / "analysis_data" / "concordance_visit_data_provider_v2"
    )
    results_root = phase2 / "results" / "descriptive"
    results_root.mkdir(parents=True, exist_ok=True)
    args.temp.mkdir(parents=True, exist_ok=True)
    core_glob = data_root / "visit_year=*" / "visit_quarter=*" / (
        "concordance_visit_core.parquet"
    )
    charge_glob = data_root / "visit_year=*" / "visit_quarter=*" / (
        "concordance_charge_components.parquet"
    )

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(args.temp)}'")
    con.execute("SET preserve_insertion_order=false")
    source_sql = (
        f"read_parquet('{qpath(core_glob)}', hive_partitioning=false)"
    )

    by_year = save_query(
        con,
        f"""
        SELECT
            visit_year,
            count(*) AS derived_union_visits,
            sum(race_primary_eligible_t50_flag) AS race_primary_t50_visits,
            sum(race_primary_eligible_t70_flag) AS race_primary_t70_visits,
            sum(race_primary_eligible_t80_flag) AS race_primary_t80_visits,
            sum(race_primary_eligible_t90_flag) AS race_primary_t90_visits,
            sum(sex_gender_primary_eligible_flag) AS sex_gender_primary_visits,
            count(DISTINCT attending_selected_npi)
                FILTER (WHERE race_primary_eligible_t50_flag = 1)
                AS race_primary_physicians,
            count(DISTINCT facility_ahca_id)
                FILTER (WHERE race_primary_eligible_t50_flag = 1)
                AS race_primary_facilities,
            count(DISTINCT attending_selected_npi)
                FILTER (WHERE sex_gender_primary_eligible_flag = 1)
                AS sex_gender_primary_physicians,
            count(DISTINCT facility_ahca_id)
                FILTER (WHERE sex_gender_primary_eligible_flag = 1)
                AS sex_gender_primary_facilities
        FROM {source_sql}
        GROUP BY visit_year
        ORDER BY visit_year
        """,
        results_root / "cohort_counts_by_year.csv",
    )

    missing_fields = [
        "age_years",
        "patient_sex_category",
        "patient_race_category",
        "patient_ethnicity_category",
        "payer_group",
        "patient_zip_rurality_3level",
        "arrival_hour",
        "los_hours_primary_0_168",
        "principal_clinical_category",
        "total_charge_reported",
        "total_charge_reported_real_2024",
        "procedure_count_analysis",
        "em_acuity_proxy_level",
        "em_critical_care_flag",
        "em_acuity_proxy_status",
        "attending_selected_npi",
        "physician_gender_category",
        "physician_race_proxy_primary_label",
        "physician_race_imputation_confidence",
        "attending_ed_specialist_flag",
        "attending_years_since_medical_school",
        "attending_has_fl_doh_hospital_privilege",
        "attending_doh_hospital_privilege_count",
        "attending_has_cms_group_practice_affiliation",
        "attending_cms_group_practice_count",
        "facility_rurality_3level",
        "cms_hospital_type",
        "cms_hospital_ownership",
    ]
    missing_union = " UNION ALL ".join(
        f"""
        SELECT
            visit_year,
            '{field}' AS variable,
            count(*) AS cohort_n,
            count({field}) AS nonmissing_n,
            count(*) - count({field}) AS missing_n,
            100.0 * (count(*) - count({field})) / count(*) AS missing_percent
        FROM {source_sql}
        GROUP BY visit_year
        """
        for field in missing_fields
    )
    save_query(
        con,
        missing_union + " ORDER BY variable, visit_year",
        results_root / "missingness_by_year.csv",
    )

    categorical_fields = [
        "physician_linkage_method",
        "race_pair_category",
        "sex_gender_pair_category",
        "payer_group",
        "patient_zip_rurality_3level",
        "patient_sex_category",
        "patient_race_category",
        "patient_ethnicity_category",
        "physician_gender_category",
        "physician_race_proxy_primary_label",
        "attending_ed_specialist_flag",
        "attending_has_fl_doh_hospital_privilege",
        "attending_has_cms_group_practice_affiliation",
        "facility_rurality_3level",
        "cms_hospital_type",
        "cms_hospital_ownership",
        "presentation_code_group",
        "em_acuity_proxy_status",
        "disposition_group",
        "principal_clinical_category",
    ]
    comp_union = " UNION ALL ".join(
        f"""
        SELECT
            '{field}' AS variable,
            coalesce(cast({field} AS VARCHAR), '<MISSING>') AS category,
            count(*) AS n,
            100.0 * count(*) / sum(count(*)) OVER () AS percent
        FROM {source_sql}
        GROUP BY {field}
        """
        for field in categorical_fields
    )
    save_query(
        con,
        comp_union + " ORDER BY variable, n DESC",
        results_root / "cohort_composition.csv",
    )

    race_summary, race_contrast = summarize_pairs(
        con,
        source_sql,
        "race_primary_eligible_t50_flag = 1",
        "race_pair_category",
        RACE_PAIRS,
        "race_primary_t50_nh_black_white_direct_npi",
    )
    race_summary.to_csv(results_root / "race_pair_descriptive_statistics.csv", index=False)
    race_contrast.to_csv(
        results_root / "race_unadjusted_interaction_contrasts.csv", index=False
    )
    sex_summary, sex_contrast = summarize_pairs(
        con,
        source_sql,
        "sex_gender_primary_eligible_flag = 1",
        "sex_gender_pair_category",
        SEX_PAIRS,
        "sex_gender_primary_binary_direct_npi",
    )
    sex_summary.to_csv(
        results_root / "sex_gender_pair_descriptive_statistics.csv", index=False
    )
    sex_contrast.to_csv(
        results_root / "sex_gender_unadjusted_interaction_contrasts.csv", index=False
    )

    charge_source = (
        f"read_parquet('{qpath(charge_glob)}', hive_partitioning=false)"
    )
    charge_components = [
        "pharmchgs_real_2024",
        "medchgs_real_2024",
        "labchgs_real_2024",
        "radchgs_real_2024",
        "cardiochgs_real_2024",
        "oprmchgs_real_2024",
        "aneschgs_real_2024",
        "recovchgs_real_2024",
        "erchgs_real_2024",
        "traumachgs_real_2024",
        "obserchgs_real_2024",
        "gastrochgs_real_2024",
        "lithochgs_real_2024",
        "othchgs_real_2024",
    ]
    charge_parts = []
    for outcome in charge_components:
        charge_parts.append(
            f"""
            SELECT
                c.race_pair_category,
                '{outcome}' AS outcome,
                count(ch.{outcome}) AS nonmissing_n,
                avg(ch.{outcome}) AS mean,
                stddev_samp(ch.{outcome}) AS sd,
                quantile_cont(ch.{outcome}, 0.50) AS median,
                quantile_cont(ch.{outcome}, 0.25) AS p25,
                quantile_cont(ch.{outcome}, 0.75) AS p75
            FROM {source_sql} c
            INNER JOIN {charge_source} ch
              USING (visit_key, visit_year, visit_quarter)
            WHERE c.race_primary_eligible_t50_flag = 1
            GROUP BY c.race_pair_category
            """
        )
    save_query(
        con,
        " UNION ALL ".join(charge_parts) + " ORDER BY outcome, race_pair_category",
        results_root / "race_charge_component_descriptive_statistics.csv",
    )

    balance_fields = {
        "age_years": "continuous",
        "elixhauser_condition_count": "continuous",
        "attending_years_since_medical_school": "continuous",
        "attending_quarter_volume_all_ed": "continuous",
        "weekend_flag": "binary",
        "off_hours_flag": "binary",
        "attending_ed_specialist_flag": "binary",
        "off_site_ed_flag": "binary",
    }
    balance_parts = []
    for field in balance_fields:
        balance_parts.append(
            f"""
            SELECT
                'race_primary_t50' AS cohort_id,
                race_pair_category AS pair_category,
                '{field}' AS variable,
                count({field}) AS nonmissing_n,
                avg(cast({field} AS DOUBLE)) AS mean,
                stddev_samp(cast({field} AS DOUBLE)) AS sd
            FROM {source_sql}
            WHERE race_primary_eligible_t50_flag = 1
            GROUP BY race_pair_category
            """
        )
        balance_parts.append(
            f"""
            SELECT
                'sex_gender_primary' AS cohort_id,
                sex_gender_pair_category AS pair_category,
                '{field}' AS variable,
                count({field}) AS nonmissing_n,
                avg(cast({field} AS DOUBLE)) AS mean,
                stddev_samp(cast({field} AS DOUBLE)) AS sd
            FROM {source_sql}
            WHERE sex_gender_primary_eligible_flag = 1
            GROUP BY sex_gender_pair_category
            """
        )
    balance = save_query(
        con,
        " UNION ALL ".join(balance_parts) + " ORDER BY cohort_id, variable, pair_category",
        results_root / "pair_balance_continuous_binary.csv",
    )
    standardized_balance_contrasts(balance).to_csv(
        results_root / "pair_balance_standardized_differences.csv",
        index=False,
    )

    trends = save_query(
        con,
        f"""
        SELECT
            visit_year,
            race_pair_category,
            count(*) AS n,
            avg(los_hours_primary_0_168) AS los_mean,
            avg(total_charge_reported_real_2024) AS charge_real_mean,
            avg(cast(any_procedure_flag AS DOUBLE))
                AS any_procedure_rate,
            avg(cast(routine_discharge_flag AS DOUBLE))
                AS routine_discharge_rate,
            avg(cast(mortality_flag AS DOUBLE))
                AS ed_mortality_rate
        FROM {source_sql}
        WHERE race_primary_eligible_t50_flag = 1
        GROUP BY visit_year, race_pair_category
        ORDER BY visit_year, race_pair_category
        """,
        results_root / "race_pair_trends_by_year.csv",
    )

    provenance = {
        "created_utc": now_utc(),
        "data_source": str(data_root),
        "full_cohort_only": True,
        "race_primary_definition": (
            "2010-2024; direct validated attending NPI; matched MD/DO; "
            "non-Hispanic Black/White patient; provider-v2 full-name "
            "Black/White physician proxy using the Florida physician prior; "
            "matched first and last names; maximum posterior probability >=0.50"
        ),
        "sex_gender_primary_definition": (
            "2010-2024; direct validated attending NPI; matched MD/DO; "
            "recorded patient sex Female/Male; physician gender Female/Male"
        ),
        "interaction_order": "physician first, patient second",
        "provider_measurement_version": (
            "provider_master_v2_full_name_race_v1"
        ),
        "unadjusted_race_contrast": (
            "black_black - black_white - white_black + white_white"
        ),
        "unadjusted_se_note": (
            "Unclustered descriptive standard errors are not confirmatory; "
            "adjusted models use prespecified multiway cluster-robust inference."
        ),
        "files_created": sorted(path.name for path in results_root.glob("*.csv")),
        "summary_rows": {
            "years": int(len(by_year)),
            "race_descriptive_rows": int(len(race_summary)),
            "sex_gender_descriptive_rows": int(len(sex_summary)),
            "trend_rows": int(len(trends)),
        },
    }
    (results_root / "descriptive_analysis_manifest.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )
    con.close()
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
