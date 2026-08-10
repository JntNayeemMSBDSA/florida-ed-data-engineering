#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/04_build_analysis_cohort.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Build checkpointed, partitioned Phase 2 concordance analysis data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import duckdb


DEFAULT_YEARS = list(range(2010, 2025))
DEFAULT_QUARTERS = [1, 2, 3, 4]
COHORT_BUILD_SPEC_VERSION = "provider_v2_cms_current_cohort_v1"

CHARGE_COMPONENTS = [
    "pharmchgs",
    "medchgs",
    "labchgs",
    "radchgs",
    "cardiochgs",
    "oprmchgs",
    "aneschgs",
    "recovchgs",
    "erchgs",
    "traumachgs",
    "obserchgs",
    "gastrochgs",
    "lithochgs",
    "othchgs",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_int_list(text: str, valid: set[int]) -> list[int]:
    values = sorted({int(item.strip()) for item in text.split(",") if item.strip()})
    invalid = [value for value in values if value not in valid]
    if invalid:
        raise ValueError(f"Invalid values {invalid}; expected subset of {sorted(valid)}")
    return values


def validated_stage_dir(temp_root: Path, year: int, quarter: int) -> Path:
    root = temp_root.resolve()
    stage = (root / f"visit_year={year}" / f"visit_quarter={quarter}").resolve()
    if root not in stage.parents:
        raise RuntimeError(f"Unsafe stage path outside temp root: {stage}")
    return stage


def success_is_valid(
    success_path: Path,
    *,
    provider_master_sha256: str | None,
    provider_race_proxy_sha256: str | None,
) -> bool:
    if not success_path.exists():
        return False
    try:
        payload = json.loads(success_path.read_text(encoding="utf-8"))
        if (
            payload.get("build_spec_version")
            != COHORT_BUILD_SPEC_VERSION
        ):
            return False
        if (
            payload.get("provider_master_sha256")
            != provider_master_sha256
            or payload.get("provider_race_proxy_sha256")
            != provider_race_proxy_sha256
        ):
            return False
        for item in payload["files"]:
            path = success_path.parent / item["name"]
            if not path.exists():
                return False
            if path.stat().st_size != item["bytes"]:
                return False
            if sha256_file(path) != item["sha256"]:
                return False
        return bool(payload.get("reconciliation_passed"))
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return False


def build_volume_dimensions(
    con: duckdb.DuckDBPyConnection,
    release: Path,
    output_root: Path,
    sample_modulus: int,
) -> None:
    dimensions = output_root / "dimensions"
    dimensions.mkdir(parents=True, exist_ok=True)
    physician_quarter = dimensions / "physician_quarter_volume.parquet"
    physician_year = dimensions / "physician_year_volume.parquet"
    facility_quarter = dimensions / "facility_quarter_volume.parquet"
    manifest_path = dimensions / "volume_dimensions_manifest.json"

    if (
        physician_quarter.exists()
        and physician_year.exists()
        and facility_quarter.exists()
        and manifest_path.exists()
    ):
        return

    fact_glob = (
        release
        / "fact_ed_visits"
        / "visit_year=*"
        / "visit_quarter=*"
        / "ed_visits.parquet"
    )
    sample_filter = (
        f"WHERE hash(visit_key) % {sample_modulus} = 0"
        if sample_modulus > 0
        else ""
    )
    con.execute(
        f"""
        COPY (
            SELECT
                visit_year,
                visit_quarter,
                attending_selected_npi,
                COUNT(*) AS attending_quarter_volume_all_ed
            FROM read_parquet('{qpath(fact_glob)}')
            {sample_filter}
            WHERE attending_selected_npi IS NOT NULL
            GROUP BY visit_year, visit_quarter, attending_selected_npi
        ) TO '{qpath(physician_quarter)}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
        """
        if not sample_filter
        else f"""
        COPY (
            SELECT
                visit_year,
                visit_quarter,
                attending_selected_npi,
                COUNT(*) AS attending_quarter_volume_all_ed
            FROM read_parquet('{qpath(fact_glob)}')
            WHERE hash(visit_key) % {sample_modulus} = 0
              AND attending_selected_npi IS NOT NULL
            GROUP BY visit_year, visit_quarter, attending_selected_npi
        ) TO '{qpath(physician_quarter)}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
        """
    )
    con.execute(
        f"""
        COPY (
            SELECT
                visit_year,
                attending_selected_npi,
                SUM(attending_quarter_volume_all_ed)
                    AS attending_year_volume_all_ed
            FROM read_parquet('{qpath(physician_quarter)}')
            GROUP BY visit_year, attending_selected_npi
        ) TO '{qpath(physician_year)}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
        """
    )
    con.execute(
        f"""
        COPY (
            SELECT
                visit_year,
                visit_quarter,
                facility_ahca_id,
                COUNT(*) AS facility_quarter_volume_all_ed
            FROM read_parquet('{qpath(fact_glob)}')
            {"WHERE hash(visit_key) % " + str(sample_modulus) + " = 0" if sample_modulus > 0 else ""}
            GROUP BY visit_year, visit_quarter, facility_ahca_id
        ) TO '{qpath(facility_quarter)}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
        """
    )
    files = []
    for path in (physician_quarter, physician_year, facility_quarter):
        files.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": con.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{qpath(path)}')"
                ).fetchone()[0],
            }
        )
    manifest_path.write_text(
        json.dumps(
            {
                "created_utc": now_utc(),
                "sample_modulus": sample_modulus,
                "files": files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--external", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument(
        "--years", default=",".join(str(year) for year in DEFAULT_YEARS)
    )
    parser.add_argument(
        "--quarters", default=",".join(str(q) for q in DEFAULT_QUARTERS)
    )
    parser.add_argument("--sample-modulus", type=int, default=0)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--provider-master-v2", type=Path)
    parser.add_argument("--provider-race-proxy-v2", type=Path)
    parser.add_argument(
        "--cohort-dir-name",
        default="concordance_visit_data",
        help="Partition directory below --output.",
    )
    args = parser.parse_args()

    years = parse_int_list(args.years, set(DEFAULT_YEARS))
    quarters = parse_int_list(args.quarters, set(DEFAULT_QUARTERS))
    if args.sample_modulus < 0:
        raise ValueError("--sample-modulus must be nonnegative")

    release = args.release.resolve()
    external = args.external.resolve()
    output_root = args.output.resolve()
    temp_root = args.temp.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(temp_root)}'")
    con.execute("SET preserve_insertion_order=false")

    sample_fact = (
        release
        / "fact_ed_visits"
        / "visit_year=2010"
        / "visit_quarter=1"
        / "ed_visits.parquet"
    )
    fact_columns = {
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{qpath(sample_fact)}')"
        ).fetchall()
    }
    elix_flags = sorted(
        column
        for column in fact_columns
        if column.startswith("elix_")
        and column.endswith("_flag")
        and column != "elixhauser_condition_count"
    )
    if not elix_flags:
        raise RuntimeError("No Elixhauser flags found in the fact schema")
    missing_charges = sorted(set(CHARGE_COMPONENTS) - fact_columns)
    if missing_charges:
        raise RuntimeError(f"Missing expected charge fields: {missing_charges}")

    build_volume_dimensions(
        con, release, output_root, args.sample_modulus
    )

    use_provider_v2 = (
        args.provider_master_v2 is not None
        or args.provider_race_proxy_v2 is not None
    )
    if use_provider_v2 and (
        args.provider_master_v2 is None
        or args.provider_race_proxy_v2 is None
    ):
        raise ValueError(
            "--provider-master-v2 and --provider-race-proxy-v2 must be "
            "supplied together"
        )
    physician_master = (
        args.provider_master_v2.resolve()
        if use_provider_v2
        else release / "dimensions" / "physician_master.parquet"
    )
    provider_race_proxy = (
        args.provider_race_proxy_v2.resolve()
        if use_provider_v2
        else None
    )
    provider_master_sha256 = (
        sha256_file(physician_master) if use_provider_v2 else None
    )
    provider_race_proxy_sha256 = (
        sha256_file(provider_race_proxy) if use_provider_v2 else None
    )
    facility_master = release / "dimensions" / "facility_master.parquet"
    cpi = external / "bls_cpi_quarterly_factors_to_2024.csv"
    dimensions = output_root / "dimensions"
    physician_quarter = dimensions / "physician_quarter_volume.parquet"
    physician_year = dimensions / "physician_year_volume.parquet"
    facility_quarter = dimensions / "facility_quarter_volume.parquet"

    if use_provider_v2:
        con.execute(
            f"""
            CREATE OR REPLACE VIEW physician_master AS
            SELECT
                npi,
                provider_entity_category_v2,
                gender_category_v2,
                gender_source_v2,
                taxonomy_display_name_v2,
                coalesce(
                    cms_primary_specialty_v2,
                    cms_primary_specialty
                ) AS cms_primary_specialty,
                ed_specialist_flag_v2,
                physician_md_do_flag_v2,
                medical_school_grad_year_v2
                    AS medical_school_grad_year,
                has_fl_doh_hospital_privilege,
                doh_hospital_privilege_count,
                has_cms_group_practice_affiliation_v2
                    AS has_cms_group_practice_affiliation,
                coalesce(
                    cms_group_practice_count_v2,
                    cms_group_practice_count
                ) AS cms_group_practice_count,
                has_cms_current_facility_affiliation_v2,
                coalesce(
                    cms_facility_certification_count_v2, 0
                ) AS cms_facility_certification_count_v2,
                has_any_current_hospital_affiliation_v2,
                phase1_master_match_flag,
                nppes_current_snapshot_match_flag
            FROM read_parquet('{qpath(physician_master)}')
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE VIEW provider_race_proxy AS
            SELECT
                npi,
                race_proxy_primary_method_id,
                race_proxy_method_label,
                race_proxy_primary_five_class_label,
                race_proxy_primary_max_probability,
                race_proxy_primary_black_white_mass,
                race_proxy_primary_prob_black_conditional_bw,
                race_proxy_primary_normalized_entropy,
                fl_physician_prob_white,
                fl_physician_prob_black,
                fl_physician_prob_hispanic,
                fl_physician_prob_asian,
                fl_physician_prob_other,
                population_prob_white,
                population_prob_black,
                population_prob_hispanic,
                population_prob_asian,
                population_prob_other,
                last_match_flag,
                first_match_flag,
                middle_match_flag,
                race_proxy_name_match_pattern,
                race_proxy_primary_eligible_t50_flag,
                race_proxy_primary_eligible_t70_flag,
                race_proxy_primary_eligible_t80_flag,
                race_proxy_primary_eligible_t90_flag,
                phase1_surname_prob_white,
                phase1_surname_prob_black,
                phase1_surname_prob_hispanic,
                phase1_surname_prob_asian_pi,
                phase1_surname_prob_aian,
                phase1_surname_prob_multiracial
            FROM read_parquet('{qpath(provider_race_proxy)}')
            """
        )
    else:
        con.execute(
            f"""
            CREATE OR REPLACE VIEW physician_master AS
            SELECT
                npi,
                gender_source,
                surname_prob_white,
                surname_prob_black,
                surname_prob_api,
                surname_prob_aian,
                surname_prob_multiracial,
                surname_prob_hispanic,
                surname_imputation_max_probability,
                race_ethnicity_source
            FROM read_parquet('{qpath(physician_master)}')
            """
        )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW facility_master AS
        SELECT
            facility_ahca_id,
            cms_hospital_type,
            cms_hospital_ownership,
            facility_rurality_3level
        FROM read_parquet('{qpath(facility_master)}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW cpi AS
        SELECT
            year::INTEGER AS visit_year,
            quarter::INTEGER AS visit_quarter,
            series_id,
            factor_to_2024_dollars
        FROM read_csv_auto('{qpath(cpi)}', HEADER=TRUE)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW physician_quarter_volume AS
        SELECT * FROM read_parquet('{qpath(physician_quarter)}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW physician_year_volume AS
        SELECT * FROM read_parquet('{qpath(physician_year)}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW facility_quarter_volume AS
        SELECT * FROM read_parquet('{qpath(facility_quarter)}')
        """
    )

    if use_provider_v2:
        provider_base_select_sql = """
            p.provider_entity_category_v2
                AS analysis_provider_entity_category,
            p.physician_md_do_flag_v2 AS analysis_physician_md_do_flag,
            p.phase1_master_match_flag,
            p.nppes_current_snapshot_match_flag,
            p.gender_category_v2 AS analysis_physician_gender_category,
            p.gender_source_v2 AS analysis_physician_gender_source,
            r.race_proxy_primary_five_class_label
                AS analysis_physician_race_label,
            r.race_proxy_primary_method_id
                AS analysis_physician_race_method_id,
            r.race_proxy_method_label
                AS analysis_physician_race_method_label,
            r.fl_physician_prob_white AS analysis_race_prob_white,
            r.fl_physician_prob_black AS analysis_race_prob_black,
            r.fl_physician_prob_hispanic AS analysis_race_prob_hispanic,
            r.fl_physician_prob_asian AS analysis_race_prob_asian,
            r.fl_physician_prob_other AS analysis_race_prob_other,
            r.population_prob_white AS sensitivity_population_prob_white,
            r.population_prob_black AS sensitivity_population_prob_black,
            r.population_prob_hispanic AS sensitivity_population_prob_hispanic,
            r.population_prob_asian AS sensitivity_population_prob_asian,
            r.population_prob_other AS sensitivity_population_prob_other,
            r.race_proxy_primary_max_probability
                AS analysis_race_max_probability,
            r.race_proxy_primary_black_white_mass
                AS analysis_race_black_white_mass,
            r.race_proxy_primary_prob_black_conditional_bw
                AS analysis_race_prob_black_conditional_bw,
            r.race_proxy_primary_normalized_entropy
                AS analysis_race_normalized_entropy,
            r.last_match_flag AS analysis_race_last_match_flag,
            r.first_match_flag AS analysis_race_first_match_flag,
            r.middle_match_flag AS analysis_race_middle_match_flag,
            r.race_proxy_name_match_pattern
                AS analysis_race_name_match_pattern,
            r.phase1_surname_prob_white,
            r.phase1_surname_prob_black,
            r.phase1_surname_prob_hispanic,
            r.phase1_surname_prob_asian_pi,
            r.phase1_surname_prob_aian,
            r.phase1_surname_prob_multiracial,
            p.taxonomy_display_name_v2
                AS analysis_attending_taxonomy_display_name,
            p.cms_primary_specialty
                AS analysis_attending_cms_primary_specialty,
            p.ed_specialist_flag_v2
                AS analysis_attending_ed_specialist_flag,
            CASE
                WHEN p.medical_school_grad_year BETWEEN 1900 AND f.visit_year
                 AND f.visit_year - p.medical_school_grad_year BETWEEN 0 AND 80
                    THEN f.visit_year - p.medical_school_grad_year
            END AS analysis_attending_years_since_medical_school,
            p.has_fl_doh_hospital_privilege
                AS analysis_attending_has_fl_doh_hospital_privilege,
            p.doh_hospital_privilege_count
                AS analysis_attending_doh_hospital_privilege_count,
            p.has_cms_group_practice_affiliation
                AS analysis_attending_has_cms_group_practice_affiliation,
            p.cms_group_practice_count
                AS analysis_attending_cms_group_practice_count,
            p.has_cms_current_facility_affiliation_v2
                AS analysis_attending_has_cms_current_facility_affiliation,
            p.cms_facility_certification_count_v2
                AS analysis_attending_cms_facility_certification_count,
            p.has_any_current_hospital_affiliation_v2
                AS analysis_attending_has_any_current_hospital_affiliation,
            'provider_master_v2_full_name_race_v1'
                AS provider_measurement_version
        """
        provider_join_sql = """
            LEFT JOIN provider_race_proxy AS r
              ON f.attending_selected_npi = r.npi
        """
        provider_filter_sql = """
            p.provider_entity_category_v2 = 'Individual'
            AND p.physician_md_do_flag_v2
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
                    AND p.gender_category_v2 IN ('Female', 'Male')
                )
            )
        """
    else:
        provider_base_select_sql = """
            'Individual'::VARCHAR AS analysis_provider_entity_category,
            f.attending_physician_md_do_flag
                AS analysis_physician_md_do_flag,
            f.attending_physician_master_matched_flag
                AS phase1_master_match_flag,
            f.attending_physician_master_matched_flag
                AS nppes_current_snapshot_match_flag,
            f.attending_gender_category
                AS analysis_physician_gender_category,
            p.gender_source AS analysis_physician_gender_source,
            CASE
                WHEN f.attending_surname_imputed_race_ethnicity =
                    'Non-Hispanic Black' THEN 'Black'
                WHEN f.attending_surname_imputed_race_ethnicity =
                    'Non-Hispanic White' THEN 'White'
            END AS analysis_physician_race_label,
            'phase1_census_2010_surname_only'
                AS analysis_physician_race_method_id,
            '2010 U.S. Census surname-only imputation'
                AS analysis_physician_race_method_label,
            p.surname_prob_white AS analysis_race_prob_white,
            p.surname_prob_black AS analysis_race_prob_black,
            p.surname_prob_hispanic AS analysis_race_prob_hispanic,
            p.surname_prob_api AS analysis_race_prob_asian,
            coalesce(p.surname_prob_aian, 0)
                + coalesce(p.surname_prob_multiracial, 0)
                AS analysis_race_prob_other,
            NULL::DOUBLE AS sensitivity_population_prob_white,
            NULL::DOUBLE AS sensitivity_population_prob_black,
            NULL::DOUBLE AS sensitivity_population_prob_hispanic,
            NULL::DOUBLE AS sensitivity_population_prob_asian,
            NULL::DOUBLE AS sensitivity_population_prob_other,
            p.surname_imputation_max_probability
                AS analysis_race_max_probability,
            coalesce(p.surname_prob_black, 0)
                + coalesce(p.surname_prob_white, 0)
                AS analysis_race_black_white_mass,
            p.surname_prob_black
                / nullif(
                    coalesce(p.surname_prob_black, 0)
                    + coalesce(p.surname_prob_white, 0),
                    0
                ) AS analysis_race_prob_black_conditional_bw,
            NULL::DOUBLE AS analysis_race_normalized_entropy,
            p.surname_imputation_max_probability IS NOT NULL
                AS analysis_race_last_match_flag,
            false AS analysis_race_first_match_flag,
            false AS analysis_race_middle_match_flag,
            'surname_only_match'::VARCHAR
                AS analysis_race_name_match_pattern,
            p.surname_prob_white AS phase1_surname_prob_white,
            p.surname_prob_black AS phase1_surname_prob_black,
            p.surname_prob_hispanic AS phase1_surname_prob_hispanic,
            p.surname_prob_api AS phase1_surname_prob_asian_pi,
            p.surname_prob_aian AS phase1_surname_prob_aian,
            p.surname_prob_multiracial
                AS phase1_surname_prob_multiracial,
            f.attending_taxonomy_display_name
                AS analysis_attending_taxonomy_display_name,
            f.attending_cms_primary_specialty
                AS analysis_attending_cms_primary_specialty,
            f.attending_ed_specialist_flag
                AS analysis_attending_ed_specialist_flag,
            f.attending_years_since_medical_school
                AS analysis_attending_years_since_medical_school,
            f.attending_has_fl_doh_hospital_privilege
                AS analysis_attending_has_fl_doh_hospital_privilege,
            f.attending_doh_hospital_privilege_count
                AS analysis_attending_doh_hospital_privilege_count,
            f.attending_has_cms_group_practice_affiliation
                AS analysis_attending_has_cms_group_practice_affiliation,
            f.attending_cms_group_practice_count
                AS analysis_attending_cms_group_practice_count,
            NULL::BOOLEAN
                AS analysis_attending_has_cms_current_facility_affiliation,
            NULL::UINTEGER
                AS analysis_attending_cms_facility_certification_count,
            f.attending_has_fl_doh_hospital_privilege
                AS analysis_attending_has_any_current_hospital_affiliation,
            'phase1_provider_measurement'
                AS provider_measurement_version
        """
        provider_join_sql = ""
        provider_filter_sql = """
            f.attending_physician_master_matched_flag
            AND f.attending_physician_md_do_flag
            AND (
                (
                    f.race_category IN (
                        'Black or African American', 'White'
                    )
                    AND f.attending_surname_imputed_race_ethnicity IN (
                        'Non-Hispanic Black', 'Non-Hispanic White'
                    )
                )
                OR (
                    f.sex_category IN ('Female', 'Male')
                    AND f.attending_gender_category IN ('Female', 'Male')
                )
            )
        """

    build_results: list[dict[str, object]] = []
    for year in years:
        for quarter in quarters:
            final_dir = (
                output_root
                / args.cohort_dir_name
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
            )
            success_path = final_dir / "_SUCCESS.json"
            if not args.overwrite and success_is_valid(
                success_path,
                provider_master_sha256=provider_master_sha256,
                provider_race_proxy_sha256=provider_race_proxy_sha256,
            ):
                build_results.append(
                    {
                        "visit_year": year,
                        "visit_quarter": quarter,
                        "status": "validated_existing",
                    }
                )
                continue

            stage_dir = validated_stage_dir(temp_root, year, quarter)
            if stage_dir.exists():
                shutil.rmtree(stage_dir)
            stage_dir.mkdir(parents=True, exist_ok=True)

            fact_file = (
                release
                / "fact_ed_visits"
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "ed_visits.parquet"
            )
            diagnosis_file = (
                release
                / "bridges"
                / "visit_diagnosis"
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "visit_diagnosis.parquet"
            )
            if not fact_file.exists() or not diagnosis_file.exists():
                raise FileNotFoundError(
                    f"Missing release partition for {year} Q{quarter}"
                )

            sample_predicate = (
                f"AND hash(f.visit_key) % {args.sample_modulus} = 0"
                if args.sample_modulus > 0
                else ""
            )
            con.execute("DROP TABLE IF EXISTS quarter_cohort")
            con.execute(
                f"""
                CREATE TEMP TABLE quarter_cohort AS
                WITH ami AS (
                    SELECT
                        visit_key,
                        MAX(
                            CASE
                                WHEN diagnosis_code_system = 'ICD-9-CM'
                                 AND regexp_full_match(
                                     diagnosis_code_norm, '410[0-9]1'
                                 )
                                THEN 1 ELSE 0
                            END
                        )::UTINYINT AS ami_icd9_anylisted_strict_flag,
                        MAX(
                            CASE
                                WHEN diagnosis_code_system = 'ICD-9-CM'
                                 AND regexp_full_match(
                                     diagnosis_code_norm, '410[0-9][01]'
                                 )
                                THEN 1 ELSE 0
                            END
                        )::UTINYINT AS ami_icd9_anylisted_broad_flag,
                        MAX(
                            CASE
                                WHEN diagnosis_code_system = 'ICD-10-CM'
                                 AND regexp_matches(
                                     diagnosis_code_norm,
                                     '^I21([0-4]|9)'
                                 )
                                THEN 1 ELSE 0
                            END
                        )::UTINYINT AS ami_icd10_anylisted_primary_flag,
                        MAX(
                            CASE
                                WHEN diagnosis_code_system = 'ICD-10-CM'
                                 AND diagnosis_code_norm IN ('I21A1', 'I21A9')
                                THEN 1 ELSE 0
                            END
                        )::UTINYINT AS ami_icd10_anylisted_type2_other_flag,
                        MAX(
                            CASE
                                WHEN diagnosis_code_system = 'ICD-10-CM'
                                 AND regexp_matches(
                                     diagnosis_code_norm, '^I22'
                                 )
                                THEN 1 ELSE 0
                            END
                        )::UTINYINT AS ami_icd10_anylisted_i22_flag
                    FROM read_parquet('{qpath(diagnosis_file)}')
                    WHERE diagnosis_role IN ('principal', 'secondary')
                      AND (
                          regexp_matches(diagnosis_code_norm, '^410')
                          OR regexp_matches(diagnosis_code_norm, '^I2[12]')
                      )
                    GROUP BY visit_key
                ), base AS (
                    SELECT
                        f.*,
                        {provider_base_select_sql},
                        pq.attending_quarter_volume_all_ed,
                        py.attending_year_volume_all_ed,
                        fq.facility_quarter_volume_all_ed,
                        fm.cms_hospital_type,
                        fm.cms_hospital_ownership,
                        fm.facility_rurality_3level,
                        cu.factor_to_2024_dollars
                            AS cpi_u_factor_to_2024,
                        cm.factor_to_2024_dollars
                            AS medical_cpi_factor_to_2024,
                        COALESCE(
                            a.ami_icd9_anylisted_strict_flag, 0
                        )::UTINYINT AS ami_icd9_anylisted_strict_flag,
                        COALESCE(
                            a.ami_icd9_anylisted_broad_flag, 0
                        )::UTINYINT AS ami_icd9_anylisted_broad_flag,
                        COALESCE(
                            a.ami_icd10_anylisted_primary_flag, 0
                        )::UTINYINT AS ami_icd10_anylisted_primary_flag,
                        COALESCE(
                            a.ami_icd10_anylisted_type2_other_flag, 0
                        )::UTINYINT
                            AS ami_icd10_anylisted_type2_other_flag,
                        COALESCE(
                            a.ami_icd10_anylisted_i22_flag, 0
                        )::UTINYINT AS ami_icd10_anylisted_i22_flag
                    FROM read_parquet('{qpath(fact_file)}') AS f
                    INNER JOIN physician_master AS p
                      ON f.attending_selected_npi = p.npi
                    {provider_join_sql}
                    LEFT JOIN physician_quarter_volume AS pq
                      ON f.visit_year = pq.visit_year
                     AND f.visit_quarter = pq.visit_quarter
                     AND f.attending_selected_npi =
                         pq.attending_selected_npi
                    LEFT JOIN physician_year_volume AS py
                      ON f.visit_year = py.visit_year
                     AND f.attending_selected_npi =
                         py.attending_selected_npi
                    LEFT JOIN facility_quarter_volume AS fq
                      ON f.visit_year = fq.visit_year
                     AND f.visit_quarter = fq.visit_quarter
                     AND f.facility_ahca_id = fq.facility_ahca_id
                    LEFT JOIN facility_master AS fm
                      ON f.facility_ahca_id = fm.facility_ahca_id
                    LEFT JOIN cpi AS cu
                      ON f.visit_year = cu.visit_year
                     AND f.visit_quarter = cu.visit_quarter
                     AND cu.series_id = 'CUUR0000SA0'
                    LEFT JOIN cpi AS cm
                      ON f.visit_year = cm.visit_year
                     AND f.visit_quarter = cm.visit_quarter
                     AND cm.series_id = 'CUUR0000SAM'
                    LEFT JOIN ami AS a
                      ON f.visit_key = a.visit_key
                    WHERE f.attending_selection_method IN (
                              'direct_validated_npi',
                              'unique_fl_license_crosswalk'
                          )
                      AND ({provider_filter_sql})
                      {sample_predicate}
                )
                SELECT
                    *,
                    CASE
                        WHEN arrival_hour BETWEEN 0 AND 23
                         AND TRY_CAST(
                                 ed_discharge_hour_raw AS INTEGER
                             ) BETWEEN 0 AND 23
                        THEN 24.0 * length_of_stay_days
                           + TRY_CAST(ed_discharge_hour_raw AS INTEGER)
                           - arrival_hour
                    END AS los_hours_clock_raw,
                    CASE
                        WHEN arrival_hour BETWEEN 0 AND 23
                         AND TRY_CAST(
                                 ed_discharge_hour_raw AS INTEGER
                             ) BETWEEN 0 AND 23
                         AND 24.0 * length_of_stay_days
                           + TRY_CAST(ed_discharge_hour_raw AS INTEGER)
                           - arrival_hour >= 0
                        THEN 24.0 * length_of_stay_days
                           + TRY_CAST(ed_discharge_hour_raw AS INTEGER)
                           - arrival_hour
                    END AS los_hours_nonnegative,
                    (
                        race_category IN (
                            'Black or African American', 'White'
                        )
                        AND ethnicity_category = 'Not Hispanic or Latino'
                        AND analysis_physician_race_label IN (
                            'Black', 'White'
                        )
                        AND analysis_race_last_match_flag
                        AND (
                            analysis_race_first_match_flag
                            OR provider_measurement_version =
                                'phase1_provider_measurement'
                        )
                    ) AS race_pair_defined_nh_flag,
                    (
                        race_category IN (
                            'Black or African American', 'White'
                        )
                        AND analysis_physician_race_label IN (
                            'Black', 'White'
                        )
                        AND analysis_race_last_match_flag
                        AND (
                            analysis_race_first_match_flag
                            OR provider_measurement_version =
                                'phase1_provider_measurement'
                        )
                    ) AS race_pair_defined_race_only_flag,
                    (
                        sex_category IN ('Female', 'Male')
                        AND analysis_physician_gender_category IN (
                            'Female', 'Male'
                        )
                    ) AS sex_gender_pair_defined_flag
                FROM base
                """
            )

            core_path = stage_dir / "concordance_visit_core.parquet"
            charge_path = stage_dir / "concordance_charge_components.parquet"
            risk_path = stage_dir / "concordance_elixhauser_flags.parquet"

            con.execute(
                f"""
                COPY (
                    SELECT
                        visit_key,
                        visit_year,
                        visit_quarter,
                        facility_ahca_id,
                        facility_ahca_id || ':' ||
                            CAST(visit_year AS VARCHAR) || 'Q' ||
                            CAST(visit_quarter AS VARCHAR)
                            AS facility_year_quarter_id,
                        source_schema_id,
                        diagnosis_code_system,
                        sex_category AS patient_sex_category,
                        race_category AS patient_race_category,
                        ethnicity_category AS patient_ethnicity_category,
                        race_ethnicity_historical_label,
                        age_years,
                        age_band,
                        age_years IS NULL AS age_missing_flag,
                        weekday_label,
                        weekend_flag,
                        arrival_hour,
                        arrival_time_band,
                        off_hours_flag,
                        TRY_CAST(ed_discharge_hour_raw AS INTEGER)
                            AS ed_discharge_hour,
                        length_of_stay_days,
                        los_hours_clock_raw,
                        los_hours_nonnegative,
                        CASE
                            WHEN los_hours_nonnegative BETWEEN 0 AND 168
                            THEN los_hours_nonnegative
                        END AS los_hours_primary_0_168,
                        (
                            los_hours_nonnegative BETWEEN 0 AND 168
                        ) AS los_primary_valid_flag,
                        patient_zip_rurality_3level,
                        payer_group,
                        disposition_group,
                        routine_discharge_flag,
                        transfer_flag,
                        hospice_flag,
                        mortality_flag,
                        left_discontinued_care_flag,
                        principal_diagnosis_code_norm,
                        principal_diagnosis_description,
                        principal_clinical_category,
                        principal_clinical_category_label,
                        principal_diagnosis_mapped_flag,
                        CASE
                            WHEN diagnosis_code_system = 'ICD-9-CM'
                             AND TRY_CAST(
                                     LEFT(
                                         principal_diagnosis_code_norm, 3
                                     ) AS INTEGER
                                 ) BETWEEN 780 AND 799
                            THEN 'symptom_sign_coded'
                            WHEN diagnosis_code_system = 'ICD-10-CM'
                             AND starts_with(
                                     principal_diagnosis_code_norm, 'R'
                                 )
                            THEN 'symptom_sign_coded'
                            WHEN principal_diagnosis_code_norm IS NOT NULL
                             AND principal_diagnosis_code_norm <> ''
                            THEN 'disease_condition_or_injury_coded'
                            ELSE 'ambiguous_or_missing'
                        END AS presentation_code_group,
                        diagnosis_code_count,
                        secondary_diagnosis_code_count,
                        external_cause_code_count,
                        elixhauser_condition_count,
                        cpt_hcpcs_count,
                        evaluation_management_code_count,
                        icd_procedure_count,
                        distinct_procedure_group_count,
                        procedure_count_analysis,
                        procedure_count_scope,
                        any_procedure_flag,
                        high_procedure_flag,
                        em_acuity_proxy_level,
                        em_critical_care_flag,
                        em_acuity_proxy_status,
                        total_charge_reported,
                        CASE
                            WHEN total_charge_reported >= 0
                            THEN total_charge_reported *
                                 cpi_u_factor_to_2024
                        END AS total_charge_reported_real_2024,
                        total_charge,
                        CASE
                            WHEN total_charge >= 0
                            THEN total_charge * cpi_u_factor_to_2024
                        END AS total_charge_real_2024,
                        component_charge_sum,
                        CASE
                            WHEN component_charge_sum >= 0
                            THEN component_charge_sum *
                                 cpi_u_factor_to_2024
                        END AS component_charge_sum_real_2024,
                        charge_reconciliation_difference,
                        charge_reconciliation_exception_flag,
                        cpi_u_factor_to_2024,
                        medical_cpi_factor_to_2024,
                        off_site_ed_flag,
                        facility_quarter_volume_all_ed,
                        cms_hospital_type,
                        cms_hospital_ownership,
                        facility_rurality_3level,
                        attending_selected_npi,
                        attending_selection_method
                            AS physician_linkage_method,
                        analysis_provider_entity_category
                            AS physician_entity_category,
                        analysis_physician_md_do_flag
                            AS physician_md_do_flag,
                        phase1_master_match_flag,
                        nppes_current_snapshot_match_flag,
                        provider_measurement_version,
                        analysis_physician_gender_category
                            AS physician_gender_category,
                        analysis_physician_gender_source
                            AS physician_gender_source,
                        analysis_physician_race_label
                            AS physician_race_proxy_primary_label,
                        analysis_physician_race_method_id
                            AS physician_race_proxy_method_id,
                        analysis_physician_race_method_label
                            AS physician_race_ethnicity_proxy_source,
                        analysis_race_prob_white
                            AS physician_race_proxy_prob_white,
                        analysis_race_prob_black
                            AS physician_race_proxy_prob_black,
                        analysis_race_prob_hispanic
                            AS physician_race_proxy_prob_hispanic,
                        analysis_race_prob_asian
                            AS physician_race_proxy_prob_asian,
                        analysis_race_prob_other
                            AS physician_race_proxy_prob_other,
                        sensitivity_population_prob_white
                            AS physician_race_population_prob_white,
                        sensitivity_population_prob_black
                            AS physician_race_population_prob_black,
                        sensitivity_population_prob_hispanic
                            AS physician_race_population_prob_hispanic,
                        sensitivity_population_prob_asian
                            AS physician_race_population_prob_asian,
                        sensitivity_population_prob_other
                            AS physician_race_population_prob_other,
                        analysis_race_max_probability
                            AS physician_race_imputation_confidence,
                        analysis_race_black_white_mass
                            AS physician_race_proxy_black_white_mass,
                        analysis_race_prob_black_conditional_bw
                            AS physician_race_proxy_prob_black_conditional_bw,
                        analysis_race_normalized_entropy
                            AS physician_race_proxy_normalized_entropy,
                        analysis_race_last_match_flag
                            AS physician_race_last_match_flag,
                        analysis_race_first_match_flag
                            AS physician_race_first_match_flag,
                        analysis_race_middle_match_flag
                            AS physician_race_middle_match_flag,
                        analysis_race_name_match_pattern
                            AS physician_race_name_match_pattern,
                        phase1_surname_prob_white,
                        phase1_surname_prob_black,
                        phase1_surname_prob_hispanic,
                        phase1_surname_prob_asian_pi,
                        phase1_surname_prob_aian,
                        phase1_surname_prob_multiracial,
                        analysis_attending_taxonomy_display_name
                            AS attending_taxonomy_display_name,
                        analysis_attending_cms_primary_specialty
                            AS attending_cms_primary_specialty,
                        analysis_attending_ed_specialist_flag
                            AS attending_ed_specialist_flag,
                        analysis_attending_years_since_medical_school
                            AS attending_years_since_medical_school,
                        analysis_attending_years_since_medical_school IS NULL
                            AS physician_experience_missing_flag,
                        analysis_attending_has_fl_doh_hospital_privilege
                            AS attending_has_fl_doh_hospital_privilege,
                        analysis_attending_doh_hospital_privilege_count
                            AS attending_doh_hospital_privilege_count,
                        analysis_attending_has_cms_group_practice_affiliation
                            AS attending_has_cms_group_practice_affiliation,
                        analysis_attending_cms_group_practice_count
                            AS attending_cms_group_practice_count,
                        analysis_attending_has_cms_current_facility_affiliation
                            AS attending_has_cms_current_facility_affiliation,
                        analysis_attending_cms_facility_certification_count
                            AS attending_cms_facility_certification_count,
                        analysis_attending_has_any_current_hospital_affiliation
                            AS attending_has_any_current_hospital_affiliation,
                        attending_quarter_volume_all_ed,
                        attending_year_volume_all_ed,
                        race_pair_defined_nh_flag,
                        race_pair_defined_race_only_flag,
                        CASE
                            WHEN race_pair_defined_nh_flag
                             AND
                             analysis_physician_race_label = 'Black'
                             AND race_category =
                                 'Black or African American'
                            THEN 'black_black'
                            WHEN race_pair_defined_nh_flag
                             AND
                             analysis_physician_race_label = 'Black'
                             AND race_category = 'White'
                            THEN 'black_white'
                            WHEN race_pair_defined_nh_flag
                             AND
                             analysis_physician_race_label = 'White'
                             AND race_category =
                                 'Black or African American'
                            THEN 'white_black'
                            WHEN race_pair_defined_nh_flag
                             AND
                             analysis_physician_race_label = 'White'
                             AND race_category = 'White'
                            THEN 'white_white'
                        END AS race_pair_category,
                        (
                            race_pair_defined_nh_flag
                            AND
                            analysis_physician_race_label = 'Black'
                            AND race_category =
                                'Black or African American'
                        )::UTINYINT AS black_black,
                        (
                            race_pair_defined_nh_flag
                            AND
                            analysis_physician_race_label = 'Black'
                            AND race_category = 'White'
                        )::UTINYINT AS black_white,
                        (
                            race_pair_defined_nh_flag
                            AND
                            analysis_physician_race_label = 'White'
                            AND race_category =
                                'Black or African American'
                        )::UTINYINT AS white_black,
                        (
                            race_pair_defined_nh_flag
                            AND
                            analysis_physician_race_label = 'White'
                            AND race_category = 'White'
                        )::UTINYINT AS white_white,
                        CASE
                            WHEN race_pair_defined_nh_flag
                            THEN (
                                race_category =
                                    'Black or African American'
                            )::UTINYINT
                        END AS patient_black_flag,
                        CASE
                            WHEN race_pair_defined_nh_flag
                            THEN (
                                analysis_physician_race_label = 'Black'
                            )::UTINYINT
                        END AS physician_black_imputed_flag,
                        (
                            analysis_race_max_probability IS NOT NULL
                        ) AS physician_race_imputation_available_flag,
                        CASE
                            WHEN race_pair_defined_nh_flag
                             AND race_category =
                                 'Black or African American'
                            THEN (
                                analysis_physician_race_label = 'Black'
                            )
                        END AS black_racial_concordance_flag,
                        CASE
                            WHEN race_pair_defined_nh_flag
                            THEN (
                                (
                                    race_category =
                                        'Black or African American'
                                    AND
                                    analysis_physician_race_label = 'Black'
                                )
                                OR (
                                    race_category = 'White'
                                    AND
                                    analysis_physician_race_label = 'White'
                                )
                            )
                        END AS racial_concordance_flag,
                        (
                            race_pair_defined_nh_flag
                            AND attending_selection_method =
                                'direct_validated_npi'
                            AND analysis_race_max_probability >= 0.50
                        ) AS race_primary_eligible_t50_flag,
                        (
                            race_pair_defined_nh_flag
                            AND attending_selection_method =
                                'direct_validated_npi'
                            AND analysis_race_max_probability >= 0.70
                        ) AS race_primary_eligible_t70_flag,
                        (
                            race_pair_defined_nh_flag
                            AND attending_selection_method =
                                'direct_validated_npi'
                            AND analysis_race_max_probability >= 0.80
                        ) AS race_primary_eligible_t80_flag,
                        (
                            race_pair_defined_nh_flag
                            AND attending_selection_method =
                                'direct_validated_npi'
                            AND analysis_race_max_probability >= 0.90
                        ) AS race_primary_eligible_t90_flag,
                        sex_gender_pair_defined_flag,
                        CASE
                            WHEN sex_gender_pair_defined_flag
                             AND analysis_physician_gender_category = 'Female'
                             AND sex_category = 'Female'
                            THEN 'female_female'
                            WHEN sex_gender_pair_defined_flag
                             AND analysis_physician_gender_category = 'Female'
                             AND sex_category = 'Male'
                            THEN 'female_male'
                            WHEN sex_gender_pair_defined_flag
                             AND analysis_physician_gender_category = 'Male'
                             AND sex_category = 'Female'
                            THEN 'male_female'
                            WHEN sex_gender_pair_defined_flag
                             AND analysis_physician_gender_category = 'Male'
                             AND sex_category = 'Male'
                            THEN 'male_male'
                        END AS sex_gender_pair_category,
                        (
                            sex_gender_pair_defined_flag
                            AND analysis_physician_gender_category = 'Female'
                            AND sex_category = 'Female'
                        )::UTINYINT AS female_female,
                        (
                            sex_gender_pair_defined_flag
                            AND analysis_physician_gender_category = 'Female'
                            AND sex_category = 'Male'
                        )::UTINYINT AS female_male,
                        (
                            sex_gender_pair_defined_flag
                            AND analysis_physician_gender_category = 'Male'
                            AND sex_category = 'Female'
                        )::UTINYINT AS male_female,
                        (
                            sex_gender_pair_defined_flag
                            AND analysis_physician_gender_category = 'Male'
                            AND sex_category = 'Male'
                        )::UTINYINT AS male_male,
                        CASE
                            WHEN sex_gender_pair_defined_flag
                            THEN (
                                analysis_physician_gender_category =
                                    sex_category
                            )
                        END AS sex_gender_concordance_flag,
                        (
                            sex_gender_pair_defined_flag
                            AND attending_selection_method =
                                'direct_validated_npi'
                        ) AS sex_gender_primary_eligible_flag,
                        (
                            diagnosis_code_system = 'ICD-9-CM'
                            AND regexp_full_match(
                                principal_diagnosis_code_norm,
                                '410[0-9]1'
                            )
                        ) AS ami_icd9_principal_strict_flag,
                        (
                            diagnosis_code_system = 'ICD-9-CM'
                            AND regexp_full_match(
                                principal_diagnosis_code_norm,
                                '410[0-9][01]'
                            )
                        ) AS ami_icd9_principal_broad_flag,
                        (
                            diagnosis_code_system = 'ICD-10-CM'
                            AND regexp_matches(
                                principal_diagnosis_code_norm,
                                '^I21([0-4]|9)'
                            )
                        ) AS ami_icd10_principal_primary_flag,
                        (
                            diagnosis_code_system = 'ICD-10-CM'
                            AND principal_diagnosis_code_norm IN (
                                'I21A1', 'I21A9'
                            )
                        ) AS ami_icd10_principal_type2_other_flag,
                        ami_icd9_anylisted_strict_flag,
                        ami_icd9_anylisted_broad_flag,
                        ami_icd10_anylisted_primary_flag,
                        ami_icd10_anylisted_type2_other_flag,
                        ami_icd10_anylisted_i22_flag,
                        (
                            ami_icd10_anylisted_i22_flag = 1
                            AND (
                                ami_icd10_anylisted_primary_flag = 1
                                OR
                                ami_icd10_anylisted_type2_other_flag = 1
                            )
                        ) AS ami_i22_with_i21_same_visit_flag
                    FROM quarter_cohort
                ) TO '{qpath(core_path)}'
                (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
                """
            )

            charge_projection = ",\n".join(
                [
                    f"                        {column},\n"
                    f"                        CASE WHEN {column} >= 0 "
                    f"THEN {column} * cpi_u_factor_to_2024 END "
                    f"AS {column}_real_2024"
                    for column in CHARGE_COMPONENTS
                ]
            )
            con.execute(
                f"""
                COPY (
                    SELECT
                        visit_key,
                        visit_year,
                        visit_quarter,
{charge_projection}
                    FROM quarter_cohort
                ) TO '{qpath(charge_path)}'
                (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
                """
            )

            risk_projection = ",\n".join(
                f"                        {column}" for column in elix_flags
            )
            con.execute(
                f"""
                COPY (
                    SELECT
                        visit_key,
                        visit_year,
                        visit_quarter,
{risk_projection}
                    FROM quarter_cohort
                ) TO '{qpath(risk_path)}'
                (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
                """
            )

            cohort_rows = con.execute(
                "SELECT COUNT(*) FROM quarter_cohort"
            ).fetchone()[0]
            core_rows = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{qpath(core_path)}')"
            ).fetchone()[0]
            charge_rows = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{qpath(charge_path)}')"
            ).fetchone()[0]
            risk_rows = con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{qpath(risk_path)}')"
            ).fetchone()[0]
            if len({cohort_rows, core_rows, charge_rows, risk_rows}) != 1:
                raise RuntimeError(
                    f"Partition row reconciliation failed for {year} Q{quarter}: "
                    f"{cohort_rows}, {core_rows}, {charge_rows}, {risk_rows}"
                )

            qa = con.execute(
                f"""
                SELECT
                    COUNT(*) AS rows,
                    COUNT(DISTINCT visit_key) AS distinct_visit_keys,
                    COUNT(*) FILTER (
                        WHERE race_primary_eligible_t50_flag
                    ) AS race_primary_t50_rows,
                    COUNT(*) FILTER (
                        WHERE sex_gender_primary_eligible_flag
                    ) AS sex_gender_primary_rows,
                    COUNT(*) FILTER (
                        WHERE los_primary_valid_flag
                    ) AS los_primary_valid_rows,
                    COUNT(*) FILTER (
                        WHERE total_charge_reported_real_2024 IS NOT NULL
                    ) AS real_reported_charge_rows,
                    COUNT(*) FILTER (
                        WHERE (
                            black_black + black_white +
                            white_black + white_white
                        ) <> CAST(race_pair_defined_nh_flag AS INTEGER)
                    ) AS race_indicator_sum_errors,
                    COUNT(*) FILTER (
                        WHERE (
                            female_female + female_male +
                            male_female + male_male
                        ) <> CAST(
                            sex_gender_pair_defined_flag AS INTEGER
                        )
                    ) AS sex_gender_indicator_sum_errors
                FROM read_parquet('{qpath(core_path)}')
                """
            ).fetchone()
            qa_names = [
                item[0]
                for item in con.execute(
                    f"""
                    SELECT
                        COUNT(*) AS rows,
                        COUNT(DISTINCT visit_key) AS distinct_visit_keys,
                        COUNT(*) FILTER (
                            WHERE race_primary_eligible_t50_flag
                        ) AS race_primary_t50_rows,
                        COUNT(*) FILTER (
                            WHERE sex_gender_primary_eligible_flag
                        ) AS sex_gender_primary_rows,
                        COUNT(*) FILTER (
                            WHERE los_primary_valid_flag
                        ) AS los_primary_valid_rows,
                        COUNT(*) FILTER (
                            WHERE total_charge_reported_real_2024 IS NOT NULL
                        ) AS real_reported_charge_rows,
                        COUNT(*) FILTER (
                            WHERE (
                                black_black + black_white +
                                white_black + white_white
                            ) <> CAST(
                                race_pair_defined_nh_flag AS INTEGER
                            )
                        ) AS race_indicator_sum_errors,
                        COUNT(*) FILTER (
                            WHERE (
                                female_female + female_male +
                                male_female + male_male
                            ) <> CAST(
                                sex_gender_pair_defined_flag AS INTEGER
                            )
                        ) AS sex_gender_indicator_sum_errors
                    FROM read_parquet('{qpath(core_path)}')
                    LIMIT 0
                    """
                ).description
            ]
            qa_payload = dict(zip(qa_names, qa))
            reconciled = (
                qa_payload["rows"] == qa_payload["distinct_visit_keys"]
                and qa_payload["race_indicator_sum_errors"] == 0
                and qa_payload["sex_gender_indicator_sum_errors"] == 0
            )
            if not reconciled:
                raise RuntimeError(
                    f"QA failed for {year} Q{quarter}: {qa_payload}"
                )

            files = []
            for path in (core_path, charge_path, risk_path):
                files.append(
                    {
                        "name": path.name,
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                        "rows": cohort_rows,
                    }
                )
            success = {
                "created_utc": now_utc(),
                "build_spec_version": COHORT_BUILD_SPEC_VERSION,
                "visit_year": year,
                "visit_quarter": quarter,
                "source_fact_file": str(fact_file),
                "source_fact_sha256": sha256_file(fact_file),
                "provider_master_sha256": provider_master_sha256,
                "provider_race_proxy_sha256": provider_race_proxy_sha256,
                "sample_modulus": args.sample_modulus,
                "cohort_rows": cohort_rows,
                "qa": qa_payload,
                "files": files,
                "reconciliation_passed": reconciled,
                "source_release_modified": False,
            }
            (stage_dir / "_SUCCESS.json").write_text(
                json.dumps(success, indent=2), encoding="utf-8"
            )

            final_dir.parent.mkdir(parents=True, exist_ok=True)
            if final_dir.exists():
                resolved_final = final_dir.resolve()
                if output_root not in resolved_final.parents:
                    raise RuntimeError(f"Unsafe final directory: {final_dir}")
                shutil.rmtree(final_dir)
            os.replace(stage_dir, final_dir)
            build_results.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "status": "built",
                    "rows": cohort_rows,
                }
            )
            con.execute("DROP TABLE IF EXISTS quarter_cohort")

    manifest = {
        "created_utc": now_utc(),
        "build_spec_version": COHORT_BUILD_SPEC_VERSION,
        "release": str(release),
        "output": str(output_root),
        "years": years,
        "quarters": quarters,
        "sample_modulus": args.sample_modulus,
        "elixhauser_flag_count": len(elix_flags),
        "charge_component_count": len(CHARGE_COMPONENTS),
        "partitions": build_results,
        "provider_master_sha256": provider_master_sha256,
        "provider_race_proxy_sha256": provider_race_proxy_sha256,
        "source_release_modified": False,
    }
    (output_root / "cohort_build_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    con.close()


if __name__ == "__main__":
    main()
