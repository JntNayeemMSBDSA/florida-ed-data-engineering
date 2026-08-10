#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/54_independent_global_multiplicity_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently reconstruct every non-directional multiplicity output.

This audit intentionally does not import the production multiplicity script.
It rebuilds each frozen family from the unadjusted result sources, implements
Holm and Benjamini-Hochberg directly, and compares the complete reconstructed
tables with the saved adjusted outputs. It reports only structural diagnostics,
counts, methods, and hashes; it does not expose or interpret estimates.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    frame = pd.DataFrame(rows, columns=fieldnames)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _validated_p_values(values: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    supplied = values.notna().to_numpy()
    if np.any(supplied & ~np.isfinite(numeric)):
        raise ValueError("A supplied p-value is not finite")
    valid = np.isfinite(numeric)
    if np.any((numeric[valid] < 0.0) | (numeric[valid] > 1.0)):
        raise ValueError("A p-value is outside [0, 1]")
    return numeric, valid


def benjamini_hochberg(values: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    numeric, valid = _validated_p_values(values)
    adjusted = np.full(len(numeric), np.nan, dtype=float)
    rejected = np.zeros(len(numeric), dtype=bool)
    valid_positions = np.flatnonzero(valid)
    if not len(valid_positions):
        return adjusted, rejected
    p = numeric[valid_positions]
    order = np.argsort(p, kind="mergesort")
    ordered = p[order]
    ranks = np.arange(1, len(ordered) + 1, dtype=float)
    ordered_adjusted = ordered * len(ordered) / ranks
    ordered_adjusted = np.minimum.accumulate(ordered_adjusted[::-1])[::-1]
    ordered_adjusted = np.clip(ordered_adjusted, 0.0, 1.0)
    inverse = np.empty_like(order)
    inverse[order] = np.arange(len(order))
    valid_adjusted = ordered_adjusted[inverse]
    adjusted[valid_positions] = valid_adjusted
    rejected[valid_positions] = valid_adjusted <= 0.05
    return adjusted, rejected


def holm(values: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    numeric, valid = _validated_p_values(values)
    adjusted = np.full(len(numeric), np.nan, dtype=float)
    rejected = np.zeros(len(numeric), dtype=bool)
    valid_positions = np.flatnonzero(valid)
    if not len(valid_positions):
        return adjusted, rejected
    p = numeric[valid_positions]
    order = np.argsort(p, kind="mergesort")
    ordered = p[order]
    multipliers = np.arange(len(ordered), 0, -1, dtype=float)
    ordered_adjusted = np.maximum.accumulate(ordered * multipliers)
    ordered_adjusted = np.clip(ordered_adjusted, 0.0, 1.0)
    inverse = np.empty_like(order)
    inverse[order] = np.arange(len(order))
    valid_adjusted = ordered_adjusted[inverse]
    adjusted[valid_positions] = valid_adjusted
    rejected[valid_positions] = valid_adjusted <= 0.05
    return adjusted, rejected


def apply_adjustment(
    frame: pd.DataFrame,
    family_column: str = "testing_family",
    p_value_column: str = "p_value",
    method: str | None = "fdr_bh",
) -> pd.DataFrame:
    expected = frame.copy()
    if method is not None:
        expected["adjustment_method"] = method
    if "adjustment_method" not in expected:
        raise ValueError("Adjustment method is missing")
    expected["adjusted_p_value"] = np.nan
    expected["reject_adjusted_alpha_0_05"] = False
    for _, indices in expected.groupby(family_column, sort=False).groups.items():
        index = list(indices)
        methods = expected.loc[index, "adjustment_method"].dropna().unique()
        if len(methods) != 1:
            raise ValueError("A testing family has multiple adjustment methods")
        family_method = str(methods[0])
        if family_method == "fdr_bh":
            adjusted, rejected = benjamini_hochberg(
                expected.loc[index, p_value_column]
            )
        elif family_method == "holm":
            adjusted, rejected = holm(expected.loc[index, p_value_column])
        else:
            raise ValueError(f"Unsupported adjustment method: {family_method}")
        expected.loc[index, "adjusted_p_value"] = adjusted
        expected.loc[index, "reject_adjusted_alpha_0_05"] = rejected
    return expected


def primary_family(row: pd.Series) -> tuple[str, str]:
    cohort = str(row["cohort"])
    model = str(row["model_id"])
    outcome = str(row["outcome"])
    sample_policy = str(row.get("analysis_sample_policy", "common_primary"))
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


def csv_roundtrip(frame: pd.DataFrame) -> pd.DataFrame:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    buffer.seek(0)
    return pd.read_csv(buffer)


def compare_complete_frames(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    expected_roundtripped = csv_roundtrip(expected)
    if list(actual.columns) != list(expected_roundtripped.columns):
        raise AssertionError(
            "Column mismatch: "
            f"actual={list(actual.columns)}, "
            f"expected={list(expected_roundtripped.columns)}"
        )
    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected_roundtripped.reset_index(drop=True),
        check_dtype=False,
        check_exact=False,
        rtol=1e-11,
        atol=1e-13,
    )


class MultiplicityAudit:
    def __init__(self, phase2: Path):
        self.phase2 = phase2
        self.sources: set[Path] = set()
        self.outputs: set[Path] = set()
        self.rows: list[dict[str, Any]] = []

    def read(self, path: Path) -> pd.DataFrame:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        self.sources.add(resolved)
        return pd.read_csv(resolved)

    def verify(
        self,
        dataset_id: str,
        output_path: Path,
        expected: pd.DataFrame,
    ) -> None:
        resolved = output_path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        actual = pd.read_csv(resolved)
        compare_complete_frames(actual, expected)
        self.outputs.add(resolved)
        family_count = (
            int(actual["testing_family"].nunique(dropna=True))
            if "testing_family" in actual
            else 0
        )
        methods = (
            sorted(actual["adjustment_method"].dropna().astype(str).unique())
            if "adjustment_method" in actual
            else []
        )
        self.rows.append(
            {
                "dataset_id": dataset_id,
                "status": "PASS",
                "rows": int(len(actual)),
                "testing_families": family_count,
                "methods": "|".join(methods),
                "output_path": str(resolved),
                "output_sha256": sha256_file(resolved),
            }
        )

    def build_and_verify(self) -> dict[str, Any]:
        phase2 = self.phase2
        model_root = phase2 / "results" / "models"
        inference = phase2 / "results" / "inference"

        primary_frames = []
        for cohort in ("race", "sex_gender"):
            path = model_root / cohort / "primary_model_coefficients.csv"
            frame = self.read(path)
            frame["analysis_sample_policy"] = "common_primary"
            frame["result_source"] = str(path.resolve())
            term = (
                "race_interaction"
                if cohort == "race"
                else "sex_gender_interaction"
            )
            primary_frames.append(frame.loc[frame["term"] == term].copy())
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
                outcome_frame = self.read(outcome_path)
                outcome_frame["analysis_sample_policy"] = sample_policy
                outcome_frame["result_source"] = str(outcome_path.resolve())
                primary_frames.append(
                    outcome_frame.loc[outcome_frame["term"] == term].copy()
                )
        primary = pd.concat(primary_frames, ignore_index=True)
        family_method = primary.apply(primary_family, axis=1)
        primary["testing_family"] = [value[0] for value in family_method]
        primary["adjustment_method"] = [value[1] for value in family_method]
        primary = apply_adjustment(primary, method=None)
        confirmatory = primary.loc[
            primary["testing_family"].eq("confirmatory_race_primary")
        ]
        if not (
            len(confirmatory) == 2
            and set(confirmatory["outcome"]) == PRIMARY
            and set(confirmatory["analysis_sample_policy"])
            == {"los_outcome", "charge_outcome"}
            and set(confirmatory["cohort"]) == {"race"}
            and set(confirmatory["model_id"])
            == {"m2_fully_adjusted_facility_yq_clinical_fe"}
            and set(confirmatory["adjustment_method"]) == {"holm"}
        ):
            raise AssertionError("Confirmatory family definition is not exact")
        self.verify(
            "primary_and_outcome_specific",
            inference / "concordance_interactions_multiple_testing.csv",
            primary,
        )

        family_summary = (
            primary.groupby(
                ["testing_family", "adjustment_method"], as_index=False
            )
            .agg(
                tests=("p_value", "count"),
                adjusted_rejections=(
                    "reject_adjusted_alpha_0_05",
                    "sum",
                ),
            )
        )
        self.verify(
            "primary_family_summary",
            inference / "multiple_testing_family_summary.csv",
            family_summary,
        )

        ami_path = (
            phase2 / "results" / "ami" / "ami_model_interaction_results.csv"
        )
        ami = self.read(ami_path)
        if not ami.empty:
            ami["testing_family"] = (
                "secondary_ami_"
                + ami["definition"].astype(str)
                + "_"
                + ami["estimator"].astype(str)
            )
            ami = apply_adjustment(ami)
        self.verify(
            "primary_ami",
            phase2 / "results" / "ami" / "ami_model_results_adjusted.csv",
            ami,
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
            frame = self.read(path)
            frame["testing_family"] = f"secondary_{cohort}_heterogeneity"
            heterogeneity_frames.append(frame)
        heterogeneity = apply_adjustment(
            pd.concat(heterogeneity_frames, ignore_index=True)
        )
        self.verify(
            "heterogeneity",
            phase2
            / "results"
            / "heterogeneity"
            / "heterogeneity_results_adjusted.csv",
            heterogeneity,
        )

        historical_race_path = (
            phase2
            / "results"
            / "historical_provider_v2_sensitivity"
            / "historical_adjusted_race_sensitivities.csv"
        )
        historical_race = self.read(historical_race_path)
        if not historical_race.empty:
            historical_race["testing_family"] = (
                "secondary_historical_race_"
                + historical_race["race_specification"].astype(str)
            )
            historical_race = apply_adjustment(historical_race)
        self.verify(
            "historical_race",
            historical_race_path.with_name(
                "historical_adjusted_race_sensitivities_multiple_testing.csv"
            ),
            historical_race,
        )

        historical_gender_path = (
            phase2
            / "results"
            / "historical_provider_v2_sex_gender_sensitivity"
            / "historical_sex_gender_adjusted_interactions.csv"
        )
        historical_gender = self.read(historical_gender_path)
        if not historical_gender.empty:
            historical_gender["testing_family"] = (
                "secondary_historical_recorded_sex_physician_gender"
            )
            historical_gender = apply_adjustment(historical_gender)
        self.verify(
            "historical_sex_gender",
            historical_gender_path.with_name(
                "historical_sex_gender_adjusted_interactions_multiple_testing.csv"
            ),
            historical_gender,
        )

        historical_ami_path = (
            phase2
            / "results"
            / "historical_provider_v2_ami"
            / "historical_ami_interaction_results.csv"
        )
        historical_ami = self.read(historical_ami_path)
        if not historical_ami.empty:
            definition_column = (
                "definition"
                if "definition" in historical_ami
                else "cohort_definition"
            )
            if definition_column not in historical_ami:
                raise AssertionError(
                    "Historical AMI definition field is absent"
                )
            historical_ami["testing_family"] = (
                "secondary_historical_ami_"
                + historical_ami[definition_column].astype(str)
                + "_"
                + historical_ami["estimator"].astype(str)
            )
            historical_ami = apply_adjustment(historical_ami)
        self.verify(
            "historical_ami",
            historical_ami_path.with_name(
                "historical_ami_interaction_results_multiple_testing.csv"
            ),
            historical_ami,
        )

        intersectional_path = (
            phase2
            / "results"
            / "intersectional"
            / "intersectional_model_coefficients.csv"
        )
        intersectional = self.read(intersectional_path)
        intersectional = intersectional.loc[
            intersectional["term"].eq("intersection_four_way")
        ].copy()
        if not intersectional.empty:
            intersectional["testing_family"] = "exploratory_intersectional"
            intersectional = apply_adjustment(intersectional)
        self.verify(
            "binary_intersectional",
            phase2
            / "results"
            / "intersectional"
            / "intersectional_results_adjusted.csv",
            intersectional,
        )

        classified_frames = []
        for cohort in ("race", "sex_gender"):
            path = (
                phase2
                / "results"
                / "classified_subjectivity"
                / cohort
                / "classified_subjectivity_interaction_differences.csv"
            )
            frame = self.read(path)
            frame["testing_family"] = (
                f"secondary_{cohort}_classified_subjectivity"
            )
            classified_frames.append(frame)
        classified = apply_adjustment(
            pd.concat(classified_frames, ignore_index=True)
        )
        self.verify(
            "classified_subjectivity",
            inference / "classified_subjectivity_multiple_testing.csv",
            classified,
        )

        threshold_path = (
            phase2
            / "results"
            / "race_sensitivities"
            / "race_threshold_probability_interactions.csv"
        )
        threshold = self.read(threshold_path)
        threshold["testing_family"] = (
            "secondary_race_proxy_threshold_probability_"
            + threshold["model_id"].astype(str)
        )
        threshold = apply_adjustment(threshold)
        self.verify(
            "race_threshold_probability",
            inference / "race_proxy_sensitivities_multiple_testing.csv",
            threshold,
        )

        glm_frames = []
        for cohort in ("race", "sex_gender"):
            path = (
                phase2
                / "results"
                / "outcome_appropriate_glm"
                / cohort
                / "outcome_appropriate_glm_sensitivities.csv"
            )
            frame = self.read(path)
            frame["testing_family"] = (
                f"secondary_{cohort}_outcome_appropriate_glm"
            )
            glm_frames.append(frame)
        glm = apply_adjustment(pd.concat(glm_frames, ignore_index=True))
        self.verify(
            "outcome_appropriate_glm",
            inference / "outcome_appropriate_glm_multiple_testing.csv",
            glm,
        )

        payer_path = (
            phase2
            / "results"
            / "payer_category_heterogeneity"
            / "payer_category_interaction_differences.csv"
        )
        payer = self.read(payer_path)
        payer["testing_family"] = (
            "secondary_race_payer_category_"
            + payer["outcome"].astype(str)
        )
        payer = apply_adjustment(payer)
        self.verify(
            "payer_category_heterogeneity",
            inference / "payer_category_heterogeneity_multiple_testing.csv",
            payer,
        )

        mi_path = (
            phase2
            / "results"
            / "race_proxy_multiple_imputation"
            / "race_proxy_mi_pooled_results.csv"
        )
        mi = self.read(mi_path)
        mi["testing_family"] = "secondary_race_proxy_multiple_imputation"
        mi = apply_adjustment(mi)
        self.verify(
            "physician_race_multiple_imputation",
            inference / "race_proxy_mi_multiple_testing.csv",
            mi,
        )

        subset_frames = []
        for cohort in ("race", "sex_gender"):
            path = (
                phase2
                / "results"
                / "exact_subset_sensitivities"
                / cohort
                / "exact_subset_interactions.csv"
            )
            frame = self.read(path)
            frame["testing_family"] = (
                "secondary_"
                + cohort
                + "_exact_subset_"
                + frame["sensitivity_id"].astype(str)
            )
            subset_frames.append(frame)
        subset = apply_adjustment(pd.concat(subset_frames, ignore_index=True))
        self.verify(
            "exact_subset_sensitivities",
            inference / "exact_subset_sensitivities_multiple_testing.csv",
            subset,
        )

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
                frame = self.read(path)
                frame = frame.loc[frame["term"].eq("race_interaction")].copy()
                frame["cohort_definition_sensitivity"] = variant_id
                frame["outcome_sample_id"] = outcome_id
                frame["testing_family"] = (
                    "secondary_race_cohort_definition_"
                    + variant_id
                    + "_"
                    + frame["model_id"].astype(str)
                )
                cohort_definition_frames.append(frame)
        cohort_definition = apply_adjustment(
            pd.concat(cohort_definition_frames, ignore_index=True)
        )
        self.verify(
            "cohort_definition_sensitivities",
            inference
            / "adjusted_cohort_definition_sensitivities_multiple_testing.csv",
            cohort_definition,
        )

        negative_frames = []
        for cohort in ("race", "sex_gender"):
            path = (
                phase2
                / "results"
                / "negative_control"
                / cohort
                / "negative_control_coefficients.csv"
            )
            frame = self.read(path)
            target = (
                "race_interaction"
                if cohort == "race"
                else "sex_gender_interaction"
            )
            frame = frame.loc[frame["term"].eq(target)].copy()
            frame["testing_family"] = "diagnostic_negative_control"
            negative_frames.append(frame)
        negative = apply_adjustment(
            pd.concat(negative_frames, ignore_index=True)
        )
        self.verify(
            "negative_controls",
            inference / "negative_controls_multiple_testing.csv",
            negative,
        )

        manifest_path = inference / "multiple_testing_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.outputs.add(manifest_path.resolve())
        supplemental_expected = {
            "classified_subjectivity_multiple_testing.csv",
            "race_proxy_sensitivities_multiple_testing.csv",
            "outcome_appropriate_glm_multiple_testing.csv",
            "payer_category_heterogeneity_multiple_testing.csv",
            "race_proxy_mi_multiple_testing.csv",
            "exact_subset_sensitivities_multiple_testing.csv",
            "adjusted_cohort_definition_sensitivities_multiple_testing.csv",
            "negative_controls_multiple_testing.csv",
        }
        manifest_checks = {
            "confirmatory_tests": manifest.get("confirmatory_tests") == 2,
            "confirmatory_outcomes": set(
                manifest.get("confirmatory_outcomes", [])
            )
            == PRIMARY,
            "confirmatory_sample_policies": set(
                manifest.get("confirmatory_sample_policies", [])
            )
            == {"los_outcome", "charge_outcome"},
            "common_primary_sample_role": manifest.get(
                "common_primary_sample_role"
            )
            == "robustness only",
            "unadjusted_p_values_preserved": manifest.get(
                "unadjusted_p_values_preserved"
            )
            is True,
            "rows": int(manifest.get("rows", -1)) == len(primary),
            "families": int(manifest.get("families", -1))
            == int(primary["testing_family"].nunique()),
            "supplemental_outputs": set(
                manifest.get("supplemental_adjusted_outputs", [])
            )
            == supplemental_expected,
        }
        if not all(manifest_checks.values()):
            raise AssertionError(
                f"Multiplicity manifest mismatch: {manifest_checks}"
            )
        self.rows.append(
            {
                "dataset_id": "multiple_testing_manifest",
                "status": "PASS",
                "rows": int(manifest["rows"]),
                "testing_families": int(manifest["families"]),
                "methods": "holm|fdr_bh",
                "output_path": str(manifest_path.resolve()),
                "output_sha256": sha256_file(manifest_path),
            }
        )

        return {
            "status": "PASS",
            "created_utc": utc_now(),
            "audit_version": "independent_global_multiplicity_v1_20260727",
            "estimate_blind": True,
            "production_script_imported": False,
            "audit_script": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "production_multiplicity_script": {
                "path": str(
                    (
                        phase2 / "scripts" / "16_apply_multiple_testing.py"
                    ).resolve()
                ),
                "sha256": sha256_file(
                    phase2 / "scripts" / "16_apply_multiple_testing.py"
                ),
            },
            "unit_test_artifact": {
                "path": str(
                    (
                        phase2
                        / "qa"
                        / "independent_multiple_testing_audit_unit_tests.json"
                    ).resolve()
                ),
                "sha256": sha256_file(
                    phase2
                    / "qa"
                    / "independent_multiple_testing_audit_unit_tests.json"
                ),
            },
            "independent_algorithms": [
                "Holm step-down familywise-error correction",
                "Benjamini-Hochberg false-discovery-rate correction",
            ],
            "adjusted_datasets_verified": len(self.rows),
            "all_complete_tables_reconstructed": True,
            "confirmatory_family_exact": True,
            "raw_p_values_preserved": True,
            "source_files": [
                {
                    "path": str(path),
                    "sha256": sha256_file(path),
                }
                for path in sorted(self.sources)
            ],
            "output_files": [
                {
                    "path": str(path),
                    "sha256": sha256_file(path),
                }
                for path in sorted(self.outputs)
            ],
            "dataset_checks": self.rows,
            "phase1_modified": False,
            "source_release_modified": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase2",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    qa = phase2 / "qa"
    output_json = qa / "independent_multiple_testing_audit.json"
    output_csv = qa / "independent_multiple_testing_audit_checks.csv"
    try:
        audit = MultiplicityAudit(phase2)
        payload = audit.build_and_verify()
        atomic_json(output_json, payload)
        atomic_csv(
            output_csv,
            payload["dataset_checks"],
            [
                "dataset_id",
                "status",
                "rows",
                "testing_families",
                "methods",
                "output_path",
                "output_sha256",
            ],
        )
        print(json.dumps(payload, indent=2))
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "created_utc": utc_now(),
            "audit_version": "independent_global_multiplicity_v1_20260727",
            "estimate_blind": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "phase1_modified": False,
            "source_release_modified": False,
        }
        atomic_json(output_json, failure)
        print(json.dumps(failure, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
