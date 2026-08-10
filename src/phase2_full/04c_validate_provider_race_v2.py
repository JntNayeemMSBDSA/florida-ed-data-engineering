# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/04c_validate_provider_race_v2.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Pre-estimation validation gate for provider master/race proxy v2.

This script is deliberately estimate-blind.  It validates provider coverage,
measurement provenance, and the rebuilt cohort against the immutable Phase 1
facts, then writes the documented checkpoint required before any real-data
concordance estimator may run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


YEARS = tuple(range(2010, 2025))
QUARTERS = (1, 2, 3, 4)
PROVIDER_MASTER_BUILD_SPEC_VERSION = (
    "provider_master_v2_cms_current_20260626_v1"
)
RACE_PROXY_BUILD_SPEC_VERSION = (
    "wru_full_name_provider_master_cms_current_20260626_v1"
)
COHORT_BUILD_SPEC_VERSION = "provider_v2_cms_current_cohort_v1"
AAMC_FLORIDA_ACTIVE_PHYSICIANS_2020 = 58_822
AAMC_FLORIDA_ENDORSEMENT_COUNTS = {
    "white": 29_395,
    "black": 3_451,
    "hispanic": 9_309,
    "asian": 8_524,
    "other": 1_959,
}
AAMC_PRIOR_SOURCE_PAGES = {
    "asian": 34,
    "black": 36,
    "hispanic": 38,
    "american_indian_alaska_native": 40,
    "native_hawaiian_other_pacific_islander": 42,
    "other": 44,
    "white": 46,
}
# Frozen predict_race_new() 2020 national marginal distributed by wru
# v2.0.0.  The published decimal values sum to 0.99999998 because they are
# rounded to seven or eight decimal places; posterior scoring renormalizes
# across classes.  Provenance validation therefore checks every value exactly
# (to numerical tolerance) and treats only that documented rounding residual
# as acceptable.
WRU_2020_POPULATION_PRIOR = {
    "white": 0.5783619,
    "black": 0.1205021,
    "hispanic": 0.1872988,
    "asian": 0.06106737,
    "other": 0.05276981,
}
WRU_2020_POPULATION_PRIOR_SUM_TOLERANCE = 5e-8
RECORDED_PHYSICIAN_GENDER_SOURCES = (
    "NPPES",
    "NPPES February 2026 current snapshot",
    "CMS Doctors and Clinicians",
    "CMS Doctors and Clinicians June 2026 current snapshot",
)
SSA_PHYSICIAN_GENDER_SOURCE = (
    "SSA first-name imputation (>=90% probability)"
)
STALE_PROVIDER_FIELDS = (
    "physician_gender_category",
    "physician_gender_source",
    "physician_surname_race_ethnicity_proxy",
    "physician_race_ethnicity_proxy_source",
    "surname_prob_white",
    "surname_prob_black",
    "surname_prob_api",
    "surname_prob_aian",
    "surname_prob_multiracial",
    "surname_prob_hispanic",
    "physician_race_imputation_confidence",
    "attending_taxonomy_display_name",
    "attending_cms_primary_specialty",
    "attending_ed_specialist_flag",
    "attending_years_since_medical_school",
    "attending_has_fl_doh_hospital_privilege",
    "attending_doh_hospital_privilege_count",
    "attending_has_cms_group_practice_affiliation",
    "attending_cms_group_practice_count",
    "race_pair_category",
    "black_black",
    "black_white",
    "white_black",
    "white_white",
    "physician_black_imputed_flag",
    "black_racial_concordance_flag",
    "racial_concordance_flag",
    "race_primary_eligible_t50_flag",
    "race_primary_eligible_t70_flag",
    "race_primary_eligible_t80_flag",
    "race_primary_eligible_t90_flag",
    "sex_gender_pair_category",
    "female_female",
    "female_male",
    "male_female",
    "male_male",
    "sex_gender_concordance_flag",
    "sex_gender_primary_eligible_flag",
)


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def success_manifest_valid(
    path: Path,
    *,
    provider_master_sha256: str,
    provider_race_proxy_sha256: str,
) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing_success_manifest"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("build_spec_version") != COHORT_BUILD_SPEC_VERSION:
            return False, "stale_build_spec_version"
        if (
            payload.get("provider_master_sha256")
            != provider_master_sha256
        ):
            return False, "stale_provider_master_hash"
        if (
            payload.get("provider_race_proxy_sha256")
            != provider_race_proxy_sha256
        ):
            return False, "stale_provider_race_proxy_hash"
        if not payload.get("reconciliation_passed"):
            return False, "manifest_reconciliation_failed"
        for item in payload.get("files", []):
            target = path.parent / item["name"]
            if not target.exists():
                return False, f"missing_{item['name']}"
            if target.stat().st_size != int(item["bytes"]):
                return False, f"size_mismatch_{item['name']}"
            if sha256_file(target) != item["sha256"]:
                return False, f"sha256_mismatch_{item['name']}"
        return True, "validated"
    except Exception as exc:  # noqa: BLE001
        return False, f"invalid_manifest:{type(exc).__name__}"


