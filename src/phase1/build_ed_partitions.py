# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_full_build_20260724/scripts/build_ed_partitions.py
# Private encounter, release, dependency, and scratch roots are environment-configured.

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
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


IN_SCOPE_YEARS = list(range(2005, 2009)) + list(range(2010, 2025))
CHARGE_COLUMNS = [
    "PHARMCHGS",
    "MEDCHGS",
    "LABCHGS",
    "RADCHGS",
    "CARDIOCHGS",
    "OPRMCHGS",
    "ANESCHGS",
    "RECOVCHGS",
    "ERCHGS",
    "TRAUMACHGS",
    "OBSERCHGS",
    "GASTROCHGS",
    "LITHOCHGS",
    "OTHCHGS",
]
DIAGNOSIS_COLUMNS = (
    ["PRINDIAG"]
    + [f"OTHDIAG{i}" for i in range(1, 10)]
    + ["ECODE1", "ECODE2", "ECODE3"]
    + ["ECMORB1", "ECMORB2", "ECMORB3"]
    + ["REASON_CDE"]
)
SERVICE_COLUMNS = (
    ["PRINCPT"]
    + [f"EVALCODE{i}" for i in range(1, 6)]
    + [f"OTHCPT{i}" for i in range(1, 31)]
)
ICD_PROCEDURE_COLUMNS = ["PRINPROC"] + [
    f"OTHPROC{i}" for i in range(1, 5)
]
ROLE_SPECS = {
    "attending": {
        "license_legacy": "ATTENPHYID",
        "license_modern": "ATTEN_PHYID",
        "npi": "ATTEN_PHYNPI",
    },
    "operating_performing": {
        "license_legacy": "OPERPHYID",
        "license_modern": "OPER_PHYID",
        "npi": "OPER_PHYNPI",
    },
    "other_practitioner": {
        "license_legacy": "OTHERPHYID",
        "license_modern": "OTHOPER_PHYID",
        "npi": "OTHOPER_PHYNPI",
    },
}


def qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_npi(value: object) -> bool:
    if value is None:
        return False
    text = re.sub(r"\D", "", str(value))
    if len(text) != 10 or text == "9999999999":
        return False
    digits = [int(char) for char in "80840" + text]
    total = sum(digits[-1::-2])
    for digit in digits[-2::-2]:
        total += sum(divmod(2 * digit, 10))
    return total % 10 == 0


def read_header(path: Path) -> list[str]:
    with path.open(
        "r", encoding="utf-8-sig", errors="replace", newline=""
    ) as stream:
        return next(csv.reader(stream))


def schema_id(columns: list[str]) -> str:
    column_set = set(columns)
    if len(columns) == 63 and "PRINCPT" in column_set:
        return "schema_1_2005_2008"
    if (
        len(columns) == 100
        and "ECODE1" in column_set
        and "PRINPROC" in column_set
    ):
        return "schema_2_2010_2015q3"
    if (
        len(columns) == 100
        and "ECMORB1" in column_set
        and "PRINPROC" in column_set
    ):
        return "schema_3_2015q4_2017"
    if len(columns) == 95 and "PRINPROC" not in column_set:
        return "schema_4_2018_2022"
    if (
        len(columns) == 100
        and "FAC_NAME" in column_set
        and "CERT_DATE" in column_set
    ):
        return "schema_5_2023_2024"
    raise RuntimeError(
        f"Unapproved schema: {len(columns)} columns; "
        f"first columns={columns[:10]}"
    )


def raw_text(column: str, columns: set[str]) -> str:
    if column not in columns:
        return "CAST(NULL AS VARCHAR)"
    return f"NULLIF(TRIM({qident(column)}), '')"


def raw_number(column: str, columns: set[str]) -> str:
    if column not in columns:
        return "CAST(NULL AS DOUBLE)"
    return f"TRY_CAST(NULLIF(TRIM({qident(column)}), '') AS DOUBLE)"


def normalize_code(expr: str) -> str:
    return (
        "NULLIF(REGEXP_REPLACE(UPPER(TRIM("
        + expr
        + ")), '[^A-Z0-9]', '', 'g'), '')"
    )


def output_path(
    family: str, year: int, quarter: int, filename: str
) -> Path:
    return (
        OUTPUT_ROOT
        / family
        / f"visit_year={year}"
        / f"visit_quarter={quarter}"
        / filename
    )


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


