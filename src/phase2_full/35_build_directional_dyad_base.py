#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/35_build_directional_dyad_base.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Build restartable, hash-bound directional-dyad derived partitions.

The output preserves one row per validated provider-v2 Phase 2 encounter.
It is a derived analysis base, not a rebuild or mutation of Phase 1 or the
validated Phase 2 cohort.  No eligibility filter removes encounters.
"""

from __future__ import annotations

import argparse
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
RECORDED_GENDER_SOURCES = (
    "NPPES",
    "NPPES February 2026 current snapshot",
    "CMS Doctors and Clinicians",
    "CMS Doctors and Clinicians June 2026 current snapshot",
)
RACE_CLASSES = ("white", "black", "hispanic", "asian", "other")
RACE_DISPLAY = {
    "white": "White",
    "black": "Black",
    "hispanic": "Hispanic",
    "asian": "Asian",
    "other": "Other/multiracial",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def live_file_matches(
    output: Path,
    success: Path,
    expected: dict[str, Any],
) -> bool:
    if not output.is_file() or not success.is_file():
        return False
    try:
        manifest = json.loads(success.read_text(encoding="utf-8"))
    except Exception:
        return False
    for key, value in expected.items():
        if manifest.get(key) != value:
            return False
    if manifest.get("status") != "PASS":
        return False
    if manifest.get("output_bytes") != output.stat().st_size:
        return False
    return manifest.get("output_sha256") == sha256(output)


def preserve_stale(path: Path) -> None:
    if path.exists():
        stale = path.with_name(path.name + f".stale_{compact_utc()}")
        os.replace(path, stale)


def patient_group_expression(prefix: str = "c") -> str:
    return f"""
        CASE
          WHEN {prefix}.patient_ethnicity_category =
               'Hispanic or Latino'
            THEN 'Hispanic'
          WHEN {prefix}.patient_ethnicity_category =
               'Not Hispanic or Latino'
           AND {prefix}.patient_race_category = 'White'
            THEN 'White'
          WHEN {prefix}.patient_ethnicity_category =
               'Not Hispanic or Latino'
           AND {prefix}.patient_race_category =
               'Black or African American'
            THEN 'Black'
          WHEN {prefix}.patient_ethnicity_category =
               'Not Hispanic or Latino'
           AND {prefix}.patient_race_category = 'Asian'
            THEN 'Asian'
          WHEN {prefix}.patient_ethnicity_category =
               'Not Hispanic or Latino'
           AND {prefix}.patient_race_category IN (
               'American Indian or Alaska Native',
               'Native Hawaiian or Other Pacific Islander',
               'Other'
           )
            THEN 'Other/multiracial'
          ELSE NULL
        END
    """


def population_label_expression() -> str:
    cases: list[str] = []
    for race in RACE_CLASSES:
        column = f"c.physician_race_population_prob_{race}"
        comparisons = " AND ".join(
            f"{column} >= "
            f"c.physician_race_population_prob_{other}"
            for other in RACE_CLASSES
            if other != race
        )
        cases.append(
            f"WHEN {comparisons} THEN {quote(RACE_DISPLAY[race])}"
        )
    return "CASE " + " ".join(cases) + " ELSE NULL END"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--only-year", type=int)
    parser.add_argument("--only-quarter", type=int)
    args = parser.parse_args()
    if (args.only_year is None) != (args.only_quarter is None):
        parser.error("--only-year and --only-quarter must be supplied together")
    if args.only_year is not None and (
        args.only_year not in YEARS or args.only_quarter not in QUARTERS
    ):
        parser.error("Requested smoke partition is outside 2010-2024 Q1-Q4")
    selected_years = (
        (args.only_year,) if args.only_year is not None else YEARS
    )
    selected_quarters = (
        (args.only_quarter,) if args.only_quarter is not None else QUARTERS
    )

    phase2 = args.phase2.resolve()
    output_root = args.output.resolve()
    temp_root = args.temp.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    extension_gate_path = (
        phase2 / "qa" / "directional_dyad_extension_pre_estimation_gate.json"
    )
    extension_manifest_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    provider_gate_path = (
        phase2 / "qa" / "pre_estimation_measurement_gate.json"
    )
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"
    provider_master = (
        phase2 / "analysis_data" / "dimensions" / "provider_master_v2.parquet"
    )
    required = (
        extension_gate_path,
        extension_manifest_path,
        provider_gate_path,
        cohort_gate_path,
        provider_master,
    )
    for path in required:
        if not path.is_file():
            raise RuntimeError(f"Required binding is missing: {path}")

    extension_gate = json.loads(
        extension_gate_path.read_text(encoding="utf-8")
    )
    provider_gate = json.loads(provider_gate_path.read_text(encoding="utf-8"))
    cohort_gate = json.loads(cohort_gate_path.read_text(encoding="utf-8"))
    if (
        extension_gate.get("status") != "PASS"
        or not extension_gate.get("estimation_authorized")
        or extension_gate.get("phase2_cohort_rebuild_required") is not False
    ):
        raise RuntimeError("Directional extension gate is not authorizing")
    if provider_gate.get("status") != "PASS":
        raise RuntimeError("Provider measurement gate is not PASS")
    if cohort_gate.get("status") != "PASS":
        raise RuntimeError("Cohort validation gate is not PASS")

    binding = {
        "extension_manifest_sha256": sha256(extension_manifest_path),
        "extension_gate_sha256": sha256(extension_gate_path),
        "provider_gate_sha256": sha256(provider_gate_path),
        "cohort_gate_sha256": sha256(cohort_gate_path),
        "provider_master_sha256": sha256(provider_master),
    }
    if (
        extension_gate["frozen_manifest"]["sha256"]
        != binding["extension_manifest_sha256"]
    ):
        raise RuntimeError("Frozen extension manifest hash changed")

    data_root = (
        phase2 / "analysis_data" / "concordance_visit_data_provider_v2"
    )
    discretion_root = phase2 / "analysis_data" / "discretion_outcomes"
    sources_sql = ", ".join(quote(value) for value in RECORDED_GENDER_SOURCES)
    patient_group = patient_group_expression()
    population_label = population_label_expression()
    population_confidence = "greatest(" + ", ".join(
        f"c.physician_race_population_prob_{race}"
        for race in RACE_CLASSES
    ) + ")"
    primary_probability_sum = " + ".join(
        f"c.physician_race_proxy_prob_{race}" for race in RACE_CLASSES
    )
    population_probability_sum = " + ".join(
        f"c.physician_race_population_prob_{race}" for race in RACE_CLASSES
    )

    con = duckdb.connect()
    con.execute(f"SET threads={int(args.threads)}")
    con.execute(f"SET memory_limit={quote(args.memory_limit)}")
    con.execute(f"SET temp_directory={quote(qpath(temp_root))}")
    con.execute("SET preserve_insertion_order=false")

    partition_rows: list[dict[str, Any]] = []
    for year in selected_years:
        for quarter in selected_quarters:
            source_part = (
                data_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
            )
            core = source_part / "concordance_visit_core.parquet"
            risk = source_part / "concordance_elixhauser_flags.parquet"
            charge = source_part / "concordance_charge_components.parquet"
            source_success = source_part / "_SUCCESS.json"
            discretion_part = (
                discretion_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
            )
            discretion = (
                discretion_part / "visit_discretion_outcomes.parquet"
            )
            discretion_success = discretion_part / "_SUCCESS.json"
            for path in (
                core,
                risk,
                charge,
                source_success,
                discretion,
                discretion_success,
            ):
                if not path.is_file():
                    raise RuntimeError(f"Missing source partition file: {path}")

            source_manifest = json.loads(
                source_success.read_text(encoding="utf-8")
            )
            discretion_manifest = json.loads(
                discretion_success.read_text(encoding="utf-8")
            )
            file_map = {
                item["name"]: item
                for item in source_manifest.get("files", [])
            }
            if (
                source_manifest.get("build_spec_version")
                != "provider_v2_cms_current_cohort_v1"
                or not source_manifest.get("reconciliation_passed")
                or source_manifest.get("source_release_modified") is not False
                or not discretion_manifest.get("passed")
            ):
                raise RuntimeError(f"Source manifest gate failed: {source_part}")
            for path in (core, risk, charge):
                item = file_map.get(path.name)
                if item is None or item.get("sha256") != sha256(path):
                    raise RuntimeError(f"Source hash mismatch: {path}")
            if discretion_manifest.get("sha256") != sha256(discretion):
                raise RuntimeError(f"Discretion hash mismatch: {discretion}")

            out_part = (
                output_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
            )
            out_part.mkdir(parents=True, exist_ok=True)
            output = out_part / "directional_dyad_base.parquet"
            success = out_part / "_SUCCESS.json"
            expected = {
                "build_spec_version": BUILD_SPEC_VERSION,
                "visit_year": year,
                "visit_quarter": quarter,
                "source_success_sha256": sha256(source_success),
                "discretion_success_sha256": sha256(discretion_success),
                **binding,
            }
            if live_file_matches(output, success, expected):
                manifest = json.loads(success.read_text(encoding="utf-8"))
                partition_rows.append(manifest)
                print(f"{year} Q{quarter}: reused", flush=True)
                continue

            preserve_stale(output)
            preserve_stale(success)
            # DuckDB on Windows may still observe MAX_PATH for long COPY
            # targets.  Write to the explicitly short scratch root and then
            # atomically replace the final partition file.
            temporary = temp_root / (
                f"ddb_{year}_{quarter}_{compact_utc()}.parquet"
            )
            if temporary.exists():
                preserve_stale(temporary)

            query = f"""
                COPY (
                    WITH joined AS (
                        SELECT
                            c.*,
                            r.* EXCLUDE (
                                visit_key, visit_year, visit_quarter
                            ),
                            ch.* EXCLUDE (
                                visit_key, visit_year, visit_quarter
                            ),
                            d.* EXCLUDE (
                                visit_key, visit_year, visit_quarter
                            ),
                            coalesce(
                                p.gender_conflict_flag_v2, false
                            ) AS physician_gender_source_conflict_flag,
                            {patient_group}
                                AS patient_race_ethnicity_5cat,
                            {population_label}
                                AS physician_race_population_label,
                            {population_confidence}
                                AS physician_race_population_confidence
                        FROM read_parquet(
                            {quote(qpath(core))},
                            hive_partitioning=false
                        ) c
                        INNER JOIN read_parquet(
                            {quote(qpath(risk))},
                            hive_partitioning=false
                        ) r USING (
                            visit_key, visit_year, visit_quarter
                        )
                        INNER JOIN read_parquet(
                            {quote(qpath(charge))},
                            hive_partitioning=false
                        ) ch USING (
                            visit_key, visit_year, visit_quarter
                        )
                        INNER JOIN read_parquet(
                            {quote(qpath(discretion))},
                            hive_partitioning=false
                        ) d USING (
                            visit_key, visit_year, visit_quarter
                        )
                        LEFT JOIN read_parquet(
                            {quote(qpath(provider_master))},
                            hive_partitioning=false
                        ) p
                          ON c.attending_selected_npi = p.npi
                    )
                    SELECT
                        *,
                        (
                            patient_sex_category IN ('Female', 'Male')
                            AND physician_gender_category IN (
                                'Female', 'Male'
                            )
                            AND physician_gender_source IN ({sources_sql})
                        ) AS directional_gender_eligible,
                        (
                            patient_race_ethnicity_5cat IS NOT NULL
                            AND attending_selected_npi IS NOT NULL
                            AND physician_md_do_flag
                            AND {primary_probability_sum.replace("c.", "")}
                                BETWEEN 0.999999 AND 1.000001
                        ) AS directional_race_probability_eligible,
                        (
                            patient_race_ethnicity_5cat IS NOT NULL
                            AND attending_selected_npi IS NOT NULL
                            AND physician_md_do_flag
                            AND {population_probability_sum.replace("c.", "")}
                                BETWEEN 0.999999 AND 1.000001
                        ) AS directional_race_population_probability_eligible,
                        (
                            patient_race_ethnicity_5cat IS NOT NULL
                            AND physician_race_proxy_primary_label IN (
                                'White', 'Black', 'Hispanic', 'Asian',
                                'Other/multiracial'
                            )
                            AND physician_race_imputation_confidence >= 0.50
                        ) AS directional_race_hard_t50_eligible,
                        (
                            patient_race_ethnicity_5cat IS NOT NULL
                            AND physician_race_proxy_primary_label IN (
                                'White', 'Black', 'Hispanic', 'Asian',
                                'Other/multiracial'
                            )
                            AND physician_race_imputation_confidence >= 0.70
                        ) AS directional_race_hard_t70_eligible,
                        (
                            patient_race_ethnicity_5cat IS NOT NULL
                            AND physician_race_proxy_primary_label IN (
                                'White', 'Black', 'Hispanic', 'Asian',
                                'Other/multiracial'
                            )
                            AND physician_race_imputation_confidence >= 0.80
                        ) AS directional_race_hard_t80_eligible,
                        (
                            patient_race_ethnicity_5cat IS NOT NULL
                            AND physician_race_proxy_primary_label IN (
                                'White', 'Black', 'Hispanic', 'Asian',
                                'Other/multiracial'
                            )
                            AND physician_race_imputation_confidence >= 0.90
                        ) AS directional_race_hard_t90_eligible,
                        (
                            patient_race_ethnicity_5cat IS NOT NULL
                            AND physician_race_population_label IN (
                                'White', 'Black', 'Hispanic', 'Asian',
                                'Other/multiracial'
                            )
                            AND physician_race_population_confidence >= 0.50
                        ) AS directional_race_population_hard_t50_eligible,
                        (
                            patient_sex_category IN ('Female', 'Male')
                            AND physician_gender_category IN (
                                'Female', 'Male'
                            )
                            AND physician_gender_source IN ({sources_sql})
                            AND patient_race_ethnicity_5cat IS NOT NULL
                            AND {primary_probability_sum.replace("c.", "")}
                                BETWEEN 0.999999 AND 1.000001
                        ) AS directional_intersectional_probability_eligible,
                        (
                            patient_sex_category IN ('Female', 'Male')
                            AND physician_gender_category IN (
                                'Female', 'Male'
                            )
                            AND physician_gender_source IN ({sources_sql})
                            AND patient_race_ethnicity_5cat IS NOT NULL
                            AND physician_race_proxy_primary_label IN (
                                'White', 'Black', 'Hispanic', 'Asian',
                                'Other/multiracial'
                            )
                            AND physician_race_imputation_confidence >= 0.50
                        ) AS directional_intersectional_hard_t50_eligible
                    FROM joined
                ) TO {quote(qpath(temporary))}
                (
                    FORMAT PARQUET,
                    COMPRESSION ZSTD,
                    ROW_GROUP_SIZE 100000
                )
            """
            con.execute(query)

            qa = con.execute(
                f"""
                SELECT
                    count(*) AS rows,
                    count(DISTINCT visit_key) AS distinct_visit_keys,
                    count(*) FILTER (
                        WHERE directional_gender_eligible
                    ) AS gender_rows,
                    count(*) FILTER (
                        WHERE directional_race_probability_eligible
                    ) AS race_probability_rows,
                    count(*) FILTER (
                        WHERE directional_race_hard_t50_eligible
                    ) AS race_hard_t50_rows,
                    count(*) FILTER (
                        WHERE
                          directional_intersectional_probability_eligible
                    ) AS intersectional_probability_rows,
                    count(*) FILTER (
                        WHERE
                          directional_intersectional_hard_t50_eligible
                    ) AS intersectional_hard_t50_rows,
                    count(*) FILTER (
                        WHERE directional_race_probability_eligible
                          AND abs(
                              {primary_probability_sum.replace("c.", "")}
                              - 1.0
                          ) > 0.000001
                    ) AS primary_probability_sum_errors,
                    count(*) FILTER (
                        WHERE
                          directional_race_population_probability_eligible
                          AND abs(
                              {population_probability_sum.replace("c.", "")}
                              - 1.0
                          ) > 0.000001
                    ) AS population_probability_sum_errors
                FROM read_parquet(
                    {quote(qpath(temporary))},
                    hive_partitioning=false
                )
                """
            ).fetchone()
            expected_rows = int(source_manifest["cohort_rows"])
            if (
                int(qa[0]) != expected_rows
                or int(qa[1]) != expected_rows
                or int(qa[7]) != 0
                or int(qa[8]) != 0
            ):
                preserve_stale(temporary)
                raise RuntimeError(
                    f"Directional base QA failed for {year} Q{quarter}: {qa}"
                )

            os.replace(temporary, output)
            output_hash = sha256(output)
            manifest = {
                "status": "PASS",
                "created_utc": utc_now(),
                "build_spec_version": BUILD_SPEC_VERSION,
                "visit_year": year,
                "visit_quarter": quarter,
                "source_success_sha256": expected[
                    "source_success_sha256"
                ],
                "discretion_success_sha256": expected[
                    "discretion_success_sha256"
                ],
                **binding,
                "source_rows": expected_rows,
                "output_rows": int(qa[0]),
                "distinct_visit_keys": int(qa[1]),
                "gender_eligible_rows": int(qa[2]),
                "race_probability_eligible_rows": int(qa[3]),
                "race_hard_t50_eligible_rows": int(qa[4]),
                "intersectional_probability_eligible_rows": int(qa[5]),
                "intersectional_hard_t50_eligible_rows": int(qa[6]),
                "primary_probability_sum_errors": int(qa[7]),
                "population_probability_sum_errors": int(qa[8]),
                "output_file": output.name,
                "output_bytes": output.stat().st_size,
                "output_sha256": output_hash,
                "phase1_modified": False,
                "phase2_cohort_modified": False,
                "encounters_filtered": False,
            }
            atomic_json(success, manifest)
            partition_rows.append(manifest)
            print(
                f"{year} Q{quarter}: PASS rows={qa[0]:,}",
                flush=True,
            )

    con.close()
    expected_partitions = len(selected_years) * len(selected_quarters)
    if len(partition_rows) != expected_partitions:
        raise RuntimeError("Directional base partition count is incomplete")
    build_manifest = {
        "status": "PASS",
        "created_utc": utc_now(),
        "build_spec_version": BUILD_SPEC_VERSION,
        "build_scope": (
            "single_partition_smoke"
            if args.only_year is not None
            else "full_2010_2024"
        ),
        "partitions_expected": expected_partitions,
        "partitions_passed": len(partition_rows),
        "source_rows": sum(int(item["source_rows"]) for item in partition_rows),
        "output_rows": sum(int(item["output_rows"]) for item in partition_rows),
        "distinct_visit_keys_partition_sum": sum(
            int(item["distinct_visit_keys"]) for item in partition_rows
        ),
        "gender_eligible_rows": sum(
            int(item["gender_eligible_rows"]) for item in partition_rows
        ),
        "race_probability_eligible_rows": sum(
            int(item["race_probability_eligible_rows"])
            for item in partition_rows
        ),
        "race_hard_t50_eligible_rows": sum(
            int(item["race_hard_t50_eligible_rows"])
            for item in partition_rows
        ),
        "intersectional_probability_eligible_rows": sum(
            int(item["intersectional_probability_eligible_rows"])
            for item in partition_rows
        ),
        "intersectional_hard_t50_eligible_rows": sum(
            int(item["intersectional_hard_t50_eligible_rows"])
            for item in partition_rows
        ),
        **binding,
        "partition_manifests": [
            {
                "visit_year": item["visit_year"],
                "visit_quarter": item["visit_quarter"],
                "output_rows": item["output_rows"],
                "output_sha256": item["output_sha256"],
            }
            for item in partition_rows
        ],
        "one_row_per_validated_phase2_encounter": True,
        "encounters_filtered": False,
        "phase1_modified": False,
        "phase2_cohort_modified": False,
    }
    if build_manifest["source_rows"] != build_manifest["output_rows"]:
        raise RuntimeError("Global directional-base row reconciliation failed")
    manifest_path = output_root / "directional_dyad_base_manifest.json"
    atomic_json(manifest_path, build_manifest)
    print(json.dumps(build_manifest, indent=2))


if __name__ == "__main__":
    main()
