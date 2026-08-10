#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/16_apply_multiple_testing.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Apply prespecified Holm/BH corrections to saved concordance contrasts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from statsmodels.stats.multitest import multipletests


PRIMARY = {
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
}
RESOURCE = {
    "total_charge_reported",
    "total_charge_real_2024",
    "component_charge_sum_real_2024",
}
CHARGE_COMPONENTS = {
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
}
PROCEDURE = {
    "procedure_count_analysis",
    "any_procedure_flag",
    "high_procedure_flag",
    "higher_discretion_procedure_count",
    "lower_discretion_procedure_count",
    "ambiguous_discretion_procedure_count",
    "any_higher_discretion_candidate_flag",
    "any_lower_discretion_candidate_flag",
    "higher_minus_lower_discretion_procedure_count",
    "any_higher_minus_any_lower_discretion_candidate",
}
DISPOSITION = {
    "routine_discharge_flag",
    "transfer_flag",
    "hospice_flag",
    "mortality_flag",
    "left_discontinued_care_flag",
    "home_health_flag",
}
TRANSFORMATION_SENSITIVITY = {
    "log1p_los_hours_primary",
    "log1p_total_charge_reported_real_2024",
    "any_positive_total_charge_reported",
    "los_hours_winsor_yq_p995",
    "total_charge_real_winsor_yq_p995",
    "total_charge_real_winsor_yq_p999",
    "total_charge_reported_real_2024_medical_cpi",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def family_for(row: pd.Series) -> tuple[str, str]:
    cohort = row["cohort"]
    model = row["model_id"]
    outcome = row["outcome"]
    sample_policy = row.get("analysis_sample_policy", "common_primary")
    if (
        cohort == "race"
        and model.startswith("m2_")
        and outcome in PRIMARY
        and sample_policy in {"los_outcome", "charge_outcome"}
    ):
        return "confirmatory_race_primary", "holm"
    if sample_policy in {"los_outcome", "charge_outcome"}:
        return (
            f"secondary_{cohort}_{model}_outcome_specific_robustness",
            "fdr_bh",
        )
    if outcome in PRIMARY:
        return (
            f"secondary_{cohort}_{model}_common_sample_primary_robustness",
            "fdr_bh",
        )
    if outcome in RESOURCE:
        return f"secondary_{cohort}_{model}_resource", "fdr_bh"
    if outcome in CHARGE_COMPONENTS:
        return f"secondary_{cohort}_{model}_charge_components", "fdr_bh"
    if outcome in PROCEDURE:
        return f"secondary_{cohort}_{model}_procedure", "fdr_bh"
    if outcome in DISPOSITION:
        return f"secondary_{cohort}_{model}_disposition", "fdr_bh"
    if outcome in TRANSFORMATION_SENSITIVITY:
        return f"secondary_{cohort}_{model}_transformation_sensitivity", "fdr_bh"
    return f"secondary_{cohort}_{model}_other", "fdr_bh"


def adjust_by_family(
    frame: pd.DataFrame,
    family_column: str,
    p_value_column: str = "p_value",
    method: str = "fdr_bh",
) -> pd.DataFrame:
    adjusted_frame = frame.copy()
    adjusted_frame["adjustment_method"] = method
    adjusted_frame["adjusted_p_value"] = pd.NA
    adjusted_frame["reject_adjusted_alpha_0_05"] = False
    for _, indices in adjusted_frame.groupby(family_column).groups.items():
        index = list(indices)
        valid_index = adjusted_frame.loc[index].index[
            adjusted_frame.loc[index, p_value_column].notna()
        ]
        if not len(valid_index):
            continue
        reject, adjusted, _, _ = multipletests(
            adjusted_frame.loc[valid_index, p_value_column].astype(float),
            alpha=0.05,
            method=method,
        )
        adjusted_frame.loc[valid_index, "adjusted_p_value"] = adjusted
        adjusted_frame.loc[
            valid_index, "reject_adjusted_alpha_0_05"
        ] = reject
    return adjusted_frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    model_root = phase2 / "results" / "models"
    frames = []
    for cohort in ("race", "sex_gender"):
        path = model_root / cohort / "primary_model_coefficients.csv"
        frame = pd.read_csv(path)
        frame["analysis_sample_policy"] = "common_primary"
        frame["result_source"] = str(path)
        interaction = (
            "race_interaction"
            if cohort == "race"
            else "sex_gender_interaction"
        )
        frames.append(frame.loc[frame["term"] == interaction].copy())
        for sample_id, sample_policy in (
            ("los", "los_outcome"),
            ("charge", "charge_outcome"),
        ):
            outcome_path = (
                phase2
                / "results"
                / "outcome_specific_primary"
                / sample_id
                / cohort
                / "primary_model_coefficients.csv"
            )
            outcome_frame = pd.read_csv(outcome_path)
            outcome_frame["analysis_sample_policy"] = sample_policy
            outcome_frame["result_source"] = str(outcome_path)
            frames.append(
                outcome_frame.loc[
                    outcome_frame["term"] == interaction
                ].copy()
            )
    results = pd.concat(frames, ignore_index=True)
    family_method = results.apply(family_for, axis=1)
    results["testing_family"] = [item[0] for item in family_method]
    results["adjustment_method"] = [item[1] for item in family_method]
    results["adjusted_p_value"] = pd.NA
    results["reject_adjusted_alpha_0_05"] = False
    for family, indices in results.groupby("testing_family").groups.items():
        index = list(indices)
        method = results.loc[index, "adjustment_method"].iloc[0]
        valid = results.loc[index, "p_value"].notna()
        valid_index = results.loc[index].index[valid]
        if not len(valid_index):
            continue
        reject, adjusted, _, _ = multipletests(
            results.loc[valid_index, "p_value"].astype(float),
            alpha=0.05,
            method=method,
        )
        results.loc[valid_index, "adjusted_p_value"] = adjusted
        results.loc[valid_index, "reject_adjusted_alpha_0_05"] = reject
    confirmatory = results.loc[
        results["testing_family"] == "confirmatory_race_primary"
    ].copy()
    if (
        len(confirmatory) != 2
        or set(confirmatory["outcome"]) != PRIMARY
        or set(confirmatory["analysis_sample_policy"])
        != {"los_outcome", "charge_outcome"}
        or set(confirmatory["cohort"]) != {"race"}
        or set(confirmatory["model_id"])
        != {"m2_fully_adjusted_facility_yq_clinical_fe"}
    ):
        raise RuntimeError(
            "Confirmatory Holm family is not exactly the two outcome-specific "
            "race M2 contrasts"
        )

    ami_path = phase2 / "results" / "ami" / "ami_model_interaction_results.csv"
    ami = pd.read_csv(ami_path)
    if not ami.empty:
        ami["testing_family"] = (
            "secondary_ami_"
            + ami["definition"].astype(str)
            + "_"
            + ami["estimator"].astype(str)
        )
        ami["adjustment_method"] = "fdr_bh"
        ami["adjusted_p_value"] = pd.NA
        ami["reject_adjusted_alpha_0_05"] = False
        for family, indices in ami.groupby("testing_family").groups.items():
            index = list(indices)
            valid_index = ami.loc[index].index[ami.loc[index, "p_value"].notna()]
            if not len(valid_index):
                continue
            reject, adjusted, _, _ = multipletests(
                ami.loc[valid_index, "p_value"].astype(float),
                alpha=0.05,
                method="fdr_bh",
            )
            ami.loc[valid_index, "adjusted_p_value"] = adjusted
            ami.loc[valid_index, "reject_adjusted_alpha_0_05"] = reject
        ami.to_csv(
            phase2 / "results" / "ami" / "ami_model_results_adjusted.csv",
            index=False,
        )

    heterogeneity_frames = []
    for cohort in ("race", "sex_gender"):
        path = (
            phase2
            / "results"
            / "heterogeneity"
            / cohort
            / "heterogeneity_interaction_differences.csv"
        )
        frame = pd.read_csv(path)
        frame["testing_family"] = f"secondary_{cohort}_heterogeneity"
        heterogeneity_frames.append(frame)
    heterogeneity = pd.concat(heterogeneity_frames, ignore_index=True)
    heterogeneity = adjust_by_family(
        heterogeneity, "testing_family", method="fdr_bh"
    )
    heterogeneity.to_csv(
        phase2
        / "results"
        / "heterogeneity"
        / "heterogeneity_results_adjusted.csv",
        index=False,
    )

    historical_race_path = (
        phase2
        / "results"
        / "historical_provider_v2_sensitivity"
        / "historical_adjusted_race_sensitivities.csv"
    )
    historical_race = pd.read_csv(historical_race_path)
    if not historical_race.empty:
        historical_race["testing_family"] = (
            "secondary_historical_race_"
            + historical_race["race_specification"].astype(str)
        )
        historical_race = adjust_by_family(
            historical_race, "testing_family"
        )
        historical_race.to_csv(
            historical_race_path.with_name(
                "historical_adjusted_race_sensitivities_multiple_testing.csv"
            ),
            index=False,
        )

    historical_sex_path = (
        phase2
        / "results"
        / "historical_provider_v2_sex_gender_sensitivity"
        / "historical_sex_gender_adjusted_interactions.csv"
    )
    historical_sex = pd.read_csv(historical_sex_path)
    if not historical_sex.empty:
        historical_sex["testing_family"] = (
            "secondary_historical_recorded_sex_physician_gender"
        )
        historical_sex = adjust_by_family(
            historical_sex, "testing_family"
        )
        historical_sex.to_csv(
            historical_sex_path.with_name(
                "historical_sex_gender_adjusted_interactions_multiple_testing.csv"
            ),
            index=False,
        )

    historical_ami_path = (
        phase2
        / "results"
        / "historical_provider_v2_ami"
        / "historical_ami_interaction_results.csv"
    )
    historical_ami = pd.read_csv(historical_ami_path)
    if not historical_ami.empty:
        historical_definition_column = (
            "definition"
            if "definition" in historical_ami.columns
            else "cohort_definition"
        )
        if historical_definition_column not in historical_ami.columns:
            raise RuntimeError(
                "Historical AMI result has no definition/cohort_definition field"
            )
        historical_ami["testing_family"] = (
            "secondary_historical_ami_"
            + historical_ami[historical_definition_column].astype(str)
            + "_"
            + historical_ami["estimator"].astype(str)
        )
        historical_ami = adjust_by_family(
            historical_ami, "testing_family"
        )
        historical_ami.to_csv(
            historical_ami_path.with_name(
                "historical_ami_interaction_results_multiple_testing.csv"
            ),
            index=False,
        )

    intersectional_path = (
        phase2
        / "results"
        / "intersectional"
        / "intersectional_model_coefficients.csv"
    )
    intersectional = pd.read_csv(intersectional_path)
    intersectional = intersectional.loc[
        intersectional["term"] == "intersection_four_way"
    ].copy()
    if not intersectional.empty:
        valid = intersectional["p_value"].notna()
        reject, adjusted, _, _ = multipletests(
            intersectional.loc[valid, "p_value"].astype(float),
            alpha=0.05,
            method="fdr_bh",
        )
        intersectional["testing_family"] = "exploratory_intersectional"
        intersectional["adjustment_method"] = "fdr_bh"
        intersectional["adjusted_p_value"] = pd.NA
        intersectional["reject_adjusted_alpha_0_05"] = False
        intersectional.loc[valid, "adjusted_p_value"] = adjusted
        intersectional.loc[valid, "reject_adjusted_alpha_0_05"] = reject
        intersectional.to_csv(
            phase2
            / "results"
            / "intersectional"
            / "intersectional_results_adjusted.csv",
            index=False,
        )

    output = phase2 / "results" / "inference"
    output.mkdir(parents=True, exist_ok=True)
    supplemental_outputs = []

    classified_subjectivity_frames = []
    for cohort in ("race", "sex_gender"):
        path = (
            phase2
            / "results"
            / "classified_subjectivity"
            / cohort
            / "classified_subjectivity_interaction_differences.csv"
        )
        frame = pd.read_csv(path)
        frame["testing_family"] = (
            f"secondary_{cohort}_classified_subjectivity"
        )
        classified_subjectivity_frames.append(frame)
    classified_subjectivity = adjust_by_family(
        pd.concat(classified_subjectivity_frames, ignore_index=True),
        "testing_family",
    )
    classified_subjectivity_output = (
        output / "classified_subjectivity_multiple_testing.csv"
    )
    classified_subjectivity.to_csv(
        classified_subjectivity_output, index=False
    )
    supplemental_outputs.append(classified_subjectivity_output.name)

    threshold_path = (
        phase2
        / "results"
        / "race_sensitivities"
        / "race_threshold_probability_interactions.csv"
    )
    threshold = pd.read_csv(threshold_path)
    threshold["testing_family"] = (
        "secondary_race_proxy_threshold_probability_"
        + threshold["model_id"].astype(str)
    )
    threshold_adjusted = adjust_by_family(threshold, "testing_family")
    threshold_output = output / "race_proxy_sensitivities_multiple_testing.csv"
    threshold_adjusted.to_csv(threshold_output, index=False)
    supplemental_outputs.append(threshold_output.name)

    glm_frames = []
    for cohort in ("race", "sex_gender"):
        path = (
            phase2
            / "results"
            / "outcome_appropriate_glm"
            / cohort
            / "outcome_appropriate_glm_sensitivities.csv"
        )
        frame = pd.read_csv(path)
        frame["testing_family"] = (
            f"secondary_{cohort}_outcome_appropriate_glm"
        )
        glm_frames.append(frame)
    glm = adjust_by_family(
        pd.concat(glm_frames, ignore_index=True), "testing_family"
    )
    glm_output = output / "outcome_appropriate_glm_multiple_testing.csv"
    glm.to_csv(glm_output, index=False)
    supplemental_outputs.append(glm_output.name)

    payer_path = (
        phase2
        / "results"
        / "payer_category_heterogeneity"
        / "payer_category_interaction_differences.csv"
    )
    payer = pd.read_csv(payer_path)
    payer["testing_family"] = (
        "secondary_race_payer_category_"
        + payer["outcome"].astype(str)
    )
    payer_adjusted = adjust_by_family(payer, "testing_family")
    payer_output = (
        output / "payer_category_heterogeneity_multiple_testing.csv"
    )
    payer_adjusted.to_csv(payer_output, index=False)
    supplemental_outputs.append(payer_output.name)

    mi_path = (
        phase2
        / "results"
        / "race_proxy_multiple_imputation"
        / "race_proxy_mi_pooled_results.csv"
    )
    mi = pd.read_csv(mi_path)
    mi["testing_family"] = "secondary_race_proxy_multiple_imputation"
    mi_adjusted = adjust_by_family(mi, "testing_family")
    mi_output = output / "race_proxy_mi_multiple_testing.csv"
    mi_adjusted.to_csv(mi_output, index=False)
    supplemental_outputs.append(mi_output.name)

    subset_frames = []
    for cohort in ("race", "sex_gender"):
        path = (
            phase2
            / "results"
            / "exact_subset_sensitivities"
            / cohort
            / "exact_subset_interactions.csv"
        )
        frame = pd.read_csv(path)
        frame["testing_family"] = (
            "secondary_"
            + cohort
            + "_exact_subset_"
            + frame["sensitivity_id"].astype(str)
        )
        subset_frames.append(frame)
    subset = adjust_by_family(
        pd.concat(subset_frames, ignore_index=True), "testing_family"
    )
    subset_output = output / "exact_subset_sensitivities_multiple_testing.csv"
    subset.to_csv(subset_output, index=False)
    supplemental_outputs.append(subset_output.name)

    cohort_definition_frames = []
    for variant_id in (
        "direct_plus_unique_license_nh_t50",
        "race_only_direct_t50",
    ):
        for outcome_id in ("los", "charge"):
            path = (
                phase2
                / "results"
                / "cohort_definition_adjusted"
                / variant_id
                / outcome_id
                / "race"
                / "primary_model_coefficients.csv"
            )
            frame = pd.read_csv(path)
            frame = frame.loc[
                frame["term"] == "race_interaction"
            ].copy()
            frame["cohort_definition_sensitivity"] = variant_id
            frame["outcome_sample_id"] = outcome_id
            frame["testing_family"] = (
                "secondary_race_cohort_definition_"
                + variant_id
                + "_"
                + frame["model_id"].astype(str)
            )
            cohort_definition_frames.append(frame)
    cohort_definition = adjust_by_family(
        pd.concat(cohort_definition_frames, ignore_index=True),
        "testing_family",
    )
    cohort_definition_output = (
        output
        / "adjusted_cohort_definition_sensitivities_multiple_testing.csv"
    )
    cohort_definition.to_csv(cohort_definition_output, index=False)
    supplemental_outputs.append(cohort_definition_output.name)

    negative_frames = []
    for cohort in ("race", "sex_gender"):
        path = (
            phase2
            / "results"
            / "negative_control"
            / cohort
            / "negative_control_coefficients.csv"
        )
        frame = pd.read_csv(path)
        target = (
            "race_interaction"
            if cohort == "race"
            else "sex_gender_interaction"
        )
        frame = frame.loc[frame["term"] == target].copy()
        frame["testing_family"] = "diagnostic_negative_control"
        negative_frames.append(frame)
    negative = adjust_by_family(
        pd.concat(negative_frames, ignore_index=True), "testing_family"
    )
    negative_output = output / "negative_controls_multiple_testing.csv"
    negative.to_csv(negative_output, index=False)
    supplemental_outputs.append(negative_output.name)

    results.to_csv(
        output / "concordance_interactions_multiple_testing.csv", index=False
    )
    family_summary = (
        results.groupby(["testing_family", "adjustment_method"], as_index=False)
        .agg(
            tests=("p_value", "count"),
            adjusted_rejections=(
                "reject_adjusted_alpha_0_05",
                "sum",
            ),
        )
    )
    family_summary.to_csv(
        output / "multiple_testing_family_summary.csv", index=False
    )
    manifest = {
        "created_utc": now_utc(),
        "primary_adjustment": (
            "Holm across exactly two outcome-specific race M2 primary "
            "contrasts: LOS and real reported total charges"
        ),
        "confirmatory_tests": len(confirmatory),
        "confirmatory_outcomes": sorted(confirmatory["outcome"].tolist()),
        "confirmatory_sample_policies": sorted(
            confirmatory["analysis_sample_policy"].tolist()
        ),
        "common_primary_sample_role": "robustness only",
        "secondary_adjustment": "Benjamini-Hochberg within prespecified outcome families",
        "unadjusted_p_values_preserved": True,
        "rows": len(results),
        "families": int(results["testing_family"].nunique()),
        "supplemental_adjusted_outputs": supplemental_outputs,
        "leave_one_year_out_note": (
            "Leave-one-year-out estimates are repeated stability diagnostics "
            "for the same estimand and are not treated as separate discovery tests."
        ),
    }
    (output / "multiple_testing_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