def create_reference_views(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    decoder = OUTPUT_ROOT / "decoders"
    dimension = OUTPUT_ROOT / "dimensions"
    references = {
        "ref_icd9_diagnosis": decoder
        / "icd9_diagnosis_reference.parquet",
        "ref_icd10_ccsr": decoder
        / "icd10_ccsr_diagnosis_mapping.parquet",
        "ref_icd9_procedure": decoder
        / "icd9_procedure_reference.parquet",
        "ref_icd10pcs": decoder
        / "icd10pcs_procedure_class_reference.parquet",
        "ref_service_ccs": decoder
        / "cpt_hcpcs_ccs_exact_reference.parquet",
        "ref_hcpcs": decoder
        / "hcpcs_level2_2026_q3_reference.parquet",
        "ref_elix_icd9": decoder
        / "elixhauser_icd9_mapping.parquet",
        "ref_elix_icd10": decoder
        / "elixhauser_icd10_mapping.parquet",
        "ref_license_npi": decoder
        / "florida_license_to_npi_unique.parquet",
        "ref_county": decoder
        / "florida_county_fips_reference.parquet",
        "ref_zip": decoder / "zip_geography_reference.parquet",
        "ref_ruca": decoder / "zip_ruca_2020_reference.parquet",
        "ref_physician": dimension / "physician_master.parquet",
        "ref_facility_companion": dimension
        / "facility_companion_history.parquet",
    }
    for view_name, path in references.items():
        if not path.exists():
            raise FileNotFoundError(path)
        connection.execute(
            f"""
            CREATE OR REPLACE VIEW {view_name} AS
            SELECT * FROM read_parquet('{sql_path(path)}')
            """
        )
    connection.execute(
        """
        CREATE OR REPLACE VIEW ref_icd10_default AS
        SELECT
            icd10_key,
            ANY_VALUE(icd10_description) AS icd10_description,
            COALESCE(
                MAX(ccsr_category) FILTER (WHERE outpatient_default = 'Y'),
                ARG_MIN(ccsr_category, category_sequence)
            ) AS default_category,
            COALESCE(
                MAX(ccsr_category_description)
                    FILTER (WHERE outpatient_default = 'Y'),
                ARG_MIN(ccsr_category_description, category_sequence)
            ) AS default_category_description,
            COUNT(DISTINCT ccsr_category) AS category_mapping_count,
            ANY_VALUE(mapping_version) AS mapping_version
        FROM ref_icd10_ccsr
        GROUP BY icd10_key
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE VIEW ref_county_normalized AS
        SELECT
            *,
            REGEXP_REPLACE(
                UPPER(county_name), '[^A-Z0-9]', '', 'g'
            ) AS county_name_norm
        FROM ref_county
        """
    )


def create_core_table(
    connection: duckdb.DuckDBPyConnection,
    raw_file: Path,
    year: int,
    quarter: int,
    columns: list[str],
    schema: str,
) -> None:
    column_set = set(columns)
    connection.execute(
        f"""
        CREATE OR REPLACE VIEW raw_source AS
        SELECT
            *,
            ROW_NUMBER() OVER () AS _source_row_number
        FROM read_csv_auto(
            '{sql_path(raw_file)}',
            HEADER = TRUE,
            ALL_VARCHAR = TRUE,
            SAMPLE_SIZE = -1,
            IGNORE_ERRORS = FALSE,
            NULL_PADDING = TRUE
        )
        """
    )
    select_parts = [
        f"{year}::SMALLINT AS visit_year",
        f"{quarter}::UTINYINT AS visit_quarter",
        f"'{schema}'::VARCHAR AS source_schema_id",
        f"'{raw_file.name}'::VARCHAR AS source_file_name",
        "_source_row_number::BIGINT AS source_row_number",
        f"{raw_text('SYS_RECID', column_set)} AS source_record_id",
        f"{raw_text('YEAR', column_set)} AS year_raw",
        f"{raw_text('QTR', column_set)} AS quarter_raw",
        f"{raw_text('TYPE_SERV', column_set)} AS type_of_service_raw",
        f"{raw_text('PRO_CODE', column_set)} AS facility_program_code_raw",
        f"{raw_text('FAC_REGION', column_set)} AS facility_region_code_raw",
        f"{raw_text('FAC_COUNTY', column_set)} AS facility_county_code_raw",
        f"{raw_text('FAC_COUNTY_NAME', column_set)} "
        "AS facility_county_name_raw",
        f"{raw_text('FACLNBR', column_set)} AS facility_ahca_id",
        f"{raw_text('FAC_NAME', column_set)} AS facility_name_raw",
        f"{raw_text('MCARE_NBR', column_set)} "
        "AS facility_medicare_number_raw",
        f"{raw_text('SERV_LOC', column_set)} AS service_location_raw",
        f"{raw_text('CERT_DATE', column_set)} "
        "AS facility_certification_date_raw",
        f"{raw_text('ETHNICITY', column_set)} AS ethnicity_raw",
        f"{raw_text('RACE', column_set)} AS race_raw",
        f"{raw_text('SEX', column_set)} AS sex_raw",
        f"{raw_text('AGE', column_set)} AS age_raw",
        f"{raw_number('AGE', column_set)} AS age_numeric_raw",
        f"{raw_text('LOSDAYS', column_set)} AS length_of_stay_days_raw",
        f"{raw_number('LOSDAYS', column_set)} "
        "AS length_of_stay_days",
        f"{raw_text('WEEKDAY', column_set)} AS weekday_raw",
        f"{raw_text('ZIPCODE', column_set)} AS patient_zip_raw",
        f"{raw_text('PTCOUNTY', column_set)} "
        "AS patient_county_code_raw",
        f"{raw_text('PTCOUNTY_NAME', column_set)} "
        "AS patient_county_name_raw",
        f"{raw_text('PTSTATE', column_set)} AS patient_state_raw",
        f"{raw_text('PTCOUNTRY', column_set)} "
        "AS patient_country_raw",
        f"{raw_text('ADMSRC', column_set)} "
        "AS admission_source_raw",
        f"{raw_text('HR_ARRIVAL', column_set)} AS arrival_hour_raw",
        f"{raw_text('EDHR_DISCH', column_set)} "
        "AS ed_discharge_hour_raw",
        f"{raw_text('PT_STATUS', column_set)} "
        "AS patient_status_raw",
        f"{raw_text('PAYER', column_set)} AS payer_raw",
        f"{raw_text('PAYER_NAME', column_set)} AS payer_name_raw",
    ]
    for column in DIAGNOSIS_COLUMNS + SERVICE_COLUMNS + ICD_PROCEDURE_COLUMNS:
        select_parts.append(
            f"{raw_text(column, column_set)} AS {column.lower()}_raw"
        )
    for role, spec in ROLE_SPECS.items():
        legacy = raw_text(spec["license_legacy"], column_set)
        modern = raw_text(spec["license_modern"], column_set)
        select_parts.extend(
            [
                f"COALESCE({modern}, {legacy}) "
                f"AS {role}_license_id_raw",
                f"{raw_text(spec['npi'], column_set)} "
                f"AS {role}_npi_raw",
            ]
        )
    for column in CHARGE_COLUMNS + ["TCHGS"]:
        select_parts.extend(
            [
                f"{raw_text(column, column_set)} "
                f"AS {column.lower()}_raw",
                f"{raw_number(column, column_set)} "
                f"AS {column.lower()}",
            ]
        )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE core_unkeyed AS
        SELECT
            {", ".join(select_parts)}
        FROM raw_source
        WHERE TRIM(TYPE_SERV) = '2'
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE core AS
        WITH keyed AS (
            SELECT
                *,
                COUNT(*) OVER (
                    PARTITION BY source_record_id
                ) AS source_record_duplicate_count,
                ROW_NUMBER() OVER (
                    PARTITION BY source_record_id
                    ORDER BY source_row_number
                ) AS source_record_duplicate_sequence
            FROM core_unkeyed
        )
        SELECT
            '{year}Q{quarter}' || '|' ||
                COALESCE(source_record_id, 'MISSING') || '|' ||
                CAST(source_record_duplicate_sequence AS VARCHAR)
                AS visit_key,
            '{year}Q{quarter}' || '|' ||
                COALESCE(source_record_id, 'MISSING')
                AS source_encounter_key,
            source_record_duplicate_count > 1
                AS source_record_duplicate_flag,
            CASE
                WHEN {year} < 2015
                    OR ({year} = 2015 AND {quarter} <= 3)
                    THEN 'ICD-9-CM'
                ELSE 'ICD-10-CM'
            END AS diagnosis_code_system,
            CASE
                WHEN {year} < 2015
                    OR ({year} = 2015 AND {quarter} <= 3)
                    THEN 'ICD-9-CM'
                WHEN {year} < 2018
                    THEN 'ICD-10-PCS'
                ELSE NULL
            END AS icd_procedure_code_system,
            *
        FROM keyed
        """
    )


def create_diagnosis_tables(
    connection: duckdb.DuckDBPyConnection,
    year: int,
    quarter: int,
) -> tuple[list[str], list[str]]:
    occurrence_queries = []
    for column in DIAGNOSIS_COLUMNS:
        if column == "PRINDIAG":
            role = "principal"
            position = 0
        elif column.startswith("OTHDIAG"):
            role = "secondary"
            position = int(column.replace("OTHDIAG", ""))
        elif column.startswith(("ECODE", "ECMORB")):
            role = "external_cause"
            position = int(re.sub(r"\D", "", column))
        else:
            role = "reason_for_visit"
            position = 0
        raw_column = f"{column.lower()}_raw"
        occurrence_queries.append(
            f"""
            SELECT
                visit_key,
                visit_year,
                visit_quarter,
                diagnosis_code_system,
                '{role}'::VARCHAR AS diagnosis_role,
                '{column}'::VARCHAR AS source_field,
                {position}::UTINYINT AS diagnosis_position,
                {raw_column} AS diagnosis_code_raw,
                {normalize_code(raw_column)} AS diagnosis_code_norm
            FROM core
            WHERE {raw_column} IS NOT NULL
            """
        )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE diagnosis_occurrence AS
        """
        + " UNION ALL ".join(occurrence_queries)
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE diagnosis_enriched AS
        SELECT
            d.*,
            r.short_title AS diagnosis_short_description,
            r.long_title AS diagnosis_long_description,
            r.ccs_category AS default_clinical_category,
            r.ccs_category_label AS default_clinical_category_label,
            CASE WHEN r.icd9_key IS NULL THEN 0 ELSE 1 END
                AS category_mapping_count,
            r.mapping_version,
            r.icd9_key IS NOT NULL AS code_description_mapped_flag
        FROM diagnosis_occurrence d
        LEFT JOIN ref_icd9_diagnosis r
            ON d.diagnosis_code_norm = r.icd9_key
        WHERE d.diagnosis_code_system = 'ICD-9-CM'

        UNION ALL

        SELECT
            d.*,
            r.icd10_description AS diagnosis_short_description,
            r.icd10_description AS diagnosis_long_description,
            r.default_category AS default_clinical_category,
            r.default_category_description
                AS default_clinical_category_label,
            COALESCE(r.category_mapping_count, 0)
                AS category_mapping_count,
            r.mapping_version,
            r.icd10_key IS NOT NULL AS code_description_mapped_flag
        FROM diagnosis_occurrence d
        LEFT JOIN ref_icd10_default r
            ON d.diagnosis_code_norm = r.icd10_key
        WHERE d.diagnosis_code_system = 'ICD-10-CM'
        """
    )
    copy_query(
        connection,
        """
        SELECT *
        FROM diagnosis_enriched
        ORDER BY source_encounter_sort_key
        """.replace(
            "source_encounter_sort_key",
            "visit_key, diagnosis_role, diagnosis_position",
        ),
        output_path(
            "bridges/visit_diagnosis",
            year,
            quarter,
            "visit_diagnosis.parquet",
        ),
    )
    copy_query(
        connection,
        """
        SELECT
            d.visit_key,
            d.visit_year,
            d.visit_quarter,
            d.diagnosis_role,
            d.source_field,
            d.diagnosis_position,
            d.diagnosis_code_system,
            d.diagnosis_code_raw,
            d.diagnosis_code_norm,
            r.ccsr_category AS clinical_category,
            r.ccsr_category_description AS clinical_category_label,
            r.inpatient_default,
            r.outpatient_default,
            r.default_rationale,
            r.category_sequence,
            r.mapping_version
        FROM diagnosis_occurrence d
        JOIN ref_icd10_ccsr r
            ON d.diagnosis_code_norm = r.icd10_key
        WHERE d.diagnosis_code_system = 'ICD-10-CM'

        UNION ALL

        SELECT
            d.visit_key,
            d.visit_year,
            d.visit_quarter,
            d.diagnosis_role,
            d.source_field,
            d.diagnosis_position,
            d.diagnosis_code_system,
            d.diagnosis_code_raw,
            d.diagnosis_code_norm,
            r.ccs_category AS clinical_category,
            r.ccs_category_label AS clinical_category_label,
            'Y' AS inpatient_default,
            'Y' AS outpatient_default,
            NULL AS default_rationale,
            1 AS category_sequence,
            r.mapping_version
        FROM diagnosis_occurrence d
        JOIN ref_icd9_diagnosis r
            ON d.diagnosis_code_norm = r.icd9_key
        WHERE d.diagnosis_code_system = 'ICD-9-CM'
        """,
        output_path(
            "bridges/visit_diagnosis_category",
            year,
            quarter,
            "visit_diagnosis_category.parquet",
        ),
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE diagnosis_metrics AS
        SELECT
            visit_key,
            COUNT(*)::USMALLINT AS diagnosis_code_count,
            COUNT(*) FILTER (
                WHERE diagnosis_role = 'secondary'
            )::UTINYINT AS secondary_diagnosis_code_count,
            COUNT(*) FILTER (
                WHERE diagnosis_role = 'external_cause'
            )::UTINYINT AS external_cause_code_count,
            COUNT(DISTINCT default_clinical_category) FILTER (
                WHERE diagnosis_role IN ('principal', 'secondary')
            )::UTINYINT AS distinct_default_clinical_group_count,
            MAX(diagnosis_code_norm) FILTER (
                WHERE diagnosis_role = 'principal'
            ) AS principal_diagnosis_code_norm,
            MAX(diagnosis_short_description) FILTER (
                WHERE diagnosis_role = 'principal'
            ) AS principal_diagnosis_description,
            MAX(default_clinical_category) FILTER (
                WHERE diagnosis_role = 'principal'
            ) AS principal_clinical_category,
            MAX(default_clinical_category_label) FILTER (
                WHERE diagnosis_role = 'principal'
            ) AS principal_clinical_category_label,
            BOOL_OR(code_description_mapped_flag) FILTER (
                WHERE diagnosis_role = 'principal'
            ) AS principal_diagnosis_mapped_flag
        FROM diagnosis_enriched
        GROUP BY visit_key
        """
    )
    icd9_conditions = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT condition FROM ref_elix_icd9 ORDER BY 1"
        ).fetchall()
    ]
    icd10_conditions = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT condition FROM ref_elix_icd10 ORDER BY 1"
        ).fetchall()
    ]
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE elixhauser_hits AS
        SELECT
            d.visit_key,
            d.visit_year,
            d.visit_quarter,
            d.diagnosis_code_system,
            r.condition,
            ANY_VALUE(r.condition_description)
                AS condition_description,
            STRING_AGG(
                DISTINCT d.diagnosis_code_norm, '|'
                ORDER BY d.diagnosis_code_norm
            ) AS contributing_diagnosis_codes,
            STRING_AGG(
                DISTINCT d.source_field, '|'
                ORDER BY d.source_field
            ) AS contributing_source_fields,
            ANY_VALUE(r.mapping_version) AS mapping_version,
            ANY_VALUE(r.mapping_scope_note) AS mapping_scope_note
        FROM diagnosis_occurrence d
        JOIN ref_elix_icd9 r
            ON d.diagnosis_code_norm = r.icd9_key
        WHERE
            d.diagnosis_role = 'secondary'
            AND d.diagnosis_code_system = 'ICD-9-CM'
        GROUP BY
            d.visit_key,
            d.visit_year,
            d.visit_quarter,
            d.diagnosis_code_system,
            r.condition

        UNION ALL

        SELECT
            d.visit_key,
            d.visit_year,
            d.visit_quarter,
            d.diagnosis_code_system,
            r.condition,
            ANY_VALUE(r.condition_description)
                AS condition_description,
            STRING_AGG(
                DISTINCT d.diagnosis_code_norm, '|'
                ORDER BY d.diagnosis_code_norm
            ) AS contributing_diagnosis_codes,
            STRING_AGG(
                DISTINCT d.source_field, '|'
                ORDER BY d.source_field
            ) AS contributing_source_fields,
            ANY_VALUE(r.mapping_version) AS mapping_version,
            ANY_VALUE(r.mapping_scope_note) AS mapping_scope_note
        FROM diagnosis_occurrence d
        JOIN ref_elix_icd10 r
            ON d.diagnosis_code_norm = r.icd10_key
        WHERE
            d.diagnosis_role = 'secondary'
            AND d.diagnosis_code_system = 'ICD-10-CM'
        GROUP BY
            d.visit_key,
            d.visit_year,
            d.visit_quarter,
            d.diagnosis_code_system,
            r.condition
        """
    )
    copy_query(
        connection,
        "SELECT * FROM elixhauser_hits",
        output_path(
            "bridges/visit_elixhauser",
            year,
            quarter,
            "visit_elixhauser.parquet",
        ),
    )
    union_conditions = sorted(set(icd9_conditions) | set(icd10_conditions))
    pivots = [
        (
            "MAX(CASE WHEN condition = "
            f"'{condition}' THEN 1 ELSE 0 END)::UTINYINT "
            f"AS elix_{condition.lower()}_flag"
        )
        for condition in union_conditions
    ]
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE elixhauser_metrics AS
        SELECT
            visit_key,
            COUNT(DISTINCT condition)::UTINYINT
                AS elixhauser_condition_count,
            {", ".join(pivots)}
        FROM elixhauser_hits
        GROUP BY visit_key
        """
    )
    return icd9_conditions, icd10_conditions


