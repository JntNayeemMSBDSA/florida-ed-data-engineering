#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/03b_outcome_specific_policy_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Deterministic unit tests for confirmatory outcome-sample policy."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    scripts = Path(__file__).resolve().parent
    matrix = load_module(
        "phase2_matrix_policy",
        scripts / "07_prepare_primary_model_matrix.py",
    )
    inference = load_module(
        "phase2_multiple_testing_policy",
        scripts / "16_apply_multiple_testing.py",
    )
    payer = load_module(
        "phase2_payer_heterogeneity",
        scripts / "19b_payer_category_heterogeneity.py",
    )
    descriptive = load_module(
        "phase2_descriptive",
        scripts / "06_descriptive_analysis.py",
    )
    expected = {
        "common_primary": (
            {
                "los_hours_primary_0_168",
                "total_charge_reported_real_2024",
            },
            {
                "los_hours_primary_0_168",
                "total_charge_reported_real_2024",
            },
        ),
        "los_outcome": (
            {"los_hours_primary_0_168"},
            {"los_hours_primary_0_168"},
        ),
        "charge_outcome": (
            {"total_charge_reported_real_2024"},
            {"total_charge_reported_real_2024"},
        ),
    }
    checks: list[dict[str, Any]] = []
    for policy, (expected_filter, expected_primary) in expected.items():
        filter_outcomes, primary_outcomes, model_outcomes = (
            matrix.analysis_sample_spec(policy)
        )
        passed = (
            set(filter_outcomes) == expected_filter
            and set(primary_outcomes) == expected_primary
            and (
                set(model_outcomes) == expected_primary
                if policy != "common_primary"
                else set(model_outcomes).issuperset(expected_primary)
            )
        )
        checks.append(
            {
                "check": f"matrix_policy_{policy}",
                "passed": passed,
            }
        )
    eligibility_expectations = {
        ("race", "primary"): "race_primary_eligible_t50_flag",
        ("sex_gender", "primary"): "sex_gender_primary_eligible_flag",
        (
            "race",
            "race_direct_plus_unique_license_nh_t50",
        ): "unique_fl_license_crosswalk",
        (
            "race",
            "race_only_direct_t50",
        ): "race_pair_defined_race_only_flag",
    }
    for (cohort, policy), required_text in eligibility_expectations.items():
        plain, aliased = matrix.eligibility_filters(cohort, policy)
        checks.append(
            {
                "check": f"eligibility_{cohort}_{policy}",
                "passed": (
                    required_text in plain
                    and "c." in aliased
                    and required_text in aliased
                ),
            }
        )
    sex_plain, sex_aliased = matrix.eligibility_filters(
        "sex_gender", "primary"
    )
    checks.append(
        {
            "check": "sex_gender_primary_uses_recorded_provider_sources",
            "passed": (
                "physician_gender_source IN" in sex_plain
                and "c.physician_gender_source IN" in sex_aliased
                and all(
                    source in sex_plain
                    for source in matrix.RECORDED_PHYSICIAN_GENDER_SOURCES
                )
                and "SSA first-name imputation" not in sex_plain
            ),
        }
    )

    def primary_model_columns(
        spec: list[dict[str, str]],
        cohort: str,
    ) -> dict[str, list[str]]:
        names = [item["name"] for item in spec]
        groups = [item["group"] for item in spec]
        absorbed = (
            "physician_black_proxy"
            if cohort == "race"
            else "physician_female"
        )
        return {
            "m1": [
                name
                for name, group in zip(names, groups)
                if group
                in (
                    "intercept",
                    "exposure",
                    "primary_interaction",
                    "patient_visit",
                    "patient_risk",
                )
            ],
            "m2": [
                name
                for name, group in zip(names, groups)
                if group
                not in (
                    "intercept",
                    "sensitivity_exposure",
                    "sensitivity_interaction",
                    "selection_only",
                )
                and not group.startswith("heterogeneity_")
                and group != "intersectional"
            ],
            "m3": [
                name
                for name, group in zip(names, groups)
                if group != "intercept"
                and group
                not in (
                    "sensitivity_exposure",
                    "sensitivity_interaction",
                    "selection_only",
                )
                and not group.startswith("heterogeneity_")
                and group != "intersectional"
                and name != absorbed
                and (
                    group != "physician"
                    or name
                    in (
                        "log1p_physician_quarter_volume",
                        "physician_quarter_volume_missing",
                    )
                )
            ],
        }

    for cohort in ("race", "sex_gender"):
        full_spec = matrix.build_design_spec(
            cohort,
            ["elix_test_flag"],
        )
        reduced_spec = matrix.primary_sequence_design_spec(full_spec)
        checks.append(
            {
                "check": (
                    f"storage_reduced_design_preserves_primary_models_{cohort}"
                ),
                "passed": (
                    primary_model_columns(full_spec, cohort)
                    == primary_model_columns(reduced_spec, cohort)
                ),
            }
        )
        subjectivity_groups = {
            item["name"]: item["group"] for item in full_spec
            if (
                item["name"] == "presentation_subjectivity_classified"
                or item["name"].startswith("classified_subjectivity_high")
            )
        }
        checks.append(
            {
                "check": (
                    f"classified_subjectivity_design_is_explicit_{cohort}"
                ),
                "passed": (
                    subjectivity_groups.get(
                        "presentation_subjectivity_classified"
                    )
                    == "selection_only"
                    and set(
                        name
                        for name, group in subjectivity_groups.items()
                        if group
                        == "heterogeneity_classified_subjectivity_high"
                    )
                    == {
                        "classified_subjectivity_high",
                        "classified_subjectivity_high_x_physician",
                        "classified_subjectivity_high_x_patient",
                        "classified_subjectivity_high_x_interaction",
                    }
                ),
            }
        )
        if cohort == "sex_gender":
            design_groups = {
                item["name"]: item["group"] for item in full_spec
            }
            checks.append(
                {
                    "check": (
                        "sex_gender_recorded_source_conflict_selection_is_"
                        "explicit"
                    ),
                    "passed": (
                        design_groups.get(
                            "physician_gender_source_no_conflict"
                        )
                        == "selection_only"
                    ),
                }
            )

    rows = [
        {
            "cohort": "race",
            "model_id": "m2_fully_adjusted_facility_yq_clinical_fe",
            "outcome": "los_hours_primary_0_168",
            "analysis_sample_policy": "los_outcome",
        },
        {
            "cohort": "race",
            "model_id": "m2_fully_adjusted_facility_yq_clinical_fe",
            "outcome": "total_charge_reported_real_2024",
            "analysis_sample_policy": "charge_outcome",
        },
        {
            "cohort": "race",
            "model_id": "m2_fully_adjusted_facility_yq_clinical_fe",
            "outcome": "los_hours_primary_0_168",
            "analysis_sample_policy": "common_primary",
        },
        {
            "cohort": "sex_gender",
            "model_id": "m2_fully_adjusted_facility_yq_clinical_fe",
            "outcome": "los_hours_primary_0_168",
            "analysis_sample_policy": "los_outcome",
        },
    ]
    families = [
        inference.family_for(pd.Series(row)) for row in rows
    ]
    checks.extend(
        [
            {
                "check": "race_los_outcome_specific_is_confirmatory",
                "passed": families[0]
                == ("confirmatory_race_primary", "holm"),
            },
            {
                "check": "race_charge_outcome_specific_is_confirmatory",
                "passed": families[1]
                == ("confirmatory_race_primary", "holm"),
            },
            {
                "check": "common_sample_is_not_confirmatory",
                "passed": families[2][0]
                != "confirmatory_race_primary",
            },
            {
                "check": "sex_gender_is_secondary",
                "passed": families[3][0]
                != "confirmatory_race_primary",
            },
        ]
    )
    family_fixture = pd.DataFrame(
        {
            "testing_family": ["race", "race", "sex_gender", "sex_gender"],
            "p_value": [0.01, 0.04, 0.02, 0.80],
        }
    )
    family_adjusted = inference.adjust_by_family(
        family_fixture, "testing_family", method="fdr_bh"
    )
    checks.append(
        {
            "check": "bh_adjustment_is_within_labeled_families",
            "passed": bool(
                np.allclose(
                    family_adjusted["adjusted_p_value"].astype(float),
                    np.asarray([0.02, 0.04, 0.04, 0.80]),
                )
            ),
        }
    )
    balance_fixture = pd.DataFrame(
        {
            "cohort_id": ["race_primary_t50"] * 4,
            "variable": ["age_years"] * 4,
            "pair_category": [
                "black_black",
                "black_white",
                "white_black",
                "white_white",
            ],
            "nonmissing_n": [100, 100, 100, 100],
            "mean": [10.0, 8.0, 7.0, 6.0],
            "sd": [2.0, 2.0, 2.0, 2.0],
        }
    )
    smd = descriptive.standardized_balance_contrasts(balance_fixture)
    checks.append(
        {
            "check": "pair_balance_smd_direction_and_formula",
            "passed": bool(
                np.allclose(
                    smd["standardized_mean_difference"].to_numpy(),
                    np.asarray([1.0, 0.5, 1.5, 1.0]),
                )
            ),
        }
    )
    tiny = np.asarray(
        [
            [1, 0, 1, 0, 0],
            [0, 1, 1, 1, 1],
        ],
        dtype=np.float64,
    )
    payer_matrix = payer.InteractionMatrix(
        tiny,
        payer_indices=[0, 1],
        physician_index=2,
        patient_index=3,
        interaction_index=4,
    )
    expected_payer_interactions = np.asarray(
        [
            [1, 0, 0, 0, 0, 0],
            [0, 0, 0, 1, 1, 1],
        ],
        dtype=np.float64,
    )
    checks.append(
        {
            "check": "jointly_saturated_payer_interaction_order",
            "passed": bool(
                np.array_equal(
                    payer_matrix[:, :],
                    expected_payer_interactions,
                )
            ),
        }
    )
    all_passed = all(bool(item["passed"]) for item in checks)
    payload = {
        "test_id": "outcome_specific_primary_policy_unit_tests_v1",
        "checks": checks,
        "all_passed": all_passed,
    }
    qa = scripts.parent / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(checks).to_csv(
        qa / "outcome_specific_policy_unit_tests.csv", index=False
    )
    (
        qa / "outcome_specific_policy_unit_tests.json"
    ).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if not all_passed:
        raise AssertionError(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
