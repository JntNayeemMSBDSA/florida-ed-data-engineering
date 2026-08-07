#!/usr/bin/env python3
# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/13_build_historical_sensitivity_cohort.py
# Historical encounter inputs and outputs remain private and are CLI parameters.

"""Build the separately checkpointed 2005-2008 provider-v2 historical cohort.

The output preserves every Phase 1 encounter. Provider linkage, MD/DO
eligibility, full-name race-proxy eligibility, and recorded patient
sex/physician gender eligibility are represented as flags rather than row
filters. This makes linkage selection auditable and prevents the historical
cohort from silently inheriting Phase 1 physician-dependent exclusions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import duckdb


DEFAULT_YEARS = (2005, 2006, 2007, 2008)
DEFAULT_QUARTERS = (1, 2, 3, 4)
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


def parse_int_list(value: str, allowed: set[int]) -> tuple[int, ...]:
    parsed = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    invalid = set(parsed) - allowed
    if not parsed or invalid:
        raise argparse.ArgumentTypeError(
            f"Expected comma-separated values from {sorted(allowed)}; invalid={sorted(invalid)}"
        )
    return parsed


def valid_existing(
    success_path: Path,
    *,
    provider_master_sha256: str,
    race_proxy_sha256: str,
    sample_modulus: int,
) -> dict[str, object] | None:
    if not success_path.exists():
        return None
    try:
        payload = json.loads(success_path.read_text(encoding="utf-8"))
        file_path = success_path.parent / str(payload["file"])
        if (
            payload.get("passed") is True
            and payload.get("build_spec_version") == BUILD_SPEC_VERSION
            and payload.get("provider_master_v2_sha256")
            == provider_master_sha256
            and payload.get("provider_race_proxy_v2_sha256")
            == race_proxy_sha256
            and int(payload.get("sample_modulus", -1))
            == sample_modulus
            and file_path.exists()
            and file_path.stat().st_size == int(payload["bytes"])
            and sha256_file(file_path) == payload["sha256"]
        ):
            return payload
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--years", default="2005,2006,2007,2008")
    parser.add_argument("--quarters", default="1,2,3,4")
    parser.add_argument("--sample-modulus", type=int, default=0)
    parser.add_argument("--output-dir-name", default=OUTPUT_DIR_NAME)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    years = parse_int_list(args.years, set(DEFAULT_YEARS))
    quarters = parse_int_list(args.quarters, set(DEFAULT_QUARTERS))
    if args.sample_modulus < 0:
        raise SystemExit("--sample-modulus must be nonnegative")

    release = args.release.resolve()
    phase2 = args.phase2.resolve()
    temp = args.temp.resolve()
    output = phase2 / "analysis_data" / args.output_dir_name
    provider_master = phase2 / "analysis_data" / "dimensions" / "provider_master_v2.parquet"
    race_proxy = phase2 / "analysis_data" / "dimensions" / "provider_race_proxy_v2.parquet"
    cpi = phase2 / "external_sources" / "bls_cpi_quarterly_factors_to_2024.csv"

    for required in (provider_master, race_proxy, cpi):
        if not required.exists():
            raise FileNotFoundError(required)
    provider_master_sha256 = sha256_file(provider_master)
    race_proxy_sha256 = sha256_file(race_proxy)
    output.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)

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

    sample_fact = (
        release
        / "fact_ed_visits"
        / "visit_year=2005"
        / "visit_quarter=1"
        / "ed_visits.parquet"
    )
    fact_columns = [
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{qpath(sample_fact)}')"
        ).fetchall()
    ]
    elix_flags = sorted(
        name
        for name in fact_columns
        if name.startswith("elix_") and name.endswith("_flag")
    )
    elix_select = ",\n                        ".join(f"f.{name}" for name in elix_flags)

    manifests: list[dict[str, object]] = []
    for year in years:
        for quarter in quarters:
            destination = (
                output
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
            )
            success = destination / "_SUCCESS.json"
            if not args.overwrite:
                existing = valid_existing(
                    success,
                    provider_master_sha256=provider_master_sha256,
                    race_proxy_sha256=race_proxy_sha256,
                    sample_modulus=args.sample_modulus,
                )
                if existing is not None:
                    manifests.append(existing)
                    continue

            destination.mkdir(parents=True, exist_ok=True)
            stage_dir = temp / f"{year}Q{quarter}"
            if stage_dir.exists():
                shutil.rmtree(stage_dir)
            stage_dir.mkdir(parents=True, exist_ok=True)
            stage = stage_dir / f"{OUTPUT_FILE_NAME}.partial"

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
            phase1_success = fact.parent / "_SUCCESS.json"
            for required in (fact, diagnosis, phase1_success):
                if not required.exists():
                    raise FileNotFoundError(required)
            phase1_manifest = json.loads(
                phase1_success.read_text(encoding="utf-8")
            )
            live_fact_sha256 = sha256_file(fact)
            if live_fact_sha256 != phase1_manifest["fact_file_sha256"]:
                raise RuntimeError(
                    f"Immutable Phase 1 fact checksum mismatch for {year} Q{quarter}"
                )

            sample_predicate = (
                f"WHERE hash(f.visit_key) % {args.sample_modulus} = 0"
                if args.sample_modulus > 0
                else ""
            )
            con.execute(
                f"""
                COPY (
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
                            )::UTINYINT AS ami_icd9_anylisted_broad_flag
                        FROM read_parquet(
                            '{qpath(diagnosis)}', hive_partitioning=false
                        )
                        WHERE diagnosis_role IN ('principal', 'secondary')
                          AND diagnosis_code_system = 'ICD-9-CM'
                          AND starts_with(diagnosis_code_norm, '410')
                        GROUP BY visit_key
                    ),
                    base AS (
                        SELECT
                            f.visit_key,
                            f.source_encounter_key,
                            f.visit_year,
                            f.visit_quarter,
                            f.facility_ahca_id,
                            f.facility_ahca_id || ':' ||
                                CAST(f.visit_year AS VARCHAR) || 'Q' ||
                                CAST(f.visit_quarter AS VARCHAR)
                                AS facility_year_quarter_id,
                            f.source_schema_id,
                            f.diagnosis_code_system,
                            f.race_raw AS historical_race_ethnicity_code,
                            f.race_ethnicity_historical_label,
                            CASE
                                WHEN f.race_raw = '3'
                                    THEN 'historical_black_code_3'
                                WHEN f.race_raw = '4'
                                    THEN 'historical_white_code_4'
                            END AS historical_patient_group,
                            f.race_raw IN ('3', '4')
                                AS historical_patient_bw_defined_flag,
                            CASE
                                WHEN f.race_raw IN ('3', '4')
                                THEN (f.race_raw = '3')::UTINYINT
                            END AS patient_black_flag,
                            f.sex_category AS patient_sex_category,
                            f.age_years,
                            f.age_band,
                            f.age_years IS NULL AS age_missing_flag,
                            f.weekday_label,
                            f.weekend_flag,
                            f.arrival_hour,
                            f.arrival_time_band,
                            f.off_hours_flag,
                            f.length_of_stay_days,
                            NULL::INTEGER AS ed_discharge_hour,
                            NULL::DOUBLE AS los_hours_clock_raw,
                            NULL::DOUBLE AS los_hours_primary_0_168,
                            false AS hourly_los_available_flag,
                            'structurally_unavailable_no_discharge_hour'
                                AS los_measurement_status,
                            f.patient_zip_rurality_3level,
                            f.payer_group,
                            f.disposition_group,
                            f.routine_discharge_flag,
                            f.transfer_flag,
                            f.hospice_flag,
                            f.mortality_flag,
                            f.left_discontinued_care_flag,
                            f.same_facility_inpatient_admission_flag,
                            f.same_facility_admission_status,
                            f.revisit_7d_flag,
                            f.revisit_30d_flag,
                            f.revisit_measure_status,
                            f.clinical_triage_level,
                            f.clinical_triage_status,
                            f.principal_diagnosis_code_norm,
                            f.principal_diagnosis_description,
                            f.principal_clinical_category,
                            f.principal_clinical_category_label,
                            f.principal_diagnosis_mapped_flag,
                            f.diagnosis_code_count,
                            f.secondary_diagnosis_code_count,
                            f.external_cause_code_count,
                            f.elixhauser_condition_count,
                            {elix_select},
                            f.cpt_hcpcs_count,
                            f.evaluation_management_code_count,
                            f.icd_procedure_count,
                            f.distinct_procedure_group_count,
                            f.procedure_count_analysis,
                            f.procedure_count_scope,
                            f.any_procedure_flag,
                            f.high_procedure_flag,
                            f.em_acuity_proxy_level,
                            f.em_critical_care_flag,
                            f.em_acuity_proxy_status,
                            f.total_charge_reported,
                            CASE
                                WHEN f.total_charge_reported >= 0
                                THEN f.total_charge_reported *
                                     cu.factor_to_2024_dollars
                            END AS total_charge_reported_real_2024,
                            f.total_charge,
                            CASE
                                WHEN f.total_charge >= 0
                                THEN f.total_charge *
                                     cu.factor_to_2024_dollars
                            END AS total_charge_real_2024,
                            f.component_charge_sum,
                            CASE
                                WHEN f.component_charge_sum >= 0
                                THEN f.component_charge_sum *
                                     cu.factor_to_2024_dollars
                            END AS component_charge_sum_real_2024,
                            f.charge_reconciliation_difference,
                            f.charge_reconciliation_exception_flag,
                            cu.factor_to_2024_dollars
                                AS cpi_u_factor_to_2024,
                            f.attending_practitioner_license_id_raw,
                            f.attending_license_number_norm,
                            f.attending_selected_npi,
                            f.attending_selection_method
                                AS physician_linkage_method,
                            (
                                f.attending_selection_method =
                                    'unique_fl_license_crosswalk'
                                AND f.attending_selected_npi IS NOT NULL
                            ) AS historical_license_link_resolved_flag,
                            p.npi IS NOT NULL
                                AS provider_master_v2_matched_flag,
                            p.phase1_master_match_flag,
                            p.nppes_current_snapshot_match_flag,
                            p.provider_entity_category_v2
                                AS physician_entity_category,
                            p.clinician_type_v2 AS physician_clinician_type,
                            p.physician_md_do_flag_v2
                                AS physician_md_do_flag,
                            (
                                f.attending_selection_method =
                                    'unique_fl_license_crosswalk'
                                AND f.attending_selected_npi IS NOT NULL
                                AND p.provider_entity_category_v2 = 'Individual'
                                AND coalesce(p.physician_md_do_flag_v2, false)
                            ) AS provider_v2_md_do_eligible_flag,
                            'provider_master_v2_full_name_race_v1'
                                AS provider_measurement_version,
                            p.provider_name_v2 AS attending_provider_name,
                            p.gender_category_v2
                                AS physician_gender_category,
                            p.gender_source_v2 AS physician_gender_source,
                            coalesce(
                                p.gender_conflict_flag_v2, false
                            ) AS physician_gender_source_conflict_flag,
                            p.taxonomy_display_name_v2
                                AS attending_taxonomy_display_name,
                            coalesce(
                                p.cms_primary_specialty_v2,
                                p.cms_primary_specialty
                            )
                                AS attending_cms_primary_specialty,
                            p.ed_specialist_flag_v2
                                AS attending_ed_specialist_flag,
                            CASE
                                WHEN p.medical_school_grad_year_v2
                                     BETWEEN 1900 AND f.visit_year
                                 AND f.visit_year
                                     - p.medical_school_grad_year_v2
                                     BETWEEN 0 AND 80
                                THEN f.visit_year
                                    - p.medical_school_grad_year_v2
                            END AS attending_years_since_medical_school,
                            p.has_fl_doh_hospital_privilege
                                AS attending_has_fl_doh_hospital_privilege,
                            p.doh_hospital_privilege_count
                                AS attending_doh_hospital_privilege_count,
                            p.has_cms_group_practice_affiliation_v2
                                AS attending_has_cms_group_practice_affiliation,
                            coalesce(
                                p.cms_group_practice_count_v2,
                                p.cms_group_practice_count
                            )
                                AS attending_cms_group_practice_count,
                            p.has_cms_current_facility_affiliation_v2
                                AS attending_has_cms_current_facility_affiliation,
                            coalesce(
                                p.cms_facility_certification_count_v2, 0
                            ) AS attending_cms_facility_certification_count,
                            p.has_any_current_hospital_affiliation_v2
                                AS attending_has_any_current_hospital_affiliation,
                            r.race_proxy_primary_five_class_label
                                AS physician_race_proxy_primary_label,
                            r.race_proxy_primary_method_id
                                AS physician_race_proxy_method_id,
                            r.race_proxy_method_label
                                AS physician_race_proxy_method_label,
                            r.fl_physician_prob_white
                                AS physician_race_proxy_prob_white,
                            r.fl_physician_prob_black
                                AS physician_race_proxy_prob_black,
                            r.fl_physician_prob_hispanic
                                AS physician_race_proxy_prob_hispanic,
                            r.fl_physician_prob_asian
                                AS physician_race_proxy_prob_asian,
                            r.fl_physician_prob_other
                                AS physician_race_proxy_prob_other,
                            r.population_prob_white
                                AS physician_race_population_prob_white,
                            r.population_prob_black
                                AS physician_race_population_prob_black,
                            r.population_prob_hispanic
                                AS physician_race_population_prob_hispanic,
                            r.population_prob_asian
                                AS physician_race_population_prob_asian,
                            r.population_prob_other
                                AS physician_race_population_prob_other,
                            r.race_proxy_population_five_class_label
                                AS physician_race_population_label,
                            r.race_proxy_population_max_probability
                                AS physician_race_population_max_probability,
                            r.race_proxy_population_black_white_mass
                                AS physician_race_population_black_white_mass,
                            r.race_proxy_population_prob_black_conditional_bw
                                AS physician_race_population_prob_black_conditional_bw,
                            r.race_proxy_label_disagrees_between_priors_flag
                                AS physician_race_label_disagrees_between_priors_flag,
                            r.race_proxy_primary_max_probability
                                AS physician_race_imputation_confidence,
                            r.race_proxy_primary_black_white_mass
                                AS physician_race_proxy_black_white_mass,
                            r.race_proxy_primary_prob_black_conditional_bw
                                AS physician_race_proxy_prob_black_conditional_bw,
                            r.race_proxy_primary_normalized_entropy
                                AS physician_race_proxy_normalized_entropy,
                            r.last_match_flag AS physician_race_last_match_flag,
                            r.first_match_flag
                                AS physician_race_first_match_flag,
                            r.middle_match_flag
                                AS physician_race_middle_match_flag,
                            r.race_proxy_name_match_pattern
                                AS physician_race_name_match_pattern,
                            r.phase1_surname_prob_white,
                            r.phase1_surname_prob_black,
                            r.phase1_surname_prob_hispanic,
                            r.phase1_surname_prob_asian_pi,
                            r.phase1_surname_prob_aian,
                            r.phase1_surname_prob_multiracial,
                            coalesce(
                                a.ami_icd9_anylisted_strict_flag, 0
                            )::UTINYINT AS ami_icd9_anylisted_strict_flag,
                            coalesce(
                                a.ami_icd9_anylisted_broad_flag, 0
                            )::UTINYINT AS ami_icd9_anylisted_broad_flag,
                            (
                                f.diagnosis_code_system = 'ICD-9-CM'
                                AND regexp_full_match(
                                    f.principal_diagnosis_code_norm,
                                    '410[0-9]1'
                                )
                            ) AS ami_icd9_principal_strict_flag,
                            (
                                f.diagnosis_code_system = 'ICD-9-CM'
                                AND regexp_full_match(
                                    f.principal_diagnosis_code_norm,
                                    '410[0-9][01]'
                                )
                            ) AS ami_icd9_principal_broad_flag
                        FROM read_parquet(
                            '{qpath(fact)}', hive_partitioning=false
                        ) AS f
                        LEFT JOIN provider_master_v2 AS p
                          ON f.attending_selected_npi = p.npi
                        LEFT JOIN provider_race_proxy_v2 AS r
                          ON f.attending_selected_npi = r.npi
                        LEFT JOIN cpi AS cu
                          ON f.visit_year = cu.visit_year
                         AND f.visit_quarter = cu.visit_quarter
                         AND cu.series_id = 'CUUR0000SA0'
                        LEFT JOIN ami AS a
                          ON f.visit_key = a.visit_key
                        {sample_predicate}
                    ),
                    eligible AS (
                        SELECT
                            *,
                            (
                                provider_v2_md_do_eligible_flag
                                AND physician_race_proxy_primary_label
                                    IN ('Black', 'White')
                                AND coalesce(
                                    physician_race_last_match_flag, false
                                )
                                AND coalesce(
                                    physician_race_first_match_flag, false
                                )
                            ) AS provider_race_bw_measurement_available_flag,
                            (
                                provider_v2_md_do_eligible_flag
                                AND physician_race_population_label
                                    IN ('Black', 'White')
                                AND coalesce(
                                    physician_race_last_match_flag, false
                                )
                                AND coalesce(
                                    physician_race_first_match_flag, false
                                )
                            ) AS provider_race_population_bw_measurement_available_flag,
                            (
                                provider_v2_md_do_eligible_flag
                                AND physician_gender_category
                                    IN ('Female', 'Male')
                                AND physician_gender_source IN (
                                    'NPPES',
                                    'NPPES February 2026 current snapshot',
                                    'CMS Doctors and Clinicians',
                                    'CMS Doctors and Clinicians June 2026 current snapshot'
                                )
                            ) AS provider_gender_measurement_available_flag
                        FROM base
                    ),
                    analytic_flags AS (
                        SELECT
                            *,
                            (
                                historical_patient_bw_defined_flag
                                AND provider_race_bw_measurement_available_flag
                                AND physician_race_imputation_confidence >= 0.50
                            ) AS historical_race_concordance_eligible_t50_flag,
                            (
                                historical_patient_bw_defined_flag
                                AND provider_race_bw_measurement_available_flag
                                AND physician_race_imputation_confidence >= 0.70
                            ) AS historical_race_concordance_eligible_t70_flag,
                            (
                                historical_patient_bw_defined_flag
                                AND provider_race_bw_measurement_available_flag
                                AND physician_race_imputation_confidence >= 0.80
                            ) AS historical_race_concordance_eligible_t80_flag,
                            (
                                historical_patient_bw_defined_flag
                                AND provider_race_bw_measurement_available_flag
                                AND physician_race_imputation_confidence >= 0.90
                            ) AS historical_race_concordance_eligible_t90_flag,
                            (
                                historical_patient_bw_defined_flag
                                AND
                                provider_race_population_bw_measurement_available_flag
                                AND
                                physician_race_population_max_probability >= 0.50
                            ) AS historical_race_population_prior_eligible_t50_flag,
                            (
                                patient_sex_category IN ('Female', 'Male')
                                AND provider_gender_measurement_available_flag
                            ) AS sex_gender_historical_eligible_flag
                        FROM eligible
                    )
                    SELECT
                        *,
                        CASE
                            WHEN attending_selected_npi IS NOT NULL
                            THEN count(*) OVER (
                                PARTITION BY attending_selected_npi
                            )
                        END AS attending_quarter_volume_all_ed,
                        count(*) OVER (
                            PARTITION BY facility_ahca_id
                        ) AS facility_quarter_volume_all_ed,
                        CASE
                            WHEN historical_race_concordance_eligible_t50_flag
                             AND physician_race_proxy_primary_label = 'Black'
                             AND historical_patient_group =
                                 'historical_black_code_3'
                            THEN 'black_black'
                            WHEN historical_race_concordance_eligible_t50_flag
                             AND physician_race_proxy_primary_label = 'Black'
                             AND historical_patient_group =
                                 'historical_white_code_4'
                            THEN 'black_white'
                            WHEN historical_race_concordance_eligible_t50_flag
                             AND physician_race_proxy_primary_label = 'White'
                             AND historical_patient_group =
                                 'historical_black_code_3'
                            THEN 'white_black'
                            WHEN historical_race_concordance_eligible_t50_flag
                             AND physician_race_proxy_primary_label = 'White'
                             AND historical_patient_group =
                                 'historical_white_code_4'
                            THEN 'white_white'
                        END AS race_pair_category,
                        CASE
                            WHEN historical_race_concordance_eligible_t50_flag
                            THEN (
                                physician_race_proxy_primary_label = 'Black'
                                AND historical_patient_group =
                                    'historical_black_code_3'
                            )::UTINYINT
                        END AS black_black,
                        CASE
                            WHEN historical_race_concordance_eligible_t50_flag
                            THEN (
                                physician_race_proxy_primary_label = 'Black'
                                AND historical_patient_group =
                                    'historical_white_code_4'
                            )::UTINYINT
                        END AS black_white,
                        CASE
                            WHEN historical_race_concordance_eligible_t50_flag
                            THEN (
                                physician_race_proxy_primary_label = 'White'
                                AND historical_patient_group =
                                    'historical_black_code_3'
                            )::UTINYINT
                        END AS white_black,
                        CASE
                            WHEN historical_race_concordance_eligible_t50_flag
                            THEN (
                                physician_race_proxy_primary_label = 'White'
                                AND historical_patient_group =
                                    'historical_white_code_4'
                            )::UTINYINT
                        END AS white_white,
                        CASE
                            WHEN historical_race_concordance_eligible_t50_flag
                            THEN (
                                (
                                    physician_race_proxy_primary_label = 'Black'
                                    AND historical_patient_group =
                                        'historical_black_code_3'
                                )
                                OR (
                                    physician_race_proxy_primary_label = 'White'
                                    AND historical_patient_group =
                                        'historical_white_code_4'
                                )
                            )
                        END AS racial_concordance_flag,
                        CASE
                            WHEN sex_gender_historical_eligible_flag
                             AND physician_gender_category = 'Female'
                             AND patient_sex_category = 'Female'
                            THEN 'female_female'
                            WHEN sex_gender_historical_eligible_flag
                             AND physician_gender_category = 'Female'
                             AND patient_sex_category = 'Male'
                            THEN 'female_male'
                            WHEN sex_gender_historical_eligible_flag
                             AND physician_gender_category = 'Male'
                             AND patient_sex_category = 'Female'
                            THEN 'male_female'
                            WHEN sex_gender_historical_eligible_flag
                             AND physician_gender_category = 'Male'
                             AND patient_sex_category = 'Male'
                            THEN 'male_male'
                        END AS sex_gender_pair_category,
                        CASE
                            WHEN sex_gender_historical_eligible_flag
                            THEN (
                                physician_gender_category = 'Female'
                                AND patient_sex_category = 'Female'
                            )::UTINYINT
                        END AS female_female,
                        CASE
                            WHEN sex_gender_historical_eligible_flag
                            THEN (
                                physician_gender_category = 'Female'
                                AND patient_sex_category = 'Male'
                            )::UTINYINT
                        END AS female_male,
                        CASE
                            WHEN sex_gender_historical_eligible_flag
                            THEN (
                                physician_gender_category = 'Male'
                                AND patient_sex_category = 'Female'
                            )::UTINYINT
                        END AS male_female,
                        CASE
                            WHEN sex_gender_historical_eligible_flag
                            THEN (
                                physician_gender_category = 'Male'
                                AND patient_sex_category = 'Male'
                            )::UTINYINT
                        END AS male_male,
                        CASE
                            WHEN sex_gender_historical_eligible_flag
                            THEN (
                                physician_gender_category =
                                    patient_sex_category
                            )
                        END AS sex_gender_concordance_flag
                    FROM analytic_flags
                ) TO '{qpath(stage)}'
                (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
                """
            )

            final_file = destination / OUTPUT_FILE_NAME
            if final_file.exists():
                final_file.unlink()
            os.replace(stage, final_file)
            qa = con.execute(
                f"""
                SELECT
                    count(*) AS rows,
                    count(DISTINCT visit_key) AS distinct_keys,
                    count(*) FILTER (
                        WHERE hourly_los_available_flag
                           OR los_hours_clock_raw IS NOT NULL
                           OR los_hours_primary_0_168 IS NOT NULL
                           OR ed_discharge_hour IS NOT NULL
                    ) AS hourly_los_errors,
                    count(*) FILTER (
                        WHERE provider_v2_md_do_eligible_flag
                          AND (
                              physician_linkage_method <>
                                  'unique_fl_license_crosswalk'
                              OR physician_entity_category <> 'Individual'
                              OR NOT physician_md_do_flag
                          )
                    ) AS provider_eligibility_errors,
                    count(*) FILTER (
                        WHERE historical_race_concordance_eligible_t50_flag
                          AND coalesce(black_black, 0)
                            + coalesce(black_white, 0)
                            + coalesce(white_black, 0)
                            + coalesce(white_white, 0) <> 1
                    ) AS race_indicator_errors,
                    count(*) FILTER (
                        WHERE sex_gender_historical_eligible_flag
                          AND coalesce(female_female, 0)
                            + coalesce(female_male, 0)
                            + coalesce(male_female, 0)
                            + coalesce(male_male, 0) <> 1
                    ) AS sex_gender_indicator_errors,
                    count(*) FILTER (
                        WHERE physician_linkage_method =
                            'unique_fl_license_crosswalk'
                    ) AS license_resolved_rows,
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
                        WHERE ami_icd9_anylisted_strict_flag = 1
                    ) AS ami_anylisted_strict_rows
                FROM read_parquet(
                    '{qpath(final_file)}', hive_partitioning=false
                )
                """
            ).fetchone()
            expected_rows = (
                con.execute(
                    f"""
                    SELECT count(*)
                    FROM read_parquet('{qpath(fact)}', hive_partitioning=false)
                    {sample_predicate.replace('f.', '')}
                    """
                ).fetchone()[0]
                if args.sample_modulus > 0
                else int(phase1_manifest["output_fact_row_count"])
            )
            passed = bool(
                qa[0] == expected_rows
                and qa[0] == qa[1]
                and qa[2] == 0
                and qa[3] == 0
                and qa[4] == 0
                and qa[5] == 0
            )
            payload: dict[str, object] = {
                "created_utc": now_utc(),
                "visit_year": year,
                "visit_quarter": quarter,
                "build_spec_version": BUILD_SPEC_VERSION,
                "rows": int(qa[0]),
                "expected_phase1_rows": int(expected_rows),
                "distinct_visit_keys": int(qa[1]),
                "hourly_los_errors": int(qa[2]),
                "provider_eligibility_errors": int(qa[3]),
                "race_indicator_errors": int(qa[4]),
                "sex_gender_indicator_errors": int(qa[5]),
                "license_resolved_rows": int(qa[6]),
                "provider_v2_md_do_rows": int(qa[7]),
                "race_t50_rows": int(qa[8]),
                "sex_gender_rows": int(qa[9]),
                "ami_principal_strict_rows": int(qa[10]),
                "ami_anylisted_strict_rows": int(qa[11]),
                "file": final_file.name,
                "bytes": final_file.stat().st_size,
                "sha256": sha256_file(final_file),
                "phase1_fact_sha256": live_fact_sha256,
                "phase1_fact_manifest_sha256": phase1_manifest[
                    "fact_file_sha256"
                ],
                "provider_master_v2_sha256": provider_master_sha256,
                "provider_race_proxy_v2_sha256": race_proxy_sha256,
                "sample_modulus": args.sample_modulus,
                "linkage": "unique Florida license crosswalk only",
                "hourly_los_policy": (
                    "structurally unavailable; null; no day-to-hour imputation"
                ),
                "source_release_modified": False,
                "passed": passed,
            }
            success.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            manifests.append(payload)
            shutil.rmtree(stage_dir, ignore_errors=True)
            if not passed:
                raise RuntimeError(
                    f"Historical provider-v2 build QA failed for {year} Q{quarter}"
                )

    con.close()
    expected_partitions = len(years) * len(quarters)
    status = (
        "PASS"
        if len(manifests) == expected_partitions
        and all(bool(item["passed"]) for item in manifests)
        else "FAIL"
    )
    manifest = {
        "created_utc": now_utc(),
        "status": status,
        "build_spec_version": BUILD_SPEC_VERSION,
        "partitions": len(manifests),
        "expected_partitions": expected_partitions,
        "years": list(years),
        "quarters": list(quarters),
        "sample_modulus": args.sample_modulus,
        "provider_master_v2_sha256": provider_master_sha256,
        "provider_race_proxy_v2_sha256": race_proxy_sha256,
        "rows": sum(int(item["rows"]) for item in manifests),
        "phase1_rows": sum(
            int(item["expected_phase1_rows"]) for item in manifests
        ),
        "provider_v2_md_do_rows": sum(
            int(item["provider_v2_md_do_rows"]) for item in manifests
        ),
        "race_t50_rows": sum(
            int(item["race_t50_rows"]) for item in manifests
        ),
        "sex_gender_rows": sum(
            int(item["sex_gender_rows"]) for item in manifests
        ),
        "definition": (
            "Every 2005-2008 Phase 1 encounter is retained; provider-v2 and "
            "analysis eligibility are flags. The cohort is separate from "
            "2010-2024 and is never silently pooled."
        ),
        "hourly_los_policy": (
            "No ED discharge hour in this schema; hourly LOS fields are null "
            "and no hourly value is imputed from length_of_stay_days."
        ),
        "provider_measurement": (
            "Provider master v2 and full-name race proxy v2; current provider "
            "attributes are not interpreted as historical employment or "
            "privilege status."
        ),
        "source_release_modified": False,
    }
    (output / "historical_provider_v2_build_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    if status != "PASS":
        raise SystemExit("Historical provider-v2 cohort build failed")


if __name__ == "__main__":
    main()