def create_procedure_tables(
    connection: duckdb.DuckDBPyConnection,
    year: int,
    quarter: int,
) -> None:
    occurrence_queries = []
    for column in SERVICE_COLUMNS:
        if column == "PRINCPT":
            role = "principal_service"
            position = 0
        elif column.startswith("EVALCODE"):
            role = "evaluation_management"
            position = int(column.replace("EVALCODE", ""))
        else:
            role = "other_service"
            position = int(column.replace("OTHCPT", ""))
        raw_column = f"{column.lower()}_raw"
        occurrence_queries.append(
            f"""
            SELECT
                visit_key,
                visit_year,
                visit_quarter,
                'CPT_HCPCS'::VARCHAR AS procedure_code_system,
                '{role}'::VARCHAR AS procedure_role,
                '{column}'::VARCHAR AS source_field,
                {position}::UTINYINT AS procedure_position,
                {raw_column} AS procedure_code_raw,
                {normalize_code(raw_column)} AS procedure_code_norm
            FROM core
            WHERE {raw_column} IS NOT NULL
            """
        )
    if year <= 2017:
        for column in ICD_PROCEDURE_COLUMNS:
            role = (
                "principal_icd_procedure"
                if column == "PRINPROC"
                else "other_icd_procedure"
            )
            position = (
                0
                if column == "PRINPROC"
                else int(column.replace("OTHPROC", ""))
            )
            raw_column = f"{column.lower()}_raw"
            occurrence_queries.append(
                f"""
                SELECT
                    visit_key,
                    visit_year,
                    visit_quarter,
                    icd_procedure_code_system
                        AS procedure_code_system,
                    '{role}'::VARCHAR AS procedure_role,
                    '{column}'::VARCHAR AS source_field,
                    {position}::UTINYINT AS procedure_position,
                    {raw_column} AS procedure_code_raw,
                    {normalize_code(raw_column)}
                        AS procedure_code_norm
                FROM core
                WHERE {raw_column} IS NOT NULL
                """
            )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE procedure_occurrence AS
        """
        + " UNION ALL ".join(occurrence_queries)
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE procedure_enriched AS
        SELECT
            p.*,
            h.hcpcs_long_description AS procedure_description,
            CASE
                WHEN h.hcpcs_code IS NOT NULL
                    THEN h.description_version
                WHEN REGEXP_FULL_MATCH(
                    p.procedure_code_norm, '[0-9]{5}'
                )
                    THEN
                    'CPT description unavailable: AMA-licensed content '
                    || 'not included'
                ELSE 'CMS HCPCS July 2026: code not found'
            END AS description_source,
            s.ccs_service_category AS procedure_group,
            s.ccs_service_category_label AS procedure_group_label,
            s.mapping_version,
            h.hcpcs_code IS NOT NULL
                AS code_description_mapped_flag,
            s.service_code IS NOT NULL AS group_mapped_flag
        FROM procedure_occurrence p
        LEFT JOIN ref_hcpcs h
            ON p.procedure_code_norm = h.hcpcs_code
        LEFT JOIN ref_service_ccs s
            ON p.procedure_code_norm = s.service_code
        WHERE p.procedure_code_system = 'CPT_HCPCS'

        UNION ALL

        SELECT
            p.*,
            r.icd9_proc_desc_long AS procedure_description,
            'CMS/AHRQ ICD-9-CM procedure description'
                AS description_source,
            r.ccs_proc_cat AS procedure_group,
            r.ccs_proc_cat_label_final AS procedure_group_label,
            r.mapping_version,
            r.icd9_proc_code IS NOT NULL
                AS code_description_mapped_flag,
            r.ccs_proc_cat IS NOT NULL AS group_mapped_flag
        FROM procedure_occurrence p
        LEFT JOIN ref_icd9_procedure r
            ON p.procedure_code_norm = r.icd9_proc_code
        WHERE p.procedure_code_system = 'ICD-9-CM'

        UNION ALL

        SELECT
            p.*,
            r.icd10pcs_desc AS procedure_description,
            'CMS ICD-10-PCS description' AS description_source,
            r.ccrs_proc_class AS procedure_group,
            r.ccrs_proc_class_name AS procedure_group_label,
            r.mapping_version,
            r.icd10pcs_code IS NOT NULL
                AS code_description_mapped_flag,
            r.ccrs_proc_class IS NOT NULL AS group_mapped_flag
        FROM procedure_occurrence p
        LEFT JOIN ref_icd10pcs r
            ON p.procedure_code_norm = r.icd10pcs_code
        WHERE p.procedure_code_system = 'ICD-10-PCS'
        """
    )
    copy_query(
        connection,
        "SELECT * FROM procedure_enriched",
        output_path(
            "bridges/visit_procedure",
            year,
            quarter,
            "visit_procedure.parquet",
        ),
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE procedure_metrics_base AS
        SELECT
            visit_key,
            COUNT(*) FILTER (
                WHERE procedure_code_system = 'CPT_HCPCS'
            )::UTINYINT AS cpt_hcpcs_count,
            COUNT(*) FILTER (
                WHERE procedure_role = 'evaluation_management'
            )::UTINYINT AS evaluation_management_code_count,
            COUNT(*) FILTER (
                WHERE procedure_code_system
                    IN ('ICD-9-CM', 'ICD-10-PCS')
            )::UTINYINT AS icd_procedure_count_observed,
            COUNT(DISTINCT procedure_group) FILTER (
                WHERE procedure_group IS NOT NULL
            )::UTINYINT AS distinct_procedure_group_count,
            MAX(
                CASE procedure_code_norm
                    WHEN '99281' THEN 1
                    WHEN 'G0380' THEN 1
                    WHEN '99282' THEN 2
                    WHEN 'G0381' THEN 2
                    WHEN '99283' THEN 3
                    WHEN 'G0382' THEN 3
                    WHEN '99284' THEN 4
                    WHEN 'G0383' THEN 4
                    WHEN '99285' THEN 5
                    WHEN 'G0384' THEN 5
                    ELSE NULL
                END
            )::UTINYINT AS em_acuity_proxy_level,
            BOOL_OR(
                procedure_code_norm IN ('99291', '99292')
            ) FILTER (
                WHERE procedure_role = 'evaluation_management'
            ) AS em_critical_care_flag,
            BOOL_OR(procedure_code_norm = '99288') FILTER (
                WHERE procedure_role = 'evaluation_management'
            ) AS em_special_emergency_code_flag,
            BOOL_OR(procedure_code_norm = '99999') FILTER (
                WHERE procedure_role = 'evaluation_management'
            ) AS em_nonbillable_sentinel_flag
        FROM procedure_enriched
        GROUP BY visit_key
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE procedure_metrics AS
        WITH completed AS (
            SELECT
                c.visit_key,
                COALESCE(p.cpt_hcpcs_count, 0)
                    AS cpt_hcpcs_count,
                COALESCE(p.evaluation_management_code_count, 0)
                    AS evaluation_management_code_count,
                CASE
                    WHEN {year} <= 2017
                        THEN COALESCE(
                            p.icd_procedure_count_observed, 0
                        )
                    ELSE NULL
                END AS icd_procedure_count,
                COALESCE(p.distinct_procedure_group_count, 0)
                    AS distinct_procedure_group_count,
                p.em_acuity_proxy_level,
                COALESCE(p.em_critical_care_flag, FALSE)
                    AS em_critical_care_flag,
                COALESCE(
                    p.em_special_emergency_code_flag, FALSE
                ) AS em_special_emergency_code_flag,
                COALESCE(
                    p.em_nonbillable_sentinel_flag, FALSE
                ) AS em_nonbillable_sentinel_flag,
                CASE
                    WHEN {year} <= 2017
                        THEN COALESCE(p.cpt_hcpcs_count, 0)
                            + COALESCE(
                                p.icd_procedure_count_observed, 0
                            )
                    ELSE COALESCE(p.cpt_hcpcs_count, 0)
                END AS procedure_count_analysis,
                CASE
                    WHEN {year} <= 2017
                        THEN
                        'CPT/HCPCS plus ICD procedure fields'
                    ELSE
                        'CPT/HCPCS only; ICD procedure fields '
                        || 'structurally unavailable'
                END AS procedure_count_scope
            FROM core c
            LEFT JOIN procedure_metrics_base p USING (visit_key)
        ),
        threshold AS (
            SELECT
                QUANTILE_CONT(
                    procedure_count_analysis, 0.90
                ) AS high_procedure_threshold
            FROM completed
        )
        SELECT
            completed.*,
            threshold.high_procedure_threshold,
            procedure_count_analysis > 0
                AS any_procedure_flag,
            procedure_count_analysis > 0
                AND procedure_count_analysis
                    >= threshold.high_procedure_threshold
                AS high_procedure_flag
        FROM completed
        CROSS JOIN threshold
        """
    )


def create_physician_linkage(
    connection: duckdb.DuckDBPyConnection,
    year: int,
) -> None:
    role_queries = []
    for role in ROLE_SPECS:
        role_queries.append(
            f"""
            SELECT
                visit_key,
                '{role}'::VARCHAR AS practitioner_role,
                {role}_license_id_raw
                    AS practitioner_license_id_raw,
                {role}_npi_raw AS practitioner_npi_raw
            FROM core
            """
        )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE practitioner_role_raw AS
        """
        + " UNION ALL ".join(role_queries)
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE practitioner_role_linked AS
        WITH normalized AS (
            SELECT
                *,
                NULLIF(
                    REGEXP_REPLACE(
                        UPPER(TRIM(practitioner_license_id_raw)),
                        '[^A-Z0-9]',
                        '',
                        'g'
                    ),
                    ''
                ) AS license_number_norm,
                NULLIF(
                    REGEXP_REPLACE(
                        TRIM(practitioner_npi_raw),
                        '[^0-9]',
                        '',
                        'g'
                    ),
                    ''
                ) AS npi_norm
            FROM practitioner_role_raw
        ),
        selected AS (
            SELECT
                n.*,
                CASE
                    WHEN npi_is_valid(npi_norm) THEN npi_norm
                    WHEN
                        NOT npi_is_valid(npi_norm)
                        AND x.npi IS NOT NULL
                        THEN x.npi
                    ELSE NULL
                END AS selected_npi,
                CASE
                    WHEN npi_is_valid(npi_norm)
                        THEN 'direct_validated_npi'
                    WHEN
                        NOT npi_is_valid(npi_norm)
                        AND x.npi IS NOT NULL
                        THEN 'unique_fl_license_crosswalk'
                    WHEN
                        npi_norm IS NOT NULL
                        AND npi_norm = '9999999999'
                        THEN 'source_npi_sentinel'
                    WHEN npi_norm IS NOT NULL
                        THEN 'invalid_direct_npi_unresolved'
                    WHEN n.license_number_norm IS NOT NULL
                        THEN 'license_unresolved'
                    ELSE 'no_practitioner_identifier'
                END AS selection_method
            FROM normalized n
            LEFT JOIN ref_license_npi x
                ON n.license_number_norm = x.license_number_norm
        )
        SELECT
            s.*,
            p.npi IS NOT NULL AS physician_master_matched_flag,
            CASE
                WHEN s.selected_npi IS NULL
                    THEN 'unresolved'
                WHEN p.npi IS NOT NULL
                    THEN 'matched_physician_master'
                ELSE 'validated_npi_not_in_physician_master'
            END AS physician_link_status,
            p.full_name,
            p.credentials,
            p.gender_category,
            p.gender_source,
            p.surname_imputed_race_ethnicity,
            p.surname_imputation_max_probability,
            p.race_ethnicity_source,
            p.taxonomy_display_name,
            p.cms_primary_specialty,
            p.cms_secondary_specialties,
            p.ed_specialist_flag,
            p.ed_specialist_source,
            p.physician_md_do_flag,
            p.medical_school_selected,
            p.medical_school_grad_year,
            CASE
                WHEN
                    p.medical_school_grad_year IS NOT NULL
                    AND {year} - p.medical_school_grad_year
                        BETWEEN 0 AND 80
                    THEN {year} - p.medical_school_grad_year
                ELSE NULL
            END AS years_since_medical_school,
            p.fl_license_numbers,
            p.doh_license_active_status,
            p.doh_board_certifications,
            p.doh_board_certification_count,
            p.doh_postgrad_specialties,
            p.doh_postgrad_row_count,
            p.has_fl_doh_hospital_privilege,
            p.doh_hospital_privilege_count,
            p.has_cms_group_practice_affiliation,
            p.cms_group_practice_count
        FROM selected s
        LEFT JOIN ref_physician p
            ON s.selected_npi = p.npi
        """
    )
    pivot_fields = [
        "practitioner_license_id_raw",
        "practitioner_npi_raw",
        "license_number_norm",
        "npi_norm",
        "selected_npi",
        "selection_method",
        "physician_master_matched_flag",
        "physician_link_status",
        "full_name",
        "gender_category",
        "surname_imputed_race_ethnicity",
        "taxonomy_display_name",
        "cms_primary_specialty",
        "ed_specialist_flag",
        "physician_md_do_flag",
        "years_since_medical_school",
        "has_fl_doh_hospital_privilege",
        "doh_hospital_privilege_count",
        "has_cms_group_practice_affiliation",
        "cms_group_practice_count",
    ]
    pivot_parts = []
    for role in ROLE_SPECS:
        for field in pivot_fields:
            pivot_parts.append(
                f"""
                MAX({field}) FILTER (
                    WHERE practitioner_role = '{role}'
                ) AS {role}_{field}
                """
            )
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE practitioner_role_wide AS
        SELECT
            visit_key,
            {", ".join(pivot_parts)}
        FROM practitioner_role_linked
        GROUP BY visit_key
        """
    )


