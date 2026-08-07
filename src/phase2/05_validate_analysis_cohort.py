#!/usr/bin/env python3
# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/05_validate_analysis_cohort.py
# All private inputs, outputs, and scratch locations are command-line parameters.

"""Independently validate the complete Phase 2 concordance analysis cohort.

This validator does not trust the build process alone. It verifies partition
coverage, recorded file hashes and sizes, Parquet row counts, one-to-one joins
across the normalized cohort files, visit-key uniqueness within partitions,
indicator logic, aggregate reconciliation to the provider-v2 pre-estimation gate,
outcome support, pair counts, and AMI definition counts.
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


YEARS = tuple(range(2010, 2025))
QUARTERS = (1, 2, 3, 4)
FILES = (
    "concordance_visit_core.parquet",
    "concordance_charge_components.parquet",
    "concordance_elixhauser_flags.parquet",
)
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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--temp", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    release = args.release.resolve()
    data_root = (
        phase2 / "analysis_data" / "concordance_visit_data_provider_v2"
    )
    qa_root = phase2 / "qa"
    args.temp.mkdir(parents=True, exist_ok=True)
    qa_root.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(args.temp)}'")
    con.execute("SET preserve_insertion_order=false")

    checks: list[dict[str, Any]] = []
    partition_rows: list[dict[str, Any]] = []
    failure_messages: list[str] = []

    def record(
        check_id: str,
        passed: bool,
        observed: Any,
        expected: Any,
        detail: str = "",
    ) -> None:
        checks.append(
            {
                "check_id": check_id,
                "passed": bool(passed),
                "observed": observed,
                "expected": expected,
                "detail": detail,
            }
        )
        if not passed:
            failure_messages.append(
                f"{check_id}: observed={observed!r}, expected={expected!r}. {detail}"
            )

    expected_partitions = {(year, quarter) for year in YEARS for quarter in QUARTERS}
    discovered_success = {
        (
            int(path.parent.parent.name.split("=", 1)[1]),
            int(path.parent.name.split("=", 1)[1]),
        ): path
        for path in data_root.glob(
            "visit_year=*/visit_quarter=*/_SUCCESS.json"
        )
    }
    record(
        "partition_coverage",
        set(discovered_success) == expected_partitions,
        len(discovered_success),
        len(expected_partitions),
        (
            f"missing={sorted(expected_partitions - set(discovered_success))}; "
            f"unexpected={sorted(set(discovered_success) - expected_partitions)}"
        ),
    )

    for year, quarter in sorted(expected_partitions):
        success_path = discovered_success.get((year, quarter))
        if success_path is None:
            continue
        payload = json.loads(success_path.read_text(encoding="utf-8"))
        part_dir = success_path.parent
        recorded = {item["name"]: item for item in payload.get("files", [])}
        file_counts: dict[str, int] = {}
        file_integrity_pass = True
        for name in FILES:
            path = part_dir / name
            item = recorded.get(name)
            if not path.exists() or item is None:
                file_integrity_pass = False
                continue
            actual_size = path.stat().st_size
            actual_hash = sha256_file(path)
            actual_rows = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{qpath(path)}', "
                "hive_partitioning=false)"
            ).fetchone()[0]
            file_counts[name] = actual_rows
            if (
                actual_size != item.get("bytes")
                or actual_hash != item.get("sha256")
                or actual_rows != item.get("rows")
            ):
                file_integrity_pass = False

        core = part_dir / FILES[0]
        charge = part_dir / FILES[1]
        risk = part_dir / FILES[2]
        if not all(path.exists() for path in (core, charge, risk)):
            record(
                f"{year}Q{quarter}_files",
                False,
                sorted(path.name for path in part_dir.glob("*.parquet")),
                list(FILES),
            )
            continue

        invariants = con.execute(
            f"""
            WITH core AS (
                SELECT * FROM read_parquet(
                    '{qpath(core)}', hive_partitioning=false
                )
            ),
            charge AS (
                SELECT * FROM read_parquet(
                    '{qpath(charge)}', hive_partitioning=false
                )
            ),
            risk AS (
                SELECT * FROM read_parquet(
                    '{qpath(risk)}', hive_partitioning=false
                )
            )
            SELECT
                COUNT(*) AS rows,
                COUNT(DISTINCT core.visit_key) AS distinct_visit_keys,
                COUNT(*) FILTER (
                    WHERE core.visit_year <> {year}
                       OR core.visit_quarter <> {quarter}
                ) AS wrong_partition_rows,
                COUNT(charge.visit_key) AS matched_charge_rows,
                COUNT(risk.visit_key) AS matched_risk_rows,
                COUNT(*) FILTER (
                    WHERE core.race_primary_eligible_t50_flag = 1
                      AND (
                        coalesce(core.black_black, 0)
                        + coalesce(core.black_white, 0)
                        + coalesce(core.white_black, 0)
                        + coalesce(core.white_white, 0)
                      ) <> 1
                ) AS race_indicator_errors,
                COUNT(*) FILTER (
                    WHERE core.sex_gender_primary_eligible_flag = 1
                      AND (
                        coalesce(core.female_female, 0)
                        + coalesce(core.female_male, 0)
                        + coalesce(core.male_female, 0)
                        + coalesce(core.male_male, 0)
                      ) <> 1
                ) AS sex_gender_indicator_errors,
                COUNT(*) FILTER (
                    WHERE core.los_primary_valid_flag = 1
                      AND (
                        core.los_hours_primary_0_168 IS NULL
                        OR core.los_hours_primary_0_168 < 0
                        OR core.los_hours_primary_0_168 > 168
                      )
                ) AS los_definition_errors
            FROM core
            LEFT JOIN charge USING (visit_key, visit_year, visit_quarter)
            LEFT JOIN risk USING (visit_key, visit_year, visit_quarter)
            """
        ).fetchone()
        (
            rows,
            distinct_keys,
            wrong_partition_rows,
            matched_charge,
            matched_risk,
            race_errors,
            sex_errors,
            los_errors,
        ) = invariants
        manifest_rows = int(payload.get("cohort_rows", -1))
        partition_pass = (
            file_integrity_pass
            and payload.get("reconciliation_passed") is True
            and payload.get("source_release_modified") is False
            and rows == distinct_keys == matched_charge == matched_risk == manifest_rows
            and wrong_partition_rows == race_errors == sex_errors == los_errors == 0
        )
        record(
            f"{year}Q{quarter}_partition",
            partition_pass,
            rows,
            manifest_rows,
            (
                f"integrity={file_integrity_pass}; distinct={distinct_keys}; "
                f"charge_matches={matched_charge}; risk_matches={matched_risk}; "
                f"wrong_partition={wrong_partition_rows}; race_errors={race_errors}; "
                f"sex_errors={sex_errors}; los_errors={los_errors}"
            ),
        )
        partition_rows.append(
            {
                "visit_year": year,
                "visit_quarter": quarter,
                "rows": rows,
                "distinct_visit_keys": distinct_keys,
                "charge_rows": file_counts.get(FILES[1]),
                "elixhauser_rows": file_counts.get(FILES[2]),
                "sha256_and_size_pass": file_integrity_pass,
                "partition_logic_pass": partition_pass,
            }
        )

    core_glob = data_root / "visit_year=*" / "visit_quarter=*" / FILES[0]
    recorded_gender_sources_sql = ", ".join(
        "'" + value.replace("'", "''") + "'"
        for value in RECORDED_PHYSICIAN_GENDER_SOURCES
    )
    aggregate = con.execute(
        f"""
        SELECT
            COUNT(*) AS all_rows,
            sum(race_primary_eligible_t50_flag) AS race_t50,
            sum(race_primary_eligible_t70_flag) AS race_t70,
            sum(race_primary_eligible_t80_flag) AS race_t80,
            sum(race_primary_eligible_t90_flag) AS race_t90,
            sum(sex_gender_primary_eligible_flag) AS sex_gender,
            count(*) FILTER (
                WHERE sex_gender_primary_eligible_flag
                  AND physician_gender_source IN (
                      {recorded_gender_sources_sql}
                  )
            ) AS sex_gender_recorded_primary,
            sum(CASE WHEN los_hours_nonnegative IS NOT NULL THEN 1 ELSE 0 END)
                AS los_nonnegative,
            sum(CASE WHEN los_hours_clock_raw < 0 THEN 1 ELSE 0 END)
                AS los_negative,
            sum(CASE WHEN los_hours_clock_raw > 168 THEN 1 ELSE 0 END)
                AS los_over_168,
            sum(CASE WHEN los_hours_primary_0_168 IS NOT NULL THEN 1 ELSE 0 END)
                AS los_primary,
            sum(CASE WHEN total_charge_reported_real_2024 IS NOT NULL THEN 1 ELSE 0 END)
                AS real_reported_charge,
            sum(ami_icd9_principal_strict_flag) AS ami_icd9_principal_strict,
            sum(ami_icd9_principal_broad_flag) AS ami_icd9_principal_broad,
            sum(ami_icd10_principal_primary_flag) AS ami_icd10_principal_primary,
            sum(ami_icd10_principal_type2_other_flag)
                AS ami_icd10_principal_type2_other
        FROM read_parquet('{qpath(core_glob)}', hive_partitioning=false)
        """
    ).fetchone()
    aggregate_names = [
        "all_rows",
        "race_t50",
        "race_t70",
        "race_t80",
        "race_t90",
        "sex_gender",
        "sex_gender_recorded_primary",
        "los_nonnegative",
        "los_negative",
        "los_over_168",
        "los_primary",
        "real_reported_charge",
        "ami_icd9_principal_strict",
        "ami_icd9_principal_broad",
        "ami_icd10_principal_primary",
        "ami_icd10_principal_type2_other",
    ]
    aggregate_counts = {
        name: int(value) if value is not None else None
        for name, value in zip(aggregate_names, aggregate)
    }
    gender_checkpoint_path = (
        qa_root / "provider_gender_measurement_checkpoint.json"
    )
    gender_checkpoint = json.loads(
        gender_checkpoint_path.read_text(encoding="utf-8")
    )
    gender_coverage = gender_checkpoint.get("coverage", {})
    record(
        "physician_gender_measurement_checkpoint",
        (
            gender_checkpoint.get("status") == "PASS"
            and gender_checkpoint.get("estimate_blind") is True
            and gender_checkpoint.get("primary_definition", {}).get(
                "physician_gender_sources"
            )
            == list(RECORDED_PHYSICIAN_GENDER_SOURCES)
            and gender_coverage.get("hierarchy_eligible_visits")
                == aggregate_counts["sex_gender"]
            and gender_coverage.get("recorded_source_primary_visits")
                == aggregate_counts["sex_gender_recorded_primary"]
        ),
        {
            "hierarchy": aggregate_counts["sex_gender"],
            "recorded_primary": aggregate_counts[
                "sex_gender_recorded_primary"
            ],
        },
        gender_coverage,
        "Recorded NPPES/CMS source filtering is applied in model matrices.",
    )
    gate_reconciliation_path = (
        qa_root / "provider_v2_cohort_fact_reconciliation.csv"
    )
    with gate_reconciliation_path.open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        gate_reconciliation = list(csv.DictReader(stream))
    record(
        "pre_estimation_gate_reconciliation_rows",
        len(gate_reconciliation) == len(expected_partitions)
        and all(item.get("status") == "PASS" for item in gate_reconciliation),
        len(gate_reconciliation),
        len(expected_partitions),
        "Independent reconciliation is generated before model estimation.",
    )
    expected_from_facts = {
        "all_rows": sum(
            int(item["expected_rows_from_phase1_facts"])
            for item in gate_reconciliation
        ),
        "race_t50": sum(
            int(item["expected_race_primary_t50_rows"])
            for item in gate_reconciliation
        ),
        "sex_gender": sum(
            int(item["expected_sex_gender_primary_rows"])
            for item in gate_reconciliation
        ),
    }
    comparisons = {
        "all_rows": expected_from_facts["all_rows"],
        "race_t50": expected_from_facts["race_t50"],
        "sex_gender": expected_from_facts["sex_gender"],
    }
    for name, expected_value in comparisons.items():
        record(
            f"aggregate_reconciliation_{name}",
            aggregate_counts[name] == expected_value,
            aggregate_counts[name],
            expected_value,
        )

    pair_rows = con.execute(
        f"""
        SELECT
            visit_year,
            sum(race_primary_eligible_t50_flag) AS race_t50,
            sum(race_primary_eligible_t70_flag) AS race_t70,
            sum(race_primary_eligible_t80_flag) AS race_t80,
            sum(race_primary_eligible_t90_flag) AS race_t90,
            sum(black_black) AS black_black,
            sum(black_white) AS black_white,
            sum(white_black) AS white_black,
            sum(white_white) AS white_white,
            sum(sex_gender_primary_eligible_flag) AS sex_gender,
            count(*) FILTER (
                WHERE sex_gender_primary_eligible_flag
                  AND physician_gender_source IN (
                      {recorded_gender_sources_sql}
                  )
            ) AS sex_gender_recorded_primary,
            sum(female_female) AS female_female,
            sum(female_male) AS female_male,
            sum(male_female) AS male_female,
            sum(male_male) AS male_male
        FROM read_parquet('{qpath(core_glob)}', hive_partitioning=false)
        GROUP BY visit_year
        ORDER BY visit_year
        """
    ).fetchdf().to_dict(orient="records")

    outcome_rows = con.execute(
        f"""
        SELECT
            visit_year,
            count(*) AS all_visits,
            count(*) FILTER (WHERE race_primary_eligible_t50_flag = 1)
                AS race_primary_visits,
            count(*) FILTER (WHERE sex_gender_primary_eligible_flag = 1)
                AS sex_gender_hierarchy_eligible_visits,
            count(*) FILTER (
                WHERE sex_gender_primary_eligible_flag = 1
                  AND physician_gender_source IN (
                      {recorded_gender_sources_sql}
                  )
            ) AS sex_gender_recorded_primary_visits,
            count(los_hours_primary_0_168) AS los_primary_nonmissing,
            avg(los_hours_primary_0_168) AS los_primary_mean,
            stddev_samp(los_hours_primary_0_168) AS los_primary_sd,
            quantile_cont(los_hours_primary_0_168, 0.5) AS los_primary_median,
            count(total_charge_reported_real_2024) AS charge_real_nonmissing,
            avg(total_charge_reported_real_2024) AS charge_real_mean,
            stddev_samp(total_charge_reported_real_2024) AS charge_real_sd,
            quantile_cont(total_charge_reported_real_2024, 0.5)
                AS charge_real_median
        FROM read_parquet('{qpath(core_glob)}', hive_partitioning=false)
        GROUP BY visit_year
        ORDER BY visit_year
        """
    ).fetchdf().to_dict(orient="records")

    physician_support_rows = con.execute(
        f"""
        WITH eligible AS (
            SELECT
                attending_selected_npi,
                max(patient_black_flag) AS has_black_patient,
                max(1 - patient_black_flag) AS has_white_patient,
                count(*) AS eligible_visits
            FROM read_parquet('{qpath(core_glob)}', hive_partitioning=false)
            WHERE race_primary_eligible_t50_flag = 1
            GROUP BY attending_selected_npi
        )
        SELECT
            count(*) AS eligible_physicians,
            count(*) FILTER (
                WHERE has_black_patient = 1 AND has_white_patient = 1
            ) AS physicians_with_both_patient_groups,
            sum(eligible_visits) AS eligible_visits,
            sum(eligible_visits) FILTER (
                WHERE has_black_patient = 1 AND has_white_patient = 1
            ) AS visits_from_physicians_with_both_groups
        FROM eligible
        """
    ).fetchone()
    physician_support = {
        "eligible_physicians": int(physician_support_rows[0]),
        "physicians_with_both_patient_groups": int(physician_support_rows[1]),
        "eligible_visits": int(physician_support_rows[2]),
        "visits_from_physicians_with_both_groups": int(physician_support_rows[3]),
    }

    all_partition_checks_pass = all(
        item["partition_logic_pass"] for item in partition_rows
    ) and len(partition_rows) == len(expected_partitions)
    aggregate_checks_pass = all(
        item["passed"]
        for item in checks
        if item["check_id"].startswith("aggregate_reconciliation_")
    )
    final_pass = (
        not failure_messages
        and all_partition_checks_pass
        and aggregate_checks_pass
    )

    write_csv(qa_root / "cohort_validation_checks.csv", checks)
    write_csv(qa_root / "cohort_partition_validation.csv", partition_rows)
    write_csv(qa_root / "cohort_pair_counts_by_year.csv", pair_rows)
    write_csv(qa_root / "cohort_outcome_profile_by_year.csv", outcome_rows)
    report = {
        "created_utc": now_utc(),
        "phase2_root": str(phase2),
        "source_release": str(release),
        "status": "PASS" if final_pass else "FAIL",
        "expected_partitions": len(expected_partitions),
        "validated_partitions": len(partition_rows),
        "aggregate_counts": aggregate_counts,
        "physician_gender_measurement_checkpoint": {
            "path": str(gender_checkpoint_path),
            "sha256": sha256_file(gender_checkpoint_path),
            "coverage": gender_coverage,
        },
        "physician_support": physician_support,
        "failed_checks": failure_messages,
        "source_release_modified": False,
    }
    (qa_root / "cohort_validation_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    con.close()
    if not final_pass:
        raise SystemExit(
            "Cohort validation failed. See qa/cohort_validation_report.json."
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