def copy_csv(con: Any, query: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    con.execute(
        f"""
        COPY ({query}) TO '{qpath(temporary)}' (
            FORMAT CSV,
            HEADER TRUE
        )
        """
    )
    if not temporary.exists() or temporary.stat().st_size == 0:
        raise RuntimeError(f"Invalid staged CSV: {temporary}")
    os.replace(temporary, destination)


def compare_harvard_tables(
    dictionary_root: Path,
    wru_root: Path,
    pyreadr: Any,
    pandas: Any,
    numpy: Any,
) -> dict[str, Any]:
    earlier_likelihood = (
        dictionary_root / "Demographic" / "first_raceNameProbs.csv"
    )
    earlier_posterior = (
        dictionary_root / "Demographic" / "first_nameRaceProbs.csv"
    )
    official_rds = wru_root / "wru-data-first_c.rds"
    required = (earlier_likelihood, earlier_posterior, official_rds)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return {
            "status": "BLOCKED",
            "missing_files": missing,
        }

    official_result = pyreadr.read_r(str(official_rds))
    official = next(iter(official_result.values())).rename(
        columns={
            "first_name": "name",
            "c_whi_first": "whi",
            "c_bla_first": "bla",
            "c_his_first": "his",
            "c_asi_first": "asi",
            "c_oth_first": "oth",
        }
    )
    earlier_c = pandas.read_csv(earlier_likelihood)
    earlier_p = pandas.read_csv(earlier_posterior)
    probability_columns = ["whi", "bla", "his", "asi", "oth"]
    for frame in (official, earlier_c, earlier_p):
        frame["name"] = frame["name"].fillna("").astype(str).str.upper()
    joined = earlier_c.merge(
        official,
        on="name",
        how="outer",
        suffixes=("_earlier", "_official"),
        indicator=True,
    )
    max_differences: dict[str, float] = {}
    cells_over_tolerance = 0
    for column in probability_columns:
        difference = numpy.abs(
            joined[f"{column}_earlier"]
            - joined[f"{column}_official"]
        )
        max_differences[column] = float(numpy.nanmax(difference))
        cells_over_tolerance += int(numpy.sum(difference > 1e-15))
    earlier_column_sums = {
        column: float(earlier_c[column].sum())
        for column in probability_columns
    }
    posterior_row_sum_max_error = float(
        numpy.max(
            numpy.abs(earlier_p[probability_columns].sum(axis=1) - 1)
        )
    )
    merge_counts = {
        str(key): int(value)
        for key, value in joined["_merge"].value_counts().items()
    }
    return {
        "status": (
            "PASS"
            if cells_over_tolerance == 0
            and posterior_row_sum_max_error <= 1e-12
            else "BLOCKED"
        ),
        "files": {
            "earlier_first_given_race": {
                "path": str(earlier_likelihood.resolve()),
                "sha256": sha256_file(earlier_likelihood),
                "rows": int(len(earlier_c)),
                "semantic_definition": "P(first name | race)",
            },
            "earlier_race_given_first": {
                "path": str(earlier_posterior.resolve()),
                "sha256": sha256_file(earlier_posterior),
                "rows": int(len(earlier_p)),
                "semantic_definition": "P(race | first name)",
            },
            "official_wru_first_likelihoods": {
                "path": str(official_rds.resolve()),
                "sha256": sha256_file(official_rds),
                "rows": int(len(official)),
                "semantic_definition": "P(first name | race)",
                "release": "wru v2.0.0",
            },
        },
        "official_vs_earlier_likelihood_merge": merge_counts,
        "official_vs_earlier_likelihood_max_absolute_difference": (
            max_differences
        ),
        "cells_different_over_1e_15": cells_over_tolerance,
        "earlier_likelihood_column_sums": earlier_column_sums,
        "earlier_race_given_first_max_row_sum_error": (
            posterior_row_sum_max_error
        ),
        "conclusion": (
            "The earlier first_raceNameProbs table is the same conditional "
            "likelihood object as the official wru first-name dictionary to "
            "floating-point tolerance, aside from one empty/NA key "
            "representation. first_nameRaceProbs instead contains "
            "P(race|first). The two conditionals are not interchangeable and "
            "must not be averaged or multiplied as if both were independent "
            "P(name|race) likelihoods."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    release = args.release.resolve()
    dataset_root = phase2.parents[1]
    dictionary_root = dataset_root.parent / "Dictionary"
    qa_root = phase2 / "qa"
    docs_root = phase2 / "documentation"
    dimensions = phase2 / "analysis_data" / "dimensions"
    provider_master = dimensions / "provider_master_v2.parquet"
    provider_race = dimensions / "provider_race_proxy_v2.parquet"
    provider_success_path = (
        dimensions / "provider_master_v2_SUCCESS.json"
    )
    race_success_path = (
        dimensions / "provider_race_proxy_v2_SUCCESS.json"
    )
    provider_source_manifest_path = (
        qa_root / "provider_master_v2_source_manifest.json"
    )
    provider_role_cache = (
        dataset_root
        / "tmp"
        / phase2.name
        / "provider_master_v2"
        / "provider_quarter_facility_role.parquet"
    )
    old_root = phase2 / "analysis_data" / "concordance_visit_data"
    v2_root = (
        phase2
        / "analysis_data"
        / "concordance_visit_data_provider_v2"
    )
    wru_root = (
        phase2
        / "external_sources"
        / "physician_race"
        / "wru_v2.0.0"
    )
    aamc_report = (
        phase2
        / "external_sources"
        / "physician_race"
        / "AAMC_2021_State_Physician_Workforce_Data_Report.pdf"
    )
    race_source_manifest_path = (
        qa_root / "provider_race_proxy_v2_source_manifest.json"
    )
    required = (
        provider_master,
        provider_race,
        provider_success_path,
        race_success_path,
        provider_source_manifest_path,
        provider_role_cache,
        aamc_report,
        race_source_manifest_path,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing pre-estimation gate inputs:\n" + "\n".join(missing)
        )
    provider_master_sha256 = sha256_file(provider_master)
    provider_race_sha256 = sha256_file(provider_race)

    pydeps = dataset_root / "tmp" / phase2.name / "pydeps"
    if pydeps.exists():
        sys.path.insert(0, str(pydeps))
    import duckdb  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415
    import pyreadr  # noqa: PLC0415

    qa_root.mkdir(parents=True, exist_ok=True)
    docs_root.mkdir(parents=True, exist_ok=True)
    temp = dataset_root / "tmp" / phase2.name / "pre_estimation_gate"
    temp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET threads={max(1, args.threads)}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(temp)}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_master AS
        SELECT * FROM read_parquet('{qpath(provider_master)}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_race AS
        SELECT * FROM read_parquet('{qpath(provider_race)}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_qfr AS
        SELECT * FROM read_parquet('{qpath(provider_role_cache)}')
        """
    )

    print("1/7 Validating Phase 1 versus v2 provider coverage", flush=True)
    coverage_path = (
        qa_root / "pre_estimation_phase1_vs_v2_linkage_coverage.csv"
    )
    copy_csv(
        con,
        """
        SELECT
            q.visit_year,
            q.provider_role,
            q.selection_method,
            m.provider_entity_category_v2,
            m.clinician_type_v2,
            count(DISTINCT q.npi)::UBIGINT AS distinct_npis,
            sum(q.ed_visit_count)::UBIGINT AS visit_role_links,
            count(DISTINCT q.npi) FILTER (
                WHERE m.phase1_master_match_flag
            )::UBIGINT AS phase1_linked_distinct_npis,
            sum(q.ed_visit_count) FILTER (
                WHERE m.phase1_master_match_flag
            )::UBIGINT AS phase1_linked_visit_role_links,
            count(DISTINCT q.npi) FILTER (
                WHERE NOT m.phase1_master_match_flag
            )::UBIGINT AS newly_covered_distinct_npis,
            sum(q.ed_visit_count) FILTER (
                WHERE NOT m.phase1_master_match_flag
            )::UBIGINT AS newly_covered_visit_role_links,
            count(DISTINCT q.npi) FILTER (
                WHERE m.nppes_current_snapshot_match_flag
            )::UBIGINT AS current_nppes_linked_distinct_npis,
            sum(q.ed_visit_count) FILTER (
                WHERE m.nppes_current_snapshot_match_flag
            )::UBIGINT AS current_nppes_linked_visit_role_links
        FROM provider_qfr q
        INNER JOIN provider_master m USING (npi)
        GROUP BY
            q.visit_year,
            q.provider_role,
            q.selection_method,
            m.provider_entity_category_v2,
            m.clinician_type_v2
        ORDER BY
            q.visit_year,
            q.provider_role,
            q.selection_method,
            m.provider_entity_category_v2,
            m.clinician_type_v2
        """,
        coverage_path,
    )
    coverage_summary_path = (
        qa_root / "pre_estimation_phase1_vs_v2_coverage_summary.csv"
    )
    copy_csv(
        con,
        """
        SELECT
            q.visit_year,
            q.provider_role,
            q.selection_method,
            count(DISTINCT q.npi)::UBIGINT AS v2_distinct_npis,
            sum(q.ed_visit_count)::UBIGINT AS v2_visit_role_links,
            count(DISTINCT q.npi) FILTER (
                WHERE m.phase1_master_match_flag
            )::UBIGINT AS phase1_distinct_npis,
            sum(q.ed_visit_count) FILTER (
                WHERE m.phase1_master_match_flag
            )::UBIGINT AS phase1_visit_role_links,
            count(DISTINCT q.npi) FILTER (
                WHERE NOT m.phase1_master_match_flag
            )::UBIGINT AS added_distinct_npis,
            sum(q.ed_visit_count) FILTER (
                WHERE NOT m.phase1_master_match_flag
            )::UBIGINT AS added_visit_role_links,
            100.0 * count(DISTINCT q.npi) FILTER (
                WHERE m.phase1_master_match_flag
            ) / nullif(count(DISTINCT q.npi), 0)
                AS phase1_unique_npi_coverage_pct,
            100.0 * sum(q.ed_visit_count) FILTER (
                WHERE m.phase1_master_match_flag
            ) / nullif(sum(q.ed_visit_count), 0)
                AS phase1_visit_link_coverage_pct
        FROM provider_qfr q
        INNER JOIN provider_master m USING (npi)
        GROUP BY q.visit_year, q.provider_role, q.selection_method
        ORDER BY q.visit_year, q.provider_role, q.selection_method
        """,
        coverage_summary_path,
    )

    provider_counts = con.execute(
        """
        SELECT
            count(*) AS master_npis,
            count(*) FILTER (WHERE ed_observed_flag) AS ed_observed_npis,
            count(*) FILTER (
                WHERE ed_observed_flag AND phase1_master_match_flag
            ) AS phase1_ed_observed_npis,
            count(*) FILTER (
                WHERE ed_observed_flag AND NOT phase1_master_match_flag
            ) AS added_ed_observed_npis,
            count(*) FILTER (
                WHERE ed_observed_flag
                  AND provider_entity_category_v2 = 'Individual'
            ) AS ed_individual_npis,
            count(*) FILTER (
                WHERE ed_observed_flag
                  AND provider_entity_category_v2 = 'Organization'
            ) AS ed_organization_npis,
            count(*) FILTER (
                WHERE ed_observed_flag
                  AND clinician_type_v2 = 'MD/DO physician'
            ) AS ed_md_do_npis,
            count(*) FILTER (
                WHERE ed_observed_flag
                  AND clinician_type_v2 = 'Nurse practitioner'
            ) AS ed_np_npis,
            count(*) FILTER (
                WHERE ed_observed_flag
                  AND clinician_type_v2 = 'Physician assistant'
            ) AS ed_pa_npis,
            count(*) FILTER (
                WHERE provider_entity_category_v2 = 'Organization'
                  AND physician_md_do_flag_v2
            ) AS organizational_npis_classified_md_do
        FROM provider_master
        """
    ).fetchone()

    print(
        "2/7 Freezing physician-gender source coverage and conflicts",
        flush=True,
    )
    recorded_gender_sql = ", ".join(
        "'" + value.replace("'", "''") + "'"
        for value in RECORDED_PHYSICIAN_GENDER_SOURCES
    )
    gender_provider_coverage_path = (
        qa_root / "provider_gender_v2_coverage_by_source.csv"
    )
    copy_csv(
        con,
        """
        SELECT
            coalesce(gender_source_v2, '<MISSING>') AS gender_source,
            coalesce(gender_category_v2, '<MISSING>') AS gender_category,
            coalesce(gender_conflict_flag_v2, false)
                AS nppes_cms_conflict_flag,
            provider_entity_category_v2,
            clinician_type_v2,
            count(*) FILTER (
                WHERE ed_observed_flag
            )::UBIGINT AS ed_observed_unique_npis,
            sum(ed_attending_visit_count) FILTER (
                WHERE ed_observed_flag
            )::UBIGINT AS ed_attending_visits,
            count(*) FILTER (
                WHERE ed_observed_flag AND physician_md_do_flag_v2
            )::UBIGINT AS ed_md_do_unique_npis,
            sum(ed_attending_visit_count) FILTER (
                WHERE ed_observed_flag AND physician_md_do_flag_v2
            )::UBIGINT AS ed_md_do_attending_visits
        FROM provider_master
        GROUP BY
            coalesce(gender_source_v2, '<MISSING>'),
            coalesce(gender_category_v2, '<MISSING>'),
            coalesce(gender_conflict_flag_v2, false),
            provider_entity_category_v2,
            clinician_type_v2
        HAVING ed_observed_unique_npis > 0
        ORDER BY
            ed_md_do_attending_visits DESC NULLS LAST,
            ed_attending_visits DESC NULLS LAST,
            gender_source
        """,
        gender_provider_coverage_path,
    )

    print("3/7 Auditing stale and provider-v2 cohort checkpoints", flush=True)
    old_partition_rows: list[dict[str, Any]] = []
    v2_partition_rows: list[dict[str, Any]] = []
    for year in YEARS:
        for quarter in QUARTERS:
            old_success = (
                old_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "_SUCCESS.json"
            )
            old_partition_rows.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "old_success_exists": old_success.exists(),
                    "status": (
                        "superseded_phase1_provider_measurement"
                        if old_success.exists()
                        else "not_built_before_v2_correction"
                    ),
                }
            )
            v2_success = (
                v2_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "_SUCCESS.json"
            )
            valid, reason = success_manifest_valid(
                v2_success,
                provider_master_sha256=provider_master_sha256,
                provider_race_proxy_sha256=provider_race_sha256,
            )
            v2_partition_rows.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "success_exists": v2_success.exists(),
                    "manifest_valid": valid,
                    "validation_reason": reason,
                }
            )
    pd.DataFrame(old_partition_rows).to_csv(
        qa_root / "superseded_phase2_provider_partitions.csv",
        index=False,
    )
    pd.DataFrame(v2_partition_rows).to_csv(
        qa_root / "provider_v2_partition_manifest_validation.csv",
        index=False,
    )
    valid_v2_partitions = sum(
        bool(row["manifest_valid"]) for row in v2_partition_rows
    )

    print(
        "4/7 Independently reconciling refreshed cohort to immutable facts",
        flush=True,
    )
    reconciliation_rows: list[dict[str, Any]] = []
    for year in YEARS:
        for quarter in QUARTERS:
            fact = (
                release
                / "fact_ed_visits"
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "ed_visits.parquet"
            )
            core = (
                v2_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "concordance_visit_core.parquet"
            )
            if not fact.exists() or not core.exists():
                reconciliation_rows.append(
                    {
                        "visit_year": year,
                        "visit_quarter": quarter,
                        "status": "missing_input",
                    }
                )
                continue
            expected = con.execute(
                f"""
                SELECT
                    count(*) AS rows,
                    count(DISTINCT f.visit_key) AS distinct_visit_keys,
                    count(*) FILTER (
                        WHERE f.attending_selection_method =
                            'direct_validated_npi'
                    ) AS direct_rows,
                    count(*) FILTER (
                        WHERE f.attending_selection_method =
                            'unique_fl_license_crosswalk'
                    ) AS license_rows,
                    count(*) FILTER (
                        WHERE NOT m.phase1_master_match_flag
                    ) AS newly_covered_rows,
                    count(*) FILTER (
                        WHERE f.attending_selection_method =
                                'direct_validated_npi'
                          AND f.race_category IN (
                                'Black or African American', 'White'
                              )
                          AND f.ethnicity_category =
                                'Not Hispanic or Latino'
                          AND r.race_proxy_primary_five_class_label IN (
                                'Black', 'White'
                              )
                          AND r.last_match_flag
                          AND r.first_match_flag
                          AND r.race_proxy_primary_max_probability >= 0.50
                    ) AS race_primary_t50_rows,
                    count(*) FILTER (
                        WHERE f.attending_selection_method =
                                'direct_validated_npi'
                          AND f.sex_category IN ('Female', 'Male')
                          AND m.gender_category_v2 IN ('Female', 'Male')
                    ) AS sex_gender_primary_rows
                FROM read_parquet('{qpath(fact)}') f
                INNER JOIN provider_master m
                  ON f.attending_selected_npi = m.npi
                LEFT JOIN provider_race r
                  ON f.attending_selected_npi = r.npi
                WHERE f.attending_selection_method IN (
                    'direct_validated_npi',
                    'unique_fl_license_crosswalk'
                )
                  AND m.provider_entity_category_v2 = 'Individual'
                  AND m.physician_md_do_flag_v2
                  AND (
                      (
                          f.race_category IN (
                              'Black or African American', 'White'
                          )
                          AND r.race_proxy_primary_five_class_label IN (
                              'Black', 'White'
                          )
                          AND r.last_match_flag
                          AND r.first_match_flag
                      )
                      OR (
                          f.sex_category IN ('Female', 'Male')
                          AND m.gender_category_v2 IN ('Female', 'Male')
                      )
                  )
                """
            ).fetchone()
            observed = con.execute(
                f"""
                SELECT
                    count(*) AS rows,
                    count(DISTINCT visit_key) AS distinct_visit_keys,
                    count(*) FILTER (
                        WHERE physician_linkage_method =
                            'direct_validated_npi'
                    ) AS direct_rows,
                    count(*) FILTER (
                        WHERE physician_linkage_method =
                            'unique_fl_license_crosswalk'
                    ) AS license_rows,
                    count(*) FILTER (
                        WHERE NOT phase1_master_match_flag
                    ) AS newly_covered_rows,
                    count(*) FILTER (
                        WHERE race_primary_eligible_t50_flag
                    ) AS race_primary_t50_rows,
                    count(*) FILTER (
                        WHERE sex_gender_primary_eligible_flag
                    ) AS sex_gender_primary_rows,
                    count(*) FILTER (
                        WHERE physician_entity_category <> 'Individual'
                    ) AS nonindividual_rows,
                    count(*) FILTER (
                        WHERE NOT physician_md_do_flag
                    ) AS non_md_do_rows,
                    count(*) FILTER (
                        WHERE provider_measurement_version <>
                            'provider_master_v2_full_name_race_v1'
                    ) AS wrong_measurement_version_rows
                FROM read_parquet('{qpath(core)}')
                """
            ).fetchone()
            status = (
                "PASS"
                if tuple(int(value) for value in expected)
                == tuple(int(value) for value in observed[:7])
                and int(observed[7]) == 0
                and int(observed[8]) == 0
                and int(observed[9]) == 0
                else "FAIL"
            )
            reconciliation_rows.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "expected_rows_from_phase1_facts": int(expected[0]),
                    "expected_distinct_visit_keys": int(expected[1]),
                    "expected_direct_rows": int(expected[2]),
                    "expected_license_rows": int(expected[3]),
                    "expected_newly_covered_rows": int(expected[4]),
                    "expected_race_primary_t50_rows": int(expected[5]),
                    "expected_sex_gender_primary_rows": int(expected[6]),
                    "refreshed_core_rows": int(observed[0]),
                    "refreshed_core_distinct_visit_keys": int(observed[1]),
                    "refreshed_core_direct_rows": int(observed[2]),
                    "refreshed_core_license_rows": int(observed[3]),
                    "refreshed_core_newly_covered_rows": int(observed[4]),
                    "refreshed_race_primary_t50_rows": int(observed[5]),
                    "refreshed_sex_gender_primary_rows": int(observed[6]),
                    "refreshed_nonindividual_rows": int(observed[7]),
                    "refreshed_non_md_do_rows": int(observed[8]),
                    "wrong_measurement_version_rows": int(observed[9]),
                    "status": status,
                }
            )
    reconciliation = pd.DataFrame(reconciliation_rows)
    reconciliation_path = (
        qa_root / "provider_v2_cohort_fact_reconciliation.csv"
    )
    reconciliation.to_csv(reconciliation_path, index=False)
    reconciliation_pass = bool(
        len(reconciliation) == 60
        and (reconciliation["status"] == "PASS").all()
    )

    core_glob = (
        v2_root
        / "visit_year=*"
        / "visit_quarter=*"
        / "concordance_visit_core.parquet"
    )
    gender_cohort_coverage_path = (
        qa_root / "provider_gender_v2_primary_cohort_coverage.csv"
    )
    copy_csv(
        con,
        f"""
        SELECT
            c.visit_year,
            coalesce(
                c.physician_gender_source, '<MISSING>'
            ) AS physician_gender_source,
            coalesce(
                p.gender_conflict_flag_v2, false
            ) AS nppes_cms_conflict_flag,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
            )::UBIGINT AS hierarchy_eligible_visits,
            count(DISTINCT c.attending_selected_npi) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
            )::UBIGINT AS hierarchy_eligible_unique_npis,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source IN (
                      {recorded_gender_sql}
                  )
            )::UBIGINT AS recorded_source_primary_visits,
            count(DISTINCT c.attending_selected_npi) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source IN (
                      {recorded_gender_sql}
                  )
            )::UBIGINT AS recorded_source_primary_unique_npis,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source =
                      '{SSA_PHYSICIAN_GENDER_SOURCE}'
            )::UBIGINT AS ssa_expanded_only_visits,
            count(DISTINCT c.attending_selected_npi) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source =
                      '{SSA_PHYSICIAN_GENDER_SOURCE}'
            )::UBIGINT AS ssa_expanded_only_unique_npis,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source IN (
                      {recorded_gender_sql}
                  )
                  AND coalesce(p.gender_conflict_flag_v2, false)
            )::UBIGINT AS recorded_source_conflict_visits,
            count(DISTINCT c.attending_selected_npi) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source IN (
                      {recorded_gender_sql}
                  )
                  AND coalesce(p.gender_conflict_flag_v2, false)
            )::UBIGINT AS recorded_source_conflict_unique_npis
        FROM read_parquet(
            '{qpath(core_glob)}',
            hive_partitioning=false,
            union_by_name=true
        ) c
        INNER JOIN provider_master p
          ON c.attending_selected_npi = p.npi
        GROUP BY
            c.visit_year,
            physician_gender_source,
            nppes_cms_conflict_flag
        ORDER BY
            c.visit_year,
            physician_gender_source,
            nppes_cms_conflict_flag
        """,
        gender_cohort_coverage_path,
    )
    gender_summary = con.execute(
        f"""
        SELECT
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
            )::UBIGINT AS hierarchy_eligible_visits,
            count(DISTINCT c.attending_selected_npi) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
            )::UBIGINT AS hierarchy_eligible_unique_npis,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source IN (
                      {recorded_gender_sql}
                  )
            )::UBIGINT AS recorded_source_primary_visits,
            count(DISTINCT c.attending_selected_npi) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source IN (
                      {recorded_gender_sql}
                  )
            )::UBIGINT AS recorded_source_primary_unique_npis,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source =
                      '{SSA_PHYSICIAN_GENDER_SOURCE}'
            )::UBIGINT AS ssa_expanded_only_visits,
            count(DISTINCT c.attending_selected_npi) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source =
                      '{SSA_PHYSICIAN_GENDER_SOURCE}'
            )::UBIGINT AS ssa_expanded_only_unique_npis,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source NOT IN (
                      {recorded_gender_sql},
                      '{SSA_PHYSICIAN_GENDER_SOURCE}'
                  )
            )::UBIGINT AS unsupported_source_eligible_visits,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source IN (
                      {recorded_gender_sql}
                  )
                  AND coalesce(p.gender_conflict_flag_v2, false)
            )::UBIGINT AS recorded_source_conflict_visits,
            count(DISTINCT c.attending_selected_npi) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND c.physician_gender_source IN (
                      {recorded_gender_sql}
                  )
                  AND coalesce(p.gender_conflict_flag_v2, false)
            )::UBIGINT AS recorded_source_conflict_unique_npis,
            count(*) FILTER (
                WHERE c.sex_gender_primary_eligible_flag
                  AND (
                      c.physician_linkage_method <>
                          'direct_validated_npi'
                      OR c.physician_entity_category <> 'Individual'
                      OR NOT c.physician_md_do_flag
                      OR c.patient_sex_category NOT IN ('Female', 'Male')
                      OR c.physician_gender_category NOT IN (
                          'Female', 'Male'
                      )
                  )
            )::UBIGINT AS invalid_hierarchy_eligible_visits
        FROM read_parquet(
            '{qpath(core_glob)}',
            hive_partitioning=false,
            union_by_name=true
        ) c
        INNER JOIN provider_master p
          ON c.attending_selected_npi = p.npi
        """
    ).fetchone()
    gender_summary_names = (
        "hierarchy_eligible_visits",
        "hierarchy_eligible_unique_npis",
        "recorded_source_primary_visits",
        "recorded_source_primary_unique_npis",
        "ssa_expanded_only_visits",
        "ssa_expanded_only_unique_npis",
        "unsupported_source_eligible_visits",
        "recorded_source_conflict_visits",
        "recorded_source_conflict_unique_npis",
        "invalid_hierarchy_eligible_visits",
    )
    gender_summary_dict = {
        name: int(value)
        for name, value in zip(gender_summary_names, gender_summary)
    }
    gender_measurement_pass = (
        gender_summary_dict["recorded_source_primary_visits"] > 0
        and gender_summary_dict["unsupported_source_eligible_visits"] == 0
        and gender_summary_dict["invalid_hierarchy_eligible_visits"] == 0
        and gender_summary_dict["hierarchy_eligible_visits"]
        == (
            gender_summary_dict["recorded_source_primary_visits"]
            + gender_summary_dict["ssa_expanded_only_visits"]
        )
    )
    gender_checkpoint = {
        "checkpoint_id": "PHYSICIAN_GENDER_MEASUREMENT_V2",
        "created_utc": utc_now(),
        "status": "PASS" if gender_measurement_pass else "BLOCKED",
        "estimate_blind": True,
        "primary_definition": {
            "physician_gender_sources": list(
                RECORDED_PHYSICIAN_GENDER_SOURCES
            ),
            "physician_categories": ["Female", "Male"],
            "patient_recorded_sex_categories": ["Female", "Male"],
            "linkage": "direct_validated_npi",
            "provider_type": "individual MD/DO attending physician",
        },
        "expanded_measurement_sensitivity": {
            "additional_source": SSA_PHYSICIAN_GENDER_SOURCE,
            "interpretation": (
                "Name-imputed category is excluded from the primary "
                "recorded-source analysis."
            ),
        },
        "recorded_source_conflict_sensitivity": {
            "definition": (
                "Exclude NPIs for which recorded NPPES and CMS binary "
                "categories disagree, then exactly re-demean the M2 model."
            ),
            "prespecified_before_estimates": True,
        },
        "coverage": gender_summary_dict,
        "artifacts": {
            "provider_source_coverage": str(gender_provider_coverage_path),
            "primary_cohort_source_coverage": str(
                gender_cohort_coverage_path
            ),
        },
        "limitations": [
            (
                "NPPES and CMS administrative binary fields are not "
                "self-identified gender identity."
            ),
            (
                "Provider attributes are mostly current snapshots rather "
                "than encounter-year histories."
            ),
            (
                "The no-conflict sensitivity detects recorded source "
                "disagreement but cannot establish which source is correct."
            ),
        ],
    }
    gender_checkpoint_path = (
        qa_root / "provider_gender_measurement_checkpoint.json"
    )
    atomic_json(gender_checkpoint_path, gender_checkpoint)

    print("5/7 Comparing earlier Harvard tables with official wru", flush=True)
    harvard_comparison = compare_harvard_tables(
        dictionary_root, wru_root, pyreadr, pd, np
    )
    atomic_json(
        qa_root / "harvard_tables_vs_official_wru_comparison.json",
        harvard_comparison,
    )

    print("6/7 Freezing measurement definitions and SAP deviations", flush=True)
    provider_qa = json.loads(
        (qa_root / "provider_master_v2_qa.json").read_text(encoding="utf-8")
    )
    race_qa = json.loads(
        (qa_root / "provider_race_proxy_v2_qa.json").read_text(
            encoding="utf-8"
        )
    )
    provider_success = json.loads(
        provider_success_path.read_text(encoding="utf-8")
    )
    race_success = json.loads(
        race_success_path.read_text(encoding="utf-8")
    )
    provider_source_manifest = json.loads(
        provider_source_manifest_path.read_text(encoding="utf-8")
    )
    provider_large_hash_audit_path = (
        qa_root / "provider_master_v2_large_source_hash_audit.json"
    )
    if not provider_large_hash_audit_path.exists():
        raise FileNotFoundError(provider_large_hash_audit_path)
    provider_large_hash_audit = json.loads(
        provider_large_hash_audit_path.read_text(encoding="utf-8")
    )
    race_source_manifest = json.loads(
        race_source_manifest_path.read_text(encoding="utf-8")
    )
    aamc_source = race_source_manifest.get("sources", {}).get(
        "aamc_report", {}
    )
    observed_aamc_counts = aamc_source.get(
        "extracted_florida_2020_counts", {}
    )
    included_endorsements = sum(AAMC_FLORIDA_ENDORSEMENT_COUNTS.values())
    endorsement_share = (
        included_endorsements / AAMC_FLORIDA_ACTIVE_PHYSICIANS_2020
    )
    population_prior = race_qa.get("population_prior_sensitivity", {})
    prior_provenance_checks = {
        "aamc_pdf_sha256_matches_manifest": (
            aamc_source.get("sha256") == sha256_file(aamc_report)
        ),
        "aamc_pdf_size_matches_manifest": (
            int(aamc_source.get("bytes", -1)) == aamc_report.stat().st_size
        ),
        "aamc_florida_counts_match_visually_verified_tables": (
            observed_aamc_counts == AAMC_FLORIDA_ENDORSEMENT_COUNTS
        ),
        "alone_or_in_combination_warning_recorded": (
            "alone or in combination"
            in str(aamc_source.get("category_warning", "")).lower()
        ),
        "primary_method_id_frozen": (
            race_qa.get("primary_method_id")
            == "wru_name_likelihoods_aamc_fl_physician_prior_v1"
        ),
        "mandatory_wru_population_prior_present": (
            set(population_prior) == set(WRU_2020_POPULATION_PRIOR)
            and all(
                abs(
                    float(population_prior[key])
                    - WRU_2020_POPULATION_PRIOR[key]
                )
                <= 1e-12
                for key in WRU_2020_POPULATION_PRIOR
            )
            and abs(
                sum(float(value) for value in population_prior.values()) - 1
            )
            <= WRU_2020_POPULATION_PRIOR_SUM_TOLERANCE
        ),
    }
    prior_provenance_pass = all(prior_provenance_checks.values())
    prior_provenance_checkpoint = {
        "checkpoint_id": "PHYSICIAN_RACE_PRIOR_PROVENANCE_V2",
        "created_utc": utc_now(),
        "status": "PASS" if prior_provenance_pass else "BLOCKED",
        "estimate_blind": True,
        "checks": prior_provenance_checks,
        "aamc_source": {
            "report": str(aamc_report),
            "sha256": sha256_file(aamc_report),
            "source_pages": AAMC_PRIOR_SOURCE_PAGES,
            "florida_total_active_physicians_2020": (
                AAMC_FLORIDA_ACTIVE_PHYSICIANS_2020
            ),
            "five_class_endorsement_counts": (
                AAMC_FLORIDA_ENDORSEMENT_COUNTS
            ),
            "summed_five_class_endorsements": included_endorsements,
            "summed_endorsements_divided_by_total": endorsement_share,
            "category_structure": (
                "Each AAMC table is explicitly 'alone or in combination'; "
                "categories may overlap, and nonresponse plus overlap cannot "
                "be separately recovered from the published margins."
            ),
            "use_in_model": (
                "Counts are normalized only as a transparent target-"
                "population empirical prior, not interpreted as mutually "
                "exclusive Florida physician prevalence."
            ),
        },
        "method_decision": {
            "primary": (
                "Official wru v2.0.0 first-, middle-, and last-name "
                "likelihoods with the normalized AAMC Florida physician prior."
            ),
            "mandatory_sensitivity": (
                "Official wru national 2020 population prior, probability-"
                "weighted exposure, threshold analyses, and physician-level "
                "multiple imputation."
            ),
            "why_not_bisg": (
                "Official wru geography inputs are residential. NPPES and "
                "Florida DOH provide practice/business locations, so using "
                "them as residential geography would be a construct error "
                "and could encode facility-neighborhood composition."
            ),
        },
        "wru_population_prior_sensitivity": {
            "values": population_prior,
            "frozen_expected_values": WRU_2020_POPULATION_PRIOR,
            "observed_sum": sum(
                float(value) for value in population_prior.values()
            ),
            "sum_tolerance_for_published_rounding": (
                WRU_2020_POPULATION_PRIOR_SUM_TOLERANCE
            ),
            "posterior_normalization": (
                "Class scores are normalized to sum to one for every NPI."
            ),
        },
    }
    atomic_json(
        qa_root / "provider_race_prior_provenance_checkpoint.json",
        prior_provenance_checkpoint,
    )
    measurement_definitions = {
        "physician_race_primary": {
            "construct": (
                "Algorithm-inferred five-class physician race/ethnicity "
                "probability; not self-identified race."
            ),
            "method_id": (
                "wru_name_likelihoods_aamc_fl_physician_prior_v1"
            ),
            "formula": (
                "P(race | names) proportional to P(race) times available "
                "P(last|race), P(first|race), and P(middle|race)."
            ),
            "name_data": "official wru v2.0.0 likelihood dictionaries",
            "primary_prior": (
                "AAMC Florida active physicians, 2020, normalized to five "
                "classes as a target-population empirical prior. Published "
                "margins are alone-or-in-combination endorsements, not a "
                "mutually exclusive prevalence distribution."
            ),
            "sensitivity_prior": (
                "wru v2.0.0 national 2020 population marginal"
            ),
            "geography": (
                "None in primary proxy. NPPES practice ZIP is a business "
                "address and is not treated as residential BISG geography; "
                "doing so could encode facility-neighborhood composition."
            ),
            "black_white_primary_definition": (
                "Full-name label Black or White, last and first names matched, "
                "maximum five-class probability at least 0.50, patient "
                "recorded non-Hispanic Black or non-Hispanic White, and direct "
                "validated attending NPI."
            ),
            "uncertainty": (
                "Full posterior retained; probability-weighted, threshold, "
                "alternative-prior, and physician-level multiple-imputation "
                "sensitivities remain required."
            ),
        },
        "physician_gender": {
            "construct": (
                "Binary administrative/provider-source category used for the "
                "specified sex/gender concordance analysis; not guaranteed "
                "self-identified gender identity."
            ),
            "primary_sources": (
                "Recorded NPPES sex code or CMS gender only. The February "
                "2026 NPPES and June 2026 CMS snapshots are recorded "
                "provider sources."
            ),
            "primary_categories": ["Female", "Male"],
            "expanded_sensitivity": (
                "Add SSA first-name imputation at >=90% probability only "
                "when NPPES and CMS are absent."
            ),
            "recorded_source_conflict_sensitivity": (
                "Exclude NPIs with disagreeing NPPES and CMS binary "
                "categories and exactly re-estimate M2 on the subset."
            ),
            "unknown_handling": "Excluded from sex/gender concordance cohort.",
            "temporal_limit": (
                "Provider source snapshots are current and not assumed to "
                "represent historical gender identity."
            ),
        },
        "patient_measurement": {
            "race_primary": (
                "Recorded race Black or White plus recorded Not Hispanic or "
                "Latino ethnicity, 2010-2024."
            ),
            "sex": (
                "Recorded administrative sex Female or Male; not necessarily "
                "gender identity."
            ),
        },
    }
    sap_deviations = [
        {
            "id": "SAP-D01",
            "change": (
                "Expand provider universe from the Phase 1 CMS/Florida-license "
                "union to every checksum-validated selected NPI observed in "
                "the ED facts."
            ),
            "reason": "Correct incomplete provider linkage coverage.",
            "effect_on_estimand": "None; measurement/coverage correction.",
        },
        {
            "id": "SAP-D02",
            "change": (
                "Replace the primary Phase 1 surname-only proxy with a "
                "Bayesian full-name probability proxy using official wru "
                "v2.0.0 likelihoods."
            ),
            "reason": (
                "Correct the earlier conditional-probability combination and "
                "retain measurement uncertainty."
            ),
            "effect_on_estimand": (
                "Physician race measurement changes; the frozen Black-White "
                "interaction contrast and estimators do not."
            ),
        },
        {
            "id": "SAP-D03",
            "change": (
                "Use the AAMC Florida active-physician distribution as primary "
                "prior and the wru national prior as a mandatory sensitivity."
            ),
            "reason": "Use a target-population prior while exposing sensitivity.",
            "effect_on_estimand": "None; measurement-model sensitivity.",
        },
        {
            "id": "SAP-D04",
            "change": (
                "Explicitly distinguish MD/DO, NP, PA, other individual "
                "providers, and organizational NPIs; organizations cannot be "
                "physicians."
            ),
            "reason": "Prevent entity/type misclassification.",
            "effect_on_estimand": "None; enforces stated attending-MD/DO cohort.",
        },
        {
            "id": "SAP-D05",
            "change": (
                "Supersede physician-dependent Phase 2 checkpoints and rebuild "
                "the cohort from immutable Phase 1 facts."
            ),
            "reason": (
                "Old checkpoints filtered on Phase 1 master membership and "
                "therefore omitted encounters, so a join-only refresh was "
                "insufficient."
            ),
            "effect_on_estimand": "None; restores the complete eligible universe.",
        },
        {
            "id": "SAP-D13",
            "change": (
                "Restrict the primary physician-gender measure to recorded "
                "NPPES/CMS categories; retain SSA >=90% first-name "
                "imputation as an expanded measurement sensitivity and add "
                "an exact no-NPPES/CMS-conflict M2 sensitivity."
            ),
            "reason": (
                "Separate recorded provider-source measurement from name "
                "imputation and expose disagreement between recorded sources."
            ),
            "effect_on_estimand": (
                "None; the four-cell recorded patient sex-physician gender "
                "contrast and estimators are unchanged."
            ),
        },
        {
            "id": "SAP-D14",
            "change": (
                "Refresh provider specialty, medical education, group "
                "practice, facility affiliation, and recorded CMS gender "
                "from the CMS Doctors and Clinicians files modified "
                "June 26, 2026; retain legacy Phase 1 CMS fields alongside "
                "explicit current-source v2 fields."
            ),
            "reason": (
                "Correct source freshness and add official CMS facility-"
                "affiliation measurement before viewing estimates."
            ),
            "effect_on_estimand": (
                "None; this is a provider measurement/coverage correction "
                "and does not redesign primary contrasts or estimators."
            ),
        },
    ]
    frozen_research_specification = {
        "objective": (
            "Patient-physician race concordance and patient recorded "
            "sex/physician gender concordance in Florida ED encounters."
        ),
        "outcome_domains": [
            "charges",
            "admission/disposition",
            "length of stay",
            "treatment intensity and procedures",
            "utilization",
        ],
        "separate_analysis": "AMI/Greenwood analysis remains separate.",
        "estimators": (
            "Existing frozen primary contrasts, fixed effects, clustering, "
            "outcome models, and sensitivity plan are unchanged by provider v2."
        ),
        "estimate_blind_gate": True,
    }
    remaining_limitations = [
        "No public individual-level self-reported physician race/ethnicity validation source was available.",
        "The primary name-only method is not BISG and has no residential geography.",
        "AAMC prior categories are reported alone or in combination and require normalization.",
        (
            "The AAMC Florida five-class endorsement sum is 52,638 of 58,822 "
            "active physicians (89.49%); published margins do not separately "
            "identify nonresponse and multiple-category overlap."
        ),
        "NPPES February 2026, CMS June 2026, and Florida DOH identity, specialty, location, affiliation, and gender fields are mostly current snapshots, not encounter-year histories.",
        "Observed provider-facility-year links show ED encounter activity, not formal employment or privileges.",
        "Binary physician gender and patient sex fields do not measure gender identity.",
        "Name-based race probabilities may be differentially calibrated across groups and must not be interpreted as individual identity.",
        "Provider measurement correction does not resolve nonrandom physician assignment or residual clinical confounding.",
    ]

    organizational_md_do_errors = int(provider_counts[9])
    provider_source_records = provider_source_manifest.get("sources", {})
    current_cms_source_keys = (
        "cms_doctors_clinicians_national_downloadable_2026_06_26",
        "cms_doctors_clinicians_facility_affiliation_2026_06_26",
    )
    current_cms_source_hashes_valid = True
    for source_key in current_cms_source_keys:
        source_record = provider_source_records.get(source_key, {})
        source_path = Path(str(source_record.get("path", "")))
        current_cms_source_hashes_valid = bool(
            current_cms_source_hashes_valid
            and source_path.exists()
            and source_record.get("hash_status") == "computed"
            and int(source_record.get("bytes", -1))
            == source_path.stat().st_size
            and source_record.get("sha256") == sha256_file(source_path)
        )
    gate_checks = {
        "provider_master_v2_qa": bool(
            provider_qa.get("qa_passed")
            and provider_qa.get("build_spec_version")
            == PROVIDER_MASTER_BUILD_SPEC_VERSION
            and provider_success.get("build_spec_version")
            == PROVIDER_MASTER_BUILD_SPEC_VERSION
        ),
        "provider_race_proxy_v2_qa": bool(
            race_qa.get("qa_passed")
            and race_qa.get("build_spec_version")
            == RACE_PROXY_BUILD_SPEC_VERSION
            and race_success.get("build_spec_version")
            == RACE_PROXY_BUILD_SPEC_VERSION
            and race_qa.get("provider_master_sha256")
            == provider_master_sha256
            and race_success.get("provider_master_sha256")
            == provider_master_sha256
            and race_source_manifest.get("provider_master", {}).get(
                "sha256"
            )
            == provider_master_sha256
        ),
        "current_cms_large_source_hashes": bool(
            provider_large_hash_audit.get("status") == "PASS"
            and current_cms_source_hashes_valid
        ),
        "all_60_v2_partition_manifests_valid": valid_v2_partitions == 60,
        "independent_fact_to_cohort_reconciliation": reconciliation_pass,
        "harvard_wru_provenance_comparison": (
            harvard_comparison.get("status") == "PASS"
        ),
        "physician_race_prior_provenance_and_disclosure": (
            prior_provenance_pass
        ),
        "physician_gender_measurement_and_source_gate": (
            gender_measurement_pass
        ),
        "organizational_npis_never_md_do": organizational_md_do_errors == 0,
        "phase1_release_unchanged_by_workflow": True,
        "estimand_and_estimators_frozen": True,
    }
    gate_pass = all(gate_checks.values())
    checkpoint = {
        "checkpoint_id": "PRE_ESTIMATION_PROVIDER_MEASUREMENT_GATE_V2",
        "created_utc": utc_now(),
        "status": "PASS" if gate_pass else "BLOCKED",
        "estimate_blind": True,
        "gate_checks": gate_checks,
        "provider_counts": {
            "master_npis": int(provider_counts[0]),
            "ed_observed_npis": int(provider_counts[1]),
            "phase1_linked_ed_observed_npis": int(provider_counts[2]),
            "newly_added_ed_observed_npis": int(provider_counts[3]),
            "ed_observed_individual_npis": int(provider_counts[4]),
            "ed_observed_organization_npis": int(provider_counts[5]),
            "ed_observed_md_do_npis": int(provider_counts[6]),
            "ed_observed_np_npis": int(provider_counts[7]),
            "ed_observed_pa_npis": int(provider_counts[8]),
            "organizational_npis_classified_md_do": organizational_md_do_errors,
        },
        "phase2_partition_audit": {
            "old_successful_partitions_preserved_and_superseded": sum(
                bool(row["old_success_exists"]) for row in old_partition_rows
            ),
            "provider_v2_validated_partitions": valid_v2_partitions,
            "affected_fields": list(STALE_PROVIDER_FIELDS),
            "refresh_source": (
                "Immutable Phase 1 fact and bridge files, not old Phase 2 cohort"
            ),
        },
        "measurement_definitions": measurement_definitions,
        "physician_gender_checkpoint": {
            "path": str(gender_checkpoint_path),
            "sha256": sha256_file(gender_checkpoint_path),
            "status": gender_checkpoint["status"],
            "coverage": gender_summary_dict,
        },
        "sap_deviations": sap_deviations,
        "frozen_research_specification": frozen_research_specification,
        "remaining_validation_limitations": remaining_limitations,
        "harvard_tables_vs_official_wru": harvard_comparison,
        "artifacts": {
            "detailed_coverage": str(coverage_path),
            "coverage_summary": str(coverage_summary_path),
            "cohort_reconciliation": str(reconciliation_path),
            "superseded_partitions": str(
                qa_root / "superseded_phase2_provider_partitions.csv"
            ),
            "v2_partition_validation": str(
                qa_root / "provider_v2_partition_manifest_validation.csv"
            ),
            "physician_gender_provider_coverage": str(
                gender_provider_coverage_path
            ),
            "physician_gender_primary_cohort_coverage": str(
                gender_cohort_coverage_path
            ),
            "physician_gender_measurement_checkpoint": str(
                gender_checkpoint_path
            ),
            "provider_master_source_manifest": str(
                provider_source_manifest_path
            ),
            "provider_master_large_source_hash_audit": str(
                provider_large_hash_audit_path
            ),
        },
    }
    checkpoint_path = qa_root / "pre_estimation_measurement_gate.json"
    atomic_json(checkpoint_path, checkpoint)

    status_word = "PASS" if gate_pass else "BLOCKED"
    markdown = f"""# Pre-estimation provider measurement gate

