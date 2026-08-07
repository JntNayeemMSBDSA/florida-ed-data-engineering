# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_full_build_20260724/scripts/finalize_facility_summaries_qa.py
# Release and scratch roots are supplied by environment; no production data are bundled.

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


DATASET_ROOT = Path(os.environ.get("FL_ED_DATASET_ROOT", "private_data")).expanduser()
OUTPUT_ROOT = Path(
    os.environ.get(
        "FL_ED_PHASE1_OUTPUT",
        str(DATASET_ROOT / "outputs" / "florida_ed_full_build_20260724"),
    )
).expanduser()
TMP_ROOT = Path(
    os.environ.get(
        "FL_ED_PHASE1_SCRATCH",
        str(DATASET_ROOT / "tmp" / "florida_ed_full_build_20260724"),
    )
).expanduser()
PYDEPS = Path(
    os.environ.get(
        "FL_ED_PYDEPS",
        str(DATASET_ROOT / "tmp" / "florida_ed_standardization_20260724" / "pydeps"),
    )
).expanduser()
if PYDEPS.exists():
    sys.path.insert(0, str(PYDEPS))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402


IN_SCOPE_YEARS = list(range(2005, 2009)) + list(range(2010, 2025))
EXPECTED_QUARTERS = [
    (year, quarter)
    for year in IN_SCOPE_YEARS
    for quarter in range(1, 5)
]


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def copy_query(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    connection.execute(
        f"""
        COPY ({query})
        TO '{sql_path(partial)}'
        (
            FORMAT PARQUET,
            COMPRESSION ZSTD,
            ROW_GROUP_SIZE 250000
        )
        """
    )
    partial.replace(destination)


def require_complete_partitions() -> list[dict[str, object]]:
    manifests = []
    missing = []
    for year, quarter in EXPECTED_QUARTERS:
        path = (
            OUTPUT_ROOT
            / "fact_ed_visits"
            / f"visit_year={year}"
            / f"visit_quarter={quarter}"
            / "_SUCCESS.json"
        )
        if not path.exists():
            missing.append(f"{year}Q{quarter}")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload.get("reconciliation_passed"):
            raise RuntimeError(
                f"Partition reconciliation failed: {year} Q{quarter}"
            )
        manifests.append(payload)
    if missing:
        raise RuntimeError(
            "Cannot finalize; incomplete partitions: " + ", ".join(missing)
        )
    return manifests


def create_views(connection: duckdb.DuckDBPyConnection) -> None:
    fact_glob = (
        OUTPUT_ROOT
        / "fact_ed_visits"
        / "visit_year=*"
        / "visit_quarter=*"
        / "ed_visits.parquet"
    )
    diagnosis_glob = (
        OUTPUT_ROOT
        / "bridges"
        / "visit_diagnosis"
        / "visit_year=*"
        / "visit_quarter=*"
        / "visit_diagnosis.parquet"
    )
    procedure_glob = (
        OUTPUT_ROOT
        / "bridges"
        / "visit_procedure"
        / "visit_year=*"
        / "visit_quarter=*"
        / "visit_procedure.parquet"
    )
    references = {
        "fact": fact_glob,
        "diagnosis": diagnosis_glob,
        "procedure": procedure_glob,
        "cms_hospital": OUTPUT_ROOT
        / "dimensions"
        / "cms_hospital_current_reference.parquet",
        "zip_ruca": OUTPUT_ROOT
        / "decoders"
        / "zip_ruca_2020_reference.parquet",
    }
    for view, path in references.items():
        connection.execute(
            f"""
            CREATE OR REPLACE VIEW {view} AS
            SELECT *
            FROM read_parquet(
                '{sql_path(path)}',
                HIVE_PARTITIONING = FALSE,
                UNION_BY_NAME = TRUE
            )
            """
        )


def build_facility_outputs(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE facility_quarter AS
        SELECT
            visit_year,
            visit_quarter,
            facility_ahca_id,
            MODE(facility_name_reported)
                AS facility_name_quarter,
            MODE(facility_medicare_number_raw)
                AS facility_medicare_number_quarter,
            MODE(facility_program_code_raw)
                AS facility_program_code_quarter,
            MODE(facility_region_code_raw)
                AS facility_region_code_quarter,
            MODE(facility_county_code_raw)
                AS facility_county_code_quarter,
            MODE(facility_county_name)
                AS facility_county_name_quarter,
            MODE(facility_county_fips)
                AS facility_county_fips_quarter,
            COUNT(*) AS ed_visit_count,
            COUNT(DISTINCT attending_selected_npi)
                AS distinct_attending_npi_count,
            COUNT(*) FILTER (
                WHERE attending_selected_npi IS NOT NULL
            ) AS visits_with_resolved_attending_npi,
            COUNT(*) FILTER (
                WHERE attending_ed_specialist_flag
            ) AS visits_with_ed_specialist_attending,
            AVG(
                attending_ed_specialist_flag::INTEGER
            ) FILTER (
                WHERE attending_ed_specialist_flag IS NOT NULL
            ) AS ed_specialist_share_linked_attending_visits,
            AVG(attending_years_since_medical_school)
                AS mean_attending_experience_years,
            BOOL_OR(off_site_ed_flag)
                AS any_off_site_ed_visit_flag,
            COUNT(*) FILTER (
                WHERE off_site_ed_flag
            ) AS off_site_ed_visit_count,
            AVG(total_charge) AS mean_total_charge,
            MEDIAN(total_charge) AS median_total_charge,
            QUANTILE_CONT(total_charge, 0.90)
                AS p90_total_charge,
            SUM(total_charge) AS sum_total_charge,
            COUNT(*) FILTER (
                WHERE charge_reconciliation_exception_flag
            ) AS charge_reconciliation_exception_count,
            MODE(principal_clinical_category)
                AS modal_principal_clinical_category,
            MODE(principal_clinical_category_label)
                AS modal_principal_clinical_category_label
        FROM fact
        WHERE facility_ahca_id IS NOT NULL
        GROUP BY
            visit_year,
            visit_quarter,
            facility_ahca_id
        """
    )
    copy_query(
        connection,
        "SELECT * FROM facility_quarter",
        OUTPUT_ROOT
        / "dimensions"
        / "facility_quarter_history.parquet",
    )
    copy_query(
        connection,
        """
        SELECT
            visit_year,
            facility_ahca_id,
            MODE(facility_name_reported)
                AS facility_name_year,
            MODE(facility_medicare_number_raw)
                AS facility_medicare_number_year,
            MODE(facility_county_name)
                AS facility_county_name_year,
            MODE(facility_county_fips)
                AS facility_county_fips_year,
            COUNT(*) AS ed_visit_count,
            COUNT(DISTINCT attending_selected_npi)
                AS distinct_attending_npi_count,
            AVG(
                attending_ed_specialist_flag::INTEGER
            ) FILTER (
                WHERE attending_ed_specialist_flag IS NOT NULL
            ) AS ed_specialist_share_linked_attending_visits,
            BOOL_OR(off_site_ed_flag)
                AS any_off_site_ed_visit_flag,
            AVG(total_charge) AS mean_total_charge,
            MEDIAN(total_charge) AS median_total_charge,
            QUANTILE_CONT(total_charge, 0.90)
                AS p90_total_charge
        FROM fact
        WHERE facility_ahca_id IS NOT NULL
        GROUP BY visit_year, facility_ahca_id
        """,
        OUTPUT_ROOT
        / "dimensions"
        / "facility_year_history.parquet",
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE facility_category AS
        SELECT
            facility_ahca_id,
            principal_clinical_category,
            ANY_VALUE(principal_clinical_category_label)
                AS principal_clinical_category_label,
            COUNT(*) AS category_visit_count
        FROM fact
        WHERE
            facility_ahca_id IS NOT NULL
            AND principal_clinical_category IS NOT NULL
        GROUP BY
            facility_ahca_id,
            principal_clinical_category
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE facility_category_top AS
        WITH ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY facility_ahca_id
                    ORDER BY
                        category_visit_count DESC,
                        principal_clinical_category
                ) AS category_rank,
                SUM(category_visit_count) OVER (
                    PARTITION BY facility_ahca_id
                ) AS mapped_category_visit_count
            FROM facility_category
        )
        SELECT
            facility_ahca_id,
            MAX(principal_clinical_category) FILTER (
                WHERE category_rank = 1
            ) AS top_principal_clinical_category,
            MAX(principal_clinical_category_label) FILTER (
                WHERE category_rank = 1
            ) AS top_principal_clinical_category_label,
            MAX(category_visit_count) FILTER (
                WHERE category_rank = 1
            ) AS top_principal_clinical_category_visit_count,
            MAX(category_visit_count) FILTER (
                WHERE category_rank = 1
            )::DOUBLE / NULLIF(
                MAX(mapped_category_visit_count), 0
            ) AS top_principal_clinical_category_share,
            MAX(principal_clinical_category) FILTER (
                WHERE category_rank = 2
            ) AS second_principal_clinical_category,
            MAX(principal_clinical_category_label) FILTER (
                WHERE category_rank = 2
            ) AS second_principal_clinical_category_label,
            MAX(category_visit_count) FILTER (
                WHERE category_rank = 2
            )::DOUBLE / NULLIF(
                MAX(mapped_category_visit_count), 0
            ) AS second_principal_clinical_category_share,
            MAX(principal_clinical_category) FILTER (
                WHERE category_rank = 3
            ) AS third_principal_clinical_category,
            MAX(principal_clinical_category_label) FILTER (
                WHERE category_rank = 3
            ) AS third_principal_clinical_category_label,
            MAX(category_visit_count) FILTER (
                WHERE category_rank = 3
            )::DOUBLE / NULLIF(
                MAX(mapped_category_visit_count), 0
            ) AS third_principal_clinical_category_share
        FROM ranked
        GROUP BY facility_ahca_id
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE facility_core AS
        SELECT
            facility_ahca_id,
            ARG_MAX(
                facility_name_reported,
                visit_year * 10 + visit_quarter
            ) AS facility_name_latest_observed,
            STRING_AGG(
                DISTINCT facility_name_reported,
                ' | '
                ORDER BY facility_name_reported
            ) AS facility_historical_names,
            ARG_MAX(
                facility_medicare_number_raw,
                visit_year * 10 + visit_quarter
            ) AS facility_medicare_number_latest_observed,
            STRING_AGG(
                DISTINCT facility_medicare_number_raw,
                ' | '
                ORDER BY facility_medicare_number_raw
            ) AS facility_medicare_numbers_observed,
            MODE(facility_program_code_raw)
                AS facility_program_code_mode,
            MODE(facility_region_code_raw)
                AS facility_region_code_mode,
            MODE(facility_county_code_raw)
                AS facility_county_code_mode,
            ARG_MAX(
                facility_county_name,
                visit_year * 10 + visit_quarter
            ) AS facility_county_name_latest_observed,
            ARG_MAX(
                facility_county_fips,
                visit_year * 10 + visit_quarter
            ) AS facility_county_fips_latest_observed,
            MIN(visit_year * 10 + visit_quarter)
                AS first_observed_period_numeric,
            MAX(visit_year * 10 + visit_quarter)
                AS last_observed_period_numeric,
            CAST(MIN(visit_year) AS VARCHAR) || 'Q' ||
                CAST(
                    ARG_MIN(visit_quarter, visit_year * 10 + visit_quarter)
                    AS VARCHAR
                ) AS first_observed_quarter,
            CAST(MAX(visit_year) AS VARCHAR) || 'Q' ||
                CAST(
                    ARG_MAX(visit_quarter, visit_year * 10 + visit_quarter)
                    AS VARCHAR
                ) AS last_observed_quarter,
            COUNT(*) AS total_ed_visits,
            COUNT(DISTINCT attending_selected_npi)
                AS distinct_attending_npi_count,
            COUNT(*) FILTER (
                WHERE attending_selected_npi IS NOT NULL
            ) AS visits_with_resolved_attending_npi,
            COUNT(*) FILTER (
                WHERE attending_ed_specialist_flag
            ) AS visits_with_ed_specialist_attending,
            AVG(
                attending_ed_specialist_flag::INTEGER
            ) FILTER (
                WHERE attending_ed_specialist_flag IS NOT NULL
            ) AS ed_specialist_share_linked_attending_visits,
            AVG(attending_years_since_medical_school)
                AS mean_attending_experience_years,
            BOOL_OR(off_site_ed_flag) AS any_off_site_ed_flag,
            MIN(visit_year * 10 + visit_quarter) FILTER (
                WHERE off_site_ed_flag
            ) AS first_off_site_ed_period_numeric,
            MAX(visit_year * 10 + visit_quarter) FILTER (
                WHERE off_site_ed_flag
            ) AS last_off_site_ed_period_numeric,
            COUNT(*) FILTER (
                WHERE off_site_ed_flag
            ) AS off_site_ed_visit_count,
            AVG(total_charge) AS mean_total_charge,
            MEDIAN(total_charge) AS median_total_charge,
            QUANTILE_CONT(total_charge, 0.90)
                AS p90_total_charge,
            SUM(total_charge) AS sum_total_charge,
            AVG(
                charge_reconciliation_exception_flag::INTEGER
            ) FILTER (
                WHERE charge_reconciliation_exception_flag
                    IS NOT NULL
            ) AS charge_reconciliation_exception_share
        FROM fact
        WHERE facility_ahca_id IS NOT NULL
        GROUP BY facility_ahca_id
        """
    )
    copy_query(
        connection,
        """
        WITH cms AS (
            SELECT
                *,
                REGEXP_REPLACE(
                    facility_medicare_id, '[^0-9]', '', 'g'
                ) AS cms_medicare_norm
            FROM cms_hospital
        ),
        ruca_unique AS (
            SELECT
                zip5,
                MAX(primaryruca) AS primaryruca,
                MAX(secondaryruca) AS secondaryruca
            FROM zip_ruca
            GROUP BY zip5
        )
        SELECT
            f.facility_ahca_id,
            f.facility_name_latest_observed,
            f.facility_historical_names,
            f.facility_medicare_number_latest_observed,
            f.facility_medicare_numbers_observed,
            f.facility_program_code_mode,
            f.facility_region_code_mode,
            f.facility_county_code_mode,
            f.facility_county_name_latest_observed,
            f.facility_county_fips_latest_observed,
            f.first_observed_quarter,
            f.last_observed_quarter,
            f.total_ed_visits,
            f.distinct_attending_npi_count,
            f.visits_with_resolved_attending_npi,
            f.visits_with_ed_specialist_attending,
            f.ed_specialist_share_linked_attending_visits,
            f.mean_attending_experience_years,
            f.any_off_site_ed_flag,
            CASE
                WHEN f.first_off_site_ed_period_numeric IS NULL
                    THEN NULL
                ELSE
                    CAST(
                        FLOOR(f.first_off_site_ed_period_numeric / 10)
                        AS VARCHAR
                    ) || 'Q' ||
                    CAST(
                        f.first_off_site_ed_period_numeric % 10
                        AS VARCHAR
                    )
            END AS first_off_site_ed_quarter,
            CASE
                WHEN f.last_off_site_ed_period_numeric IS NULL
                    THEN NULL
                ELSE
                    CAST(
                        FLOOR(f.last_off_site_ed_period_numeric / 10)
                        AS VARCHAR
                    ) || 'Q' ||
                    CAST(
                        f.last_off_site_ed_period_numeric % 10
                        AS VARCHAR
                    )
            END AS last_off_site_ed_quarter,
            f.off_site_ed_visit_count,
            f.mean_total_charge,
            f.median_total_charge,
            f.p90_total_charge,
            f.sum_total_charge,
            f.charge_reconciliation_exception_share,
            t.top_principal_clinical_category,
            t.top_principal_clinical_category_label,
            t.top_principal_clinical_category_visit_count,
            t.top_principal_clinical_category_share,
            t.second_principal_clinical_category,
            t.second_principal_clinical_category_label,
            t.second_principal_clinical_category_share,
            t.third_principal_clinical_category,
            t.third_principal_clinical_category_label,
            t.third_principal_clinical_category_share,
            c.facility_medicare_id AS cms_facility_medicare_id,
            c.cms_facility_name,
            c.cms_address,
            c.cms_city,
            c.cms_state,
            c.cms_zip_code,
            c.cms_county_name,
            c.cms_hospital_type,
            c.cms_hospital_ownership,
            c.cms_emergency_services,
            c.cms_zip_county_fips,
            TRY_CAST(
                c.cms_zip_centroid_latitude AS DOUBLE
            ) AS facility_zip_centroid_latitude,
            TRY_CAST(
                c.cms_zip_centroid_longitude AS DOUBLE
            ) AS facility_zip_centroid_longitude,
            c.geocode_method,
            r.primaryruca AS facility_ruca_primary,
            r.secondaryruca AS facility_ruca_secondary,
            CASE
                WHEN TRY_CAST(r.primaryruca AS DOUBLE)
                    BETWEEN 1 AND 3 THEN 'Metropolitan'
                WHEN TRY_CAST(r.primaryruca AS DOUBLE)
                    BETWEEN 4 AND 6 THEN 'Micropolitan'
                WHEN TRY_CAST(r.primaryruca AS DOUBLE)
                    BETWEEN 7 AND 10 THEN 'Small town/rural'
                ELSE NULL
            END AS facility_rurality_3level,
            'CMS current hospital address joined by latest '
                || 'observed Medicare provider number; coordinates '
                || 'are ZIP centroids, not rooftop geocodes'
                AS current_address_linkage_note,
            '2020 RUCA ZIP approximation; primary RUCA 1-3 '
                || 'metropolitan, 4-6 micropolitan, 7-10 '
                || 'small town/rural'
                AS facility_ruca_version_rule
        FROM facility_core f
        LEFT JOIN facility_category_top t USING (facility_ahca_id)
        LEFT JOIN cms c
            ON LPAD(
                REGEXP_REPLACE(
                    f.facility_medicare_number_latest_observed,
                    '[^0-9]',
                    '',
                    'g'
                ),
                6,
                '0'
            ) = LPAD(c.cms_medicare_norm, 6, '0')
        LEFT JOIN ruca_unique r
            ON c.cms_zip5 = r.zip5
        """,
        OUTPUT_ROOT / "dimensions" / "facility_master.parquet",
    )


def build_summary_outputs(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    summary_dir = OUTPUT_ROOT / "summaries"
    summary_dir.mkdir(parents=True, exist_ok=True)
    queries = {
        "annual_visit_summary": """
            SELECT
                visit_year,
                COUNT(*) AS ed_visit_count,
                COUNT(DISTINCT facility_ahca_id)
                    AS facility_count,
                COUNT(DISTINCT attending_selected_npi)
                    AS distinct_attending_npi_count,
                AVG(
                    (attending_selected_npi IS NOT NULL)::INTEGER
                ) AS attending_npi_resolved_share,
                AVG(
                    attending_physician_master_matched_flag::INTEGER
                ) AS attending_physician_master_match_share,
                AVG(
                    attending_ed_specialist_flag::INTEGER
                ) FILTER (
                    WHERE attending_ed_specialist_flag IS NOT NULL
                ) AS ed_specialist_share_linked_attending_visits,
                AVG(attending_years_since_medical_school)
                    AS mean_attending_experience_years,
                AVG(pediatric_flag::INTEGER) FILTER (
                    WHERE pediatric_flag IS NOT NULL
                ) AS pediatric_visit_share,
                AVG(transfer_flag::INTEGER)
                    AS transfer_visit_share,
                AVG(mortality_flag::INTEGER)
                    AS mortality_visit_share,
                AVG(any_procedure_flag::INTEGER)
                    AS any_procedure_visit_share,
                AVG(em_acuity_proxy_level)
                    AS mean_em_acuity_proxy_level,
                AVG(total_charge) AS mean_total_charge,
                MEDIAN(total_charge) AS median_total_charge,
                QUANTILE_CONT(total_charge, 0.90)
                    AS p90_total_charge,
                AVG(
                    charge_reconciliation_exception_flag::INTEGER
                ) FILTER (
                    WHERE charge_reconciliation_exception_flag
                        IS NOT NULL
                ) AS charge_reconciliation_exception_share
            FROM fact
            GROUP BY visit_year
            ORDER BY visit_year
        """,
        "annual_payer_summary": """
            SELECT
                visit_year,
                payer_group,
                COUNT(*) AS ed_visit_count,
                COUNT(*)::DOUBLE
                    / SUM(COUNT(*)) OVER (PARTITION BY visit_year)
                    AS annual_visit_share
            FROM fact
            GROUP BY visit_year, payer_group
            ORDER BY visit_year, ed_visit_count DESC
        """,
        "annual_disposition_summary": """
            SELECT
                visit_year,
                disposition_group,
                COUNT(*) AS ed_visit_count,
                COUNT(*)::DOUBLE
                    / SUM(COUNT(*)) OVER (PARTITION BY visit_year)
                    AS annual_visit_share
            FROM fact
            GROUP BY visit_year, disposition_group
            ORDER BY visit_year, ed_visit_count DESC
        """,
        "annual_physician_composition": """
            SELECT
                visit_year,
                attending_gender_category,
                attending_surname_imputed_race_ethnicity,
                attending_taxonomy_display_name,
                attending_ed_specialist_flag,
                COUNT(*) AS visit_count,
                COUNT(DISTINCT attending_selected_npi)
                    AS distinct_attending_npi_count
            FROM fact
            WHERE attending_selected_npi IS NOT NULL
            GROUP BY
                visit_year,
                attending_gender_category,
                attending_surname_imputed_race_ethnicity,
                attending_taxonomy_display_name,
                attending_ed_specialist_flag
            ORDER BY visit_year, visit_count DESC
        """,
        "annual_major_clinical_categories": """
            WITH counts AS (
                SELECT
                    visit_year,
                    principal_clinical_category,
                    ANY_VALUE(principal_clinical_category_label)
                        AS principal_clinical_category_label,
                    COUNT(*) AS visit_count
                FROM fact
                WHERE principal_clinical_category IS NOT NULL
                GROUP BY
                    visit_year,
                    principal_clinical_category
            ),
            ranked AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY visit_year
                        ORDER BY
                            visit_count DESC,
                            principal_clinical_category
                    ) AS annual_rank,
                    visit_count::DOUBLE
                        / SUM(visit_count) OVER (
                            PARTITION BY visit_year
                        ) AS mapped_visit_share
                FROM counts
            )
            SELECT *
            FROM ranked
            WHERE annual_rank <= 25
            ORDER BY visit_year, annual_rank
        """,
        "annual_major_procedure_groups": """
            WITH counts AS (
                SELECT
                    visit_year,
                    procedure_code_system,
                    procedure_group,
                    ANY_VALUE(procedure_group_label)
                        AS procedure_group_label,
                    COUNT(*) AS procedure_occurrence_count,
                    COUNT(DISTINCT visit_key)
                        AS visit_count
                FROM procedure
                WHERE procedure_group IS NOT NULL
                GROUP BY
                    visit_year,
                    procedure_code_system,
                    procedure_group
            ),
            ranked AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            visit_year,
                            procedure_code_system
                        ORDER BY
                            procedure_occurrence_count DESC,
                            procedure_group
                    ) AS annual_system_rank
                FROM counts
            )
            SELECT *
            FROM ranked
            WHERE annual_system_rank <= 25
            ORDER BY
                visit_year,
                procedure_code_system,
                annual_system_rank
        """,
        "annual_facility_composition": """
            SELECT
                visit_year,
                facility_program_label,
                facility_rurality_3level,
                COUNT(DISTINCT facility_ahca_id)
                    AS facility_count,
                COUNT(*) AS ed_visit_count
            FROM fact f
            LEFT JOIN read_parquet(
                'FACILITY_MASTER_PLACEHOLDER'
            ) m USING (facility_ahca_id)
            GROUP BY
                visit_year,
                facility_program_label,
                facility_rurality_3level
            ORDER BY visit_year, ed_visit_count DESC
        """.replace(
            "FACILITY_MASTER_PLACEHOLDER",
            sql_path(
                OUTPUT_ROOT / "dimensions" / "facility_master.parquet"
            ),
        ),
    }
    for name, query in queries.items():
        parquet_path = summary_dir / f"{name}.parquet"
        copy_query(connection, query, parquet_path)
        frame = pd.read_parquet(parquet_path)
        frame.to_csv(summary_dir / f"{name}.csv", index=False)


def build_qa_outputs(
    connection: duckdb.DuckDBPyConnection,
    manifests: list[dict[str, object]],
) -> None:
    qa_dir = OUTPUT_ROOT / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    manifest_frame = pd.json_normalize(manifests)
    manifest_frame.to_parquet(
        qa_dir / "quarterly_build_reconciliation.parquet",
        index=False,
    )
    manifest_frame.to_csv(
        qa_dir / "quarterly_build_reconciliation.csv",
        index=False,
    )
    qa_queries = {
        "annual_missingness": """
            SELECT
                visit_year,
                COUNT(*) AS visit_count,
                AVG((sex_category IN ('Missing','Unmapped'))::INTEGER)
                    AS sex_missing_unmapped_share,
                AVG((race_category IN ('Missing','Unmapped'))::INTEGER)
                    AS race_missing_unmapped_share,
                AVG(
                    (
                        ethnicity_category IN ('Missing','Unmapped')
                        OR ethnicity_category =
                            'Not separately reported/not derivable'
                    )::INTEGER
                ) AS ethnicity_unavailable_missing_share,
                AVG((age_years IS NULL)::INTEGER)
                    AS exact_age_unavailable_share,
                AVG((patient_zip5 IS NULL)::INTEGER)
                    AS patient_zip_missing_invalid_share,
                AVG(
                    (patient_zip_rurality_3level IS NULL)::INTEGER
                ) AS patient_ruca_unavailable_share,
                AVG(
                    (
                        disposition_group IN (
                            'Missing',
                            'Unmapped/legacy'
                        )
                    )::INTEGER
                ) AS disposition_missing_unmapped_share,
                AVG(
                    (
                        payer_group IN ('Missing', 'Unmapped')
                    )::INTEGER
                ) AS payer_missing_unmapped_share,
                AVG((principal_diagnosis_code_norm IS NULL)::INTEGER)
                    AS principal_diagnosis_missing_share,
                AVG(
                    (principal_diagnosis_mapped_flag IS DISTINCT FROM TRUE)
                    ::INTEGER
                ) AS principal_diagnosis_unmapped_share,
                AVG((attending_selected_npi IS NULL)::INTEGER)
                    AS attending_npi_unresolved_share,
                AVG(
                    (
                        attending_physician_master_matched_flag
                        IS DISTINCT FROM TRUE
                    )::INTEGER
                ) AS attending_master_unmatched_share,
                AVG((total_charge IS NULL)::INTEGER)
                    AS total_charge_missing_share,
                AVG(
                    (em_acuity_proxy_level IS NULL)::INTEGER
                ) AS em_acuity_proxy_unavailable_share,
                AVG(
                    (
                        charge_reconciliation_exception_flag
                        IS NULL
                    )::INTEGER
                ) AS charge_reconciliation_not_assessable_share
            FROM fact
            GROUP BY visit_year
            ORDER BY visit_year
        """,
        "diagnosis_mapping_coverage": """
            SELECT
                visit_year,
                diagnosis_code_system,
                diagnosis_role,
                COUNT(*) AS diagnosis_occurrence_count,
                COUNT(*) FILTER (
                    WHERE code_description_mapped_flag
                ) AS mapped_occurrence_count,
                AVG(code_description_mapped_flag::INTEGER)
                    AS mapped_occurrence_share,
                COUNT(DISTINCT diagnosis_code_norm)
                    AS distinct_codes,
                COUNT(DISTINCT diagnosis_code_norm) FILTER (
                    WHERE NOT code_description_mapped_flag
                ) AS distinct_unmapped_codes
            FROM diagnosis
            GROUP BY
                visit_year,
                diagnosis_code_system,
                diagnosis_role
            ORDER BY
                visit_year,
                diagnosis_code_system,
                diagnosis_role
        """,
        "procedure_mapping_coverage": """
            SELECT
                visit_year,
                procedure_code_system,
                procedure_role,
                COUNT(*) AS procedure_occurrence_count,
                AVG(code_description_mapped_flag::INTEGER)
                    AS description_mapped_occurrence_share,
                AVG(group_mapped_flag::INTEGER)
                    AS group_mapped_occurrence_share,
                COUNT(DISTINCT procedure_code_norm)
                    AS distinct_codes,
                COUNT(DISTINCT procedure_code_norm) FILTER (
                    WHERE NOT code_description_mapped_flag
                ) AS distinct_description_unmapped_codes,
                COUNT(DISTINCT procedure_code_norm) FILTER (
                    WHERE NOT group_mapped_flag
                ) AS distinct_group_unmapped_codes
            FROM procedure
            GROUP BY
                visit_year,
                procedure_code_system,
                procedure_role
            ORDER BY
                visit_year,
                procedure_code_system,
                procedure_role
        """,
        "physician_linkage_by_year_role": """
            SELECT
                visit_year,
                role,
                selection_method,
                physician_link_status,
                COUNT(*) AS visit_role_count
            FROM (
                SELECT
                    visit_year,
                    'attending' AS role,
                    attending_selection_method
                        AS selection_method,
                    attending_physician_link_status
                        AS physician_link_status
                FROM fact
                UNION ALL
                SELECT
                    visit_year,
                    'operating_performing' AS role,
                    operating_performing_selection_method,
                    operating_performing_physician_link_status
                FROM fact
                UNION ALL
                SELECT
                    visit_year,
                    'other_practitioner' AS role,
                    other_practitioner_selection_method,
                    other_practitioner_physician_link_status
                FROM fact
            )
            GROUP BY
                visit_year,
                role,
                selection_method,
                physician_link_status
            ORDER BY
                visit_year,
                role,
                visit_role_count DESC
        """,
        "facility_name_many_to_many_check": """
            SELECT
                facility_ahca_id,
                COUNT(DISTINCT facility_name_reported)
                    AS distinct_reported_name_count,
                STRING_AGG(
                    DISTINCT facility_name_reported,
                    ' | '
                    ORDER BY facility_name_reported
                ) AS reported_names,
                COUNT(DISTINCT facility_medicare_number_raw)
                    AS distinct_medicare_number_count,
                STRING_AGG(
                    DISTINCT facility_medicare_number_raw,
                    ' | '
                    ORDER BY facility_medicare_number_raw
                ) AS medicare_numbers
            FROM fact
            WHERE facility_ahca_id IS NOT NULL
            GROUP BY facility_ahca_id
            HAVING
                COUNT(DISTINCT facility_name_reported) > 1
                OR COUNT(
                    DISTINCT facility_medicare_number_raw
                ) > 1
            ORDER BY
                distinct_reported_name_count DESC,
                facility_ahca_id
        """,
        "charge_reconciliation_by_year": """
            SELECT
                visit_year,
                COUNT(*) AS visit_count,
                COUNT(*) FILTER (
                    WHERE charge_reconciliation_exception_flag
                ) AS exception_count,
                AVG(
                    charge_reconciliation_exception_flag::INTEGER
                ) FILTER (
                    WHERE charge_reconciliation_exception_flag
                        IS NOT NULL
                ) AS exception_share_assessable,
                MEDIAN(
                    ABS(charge_reconciliation_difference)
                ) AS median_absolute_difference,
                QUANTILE_CONT(
                    ABS(charge_reconciliation_difference), 0.95
                ) AS p95_absolute_difference
            FROM fact
            GROUP BY visit_year
            ORDER BY visit_year
        """,
        "physician_master_attribute_coverage": """
            SELECT
                COUNT(*) AS physician_master_rows,
                COUNT(DISTINCT npi) AS distinct_npi_count,
                AVG(
                    (gender_category <> 'Unknown')::INTEGER
                ) AS gender_available_share,
                AVG(
                    (
                        surname_imputed_race_ethnicity
                            <> 'Unknown'
                    )::INTEGER
                ) AS surname_race_ethnicity_imputed_share,
                AVG(
                    (medical_school_grad_year IS NOT NULL)::INTEGER
                ) AS medical_school_grad_year_available_share,
                AVG(
                    (taxonomy_display_name IS NOT NULL)::INTEGER
                ) AS taxonomy_display_available_share,
                AVG(
                    (cms_primary_specialty IS NOT NULL)::INTEGER
                ) AS cms_primary_specialty_available_share,
                AVG(ed_specialist_flag::INTEGER)
                    AS ed_specialist_share_master,
                AVG(physician_md_do_flag::INTEGER)
                    AS md_do_share_master,
                AVG(
                    has_fl_doh_hospital_privilege::INTEGER
                ) AS fl_doh_hospital_privilege_share,
                AVG(
                    has_cms_group_practice_affiliation::INTEGER
                ) AS cms_group_affiliation_share,
                AVG(has_fl_license::INTEGER)
                    AS florida_license_share,
                AVG(is_cms_clinician::INTEGER)
                    AS cms_clinician_share
            FROM read_parquet(
                'PHYSICIAN_MASTER_PLACEHOLDER'
            )
        """.replace(
            "PHYSICIAN_MASTER_PLACEHOLDER",
            sql_path(
                OUTPUT_ROOT
                / "dimensions"
                / "physician_master.parquet"
            ),
        ),
        "facility_master_attribute_coverage": """
            SELECT
                COUNT(*) AS facility_master_rows,
                COUNT(DISTINCT facility_ahca_id)
                    AS distinct_facility_ahca_ids,
                AVG(
                    (
                        facility_name_latest_observed
                            IS NOT NULL
                    )::INTEGER
                ) AS observed_name_available_share,
                AVG(
                    (
                        facility_medicare_number_latest_observed
                            IS NOT NULL
                    )::INTEGER
                ) AS observed_medicare_number_available_share,
                AVG(
                    (
                        cms_facility_medicare_id
                            IS NOT NULL
                    )::INTEGER
                ) AS current_cms_hospital_match_share,
                AVG(
                    (
                        facility_county_fips_latest_observed
                            IS NOT NULL
                    )::INTEGER
                ) AS county_fips_available_share,
                AVG(
                    (
                        facility_rurality_3level
                            IS NOT NULL
                    )::INTEGER
                ) AS ruca_rurality_available_share,
                AVG(any_off_site_ed_flag::INTEGER)
                    AS ever_observed_off_site_ed_share,
                AVG(
                    (
                        ed_specialist_share_linked_attending_visits
                            IS NOT NULL
                    )::INTEGER
                ) AS physician_composition_available_share,
                AVG(
                    (
                        top_principal_clinical_category
                            IS NOT NULL
                    )::INTEGER
                ) AS top_clinical_category_available_share
            FROM read_parquet(
                'FACILITY_MASTER_PLACEHOLDER'
            )
        """.replace(
            "FACILITY_MASTER_PLACEHOLDER",
            sql_path(
                OUTPUT_ROOT
                / "dimensions"
                / "facility_master.parquet"
            ),
        ),
        "unmapped_diagnosis_codes": """
            SELECT
                visit_year,
                diagnosis_code_system,
                diagnosis_role,
                diagnosis_code_norm,
                COUNT(*) AS occurrence_count
            FROM diagnosis
            WHERE NOT code_description_mapped_flag
            GROUP BY
                visit_year,
                diagnosis_code_system,
                diagnosis_role,
                diagnosis_code_norm
            QUALIFY
                ROW_NUMBER() OVER (
                    PARTITION BY
                        visit_year,
                        diagnosis_code_system,
                        diagnosis_role
                    ORDER BY
                        COUNT(*) DESC,
                        diagnosis_code_norm
                ) <= 100
            ORDER BY
                visit_year,
                diagnosis_code_system,
                diagnosis_role,
                occurrence_count DESC
        """,
        "unmapped_procedure_codes": """
            SELECT
                visit_year,
                procedure_code_system,
                procedure_role,
                procedure_code_norm,
                COUNT(*) AS occurrence_count,
                BOOL_OR(code_description_mapped_flag)
                    AS any_description_mapping,
                BOOL_OR(group_mapped_flag)
                    AS any_group_mapping
            FROM procedure
            WHERE
                NOT code_description_mapped_flag
                OR NOT group_mapped_flag
            GROUP BY
                visit_year,
                procedure_code_system,
                procedure_role,
                procedure_code_norm
            QUALIFY
                ROW_NUMBER() OVER (
                    PARTITION BY
                        visit_year,
                        procedure_code_system,
                        procedure_role
                    ORDER BY
                        COUNT(*) DESC,
                        procedure_code_norm
                ) <= 100
            ORDER BY
                visit_year,
                procedure_code_system,
                procedure_role,
                occurrence_count DESC
        """,
    }
    for name, query in qa_queries.items():
        parquet_path = qa_dir / f"{name}.parquet"
        copy_query(connection, query, parquet_path)
        frame = pd.read_parquet(parquet_path)
        frame.to_csv(qa_dir / f"{name}.csv", index=False)
    fact_count = connection.execute(
        "SELECT COUNT(*) FROM fact"
    ).fetchone()[0]
    fact_distinct_visit = connection.execute(
        "SELECT COUNT(DISTINCT visit_key) FROM fact"
    ).fetchone()[0]
    success_total = sum(
        int(item["output_fact_row_count"]) for item in manifests
    )
    excluded_year_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM fact
        WHERE visit_year IN (2009, 2025)
        """
    ).fetchone()[0]
    wrong_transition = connection.execute(
        """
        SELECT COUNT(*)
        FROM fact
        WHERE
            (visit_year = 2015 AND visit_quarter <= 3
                AND diagnosis_code_system <> 'ICD-9-CM')
            OR
            (visit_year = 2015 AND visit_quarter = 4
                AND diagnosis_code_system <> 'ICD-10-CM')
        """
    ).fetchone()[0]
    false_deferred = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE same_facility_inpatient_admission_flag
                    IS NOT NULL
            ),
            COUNT(*) FILTER (
                WHERE revisit_7d_flag IS NOT NULL
                    OR revisit_30d_flag IS NOT NULL
            ),
            COUNT(*) FILTER (
                WHERE clinical_triage_level IS NOT NULL
            )
        FROM fact
        """
    ).fetchone()
    facility_master_path = (
        OUTPUT_ROOT / "dimensions" / "facility_master.parquet"
    )
    physician_master_path = (
        OUTPUT_ROOT / "dimensions" / "physician_master.parquet"
    )
    facility_rows = pq.ParquetFile(
        facility_master_path
    ).metadata.num_rows
    facility_distinct = connection.execute(
        f"""
        SELECT COUNT(DISTINCT facility_ahca_id)
        FROM read_parquet('{sql_path(facility_master_path)}')
        """
    ).fetchone()[0]
    physician_rows = pq.ParquetFile(
        physician_master_path
    ).metadata.num_rows
    physician_distinct = connection.execute(
        f"""
        SELECT COUNT(DISTINCT npi)
        FROM read_parquet('{sql_path(physician_master_path)}')
        """
    ).fetchone()[0]
    qa_summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "expected_quarters": len(EXPECTED_QUARTERS),
        "completed_quarters": len(manifests),
        "fact_row_count": fact_count,
        "sum_quarter_manifest_fact_rows": success_total,
        "fact_distinct_visit_key_count": fact_distinct_visit,
        "fact_count_reconciliation_passed": fact_count == success_total,
        "visit_key_uniqueness_passed": fact_count == fact_distinct_visit,
        "excluded_2009_2025_row_count": excluded_year_count,
        "excluded_years_passed": excluded_year_count == 0,
        "icd_transition_error_row_count": wrong_transition,
        "icd_transition_passed": wrong_transition == 0,
        "non_null_same_facility_admission_count": false_deferred[0],
        "non_null_revisit_measure_count": false_deferred[1],
        "non_null_true_triage_count": false_deferred[2],
        "deferred_measure_semantics_passed": false_deferred
        == (0, 0, 0),
        "facility_master_row_count": facility_rows,
        "facility_master_distinct_ahca_id_count":
            facility_distinct,
        "facility_master_one_row_per_ahca_id_passed":
            facility_rows == facility_distinct,
        "physician_master_row_count": physician_rows,
        "physician_master_distinct_npi_count": physician_distinct,
        "physician_master_one_row_per_npi_passed": physician_rows
        == physician_distinct,
        "all_required_checks_passed": all(
            [
                fact_count == success_total,
                fact_count == fact_distinct_visit,
                excluded_year_count == 0,
                wrong_transition == 0,
                false_deferred == (0, 0, 0),
                facility_rows == facility_distinct,
                physician_rows == physician_distinct,
            ]
        ),
    }
    (qa_dir / "qa_summary.json").write_text(
        json.dumps(qa_summary, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    manifests = require_complete_partitions()
    connection = duckdb.connect()
    connection.execute("SET threads = 8")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute("SET memory_limit = '16GB'")
    final_tmp = TMP_ROOT / "finalize"
    final_tmp.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"SET temp_directory = '{sql_path(final_tmp)}'"
    )
    create_views(connection)
    print("1/3 Building facility history and master", flush=True)
    build_facility_outputs(connection)
    print("2/3 Building summary statistics", flush=True)
    build_summary_outputs(connection)
    print("3/3 Building QA and missingness outputs", flush=True)
    build_qa_outputs(connection, manifests)
    connection.close()
    print(
        json.dumps(
            {
                "status": "Complete",
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "output": str(OUTPUT_ROOT),
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
