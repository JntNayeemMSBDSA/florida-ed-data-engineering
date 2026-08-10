#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/46b_directional_measurement_sensitivity_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Estimate-blind tests for directional race-measurement sensitivities."""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "directional_measurement_sensitivity_under_test", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            default=lambda value: (
                value.item() if isinstance(value, np.generic) else str(value)
            ),
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    module = load_module(
        phase2
        / "scripts"
        / "47_estimate_directional_measurement_sensitivities.py"
    )
    checks = []

    race_cells = [
        {
            "cell_id": f"physician={physician}|patient={patient}",
            "physician_group": physician,
            "patient_group": patient,
        }
        for physician in module.RACES
        for patient in module.RACES
    ]
    cell_context, mapping, contexts = module.context_map(
        race_cells, "race_dyads"
    )
    checks.append(
        {
            "check_id": "race_context_complete",
            "passed": (
                mapping.shape == (5, 5)
                and len(contexts) == 5
                and len(np.unique(mapping)) == 25
            ),
        }
    )
    probabilities = np.array(
        [
            [0.70, 0.10, 0.10, 0.05, 0.05],
            [0.10, 0.60, 0.10, 0.10, 0.10],
            [0.10, 0.10, 0.60, 0.10, 0.10],
        ],
        dtype=np.float64,
    )
    physicians = np.array([0, 1, 2, 0, 1], dtype=np.int64)
    row_context = np.array([0, 1, 2, 3, 4], dtype=np.int64)
    indices, weights = module.cell_indices_and_weights(
        row_context, physicians, mapping, probabilities, None
    )
    basis = np.zeros((len(row_context), 25), dtype=np.float64)
    basis[np.arange(len(row_context))[:, None], indices] = weights
    recovered = module.derive_context(basis, cell_context, len(contexts))
    checks.append(
        {
            "check_id": "probability_basis_sums_and_context_recovers",
            "passed": (
                np.allclose(basis.sum(axis=1), 1.0)
                and np.array_equal(recovered, row_context)
            ),
        }
    )
    assignment = np.array([0, 1, 2], dtype=np.uint8)
    hard_indices, hard_weights = module.cell_indices_and_weights(
        row_context, physicians, mapping, None, assignment
    )
    checks.append(
        {
            "check_id": "hard_assignment_one_cell_per_row",
            "passed": (
                hard_indices.shape == (5, 1)
                and np.array_equal(hard_weights, np.ones((5, 1)))
                and np.array_equal(
                    hard_indices[:, 0],
                    mapping[row_context, assignment[physicians]],
                )
            ),
        }
    )
    npis = ["1000000001", "1000000002", "1000000003"]
    draw1 = module.categorical_assignments(
        npis, probabilities, 20260726, "aamc_fl", 1
    )
    draw1_repeat = module.categorical_assignments(
        npis, probabilities, 20260726, "aamc_fl", 1
    )
    draw2 = module.categorical_assignments(
        npis, probabilities, 20260726, "aamc_fl", 2
    )
    checks.append(
        {
            "check_id": "npi_assignment_deterministic_and_imputation_specific",
            "passed": (
                np.array_equal(draw1, draw1_repeat)
                and not np.array_equal(
                    np.array(
                        [
                            module.stable_uniform(
                                20260726, "aamc_fl", 1, npi
                            )
                            for npi in npis
                        ]
                    ),
                    np.array(
                        [
                            module.stable_uniform(
                                20260726, "aamc_fl", 2, npi
                            )
                            for npi in npis
                        ]
                    ),
                )
                and np.isin(draw2, np.arange(5)).all()
            ),
        }
    )

    base = np.arange(30, dtype=np.float64).reshape(5, 6)
    cells = np.arange(15, dtype=np.float64).reshape(5, 3)
    combined = module.CombinedMatrix(cells, base, 3)
    expected_combined = np.column_stack((cells, base[:, 3:]))
    checks.append(
        {
            "check_id": "combined_matrix_exact",
            "passed": np.array_equal(
                combined[1:4, :], expected_combined[1:4, :]
            ),
        }
    )

    component_rows = []
    for imputation in range(1, 21):
        component_rows.append(
            {
                "family_id": "race_dyads",
                "outcome": "synthetic",
                "measurement_specification": "aamc_fl_npi_mi",
                "model_id": "M2_DIRECTIONAL",
                "target_type": "planned_contrast",
                "target_id": "c1",
                "contrast_family": "synthetic_family",
                "imputation": imputation,
                "estimate": 1.0 + imputation / 100.0,
                "variance": 0.04,
                "identified": True,
                "variance_valid": True,
                "support_pass": True,
                "limited_support_flag": False,
            }
        )
    pooled = module.pool_mi(pd.DataFrame(component_rows), 20).iloc[0]
    expected_mean = np.mean(
        [1.0 + imputation / 100.0 for imputation in range(1, 21)]
    )
    expected_between = np.var(
        [1.0 + imputation / 100.0 for imputation in range(1, 21)],
        ddof=1,
    )
    expected_variance = 0.04 + 1.05 * expected_between
    checks.append(
        {
            "check_id": "rubin_pooling_exact",
            "passed": (
                math.isclose(pooled["estimate"], expected_mean, abs_tol=1e-12)
                and math.isclose(
                    pooled["variance"], expected_variance, abs_tol=1e-12
                )
                and pooled["imputations_completed"] == 20
            ),
        }
    )

    accumulator = module.SupportAccumulator(3, 2, 2)
    accumulator.add(
        np.array([[0], [0], [1], [1]], dtype=np.int64),
        np.ones((4, 1)),
        np.array([0, 1, 1, 2], dtype=np.int64),
        np.array([0, 0, 1, 1], dtype=np.int64),
        np.array([1.0, 2.0, 3.0, 4.0]),
    )
    support = accumulator.frame(["cell0", "cell1"])
    checks.append(
        {
            "check_id": "support_moments_exact",
            "passed": (
                np.array_equal(
                    support["weighted_visit_mass"].to_numpy(), [2.0, 2.0]
                )
                and np.array_equal(
                    support["distinct_physicians_positive_mass"].to_numpy(),
                    [2, 2],
                )
                and np.allclose(
                    support["weighted_outcome_mean"].to_numpy(), [1.5, 3.5]
                )
            ),
        }
    )

    # Synthetic end-to-end check of the storage optimization: demeaning only
    # replacement cell columns and joining them to already-demeaned,
    # measurement-invariant covariates must equal demeaning the full replaced
    # matrix in one pass.
    engine = module.load_module(
        phase2 / "scripts" / "08_estimate_primary_models.py",
        "synthetic_measurement_sensitivity_demeaning_engine",
    )
    estimator = module.load_module(
        phase2 / "scripts" / "41_estimate_directional_models.py",
        "synthetic_measurement_sensitivity_estimator",
    )
    rng = np.random.default_rng(20260726)
    n = 2400
    q = 25
    covariates = 4
    patient_context = rng.integers(0, 5, size=n)
    physician_code = rng.integers(0, 60, size=n)
    facility_code = rng.integers(0, 24, size=n)
    primary_probabilities = rng.dirichlet(np.ones(5) * 2, size=60)
    national_probabilities = rng.dirichlet(np.ones(5) * 2, size=60)
    primary_cells = np.zeros((n, q), dtype=np.float64)
    national_cells = np.zeros((n, q), dtype=np.float64)
    for race in range(5):
        primary_cells[
            np.arange(n), mapping[patient_context, race]
        ] = primary_probabilities[physician_code, race]
        national_cells[
            np.arange(n), mapping[patient_context, race]
        ] = national_probabilities[physician_code, race]
    invariant = rng.normal(size=(n, covariates))
    primary_design = np.column_stack((primary_cells, invariant))
    national_design = np.column_stack((national_cells, invariant))
    outcome_values = (
        national_cells[:, 0]
        - national_cells[:, 6]
        + invariant @ np.array([0.4, -0.2, 0.1, 0.3])
        + rng.normal(scale=0.5, size=n)
    )[:, None]
    facility_yq = facility_code * 4 + rng.integers(0, 4, size=n)
    clinical = rng.integers(0, 20, size=n)
    fe_codes_array = np.column_stack(
        (physician_code, facility_yq, clinical)
    ).astype(np.uint64)
    physician_facility = (
        physician_code * (facility_code.max() + 1) + facility_code
    )
    cluster_array = np.column_stack(
        (physician_code, facility_code, physician_facility)
    ).astype(np.uint64)
    with tempfile.TemporaryDirectory(
        prefix="directional_measurement_test_"
    ) as temporary:
        root = Path(temporary)

        def mmap(name: str, values: np.ndarray) -> np.memmap:
            result = np.memmap(
                root / name,
                dtype=values.dtype,
                mode="w+",
                shape=values.shape,
            )
            result[:] = values
            result.flush()
            return result

        raw_primary = mmap("primary.float64.mmap", primary_design)
        raw_national = mmap("national.float64.mmap", national_design)
        raw_cells = mmap("cells.float64.mmap", national_cells)
        raw_outcome = mmap("outcome.float64.mmap", outcome_values)
        raw_fe = mmap("fe.uint64.mmap", fe_codes_array)
        raw_clusters = mmap("clusters.uint64.mmap", cluster_array)
        base_tilde, base_y, _ = engine.residualize(
            raw_primary,
            raw_outcome,
            raw_fe,
            list(range(q + covariates)),
            [1, 2],
            root / "base",
            4,
            1e-10,
            {"synthetic": "base"},
        )
        cells_tilde, _, _ = engine.residualize(
            raw_cells,
            raw_outcome,
            raw_fe,
            list(range(q)),
            [1, 2],
            root / "cells",
            4,
            1e-10,
            {"synthetic": "cells"},
        )
        full_tilde, full_y, _ = engine.residualize(
            raw_national,
            raw_outcome,
            raw_fe,
            list(range(q + covariates)),
            [1, 2],
            root / "full",
            4,
            1e-10,
            {"synthetic": "full"},
        )
        combined_matrix = module.CombinedMatrix(cells_tilde, base_tilde, q)
        joined_difference = 0.0
        for start in range(0, n, 211):
            stop = min(n, start + 211)
            joined_difference = max(
                joined_difference,
                float(
                    np.max(
                        np.abs(
                            combined_matrix[start:stop, :]
                            - full_tilde[start:stop, :]
                        )
                    )
                ),
            )
        fit_combined = estimator.fit_model(
            "synthetic_combined",
            combined_matrix,
            base_y,
            raw_clusters,
            257,
        )
        fit_full = estimator.fit_model(
            "synthetic_full",
            full_tilde,
            full_y,
            raw_clusters,
            257,
        )
        beta_difference = float(
            np.max(np.abs(fit_combined["beta"] - fit_full["beta"]))
        )
        covariance_difference = float(
            np.max(
                np.abs(
                    fit_combined["covariance"] - fit_full["covariance"]
                )
            )
        )
        del (
            fit_combined,
            fit_full,
            combined_matrix,
            base_tilde,
            base_y,
            cells_tilde,
            full_tilde,
            full_y,
            raw_primary,
            raw_national,
            raw_cells,
            raw_outcome,
            raw_fe,
            raw_clusters,
        )
        gc.collect()
    checks.append(
        {
            "check_id": "optimized_cell_replacement_matches_full_refit",
            "passed": (
                joined_difference <= 1e-10
                and beta_difference <= 1e-9
                and covariance_difference <= 1e-8
            ),
        }
    )

    failures = [
        item["check_id"] for item in checks if not bool(item["passed"])
    ]
    payload = {
        "status": "PASS" if not failures else "FAIL",
        "test_id": "directional_measurement_sensitivity_tests_v1",
        "checks": checks,
        "checks_passed": len(checks) - len(failures),
        "checks_total": len(checks),
        "failures": failures,
        "real_result_values_read": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output = (
        phase2 / "qa" / "directional_measurement_sensitivity_tests.json"
    )
    atomic_json(output, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "checks_passed": payload["checks_passed"],
                "checks_total": payload["checks_total"],
                "failures": failures,
                "real_result_values_emitted": False,
            },
            indent=2,
        )
    )
    if failures:
        raise SystemExit("Directional measurement sensitivity tests failed")


if __name__ == "__main__":
    main()