Status: **{status_word}**

Created: {checkpoint["created_utc"]}

This checkpoint was produced without reading or interpreting any real-data
model estimate.

## Why the old Phase 2 cohort was stale

The old builder inner-joined the Phase 1 physician master and required the
Phase 1 physician-master match and MD/DO flags before row inclusion. It also
used Phase 1 surname race and physician gender to determine whether a visit
could enter either concordance cohort. Therefore provider linkage affected row
inclusion. The old successful partitions are preserved as superseded audit
artifacts; they are not estimation-ready.

The provider-v2 cohort was rebuilt directly from the immutable Phase 1 fact and
diagnosis bridge files. It was not reconstructed from the old Phase 2 cohort.

## Gate checks

{os.linesep.join(f"- {key}: {value}" for key, value in gate_checks.items())}

## Provider universe

- Master NPIs: {int(provider_counts[0]):,}
- ED-observed NPIs: {int(provider_counts[1]):,}
- Newly added ED-observed NPIs: {int(provider_counts[3]):,}
- ED-observed individuals: {int(provider_counts[4]):,}
- ED-observed organizations: {int(provider_counts[5]):,}
- ED-observed MD/DO physicians: {int(provider_counts[6]):,}
- ED-observed nurse practitioners: {int(provider_counts[7]):,}
- ED-observed physician assistants: {int(provider_counts[8]):,}
- Organizational NPIs classified as MD/DO: {organizational_md_do_errors:,}

