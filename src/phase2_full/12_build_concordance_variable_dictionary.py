#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/12_build_concordance_variable_dictionary.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Create the auditable variable dictionary for Phase 2 derived data."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


OVERRIDES = {
    "los_hours_clock_raw": {
        "source_fields": "length_of_stay_days; arrival_hour; ed_discharge_hour_raw",
        "definition": (
            "24 * length_of_stay_days + valid ED discharge hour - valid "
            "arrival hour."
        ),
        "missingness_rule": (
            "Missing when arrival/discharge hour is outside 0-23 or source "
            "inputs are missing; discharge code 99 is invalid."
        ),
        "historical_compatibility": (
            "Not available in 2005-2008 because an ED discharge hour is absent."
        ),
        "limitation": "Clock reconstruction is not a timestamp and can be inconsistent.",
    },
    "los_hours_primary_0_168": {
        "source_fields": "los_hours_clock_raw",
        "definition": (
            "Clock-based LOS retained only when nonnegative and no more than "
            "168 hours."
        ),
        "missingness_rule": (
            "Negative, >168-hour, invalid-hour, and source-missing values are "
            "excluded; they are not recoded to zero."
        ),
        "historical_compatibility": "Primary only for 2010-2024.",
        "limitation": "Administrative timing proxy; not clinical throughput detail.",
    },
    "total_charge_reported_real_2024": {
        "source_fields": "total_charge_reported; BLS CPI-U CUUR0000SA0",
        "definition": (
            "Nonnegative facility-reported total charge multiplied by the "
            "quarter CPI-U factor to 2024 dollars."
        ),
        "missingness_rule": "Negative and missing charges remain missing.",
        "historical_compatibility": (
            "Comparable as inflation-standardized reported charges subject "
            "to source-schema and charging-practice changes."
        ),
        "limitation": "Not cost, payment, reimbursement, or actual spending.",
    },
    "log1p_los_hours_primary": {
        "source_fields": "los_hours_primary_0_168",
        "definition": "Natural log of 1 plus the primary 0-168-hour LOS measure.",
        "coding_rule": "log1p(los_hours_primary_0_168).",
        "missingness_rule": "Defined only in a matrix whose source LOS is observed.",
        "historical_compatibility": "Not constructed for 2005-2008.",
    },
    "log1p_total_charge_reported_real_2024": {
        "source_fields": "total_charge_reported_real_2024",
        "definition": (
            "Natural log of 1 plus nonnegative facility-reported total charges "
            "inflated to 2024 dollars."
        ),
        "coding_rule": "log1p(total_charge_reported_real_2024).",
        "limitation": "Facility-reported charge transformation, not cost or payment.",
    },
    "any_positive_total_charge_reported": {
        "source_fields": "total_charge_reported_real_2024",
        "definition": "1 when real reported total charges are strictly positive; 0 at zero.",
        "coding_rule": "I(total_charge_reported_real_2024 > 0).",
    },
    "los_hours_winsor_yq_p995": {
        "source_fields": "los_hours_primary_0_168; visit_year; visit_quarter",
        "definition": (
            "Primary LOS capped at its eligible year-quarter 99.5th percentile."
        ),
        "coding_rule": "min(LOS, eligible year-quarter p99.5).",
    },
    "total_charge_real_winsor_yq_p995": {
        "source_fields": "total_charge_reported_real_2024; visit_year; visit_quarter",
        "definition": (
            "Real reported total charges capped at the eligible year-quarter "
            "99.5th percentile."
        ),
        "coding_rule": "min(real reported charge, eligible year-quarter p99.5).",
        "limitation": "Facility-reported charges, not cost or payment.",
    },
    "total_charge_real_winsor_yq_p999": {
        "source_fields": "total_charge_reported_real_2024; visit_year; visit_quarter",
        "definition": (
            "Real reported total charges capped at the eligible year-quarter "
            "99.9th percentile."
        ),
        "coding_rule": "min(real reported charge, eligible year-quarter p99.9).",
        "limitation": "Facility-reported charges, not cost or payment.",
    },
    "total_charge_reported_real_2024_medical_cpi": {
        "source_fields": "total_charge_reported; BLS Medical Care CPI CUUR0000SAM",
        "definition": (
            "Nonnegative facility-reported total charge multiplied by the "
            "quarter Medical Care CPI factor to 2024 dollars."
        ),
        "coding_rule": "total_charge_reported * medical_cpi_factor_to_2024.",
        "limitation": "Alternative inflation sensitivity; not cost or payment.",
    },
    "higher_discretion_procedure_count": {
        "source_fields": "visit_procedure; treatment_discretion_review.csv",
        "definition": (
            "Number of coded procedures mapped to a provisional "
            "higher-discretion candidate group."
        ),
        "limitation": "Evidence-informed and provisional pending clinician review.",
    },
    "lower_discretion_procedure_count": {
        "source_fields": "visit_procedure; treatment_discretion_review.csv",
        "definition": (
            "Number of coded procedures mapped to a provisional "
            "lower-discretion candidate group."
        ),
        "limitation": "Evidence-informed and provisional pending clinician review.",
    },
    "ambiguous_discretion_procedure_count": {
        "source_fields": "visit_procedure; treatment_discretion_review.csv",
        "definition": (
            "Number of coded procedures that remain ambiguous, unclassified, "
            "or unmatched in the provisional discretion crosswalk."
        ),
        "limitation": "Ambiguity is preserved rather than forced into a binary group.",
    },
    "any_higher_discretion_candidate_flag": {
        "source_fields": "higher_discretion_procedure_count",
        "definition": "1 when the higher-discretion candidate count is greater than zero.",
    },
    "any_lower_discretion_candidate_flag": {
        "source_fields": "lower_discretion_procedure_count",
        "definition": "1 when the lower-discretion candidate count is greater than zero.",
    },
    "higher_minus_lower_discretion_procedure_count": {
        "source_fields": (
            "higher_discretion_procedure_count; "
            "lower_discretion_procedure_count"
        ),
        "definition": (
            "Higher-discretion candidate procedure count minus "
            "lower-discretion candidate procedure count."
        ),
        "limitation": "Exploratory contrast based on a provisional crosswalk.",
    },
    "any_higher_minus_any_lower_discretion_candidate": {
        "source_fields": (
            "any_higher_discretion_candidate_flag; "
            "any_lower_discretion_candidate_flag"
        ),
        "definition": (
            "Any higher-discretion candidate indicator minus any "
            "lower-discretion candidate indicator."
        ),
        "limitation": "Exploratory contrast based on a provisional crosswalk.",
    },
    "home_health_flag": {
        "source_fields": "disposition_group",
        "definition": "1 when the standardized ED disposition is Home health; 0 otherwise.",
        "coding_rule": "I(disposition_group == 'Home health').",
        "limitation": (
            "ED disposition only; it is not a confirmed same-facility inpatient admission."
        ),
    },
    "presentation_subjectivity_classified": {
        "source_fields": (
            "diagnosis_code_system; principal_clinical_category; "
            "presentation_subjectivity_review.csv"
        ),
        "definition": (
            "1 when the versioned category-level review labels the presentation "
            "higher- or lower-uncertainty; 0 when ambiguous/mixed."
        ),
        "limitation": "Provisional and evidence-informed pending clinician review.",
    },
    "classified_subjectivity_high": {
        "source_fields": "presentation_subjectivity_review.csv",
        "definition": (
            "1 for a nonambiguous higher-uncertainty proxy category and 0 for "
            "a lower-uncertainty proxy category; ambiguous rows are excluded "
            "from the exact sensitivity."
        ),
        "limitation": "Not a validated measure of clinical subjectivity.",
    },
    "race_pair_category": {
        "source_fields": (
            "patient_race_category; patient_ethnicity_category; "
            "physician_race_proxy_primary_label"
        ),
        "definition": (
            "Four-level non-Hispanic Black/White physician-proxy–patient pair; "
            "physician category is written first."
        ),
        "missingness_rule": (
            "Undefined outside non-Hispanic Black/White patient and "
            "Black/White physician-proxy combinations."
        ),
        "historical_compatibility": (
            "Primary 2010-2024 only; historical combined semantics analyzed separately."
        ),
        "limitation": (
            "Physician race/ethnicity is a Bayesian full-name analytical "
            "probability proxy without residential geography, not BISG or "
            "self-reported identity."
        ),
    },
    "black_black": {
        "source_fields": "race_pair_category",
        "definition": (
            "1 for full-name-proxy Black physician and recorded "
            "non-Hispanic Black patient; physician first."
        ),
    },
    "black_white": {
        "source_fields": "race_pair_category",
        "definition": (
            "1 for full-name-proxy Black physician and recorded "
            "non-Hispanic White patient; physician first."
        ),
    },
    "white_black": {
        "source_fields": "race_pair_category",
        "definition": (
            "1 for full-name-proxy White physician and recorded "
            "non-Hispanic Black patient; physician first."
        ),
    },
    "white_white": {
        "source_fields": "race_pair_category",
        "definition": (
            "1 for full-name-proxy White physician and recorded "
            "non-Hispanic White patient; physician first."
        ),
    },
    "race_primary_eligible_t50_flag": {
        "source_fields": (
            "race_pair_defined_nh_flag; physician_linkage_method; "
            "physician_race_imputation_confidence"
        ),
        "definition": (
            "Direct validated attending NPI, matched MD/DO, defined "
            "non-Hispanic Black/White pair, matched first and last name, "
            "full-name-proxy maximum posterior probability >=0.50."
        ),
        "historical_compatibility": "2010-2024 primary period only.",
        "limitation": (
            "Selection depends on direct physician linkage, individual MD/DO "
            "classification, and full-name probability availability."
        ),
    },
    "sex_gender_pair_category": {
        "source_fields": "patient_sex_category; physician_gender_category",
        "definition": (
            "Four-level recorded patient sex–physician gender pair; physician "
            "category is written first."
        ),
        "missingness_rule": (
            "Undefined when either source is not Female or Male; unknown and "
            "ambiguous categories remain visible in QA tables."
        ),
        "limitation": "Neither variable is interpreted as gender identity.",
    },
    "sex_gender_primary_eligible_flag": {
        "source_fields": (
            "sex_gender_pair_defined_flag; physician_linkage_method; "
            "physician_md_do_flag"
        ),
        "definition": (
            "Binary hierarchy-eligible flag written by the provider-v2 cohort: "
            "direct validated attending NPI, individual MD/DO, and defined "
            "Female/Male patient and physician categories."
        ),
        "coding_rule": (
            "The model-matrix primary filter additionally requires "
            "physician_gender_source to be recorded NPPES or CMS. The cohort "
            "flag alone is not the final recorded-source primary rule."
        ),
        "limitation": (
            "SSA name-imputed physician gender can satisfy this intermediate "
            "flag but is excluded from primary model matrices."
        ),
    },
    "physician_gender_source": {
        "source_fields": "provider_master_v2.gender_source_v2",
        "definition": (
            "Provenance of the binary administrative physician-gender "
            "category. Recorded NPPES/CMS sources define the primary cohort; "
            "SSA first-name imputation is expanded-sensitivity only."
        ),
        "limitation": (
            "Administrative binary categories are not self-identified gender "
            "identity and are mostly current snapshots."
        ),
    },
    "physician_gender_source_no_conflict": {
        "source_fields": "provider_master_v2.gender_conflict_flag",
        "definition": (
            "Model-matrix selection indicator equal to 1 when recorded NPPES "
            "and CMS binary physician-gender categories do not disagree."
        ),
        "coding_rule": (
            "Used for exact M2 subset re-demeaning; missing conflict flags for "
            "new current-NPPES records are treated as no observed conflict."
        ),
        "limitation": (
            "Absence of recorded disagreement does not validate the category "
            "as self-identified gender."
        ),
    },
    "female_female": {
        "source_fields": "sex_gender_pair_category",
        "definition": "1 for Female physician gender and Female recorded patient sex.",
    },
    "female_male": {
        "source_fields": "sex_gender_pair_category",
        "definition": "1 for Female physician gender and Male recorded patient sex.",
    },
    "male_female": {
        "source_fields": "sex_gender_pair_category",
        "definition": "1 for Male physician gender and Female recorded patient sex.",
    },
    "male_male": {
        "source_fields": "sex_gender_pair_category",
        "definition": "1 for Male physician gender and Male recorded patient sex.",
    },
    "presentation_code_group": {
        "source_fields": (
            "principal_diagnosis_code_norm; diagnosis_code_system"
        ),
        "definition": (
            "Symptom/sign coded for ICD-9 780-799 or ICD-10-CM R00-R99; "
            "otherwise disease/condition/injury coded, or ambiguous/missing."
        ),
        "limitation": (
            "Proxy for coded diagnostic uncertainty, not a validated measure "
            "of symptom subjectivity or objective truth."
        ),
    },
    "physician_linkage_method": {
        "source_fields": "attending_selection_method",
        "definition": (
            "Direct validated NPI or unique Florida license-to-NPI crosswalk."
        ),
        "limitation": "License-derived links are sensitivity-only after 2010.",
    },
    "physician_race_imputation_confidence": {
        "source_fields": "race_proxy_primary_max_probability",
        "definition": (
            "Maximum of five Bayesian posterior race/ethnicity probabilities "
            "from matched surname, first name, and available middle name using "
            "the Florida active-physician prior."
        ),
        "limitation": (
            "Name-only probability without residential geography; not BISG "
            "and not self-reported identity."
        ),
    },
    "ami_icd9_principal_strict_flag": {
        "source_fields": "principal_diagnosis_code_norm",
        "definition": "Principal ICD-9-CM acute myocardial infarction code 410.X1.",
        "historical_compatibility": "ICD-9-CM era only.",
    },
    "ami_icd10_principal_primary_flag": {
        "source_fields": "principal_diagnosis_code_norm",
        "definition": (
            "Principal ICD-10-CM acute myocardial infarction I21.0-I21.4 or I21.9."
        ),
        "historical_compatibility": "ICD-10-CM era only.",
    },
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import locked definitions from {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses and other annotation-aware code resolve the defining module
    # through sys.modules while the class body is executed.  Register the
    # dynamic module exactly as the standard import machinery does.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def design_source_fields(name: str, group: str) -> str:
    direct = {
        "physician_black_proxy": "physician_black_imputed_flag",
        "patient_black": "patient_black_flag",
        "race_interaction": "physician_black_proxy; patient_black",
        "physician_black_probability": (
            "physician_race_proxy_prob_black; physician_race_proxy_prob_white"
        ),
        "race_probability_interaction": (
            "physician_black_probability; patient_black"
        ),
        "physician_black_probability_population_prior": (
            "physician_race_population_prob_black; "
            "physician_race_population_prob_white"
        ),
        "race_probability_interaction_population_prior": (
            "physician_black_probability_population_prior; patient_black"
        ),
        "physician_female": "physician_gender_category",
        "patient_female": "patient_sex_category",
        "sex_gender_interaction": "physician_female; patient_female",
        "visit_year_numeric": "visit_year",
        "los_le72": "los_hours_primary_0_168",
        "positive_reported_charge": "total_charge_reported_real_2024",
        "complete_case_covariates": "all documented M1/M2 covariates",
        "em_acuity_available": "em_acuity_proxy_level",
        "em_acuity_value": "em_acuity_proxy_level",
        "em_critical_care_available": "em_critical_care_flag",
        "em_critical_care_value": "em_critical_care_flag",
        "presentation_subjectivity_classified": (
            "presentation_subjectivity_review.csv; principal_clinical_category"
        ),
        "classified_subjectivity_high": (
            "presentation_subjectivity_review.csv; principal_clinical_category"
        ),
    }
    if name in direct:
        return direct[name]
    if "_x_physician" in name:
        return (
            name.replace("_x_physician", "")
            + "; cohort-specific physician exposure"
        )
    if "_x_patient" in name:
        return (
            name.replace("_x_patient", "")
            + "; cohort-specific patient exposure"
        )
    if "_x_interaction" in name:
        return (
            name.replace("_x_interaction", "")
            + "; cohort-specific physician-by-patient interaction"
        )
    if name.startswith("payer__"):
        return "payer_group"
    if name.startswith("patient_rurality__"):
        return "patient_zip_rurality_3level"
    if name.startswith("arrival_band__"):
        return "arrival_time_band"
    if name.startswith("patient_ethnicity__"):
        return "patient_ethnicity_category"
    if name.startswith("patient_race_ethnicity__"):
        return "patient_race_category; patient_ethnicity_category"
    if name.startswith("elix_"):
        return name
    if name.startswith("intersection_"):
        return (
            "physician_black_proxy; patient_black; physician_female; "
            "patient_female"
        )
    return name


def design_definition(name: str, group: str) -> str:
    direct = {
        "intercept": "Constant equal to 1.",
        "physician_black_proxy": (
            "1 for a Black physician full-name proxy and 0 for a White proxy "
            "in the eligible race cohort."
        ),
        "patient_black": (
            "1 for a recorded non-Hispanic Black patient and 0 for a recorded "
            "non-Hispanic White patient in the primary race cohort."
        ),
        "race_interaction": "physician_black_proxy multiplied by patient_black.",
        "physician_black_probability": (
            "Black posterior divided by Black plus White posterior under the "
            "Florida active-physician prior."
        ),
        "race_probability_interaction": (
            "physician_black_probability multiplied by patient_black."
        ),
        "physician_black_probability_population_prior": (
            "Black posterior divided by Black plus White posterior under the "
            "official wru national-population prior sensitivity."
        ),
        "race_probability_interaction_population_prior": (
            "population-prior physician Black probability multiplied by "
            "patient_black."
        ),
        "physician_female": (
            "1 for recorded Female physician gender and 0 for Male."
        ),
        "patient_female": (
            "1 for recorded Female patient sex and 0 for Male."
        ),
        "sex_gender_interaction": (
            "physician_female multiplied by patient_female."
        ),
        "visit_year_numeric": "Calendar year as a numeric selection field.",
        "los_le72": "1 when primary LOS is no more than 72 hours.",
        "positive_reported_charge": "1 when real reported total charge is positive.",
        "complete_case_covariates": (
            "1 when all covariates designated for the complete-case "
            "sensitivity are observed and nonunknown."
        ),
        "em_acuity_available": "1 when the billing-derived E/M acuity proxy is available.",
        "em_acuity_value": "Numeric billing-derived E/M acuity proxy value.",
        "em_critical_care_available": (
            "1 when the billing-derived critical-care indicator is available."
        ),
        "em_critical_care_value": "Billing-derived critical-care indicator value.",
        "presentation_subjectivity_classified": OVERRIDES[
            "presentation_subjectivity_classified"
        ]["definition"],
        "classified_subjectivity_high": OVERRIDES[
            "classified_subjectivity_high"
        ]["definition"],
    }
    if name in direct:
        return direct[name]
    if "_x_physician" in name:
        modifier = name.replace("_x_physician", "")
        return f"{modifier} multiplied by the cohort-specific physician exposure."
    if "_x_patient" in name:
        modifier = name.replace("_x_patient", "")
        return f"{modifier} multiplied by the cohort-specific patient exposure."
    if "_x_interaction" in name:
        modifier = name.replace("_x_interaction", "")
        return (
            f"{modifier} multiplied by the cohort-specific physician-by-patient "
            "interaction."
        )
    if name.startswith("intersection_"):
        return (
            "Explicit product term among the race and recorded-sex/physician-"
            "gender exposure indicators, with physician components written first."
        )
    if "__" in name:
        source, level = name.split("__", 1)
        return (
            f"Indicator for {source.replace('_', ' ')} category {level}; "
            "the reference category is stored in the matrix manifest."
        )
    if name.startswith("age_gt"):
        knot = name.replace("age_gt", "")
        return f"Positive-part age spline max(age - {knot}, 0)."
    if name == "age":
        return "Age in years after frozen median imputation for invalid/missing values."
    if name == "age2_scaled":
        return "Squared imputed age divided by 100."
    if name == "age_missing":
        return "1 when source age is invalid or missing and median imputation is used."
    if name.startswith("experience_gt"):
        knot = name.replace("experience_gt", "")
        return (
            f"Positive-part years-since-medical-school spline "
            f"max(experience - {knot}, 0)."
        )
    if name == "experience":
        return (
            "Years since medical-school graduation after frozen median "
            "imputation for invalid/missing values."
        )
    if name.startswith("elix_"):
        return "Binary AHRQ Elixhauser comorbidity indicator."
    if group.startswith("heterogeneity_"):
        return "Prespecified binary heterogeneity modifier."
    return (
        "Analysis design field defined deterministically in the locked matrix "
        "builder; the source field and design group are recorded here."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    release = args.release.resolve()
    sample = (
        phase2
        / "analysis_data"
        / "concordance_visit_data_provider_v2"
        / "visit_year=2010"
        / "visit_quarter=1"
    )
    source_dictionary = pd.read_csv(
        release / "documentation" / "fact_field_dictionary.csv"
    ).set_index("field_name")
    tables = [
        ("concordance_visit_core", sample / "concordance_visit_core.parquet"),
        (
            "concordance_charge_components",
            sample / "concordance_charge_components.parquet",
        ),
        (
            "concordance_elixhauser_flags",
            sample / "concordance_elixhauser_flags.parquet",
        ),
        (
            "visit_discretion_outcomes",
            phase2
            / "analysis_data"
            / "discretion_outcomes"
            / "visit_year=2010"
            / "visit_quarter=1"
            / "visit_discretion_outcomes.parquet",
        ),
    ]
    rows = []
    for table, path in tables:
        schema = pq.read_schema(path)
        for position, field in enumerate(schema, start=1):
            original = (
                source_dictionary.loc[field.name].to_dict()
                if field.name in source_dictionary.index
                else {}
            )
            override = OVERRIDES.get(field.name, {})
            rows.append(
                {
                    "table": table,
                    "ordinal_position": position,
                    "variable": field.name,
                    "parquet_type": str(field.type),
                    "grain": "one row per ED visit",
                    "key_role": (
                        "primary visit key component"
                        if field.name
                        in ("visit_key", "visit_year", "visit_quarter")
                        else ""
                    ),
                    "source_fields": override.get(
                        "source_fields",
                        field.name if original else "Phase 2 derived",
                    ),
                    "definition": override.get(
                        "definition",
                        original.get(
                            "definition",
                            "See locked cohort builder and source release dictionary.",
                        ),
                    ),
                    "coding_rule": override.get(
                        "coding_rule",
                        "Preserve source missingness unless an explicit derived rule applies.",
                    ),
                    "missingness_rule": override.get(
                        "missingness_rule",
                        "Missing remains missing; no implicit zero fill.",
                    ),
                    "historical_compatibility": override.get(
                        "historical_compatibility",
                        (
                            "Primary derived cohort covers 2010-2024; consult "
                            "source coverage and separate historical sensitivity."
                        ),
                    ),
                    "limitation": override.get(
                        "limitation",
                        original.get("qa_note", ""),
                    ),
                    "source_release_domain": original.get("domain", ""),
                    "source_release_source_class": original.get(
                        "source_class", ""
                    ),
                    "analysis_cohort": "all",
                    "analysis_role": (
                        "visit-level source or Phase 2 derived analytical field"
                    ),
                    "design_group": "",
                }
            )
    matrix_definitions = load_module(
        "phase2_matrix_dictionary_definitions",
        phase2 / "scripts" / "07_prepare_primary_model_matrix.py",
    )
    risk_schema = pq.read_schema(sample / "concordance_elixhauser_flags.parquet")
    elix_flags = sorted(
        field.name
        for field in risk_schema
        if field.name.startswith("elix_") and field.name.endswith("_flag")
    )
    for cohort in ("race", "sex_gender"):
        for position, item in enumerate(
            matrix_definitions.build_design_spec(cohort, elix_flags), start=1
        ):
            name = item["name"]
            override = OVERRIDES.get(name, {})
            rows.append(
                {
                    "table": f"model_design_{cohort}",
                    "ordinal_position": position,
                    "variable": name,
                    "parquet_type": "float64 matrix column",
                    "grain": "one row per eligible model encounter",
                    "key_role": "",
                    "source_fields": override.get(
                        "source_fields",
                        design_source_fields(name, item["group"]),
                    ),
                    "definition": override.get(
                        "definition",
                        design_definition(name, item["group"]),
                    ),
                    "coding_rule": override.get(
                        "coding_rule",
                        (
                            "Computed exactly by design_batch() in "
                            "07_prepare_primary_model_matrix.py."
                        ),
                    ),
                    "missingness_rule": override.get(
                        "missingness_rule",
                        (
                            "Frozen missing-category indicators or documented "
                            "median imputation are used; exposure eligibility "
                            "rules are applied before matrix construction."
                        ),
                    ),
                    "historical_compatibility": override.get(
                        "historical_compatibility",
                        "Primary 2010-2024 model design only.",
                    ),
                    "limitation": override.get(
                        "limitation",
                        (
                            "Interpret with the cohort, reference levels, and "
                            "fixed effects stored in the matrix manifest."
                        ),
                    ),
                    "source_release_domain": "",
                    "source_release_source_class": "",
                    "analysis_cohort": cohort,
                    "analysis_role": "model design",
                    "design_group": item["group"],
                }
            )
    existing_table_variables = {
        (row["table"], row["variable"]) for row in rows
    }
    for position, name in enumerate(
        matrix_definitions.MODEL_OUTCOMES, start=1
    ):
        if ("model_outcome_catalog", name) in existing_table_variables:
            continue
        override = OVERRIDES.get(name, {})
        rows.append(
            {
                "table": "model_outcome_catalog",
                "ordinal_position": position,
                "variable": name,
                "parquet_type": "float64 matrix outcome",
                "grain": "one row per eligible model encounter",
                "key_role": "",
                "source_fields": override.get("source_fields", name),
                "definition": override.get(
                    "definition",
                    (
                        "Visit-level analysis outcome preserved or derived "
                        "under the locked model-matrix rules."
                    ),
                ),
                "coding_rule": override.get(
                    "coding_rule",
                    "See 07_prepare_primary_model_matrix.py and the source field dictionary.",
                ),
                "missingness_rule": override.get(
                    "missingness_rule",
                    (
                        "Outcome-specific eligibility is documented in the "
                        "matrix manifest; missing values are never silently zero-filled."
                    ),
                ),
                "historical_compatibility": override.get(
                    "historical_compatibility",
                    "Primary 2010-2024 model outcome unless separately documented.",
                ),
                "limitation": override.get("limitation", ""),
                "source_release_domain": "",
                "source_release_source_class": "",
                "analysis_cohort": "race; sex_gender",
                "analysis_role": "model outcome",
                "design_group": "outcome",
            }
        )
    frame = pd.DataFrame(rows)
    documentation = phase2 / "documentation"
    documentation.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        documentation / "Concordance_Variable_Dictionary.csv", index=False
    )
    readme = """# Concordance variable dictionary

The machine-readable dictionary is `Concordance_Variable_Dictionary.csv`.
It covers all fields in the normalized Phase 2 visit-level tables, the
versioned procedure-discretion sidecar, both cohort-specific model designs,
and the complete model-outcome catalog.

Important conventions:

- Every table has one row per ED visit and joins one-to-one on
  `visit_key`, `visit_year`, and `visit_quarter`.
- Physician–patient pair names put the physician first.
- Physician race/ethnicity is a Bayesian full-name analytical probability
  proxy without residential geography; it is not BISG or self-identified race.
- Patient sex and physician gender do not measure gender identity.
- Facility-reported charges are not costs, payments, or reimbursement.
- Missing values are never silently changed to zero.
- 2005–2008 historical race/ethnicity semantics are not pooled with the
  2010–2024 primary definitions.
- The exact transformation code is authoritative if a short dictionary label
  cannot express every edge case.
"""
    (documentation / "Concordance_Variable_Dictionary_README.md").write_text(
        readme, encoding="utf-8"
    )
    manifest = {
        "created_utc": now_utc(),
        "tables": [table for table, _ in tables],
        "model_designs": ["race", "sex_gender"],
        "includes_complete_model_outcome_catalog": True,
        "variables": len(frame),
        "status": "complete",
    }
    (documentation / "concordance_variable_dictionary_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
