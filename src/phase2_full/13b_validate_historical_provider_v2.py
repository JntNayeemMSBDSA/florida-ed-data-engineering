#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/13b_validate_historical_provider_v2.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently reconcile all 16 historical provider-v2 partitions to Phase 1.

This is an estimate-blind measurement and comparability gate. No model result
files are read. Historical analyses must verify the PASS artifact written by
this script before estimating or reporting results.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


YEARS = (2005, 2006, 2007, 2008)
QUARTERS = (1, 2, 3, 4)
EXPECTED_PARTITIONS = 16
BUILD_SPEC_VERSION = "historical_provider_v2_universe_v4"
OUTPUT_DIR_NAME = "historical_provider_v2"
OUTPUT_FILE_NAME = "historical_provider_v2_core.parquet"


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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def comparison_catalog() -> list[dict[str, str]]:
    return [
        {
            "domain": "encounter identity",
            "variable_or_outcome": "visit_key and quarter",
            "historical_availability": "available",
            "cross_period_status": "fully comparable",
            "permitted_use": "reconciliation, fixed effects, trends",
            "restriction": "All 16 partitions must reconcile exactly to Phase 1.",
        },
        {
            "domain": "patient demographics",
            "variable_or_outcome": "age_years and age bands",
            "historical_availability": "available",
            "cross_period_status": "comparable with missingness checks",
            "permitted_use": "covariate and stratification",
            "restriction": "Do not infer values when age is missing.",
        },
        {
            "domain": "patient demographics",
            "variable_or_outcome": "recorded patient sex",
            "historical_availability": "available",
            "cross_period_status": "comparable administrative field",
            "permitted_use": "sex/gender concordance and covariate",
            "restriction": "Not a measure of patient gender identity.",
        },
        {
            "domain": "patient demographics",
            "variable_or_outcome": "race/ethnicity",
            "historical_availability": "combined historical codes",
            "cross_period_status": "partially comparable",
            "permitted_use": "separate code-3 versus code-4 historical sensitivity",
            "restriction": (
                "Never pool with modern separate race and ethnicity fields; "
                "Hispanic historical codes are excluded from the Black/White contrast."
            ),
        },
        {
            "domain": "provider linkage",
            "variable_or_outcome": "attending NPI",
            "historical_availability": "license-derived NPI only",
            "cross_period_status": "not linkage-equivalent",
            "permitted_use": "separate historical sensitivity after linkage audit",
            "restriction": (
                "No direct source NPI in 2005-2008; only unique Florida-license "
                "crosswalk links are eligible."
            ),
        },
        {
            "domain": "provider measurement",
            "variable_or_outcome": "MD/DO, clinician type, specialty",
            "historical_availability": "provider master v2 cross-sectional linkage",
            "cross_period_status": "partially comparable",
            "permitted_use": "eligibility and sensitivity covariates",
            "restriction": (
                "Current registry attributes are not proof of historical activity, "
                "employment, specialty, or privilege."
            ),
        },
        {
            "domain": "provider measurement",
            "variable_or_outcome": "physician full-name race proxy",
            "historical_availability": "same provider-v2 method as primary era",
            "cross_period_status": "method-comparable, construct imperfect",
            "permitted_use": "probabilistic and threshold sensitivity analyses",
            "restriction": (
                "Algorithm-inferred name probabilities without geography; not BISG "
                "and not self-identified race/ethnicity."
            ),
        },
        {
            "domain": "provider measurement",
            "variable_or_outcome": "physician recorded/inferred gender category",
            "historical_availability": "provider master v2",
            "cross_period_status": "method-comparable, temporal caveat",
            "permitted_use": "recorded patient sex-physician gender concordance",
            "restriction": "Not a measure of historical gender identity.",
        },
        {
            "domain": "clinical coding",
            "variable_or_outcome": "diagnosis and clinical category",
            "historical_availability": "ICD-9-CM",
            "cross_period_status": "conceptually but not code-identical",
            "permitted_use": "era-specific adjustment and separate sensitivity",
            "restriction": "Do not assume ICD-9 and ICD-10 category equivalence.",
        },
        {
            "domain": "clinical coding",
            "variable_or_outcome": "Elixhauser condition flags",
            "historical_availability": "ICD-9-derived",
            "cross_period_status": "partially comparable",
            "permitted_use": "era-specific risk adjustment",
            "restriction": "Use era-appropriate definitions and report version differences.",
        },
        {
            "domain": "AMI/Greenwood",
            "variable_or_outcome": "AMI cohort",
            "historical_availability": "ICD-9-CM 410.X1 strict; 410.X0/X1 sensitivity",
            "cross_period_status": "conceptually comparable, code-era specific",
            "permitted_use": "separate historical ED-only Greenwood extension",
            "restriction": "Not an inpatient Greenwood replication.",
        },
        {
            "domain": "outcome",
            "variable_or_outcome": "ED mortality",
            "historical_availability": "available",
            "cross_period_status": "comparable ED disposition measure",
            "permitted_use": "binary outcome including historical AMI",
            "restriction": "Does not capture post-ED inpatient mortality.",
        },
        {
            "domain": "outcome",
            "variable_or_outcome": "routine discharge, transfer, hospice, left care",
            "historical_availability": "available",
            "cross_period_status": "comparable after code validation",
            "permitted_use": "separate historical outcomes",
            "restriction": "Report outcome-specific nonmissingness and code semantics.",
        },
        {
            "domain": "outcome",
            "variable_or_outcome": "same-facility inpatient admission",
            "historical_availability": "structurally unavailable in Phase 1 release",
            "cross_period_status": "not available",
            "permitted_use": "none",
            "restriction": "Do not treat missing as no admission.",
        },
        {
            "domain": "outcome",
            "variable_or_outcome": "length_of_stay_days",
            "historical_availability": "available at day granularity",
            "cross_period_status": "partially comparable",
            "permitted_use": "historical day-level LOS outcome only",
            "restriction": "Do not relabel or convert it to clock-hour LOS.",
        },
        {
            "domain": "outcome",
            "variable_or_outcome": "hourly LOS",
            "historical_availability": "structurally unavailable",
            "cross_period_status": "not comparable",
            "permitted_use": "none",
            "restriction": "Must remain null; no 24-times-days imputation.",
        },
        {
            "domain": "outcome",
            "variable_or_outcome": "procedure counts and treatment intensity",
            "historical_availability": "available",
            "cross_period_status": "partially comparable",
            "permitted_use": "separate historical outcome and within-era comparisons",
            "restriction": "Coding opportunities and procedure systems differ by era.",
        },
        {
            "domain": "outcome",
            "variable_or_outcome": "reported/component charges",
            "historical_availability": "available",
            "cross_period_status": "comparable after inflation adjustment with caveats",
            "permitted_use": "nominal and CPI-adjusted historical outcome",
            "restriction": "Charges are not costs or payments; billing practices may change.",
        },
        {
            "domain": "utilization",
            "variable_or_outcome": "7-day and 30-day revisit",
            "historical_availability": "structurally unavailable in Phase 1 release",
            "cross_period_status": "not available",
            "permitted_use": "none",
            "restriction": "Do not impute or interpret missing as no revisit.",
        },
        {
            "domain": "severity",
            "variable_or_outcome": "true triage level",
            "historical_availability": "structurally unavailable in Phase 1 release",
            "cross_period_status": "not available",
            "permitted_use": "none",
            "restriction": "E/M proxies may be separately labeled but are not triage.",
        },
        {
            "domain": "operations",
            "variable_or_outcome": "arrival hour, weekend, off-hours",
            "historical_availability": "available with small source missingness",
            "cross_period_status": "comparable after missingness checks",
            "permitted_use": "covariates and stratification",
            "restriction": "Arrival hour does not make hourly LOS available.",
        },
        {
            "domain": "facility",
            "variable_or_outcome": "facility identifiers and fixed effects",
            "historical_availability": "available",
            "cross_period_status": "comparable identifiers with facility-history caveats",
            "permitted_use": "fixed effects, clustering, within-era trends",
            "restriction": "Contemporary facility/provider affiliations are not historical employment.",
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    args = parser.parse_args()

    release = args.release.resolve()
    phase2 = args.phase2.resolve()
    temp = args.temp.resolve()
    temp.mkdir(parents=True, exist_ok=True)
    historical_root = phase2 / "analysis_data" / OUTPUT_DIR_NAME
    provider_master = phase2 / "analysis_data" / "dimensions" / "provider_master_v2.parquet"
    race_proxy = phase2 / "analysis_data" / "dimensions" / "provider_race_proxy_v2.parquet"
    gender_checkpoint_path = (
        phase2 / "qa" / "provider_gender_measurement_checkpoint.json"
    )
    build_manifest_path = historical_root / "historical_provider_v2_build_manifest.json"
    qa_dir = phase2 / "qa"
    documentation = phase2 / "documentation"
    qa_dir.mkdir(parents=True, exist_ok=True)
    documentation.mkdir(parents=True, exist_ok=True)
    for required in (
        provider_master,
        race_proxy,
        build_manifest_path,
        gender_checkpoint_path,
    ):
        if not required.exists():
            raise FileNotFoundError(required)
    provider_master_sha256 = sha256_file(provider_master)
    race_proxy_sha256 = sha256_file(race_proxy)
    gender_checkpoint = json.loads(
        gender_checkpoint_path.read_text(encoding="utf-8")
    )
    gender_checkpoint_valid = bool(
        gender_checkpoint.get("status") == "PASS"
        and gender_checkpoint.get("estimate_blind") is True
        and gender_checkpoint.get("primary_definition", {}).get(
            "physician_gender_sources"
        )
        == [
            "NPPES",
            "NPPES February 2026 current snapshot",
            "CMS Doctors and Clinicians",
            "CMS Doctors and Clinicians June 2026 current snapshot",
        ]
    )

    build_manifest = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    build_manifest_valid = bool(
        build_manifest.get("status") == "PASS"
        and build_manifest.get("build_spec_version") == BUILD_SPEC_VERSION
        and build_manifest.get("partitions") == EXPECTED_PARTITIONS
        and build_manifest.get("sample_modulus") == 0
        and build_manifest.get("years") == list(YEARS)
        and build_manifest.get("quarters") == list(QUARTERS)
        and build_manifest.get("provider_master_v2_sha256")
        == provider_master_sha256
        and build_manifest.get("provider_race_proxy_v2_sha256")
        == race_proxy_sha256
    )

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(temp)}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_master_v2 AS
        SELECT * FROM read_parquet('{qpath(provider_master)}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_race_proxy_v2 AS
        SELECT * FROM read_parquet('{qpath(race_proxy)}')
        """
    )

    partition_rows: list[dict[str, Any]] = []
    for year in YEARS:
        for quarter in QUARTERS:
            fact = (
                release
                / "fact_ed_visits"
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "ed_visits.parquet"
            )
            diagnosis = (
                release
                / "bridges"
                / "visit_diagnosis"
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "visit_diagnosis.parquet"
            )
            phase1_success_path = fact.parent / "_SUCCESS.json"
            output = (
                historical_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / OUTPUT_FILE_NAME
            )
            output_success_path = output.parent / "_SUCCESS.json"
            for required in (
                fact,
                diagnosis,
                phase1_success_path,
                output,
                output_success_path,
            ):
                if not required.exists():
                    raise FileNotFoundError(required)
            phase1_success = json.loads(
                phase1_success_path.read_text(encoding="utf-8")
            )
            output_success = json.loads(
                output_success_path.read_text(encoding="utf-8")
            )
            fact_sha_live = sha256_file(fact)
            output_sha_live = sha256_file(output)
            source = f"read_parquet('{qpath(fact)}', hive_partitioning=false)"
            derived = f"read_parquet('{qpath(output)}', hive_partitioning=false)"

            expected = con.execute(
                f"""
                SELECT
                    count(*) AS rows,
                    count(DISTINCT f.visit_key) AS distinct_keys,
                    count(*) FILTER (
                        WHERE f.attending_selection_method =
                            'unique_fl_license_crosswalk'
                          AND f.attending_selected_npi IS NOT NULL
                    ) AS license_resolved_rows,
                    count(*) FILTER (
                        WHERE p.npi IS NOT NULL
                    ) AS provider_v2_matched_rows,
                    count(*) FILTER (
                        WHERE f.attending_selection_method =
                                'unique_fl_license_crosswalk'
                          AND f.attending_selected_npi IS NOT NULL
                          AND p.provider_entity_category_v2 = 'Individual'
                          AND coalesce(p.physician_md_do_flag_v2, false)
                    ) AS provider_v2_md_do_rows,
                    count(*) FILTER (
                        WHERE f.race_raw IN ('3', '4')
                          AND f.attending_selection_method =
                                'unique_fl_license_crosswalk'
                          AND f.attending_selected_npi IS NOT NULL
                          AND p.provider_entity_category_v2 = 'Individual'
                          AND coalesce(p.physician_md_do_flag_v2, false)
                          AND r.race_proxy_primary_five_class_label
                                IN ('Black', 'White')
                          AND coalesce(r.last_match_flag, false)
                          AND coalesce(r.first_match_flag, false)
                          AND r.race_proxy_primary_max_probability >= 0.50
                    ) AS race_t50_rows,
                    count(*) FILTER (
                        WHERE f.sex_category IN ('Female', 'Male')
                          AND f.attending_selection_method =
                                'unique_fl_license_crosswalk'
                          AND f.attending_selected_npi IS NOT NULL
                          AND p.provider_entity_category_v2 = 'Individual'
                          AND coalesce(p.physician_md_do_flag_v2, false)
                          AND p.gender_category_v2 IN ('Female', 'Male')
                          AND p.gender_source_v2 IN (
                              'NPPES',
                              'NPPES February 2026 current snapshot',
                              'CMS Doctors and Clinicians',
                              'CMS Doctors and Clinicians June 2026 current snapshot'
                          )
                    ) AS sex_gender_rows,
                    count(*) FILTER (
                        WHERE f.diagnosis_code_system = 'ICD-9-CM'
                          AND regexp_full_match(
                              f.principal_diagnosis_code_norm, '410[0-9]1'
                          )
                    ) AS ami_principal_strict_rows,
                    count(*) FILTER (
                        WHERE f.diagnosis_code_system = 'ICD-9-CM'
                          AND regexp_full_match(
                              f.principal_diagnosis_code_norm, '410[0-9][01]'
                          )
                    ) AS ami_principal_broad_rows
                FROM {source} AS f
                LEFT JOIN provider_master_v2 AS p
                  ON f.attending_selected_npi = p.npi
                LEFT JOIN provider_race_proxy_v2 AS r
                  ON f.attending_selected_npi = r.npi
                """
            ).fetchone()
            expected_anylisted = con.execute(
                f"""
                SELECT
                    count(DISTINCT visit_key) FILTER (
                        WHERE regexp_full_match(
                            diagnosis_code_norm, '410[0-9]1'
                        )
                    ) AS strict_rows,
                    count(DISTINCT visit_key) FILTER (
                        WHERE regexp_full_match(
                            diagnosis_code_norm, '410[0-9][01]'
                        )
                    ) AS broad_rows
                FROM read_parquet(
                    '{qpath(diagnosis)}', hive_partitioning=false
                )
                WHERE diagnosis_role IN ('principal', 'secondary')
                  AND diagnosis_code_system = 'ICD-9-CM'
                  AND starts_with(diagnosis_code_norm, '410')
                """
            ).fetchone()
            observed = con.execute(
                f"""
                SELECT
                    count(*) AS rows,
                    count(DISTINCT visit_key) AS distinct_keys,
                    count(*) FILTER (
                        WHERE historical_license_link_resolved_flag
                    ) AS license_resolved_rows,
                    count(*) FILTER (
                        WHERE provider_master_v2_matched_flag
                    ) AS provider_v2_matched_rows,
                    count(*) FILTER (
                        WHERE provider_v2_md_do_eligible_flag
                    ) AS provider_v2_md_do_rows,
                    count(*) FILTER (
                        WHERE historical_race_concordance_eligible_t50_flag
                    ) AS race_t50_rows,
                    count(*) FILTER (
                        WHERE sex_gender_historical_eligible_flag
                    ) AS sex_gender_rows,
                    count(*) FILTER (
                        WHERE ami_icd9_principal_strict_flag
                    ) AS ami_principal_strict_rows,
                    count(*) FILTER (
                        WHERE ami_icd9_principal_broad_flag
                    ) AS ami_principal_broad_rows,
                    count(*) FILTER (
                        WHERE ami_icd9_anylisted_strict_flag = 1
                    ) AS ami_anylisted_strict_rows,
                    count(*) FILTER (
                        WHERE ami_icd9_anylisted_broad_flag = 1
                    ) AS ami_anylisted_broad_rows,
                    count(*) FILTER (
                        WHERE hourly_los_available_flag
                           OR ed_discharge_hour IS NOT NULL
                           OR los_hours_clock_raw IS NOT NULL
                           OR los_hours_primary_0_168 IS NOT NULL
                    ) AS hourly_los_errors,
                    count(*) FILTER (
                        WHERE physician_linkage_method =
                            'direct_validated_npi'
                    ) AS direct_npi_rows,
                    count(*) FILTER (
                        WHERE provider_v2_md_do_eligible_flag
                          AND (
                              physician_entity_category <> 'Individual'
                              OR physician_clinician_type <> 'MD/DO physician'
                              OR NOT physician_md_do_flag
                          )
                    ) AS invalid_md_do_rows
                FROM {derived}
                """
            ).fetchone()
            missing_from_output = con.execute(
                f"""
                SELECT count(*)
                FROM (
                    SELECT visit_key FROM {source}
                    EXCEPT
                    SELECT visit_key FROM {derived}
                )
                """
            ).fetchone()[0]
            extra_in_output = con.execute(
                f"""
                SELECT count(*)
                FROM (
                    SELECT visit_key FROM {derived}
                    EXCEPT
                    SELECT visit_key FROM {source}
                )
                """
            ).fetchone()[0]
            field_mismatches = con.execute(
                f"""
                SELECT count(*)
                FROM {source} AS f
                INNER JOIN {derived} AS h USING (visit_key)
                WHERE f.visit_year IS DISTINCT FROM h.visit_year
                   OR f.visit_quarter IS DISTINCT FROM h.visit_quarter
                   OR f.facility_ahca_id IS DISTINCT FROM h.facility_ahca_id
                   OR f.race_raw IS DISTINCT FROM
                        h.historical_race_ethnicity_code
                   OR f.sex_category IS DISTINCT FROM h.patient_sex_category
                   OR f.age_years IS DISTINCT FROM h.age_years
                   OR f.weekend_flag IS DISTINCT FROM h.weekend_flag
                   OR f.arrival_hour IS DISTINCT FROM h.arrival_hour
                   OR f.off_hours_flag IS DISTINCT FROM h.off_hours_flag
                   OR f.length_of_stay_days IS DISTINCT FROM
                        h.length_of_stay_days
                   OR f.payer_group IS DISTINCT FROM h.payer_group
                   OR f.disposition_group IS DISTINCT FROM h.disposition_group
                   OR f.routine_discharge_flag IS DISTINCT FROM
                        h.routine_discharge_flag
                   OR f.transfer_flag IS DISTINCT FROM h.transfer_flag
                   OR f.mortality_flag IS DISTINCT FROM h.mortality_flag
                   OR f.principal_diagnosis_code_norm IS DISTINCT FROM
                        h.principal_diagnosis_code_norm
                   OR f.procedure_count_analysis IS DISTINCT FROM
                        h.procedure_count_analysis
                   OR f.total_charge_reported IS DISTINCT FROM
                        h.total_charge_reported
                   OR f.component_charge_sum IS DISTINCT FROM
                        h.component_charge_sum
                   OR f.attending_selected_npi IS DISTINCT FROM
                        h.attending_selected_npi
                   OR f.attending_selection_method IS DISTINCT FROM
                        h.physician_linkage_method
                """
            ).fetchone()[0]

            comparisons = [
                int(observed[index]) == int(expected[index])
                for index in range(9)
            ]
            comparisons.extend(
                [
                    int(observed[9]) == int(expected_anylisted[0]),
                    int(observed[10]) == int(expected_anylisted[1]),
                ]
            )
            passed = bool(
                all(comparisons)
                and expected[0] == expected[1]
                and observed[0] == observed[1]
                and missing_from_output == 0
                and extra_in_output == 0
                and field_mismatches == 0
                and observed[11] == 0
                and observed[12] == 0
                and observed[13] == 0
                and fact_sha_live == phase1_success["fact_file_sha256"]
                and output_sha_live == output_success["sha256"]
                and output_success.get("build_spec_version")
                    == BUILD_SPEC_VERSION
                and output_success.get("provider_master_v2_sha256")
                    == provider_master_sha256
                and output_success.get("provider_race_proxy_v2_sha256")
                    == race_proxy_sha256
                and output_success.get("passed") is True
            )
            partition_rows.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "phase1_rows": int(expected[0]),
                    "historical_rows": int(observed[0]),
                    "phase1_distinct_keys": int(expected[1]),
                    "historical_distinct_keys": int(observed[1]),
                    "missing_from_output": int(missing_from_output),
                    "extra_in_output": int(extra_in_output),
                    "selected_field_mismatches": int(field_mismatches),
                    "expected_license_resolved_rows": int(expected[2]),
                    "observed_license_resolved_rows": int(observed[2]),
                    "expected_provider_v2_matched_rows": int(expected[3]),
                    "observed_provider_v2_matched_rows": int(observed[3]),
                    "expected_provider_v2_md_do_rows": int(expected[4]),
                    "observed_provider_v2_md_do_rows": int(observed[4]),
                    "expected_race_t50_rows": int(expected[5]),
                    "observed_race_t50_rows": int(observed[5]),
                    "expected_sex_gender_rows": int(expected[6]),
                    "observed_sex_gender_rows": int(observed[6]),
                    "expected_ami_principal_strict_rows": int(expected[7]),
                    "observed_ami_principal_strict_rows": int(observed[7]),
                    "expected_ami_principal_broad_rows": int(expected[8]),
                    "observed_ami_principal_broad_rows": int(observed[8]),
                    "expected_ami_anylisted_strict_rows": int(
                        expected_anylisted[0]
                    ),
                    "observed_ami_anylisted_strict_rows": int(observed[9]),
                    "expected_ami_anylisted_broad_rows": int(
                        expected_anylisted[1]
                    ),
                    "observed_ami_anylisted_broad_rows": int(observed[10]),
                    "hourly_los_errors": int(observed[11]),
                    "direct_npi_rows": int(observed[12]),
                    "invalid_md_do_rows": int(observed[13]),
                    "phase1_fact_checksum_match": (
                        fact_sha_live == phase1_success["fact_file_sha256"]
                    ),
                    "historical_file_checksum_match": (
                        output_sha_live == output_success["sha256"]
                    ),
                    "passed": passed,
                }
            )

    historical_glob = (
        historical_root
        / "visit_year=*"
        / "visit_quarter=*"
        / OUTPUT_FILE_NAME
    )
    source_all = (
        f"read_parquet('{qpath(historical_glob)}', "
        "hive_partitioning=false)"
    )
    coverage_by_year = con.execute(
        f"""
        SELECT
            visit_year,
            count(*) AS phase1_encounters,
            count(*) FILTER (
                WHERE historical_license_link_resolved_flag
            ) AS license_resolved_encounters,
            count(*) FILTER (
                WHERE provider_master_v2_matched_flag
            ) AS provider_v2_matched_encounters,
            count(*) FILTER (
                WHERE provider_v2_md_do_eligible_flag
            ) AS provider_v2_md_do_encounters,
            count(*) FILTER (
                WHERE historical_race_concordance_eligible_t50_flag
            ) AS race_t50_encounters,
            count(*) FILTER (
                WHERE sex_gender_historical_eligible_flag
            ) AS sex_gender_encounters,
            count(DISTINCT attending_selected_npi) FILTER (
                WHERE historical_license_link_resolved_flag
            ) AS license_resolved_unique_npi,
            count(DISTINCT attending_selected_npi) FILTER (
                WHERE provider_v2_md_do_eligible_flag
            ) AS provider_v2_md_do_unique_npi,
            count(DISTINCT attending_selected_npi) FILTER (
                WHERE historical_race_concordance_eligible_t50_flag
            ) AS race_t50_unique_npi,
            count(DISTINCT attending_selected_npi) FILTER (
                WHERE sex_gender_historical_eligible_flag
            ) AS sex_gender_unique_npi,
            100.0 * count(*) FILTER (
                WHERE historical_license_link_resolved_flag
            ) / count(*) AS license_resolved_visit_pct,
            100.0 * count(*) FILTER (
                WHERE provider_v2_md_do_eligible_flag
            ) / count(*) AS provider_v2_md_do_visit_pct,
            100.0 * count(*) FILTER (
                WHERE historical_race_concordance_eligible_t50_flag
            ) / count(*) AS race_t50_visit_pct,
            100.0 * count(*) FILTER (
                WHERE sex_gender_historical_eligible_flag
            ) / count(*) AS sex_gender_visit_pct
        FROM {source_all}
        GROUP BY visit_year
        ORDER BY visit_year
        """
    ).fetchdf()
    coverage_by_type = con.execute(
        f"""
        SELECT
            visit_year,
            coalesce(
                physician_clinician_type, '<UNRESOLVED_OR_UNMATCHED>'
            ) AS physician_clinician_type,
            coalesce(
                physician_entity_category, '<UNRESOLVED_OR_UNMATCHED>'
            ) AS physician_entity_category,
            count(*) AS encounters,
            count(DISTINCT attending_selected_npi) AS unique_npi
        FROM {source_all}
        GROUP BY visit_year, 2, 3
        ORDER BY visit_year, encounters DESC, 2, 3
        """
    ).fetchdf()
    selection_profile = con.execute(
        f"""
        SELECT
            visit_year,
            provider_v2_md_do_eligible_flag,
            coalesce(
                historical_patient_group, '<OTHER_OR_UNKNOWN>'
            ) AS historical_patient_group,
            patient_sex_category,
            count(*) AS encounters,
            avg(age_years) AS mean_age,
            avg(length_of_stay_days) AS mean_los_days,
            avg(total_charge_reported_real_2024)
                AS mean_charge_real_2024,
            avg(procedure_count_analysis)
                AS mean_procedure_count,
            avg(routine_discharge_flag::INTEGER)
                AS routine_discharge_rate,
            avg(transfer_flag::INTEGER) AS transfer_rate,
            avg(mortality_flag::INTEGER) AS mortality_rate
        FROM {source_all}
        GROUP BY visit_year, 2, 3, 4
        ORDER BY visit_year, 2, 3, 4
        """
    ).fetchdf()
    historical_schema = con.execute(
        f"DESCRIBE SELECT * FROM {source_all}"
    ).fetchdf()
    con.close()

    reconciliation_path = qa_dir / "historical_provider_v2_phase1_reconciliation.csv"
    write_csv(reconciliation_path, partition_rows)
    coverage_year_path = qa_dir / "historical_provider_v2_coverage_by_year.csv"
    coverage_type_path = (
        qa_dir / "historical_provider_v2_coverage_by_clinician_type.csv"
    )
    selection_path = qa_dir / "historical_provider_v2_linkage_selection_profile.csv"
    coverage_by_year.to_csv(coverage_year_path, index=False)
    coverage_by_type.to_csv(coverage_type_path, index=False)
    selection_profile.to_csv(selection_path, index=False)

    catalog = comparison_catalog()
    comparability_csv = documentation / "Historical_2005_2008_Comparability_Matrix.csv"
    comparability_json = documentation / "Historical_2005_2008_Comparability_Matrix.json"
    write_csv(comparability_csv, catalog)
    comparability_json.write_text(
        json.dumps(catalog, indent=2), encoding="utf-8"
    )
    outcome_fields = {
        "length_of_stay_days",
        "total_charge_reported",
        "total_charge_reported_real_2024",
        "total_charge",
        "total_charge_real_2024",
        "component_charge_sum",
        "component_charge_sum_real_2024",
        "procedure_count_analysis",
        "any_procedure_flag",
        "high_procedure_flag",
        "routine_discharge_flag",
        "transfer_flag",
        "hospice_flag",
        "mortality_flag",
        "left_discontinued_care_flag",
    }

    def variable_role(name: str) -> str:
        if name in outcome_fields:
            return "outcome"
        if name.startswith("ami_"):
            return "AMI cohort definition"
        if (
            "eligible" in name
            or name.endswith("_defined_flag")
            or name.endswith("_available_flag")
        ):
            return "eligibility/measurement flag"
        if (
            name.startswith("physician_")
            or name.startswith("attending_")
            or name.startswith("provider_")
        ):
            return "provider measurement"
        if name.startswith("elix_"):
            return "risk-adjustment covariate"
        if (
            name.startswith("patient_")
            or name in {
                "age_years",
                "age_band",
                "payer_group",
                "weekend_flag",
                "off_hours_flag",
                "arrival_hour",
                "arrival_time_band",
            }
        ):
            return "patient/visit covariate"
        return "identifier, source, or supporting analytic field"

    historical_schema["variable_role"] = historical_schema[
        "column_name"
    ].map(variable_role)
    historical_schema["historical_track"] = "2005-2008 separate provider-v2"
    historical_schema["hourly_los_policy"] = historical_schema[
        "column_name"
    ].map(
        lambda name: (
            "structurally unavailable; must remain null"
            if name
            in {
                "ed_discharge_hour",
                "los_hours_clock_raw",
                "los_hours_primary_0_168",
            }
            else ""
        )
    )
    historical_dictionary_path = (
        documentation / "Historical_Provider_V2_Variable_Dictionary.csv"
    )
    historical_schema.to_csv(historical_dictionary_path, index=False)

    all_partitions_pass = bool(
        len(partition_rows) == EXPECTED_PARTITIONS
        and all(bool(row["passed"]) for row in partition_rows)
    )
    source_total = sum(int(row["phase1_rows"]) for row in partition_rows)
    output_total = sum(int(row["historical_rows"]) for row in partition_rows)
    gate_pass = bool(
        build_manifest_valid
        and gender_checkpoint_valid
        and all_partitions_pass
        and source_total == output_total
    )
    gate = {
        "created_utc": now_utc(),
        "status": "PASS" if gate_pass else "FAIL",
        "gate_id": "historical_provider_v2_pre_estimation_gate_v1",
        "estimate_blind": True,
        "model_result_files_read": False,
        "historical_estimation_authorized": gate_pass,
        "build_manifest_valid": build_manifest_valid,
        "provider_gender_measurement_checkpoint_valid": (
            gender_checkpoint_valid
        ),
        "provider_gender_measurement_checkpoint": str(
            gender_checkpoint_path
        ),
        "provider_gender_measurement_checkpoint_sha256": sha256_file(
            gender_checkpoint_path
        ),
        "provider_master_v2_sha256": provider_master_sha256,
        "provider_race_proxy_v2_sha256": race_proxy_sha256,
        "expected_partitions": EXPECTED_PARTITIONS,
        "reconciled_partitions": len(partition_rows),
        "passed_partitions": sum(
            bool(row["passed"]) for row in partition_rows
        ),
        "phase1_rows": source_total,
        "historical_rows": output_total,
        "missing_phase1_keys": sum(
            int(row["missing_from_output"]) for row in partition_rows
        ),
        "extra_historical_keys": sum(
            int(row["extra_in_output"]) for row in partition_rows
        ),
        "selected_field_mismatches": sum(
            int(row["selected_field_mismatches"])
            for row in partition_rows
        ),
        "hourly_los_errors": sum(
            int(row["hourly_los_errors"]) for row in partition_rows
        ),
        "direct_npi_rows": sum(
            int(row["direct_npi_rows"]) for row in partition_rows
        ),
        "invalid_md_do_rows": sum(
            int(row["invalid_md_do_rows"]) for row in partition_rows
        ),
        "cohort_policy": (
            "All Phase 1 encounters retained with provider-v2 eligibility "
            "flags; 2005-2008 remains separate from 2010-2024."
        ),
        "hourly_los_policy": (
            "Structurally unavailable; hourly fields must be null; "
            "length_of_stay_days is not converted to hours."
        ),
        "provider_temporal_limitation": (
            "Current NPPES/CMS/Florida DOH attributes do not establish "
            "historical employment, affiliation, privilege, specialty, or "
            "gender identity at the encounter date."
        ),
        "race_measurement": (
            "Full-name Bayesian probability proxy without geography; not "
            "BISG and not self-identified race/ethnicity."
        ),
        "inverse_probability_weighting_decision": (
            "Not applied automatically. Concordance exposure is structurally "
            "unobserved when provider linkage or demographics are absent, so "
            "an observed-covariate linkage model cannot establish a "
            "missing-at-random identification assumption. Linked-versus-"
            "unlinked profiles are retained for selection assessment."
        ),
        "ipw_justified_as_primary_correction": False,
        "artifacts": {
            "partition_reconciliation": str(reconciliation_path),
            "coverage_by_year": str(coverage_year_path),
            "coverage_by_clinician_type": str(coverage_type_path),
            "linkage_selection_profile": str(selection_path),
            "comparability_csv": str(comparability_csv),
            "comparability_json": str(comparability_json),
            "historical_variable_dictionary": str(
                historical_dictionary_path
            ),
        },
        "source_release_modified": False,
    }
    gate_path = qa_dir / "historical_provider_v2_pre_estimation_gate.json"
    gate_path.write_text(json.dumps(gate, indent=2), encoding="utf-8")

    coverage_lines = coverage_by_year.to_markdown(index=False)
    comparability_lines = "\n".join(
        (
            f"| {item['domain']} | {item['variable_or_outcome']} | "
            f"{item['cross_period_status']} | {item['permitted_use']} | "
            f"{item['restriction']} |"
        )
        for item in catalog
    )
    document = f"""# Historical 2005-2008 provider-v2 checkpoint

Generated: {gate['created_utc']}

## Decision

**{gate['status']}**. Historical estimation authorized:
**{gate['historical_estimation_authorized']}**.

This checkpoint is estimate-blind. It did not read model-result files.
The 2005-2008 cohort remains a separate historical sensitivity and is never
silently pooled with the 2010-2024 primary cohort.

## Independent reconciliation

- Expected and reconciled partitions: {EXPECTED_PARTITIONS}
- Phase 1 encounter rows: {source_total:,}
- Historical provider-v2 rows: {output_total:,}
- Missing Phase 1 keys: {gate['missing_phase1_keys']:,}
- Extra historical keys: {gate['extra_historical_keys']:,}
- Selected source-field mismatches: {gate['selected_field_mismatches']:,}
- Non-null or asserted hourly-LOS errors: {gate['hourly_los_errors']:,}
- Direct-NPI rows in the historical era: {gate['direct_npi_rows']:,}
- Invalid organizational/non-MD/DO physician eligibility rows:
  {gate['invalid_md_do_rows']:,}

Every quarter is independently compared with the immutable Phase 1 fact file,
including exact row and encounter-key preservation, selected source fields,
license linkage, provider-v2 MD/DO eligibility, full-name race eligibility,
recorded patient sex-physician gender eligibility, and strict/broad AMI counts.
Checksums are recomputed for Phase 1 facts and historical outputs.

## Provider-v2 coverage by year

{coverage_lines}

The full pre-linkage encounter universe is retained. Analytic cohorts are
defined by flags, so linkage loss is visible and can be evaluated rather than
being introduced through an inner join.

## LOS policy

Historical `length_of_stay_days` is retained as a day-level measure.
`ed_discharge_hour`, `los_hours_clock_raw`, and
`los_hours_primary_0_168` are structurally unavailable and must remain null.
No day-to-hour conversion is permitted.

## Measurement limitations

- Historical physician linkage is a unique Florida-license-to-NPI crosswalk,
  not a direct source NPI.
- Provider master v2 uses current registry snapshots. They do not establish
  historical employment, hospital privilege, specialty, or activity.
- Physician race is an algorithm-inferred full-name probability proxy without
  residential geography. It is not BISG and not self-identified race.
- Patient race and ethnicity are historically combined. The code-3/code-4
  comparison is a separate sensitivity and is not measurement-equivalent to
  modern separate race and ethnicity fields.
- Recorded patient sex and physician gender categories are administrative
  measurement fields, not measures of gender identity.
- The Greenwood analysis is an ED-only extension, not an inpatient replication.
- Inverse-probability weighting is not treated as an automatic correction:
  physician concordance is structurally unobserved when linkage or physician
  demographics are absent, so observed linkage propensities alone cannot
  establish a missing-at-random identification assumption. The linked versus
  unlinked profiles are preserved for transparent selection assessment.

## Cross-period comparability matrix

| Domain | Variable/outcome | Status | Permitted use | Restriction |
|---|---|---|---|---|
{comparability_lines}

## Machine-readable evidence

- `qa/historical_provider_v2_pre_estimation_gate.json`
- `qa/historical_provider_v2_phase1_reconciliation.csv`
- `qa/historical_provider_v2_coverage_by_year.csv`
- `qa/historical_provider_v2_coverage_by_clinician_type.csv`
- `qa/historical_provider_v2_linkage_selection_profile.csv`
- `documentation/Historical_2005_2008_Comparability_Matrix.csv`
- `documentation/Historical_2005_2008_Comparability_Matrix.json`
- `documentation/Historical_Provider_V2_Variable_Dictionary.csv`
"""
    document_path = (
        documentation
        / "Historical_2005_2008_Comparability_and_Reconciliation.md"
    )
    document_path.write_text(document, encoding="utf-8")
    print(json.dumps(gate, indent=2))
    if not gate_pass:
        raise SystemExit(
            "Historical provider-v2 pre-estimation gate failed; "
            "historical models are blocked"
        )


if __name__ == "__main__":
    main()
