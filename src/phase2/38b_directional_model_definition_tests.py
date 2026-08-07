#!/usr/bin/env python3
# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/38b_directional_model_definition_tests.py
# This copy contains definitions and synthetic tests, not fitted results.

"""Synthetic tests for the frozen directional model definitions."""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    manifest_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Model_Implementation_FROZEN.json"
    )
    gate_path = (
        phase2 / "qa" / "directional_model_implementation_pre_estimation_gate.json"
    )
    extension_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    extension = json.loads(extension_path.read_text(encoding="utf-8"))
    checks: list[dict[str, object]] = []

    def add(check_id: str, passed: bool, evidence: object) -> None:
        checks.append(
            {"check_id": check_id, "passed": bool(passed), "evidence": evidence}
        )

    add(
        "implementation_gate_is_estimate_blind",
        (
            manifest.get("status") == "FROZEN_ESTIMATE_BLIND_PASS"
            and gate.get("estimate_blind") is True
            and gate.get("model_estimate_interpretation_authorized") is False
        ),
        gate,
    )
    counts = {
        family: len(spec["cells"])
        for family, spec in extension["analysis_families"].items()
    }
    add(
        "frozen_cell_counts",
        counts
        == {
            "gender_dyads": 4,
            "race_dyads": 25,
            "intersectional_dyads": 100,
        },
        counts,
    )
    contrast_counts = {
        family: len(spec["contrasts"])
        for family, spec in extension["analysis_families"].items()
    }
    add(
        "frozen_contrast_counts",
        contrast_counts
        == {
            "gender_dyads": 6,
            "race_dyads": 68,
            "intersectional_dyads": 359,
        },
        contrast_counts,
    )

    rng = np.random.default_rng(20260726)
    posterior = rng.dirichlet(np.ones(5))
    patient = 3
    race_cells = np.zeros((5, 5), dtype=float)
    race_cells[:, patient] = posterior
    add(
        "race_probability_cells_sum_to_one",
        math.isclose(float(race_cells.sum()), 1.0, abs_tol=1e-12),
        float(race_cells.sum()),
    )
    physician_gender = 1
    patient_sex = 0
    inter = np.zeros((5, 2, 5, 2), dtype=float)
    inter[:, physician_gender, patient, patient_sex] = posterior
    add(
        "intersectional_probability_cells_sum_to_one",
        math.isclose(float(inter.sum()), 1.0, abs_tol=1e-12),
        float(inter.sum()),
    )
    gender = np.zeros((2, 2), dtype=float)
    gender[physician_gender, patient_sex] = 1.0
    add(
        "gender_cells_are_mutually_exclusive",
        math.isclose(float(gender.sum()), 1.0, abs_tol=1e-12),
        gender.tolist(),
    )

    k = 25
    beta = rng.normal(size=k)
    cbar = rng.dirichlet(np.ones(k))
    target = np.zeros(k)
    target[7] = 1.0
    base_prediction = float((target - cbar) @ beta)
    shifted_prediction = float((target - cbar) @ (beta + 17.0))
    add(
        "anchored_prediction_is_common_level_invariant",
        math.isclose(
            base_prediction, shifted_prediction, abs_tol=1e-10
        ),
        {
            "base": base_prediction,
            "shifted": shifted_prediction,
        },
    )
    a = rng.normal(size=(k, k))
    covariance = a @ a.T
    variance = float((target - cbar) @ covariance @ (target - cbar))
    add(
        "anchored_prediction_variance_nonnegative_for_psd_vcov",
        variance >= -1e-10,
        variance,
    )
    contrast_sum_errors = []
    for family, spec in extension["analysis_families"].items():
        for contrast in spec["contrasts"]:
            total = sum(
                float(part["weight"])
                for part in contrast["linear_combination"]
            )
            if not math.isclose(total, 0.0, abs_tol=1e-12):
                contrast_sum_errors.append(
                    f"{family}:{contrast['contrast_id']}:{total}"
                )
    add(
        "all_pairwise_contrast_weights_sum_to_zero",
        not contrast_sum_errors,
        contrast_sum_errors,
    )

    npis = np.array(["A", "A", "B", "B", "B", "C"])
    draws = {
        npi: int(rng.choice(5, p=rng.dirichlet(np.ones(5))))
        for npi in np.unique(npis)
    }
    visit_draws = np.array([draws[npi] for npi in npis])
    npi_consistent = all(
        len(set(visit_draws[npis == npi].tolist())) == 1
        for npi in np.unique(npis)
    )
    add(
        "npi_level_mi_draw_is_constant_across_visits",
        npi_consistent,
        {"draws": draws, "visit_draws": visit_draws.tolist()},
    )
    add(
        "m3_absolute_cell_predictions_prohibited",
        "not absolute physician-group cells"
        in manifest["adjusted_prediction"]["M3_policy"],
        manifest["adjusted_prediction"]["M3_policy"],
    )
    add(
        "primary_outcomes_preserved",
        manifest["outcomes"][
            "frozen_primary_outcome_definitions_secondary_directional_use"
        ]
        == ["los_hours_primary_0_168", "total_charge_reported_real_2024"],
        manifest["outcomes"][
            "frozen_primary_outcome_definitions_secondary_directional_use"
        ],
    )
    status = "PASS" if all(c["passed"] for c in checks) else "FAIL"
    payload = {
        "test_id": "directional_model_definition_tests_v1",
        "created_utc": utc_now(),
        "status": status,
        "checks_passed": sum(c["passed"] for c in checks),
        "checks_total": len(checks),
        "checks": checks,
        "synthetic_only": True,
        "real_outcome_estimates_read": False,
    }
    output = phase2 / "qa" / "directional_model_definition_tests.json"
    atomic_json(output, payload)
    print(json.dumps(payload, indent=2))
    if status != "PASS":
        raise RuntimeError(f"Directional definition tests failed: {output}")


if __name__ == "__main__":
    main()