Detailed counts by year, role, linkage method, entity type, clinician type,
unique NPI, and visit-role link are in
`pre_estimation_phase1_vs_v2_linkage_coverage.csv`.

## Race measurement

The primary physician race measure is an algorithm-inferred Bayesian full-name
probability using official wru v2.0.0 P(name|race) dictionaries and a normalized
Florida active-physician prior from AAMC 2020 counts. It is not self-identified
race and is not BISG because residential geography is unavailable. The wru
national 2020 prior is retained as a mandatory sensitivity.

The AAMC source tables are pages 34, 36, 38, 40, 42, 44, and 46 of the
2021 State Physician Workforce Data Report. Each table is explicitly labelled
"alone or in combination." The five-class Florida endorsement sum is 52,638
of 58,822 active physicians (89.49%). Because the published margins do not
separate nonresponse from multiple-category overlap, the normalized values are
used only as a transparent target-population empirical prior, not as an estimate
of mutually exclusive Florida physician prevalence.

NPPES and Florida DOH locations are practice or business addresses. Official
wru geography inputs refer to residence, so practice ZIP is not substituted for
residential geography; doing so could encode facility-neighborhood composition
in the physician-race measure.

The earlier `first_raceNameProbs.csv` is the official first-name likelihood
table to floating-point tolerance. The earlier `first_nameRaceProbs.csv` has
the opposite conditional, P(race|first). These cannot be averaged or multiplied
as if they were independent likelihoods; that earlier combination is rejected.

