#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/07_prepare_primary_model_matrix.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Prepare restartable double-precision matrices for full-cohort HDFE models."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


YEARS = tuple(range(2010, 2025))
QUARTERS = (1, 2, 3, 4)
PRIMARY_OUTCOMES = [
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
]
CORE_MODEL_OUTCOMES = [
    *PRIMARY_OUTCOMES,
    "total_charge_reported",
    "total_charge_real_2024",
    "component_charge_sum_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "high_procedure_flag",
    "routine_discharge_flag",
    "transfer_flag",
    "hospice_flag",
    "mortality_flag",
    "left_discontinued_care_flag",
]
CHARGE_COMPONENT_OUTCOMES = [
    "pharmchgs_real_2024",
    "medchgs_real_2024",
    "labchgs_real_2024",
    "radchgs_real_2024",
    "cardiochgs_real_2024",
    "oprmchgs_real_2024",
    "aneschgs_real_2024",
    "recovchgs_real_2024",
    "erchgs_real_2024",
    "traumachgs_real_2024",
    "obserchgs_real_2024",
    "gastrochgs_real_2024",
    "lithochgs_real_2024",
    "othchgs_real_2024",
]
DISCRETION_OUTCOMES = [
    "higher_discretion_procedure_count",
    "lower_discretion_procedure_count",
    "ambiguous_discretion_procedure_count",
    "any_higher_discretion_candidate_flag",
    "any_lower_discretion_candidate_flag",
]
DERIVED_MODEL_OUTCOMES = [
    "log1p_los_hours_primary",
    "log1p_total_charge_reported_real_2024",
    "any_positive_total_charge_reported",
    "los_hours_winsor_yq_p995",
    "total_charge_real_winsor_yq_p995",
    "total_charge_real_winsor_yq_p999",
    "total_charge_reported_real_2024_medical_cpi",
    "higher_minus_lower_discretion_procedure_count",
    "any_higher_minus_any_lower_discretion_candidate",
    "home_health_flag",
]
MODEL_OUTCOMES = [
    *CORE_MODEL_OUTCOMES,
    *CHARGE_COMPONENT_OUTCOMES,
    *DISCRETION_OUTCOMES,
    *DERIVED_MODEL_OUTCOMES,
]
PAYER_LEVELS = [
    "Commercial",
    "Medicaid",
    "Medicare",
    "Self-pay",
    "Non-payment/charity",
    "Other government",
    "Federal government",
    "Workers compensation",
    "Liability",
    "Other",
    "Unknown",
    "<MISSING>",
]
RURALITY_LEVELS = [
    "Metropolitan",
    "Micropolitan",
    "Small town/rural",
    "<MISSING>",
]
ARRIVAL_LEVELS = [
    "Morning",
    "Afternoon",
    "Evening",
    "Night",
    "Unknown",
    "<MISSING>",
]
PATIENT_RACE_ETHNICITY_LEVELS = [
    "NH_White",
    "NH_Black",
    "Hispanic",
    "NH_Other",
    "Unknown",
]
PATIENT_ETHNICITY_LEVELS = [
    "Not Hispanic or Latino",
    "Hispanic or Latino",
    "Unknown",
    "<MISSING>",
]
RECORDED_PHYSICIAN_GENDER_SOURCES = (
    "NPPES",
    "NPPES February 2026 current snapshot",
    "CMS Doctors and Clinicians",
    "CMS Doctors and Clinicians June 2026 current snapshot",
)


def analysis_sample_spec(
    policy: str,
) -> tuple[list[str], list[str], list[str]]:
    """Return filter, confirmatory, and modeled outcomes for a sample policy."""
    if policy == "common_primary":
        return (
            list(PRIMARY_OUTCOMES),
            list(PRIMARY_OUTCOMES),
            list(MODEL_OUTCOMES),
        )
    if policy == "los_outcome":
        return (
            ["los_hours_primary_0_168"],
            ["los_hours_primary_0_168"],
            ["los_hours_primary_0_168"],
        )
    if policy == "charge_outcome":
        return (
            ["total_charge_reported_real_2024"],
            ["total_charge_reported_real_2024"],
            ["total_charge_reported_real_2024"],
        )
    raise ValueError(f"Unsupported analysis sample policy: {policy}")


def eligibility_filters(
    cohort: str, policy: str
) -> tuple[str, str]:
    """Return unaliased and c.-aliased eligibility filters."""
    if policy == "primary":
        if cohort == "race":
            field = "race_primary_eligible_t50_flag"
            return f"{field} = 1", f"c.{field} = 1"
        sources = ", ".join(
            "'" + value.replace("'", "''") + "'"
            for value in RECORDED_PHYSICIAN_GENDER_SOURCES
        )
        plain = (
            "sex_gender_primary_eligible_flag = 1 "
            f"AND physician_gender_source IN ({sources})"
        )
        aliased = (
            "c.sex_gender_primary_eligible_flag = 1 "
            f"AND c.physician_gender_source IN ({sources})"
        )
        return plain, aliased
    if cohort != "race":
        raise ValueError(
            "Expanded linkage/race-semantics policies apply only to race"
        )
    if policy == "race_direct_plus_unique_license_nh_t50":
        plain = (
            "race_pair_defined_nh_flag = 1 "
            "AND physician_linkage_method IN "
            "('direct_validated_npi','unique_fl_license_crosswalk') "
            "AND physician_race_imputation_confidence >= 0.50"
        )
        aliased = (
            "c.race_pair_defined_nh_flag = 1 "
            "AND c.physician_linkage_method IN "
            "('direct_validated_npi','unique_fl_license_crosswalk') "
            "AND c.physician_race_imputation_confidence >= 0.50"
        )
        return plain, aliased
    if policy == "race_only_direct_t50":
        plain = (
            "race_pair_defined_race_only_flag = 1 "
            "AND physician_linkage_method = 'direct_validated_npi' "
            "AND physician_race_imputation_confidence >= 0.50"
        )
        aliased = (
            "c.race_pair_defined_race_only_flag = 1 "
            "AND c.physician_linkage_method = 'direct_validated_npi' "
            "AND c.physician_race_imputation_confidence >= 0.50"
        )
        return plain, aliased
    raise ValueError(f"Unsupported eligibility policy: {policy}")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


@dataclass
class IncrementalEncoder:
    mapping: dict[str, int] = field(default_factory=dict)

    def encode(self, series: pd.Series) -> np.ndarray:
        normalized = series.astype("string").fillna("<MISSING>")
        local_codes, uniques = pd.factorize(normalized, sort=False)
        mapped_unique = np.empty(len(uniques), dtype=np.uint64)
        for index, value in enumerate(uniques.tolist()):
            key = str(value)
            if key not in self.mapping:
                self.mapping[key] = len(self.mapping)
            mapped_unique[index] = self.mapping[key]
        return mapped_unique[local_codes]


def positive_part(values: np.ndarray, knot: float) -> np.ndarray:
    return np.maximum(values - knot, 0.0)


def bool_value(series: pd.Series) -> np.ndarray:
    return series.fillna(False).astype(bool).to_numpy(dtype=np.float64)


