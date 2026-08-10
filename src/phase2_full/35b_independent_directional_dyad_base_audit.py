#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/35b_independent_directional_dyad_base_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independent fail-closed audit of the directional-dyad derived base.

This script never writes or modifies encounter partitions.  It independently
reconciles every derived partition to the validated provider-v2 cohort and its
sidecars, recomputes all directional eligibility fields, verifies source and
output hashes, and writes only QA artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


YEARS = tuple(range(2010, 2025))
QUARTERS = (1, 2, 3, 4)
BUILD_SPEC_VERSION = "directional_dyad_derived_base_v1_20260726"
RACE_CLASSES = ("white", "black", "hispanic", "asian", "other")
RACE_DISPLAY = {
    "white": "White",
    "black": "Black",
    "hispanic": "Hispanic",
    "asian": "Asian",
    "other": "Other/multiracial",
}
RECORDED_GENDER_SOURCES = (
    "NPPES",
    "NPPES February 2026 current snapshot",
    "CMS Doctors and Clinicians",
    "CMS Doctors and Clinicians June 2026 current snapshot",
)
KEYS = ("visit_key", "visit_year", "visit_quarter")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def describe(con: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, str]]:
    return [
        (str(row[0]), str(row[1]))
        for row in con.execute(
            f"""
            DESCRIBE SELECT *
            FROM read_parquet(
                {quote(qpath(path))},
                hive_partitioning=false
            )
            """
        ).fetchall()
    ]


def patient_group_expression(prefix: str = "o") -> str:
    return f"""
        CASE
          WHEN {prefix}.patient_ethnicity_category = 'Hispanic or Latino'
            THEN 'Hispanic'
          WHEN {prefix}.patient_ethnicity_category = 'Not Hispanic or Latino'
           AND {prefix}.patient_race_category = 'White'
            THEN 'White'
          WHEN {prefix}.patient_ethnicity_category = 'Not Hispanic or Latino'
           AND {prefix}.patient_race_category = 'Black or African American'
            THEN 'Black'
          WHEN {prefix}.patient_ethnicity_category = 'Not Hispanic or Latino'
           AND {prefix}.patient_race_category = 'Asian'
            THEN 'Asian'
          WHEN {prefix}.patient_ethnicity_category = 'Not Hispanic or Latino'
           AND {prefix}.patient_race_category IN (
               'American Indian or Alaska Native',
               'Native Hawaiian or Other Pacific Islander',
               'Other'
           )
            THEN 'Other/multiracial'
          ELSE NULL
        END
    """


def population_label_expression(prefix: str = "o") -> str:
    cases: list[str] = []
    for race in RACE_CLASSES:
        column = f"{prefix}.physician_race_population_prob_{race}"
        comparisons = " AND ".join(
            f"{column} >= "
            f"{prefix}.physician_race_population_prob_{other}"
            for other in RACE_CLASSES
            if other != race
        )
        cases.append(
            f"WHEN {comparisons} THEN {quote(RACE_DISPLAY[race])}"
        )
    return "CASE " + " ".join(cases) + " ELSE NULL END"


def mismatch_or(
    output_alias: str,
    source_alias: str,
    columns: list[str],
) -> str:
    if not columns:
        return "false"
    return " OR ".join(
        f"{output_alias}.{ident(column)} IS DISTINCT FROM "
        f"{source_alias}.{ident(column)}"
        for column in columns
    )