def build_fact_query(
    year: int,
    quarter: int,
    icd9_conditions: list[str],
    icd10_conditions: list[str],
) -> str:
    charge_sum = " + ".join(
        f"COALESCE(c.{column.lower()}, 0)" for column in CHARGE_COLUMNS
    )
    charge_nonmissing = " + ".join(
        f"CASE WHEN c.{column.lower()} IS NOT NULL THEN 1 ELSE 0 END"
        for column in CHARGE_COLUMNS
    )
    raw_code_columns = [
        f"c.{column.lower()}_raw"
        for column in (
            DIAGNOSIS_COLUMNS
            + SERVICE_COLUMNS
            + ICD_PROCEDURE_COLUMNS
        )
    ]
    raw_charge_columns = []
    for column in CHARGE_COLUMNS + ["TCHGS"]:
        raw_charge_columns.extend(
            [f"c.{column.lower()}_raw", f"c.{column.lower()}"]
        )
    physician_columns = []
    pivot_fields = [
        "practitioner_license_id_raw",
        "practitioner_npi_raw",
        "license_number_norm",
        "npi_norm",
        "selected_npi",
        "selection_method",
        "physician_master_matched_flag",
        "physician_link_status",
        "full_name",
        "gender_category",
        "surname_imputed_race_ethnicity",
        "taxonomy_display_name",
        "cms_primary_specialty",
        "ed_specialist_flag",
        "physician_md_do_flag",
        "years_since_medical_school",
        "has_fl_doh_hospital_privilege",
        "doh_hospital_privilege_count",
        "has_cms_group_practice_affiliation",
        "cms_group_practice_count",
    ]
    for role in ROLE_SPECS:
        physician_columns.extend(
            f"pr.{role}_{field}" for field in pivot_fields
        )
    all_conditions = sorted(set(icd9_conditions) | set(icd10_conditions))
    active_conditions = (
        set(icd9_conditions)
        if year < 2015 or (year == 2015 and quarter <= 3)
        else set(icd10_conditions)
    )
    elix_fields = []
    for condition in all_conditions:
        alias = f"elix_{condition.lower()}_flag"
        if condition in active_conditions:
            elix_fields.append(
                f"COALESCE(e.{alias}, 0)::UTINYINT AS {alias}"
            )
        else:
            elix_fields.append(
                f"CAST(NULL AS UTINYINT) AS {alias}"
            )
    charge_tolerance = 10 if year <= 2008 else 13
    return f"""
    WITH base AS (
        SELECT
            c.visit_key,
            c.source_encounter_key,
            c.visit_year,
            c.visit_quarter,
            c.source_schema_id,
            c.source_file_name,
            c.source_row_number,
            c.source_record_id,
            c.source_record_duplicate_count,
            c.source_record_duplicate_flag,
            c.type_of_service_raw,
            'Emergency department visit' AS type_of_service_label,
            c.diagnosis_code_system,
            c.icd_procedure_code_system,

            c.facility_ahca_id,
            c.facility_name_raw,
            fc.facility_name_companion,
            COALESCE(
                c.facility_name_raw,
                fc.facility_name_companion
            ) AS facility_name_reported,
            CASE
                WHEN c.facility_name_raw IS NOT NULL
                    THEN 'ED encounter file'
                WHEN fc.facility_name_companion IS NOT NULL
                    THEN 'AHCA quarterly facility companion'
                ELSE NULL
            END AS facility_name_source,
            c.facility_medicare_number_raw,
            c.facility_program_code_raw,
            CASE c.facility_program_code_raw
                WHEN '14' THEN 'Ambulatory Surgery Center'
                WHEN '23' THEN 'Hospital'
                WHEN '64' THEN 'Cardiac Catheterization Laboratory'
                ELSE 'Unmapped/other program code'
            END AS facility_program_label,
            c.facility_region_code_raw,
            c.facility_county_code_raw,
            COALESCE(
                c.facility_county_name_raw,
                fc.facility_county_name_companion
            ) AS facility_county_name,
            county.county_fips AS facility_county_fips,
            c.service_location_raw,
            CASE
                WHEN {year} < 2010 THEN NULL
                WHEN c.service_location_raw
                    IS NULL THEN FALSE
                WHEN REGEXP_FULL_MATCH(
                    c.service_location_raw, '[A-Z]'
                ) THEN TRUE
                ELSE NULL
            END AS off_site_ed_flag,
            CASE
                WHEN {year} < 2010
                    THEN 'Structurally unavailable before 2010'
                WHEN c.service_location_raw IS NULL
                    THEN 'Main hospital/no off-site code reported'
                WHEN REGEXP_FULL_MATCH(
                    c.service_location_raw, '[A-Z]'
                ) THEN 'AHCA-assigned off-site ED location code'
                ELSE 'Invalid/unmapped service-location value'
            END AS off_site_ed_status,
            c.facility_certification_date_raw,
            fc.reported_ed_visit_count_companion,

            c.sex_raw,
            CASE
                WHEN {year} <= 2008 AND c.sex_raw = '1'
                    THEN 'Male'
                WHEN {year} <= 2008 AND c.sex_raw = '2'
                    THEN 'Female'
                WHEN {year} <= 2008 AND c.sex_raw = '3'
                    THEN 'Unknown'
                WHEN {year} >= 2010 AND c.sex_raw = 'M'
                    THEN 'Male'
                WHEN {year} >= 2010 AND c.sex_raw = 'F'
                    THEN 'Female'
                WHEN {year} >= 2010 AND c.sex_raw = 'U'
                    THEN 'Unknown'
                WHEN c.sex_raw IS NULL THEN 'Missing'
                ELSE 'Unmapped'
            END AS sex_category,
            c.race_raw,
            CASE
                WHEN {year} <= 2008 AND c.race_raw = '1'
                    THEN 'American Indian or Alaska Native'
                WHEN {year} <= 2008 AND c.race_raw = '2'
                    THEN 'Asian'
                WHEN {year} <= 2008 AND c.race_raw IN ('3', '6')
                    THEN 'Black or African American'
                WHEN {year} <= 2008 AND c.race_raw IN ('4', '5')
                    THEN 'White'
                WHEN {year} <= 2008 AND c.race_raw = '7'
                    THEN 'Other'
                WHEN {year} <= 2008 AND c.race_raw = '8'
                    THEN 'No response'
                WHEN {year} >= 2010 AND c.race_raw = '1'
                    THEN 'American Indian or Alaska Native'
                WHEN {year} >= 2010 AND c.race_raw = '2'
                    THEN 'Asian'
                WHEN {year} >= 2010 AND c.race_raw = '3'
                    THEN 'Black or African American'
                WHEN {year} >= 2010 AND c.race_raw = '4'
                    THEN 'Native Hawaiian or Other Pacific Islander'
                WHEN {year} >= 2010 AND c.race_raw = '5'
                    THEN 'White'
                WHEN {year} >= 2010 AND c.race_raw = '6'
                    THEN 'Other'
                WHEN {year} >= 2010 AND c.race_raw = '7'
                    THEN 'Unknown'
                WHEN c.race_raw IS NULL THEN 'Missing'
                ELSE 'Unmapped'
            END AS race_category,
            CASE
                WHEN {year} <= 2008 AND c.race_raw = '5'
                    THEN 'White Hispanic'
                WHEN {year} <= 2008 AND c.race_raw = '6'
                    THEN 'Black Hispanic'
                WHEN {year} <= 2008 AND c.race_raw = '4'
                    THEN 'White (historical combined code)'
                WHEN {year} <= 2008 AND c.race_raw = '8'
                    THEN 'No response'
                WHEN {year} <= 2008
                    THEN 'Historical race/ethnicity code: '
                        || COALESCE(c.race_raw, 'missing')
                ELSE NULL
            END AS race_ethnicity_historical_label,
            c.ethnicity_raw,
            CASE
                WHEN {year} <= 2008 AND c.race_raw IN ('5', '6')
                    THEN 'Hispanic or Latino (from historical combined code)'
                WHEN {year} <= 2008
                    THEN 'Not separately reported/not derivable'
                WHEN c.ethnicity_raw = 'E1'
                    THEN 'Hispanic or Latino'
                WHEN c.ethnicity_raw = 'E2'
                    THEN 'Not Hispanic or Latino'
                WHEN c.ethnicity_raw = 'E7'
                    THEN 'Unknown'
                WHEN c.ethnicity_raw IS NULL THEN 'Missing'
                ELSE 'Unmapped'
            END AS ethnicity_category,

            c.age_raw,
            CASE
                WHEN {year} >= 2018
                    AND c.age_numeric_raw IN (777, 888, 999)
                    THEN NULL
                WHEN c.age_numeric_raw BETWEEN 0 AND 115
                    THEN c.age_numeric_raw
                ELSE NULL
            END AS age_years,
            CASE
                WHEN {year} >= 2018 AND c.age_numeric_raw = 0
                    THEN '0-28 days'
                WHEN {year} >= 2018 AND c.age_numeric_raw = 777
                    THEN '29-364 days'
                WHEN {year} >= 2018 AND c.age_numeric_raw = 888
                    THEN '100 years and older'
                WHEN {year} >= 2018 AND c.age_numeric_raw = 999
                    THEN 'Unknown'
                WHEN c.age_numeric_raw BETWEEN 0 AND 17
                    THEN '0-17'
                WHEN c.age_numeric_raw BETWEEN 18 AND 44
                    THEN '18-44'
                WHEN c.age_numeric_raw BETWEEN 45 AND 64
                    THEN '45-64'
                WHEN c.age_numeric_raw BETWEEN 65 AND 84
                    THEN '65-84'
                WHEN c.age_numeric_raw BETWEEN 85 AND 115
                    THEN '85+'
                WHEN c.age_numeric_raw IS NULL THEN 'Missing'
                ELSE 'Invalid/unmapped'
            END AS age_band,
            CASE
                WHEN {year} >= 2018
                    AND c.age_numeric_raw IN (0, 777) THEN TRUE
                WHEN c.age_numeric_raw BETWEEN 0 AND 12 THEN TRUE
                WHEN c.age_numeric_raw IS NULL
                    OR ({year} >= 2018
                        AND c.age_numeric_raw IN (888, 999))
                    THEN NULL
                ELSE FALSE
            END AS age_0_12_flag,
            CASE
                WHEN c.age_numeric_raw BETWEEN 13 AND 17 THEN TRUE
                WHEN c.age_numeric_raw IS NULL
                    OR ({year} >= 2018
                        AND c.age_numeric_raw IN (777, 888, 999))
                    THEN NULL
                ELSE FALSE
            END AS age_13_17_flag,
            CASE
                WHEN {year} >= 2018
                    AND c.age_numeric_raw IN (0, 777) THEN TRUE
                WHEN c.age_numeric_raw BETWEEN 0 AND 17 THEN TRUE
                WHEN c.age_numeric_raw IS NULL
                    OR ({year} >= 2018
                        AND c.age_numeric_raw IN (888, 999))
                    THEN NULL
                ELSE FALSE
            END AS pediatric_flag,
            CASE
                WHEN c.age_numeric_raw BETWEEN 18 AND 64 THEN TRUE
                WHEN c.age_numeric_raw IS NULL
                    OR ({year} >= 2018
                        AND c.age_numeric_raw IN (777, 888, 999))
                    THEN NULL
                ELSE FALSE
            END AS adult_18_64_flag,
            CASE
                WHEN {year} >= 2018 AND c.age_numeric_raw = 888
                    THEN TRUE
                WHEN c.age_numeric_raw BETWEEN 65 AND 115
                    THEN TRUE
                WHEN c.age_numeric_raw IS NULL
                    OR ({year} >= 2018
                        AND c.age_numeric_raw IN (777, 999))
                    THEN NULL
                ELSE FALSE
            END AS older_adult_65plus_flag,

            c.weekday_raw,
            CASE c.weekday_raw
                WHEN '1' THEN 'Monday'
                WHEN '2' THEN 'Tuesday'
                WHEN '3' THEN 'Wednesday'
                WHEN '4' THEN 'Thursday'
                WHEN '5' THEN 'Friday'
                WHEN '6' THEN 'Saturday'
                WHEN '7' THEN 'Sunday'
                ELSE 'Unmapped/missing'
            END AS weekday_label,
            CASE
                WHEN c.weekday_raw IN ('6', '7') THEN TRUE
                WHEN c.weekday_raw BETWEEN '1' AND '5' THEN FALSE
                ELSE NULL
            END AS weekend_flag,
            c.arrival_hour_raw,
            CASE
                WHEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                    BETWEEN 0 AND 23
                    THEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                ELSE NULL
            END AS arrival_hour,
            CASE
                WHEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                    BETWEEN 6 AND 11 THEN 'Morning'
                WHEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                    BETWEEN 12 AND 17 THEN 'Afternoon'
                WHEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                    BETWEEN 18 AND 23 THEN 'Evening'
                WHEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                    BETWEEN 0 AND 5 THEN 'Night'
                ELSE 'Unknown'
            END AS arrival_time_band,
            CASE
                WHEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                    BETWEEN 0 AND 6 THEN TRUE
                WHEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                    BETWEEN 18 AND 23 THEN TRUE
                WHEN TRY_CAST(c.arrival_hour_raw AS INTEGER)
                    BETWEEN 7 AND 17 THEN FALSE
                ELSE NULL
            END AS off_hours_flag,
            c.ed_discharge_hour_raw,
            c.length_of_stay_days_raw,
            c.length_of_stay_days,

            c.patient_zip_raw,
            CASE
                WHEN REGEXP_FULL_MATCH(
                    c.patient_zip_raw, '[0-9]{{5}}'
                ) THEN c.patient_zip_raw
                ELSE NULL
            END AS patient_zip5,
            c.patient_county_code_raw,
            c.patient_county_name_raw,
            c.patient_state_raw,
            c.patient_country_raw,
            z.city AS patient_zip_city,
            z.county_name AS patient_zip_county_name,
            z.county_fips AS patient_zip_county_fips,
            z.lat AS patient_zip_centroid_latitude,
            z.lng AS patient_zip_centroid_longitude,
            r.primaryruca AS patient_zip_ruca_primary,
            r.secondaryruca AS patient_zip_ruca_secondary,
            CASE
                WHEN TRY_CAST(r.primaryruca AS DOUBLE)
                    BETWEEN 1 AND 3 THEN 'Metropolitan'
                WHEN TRY_CAST(r.primaryruca AS DOUBLE)
                    BETWEEN 4 AND 6 THEN 'Micropolitan'
                WHEN TRY_CAST(r.primaryruca AS DOUBLE)
                    BETWEEN 7 AND 10 THEN 'Small town/rural'
                ELSE NULL
            END AS patient_zip_rurality_3level,
            '2020 RUCA ZIP approximation; primary RUCA 1-3 '
                || 'metropolitan, 4-6 micropolitan, 7-10 '
                || 'small town/rural'
                AS patient_zip_ruca_version_rule,

            c.admission_source_raw,
            CASE c.admission_source_raw
                WHEN '01' THEN 'Non-health care facility/home/workplace'
                WHEN '02' THEN 'Clinic or physician office'
                WHEN '04' THEN 'Transfer from a different hospital'
                WHEN '05' THEN 'Transfer from SNF or ICF'
                WHEN '06' THEN 'Transfer from another health care facility'
                WHEN '07' THEN
                    CASE
                        WHEN {year} = 2010
                            THEN 'Emergency room (discontinued 2011-01-01)'
                        ELSE 'Legacy code 07 outside documented validity'
                    END
                WHEN '08' THEN 'Court/law enforcement'
                WHEN '09' THEN 'Information not available'
                WHEN 'D' THEN 'Transfer within same hospital distinct unit'
                WHEN 'E' THEN 'Transfer from ambulatory surgery center'
                WHEN 'F' THEN 'Transfer from hospice'
                WHEN '00' THEN 'Zero-filled/unmapped'
                WHEN NULL THEN 'Structurally unavailable/missing'
                ELSE 'Unmapped'
            END AS admission_source_label,
            c.patient_status_raw,
            CASE
                WHEN c.patient_status_raw = '01'
                    THEN 'Routine discharge/home'
                WHEN c.patient_status_raw = '06'
                    THEN 'Home health'
                WHEN c.patient_status_raw IN (
                    '02','03','04','05','62','63','64',
                    '65','66','70'
                ) THEN 'Transfer'
                WHEN c.patient_status_raw = '07'
                    THEN 'Left/discontinued care'
                WHEN c.patient_status_raw = '20'
                    THEN 'Expired'
                WHEN c.patient_status_raw = '21'
                    THEN 'Court/law enforcement'
                WHEN c.patient_status_raw IN ('50','51')
                    THEN 'Hospice'
                WHEN c.patient_status_raw IS NULL THEN 'Missing'
                ELSE 'Unmapped/legacy'
            END AS disposition_group,
            c.patient_status_raw = '01'
                AS routine_discharge_flag,
            c.patient_status_raw IN (
                '02','03','04','05','62','63','64',
                '65','66','70'
            ) AS transfer_flag,
            c.patient_status_raw IN ('50','51')
                AS hospice_flag,
            c.patient_status_raw = '20' AS mortality_flag,
            c.patient_status_raw = '21'
                AS court_law_enforcement_flag,
            c.patient_status_raw = '07'
                AS left_discontinued_care_flag,
            CAST(NULL AS BOOLEAN)
                AS same_facility_inpatient_admission_flag,
            'Deferred: this ED release excludes visits admitted '
                || 'to the same hospital and has no admission outcome'
                AS same_facility_admission_status,
            CAST(NULL AS BOOLEAN) AS revisit_7d_flag,
            CAST(NULL AS BOOLEAN) AS revisit_30d_flag,
            'Deferred: no stable patient identifier or exact '
                || 'service date in supplied release'
                AS revisit_measure_status,
            CAST(NULL AS VARCHAR) AS clinical_triage_level,
            'Unavailable; E/M acuity proxy retained separately'
                AS clinical_triage_status,

            c.payer_raw,
            c.payer_name_raw,
            CASE
                WHEN c.payer_raw = 'A' THEN 'Medicare'
                WHEN c.payer_raw = 'B' AND {year} <= 2008
                    THEN 'Medicare HMO/PPO'
                WHEN c.payer_raw = 'B'
                    THEN 'Medicare Managed Care'
                WHEN c.payer_raw = 'C' THEN 'Medicaid'
                WHEN c.payer_raw = 'D' AND {year} <= 2008
                    THEN 'Medicaid HMO'
                WHEN c.payer_raw = 'D'
                    THEN 'Medicaid Managed Care'
                WHEN c.payer_raw = 'E' AND {year} <= 2008
                    THEN 'Commercial insurance'
                WHEN c.payer_raw = 'F' AND {year} <= 2008
                    THEN 'Commercial HMO'
                WHEN c.payer_raw = 'G' AND {year} <= 2008
                    THEN 'Commercial PPO'
                WHEN c.payer_raw = 'E'
                    THEN 'Commercial health insurance'
                WHEN c.payer_raw = 'H' THEN 'Workers Compensation'
                WHEN c.payer_raw = 'I' AND {year} <= 2008
                    THEN 'CHAMPUS'
                WHEN c.payer_raw = 'I'
                    THEN 'TRICARE/other federal government'
                WHEN c.payer_raw = 'J' THEN 'VA'
                WHEN c.payer_raw = 'K'
                    THEN 'Other state/local government'
                WHEN c.payer_raw = 'L' AND {year} <= 2008
                    THEN 'Self pay/under-insured'
                WHEN c.payer_raw = 'L' THEN 'Self pay'
                WHEN c.payer_raw = 'M' THEN 'Other'
                WHEN c.payer_raw = 'N' AND {year} <= 2008
                    THEN 'Charity'
                WHEN c.payer_raw = 'N' THEN 'Non-payment'
                WHEN c.payer_raw = 'O' THEN 'KidCare'
                WHEN c.payer_raw = 'P' THEN 'Unknown'
                WHEN c.payer_raw = 'Q'
                    THEN 'Commercial liability coverage'
                WHEN c.payer_raw IS NULL THEN 'Missing'
                ELSE 'Unmapped'
            END AS payer_label,
            CASE
                WHEN c.payer_raw IN ('A','B') THEN 'Medicare'
                WHEN c.payer_raw IN ('C','D') THEN 'Medicaid'
                WHEN c.payer_raw IN ('E','F','G') THEN 'Commercial'
                WHEN c.payer_raw = 'L' THEN 'Self-pay'
                WHEN c.payer_raw = 'H' THEN 'Workers compensation'
                WHEN c.payer_raw IN ('I','J') THEN 'Federal government'
                WHEN c.payer_raw IN ('K','O')
                    THEN 'Other government'
                WHEN c.payer_raw = 'Q' THEN 'Liability'
                WHEN c.payer_raw = 'N' THEN 'Non-payment/charity'
                WHEN c.payer_raw = 'P' THEN 'Unknown'
                WHEN c.payer_raw = 'M' THEN 'Other'
                WHEN c.payer_raw IS NULL THEN 'Missing'
                ELSE 'Unmapped'
            END AS payer_group,

            dm.diagnosis_code_count,
            dm.secondary_diagnosis_code_count,
            dm.external_cause_code_count,
            dm.distinct_default_clinical_group_count,
            dm.principal_diagnosis_code_norm,
            dm.principal_diagnosis_description,
            dm.principal_clinical_category,
            dm.principal_clinical_category_label,
            dm.principal_diagnosis_mapped_flag,
            pm.cpt_hcpcs_count,
            pm.evaluation_management_code_count,
            pm.icd_procedure_count,
            pm.distinct_procedure_group_count,
            pm.procedure_count_analysis,
            pm.procedure_count_scope,
            pm.high_procedure_threshold,
            pm.any_procedure_flag,
            pm.high_procedure_flag,
            CASE WHEN {year} >= 2010
                THEN pm.em_acuity_proxy_level
                ELSE NULL
            END AS em_acuity_proxy_level,
            CASE WHEN {year} >= 2010
                THEN pm.em_critical_care_flag
                ELSE NULL
            END AS em_critical_care_flag,
            CASE WHEN {year} >= 2010
                THEN pm.em_special_emergency_code_flag
                ELSE NULL
            END AS em_special_emergency_code_flag,
            CASE WHEN {year} >= 2010
                THEN pm.em_nonbillable_sentinel_flag
                ELSE NULL
            END AS em_nonbillable_sentinel_flag,
            CASE
                WHEN {year} < 2010
                    THEN 'Structurally unavailable before 2010'
                WHEN pm.em_acuity_proxy_level IS NOT NULL
                    THEN 'AHCA E/M acuity proxy; not a clinical triage score'
                WHEN pm.em_nonbillable_sentinel_flag
                    THEN '99999 sentinel: status 07 or zero charges'
                ELSE 'No mapped E/M acuity level'
            END AS em_acuity_proxy_status,

            CASE
                WHEN ({charge_nonmissing}) = 0 THEN NULL
                ELSE ({charge_sum})
            END AS component_charge_sum,
            c.tchgs AS total_charge_reported,
            CASE
                WHEN c.tchgs IS NOT NULL AND c.tchgs >= 0
                    THEN c.tchgs
                WHEN ({charge_nonmissing}) > 0
                    THEN ({charge_sum})
                ELSE NULL
            END AS total_charge,
            CASE
                WHEN c.tchgs IS NOT NULL
                    AND ({charge_nonmissing}) > 0
                    THEN c.tchgs - ({charge_sum})
                ELSE NULL
            END AS charge_reconciliation_difference,
            {charge_tolerance}::UTINYINT
                AS charge_reconciliation_tolerance,
            CASE
                WHEN c.tchgs IS NOT NULL
                    AND ({charge_nonmissing}) > 0
                    THEN ABS(c.tchgs - ({charge_sum}))
                        > {charge_tolerance}
                ELSE NULL
            END AS charge_reconciliation_exception_flag,

            COALESCE(e.elixhauser_condition_count, 0)
                AS elixhauser_condition_count,
            {", ".join(elix_fields)},

            {", ".join(physician_columns)},
            {", ".join(raw_code_columns)},
            {", ".join(raw_charge_columns)}
        FROM core c
        LEFT JOIN ref_facility_companion fc
            ON c.visit_year = fc.visit_year
            AND c.visit_quarter = fc.visit_quarter
            AND c.facility_ahca_id = fc.facility_ahca_id
        LEFT JOIN ref_county_normalized county
            ON REGEXP_REPLACE(
                UPPER(
                    COALESCE(
                        c.facility_county_name_raw,
                        fc.facility_county_name_companion
                    )
                ),
                '[^A-Z0-9]',
                '',
                'g'
            ) = county.county_name_norm
        LEFT JOIN ref_zip z
            ON c.patient_zip_raw = z.zip5
        LEFT JOIN ref_ruca r
            ON c.patient_zip_raw = r.zip5
        LEFT JOIN diagnosis_metrics dm USING (visit_key)
        LEFT JOIN procedure_metrics pm USING (visit_key)
        LEFT JOIN elixhauser_metrics e USING (visit_key)
        LEFT JOIN practitioner_role_wide pr USING (visit_key)
    ),
    threshold AS (
        SELECT
            QUANTILE_CONT(total_charge, 0.90)
                AS high_cost_threshold
        FROM base
        WHERE total_charge IS NOT NULL
    )
    SELECT
        base.*,
        CASE
            WHEN total_charge IS NOT NULL AND total_charge >= 0
                THEN LN(1 + total_charge)
            ELSE NULL
        END AS log1p_total_charge,
        threshold.high_cost_threshold,
        CASE
            WHEN total_charge IS NULL THEN NULL
            ELSE total_charge >= threshold.high_cost_threshold
        END AS high_cost_flag,
        'Quarter-specific 90th percentile of validated total charge'
            AS high_cost_threshold_definition
    FROM base
    CROSS JOIN threshold
    """