def missing_flag(series: pd.Series) -> np.ndarray:
    return series.isna().to_numpy(dtype=np.float64)


def normalize_string(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("<MISSING>")


def patient_race_ethnicity_group(frame: pd.DataFrame) -> np.ndarray:
    race = normalize_string(frame["patient_race_category"])
    ethnicity = normalize_string(frame["patient_ethnicity_category"])
    result = np.full(len(frame), "Unknown", dtype=object)
    hispanic = ethnicity.eq("Hispanic or Latino").to_numpy()
    non_hispanic = ethnicity.eq("Not Hispanic or Latino").to_numpy()
    black = race.eq("Black or African American").to_numpy()
    white = race.eq("White").to_numpy()
    result[hispanic] = "Hispanic"
    result[non_hispanic] = "NH_Other"
    result[non_hispanic & black] = "NH_Black"
    result[non_hispanic & white] = "NH_White"
    return result


def build_design_spec(cohort: str, elix_flags: list[str]) -> list[dict[str, str]]:
    spec: list[dict[str, str]] = []

    def add(name: str, group: str) -> None:
        spec.append({"name": name, "group": group})

    add("intercept", "intercept")
    if cohort == "race":
        add("physician_black_proxy", "exposure")
        add("patient_black", "exposure")
        add("race_interaction", "primary_interaction")
        add("physician_black_probability", "sensitivity_exposure")
        add("race_probability_interaction", "sensitivity_interaction")
        add(
            "physician_black_probability_population_prior",
            "sensitivity_exposure",
        )
        add(
            "race_probability_interaction_population_prior",
            "sensitivity_interaction",
        )
        add("race_proxy_confidence", "selection_only")
        add("eligible_t70", "selection_only")
        add("eligible_t80", "selection_only")
        add("eligible_t90", "selection_only")
        add("intersectional_eligible", "selection_only")
        for name in (
            "intersection_physician_female",
            "intersection_patient_female",
            "intersection_female_pair",
            "intersection_physician_black_x_physician_female",
            "intersection_physician_black_x_patient_female",
            "intersection_patient_black_x_physician_female",
            "intersection_patient_black_x_patient_female",
            "intersection_race_pair_x_physician_female",
            "intersection_race_pair_x_patient_female",
            "intersection_physician_black_x_female_pair",
            "intersection_patient_black_x_female_pair",
            "intersection_four_way",
        ):
            add(name, "intersectional")
    else:
        add("physician_female", "exposure")
        add("patient_female", "exposure")
        add("sex_gender_interaction", "primary_interaction")
        add("physician_gender_source_no_conflict", "selection_only")
    add("visit_year_numeric", "selection_only")
    add("los_le72", "selection_only")
    add("positive_reported_charge", "selection_only")
    add("complete_case_covariates", "selection_only")
    add("em_acuity_available", "selection_only")
    add("em_acuity_value", "selection_only")
    add("em_critical_care_available", "selection_only")
    add("em_critical_care_value", "selection_only")
    add("presentation_subjectivity_classified", "selection_only")

    for name in (
        "age",
        "age_gt18",
        "age_gt45",
        "age_gt65",
        "age_gt80",
        "age_missing",
    ):
        add(name, "patient_visit")
    if cohort == "race":
        add("patient_female", "patient_visit")
        add("patient_sex_unknown", "patient_visit")
        for level in PATIENT_ETHNICITY_LEVELS[1:]:
            add(f"patient_ethnicity__{level}", "patient_visit")
    else:
        for level in PATIENT_RACE_ETHNICITY_LEVELS[1:]:
            add(f"patient_race_ethnicity__{level}", "patient_visit")

    for level in PAYER_LEVELS[1:]:
        add(f"payer__{level}", "patient_visit")
    for level in RURALITY_LEVELS[1:]:
        add(f"patient_rurality__{level}", "patient_visit")
    for name in (
        "weekend",
        "weekend_missing",
        "off_hours",
        "off_hours_missing",
    ):
        add(name, "patient_visit")
    for level in ARRIVAL_LEVELS[1:]:
        add(f"arrival_band__{level}", "patient_visit")
    for flag in elix_flags:
        add(flag, "patient_risk")
    add("elixhauser_condition_count", "patient_risk")
    for name in (
        "physician_ed_specialist",
        "physician_ed_specialist_missing",
        "experience",
        "experience_gt10",
        "experience_gt20",
        "experience_gt30",
        "experience_missing",
        "log1p_physician_quarter_volume",
        "physician_quarter_volume_missing",
    ):
        add(name, "physician")
    for modifier in (
        "symptom_sign",
        "uninsured",
        "ed_specialist",
        "age65plus",
        "high_comorbidity",
        "icd10_era",
        "high_experience",
        "high_physician_volume",
        "facility_rural",
        "facility_for_profit",
        "classified_subjectivity_high",
    ):
        add(modifier, f"heterogeneity_{modifier}")
        add(
            f"{modifier}_x_physician",
            f"heterogeneity_{modifier}",
        )
        add(
            f"{modifier}_x_patient",
            f"heterogeneity_{modifier}",
        )
        add(
            f"{modifier}_x_interaction",
            f"heterogeneity_{modifier}",
        )
    return spec


def primary_sequence_design_spec(
    full_spec: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Retain exactly the columns consumed by primary M1/M2/M3 models."""
    primary_model_groups = {
        "intercept",
        "exposure",
        "primary_interaction",
        "patient_visit",
        "patient_risk",
        "physician",
    }
    return [
        item for item in full_spec
        if item["group"] in primary_model_groups
    ]


def design_batch(
    frame: pd.DataFrame,
    cohort: str,
    elix_flags: list[str],
    age_median: float,
    experience_median: float,
    design_spec: list[dict[str, str]],
    subjectivity_mapping: dict[str, str],
) -> np.ndarray:
    n = len(frame)
    arrays: dict[str, np.ndarray] = {"intercept": np.ones(n, dtype=np.float64)}

    if cohort == "race":
        physician = frame["physician_black_imputed_flag"].to_numpy(
            dtype=np.float64
        )
        patient = frame["patient_black_flag"].to_numpy(dtype=np.float64)
        arrays["physician_black_proxy"] = physician
        arrays["patient_black"] = patient
        arrays["race_interaction"] = physician * patient
        prob_black = pd.to_numeric(
            frame["physician_race_proxy_prob_black"], errors="coerce"
        ).to_numpy(dtype=np.float64)
        prob_white = pd.to_numeric(
            frame["physician_race_proxy_prob_white"], errors="coerce"
        ).to_numpy(dtype=np.float64)
        probability_denominator = prob_black + prob_white
        probability = np.divide(
            prob_black,
            probability_denominator,
            out=physician.copy(),
            where=(
                np.isfinite(probability_denominator)
                & (probability_denominator > 0)
            ),
        )
        probability = np.clip(probability, 0, 1)
        arrays["physician_black_probability"] = probability
        arrays["race_probability_interaction"] = probability * patient
        population_prob_black = pd.to_numeric(
            frame["physician_race_population_prob_black"],
            errors="coerce",
        ).to_numpy(dtype=np.float64)
        population_prob_white = pd.to_numeric(
            frame["physician_race_population_prob_white"],
            errors="coerce",
        ).to_numpy(dtype=np.float64)
        population_denominator = (
            population_prob_black + population_prob_white
        )
        population_probability = np.divide(
            population_prob_black,
            population_denominator,
            out=probability.copy(),
            where=(
                np.isfinite(population_denominator)
                & (population_denominator > 0)
            ),
        )
        population_probability = np.clip(
            population_probability, 0, 1
        )
        arrays[
            "physician_black_probability_population_prior"
        ] = population_probability
        arrays[
            "race_probability_interaction_population_prior"
        ] = population_probability * patient
        arrays["race_proxy_confidence"] = pd.to_numeric(
            frame["physician_race_imputation_confidence"], errors="coerce"
        ).to_numpy(dtype=np.float64)
        arrays["eligible_t70"] = bool_value(
            frame["race_primary_eligible_t70_flag"]
        )
        arrays["eligible_t80"] = bool_value(
            frame["race_primary_eligible_t80_flag"]
        )
        arrays["eligible_t90"] = bool_value(
            frame["race_primary_eligible_t90_flag"]
        )
        intersectional_eligible = bool_value(
            frame["sex_gender_primary_eligible_flag"]
        )
        intersectional_eligible *= (
            frame["physician_gender_source"]
            .isin(RECORDED_PHYSICIAN_GENDER_SOURCES)
            .to_numpy(dtype=np.float64)
        )
        physician_female = (
            frame["physician_gender_category"]
            .eq("Female")
            .to_numpy(dtype=np.float64)
        )
        patient_female_intersection = (
            frame["patient_sex_category"]
            .eq("Female")
            .to_numpy(dtype=np.float64)
        )
        arrays["intersectional_eligible"] = intersectional_eligible
        arrays["intersection_physician_female"] = physician_female
        arrays["intersection_patient_female"] = patient_female_intersection
        arrays["intersection_female_pair"] = (
            physician_female * patient_female_intersection
        )
        arrays["intersection_physician_black_x_physician_female"] = (
            physician * physician_female
        )
        arrays["intersection_physician_black_x_patient_female"] = (
            physician * patient_female_intersection
        )
        arrays["intersection_patient_black_x_physician_female"] = (
            patient * physician_female
        )
        arrays["intersection_patient_black_x_patient_female"] = (
            patient * patient_female_intersection
        )
        arrays["intersection_race_pair_x_physician_female"] = (
            physician * patient * physician_female
        )
        arrays["intersection_race_pair_x_patient_female"] = (
            physician * patient * patient_female_intersection
        )
        arrays["intersection_physician_black_x_female_pair"] = (
            physician * physician_female * patient_female_intersection
        )
        arrays["intersection_patient_black_x_female_pair"] = (
            patient * physician_female * patient_female_intersection
        )
        arrays["intersection_four_way"] = (
            physician
            * patient
            * physician_female
            * patient_female_intersection
        )
    else:
        physician = (
            frame["physician_gender_category"]
            .eq("Female")
            .to_numpy(dtype=np.float64)
        )
        patient = (
            frame["patient_sex_category"]
            .eq("Female")
            .to_numpy(dtype=np.float64)
        )
        arrays["physician_female"] = physician
        arrays["patient_female"] = patient
        arrays["sex_gender_interaction"] = physician * patient
        arrays["physician_gender_source_no_conflict"] = (
            ~frame["physician_gender_source_conflict_flag"]
            .fillna(False)
            .astype(bool)
            .to_numpy()
        ).astype(np.float64)
    arrays["visit_year_numeric"] = frame["visit_year"].to_numpy(
        dtype=np.float64
    )
    arrays["los_le72"] = (
        frame["los_hours_primary_0_168"].to_numpy(dtype=np.float64) <= 72
    ).astype(np.float64)
    arrays["positive_reported_charge"] = (
        frame["total_charge_reported_real_2024"].to_numpy(dtype=np.float64) > 0
    ).astype(np.float64)
    em_acuity = pd.to_numeric(
        frame["em_acuity_proxy_level"], errors="coerce"
    ).to_numpy(dtype=np.float64)
    em_acuity_available = np.isfinite(em_acuity) & (em_acuity >= 1) & (
        em_acuity <= 5
    )
    arrays["em_acuity_available"] = em_acuity_available.astype(np.float64)
    arrays["em_acuity_value"] = np.where(
        em_acuity_available, em_acuity, 0.0
    )
    em_critical = pd.to_numeric(
        frame["em_critical_care_flag"], errors="coerce"
    ).to_numpy(dtype=np.float64)
    em_critical_available = np.isfinite(em_critical)
    arrays["em_critical_care_available"] = (
        em_critical_available.astype(np.float64)
    )
    arrays["em_critical_care_value"] = np.where(
        em_critical_available, em_critical, 0.0
    )

    raw_age = pd.to_numeric(frame["age_years"], errors="coerce").to_numpy(
        dtype=np.float64
    )
    invalid_age = (~np.isfinite(raw_age)) | (raw_age < 0) | (raw_age > 120)
    age = raw_age.copy()
    age[invalid_age] = age_median
    arrays["age"] = age
    arrays["age_gt18"] = positive_part(age, 18)
    arrays["age_gt45"] = positive_part(age, 45)
    arrays["age_gt65"] = positive_part(age, 65)
    arrays["age_gt80"] = positive_part(age, 80)
    arrays["age_missing"] = invalid_age.astype(np.float64)

    if cohort == "race":
        sex = normalize_string(frame["patient_sex_category"])
        arrays["patient_female"] = sex.eq("Female").to_numpy(dtype=np.float64)
        arrays["patient_sex_unknown"] = (
            ~sex.isin(["Female", "Male"])
        ).to_numpy(dtype=np.float64)
        ethnicity = normalize_string(
            frame["patient_ethnicity_category"]
        ).to_numpy()
        for level in PATIENT_ETHNICITY_LEVELS[1:]:
            arrays[f"patient_ethnicity__{level}"] = (
                ethnicity == level
            ).astype(np.float64)
    else:
        race_ethnicity = patient_race_ethnicity_group(frame)
        for level in PATIENT_RACE_ETHNICITY_LEVELS[1:]:
            arrays[f"patient_race_ethnicity__{level}"] = (
                race_ethnicity == level
            ).astype(np.float64)

    payer = normalize_string(frame["payer_group"]).to_numpy()
    for level in PAYER_LEVELS[1:]:
        arrays[f"payer__{level}"] = (payer == level).astype(np.float64)
    rurality = normalize_string(
        frame["patient_zip_rurality_3level"]
    ).to_numpy()
    for level in RURALITY_LEVELS[1:]:
        arrays[f"patient_rurality__{level}"] = (
            rurality == level
        ).astype(np.float64)

    arrays["weekend"] = bool_value(frame["weekend_flag"])
    arrays["weekend_missing"] = missing_flag(frame["weekend_flag"])
    arrays["off_hours"] = bool_value(frame["off_hours_flag"])
    arrays["off_hours_missing"] = missing_flag(frame["off_hours_flag"])
    arrival = normalize_string(frame["arrival_time_band"]).to_numpy()
    for level in ARRIVAL_LEVELS[1:]:
        arrays[f"arrival_band__{level}"] = (
            arrival == level
        ).astype(np.float64)

    for flag in elix_flags:
        arrays[flag] = (
            pd.to_numeric(frame[flag], errors="coerce")
            .fillna(0)
            .to_numpy(dtype=np.float64)
        )
    arrays["elixhauser_condition_count"] = (
        pd.to_numeric(frame["elixhauser_condition_count"], errors="coerce")
        .fillna(0)
        .to_numpy(dtype=np.float64)
    )

    specialist = frame["attending_ed_specialist_flag"]
    arrays["physician_ed_specialist"] = bool_value(specialist)
    arrays["physician_ed_specialist_missing"] = missing_flag(specialist)
    raw_experience = pd.to_numeric(
        frame["attending_years_since_medical_school"], errors="coerce"
    ).to_numpy(dtype=np.float64)
    invalid_experience = (
        (~np.isfinite(raw_experience))
        | (raw_experience < 0)
        | (raw_experience > 80)
    )
    experience = raw_experience.copy()
    experience[invalid_experience] = experience_median
    arrays["experience"] = experience
    arrays["experience_gt10"] = positive_part(experience, 10)
    arrays["experience_gt20"] = positive_part(experience, 20)
    arrays["experience_gt30"] = positive_part(experience, 30)
    arrays["experience_missing"] = invalid_experience.astype(np.float64)
    volume = pd.to_numeric(
        frame["attending_quarter_volume_all_ed"], errors="coerce"
    ).to_numpy(dtype=np.float64)
    invalid_volume = (~np.isfinite(volume)) | (volume < 0)
    volume[invalid_volume] = 0
    arrays["log1p_physician_quarter_volume"] = np.log1p(volume)
    arrays["physician_quarter_volume_missing"] = invalid_volume.astype(
        np.float64
    )
    complete_case = (
        (arrays["age_missing"] == 0)
        & ~np.isin(payer, ["Unknown", "<MISSING>"])
        & (rurality != "<MISSING>")
        & (arrays["weekend_missing"] == 0)
        & (arrays["off_hours_missing"] == 0)
        & ~np.isin(arrival, ["Unknown", "<MISSING>"])
        & (arrays["physician_ed_specialist_missing"] == 0)
        & (arrays["experience_missing"] == 0)
        & (arrays["physician_quarter_volume_missing"] == 0)
    )
    if cohort == "race":
        complete_case &= arrays["patient_sex_unknown"] == 0
    else:
        complete_case &= race_ethnicity != "Unknown"
    arrays["complete_case_covariates"] = complete_case.astype(np.float64)

    subjectivity_key = (
        normalize_string(frame["diagnosis_code_system"])
        + "|"
        + normalize_string(frame["principal_clinical_category"])
    )
    subjectivity_group = subjectivity_key.map(subjectivity_mapping).fillna(
        "ambiguous_or_mixed"
    )
    subjectivity_classified = subjectivity_group.isin(
        [
            "higher_subjectivity_proxy_symptom_sign_coded",
            "lower_subjectivity_proxy_disease_condition_injury_coded",
        ]
    ).to_numpy(dtype=np.float64)
    subjectivity_high = subjectivity_group.eq(
        "higher_subjectivity_proxy_symptom_sign_coded"
    ).to_numpy(dtype=np.float64)
    arrays["presentation_subjectivity_classified"] = subjectivity_classified

    modifiers = {
        "symptom_sign": (
            frame["presentation_code_group"]
            .eq("symptom_sign_coded")
            .to_numpy(dtype=np.float64)
        ),
        "uninsured": (
            frame["payer_group"]
            .isin(["Self-pay", "Non-payment/charity"])
            .to_numpy(dtype=np.float64)
        ),
        "ed_specialist": arrays["physician_ed_specialist"],
        "age65plus": (age >= 65).astype(np.float64),
        "high_comorbidity": (
            arrays["elixhauser_condition_count"] >= 3
        ).astype(np.float64),
        "icd10_era": (
            frame["diagnosis_code_system"]
            .eq("ICD-10-CM")
            .to_numpy(dtype=np.float64)
        ),
        "high_experience": (
            (~invalid_experience) & (experience >= 20)
        ).astype(np.float64),
        "high_physician_volume": (
            (~invalid_volume) & (volume >= 250)
        ).astype(np.float64),
        "facility_rural": (
            frame["facility_rurality_3level"]
            .isin(["Micropolitan", "Small town/rural"])
            .to_numpy(dtype=np.float64)
        ),
        "facility_for_profit": (
            frame["cms_hospital_ownership"]
            .eq("Proprietary")
            .to_numpy(dtype=np.float64)
        ),
        "classified_subjectivity_high": subjectivity_high,
    }
    for modifier_name, modifier in modifiers.items():
        arrays[modifier_name] = modifier
        arrays[f"{modifier_name}_x_physician"] = modifier * physician
        arrays[f"{modifier_name}_x_patient"] = modifier * patient
        arrays[f"{modifier_name}_x_interaction"] = modifier * physician * patient

    matrix = np.column_stack([arrays[item["name"]] for item in design_spec])
    if not np.isfinite(matrix).all():
        raise RuntimeError("Non-finite value found in prepared design matrix")
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--cohort", required=True, choices=("race", "sex_gender"))
    parser.add_argument(
        "--analysis-sample",
        choices=("common_primary", "los_outcome", "charge_outcome"),
        default="common_primary",
        help=(
            "common_primary retains the original common LOS/charge sample as "
            "a robustness analysis; los_outcome and charge_outcome create the "
            "outcome-specific confirmatory samples required by the SAP"
        ),
    )
    parser.add_argument(
        "--eligibility-policy",
        choices=(
            "primary",
            "race_direct_plus_unique_license_nh_t50",
            "race_only_direct_t50",
        ),
        default="primary",
        help=(
            "Exposure/linkage cohort rule. Expanded policies are prespecified "
            "race sensitivity analyses."
        ),
    )
    parser.add_argument(
        "--matrix-id",
        default="",
        help=(
            "Optional single-directory identifier below --scratch. Defaults "
            "to the cohort name for the common-primary matrix."
        ),
    )
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--batch-size", type=int, default=100_000)
    parser.add_argument("--hash-large-files", action="store_true")
    parser.add_argument(
        "--minimum-free-reserve-gb",
        type=float,
        default=40.0,
        help=(
            "Stop before allocating a new matrix unless enough disk remains "
            "for the matrix, its M2/M3 demeaning scratch, and this reserve."
        ),
    )
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    provider_gate_path = phase2 / "qa" / "pre_estimation_measurement_gate.json"
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"
    for gate_path in (provider_gate_path, cohort_gate_path):
        if not gate_path.exists():
            raise SystemExit(f"Required pre-model gate is missing: {gate_path}")
    provider_gate = json.loads(
        provider_gate_path.read_text(encoding="utf-8")
    )
    cohort_gate = json.loads(cohort_gate_path.read_text(encoding="utf-8"))
    if provider_gate.get("status") != "PASS":
        raise SystemExit(
            "Provider-v2 pre-estimation gate did not authorize matrix creation"
        )
    if cohort_gate.get("status") != "PASS":
        raise SystemExit(
            "Cohort validation gate did not authorize matrix creation"
        )
    provider_gate_sha256 = sha256_file(provider_gate_path)
    cohort_gate_sha256 = sha256_file(cohort_gate_path)
    gender_checkpoint_path = (
        phase2 / "qa" / "provider_gender_measurement_checkpoint.json"
    )
    if not gender_checkpoint_path.is_file():
        raise SystemExit(
            "Physician-gender measurement checkpoint is required before "
            f"matrix creation: {gender_checkpoint_path}"
        )
    gender_checkpoint = json.loads(
        gender_checkpoint_path.read_text(encoding="utf-8")
    )
    if (
        gender_checkpoint.get("status") != "PASS"
        or gender_checkpoint.get("estimate_blind") is not True
        or gender_checkpoint.get("primary_definition", {}).get(
            "physician_gender_sources"
        )
        != list(RECORDED_PHYSICIAN_GENDER_SOURCES)
    ):
        raise SystemExit(
            "Physician-gender measurement checkpoint did not authorize the "
            "recorded-source primary definition"
        )
    gender_checkpoint_sha256 = sha256_file(gender_checkpoint_path)
    matrix_builder_sha256 = sha256_file(Path(__file__).resolve())
    subjectivity_review_path = (
        phase2
        / "results"
        / "clinical_classification"
        / "presentation_subjectivity_review.csv"
    )
    if not subjectivity_review_path.is_file():
        raise SystemExit(
            "The versioned presentation-subjectivity review is required before "
            f"matrix creation: {subjectivity_review_path}"
        )
    subjectivity_review_sha256 = sha256_file(subjectivity_review_path)
    subjectivity_review = pd.read_csv(subjectivity_review_path, dtype=str)
    required_subjectivity_columns = {
        "diagnosis_code_system",
        "source_clinical_category",
        "assigned_group",
        "version",
    }
    missing_subjectivity_columns = (
        required_subjectivity_columns - set(subjectivity_review.columns)
    )
    if missing_subjectivity_columns:
        raise RuntimeError(
            "Presentation-subjectivity review is missing columns: "
            f"{sorted(missing_subjectivity_columns)}"
        )
    allowed_subjectivity_groups = {
        "higher_subjectivity_proxy_symptom_sign_coded",
        "lower_subjectivity_proxy_disease_condition_injury_coded",
        "ambiguous_or_mixed",
    }
    unexpected_subjectivity_groups = set(
        subjectivity_review["assigned_group"].dropna()
    ) - allowed_subjectivity_groups
    if unexpected_subjectivity_groups:
        raise RuntimeError(
            "Unexpected presentation-subjectivity labels: "
            f"{sorted(unexpected_subjectivity_groups)}"
        )
    subjectivity_review["_mapping_key"] = (
        subjectivity_review["diagnosis_code_system"].fillna("").str.strip()
        + "|"
        + subjectivity_review["source_clinical_category"].fillna("").str.strip()
    )
    subjectivity_conflicts = (
        subjectivity_review.groupby("_mapping_key", dropna=False)[
            "assigned_group"
        ]
        .nunique(dropna=False)
        .loc[lambda values: values > 1]
    )
    if len(subjectivity_conflicts):
        raise RuntimeError(
            "Conflicting presentation-subjectivity labels for clinical keys: "
            f"{subjectivity_conflicts.index[:10].tolist()}"
        )
    subjectivity_mapping = (
        subjectivity_review.drop_duplicates("_mapping_key")
        .set_index("_mapping_key")["assigned_group"]
        .to_dict()
    )
    subjectivity_versions = sorted(
        subjectivity_review["version"].dropna().unique().tolist()
    )
    if len(subjectivity_versions) != 1:
        raise RuntimeError(
            "Presentation-subjectivity review must contain exactly one version; "
            f"found {subjectivity_versions}"
        )
    subjectivity_review_version = subjectivity_versions[0]
    classification_manifest_path = (
        phase2
        / "results"
        / "clinical_classification"
        / "clinical_classification_manifest.json"
    )
    if not classification_manifest_path.is_file():
        raise SystemExit(
            "Clinical-classification manifest is required before matrix "
            f"creation: {classification_manifest_path}"
        )
    classification_manifest = json.loads(
        classification_manifest_path.read_text(encoding="utf-8")
    )
    if (
        classification_manifest.get("status_gate") != "PASS"
        or classification_manifest.get("all_sidecars_passed") is not True
        or classification_manifest.get("version") != subjectivity_review_version
        or classification_manifest.get("presentation_review_sha256")
        != subjectivity_review_sha256
        or len(classification_manifest.get("sidecar_manifests", [])) != 60
    ):
        raise RuntimeError(
            "Clinical-classification manifest is incomplete or inconsistent "
            "with the presentation review"
        )
    classification_manifest_sha256 = sha256_file(
        classification_manifest_path
    )
    data_root = (
        phase2 / "analysis_data" / "concordance_visit_data_provider_v2"
    )
    provider_master_path = (
        phase2 / "analysis_data" / "dimensions" / "provider_master_v2.parquet"
    )
    if not provider_master_path.is_file():
        raise SystemExit(
            f"Provider master v2 is required: {provider_master_path}"
        )
    (
        filter_outcomes,
        primary_outcomes,
        model_outcomes,
    ) = analysis_sample_spec(args.analysis_sample)
    matrix_id = args.matrix_id.strip() or args.cohort
    if Path(matrix_id).name != matrix_id or matrix_id in {".", ".."}:
        raise SystemExit("--matrix-id must be one safe directory name")
    output = (args.scratch / matrix_id).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "duckdb_temp").mkdir(parents=True, exist_ok=True)
    success_path = output / "_SUCCESS.json"
    if success_path.exists():
        existing = json.loads(success_path.read_text(encoding="utf-8"))
        if (
            existing.get("provider_measurement_version")
                == "provider_master_v2_full_name_race_v1"
            and existing.get("provider_gate_sha256")
                == provider_gate_sha256
            and existing.get("cohort_gate_sha256") == cohort_gate_sha256
            and existing.get("gender_checkpoint_sha256")
                == gender_checkpoint_sha256
            and existing.get("matrix_builder_sha256")
                == matrix_builder_sha256
            and existing.get("subjectivity_review_sha256")
                == subjectivity_review_sha256
            and existing.get("classification_manifest_sha256")
                == classification_manifest_sha256
            and existing.get("analysis_sample_policy")
                == args.analysis_sample
            and existing.get("eligibility_policy")
                == args.eligibility_policy
            and existing.get("matrix_id") == matrix_id
        ):
            print(success_path.read_text(encoding="utf-8"))
            return
        raise SystemExit(
            "Existing model matrix is stale relative to provider-v2 gates; "
            "preserve it for audit and choose a new matrix root"
        )

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(output / 'duckdb_temp')}'")
    con.execute("SET preserve_insertion_order=false")

    sample_risk = (
        data_root
        / "visit_year=2010"
        / "visit_quarter=1"
        / "concordance_elixhauser_flags.parquet"
    )
    elix_flags = sorted(
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{qpath(sample_risk)}')"
        ).fetchall()
        if row[0].startswith("elix_") and row[0].endswith("_flag")
    )
    design_spec = build_design_spec(args.cohort, elix_flags)
    design_scope = "full_secondary_analysis"
    if (
        args.analysis_sample in {"los_outcome", "charge_outcome"}
        or args.eligibility_policy != "primary"
    ):
        # Outcome-specific confirmatory matrices and adjusted cohort-definition
        # sensitivities are consumed only by the M1/M2/M3 primary sequence.
        # Excluding unused selection, probability, heterogeneity, and
        # intersectional columns avoids hundreds of gigabytes of redundant
        # temporary storage without changing any fitted specification.
        design_spec = primary_sequence_design_spec(design_spec)
        design_scope = "primary_model_sequence_only"
    design_names = [item["name"] for item in design_spec]

    eligibility, eligibility_aliased = eligibility_filters(
        args.cohort, args.eligibility_policy
    )
    outcome_filter = " AND ".join(
        f"{name} IS NOT NULL" for name in filter_outcomes
    )
    row_counts: list[dict[str, int]] = []
    for year in YEARS:
        for quarter in QUARTERS:
            core = (
                data_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "concordance_visit_core.parquet"
            )
            values = con.execute(
                f"""
                SELECT
                    count(*) AS n,
                    quantile_cont(los_hours_primary_0_168, 0.995)
                        AS los_p995,
                    quantile_cont(
                        total_charge_reported_real_2024, 0.995
                    ) AS charge_p995,
                    quantile_cont(
                        total_charge_reported_real_2024, 0.999
                    ) AS charge_p999
                FROM read_parquet('{qpath(core)}', hive_partitioning=false)
                WHERE {eligibility} AND {outcome_filter}
                """
            ).fetchone()
            n = int(values[0])
            row_counts.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "rows": n,
                    "los_p995": (
                        float(values[1])
                        if values[1] is not None
                        else math.nan
                    ),
                    "charge_p995": (
                        float(values[2])
                        if values[2] is not None
                        else math.nan
                    ),
                    "charge_p999": (
                        float(values[3])
                        if values[3] is not None
                        else math.nan
                    ),
                }
            )
    core_glob = (
        data_root
        / "visit_year=*"
        / "visit_quarter=*"
        / "concordance_visit_core.parquet"
    )
    exact_medians = con.execute(
        f"""
        SELECT
            quantile_cont(age_years, 0.5)
                FILTER (WHERE age_years BETWEEN 0 AND 120),
            quantile_cont(attending_years_since_medical_school, 0.5)
                FILTER (
                    WHERE attending_years_since_medical_school BETWEEN 0 AND 80
                )
        FROM read_parquet('{qpath(core_glob)}', hive_partitioning=false)
        WHERE {eligibility} AND {outcome_filter}
        """
    ).fetchone()
    age_median = float(exact_medians[0])
    experience_median = float(exact_medians[1])
    n_rows = sum(item["rows"] for item in row_counts)
    n_columns = len(design_names)
    if n_rows <= 0:
        raise RuntimeError("No eligible rows for requested model cohort")
    groups = [item["group"] for item in design_spec]
    m2_columns = [
        index
        for index, group in enumerate(groups)
        if group
        not in (
            "intercept",
            "sensitivity_exposure",
            "sensitivity_interaction",
            "selection_only",
        )
        and not group.startswith("heterogeneity_")
        and group != "intersectional"
    ]
    absorbed_physician_main = (
        "physician_black_proxy"
        if args.cohort == "race"
        else "physician_female"
    )
    m3_columns = [
        index
        for index, (name, group) in enumerate(
            zip(design_names, groups)
        )
        if group != "intercept"
        and group
        not in (
            "sensitivity_exposure",
            "sensitivity_interaction",
            "selection_only",
        )
        and not group.startswith("heterogeneity_")
        and group != "intersectional"
        and name != absorbed_physician_main
        and (
            group != "physician"
            or name
            in (
                "log1p_physician_quarter_volume",
                "physician_quarter_volume_missing",
            )
        )
    ]
    raw_matrix_bytes = n_rows * (
        8 * n_columns
        + 8 * len(model_outcomes)
        + 8 * 3
        + 8 * 3
    )
    demeaning_scratch_bytes = n_rows * (
        8 * (len(m2_columns) + len(m3_columns))
        + 8 * len(model_outcomes) * 2
    )
    estimated_peak_new_bytes = (
        raw_matrix_bytes + demeaning_scratch_bytes
    )
    reserve_bytes = int(args.minimum_free_reserve_gb * (1024**3))
    free_bytes = shutil.disk_usage(output).free
    if free_bytes < estimated_peak_new_bytes + reserve_bytes:
        preflight = {
            "created_utc": now_utc(),
            "matrix_id": matrix_id,
            "n_rows": n_rows,
            "n_design_columns": n_columns,
            "n_outcomes": len(model_outcomes),
            "m2_columns": len(m2_columns),
            "m3_columns": len(m3_columns),
            "raw_matrix_bytes": raw_matrix_bytes,
            "demeaning_scratch_bytes": demeaning_scratch_bytes,
            "estimated_peak_new_bytes": estimated_peak_new_bytes,
            "free_bytes": free_bytes,
            "minimum_reserve_bytes": reserve_bytes,
            "preflight_passed": False,
        }
        atomic_json(output / "storage_preflight.json", preflight)
        raise RuntimeError(
            "Insufficient disk for restartable matrix plus M2/M3 scratch: "
            f"need {(estimated_peak_new_bytes + reserve_bytes) / 1024**3:.1f} "
            f"GiB, have {free_bytes / 1024**3:.1f} GiB. Run matrices "
            "sequentially and compact only after independent audit."
        )

    matrix_path = output / "raw_design.float64.mmap"
    outcomes_path = output / "model_outcomes.float64.mmap"
    fe_path = output / "fe_codes.uint64.mmap"
    cluster_path = output / "cluster_codes.uint64.mmap"
    state_path = output / "build_state.json"
    encoders_path = output / "encoders.json"
    encoders = {
        "physician": IncrementalEncoder(),
        "facility_yq": IncrementalEncoder(),
        "clinical": IncrementalEncoder(),
        "facility": IncrementalEncoder(),
        "physician_facility": IncrementalEncoder(),
    }
    resumable = (
        state_path.exists()
        and encoders_path.exists()
        and all(
            path.exists()
            for path in (matrix_path, outcomes_path, fe_path, cluster_path)
        )
    )
    if resumable:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (
            state.get("cohort") != args.cohort
            or int(state.get("expected_rows", -1)) != n_rows
            or state.get("analysis_sample_policy") != args.analysis_sample
            or state.get("eligibility_policy") != args.eligibility_policy
            or state.get("matrix_id") != matrix_id
            or state.get("matrix_builder_sha256")
                != matrix_builder_sha256
            or state.get("subjectivity_review_sha256")
                != subjectivity_review_sha256
            or state.get("classification_manifest_sha256")
                != classification_manifest_sha256
        ):
            raise RuntimeError(
                "Existing incomplete matrix is incompatible with current build"
            )
        encoder_payload = json.loads(encoders_path.read_text(encoding="utf-8"))
        for name, mapping in encoder_payload.items():
            encoders[name].mapping = {
                str(key): int(value) for key, value in mapping.items()
            }
        offset = int(state["offset"])
        completed = list(state["completed_partitions"])
        mode = "r+"
    else:
        offset = 0
        completed = []
        mode = "w+"

    matrix = np.memmap(
        matrix_path, dtype=np.float64, mode=mode, shape=(n_rows, n_columns)
    )
    outcomes = np.memmap(
        outcomes_path,
        dtype=np.float64,
        mode=mode,
        shape=(n_rows, len(model_outcomes)),
    )
    fe_codes = np.memmap(
        fe_path, dtype=np.uint64, mode=mode, shape=(n_rows, 3)
    )
    cluster_codes = np.memmap(
        cluster_path, dtype=np.uint64, mode=mode, shape=(n_rows, 3)
    )
    core_columns = [
        "visit_year",
        "patient_black_flag",
        "physician_black_imputed_flag",
        "physician_race_proxy_prob_black",
        "physician_race_proxy_prob_white",
        "physician_race_population_prob_black",
        "physician_race_population_prob_white",
        "physician_race_imputation_confidence",
        "race_primary_eligible_t70_flag",
        "race_primary_eligible_t80_flag",
        "race_primary_eligible_t90_flag",
        "sex_gender_primary_eligible_flag",
        "physician_gender_category",
        "physician_gender_source",
        "patient_sex_category",
        "patient_race_category",
        "patient_ethnicity_category",
        "diagnosis_code_system",
        "presentation_code_group",
        "disposition_group",
        "age_years",
        "payer_group",
        "patient_zip_rurality_3level",
        "weekend_flag",
        "off_hours_flag",
        "arrival_time_band",
        "elixhauser_condition_count",
        "em_acuity_proxy_level",
        "em_critical_care_flag",
        "attending_ed_specialist_flag",
        "attending_years_since_medical_school",
        "attending_quarter_volume_all_ed",
        "medical_cpi_factor_to_2024",
        "attending_selected_npi",
        "facility_year_quarter_id",
        "principal_clinical_category",
        "facility_ahca_id",
        "facility_rurality_3level",
        "cms_hospital_ownership",
        *CORE_MODEL_OUTCOMES,
    ]
    select_core = ", ".join(f"c.{name}" for name in core_columns)
    select_risk = ", ".join(f"r.{name}" for name in elix_flags)
    select_charge = ", ".join(
        f"ch.{name}" for name in CHARGE_COMPONENT_OUTCOMES
    )
    select_discretion = ", ".join(
        f"d.{name}" for name in DISCRETION_OUTCOMES
    )
    select_provider = (
        "coalesce(p.gender_conflict_flag_v2, false) "
        "AS physician_gender_source_conflict_flag"
    )

    for item in row_counts:
        year = item["visit_year"]
        quarter = item["visit_quarter"]
        expected_rows = item["rows"]
        label = f"{year}Q{quarter}"
        if label in completed:
            continue
        if expected_rows == 0:
            completed.append(label)
            continue
        part = data_root / f"visit_year={year}" / f"visit_quarter={quarter}"
        core = part / "concordance_visit_core.parquet"
        risk = part / "concordance_elixhauser_flags.parquet"
        charge = part / "concordance_charge_components.parquet"
        discretion = (
            data_root.parent
            / "discretion_outcomes"
            / f"visit_year={year}"
            / f"visit_quarter={quarter}"
            / "visit_discretion_outcomes.parquet"
        )
        query = f"""
            SELECT
                {select_core}, {select_risk}, {select_charge},
                {select_discretion}, {select_provider}
            FROM read_parquet('{qpath(core)}', hive_partitioning=false) c
            INNER JOIN read_parquet(
                '{qpath(risk)}', hive_partitioning=false
            ) r USING (visit_key, visit_year, visit_quarter)
            INNER JOIN read_parquet(
                '{qpath(charge)}', hive_partitioning=false
            ) ch USING (visit_key, visit_year, visit_quarter)
            INNER JOIN read_parquet(
                '{qpath(discretion)}', hive_partitioning=false
            ) d USING (visit_key, visit_year, visit_quarter)
            INNER JOIN read_parquet(
                '{qpath(provider_master_path)}',
                hive_partitioning=false
            ) p
              ON c.attending_selected_npi = p.npi
            WHERE {eligibility_aliased}
              AND {" AND ".join(f"c.{name} IS NOT NULL" for name in filter_outcomes)}
        """
        reader = con.execute(query).fetch_record_batch(rows_per_batch=args.batch_size)
        partition_written = 0
        for batch in reader:
            frame = batch.to_pandas()
            if args.eligibility_policy == "race_only_direct_t50":
                frame["patient_black_flag"] = (
                    frame["patient_race_category"]
                    .eq("Black or African American")
                    .astype("int8")
                )
            n = len(frame)
            stop = offset + n
            x = design_batch(
                frame,
                args.cohort,
                elix_flags,
                age_median,
                experience_median,
                design_spec,
                subjectivity_mapping,
            )
            frame["log1p_los_hours_primary"] = np.log1p(
                frame["los_hours_primary_0_168"].to_numpy(dtype=np.float64)
            )
            frame["log1p_total_charge_reported_real_2024"] = np.log1p(
                frame["total_charge_reported_real_2024"].to_numpy(
                    dtype=np.float64
                )
            )
            frame["any_positive_total_charge_reported"] = (
                frame["total_charge_reported_real_2024"].to_numpy(
                    dtype=np.float64
                )
                > 0
            ).astype(np.float64)
            frame["los_hours_winsor_yq_p995"] = np.minimum(
                frame["los_hours_primary_0_168"].to_numpy(dtype=np.float64),
                float(item["los_p995"]),
            )
            frame["total_charge_real_winsor_yq_p995"] = np.minimum(
                frame["total_charge_reported_real_2024"].to_numpy(
                    dtype=np.float64
                ),
                float(item["charge_p995"]),
            )
            frame["total_charge_real_winsor_yq_p999"] = np.minimum(
                frame["total_charge_reported_real_2024"].to_numpy(
                    dtype=np.float64
                ),
                float(item["charge_p999"]),
            )
            frame["total_charge_reported_real_2024_medical_cpi"] = (
                frame["total_charge_reported"].to_numpy(dtype=np.float64)
                * frame["medical_cpi_factor_to_2024"].to_numpy(
                    dtype=np.float64
                )
            )
            frame["higher_minus_lower_discretion_procedure_count"] = (
                frame["higher_discretion_procedure_count"].to_numpy(
                    dtype=np.float64
                )
                - frame["lower_discretion_procedure_count"].to_numpy(
                    dtype=np.float64
                )
            )
            frame["any_higher_minus_any_lower_discretion_candidate"] = (
                frame["any_higher_discretion_candidate_flag"].to_numpy(
                    dtype=np.float64
                )
                - frame["any_lower_discretion_candidate_flag"].to_numpy(
                    dtype=np.float64
                )
            )
            if frame["disposition_group"].isna().any():
                raise RuntimeError(
                    f"Missing disposition_group encountered in {label}; "
                    "do not silently recode missing disposition to zero"
                )
            frame["home_health_flag"] = (
                frame["disposition_group"]
                .eq("Home health")
                .to_numpy(dtype=np.float64)
            )
            y = frame[model_outcomes].to_numpy(dtype=np.float64)
            if not np.isfinite(y).all():
                raise RuntimeError(f"Non-finite outcome in {label}")
            matrix[offset:stop, :] = x
            outcomes[offset:stop, :] = y

            physician = frame["attending_selected_npi"]
            facility_yq = frame["facility_year_quarter_id"]
            clinical = frame["principal_clinical_category"]
            facility = frame["facility_ahca_id"]
            physician_facility = (
                normalize_string(physician)
                + "|"
                + normalize_string(facility)
            )
            physician_code = encoders["physician"].encode(physician)
            facility_code = encoders["facility"].encode(facility)
            fe_codes[offset:stop, 0] = physician_code
            fe_codes[offset:stop, 1] = encoders["facility_yq"].encode(facility_yq)
            fe_codes[offset:stop, 2] = encoders["clinical"].encode(clinical)
            cluster_codes[offset:stop, 0] = physician_code
            cluster_codes[offset:stop, 1] = facility_code
            cluster_codes[offset:stop, 2] = encoders[
                "physician_facility"
            ].encode(physician_facility)
            offset = stop
            partition_written += n
        if partition_written != expected_rows:
            raise RuntimeError(
                f"{label}: wrote {partition_written}, expected {expected_rows}"
            )
        completed.append(label)
        for mmap in (matrix, outcomes, fe_codes, cluster_codes):
            mmap.flush()
        atomic_json(
            state_path,
            {
                "updated_utc": now_utc(),
                "cohort": args.cohort,
                "matrix_id": matrix_id,
                "analysis_sample_policy": args.analysis_sample,
                "eligibility_policy": args.eligibility_policy,
                "matrix_builder_sha256": matrix_builder_sha256,
                "subjectivity_review_sha256": subjectivity_review_sha256,
                "classification_manifest_sha256": (
                    classification_manifest_sha256
                ),
                "offset": offset,
                "expected_rows": n_rows,
                "completed_partitions": completed,
                "encoder_sizes": {
                    name: len(encoder.mapping)
                    for name, encoder in encoders.items()
                },
            },
        )
        atomic_json(
            encoders_path,
            {
                name: encoder.mapping for name, encoder in encoders.items()
            },
        )

    if offset != n_rows:
        raise RuntimeError(f"Wrote {offset} rows, expected {n_rows}")
    for mmap in (matrix, outcomes, fe_codes, cluster_codes):
        mmap.flush()

    files = []
    for path in (matrix_path, outcomes_path, fe_path, cluster_path):
        files.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path) if args.hash_large_files else None,
            }
        )
    manifest = {
        "created_utc": now_utc(),
        "cohort": args.cohort,
        "matrix_id": matrix_id,
        "analysis_sample_policy": args.analysis_sample,
        "eligibility_policy": args.eligibility_policy,
        "design_scope": design_scope,
        "provider_measurement_version": (
            "provider_master_v2_full_name_race_v1"
        ),
        "provider_gate_path": str(provider_gate_path),
        "provider_gate_sha256": provider_gate_sha256,
        "cohort_gate_path": str(cohort_gate_path),
        "cohort_gate_sha256": cohort_gate_sha256,
        "gender_checkpoint_path": str(gender_checkpoint_path),
        "gender_checkpoint_sha256": gender_checkpoint_sha256,
        "primary_physician_gender_sources": list(
            RECORDED_PHYSICIAN_GENDER_SOURCES
        ),
        "physician_gender_source_conflict_sensitivity": (
            "exact M2 subset excluding recorded NPPES-CMS disagreements"
        ),
        "matrix_builder_sha256": matrix_builder_sha256,
        "subjectivity_review_path": str(subjectivity_review_path),
        "subjectivity_review_sha256": subjectivity_review_sha256,
        "subjectivity_review_version": subjectivity_review_version,
        "subjectivity_mapping_keys": len(subjectivity_mapping),
        "classification_manifest_path": str(classification_manifest_path),
        "classification_manifest_sha256": classification_manifest_sha256,
        "discretion_sidecar_manifest_digest_sha256": (
            classification_manifest["sidecar_manifest_digest_sha256"]
        ),
        "row_filter": f"{eligibility} AND {outcome_filter}",
        "common_primary_outcome_sample": (
            args.analysis_sample == "common_primary"
        ),
        "outcome_specific_sample": (
            args.analysis_sample in {"los_outcome", "charge_outcome"}
        ),
        "outcome_specific_confirmatory_sample": (
            args.eligibility_policy == "primary"
            and args.analysis_sample in {"los_outcome", "charge_outcome"}
        ),
        "confirmatory_designated": (
            args.eligibility_policy == "primary"
            and args.analysis_sample in {"los_outcome", "charge_outcome"}
        ),
        "n_rows": n_rows,
        "n_design_columns": n_columns,
        "design_spec": design_spec,
        "primary_outcomes": primary_outcomes,
        "outcomes": model_outcomes,
        "fe_code_order": [
            "attending_physician",
            "facility_by_year_quarter",
            "principal_clinical_category",
        ],
        "cluster_code_order": [
            "attending_physician",
            "facility",
            "attending_physician_by_facility_intersection",
        ],
        "age_median_imputation": age_median,
        "age_spline_knots": [18, 45, 65, 80],
        "experience_median_imputation": experience_median,
        "experience_spline_knots": [10, 20, 30],
        "categorical_reference_levels": {
            "payer": PAYER_LEVELS[0],
            "patient_rurality": RURALITY_LEVELS[0],
            "arrival_time_band": ARRIVAL_LEVELS[0],
            "patient_race_ethnicity": PATIENT_RACE_ETHNICITY_LEVELS[0],
            "patient_ethnicity": PATIENT_ETHNICITY_LEVELS[0],
            "patient_sex": "Male",
        },
        "partitions": row_counts,
        "encoder_sizes": {
            name: len(encoder.mapping) for name, encoder in encoders.items()
        },
        "files": files,
        "matrix_build_passed": True,
    }
    atomic_json(output / "matrix_manifest.json", manifest)
    atomic_json(success_path, manifest)
    con.close()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
