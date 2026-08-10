#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/02_measurement_feasibility.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Audit Phase 2 measurement and cohort feasibility without altering the release."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


YEARS = [*range(2010, 2025)]
RACE_THRESHOLDS = (0.50, 0.70, 0.80, 0.90)


def qpath(path: Path) -> str:
    """Return a SQL-safe literal path."""
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--memory-limit", default="24GB")
    args = parser.parse_args()

    release = args.release.resolve()
    output = args.output.resolve()
    temp = args.temp.resolve()
    output.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(temp)}'")
    con.execute("SET preserve_insertion_order=false")

    physician_master = (
        release / "dimensions" / "physician_master.parquet"
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW physician_master AS
        SELECT
            npi,
            surname_prob_white,
            surname_prob_black,
            surname_prob_api,
            surname_prob_aian,
            surname_prob_multiracial,
            surname_prob_hispanic,
            surname_imputed_race_ethnicity,
            surname_imputation_max_probability,
            gender_category,
            physician_md_do_flag
        FROM read_parquet('{qpath(physician_master)}')
        """
    )

    timing_rows: list[pd.DataFrame] = []
    cohort_rows: list[pd.DataFrame] = []
    threshold_rows: list[pd.DataFrame] = []

    for year in YEARS:
        fact_pattern = (
            release
            / "fact_ed_visits"
            / f"visit_year={year}"
            / "visit_quarter=*"
            / "ed_visits.parquet"
        )
        fact_sql = f"read_parquet('{qpath(fact_pattern)}')"

        timing = con.execute(
            f"""
            WITH x AS (
                SELECT
                    visit_quarter,
                    arrival_hour,
                    TRY_CAST(ed_discharge_hour_raw AS INTEGER) AS discharge_hour,
                    length_of_stay_days,
                    total_charge_reported,
                    total_charge,
                    component_charge_sum
                FROM {fact_sql}
            ), y AS (
                SELECT
                    *,
                    CASE
                        WHEN arrival_hour BETWEEN 0 AND 23
                         AND discharge_hour BETWEEN 0 AND 23
                        THEN 24.0 * length_of_stay_days
                           + discharge_hour - arrival_hour
                    END AS los_hours_clock
                FROM x
            )
            SELECT
                {year}::INTEGER AS visit_year,
                COUNT(*) AS visits,
                COUNT(*) FILTER (
                    WHERE arrival_hour BETWEEN 0 AND 23
                ) AS valid_arrival_hour_visits,
                COUNT(*) FILTER (
                    WHERE discharge_hour BETWEEN 0 AND 23
                ) AS valid_discharge_hour_visits,
                COUNT(*) FILTER (
                    WHERE discharge_hour = 99
                ) AS unknown_discharge_hour_visits,
                COUNT(los_hours_clock) AS clock_los_constructible_visits,
                COUNT(*) FILTER (
                    WHERE los_hours_clock < 0
                ) AS clock_los_negative_visits,
                COUNT(*) FILTER (
                    WHERE los_hours_clock >= 0
                ) AS clock_los_nonnegative_visits,
                COUNT(*) FILTER (
                    WHERE los_hours_clock BETWEEN 0 AND 72
                ) AS clock_los_0_72h_visits,
                COUNT(*) FILTER (
                    WHERE los_hours_clock BETWEEN 0 AND 168
                ) AS clock_los_0_168h_visits,
                COUNT(*) FILTER (
                    WHERE los_hours_clock > 168
                ) AS clock_los_over_168h_visits,
                AVG(los_hours_clock) FILTER (
                    WHERE los_hours_clock >= 0
                ) AS clock_los_mean_nonnegative,
                APPROX_QUANTILE(los_hours_clock, 0.50) FILTER (
                    WHERE los_hours_clock >= 0
                ) AS clock_los_median_nonnegative,
                APPROX_QUANTILE(los_hours_clock, 0.95) FILTER (
                    WHERE los_hours_clock >= 0
                ) AS clock_los_p95_nonnegative,
                APPROX_QUANTILE(los_hours_clock, 0.99) FILTER (
                    WHERE los_hours_clock >= 0
                ) AS clock_los_p99_nonnegative,
                APPROX_QUANTILE(los_hours_clock, 0.995) FILTER (
                    WHERE los_hours_clock >= 0
                ) AS clock_los_p995_nonnegative,
                MAX(los_hours_clock) FILTER (
                    WHERE los_hours_clock >= 0
                ) AS clock_los_max_nonnegative,
                COUNT(total_charge_reported) AS reported_charge_nonmissing,
                COUNT(*) FILTER (
                    WHERE total_charge_reported = 0
                ) AS reported_charge_zero,
                COUNT(*) FILTER (
                    WHERE total_charge_reported < 0
                ) AS reported_charge_negative,
                COUNT(total_charge) AS canonical_charge_nonmissing,
                COUNT(*) FILTER (
                    WHERE total_charge = 0
                ) AS canonical_charge_zero,
                COUNT(*) FILTER (
                    WHERE total_charge < 0
                ) AS canonical_charge_negative,
                COUNT(component_charge_sum) AS component_sum_nonmissing,
                COUNT(*) FILTER (
                    WHERE component_charge_sum = 0
                ) AS component_sum_zero,
                COUNT(*) FILTER (
                    WHERE component_charge_sum < 0
                ) AS component_sum_negative
            FROM y
            """
        ).df()
        timing_rows.append(timing)

        cohort = con.execute(
            f"""
            WITH x AS (
                SELECT
                    f.visit_quarter,
                    f.facility_ahca_id,
                    f.visit_key,
                    f.attending_selected_npi,
                    f.attending_selection_method,
                    f.attending_physician_master_matched_flag,
                    f.attending_physician_md_do_flag,
                    f.race_category,
                    f.ethnicity_category,
                    f.sex_category,
                    f.attending_gender_category,
                    f.attending_surname_imputed_race_ethnicity,
                    p.surname_prob_white,
                    p.surname_prob_black,
                    p.surname_imputation_max_probability
                FROM {fact_sql} AS f
                LEFT JOIN physician_master AS p
                  ON f.attending_selected_npi = p.npi
            )
            SELECT
                {year}::INTEGER AS visit_year,
                COUNT(*) AS all_ed_visits,
                COUNT(*) FILTER (
                    WHERE attending_selected_npi IS NOT NULL
                ) AS resolved_attending_visits,
                COUNT(*) FILTER (
                    WHERE attending_selection_method = 'direct_validated_npi'
                ) AS direct_npi_attending_visits,
                COUNT(*) FILTER (
                    WHERE attending_selection_method =
                          'unique_fl_license_crosswalk'
                ) AS unique_license_attending_visits,
                COUNT(*) FILTER (
                    WHERE attending_physician_master_matched_flag
                ) AS physician_master_matched_visits,
                COUNT(*) FILTER (
                    WHERE attending_physician_md_do_flag
                ) AS md_do_attending_visits,
                COUNT(*) FILTER (
                    WHERE race_category IN (
                              'Black or African American', 'White'
                          )
                      AND ethnicity_category = 'Not Hispanic or Latino'
                ) AS patient_nh_black_white_visits,
                COUNT(*) FILTER (
                    WHERE race_category IN (
                              'Black or African American', 'White'
                          )
                ) AS patient_race_only_black_white_visits,
                COUNT(*) FILTER (
                    WHERE attending_surname_imputed_race_ethnicity IN (
                        'Non-Hispanic Black', 'Non-Hispanic White'
                    )
                ) AS physician_hard_black_white_visits,
                COUNT(*) FILTER (
                    WHERE sex_category IN ('Female', 'Male')
                ) AS patient_binary_sex_visits,
                COUNT(*) FILTER (
                    WHERE attending_gender_category IN ('Female', 'Male')
                ) AS physician_binary_gender_visits,
                COUNT(*) FILTER (
                    WHERE attending_selection_method = 'direct_validated_npi'
                      AND attending_physician_master_matched_flag
                      AND attending_physician_md_do_flag
                      AND race_category IN (
                              'Black or African American', 'White'
                          )
                      AND ethnicity_category = 'Not Hispanic or Latino'
                      AND attending_surname_imputed_race_ethnicity IN (
                          'Non-Hispanic Black', 'Non-Hispanic White'
                      )
                      AND surname_imputation_max_probability >= 0.50
                ) AS race_primary_eligible_visits,
                COUNT(DISTINCT attending_selected_npi) FILTER (
                    WHERE attending_selection_method = 'direct_validated_npi'
                      AND attending_physician_master_matched_flag
                      AND attending_physician_md_do_flag
                      AND race_category IN (
                              'Black or African American', 'White'
                          )
                      AND ethnicity_category = 'Not Hispanic or Latino'
                      AND attending_surname_imputed_race_ethnicity IN (
                          'Non-Hispanic Black', 'Non-Hispanic White'
                      )
                      AND surname_imputation_max_probability >= 0.50
                ) AS race_primary_distinct_physicians,
                COUNT(DISTINCT facility_ahca_id) FILTER (
                    WHERE attending_selection_method = 'direct_validated_npi'
                      AND attending_physician_master_matched_flag
                      AND attending_physician_md_do_flag
                      AND race_category IN (
                              'Black or African American', 'White'
                          )
                      AND ethnicity_category = 'Not Hispanic or Latino'
                      AND attending_surname_imputed_race_ethnicity IN (
                          'Non-Hispanic Black', 'Non-Hispanic White'
                      )
                      AND surname_imputation_max_probability >= 0.50
                ) AS race_primary_distinct_facilities,
                COUNT(*) FILTER (
                    WHERE attending_selection_method = 'direct_validated_npi'
                      AND attending_physician_master_matched_flag
                      AND attending_physician_md_do_flag
                      AND sex_category IN ('Female', 'Male')
                      AND attending_gender_category IN ('Female', 'Male')
                ) AS sex_gender_primary_eligible_visits
            FROM x
            """
        ).df()
        cohort_rows.append(cohort)

        threshold_values = ", ".join(f"({x})" for x in RACE_THRESHOLDS)
        by_pair = con.execute(
            f"""
                WITH eligible AS (
                    SELECT
                        f.attending_surname_imputed_race_ethnicity,
                        f.race_category,
                        f.attending_selected_npi,
                        f.facility_ahca_id,
                        p.surname_imputation_max_probability
                    FROM {fact_sql} AS f
                    INNER JOIN physician_master AS p
                      ON f.attending_selected_npi = p.npi
                    WHERE f.attending_selection_method =
                          'direct_validated_npi'
                      AND f.attending_physician_md_do_flag
                      AND f.race_category IN (
                              'Black or African American', 'White'
                          )
                      AND f.ethnicity_category = 'Not Hispanic or Latino'
                      AND f.attending_surname_imputed_race_ethnicity IN (
                          'Non-Hispanic Black', 'Non-Hispanic White'
                      )
                ), thresholds(physician_proxy_threshold) AS (
                    VALUES {threshold_values}
                )
                SELECT
                    {year}::INTEGER AS visit_year,
                    t.physician_proxy_threshold::DOUBLE
                        AS physician_proxy_threshold,
                    CASE
                        WHEN e.attending_surname_imputed_race_ethnicity =
                             'Non-Hispanic Black'
                         AND e.race_category = 'Black or African American'
                        THEN 'black_black'
                        WHEN e.attending_surname_imputed_race_ethnicity =
                             'Non-Hispanic Black'
                         AND e.race_category = 'White'
                        THEN 'black_white'
                        WHEN e.attending_surname_imputed_race_ethnicity =
                             'Non-Hispanic White'
                         AND e.race_category = 'Black or African American'
                        THEN 'white_black'
                        WHEN e.attending_surname_imputed_race_ethnicity =
                             'Non-Hispanic White'
                         AND e.race_category = 'White'
                        THEN 'white_white'
                    END AS race_pair_category,
                    COUNT(*) AS visits,
                    COUNT(DISTINCT e.attending_selected_npi) AS physicians,
                    COUNT(DISTINCT e.facility_ahca_id) AS facilities
                FROM eligible AS e
                CROSS JOIN thresholds AS t
                WHERE e.surname_imputation_max_probability >=
                      t.physician_proxy_threshold
                GROUP BY
                    t.physician_proxy_threshold,
                    race_pair_category
                ORDER BY
                    t.physician_proxy_threshold,
                    race_pair_category
            """
        ).df()
        threshold_rows.append(by_pair)

    timing_df = pd.concat(timing_rows, ignore_index=True)
    cohort_df = pd.concat(cohort_rows, ignore_index=True)
    threshold_df = pd.concat(threshold_rows, ignore_index=True)

    timing_df.to_csv(output / "timing_and_charge_feasibility_by_year.csv", index=False)
    cohort_df.to_csv(output / "main_cohort_feasibility_by_year.csv", index=False)
    threshold_df.to_csv(
        output / "race_pair_counts_by_year_and_threshold.csv", index=False
    )

    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release": str(release),
        "years": YEARS,
        "primary_period": "2010-2024",
        "los_hour_rule": (
            "24*length_of_stay_days + valid ED discharge hour - valid arrival "
            "hour; invalid 99 codes and negative results are not analyzed"
        ),
        "race_primary_eligibility": (
            "Direct validated attending NPI; physician-master match; MD/DO; "
            "patient non-Hispanic Black or non-Hispanic White; attending "
            "surname-imputed non-Hispanic Black or non-Hispanic White proxy; "
            "maximum surname probability >=0.50"
        ),
        "race_thresholds_audited": list(RACE_THRESHOLDS),
        "aggregate_counts": {
            "all_ed_visits_2010_2024": int(cohort_df["all_ed_visits"].sum()),
            "race_primary_eligible_visits": int(
                cohort_df["race_primary_eligible_visits"].sum()
            ),
            "sex_gender_primary_eligible_visits": int(
                cohort_df["sex_gender_primary_eligible_visits"].sum()
            ),
            "clock_los_nonnegative_visits": int(
                timing_df["clock_los_nonnegative_visits"].sum()
            ),
            "clock_los_negative_visits": int(
                timing_df["clock_los_negative_visits"].sum()
            ),
            "clock_los_over_168h_visits": int(
                timing_df["clock_los_over_168h_visits"].sum()
            ),
        },
        "source_release_modified": False,
    }
    (output / "measurement_feasibility_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    con.close()


if __name__ == "__main__":
    main()