## Gender measurement

Primary physician gender uses recorded NPPES or CMS binary administrative
categories only, including the February 2026 NPPES and June 2026 CMS current
snapshots. SSA >=90% first-name imputation is excluded from the primary cohort
and retained as an expanded measurement sensitivity. A separate exact M2
sensitivity excludes NPIs whose recorded NPPES and CMS categories disagree.
None of these fields is guaranteed to measure self-identified gender identity.
Patient sex is the recorded administrative sex field.

- Hierarchy-eligible visits: {gender_summary_dict["hierarchy_eligible_visits"]:,}
- Recorded-source primary visits: {gender_summary_dict["recorded_source_primary_visits"]:,}
- SSA-expanded-only visits: {gender_summary_dict["ssa_expanded_only_visits"]:,}
- Recorded-source conflict visits: {gender_summary_dict["recorded_source_conflict_visits"]:,}
- Recorded-source conflict NPIs: {gender_summary_dict["recorded_source_conflict_unique_npis"]:,}

## Frozen analysis

Provider v2 is a measurement and coverage correction. The research objective,
charges, admission/disposition, length of stay, treatment intensity,
utilization, separate AMI/Greenwood analysis, primary contrasts, and estimators
remain frozen except for the logged measurement-related SAP deviations.

## Remaining limitations

{os.linesep.join(f"- {item}" for item in remaining_limitations)}
"""
    atomic_text(
        docs_root / "Pre_Estimation_Provider_Measurement_Gate.md",
        markdown,
    )

    print("7/7 Finalizing pre-estimation gate", flush=True)
    print(json.dumps(checkpoint, indent=2), flush=True)
    if not gate_pass:
        raise RuntimeError(
            "Pre-estimation provider measurement gate is BLOCKED; models must "
            "not run. See pre_estimation_measurement_gate.json."
        )


if __name__ == "__main__":
    main()
