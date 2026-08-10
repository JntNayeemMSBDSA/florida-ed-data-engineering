#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/03e_inference_engine_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Reference tests for the production OLS/HDFE and clustered-inference engine.

All inputs are synthetic. No Florida encounter data or real-data estimates are
read. The tests compare production calculations with independent NumPy,
explicit-dummy OLS, and statsmodels reference implementations.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib.util
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import statsmodels.api as sm
from statsmodels.stats.sandwich_covariance import cov_cluster_2groups


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_engine(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "phase2_inference_engine_under_test", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load inference engine: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(
    rows: list[dict[str, Any]],
    test_id: str,
    observed: Any,
    expected: Any,
    tolerance: float,
    passed: bool,
) -> None:
    rows.append(
        {
            "test_id": test_id,
            "observed": json.dumps(observed, default=str),
            "expected": json.dumps(expected, default=str),
            "tolerance": tolerance,
            "passed": bool(passed),
        }
    )
    if not passed:
        raise AssertionError(f"Inference engine test failed: {test_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    engine_path = phase2 / "scripts" / "08_estimate_primary_models.py"
    engine = load_engine(engine_path)
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(20260726)

    # 1. OLS point estimates and the four-cell interaction parameterization.
    repeats = 60
    physician_black = np.repeat([0, 0, 1, 1], repeats)
    patient_black = np.repeat([0, 1, 0, 1], repeats)
    interaction = physician_black * patient_black
    design = np.column_stack(
        [
            np.ones(len(interaction)),
            physician_black,
            patient_black,
            interaction,
        ]
    ).astype(np.float64)
    cell_means = {
        (0, 0): 5.0,
        (0, 1): 7.0,
        (1, 0): 8.0,
        (1, 1): 11.0,
    }
    outcome = np.array(
        [
            cell_means[(int(physician), int(patient))]
            for physician, patient in zip(
                physician_black, patient_black
            )
        ],
        dtype=np.float64,
    ) + rng.normal(scale=0.05, size=len(interaction))
    xtx, xty, _, _ = engine.crossproducts(
        design, outcome[:, None], row_chunk=37
    )
    production_beta = np.linalg.solve(xtx, xty)[:, 0]
    reference_beta = np.linalg.lstsq(design, outcome, rcond=None)[0]
    record(
        rows,
        "ols_coefficients_match_numpy_lstsq",
        production_beta.tolist(),
        reference_beta.tolist(),
        1e-11,
        bool(np.allclose(production_beta, reference_beta, atol=1e-11)),
    )
    requested_contrast = (
        cell_means[(1, 1)]
        - cell_means[(1, 0)]
        - cell_means[(0, 1)]
        + cell_means[(0, 0)]
    )
    empirical_cells = {
        key: float(
            outcome[
                (physician_black == key[0])
                & (patient_black == key[1])
            ].mean()
        )
        for key in cell_means
    }
    empirical_contrast = (
        empirical_cells[(1, 1)]
        - empirical_cells[(1, 0)]
        - empirical_cells[(0, 1)]
        + empirical_cells[(0, 0)]
    )
    record(
        rows,
        "interaction_equals_empirical_four_cell_contrast",
        float(production_beta[3]),
        empirical_contrast,
        1e-11,
        bool(np.isclose(production_beta[3], empirical_contrast, atol=1e-11)),
    )
    record(
        rows,
        "synthetic_population_four_cell_contrast_known",
        requested_contrast,
        1.0,
        0.0,
        requested_contrast == 1.0,
    )

    # 2. Collinearity and zero-column detection.
    collinear = np.column_stack(
        [design[:, 0], design[:, 1], 2 * design[:, 1], np.zeros(len(design))]
    )
    col_xtx = collinear.T @ collinear
    keep, dropped, rank, condition = engine.independent_columns(
        col_xtx, ["intercept", "x", "two_x", "zero"]
    )
    record(
        rows,
        "rank_detection_drops_zero_and_one_collinear_column",
        {
            "keep": keep,
            "dropped": dropped,
            "rank": rank,
            "condition": condition,
        },
        {"rank": 2, "dropped_count": 2},
        0.0,
        rank == 2 and len(dropped) == 2 and 3 in dropped,
    )

    # 3. Two-way CRV1 covariance against statsmodels.
    n = 1_000
    x = np.column_stack(
        [
            np.ones(n),
            rng.normal(size=n),
            rng.normal(size=n),
        ]
    )
    physician_cluster = np.repeat(np.arange(50), 20)
    facility_cluster = np.tile(np.arange(20), 50)
    pairs = np.column_stack([physician_cluster, facility_cluster])
    _, intersection_cluster = np.unique(
        pairs, axis=0, return_inverse=True
    )
    clusters = np.column_stack(
        [physician_cluster, facility_cluster, intersection_cluster]
    ).astype(np.uint64)
    y = (
        x @ np.array([1.0, 0.5, -0.25])
        + rng.normal(scale=1.0, size=n)
    )[:, None]
    bread = np.linalg.inv(x.T @ x)
    beta = bread @ x.T @ y
    production_covariances, covariance_meta, wild_a = (
        engine.selected_cluster_covariance(
            x,
            y,
            beta,
            bread,
            clusters,
            [0, 1, 2],
            row_chunk=137,
            seed=1947,
            bootstrap_draws=999,
        )
    )
    reference_fit = sm.OLS(y[:, 0], x).fit()
    reference_covariance = cov_cluster_2groups(
        reference_fit,
        physician_cluster,
        facility_cluster,
        use_correction=True,
    )[0]
    covariance_difference = float(
        np.max(
            np.abs(production_covariances[0] - reference_covariance)
        )
    )
    record(
        rows,
        "two_way_crv1_matches_statsmodels_reference",
        covariance_difference,
        0.0,
        1e-12,
        covariance_difference <= 1e-12,
    )
    record(
        rows,
        "cluster_counts_and_minimum_df_are_correct",
        covariance_meta[0]["cluster_counts"],
        {
            "physician": 50,
            "facility": 20,
            "physician_facility_intersection": 1_000,
        },
        0.0,
        covariance_meta[0]["cluster_counts"]
        == {
            "physician": 50,
            "facility": 20,
            "physician_facility_intersection": 1_000,
        }
        and covariance_meta[0]["minimum_cluster_df"] == 19,
    )
    _, _, wild_b = engine.selected_cluster_covariance(
        x,
        y,
        beta,
        bread,
        clusters,
        [0, 1, 2],
        row_chunk=137,
        seed=1947,
        bootstrap_draws=999,
    )
    record(
        rows,
        "wild_score_bootstrap_is_seed_reproducible",
        wild_a,
        wild_b,
        0.0,
        wild_a == wild_b,
    )
    _, _, wild_chunk = engine.selected_cluster_covariance(
        x,
        y,
        beta,
        bread,
        clusters,
        [0, 1, 2],
        row_chunk=211,
        seed=1947,
        bootstrap_draws=999,
    )
    chunk_fields = (
        "bootstrap_score_sd",
        "bootstrap_delta_p025",
        "bootstrap_delta_p975",
        "basic_ci95_low",
        "basic_ci95_high",
        "two_sided_score_p_value",
    )
    chunk_a = wild_a["outcomes"][0]
    chunk_b = wild_chunk["outcomes"][0]
    chunk_difference = max(
        abs(float(chunk_a[field]) - float(chunk_b[field]))
        for field in chunk_fields
    )
    record(
        rows,
        "wild_score_bootstrap_is_row_chunk_invariant",
        chunk_difference,
        0.0,
        1e-12,
        chunk_difference <= 1e-12,
    )
    wild_outcome = wild_a["outcomes"][0]
    record(
        rows,
        "wild_score_bootstrap_outputs_are_valid",
        wild_outcome,
        "finite ordered CI and p-value in [0, 1]",
        0.0,
        (
            np.isfinite(wild_outcome["basic_ci95_low"])
            and np.isfinite(wild_outcome["basic_ci95_high"])
            and wild_outcome["basic_ci95_low"]
            <= wild_outcome["basic_ci95_high"]
            and 0.0
            <= wild_outcome["two_sided_score_p_value"]
            <= 1.0
        ),
    )

    # 4. Three-way fixed-effect residualization against explicit dummy OLS.
    n_fe = 2_000
    fe_physician = rng.integers(0, 40, size=n_fe)
    fe_facility_yq = rng.integers(0, 25, size=n_fe)
    fe_clinical = rng.integers(0, 8, size=n_fe)
    x_fe = rng.normal(size=(n_fe, 2))
    physician_effect = rng.normal(size=40)
    facility_effect = rng.normal(size=25)
    clinical_effect = rng.normal(size=8)
    y_fe = (
        x_fe @ np.array([0.7, -0.3])
        + physician_effect[fe_physician]
        + facility_effect[fe_facility_yq]
        + clinical_effect[fe_clinical]
        + rng.normal(scale=0.1, size=n_fe)
    )[:, None]
    fe_codes = np.column_stack(
        [fe_physician, fe_facility_yq, fe_clinical]
    ).astype(np.uint64)
    with tempfile.TemporaryDirectory(prefix="p2infer_") as temporary:
        x_tilde, y_tilde, demeaning_meta = engine.residualize(
            x_fe,
            y_fe,
            fe_codes,
            [0, 1],
            [0, 1, 2],
            Path(temporary),
            block_columns=2,
            tolerance=1e-10,
            checkpoint_binding={"matrix_manifest_sha256": "binding_a"},
        )
        x_tilde_array = np.asarray(x_tilde).copy()
        y_tilde_array = np.asarray(y_tilde).copy()
        within_beta = np.linalg.solve(
            x_tilde_array.T @ x_tilde_array,
            x_tilde_array.T @ y_tilde_array,
        )[:, 0]
        dummy_blocks = [np.ones((n_fe, 1)), x_fe]
        for values in (
            fe_physician,
            fe_facility_yq,
            fe_clinical,
        ):
            dummy_blocks.append(
                np.eye(int(values.max()) + 1, dtype=np.float64)[values][
                    :, 1:
                ]
            )
        explicit_design = np.column_stack(dummy_blocks)
        explicit_beta = np.linalg.lstsq(
            explicit_design, y_fe[:, 0], rcond=None
        )[0][1:3]
        fixed_effect_difference = float(
            np.max(np.abs(within_beta - explicit_beta))
        )
        del x_tilde, y_tilde
        gc.collect()
        x_fe_changed = x_fe.copy()
        x_fe_changed[:, 0] *= 2.0
        x_changed_tilde, y_changed_tilde, changed_meta = engine.residualize(
            x_fe_changed,
            y_fe,
            fe_codes,
            [0, 1],
            [0, 1, 2],
            Path(temporary),
            block_columns=2,
            tolerance=1e-10,
            checkpoint_binding={"matrix_manifest_sha256": "binding_b"},
        )
        checkpoint_recompute_difference = float(
            np.max(
                np.abs(
                    np.asarray(x_changed_tilde)[:, 0]
                    - 2.0 * x_tilde_array[:, 0]
                )
            )
        )
        checkpoint_state = json.loads(
            (Path(temporary) / "demeaning_state.json").read_text(
                encoding="utf-8"
            )
        )
        del (
            x_changed_tilde,
            y_changed_tilde,
            x_tilde_array,
            y_tilde_array,
        )
        gc.collect()
    record(
        rows,
        "three_way_hdfe_matches_explicit_dummy_ols",
        fixed_effect_difference,
        0.0,
        1e-10,
        fixed_effect_difference <= 1e-10
        and demeaning_meta.get("converged") is True,
    )
    record(
        rows,
        "demeaning_checkpoint_binding_change_forces_recompute",
        {
            "max_difference_from_expected_scaled_residual": (
                checkpoint_recompute_difference
            ),
            "stored_binding": checkpoint_state.get("checkpoint_binding"),
            "changed_meta_binding": changed_meta.get("checkpoint_binding"),
        },
        {
            "max_difference_from_expected_scaled_residual": 0.0,
            "stored_binding": {"matrix_manifest_sha256": "binding_b"},
            "changed_meta_binding": {
                "matrix_manifest_sha256": "binding_b"
            },
        },
        1e-10,
        checkpoint_recompute_difference <= 1e-10
        and checkpoint_state.get("checkpoint_binding")
        == {"matrix_manifest_sha256": "binding_b"}
        and changed_meta.get("checkpoint_binding")
        == {"matrix_manifest_sha256": "binding_b"},
    )

    output_csv = phase2 / "qa" / "inference_engine_unit_tests.csv"
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "created_utc": now_utc(),
        "test_id": "primary_inference_engine_reference_tests_v1",
        "synthetic_only": True,
        "real_data_estimates_generated": False,
        "tests": len(rows),
        "passed_tests": sum(int(row["passed"]) for row in rows),
        "failed_tests": sum(int(not row["passed"]) for row in rows),
        "all_passed": all(row["passed"] for row in rows),
        "engine": {
            "path": str(engine_path),
            "sha256": sha256_file(engine_path),
        },
        "references": {
            "point_estimates": "NumPy least squares",
            "fixed_effects": "explicit dummy-variable NumPy least squares",
            "two_way_crv1": (
                "statsmodels cov_cluster_2groups with finite-sample correction"
            ),
        },
        "check_table": str(output_csv),
    }
    atomic_json(
        phase2 / "qa" / "inference_engine_unit_tests.json",
        payload,
    )
    print(json.dumps(payload, indent=2))
    if not payload["all_passed"]:
        raise RuntimeError("Inference engine reference tests failed")


if __name__ == "__main__":
    main()
