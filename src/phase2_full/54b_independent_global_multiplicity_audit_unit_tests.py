#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/54b_independent_global_multiplicity_audit_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic tests for the independent global multiplicity audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).with_name(
    "54_independent_global_multiplicity_audit.py"
)
SPEC = importlib.util.spec_from_file_location(
    "independent_global_multiplicity_audit",
    SCRIPT,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to import independent multiplicity audit")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def close(actual: np.ndarray, expected: list[float]) -> bool:
    return bool(
        np.allclose(
            actual,
            np.asarray(expected, dtype=float),
            rtol=1e-12,
            atol=1e-14,
            equal_nan=True,
        )
    )


def main() -> None:
    tests: list[dict[str, object]] = []

    p = pd.Series([0.01, 0.04, 0.03, 0.002])
    bh, bh_reject = MODULE.benjamini_hochberg(p)
    tests.append(
        {
            "test": "benjamini_hochberg_reference",
            "passed": close(bh, [0.02, 0.04, 0.04, 0.008])
            and bh_reject.tolist() == [True, True, True, True],
        }
    )

    holm, holm_reject = MODULE.holm(p)
    tests.append(
        {
            "test": "holm_reference",
            "passed": close(holm, [0.03, 0.06, 0.06, 0.008])
            and holm_reject.tolist() == [True, False, False, True],
        }
    )

    missing, missing_reject = MODULE.benjamini_hochberg(
        pd.Series([0.01, np.nan, 0.20])
    )
    tests.append(
        {
            "test": "missing_p_values_excluded",
            "passed": close(missing, [0.02, np.nan, 0.20])
            and missing_reject.tolist() == [True, False, False],
        }
    )

    grouped = pd.DataFrame(
        {
            "testing_family": ["a", "a", "b", "b"],
            "p_value": [0.01, 0.20, 0.01, 0.20],
        }
    )
    grouped_adjusted = MODULE.apply_adjustment(grouped)
    tests.append(
        {
            "test": "families_adjusted_separately",
            "passed": close(
                grouped_adjusted["adjusted_p_value"].to_numpy(dtype=float),
                [0.02, 0.20, 0.02, 0.20],
            ),
        }
    )

    confirmatory = pd.Series(
        {
            "cohort": "race",
            "model_id": "m2_fully_adjusted_facility_yq_clinical_fe",
            "outcome": "los_hours_primary_0_168",
            "analysis_sample_policy": "los_outcome",
        }
    )
    robustness = confirmatory.copy()
    robustness["analysis_sample_policy"] = "common_primary"
    tests.append(
        {
            "test": "confirmatory_family_is_outcome_specific_only",
            "passed": MODULE.primary_family(confirmatory)
            == ("confirmatory_race_primary", "holm")
            and MODULE.primary_family(robustness)[0]
            == (
                "secondary_race_m2_fully_adjusted_facility_yq_clinical_fe_"
                "common_sample_primary_robustness"
            ),
        }
    )

    expected = MODULE.apply_adjustment(
        pd.DataFrame(
            {
                "testing_family": ["a", "a"],
                "p_value": [0.01, 0.20],
            }
        )
    )
    actual = MODULE.csv_roundtrip(expected)
    exact_pass = True
    try:
        MODULE.compare_complete_frames(actual, expected)
    except AssertionError:
        exact_pass = False
    actual.loc[0, "adjusted_p_value"] = 0.99
    tamper_detected = False
    try:
        MODULE.compare_complete_frames(actual, expected)
    except AssertionError:
        tamper_detected = True
    tests.append(
        {
            "test": "complete_table_comparison_detects_tampering",
            "passed": exact_pass and tamper_detected,
        }
    )

    passed = sum(bool(test["passed"]) for test in tests)
    payload = {
        "status": "PASS" if passed == len(tests) else "FAIL",
        "tests_passed": passed,
        "tests_total": len(tests),
        "tests": tests,
    }
    output = SCRIPT.parents[1] / "qa" / (
        "independent_multiple_testing_audit_unit_tests.json"
    )
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