def build_quarter(
    year: int,
    quarter: int,
    force: bool = False,
    memory_limit_gb: int = 12,
    threads: int = 6,
) -> dict[str, object]:
    success_path = output_path(
        "fact_ed_visits", year, quarter, "_SUCCESS.json"
    )
    if success_path.exists() and not force:
        return {
            "year": year,
            "quarter": quarter,
            "status": "Skipped complete partition",
            "success_path": str(success_path),
        }
    folder = DATASET_ROOT / f"{year % 100:02d}Q{quarter}ED"
    raw_files = sorted(folder.glob("*_ED.csv"))
    if len(raw_files) != 1:
        raise RuntimeError(
            f"Expected one raw ED CSV in {folder}; found {raw_files}"
        )
    raw_file = raw_files[0]
    columns = read_header(raw_file)
    approved_schema = schema_id(columns)
    start = time.time()
    connection = duckdb.connect()
    connection.create_function(
        "npi_is_valid",
        valid_npi,
        ["VARCHAR"],
        "BOOLEAN",
        null_handling="special",
    )
    connection.execute(f"SET threads = {threads}")
    connection.execute("SET preserve_insertion_order = false")
    connection.execute(
        f"SET memory_limit = '{memory_limit_gb}GB'"
    )
    quarter_tmp = TMP_ROOT / f"{year}Q{quarter}"
    quarter_tmp.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"SET temp_directory = '{sql_path(quarter_tmp)}'"
    )
    create_reference_views(connection)
    create_core_table(
        connection,
        raw_file,
        year,
        quarter,
        columns,
        approved_schema,
    )
    raw_count = connection.execute(
        "SELECT COUNT(*) FROM raw_source"
    ).fetchone()[0]
    ed_count = connection.execute(
        "SELECT COUNT(*) FROM core"
    ).fetchone()[0]
    distinct_source_ids = connection.execute(
        """
        SELECT COUNT(DISTINCT source_record_id)
        FROM core
        """
    ).fetchone()[0]
    duplicate_rows = connection.execute(
        """
        SELECT COUNT(*)
        FROM core
        WHERE source_record_duplicate_flag
        """
    ).fetchone()[0]
    icd9_conditions, icd10_conditions = create_diagnosis_tables(
        connection, year, quarter
    )
    create_procedure_tables(connection, year, quarter)
    create_physician_linkage(connection, year)
    fact_query = build_fact_query(
        year, quarter, icd9_conditions, icd10_conditions
    )
    fact_path = output_path(
        "fact_ed_visits", year, quarter, "ed_visits.parquet"
    )
    copy_query(connection, fact_query, fact_path)
    output_fact_count = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{sql_path(fact_path)}')
        """
    ).fetchone()[0]
    diagnosis_count = connection.execute(
        "SELECT COUNT(*) FROM diagnosis_enriched"
    ).fetchone()[0]
    procedure_count = connection.execute(
        "SELECT COUNT(*) FROM procedure_enriched"
    ).fetchone()[0]
    physician_linkage = connection.execute(
        """
        SELECT
            practitioner_role,
            selection_method,
            COUNT(*) AS records
        FROM practitioner_role_linked
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).fetchdf().to_dict("records")
    elapsed = time.time() - start
    manifest = {
        "year": year,
        "quarter": quarter,
        "status": "Complete",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "source_file": str(raw_file),
        "source_sha256": sha256_file(raw_file),
        "approved_schema": approved_schema,
        "source_column_count": len(columns),
        "source_row_count_all_service_types": raw_count,
        "source_ed_row_count_type_service_2": ed_count,
        "output_fact_row_count": output_fact_count,
        "distinct_source_record_ids": distinct_source_ids,
        "source_duplicate_rows": duplicate_rows,
        "visit_diagnosis_rows": diagnosis_count,
        "visit_procedure_rows": procedure_count,
        "physician_linkage_counts": physician_linkage,
        "fact_file": str(fact_path),
        "fact_file_sha256": sha256_file(fact_path),
        "reconciliation_passed": ed_count == output_fact_count,
    }
    connection.close()
    if ed_count != output_fact_count:
        raise RuntimeError(
            f"Fact count mismatch for {year} Q{quarter}: "
            f"{ed_count} vs {output_fact_count}"
        )
    success_path.parent.mkdir(parents=True, exist_ok=True)
    success_path.write_text(
        json.dumps(manifest, indent=2, default=str),
        encoding="utf-8",
    )
    failure_path = output_path(
        "fact_ed_visits", year, quarter, "_FAILED.json"
    )
    if failure_path.exists():
        failure_path.unlink()
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build standardized Florida ED Parquet partitions and "
            "diagnosis/procedure bridges."
        )
    )
    parser.add_argument(
        "--years",
        nargs="*",
        type=int,
        default=IN_SCOPE_YEARS,
    )
    parser.add_argument(
        "--quarters",
        nargs="*",
        type=int,
        default=[1, 2, 3, 4],
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--status-tag",
        default="main",
        help="Suffix for this process's run-status files.",
    )
    parser.add_argument(
        "--memory-limit-gb",
        type=int,
        default=12,
        help="DuckDB memory limit for this worker.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=6,
        help="DuckDB worker threads for this process.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    invalid_years = sorted(set(args.years) - set(IN_SCOPE_YEARS))
    if invalid_years:
        raise ValueError(
            f"Years outside authorized scope requested: {invalid_years}"
        )
    invalid_quarters = sorted(
        set(args.quarters) - {1, 2, 3, 4}
    )
    if invalid_quarters:
        raise ValueError(f"Invalid quarters: {invalid_quarters}")
    if args.memory_limit_gb < 4:
        raise ValueError("--memory-limit-gb must be at least 4")
    if args.threads < 1:
        raise ValueError("--threads must be at least 1")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    status_tag = re.sub(
        r"[^A-Za-z0-9_-]", "_", str(args.status_tag)
    )
    status_json = (
        OUTPUT_ROOT / "qa" / f"build_run_status_{status_tag}.json"
    )
    status_csv = (
        OUTPUT_ROOT / "qa" / f"build_run_status_{status_tag}.csv"
    )
    audit_rows = []
    for year in args.years:
        for quarter in args.quarters:
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] "
                f"Building {year} Q{quarter}",
                flush=True,
            )
            try:
                result = build_quarter(
                    year,
                    quarter,
                    force=args.force,
                    memory_limit_gb=args.memory_limit_gb,
                    threads=args.threads,
                )
                audit_rows.append(result)
                print(
                    json.dumps(result, indent=2, default=str),
                    flush=True,
                )
            except Exception as exc:
                failure = {
                    "year": year,
                    "quarter": quarter,
                    "status": "Failed",
                    "error": repr(exc),
                    "failed_utc": datetime.now(timezone.utc).isoformat(),
                }
                audit_rows.append(failure)
                failure_path = output_path(
                    "fact_ed_visits",
                    year,
                    quarter,
                    "_FAILED.json",
                )
                failure_path.parent.mkdir(parents=True, exist_ok=True)
                failure_path.write_text(
                    json.dumps(failure, indent=2),
                    encoding="utf-8",
                )
                pd.DataFrame(audit_rows).to_json(
                    status_json,
                    orient="records",
                    indent=2,
                )
                raise
    status_frame = pd.DataFrame(audit_rows)
    status_frame.to_json(
        status_json,
        orient="records",
        indent=2,
    )
    status_frame.to_csv(
        status_csv,
        index=False,
    )


if __name__ == "__main__":
    main()
