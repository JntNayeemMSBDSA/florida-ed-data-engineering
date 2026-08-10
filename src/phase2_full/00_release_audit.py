#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/00_release_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Read-only feasibility and integrity audit for Phase 2 concordance analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq


SCOPE_YEARS = [2005, 2006, 2007, 2008, *range(2010, 2025)]


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def write_query_csv(con: duckdb.DuckDBPyConnection, sql: str, path: Path) -> None:
    frame = con.execute(sql).fetchdf()
    frame.to_csv(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="20GB")
    args = parser.parse_args()

    release = args.release.resolve()
    output = args.output.resolve()
    temp = args.temp.resolve()
    output.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)

    fact_root = release / "fact_ed_visits"
    fact_glob = str(fact_root / "visit_year=*" / "visit_quarter=*" / "ed_visits.parquet")
    physician_path = release / "dimensions" / "physician_master.parquet"

    partitions: list[dict[str, object]] = []
    for parquet_path in sorted(fact_root.glob("visit_year=*/visit_quarter=*/ed_visits.parquet")):
        year = int(parquet_path.parent.parent.name.split("=")[1])
        quarter = int(parquet_path.parent.name.split("=")[1])
        success_path = parquet_path.parent / "_SUCCESS.json"
        parquet_meta = pq.ParquetFile(parquet_path).metadata
        success = json.loads(success_path.read_text(encoding="utf-8")) if success_path.exists() else {}
        partitions.append(
            {
                "visit_year": year,
                "visit_quarter": quarter,
                "parquet_path": str(parquet_path),
                "success_path": str(success_path),
                "success_exists": success_path.exists(),
                "parquet_rows": parquet_meta.num_rows,
                "parquet_columns": parquet_meta.num_columns,
                "parquet_row_groups": parquet_meta.num_row_groups,
                "parquet_bytes": parquet_path.stat().st_size,
                "success_fact_rows": success.get("output_fact_row_count"),
                "success_sha256": success.get("fact_file_sha256"),
                "success_reconciliation_passed": success.get("reconciliation_passed"),
            }
        )

    partition_frame = pd.DataFrame(partitions)
    partition_frame.to_csv(output / "partition_inventory.csv", index=False)

    expected_pairs = {(year, quarter) for year in SCOPE_YEARS for quarter in range(1, 5)}
    observed_pairs = {
        (int(row["visit_year"]), int(row["visit_quarter"])) for row in partitions
    }
    missing_pairs = sorted(expected_pairs - observed_pairs)
    unexpected_pairs = sorted(observed_pairs - expected_pairs)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{str(temp).replace(chr(39), chr(39) * 2)}'")
    con.execute("SET preserve_insertion_order=false")
    quoted_fact_glob = fact_glob.replace("'", "''")
    quoted_physician_path = str(physician_path).replace("'", "''")
    con.execute(
        f"""
        CREATE VIEW fact AS
        SELECT *
        FROM read_parquet('{quoted_fact_glob}', hive_partitioning=true, union_by_name=true)
        """
    )
    con.execute(
        f"""
        CREATE VIEW physician_master AS
        SELECT *
        FROM read_parquet('{quoted_physician_path}')
        """
    )

    fact_columns = [row[0] for row in con.execute("DESCRIBE fact").fetchall()]
    physician_columns = [row[0] for row in con.execute("DESCRIBE physician_master").fetchall()]

    write_query_csv(
        con,
        """
        SELECT visit_year,
               COUNT(*) AS visit_count,
               COUNT(DISTINCT visit_key) AS distinct_visit_keys,
               SUM(CASE WHEN source_record_duplicate_flag THEN 1 ELSE 0 END) AS duplicate_flagged_visits,
               SUM(CASE WHEN attending_selected_npi IS NOT NULL THEN 1 ELSE 0 END) AS attending_npi_available,
               SUM(CASE WHEN attending_physician_link_status = 'matched_physician_master' THEN 1 ELSE 0 END)
                   AS attending_master_matched,
               SUM(CASE WHEN attending_surname_imputed_race_ethnicity IS NOT NULL THEN 1 ELSE 0 END)
                   AS attending_imputed_race_available,
               SUM(CASE WHEN attending_gender_category IS NOT NULL THEN 1 ELSE 0 END)
                   AS attending_gender_available,
               SUM(CASE WHEN race_category IS NOT NULL THEN 1 ELSE 0 END) AS patient_race_available,
               SUM(CASE WHEN ethnicity_category IS NOT NULL THEN 1 ELSE 0 END) AS patient_ethnicity_available,
               SUM(CASE WHEN sex_category IS NOT NULL THEN 1 ELSE 0 END) AS patient_sex_available
        FROM fact
        GROUP BY visit_year
        ORDER BY visit_year
        """,
        output / "cohort_availability_by_year.csv",
    )

    for column, file_name in [
        ("race_category", "patient_race_counts.csv"),
        ("ethnicity_category", "patient_ethnicity_counts.csv"),
        ("sex_category", "patient_sex_counts.csv"),
        ("attending_surname_imputed_race_ethnicity", "attending_imputed_race_counts.csv"),
        ("attending_gender_category", "attending_gender_counts.csv"),
        ("attending_selection_method", "attending_selection_method_counts.csv"),
        ("attending_physician_link_status", "attending_link_status_counts.csv"),
    ]:
        write_query_csv(
            con,
            f"""
            SELECT visit_year, {column} AS category, COUNT(*) AS visit_count
            FROM fact
            GROUP BY visit_year, {column}
            ORDER BY visit_year, visit_count DESC, category
            """,
            output / file_name,
        )

    write_query_csv(
        con,
        """
        SELECT visit_year,
               COUNT(*) AS visit_count,
               SUM(CASE WHEN total_charge < 0 THEN 1 ELSE 0 END) AS negative_total_charge_count,
               SUM(CASE WHEN total_charge = 0 THEN 1 ELSE 0 END) AS zero_total_charge_count,
               SUM(CASE WHEN length_of_stay_days < 0 THEN 1 ELSE 0 END) AS negative_los_count,
               SUM(CASE WHEN length_of_stay_days = 0 THEN 1 ELSE 0 END) AS zero_los_count,
               AVG(total_charge) AS mean_total_charge,
               approx_quantile(total_charge, 0.50) AS median_total_charge,
               approx_quantile(total_charge, 0.95) AS p95_total_charge,
               approx_quantile(total_charge, 0.99) AS p99_total_charge,
               AVG(length_of_stay_days * 24.0) AS mean_los_hours,
               approx_quantile(length_of_stay_days * 24.0, 0.50) AS median_los_hours,
               approx_quantile(length_of_stay_days * 24.0, 0.95) AS p95_los_hours,
               approx_quantile(length_of_stay_days * 24.0, 0.99) AS p99_los_hours,
               AVG(procedure_count_analysis) AS mean_procedure_count
        FROM fact
        GROUP BY visit_year
        ORDER BY visit_year
        """,
        output / "outcome_profile_by_year.csv",
    )

    write_query_csv(
        con,
        """
        WITH normalized AS (
            SELECT visit_year,
                   visit_quarter,
                   upper(replace(coalesce(principal_diagnosis_code_norm, ''), '.', '')) AS dx
            FROM fact
        )
        SELECT visit_year,
               visit_quarter,
               SUM(CASE WHEN dx LIKE '410%' THEN 1 ELSE 0 END) AS icd9_410_broad,
               SUM(CASE WHEN dx LIKE '410%' AND
                                  NOT (length(dx) >= 5 AND substr(dx, 5, 1) = '2')
                        THEN 1 ELSE 0 END) AS icd9_410_excluding_subsequent_episode,
               SUM(CASE WHEN dx LIKE 'I21%' THEN 1 ELSE 0 END) AS icd10_i21,
               SUM(CASE WHEN dx LIKE 'I22%' THEN 1 ELSE 0 END) AS icd10_i22,
               SUM(CASE WHEN dx LIKE '410%' OR dx LIKE 'I21%' OR dx LIKE 'I22%'
                        THEN 1 ELSE 0 END) AS ami_broad
        FROM normalized
        GROUP BY visit_year, visit_quarter
        ORDER BY visit_year, visit_quarter
        """,
        output / "ami_principal_counts_by_quarter.csv",
    )

    write_query_csv(
        con,
        """
        SELECT surname_imputed_race_ethnicity AS category,
               COUNT(*) AS physician_count,
               AVG(surname_imputation_max_probability) AS mean_max_probability,
               approx_quantile(surname_imputation_max_probability, 0.10) AS p10_max_probability,
               approx_quantile(surname_imputation_max_probability, 0.50) AS median_max_probability,
               approx_quantile(surname_imputation_max_probability, 0.90) AS p90_max_probability
        FROM physician_master
        GROUP BY surname_imputed_race_ethnicity
        ORDER BY physician_count DESC
        """,
        output / "physician_master_imputed_race_profile.csv",
    )

    write_query_csv(
        con,
        """
        SELECT gender_category,
               gender_source,
               COUNT(*) AS physician_count
        FROM physician_master
        GROUP BY gender_category, gender_source
        ORDER BY physician_count DESC
        """,
        output / "physician_master_gender_profile.csv",
    )

    build_manifest = json.loads((release / "build_manifest_final.json").read_text(encoding="utf-8"))
    qa_summary = json.loads((release / "qa" / "qa_summary.json").read_text(encoding="utf-8"))
    independent_validation = json.loads(
        (release / "qa" / "independent_release_validation.json").read_text(encoding="utf-8")
    )

    audit = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "release_path": str(release),
        "release_manifest_sha256": sha256_file(release / "build_manifest_final.json"),
        "release_readme_sha256": sha256_file(release / "README.md"),
        "expected_partition_count": len(expected_pairs),
        "observed_partition_count": len(observed_pairs),
        "missing_partitions": missing_pairs,
        "unexpected_partitions": unexpected_pairs,
        "all_success_markers_exist": bool(partition_frame["success_exists"].all()),
        "all_partition_reconciliations_passed": bool(
            partition_frame["success_reconciliation_passed"].fillna(False).all()
        ),
        "parquet_row_sum": int(partition_frame["parquet_rows"].sum()),
        "success_manifest_row_sum": int(
            pd.to_numeric(partition_frame["success_fact_rows"], errors="coerce").sum()
        ),
        "fact_column_count": len(fact_columns),
        "fact_columns": fact_columns,
        "physician_master_column_count": len(physician_columns),
        "physician_master_columns": physician_columns,
        "build_manifest_summary": build_manifest,
        "qa_summary": qa_summary,
        "independent_validation": independent_validation,
        "read_only_audit_passed": (
            not missing_pairs
            and not unexpected_pairs
            and bool(partition_frame["success_exists"].all())
            and bool(partition_frame["success_reconciliation_passed"].fillna(False).all())
            and int(partition_frame["parquet_rows"].sum()) == qa_summary["fact_row_count"]
            and int(
                pd.to_numeric(partition_frame["success_fact_rows"], errors="coerce").sum()
            )
            == qa_summary["fact_row_count"]
            and qa_summary["all_required_checks_passed"]
            and independent_validation["status"] == "PASS"
        ),
    }
    (output / "release_audit.json").write_text(
        json.dumps(audit, indent=2, default=str), encoding="utf-8"
    )
    con.close()


if __name__ == "__main__":
    main()