def require_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected object JSON: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="20GB")
    parser.add_argument("--temp", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    temp = args.temp.resolve()
    temp.mkdir(parents=True, exist_ok=True)
    qa_root = phase2 / "qa"
    output_root = phase2 / "analysis_data" / "directional_dyad_base"
    source_root = (
        phase2 / "analysis_data" / "concordance_visit_data_provider_v2"
    )
    discretion_root = phase2 / "analysis_data" / "discretion_outcomes"

    binding_paths = {
        "extension_manifest_sha256": (
            phase2
            / "documentation"
            / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
        ),
        "extension_gate_sha256": (
            phase2
            / "qa"
            / "directional_dyad_extension_pre_estimation_gate.json"
        ),
        "provider_gate_sha256": (
            phase2 / "qa" / "pre_estimation_measurement_gate.json"
        ),
        "cohort_gate_sha256": (
            phase2 / "qa" / "cohort_validation_report.json"
        ),
        "provider_master_sha256": (
            phase2
            / "analysis_data"
            / "dimensions"
            / "provider_master_v2.parquet"
        ),
    }
    for path in binding_paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    binding = {key: sha256(path) for key, path in binding_paths.items()}

    extension_gate = require_json(
        binding_paths["extension_gate_sha256"]
    )
    provider_gate = require_json(binding_paths["provider_gate_sha256"])
    cohort_gate = require_json(binding_paths["cohort_gate_sha256"])
    if (
        extension_gate.get("status") != "PASS"
        or not extension_gate.get("estimation_authorized")
        or provider_gate.get("status") != "PASS"
        or cohort_gate.get("status") != "PASS"
    ):
        raise RuntimeError("Required pre-estimation gate is not PASS.")

    global_manifest_path = output_root / "directional_dyad_base_manifest.json"
    global_manifest = require_json(global_manifest_path)
    global_parts = {
        (int(row["visit_year"]), int(row["visit_quarter"])): row
        for row in global_manifest.get("partition_manifests", [])
    }
    expected_pairs = {(y, q) for y in YEARS for q in QUARTERS}
    if set(global_parts) != expected_pairs:
        raise RuntimeError("Global manifest partition grid is incomplete.")

    con = duckdb.connect()
    con.execute(f"SET threads={int(args.threads)}")
    con.execute(f"SET memory_limit={quote(args.memory_limit)}")
    con.execute(f"SET temp_directory={quote(qpath(temp))}")
    con.execute("SET preserve_insertion_order=false")

    partition_rows: list[dict[str, Any]] = []
    baseline_schema: list[tuple[str, str]] | None = None
    baseline_expected_schema: list[tuple[str, str]] | None = None

    sources_sql = ", ".join(
        quote(value) for value in RECORDED_GENDER_SOURCES
    )
    patient_group = patient_group_expression("o")
    population_label = population_label_expression("o")
    primary_sum = " + ".join(
        f"o.physician_race_proxy_prob_{race}" for race in RACE_CLASSES
    )
    population_sum = " + ".join(
        f"o.physician_race_population_prob_{race}"
        for race in RACE_CLASSES
    )
    population_confidence = "greatest(" + ", ".join(
        f"o.physician_race_population_prob_{race}"
        for race in RACE_CLASSES
    ) + ")"
    primary_confidence = "greatest(" + ", ".join(
        f"o.physician_race_proxy_prob_{race}" for race in RACE_CLASSES
    ) + ")"
    complete_primary_vector = " AND ".join(
        f"o.physician_race_proxy_prob_{race} IS NOT NULL"
        for race in RACE_CLASSES
    )
    complete_population_vector = " AND ".join(
        f"o.physician_race_population_prob_{race} IS NOT NULL"
        for race in RACE_CLASSES
    )
    primary_bounds_error = " OR ".join(
        f"o.physician_race_proxy_prob_{race} NOT BETWEEN 0 AND 1"
        for race in RACE_CLASSES
    )
    population_bounds_error = " OR ".join(
        f"o.physician_race_population_prob_{race} NOT BETWEEN 0 AND 1"
        for race in RACE_CLASSES
    )
    hard_labels = (
        "'White', 'Black', 'Hispanic', 'Asian', 'Other/multiracial'"
    )
    gender_expected = f"""
        (
          o.patient_sex_category IN ('Female', 'Male')
          AND o.physician_gender_category IN ('Female', 'Male')
          AND o.physician_gender_source IN ({sources_sql})
        )
    """
    race_probability_expected = f"""
        (
          o.patient_race_ethnicity_5cat IS NOT NULL
          AND o.attending_selected_npi IS NOT NULL
          AND o.physician_md_do_flag
          AND {primary_sum} BETWEEN 0.999999 AND 1.000001
        )
    """
    race_population_probability_expected = f"""
        (
          o.patient_race_ethnicity_5cat IS NOT NULL
          AND o.attending_selected_npi IS NOT NULL
          AND o.physician_md_do_flag
          AND {population_sum} BETWEEN 0.999999 AND 1.000001
        )
    """

    derived_types = [
        ("physician_gender_source_conflict_flag", "BOOLEAN"),
        ("patient_race_ethnicity_5cat", "VARCHAR"),
        ("physician_race_population_label", "VARCHAR"),
        ("physician_race_population_confidence", "DOUBLE"),
        ("directional_gender_eligible", "BOOLEAN"),
        ("directional_race_probability_eligible", "BOOLEAN"),
        ("directional_race_population_probability_eligible", "BOOLEAN"),
        ("directional_race_hard_t50_eligible", "BOOLEAN"),
        ("directional_race_hard_t70_eligible", "BOOLEAN"),
        ("directional_race_hard_t80_eligible", "BOOLEAN"),
        ("directional_race_hard_t90_eligible", "BOOLEAN"),
        ("directional_race_population_hard_t50_eligible", "BOOLEAN"),
        ("directional_intersectional_probability_eligible", "BOOLEAN"),
        ("directional_intersectional_hard_t50_eligible", "BOOLEAN"),
    ]

    for index, (year, quarter) in enumerate(sorted(expected_pairs), start=1):
        source_part = (
            source_root
            / f"visit_year={year}"
            / f"visit_quarter={quarter}"
        )
        core = source_part / "concordance_visit_core.parquet"
        risk = source_part / "concordance_elixhauser_flags.parquet"
        charge = source_part / "concordance_charge_components.parquet"
        source_success_path = source_part / "_SUCCESS.json"
        discretion_part = (
            discretion_root
            / f"visit_year={year}"
            / f"visit_quarter={quarter}"
        )
        discretion = (
            discretion_part / "visit_discretion_outcomes.parquet"
        )
        discretion_success_path = discretion_part / "_SUCCESS.json"
        out_part = (
            output_root
            / f"visit_year={year}"
            / f"visit_quarter={quarter}"
        )
        output = out_part / "directional_dyad_base.parquet"
        success_path = out_part / "_SUCCESS.json"
        required = [
            core,
            risk,
            charge,
            source_success_path,
            discretion,
            discretion_success_path,
            output,
            success_path,
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"Missing files for {year} Q{quarter}: {missing}"
            )

        source_success = require_json(source_success_path)
        discretion_success = require_json(discretion_success_path)
        success = require_json(success_path)
        global_part = global_parts[(year, quarter)]
        file_map = {
            row["name"]: row for row in source_success.get("files", [])
        }

        output_hash = sha256(output)
        source_hashes_pass = all(
            file_map.get(path.name, {}).get("sha256") == sha256(path)
            for path in (core, risk, charge)
        ) and discretion_success.get("sha256") == sha256(discretion)
        binding_pass = all(
            success.get(key) == value for key, value in binding.items()
        )
        manifest_pass = (
            success.get("status") == "PASS"
            and success.get("build_spec_version") == BUILD_SPEC_VERSION
            and int(success.get("visit_year", -1)) == year
            and int(success.get("visit_quarter", -1)) == quarter
            and success.get("source_success_sha256")
            == sha256(source_success_path)
            and success.get("discretion_success_sha256")
            == sha256(discretion_success_path)
            and success.get("output_sha256") == output_hash
            and int(success.get("output_bytes", -1))
            == output.stat().st_size
            and success.get("phase1_modified") is False
            and success.get("phase2_cohort_modified") is False
            and success.get("encounters_filtered") is False
            and global_part.get("output_sha256") == output_hash
            and int(global_part.get("output_rows", -1))
            == int(success.get("output_rows", -2))
        )

        output_schema = describe(con, output)
        core_schema = describe(con, core)
        risk_schema = describe(con, risk)
        charge_schema = describe(con, charge)
        discretion_schema = describe(con, discretion)
        expected_schema = (
            core_schema
            + [row for row in risk_schema if row[0] not in KEYS]
            + [row for row in charge_schema if row[0] not in KEYS]
            + [row for row in discretion_schema if row[0] not in KEYS]
            + derived_types
        )
        if baseline_schema is None:
            baseline_schema = output_schema
            baseline_expected_schema = expected_schema
        schema_matches_expected = output_schema == expected_schema
        schema_matches_all_partitions = output_schema == baseline_schema

        output_sql = (
            f"read_parquet({quote(qpath(output))}, "
            "hive_partitioning=false)"
        )
        core_sql = (
            f"read_parquet({quote(qpath(core))}, "
            "hive_partitioning=false)"
        )
        risk_sql = (
            f"read_parquet({quote(qpath(risk))}, "
            "hive_partitioning=false)"
        )
        charge_sql = (
            f"read_parquet({quote(qpath(charge))}, "
            "hive_partitioning=false)"
        )
        discretion_sql = (
            f"read_parquet({quote(qpath(discretion))}, "
            "hive_partitioning=false)"
        )

        key_qa = con.execute(
            f"""
            WITH o AS (
              SELECT visit_key, visit_year, visit_quarter
              FROM {output_sql}
            ),
            c AS (
              SELECT visit_key, visit_year, visit_quarter
              FROM {core_sql}
            ),
            missing_in_output AS (
              SELECT * FROM c EXCEPT SELECT * FROM o
            ),
            extra_in_output AS (
              SELECT * FROM o EXCEPT SELECT * FROM c
            )
            SELECT
              (SELECT count(*) FROM o) AS output_rows,
              (SELECT count(DISTINCT visit_key) FROM o)
                AS output_distinct_visit_keys,
              (SELECT count(*) FROM o WHERE visit_key IS NULL)
                AS output_null_visit_keys,
              (SELECT count(*) FROM c) AS source_rows,
              (SELECT count(DISTINCT visit_key) FROM c)
                AS source_distinct_visit_keys,
              (SELECT count(*) FROM missing_in_output)
                AS missing_in_output,
              (SELECT count(*) FROM extra_in_output)
                AS extra_in_output,
              (SELECT count(*) FROM o
                WHERE visit_year <> {year}
                   OR visit_quarter <> {quarter})
                AS partition_value_errors
            """
        ).fetchone()

        core_columns = [row[0] for row in core_schema if row[0] not in KEYS]
        risk_columns = [row[0] for row in risk_schema if row[0] not in KEYS]
        charge_columns = [
            row[0] for row in charge_schema if row[0] not in KEYS
        ]
        discretion_columns = [
            row[0] for row in discretion_schema if row[0] not in KEYS
        ]
        source_field_qa = con.execute(
            f"""
            SELECT
              count(*) AS joined_rows,
              count(*) FILTER (
                WHERE {mismatch_or("o", "c", core_columns)}
              ) AS core_field_mismatch_rows,
              count(*) FILTER (
                WHERE {mismatch_or("o", "r", risk_columns)}
              ) AS risk_field_mismatch_rows,
              count(*) FILTER (
                WHERE {mismatch_or("o", "ch", charge_columns)}
              ) AS charge_field_mismatch_rows,
              count(*) FILTER (
                WHERE {mismatch_or("o", "d", discretion_columns)}
              ) AS discretion_field_mismatch_rows
            FROM {output_sql} o
            INNER JOIN {core_sql} c USING (
              visit_key, visit_year, visit_quarter
            )
            INNER JOIN {risk_sql} r USING (
              visit_key, visit_year, visit_quarter
            )
            INNER JOIN {charge_sql} ch USING (
              visit_key, visit_year, visit_quarter
            )
            INNER JOIN {discretion_sql} d USING (
              visit_key, visit_year, visit_quarter
            )
            """
        ).fetchone()

        derived_qa = con.execute(
            f"""
            SELECT
              count(*) FILTER (
                WHERE o.patient_race_ethnicity_5cat
                      IS DISTINCT FROM ({patient_group})
              ) AS patient_group_mismatch,
              count(*) FILTER (
                WHERE o.physician_race_population_label
                      IS DISTINCT FROM ({population_label})
              ) AS population_label_mismatch,
              count(*) FILTER (
                WHERE o.physician_race_population_confidence
                      IS DISTINCT FROM ({population_confidence})
              ) AS population_confidence_mismatch,
              count(*) FILTER (
                WHERE o.directional_gender_eligible
                      IS DISTINCT FROM ({gender_expected})
              ) AS gender_eligible_mismatch,
              count(*) FILTER (
                WHERE o.directional_race_probability_eligible
                      IS DISTINCT FROM ({race_probability_expected})
              ) AS race_probability_mismatch,
              count(*) FILTER (
                WHERE o.directional_race_population_probability_eligible
                      IS DISTINCT FROM
                      ({race_population_probability_expected})
              ) AS race_population_probability_mismatch,
              count(*) FILTER (
                WHERE o.directional_race_hard_t50_eligible
                      IS DISTINCT FROM (
                        o.patient_race_ethnicity_5cat IS NOT NULL
                        AND o.physician_race_proxy_primary_label
                            IN ({hard_labels})
                        AND o.physician_race_imputation_confidence >= 0.50
                      )
              ) AS hard_t50_mismatch,
              count(*) FILTER (
                WHERE o.directional_race_hard_t70_eligible
                      IS DISTINCT FROM (
                        o.patient_race_ethnicity_5cat IS NOT NULL
                        AND o.physician_race_proxy_primary_label
                            IN ({hard_labels})
                        AND o.physician_race_imputation_confidence >= 0.70
                      )
              ) AS hard_t70_mismatch,
              count(*) FILTER (
                WHERE o.directional_race_hard_t80_eligible
                      IS DISTINCT FROM (
                        o.patient_race_ethnicity_5cat IS NOT NULL
                        AND o.physician_race_proxy_primary_label
                            IN ({hard_labels})
                        AND o.physician_race_imputation_confidence >= 0.80
                      )
              ) AS hard_t80_mismatch,
              count(*) FILTER (
                WHERE o.directional_race_hard_t90_eligible
                      IS DISTINCT FROM (
                        o.patient_race_ethnicity_5cat IS NOT NULL
                        AND o.physician_race_proxy_primary_label
                            IN ({hard_labels})
                        AND o.physician_race_imputation_confidence >= 0.90
                      )
              ) AS hard_t90_mismatch,
              count(*) FILTER (
                WHERE o.directional_race_population_hard_t50_eligible
                      IS DISTINCT FROM (
                        o.patient_race_ethnicity_5cat IS NOT NULL
                        AND o.physician_race_population_label
                            IN ({hard_labels})
                        AND o.physician_race_population_confidence >= 0.50
                      )
              ) AS population_hard_t50_mismatch,
              count(*) FILTER (
                WHERE o.directional_intersectional_probability_eligible
                      IS DISTINCT FROM (
                        {gender_expected}
                        AND o.patient_race_ethnicity_5cat IS NOT NULL
                        AND {primary_sum} BETWEEN 0.999999 AND 1.000001
                      )
              ) AS intersectional_probability_mismatch,
              count(*) FILTER (
                WHERE o.directional_intersectional_hard_t50_eligible
                      IS DISTINCT FROM (
                        {gender_expected}
                        AND o.patient_race_ethnicity_5cat IS NOT NULL
                        AND o.physician_race_proxy_primary_label
                            IN ({hard_labels})
                        AND o.physician_race_imputation_confidence >= 0.50
                      )
              ) AS intersectional_hard_t50_mismatch,
              count(*) FILTER (
                WHERE ({complete_primary_vector})
                  AND abs(({primary_sum}) - 1.0) > 0.000001
              ) AS primary_probability_sum_errors,
              count(*) FILTER (
                WHERE ({complete_population_vector})
                  AND abs(({population_sum}) - 1.0) > 0.000001
              ) AS population_probability_sum_errors,
              count(*) FILTER (
                WHERE {primary_bounds_error}
              ) AS primary_probability_bounds_errors,
              count(*) FILTER (
                WHERE {population_bounds_error}
              ) AS population_probability_bounds_errors,
              count(*) FILTER (
                WHERE ({complete_primary_vector})
                  AND o.physician_race_imputation_confidence
                      IS DISTINCT FROM ({primary_confidence})
              ) AS primary_confidence_mismatch,
              count(*) FILTER (
                WHERE o.directional_race_hard_t90_eligible
                  AND NOT o.directional_race_hard_t80_eligible
              ) + count(*) FILTER (
                WHERE o.directional_race_hard_t80_eligible
                  AND NOT o.directional_race_hard_t70_eligible
              ) + count(*) FILTER (
                WHERE o.directional_race_hard_t70_eligible
                  AND NOT o.directional_race_hard_t50_eligible
              ) AS hard_threshold_monotonicity_errors,
              count(*) FILTER (
                WHERE o.directional_intersectional_probability_eligible
                  AND (
                    NOT o.directional_gender_eligible
                    OR NOT o.directional_race_probability_eligible
                  )
              ) AS intersection_probability_subset_errors,
              count(*) FILTER (
                WHERE o.directional_intersectional_hard_t50_eligible
                  AND (
                    NOT o.directional_gender_eligible
                    OR NOT o.directional_race_hard_t50_eligible
                  )
              ) AS intersection_hard_subset_errors,
              count(*) FILTER (
                WHERE o.directional_gender_eligible
                  AND (
                    o.attending_selected_npi IS NULL
                    OR NOT o.physician_md_do_flag
                    OR o.physician_entity_category <> 'Individual'
                  )
              ) AS gender_eligible_nonphysician_errors,
              count(*) FILTER (
                WHERE o.directional_race_probability_eligible
                  AND (
                    NOT o.physician_md_do_flag
                    OR o.physician_entity_category <> 'Individual'
                  )
              ) AS race_eligible_nonphysician_errors
            FROM {output_sql} o
            """
        ).fetchone()

        conflict_qa = con.execute(
            f"""
            SELECT count(*) FILTER (
              WHERE o.physician_gender_source_conflict_flag
                    IS DISTINCT FROM
                    coalesce(p.gender_conflict_flag_v2, false)
            ) AS conflict_flag_mismatch
            FROM {output_sql} o
            LEFT JOIN read_parquet(
              {quote(qpath(binding_paths["provider_master_sha256"]))},
              hive_partitioning=false
            ) p
              ON o.attending_selected_npi = p.npi
            """
        ).fetchone()

        derived_names = [
            "patient_group_mismatch",
            "population_label_mismatch",
            "population_confidence_mismatch",
            "gender_eligible_mismatch",
            "race_probability_mismatch",
            "race_population_probability_mismatch",
            "hard_t50_mismatch",
            "hard_t70_mismatch",
            "hard_t80_mismatch",
            "hard_t90_mismatch",
            "population_hard_t50_mismatch",
            "intersectional_probability_mismatch",
            "intersectional_hard_t50_mismatch",
            "primary_probability_sum_errors",
            "population_probability_sum_errors",
            "primary_probability_bounds_errors",
            "population_probability_bounds_errors",
            "primary_confidence_mismatch",
            "hard_threshold_monotonicity_errors",
            "intersection_probability_subset_errors",
            "intersection_hard_subset_errors",
            "gender_eligible_nonphysician_errors",
            "race_eligible_nonphysician_errors",
        ]
        derived = dict(zip(derived_names, map(int, derived_qa)))
        row = {
            "visit_year": year,
            "visit_quarter": quarter,
            "status": "PASS",
            "manifest_pass": manifest_pass,
            "source_hashes_pass": source_hashes_pass,
            "binding_pass": binding_pass,
            "schema_matches_expected": schema_matches_expected,
            "schema_matches_all_partitions": schema_matches_all_partitions,
            "output_columns": len(output_schema),
            "output_rows": int(key_qa[0]),
            "output_distinct_visit_keys": int(key_qa[1]),
            "output_null_visit_keys": int(key_qa[2]),
            "source_rows": int(key_qa[3]),
            "source_distinct_visit_keys": int(key_qa[4]),
            "missing_in_output": int(key_qa[5]),
            "extra_in_output": int(key_qa[6]),
            "partition_value_errors": int(key_qa[7]),
            "joined_rows": int(source_field_qa[0]),
            "core_field_mismatch_rows": int(source_field_qa[1]),
            "risk_field_mismatch_rows": int(source_field_qa[2]),
            "charge_field_mismatch_rows": int(source_field_qa[3]),
            "discretion_field_mismatch_rows": int(source_field_qa[4]),
            **derived,
            "conflict_flag_mismatch": int(conflict_qa[0]),
            "output_bytes": output.stat().st_size,
            "output_sha256": output_hash,
        }
        numeric_errors = [
            row[name]
            for name in (
                "output_null_visit_keys",
                "missing_in_output",
                "extra_in_output",
                "partition_value_errors",
                "core_field_mismatch_rows",
                "risk_field_mismatch_rows",
                "charge_field_mismatch_rows",
                "discretion_field_mismatch_rows",
                *derived_names,
                "conflict_flag_mismatch",
            )
        ]
        counts_pass = (
            row["output_rows"]
            == row["output_distinct_visit_keys"]
            == row["source_rows"]
            == row["source_distinct_visit_keys"]
            == row["joined_rows"]
            == int(success["output_rows"])
            == int(success["source_rows"])
        )
        row["counts_pass"] = counts_pass
        row["status"] = (
            "PASS"
            if (
                manifest_pass
                and source_hashes_pass
                and binding_pass
                and schema_matches_expected
                and schema_matches_all_partitions
                and counts_pass
                and all(value == 0 for value in numeric_errors)
            )
            else "FAIL"
        )
        partition_rows.append(row)
        print(
            f"{index:02d}/60 {year} Q{quarter}: {row['status']} "
            f"rows={row['output_rows']:,}",
            flush=True,
        )

    con.close()

    aggregate = {
        "partitions_expected": 60,
        "partitions_audited": len(partition_rows),
        "partitions_passed": sum(
            row["status"] == "PASS" for row in partition_rows
        ),
        "source_rows": sum(row["source_rows"] for row in partition_rows),
        "output_rows": sum(row["output_rows"] for row in partition_rows),
        "distinct_visit_keys_partition_sum": sum(
            row["output_distinct_visit_keys"] for row in partition_rows
        ),
        "all_numeric_error_counts": {
            name: sum(int(row[name]) for row in partition_rows)
            for name in (
                "output_null_visit_keys",
                "missing_in_output",
                "extra_in_output",
                "partition_value_errors",
                "core_field_mismatch_rows",
                "risk_field_mismatch_rows",
                "charge_field_mismatch_rows",
                "discretion_field_mismatch_rows",
                "patient_group_mismatch",
                "population_label_mismatch",
                "population_confidence_mismatch",
                "gender_eligible_mismatch",
                "race_probability_mismatch",
                "race_population_probability_mismatch",
                "hard_t50_mismatch",
                "hard_t70_mismatch",
                "hard_t80_mismatch",
                "hard_t90_mismatch",
                "population_hard_t50_mismatch",
                "intersectional_probability_mismatch",
                "intersectional_hard_t50_mismatch",
                "primary_probability_sum_errors",
                "population_probability_sum_errors",
                "primary_probability_bounds_errors",
                "population_probability_bounds_errors",
                "primary_confidence_mismatch",
                "hard_threshold_monotonicity_errors",
                "intersection_probability_subset_errors",
                "intersection_hard_subset_errors",
                "gender_eligible_nonphysician_errors",
                "race_eligible_nonphysician_errors",
                "conflict_flag_mismatch",
            )
        },
    }
    manifest_binding_pass = (
        global_manifest.get("status") == "PASS"
        and global_manifest.get("build_spec_version") == BUILD_SPEC_VERSION
        and int(global_manifest.get("partitions_expected", -1)) == 60
        and int(global_manifest.get("partitions_passed", -1)) == 60
        and all(
            global_manifest.get(key) == value
            for key, value in binding.items()
        )
        and int(global_manifest.get("source_rows", -1))
        == aggregate["source_rows"]
        and int(global_manifest.get("output_rows", -1))
        == aggregate["output_rows"]
        and int(
            global_manifest.get("distinct_visit_keys_partition_sum", -1)
        )
        == aggregate["distinct_visit_keys_partition_sum"]
    )
    aggregate["global_manifest_binding_pass"] = manifest_binding_pass
    aggregate["phase1_modified"] = False
    aggregate["phase2_cohort_modified"] = False

    overall_pass = (
        aggregate["partitions_audited"] == 60
        and aggregate["partitions_passed"] == 60
        and aggregate["source_rows"]
        == aggregate["output_rows"]
        == aggregate["distinct_visit_keys_partition_sum"]
        == int(cohort_gate["aggregate_counts"]["all_rows"])
        and all(
            value == 0
            for value in aggregate["all_numeric_error_counts"].values()
        )
        and manifest_binding_pass
        and baseline_schema == baseline_expected_schema
    )

    partition_csv = qa_root / "independent_directional_dyad_base_audit.csv"
    fields = list(partition_rows[0])
    atomic_csv(partition_csv, partition_rows, fields)
    payload = {
        "audit_id": "independent_directional_dyad_base_audit_v1",
        "created_utc": utc_now(),
        "status": "PASS" if overall_pass else "FAIL",
        "scope": (
            "All 60 directional derived-base partitions, including exact key "
            "reconciliation, all copied source fields, all derived eligibility "
            "definitions, provider conflict linkage, schema, hashes, and bindings."
        ),
        "source_release_modified": False,
        "phase2_cohort_modified": False,
        "global_manifest": {
            "path": str(global_manifest_path),
            "sha256": sha256(global_manifest_path),
        },
        "bindings": binding,
        "aggregate": aggregate,
        "schema": {
            "column_count": len(baseline_schema or []),
            "matches_expected": baseline_schema == baseline_expected_schema,
            "columns": [
                {"name": name, "type": dtype}
                for name, dtype in (baseline_schema or [])
            ],
        },
        "partition_audit_csv": {
            "path": str(partition_csv),
            "sha256": sha256(partition_csv),
            "rows": len(partition_rows),
        },
    }
    output_json = (
        qa_root / "independent_directional_dyad_base_audit.json"
    )
    atomic_json(output_json, payload)
    print(json.dumps(payload, indent=2), flush=True)
    if not overall_pass:
        raise RuntimeError(
            f"Independent directional-base audit failed: {output_json}"
        )


if __name__ == "__main__":
    main()
