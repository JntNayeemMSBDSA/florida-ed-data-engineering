#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/03_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Deterministic hand-constructed tests for locked Phase 2 definitions."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests


def race_pair(patient_black: int, physician_black: int) -> str:
    mapping = {
        (1, 1): "black_black",
        (0, 1): "black_white",
        (1, 0): "white_black",
        (0, 0): "white_white",
    }
    return mapping[(patient_black, physician_black)]


def sex_gender_pair(patient_female: int, physician_female: int) -> str:
    mapping = {
        (1, 1): "female_female",
        (0, 1): "female_male",
        (1, 0): "male_female",
        (0, 0): "male_male",
    }
    return mapping[(patient_female, physician_female)]


def los_hours(days: float, arrival: int | None, discharge: int | None) -> float:
    if arrival is None or discharge is None:
        return np.nan
    if not (0 <= arrival <= 23 and 0 <= discharge <= 23):
        return np.nan
    value = 24.0 * days + discharge - arrival
    return value if value >= 0 else np.nan


def icd9_ami_strict(code: str) -> bool:
    return bool(re.fullmatch(r"410[0-9]1", code))


def icd9_ami_broad_initial(code: str) -> bool:
    return bool(re.fullmatch(r"410[0-9][01]", code))


def icd10_ami_primary(code: str) -> bool:
    return bool(re.match(r"^I21(?:[0-4]|9)", code))


def source_ami_primary_count(
    year: int,
    quarter: int,
    icd9_count: int,
    icd10_count: int,
) -> int:
    """Apply the U.S. ICD-10-CM transition at 2015 Q4."""
    use_icd9 = year < 2015 or (year == 2015 and quarter <= 3)
    return icd9_count if use_icd9 else icd10_count


def symptom_sign_coded(code_system: str, code: str) -> bool:
    if code_system == "ICD-9-CM":
        return len(code) >= 3 and code[:3].isdigit() and 780 <= int(code[:3]) <= 799
    if code_system == "ICD-10-CM":
        return code.startswith("R")
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    tests: list[dict[str, object]] = []

    race_expected = {
        (1, 1): "black_black",
        (0, 1): "black_white",
        (1, 0): "white_black",
        (0, 0): "white_white",
    }
    race_observed = {key: race_pair(*key) for key in race_expected}
    assert race_observed == race_expected
    tests.append(
        {
            "test": "physician_first_race_pair_order",
            "status": "PASS",
            "detail": str(race_observed),
        }
    )

    sex_expected = {
        (1, 1): "female_female",
        (0, 1): "female_male",
        (1, 0): "male_female",
        (0, 0): "male_male",
    }
    sex_observed = {key: sex_gender_pair(*key) for key in sex_expected}
    assert sex_observed == sex_expected
    tests.append(
        {
            "test": "physician_first_sex_gender_pair_order",
            "status": "PASS",
            "detail": str(sex_observed),
        }
    )

    means = np.array([10.0, 8.0, 7.0, 6.0])
    contrast = np.array([1.0, -1.0, -1.0, 1.0])
    estimate = float(contrast @ means)
    assert estimate == 1.0
    vcov = np.diag([0.04, 0.09, 0.16, 0.25])
    variance = float(contrast @ vcov @ contrast)
    assert np.isclose(variance, 0.54)
    tests.append(
        {
            "test": "four_cell_contrast_and_vcov",
            "status": "PASS",
            "detail": f"estimate={estimate}; variance={variance}",
        }
    )

    assert los_hours(0, 10, 14) == 4.0
    assert los_hours(1, 22, 2) == 4.0
    assert np.isnan(los_hours(0, 22, 2))
    assert np.isnan(los_hours(0, 10, 99))
    tests.append(
        {
            "test": "clock_los_rule",
            "status": "PASS",
            "detail": "valid same-day and overnight examples; negative and 99 invalid",
        }
    )

    assert icd9_ami_strict("41001")
    assert icd9_ami_strict("41091")
    assert not icd9_ami_strict("41090")
    assert not icd9_ami_strict("41092")
    assert icd9_ami_broad_initial("41090")
    assert icd9_ami_broad_initial("41091")
    assert not icd9_ami_broad_initial("41092")
    assert icd10_ami_primary("I210")
    assert icd10_ami_primary("I214")
    assert icd10_ami_primary("I219")
    assert not icd10_ami_primary("I21A1")
    assert not icd10_ami_primary("I220")
    tests.append(
        {
            "test": "ami_code_rules",
            "status": "PASS",
            "detail": "ICD-9 episode digit and ICD-10 primary family boundaries",
        }
    )

    transition_counts = [
        source_ami_primary_count(2015, 3, 31, 7),
        source_ami_primary_count(2015, 4, 29, 11),
        source_ami_primary_count(2016, 1, 23, 13),
    ]
    assert transition_counts == [31, 11, 13]
    assert sum(transition_counts[:2]) == 42
    tests.append(
        {
            "test": "ami_2015_q4_icd10_transition",
            "status": "PASS",
            "detail": (
                "2015 Q1-Q3 use ICD-9-CM; 2015 Q4 and later use ICD-10-CM; "
                "annual 2015 totals therefore combine both systems"
            ),
        }
    )

    assert symptom_sign_coded("ICD-9-CM", "7802")
    assert symptom_sign_coded("ICD-9-CM", "7999")
    assert not symptom_sign_coded("ICD-9-CM", "7799")
    assert symptom_sign_coded("ICD-10-CM", "R0602")
    assert not symptom_sign_coded("ICD-10-CM", "I219")
    tests.append(
        {
            "test": "symptom_sign_code_rule",
            "status": "PASS",
            "detail": "ICD-9 780-799 and ICD-10 R00-R99",
        }
    )

    nominal = 100.0
    quarter_index = 200.0
    reference_index = 250.0
    real = nominal * reference_index / quarter_index
    assert real == 125.0
    tests.append(
        {
            "test": "cpi_constant_dollar_formula",
            "status": "PASS",
            "detail": "100 * 250 / 200 = 125",
        }
    )

    pvalues = np.array([0.001, 0.01, 0.04, 0.20])
    bh = multipletests(pvalues, method="fdr_bh")[1]
    holm = multipletests(pvalues, method="holm")[1]
    assert np.allclose(bh, np.array([0.004, 0.02, 0.05333333333333334, 0.2]))
    assert np.allclose(holm, np.array([0.004, 0.03, 0.08, 0.2]))
    tests.append(
        {
            "test": "multiple_testing_reference_values",
            "status": "PASS",
            "detail": f"BH={bh.tolist()}; Holm={holm.tolist()}",
        }
    )

    pd.DataFrame(tests).to_csv(
        args.output / "definition_unit_tests.csv", index=False
    )
    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "tests_run": len(tests),
        "tests_passed": len(tests),
        "all_passed": True,
        "deterministic": True,
    }
    (args.output / "definition_unit_tests.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
