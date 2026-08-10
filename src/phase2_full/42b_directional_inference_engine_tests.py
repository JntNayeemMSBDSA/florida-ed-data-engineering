#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/42b_directional_inference_engine_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic equivalence tests for the two directional inference paths."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    estimator_path = phase2 / "scripts" / "41_estimate_directional_models.py"
    auditor_path = (
        phase2 / "scripts" / "42_independent_directional_result_audit.py"
    )
    matrix_auditor_path = (
        phase2 / "scripts" / "40_independent_directional_matrix_audit.py"
    )
    estimator = load_module("directional_estimator_test", estimator_path)
    auditor = load_module("directional_auditor_test", auditor_path)
    matrix_auditor = load_module(
        "directional_matrix_auditor_test", matrix_auditor_path
    )

    rng = np.random.default_rng(20260726)
    n, k = 12_000, 9
    physician = rng.integers(0, 137, n, dtype=np.uint64)
    facility = rng.integers(0, 23, n, dtype=np.uint64)
    pair = np.unique(
        np.column_stack([physician, facility]),
        axis=0,
        return_inverse=True,
    )[1].astype(np.uint64)
    clusters = np.column_stack([physician, facility, pair])
    x = rng.normal(size=(n, k))
    x[:, 0] = 1
    x[:, 2] = x[:, 1] + x[:, 2] * 0.01
    true_beta = rng.normal(size=k)
    y = (x @ true_beta + rng.normal(size=n))[:, None]

    primary = estimator.fit_model("SYNTHETIC", x, y, clusters, 777)
    xtx, xty = auditor.crossproducts(x, y, 911)
    rank, beta, projector = auditor.pinv_solution(xtx, xty)
    eigenvalues, eigenvectors = np.linalg.eigh((xtx + xtx.T) / 2)
    tolerance = (
        max(xtx.shape)
        * np.finfo(float).eps
        * max(float(eigenvalues[-1]), 1.0)
        * 10
    )
    inverse = np.zeros_like(eigenvalues)
    inverse[eigenvalues > tolerance] = (
        1 / eigenvalues[eigenvalues > tolerance]
    )
    bread = (eigenvectors * inverse) @ eigenvectors.T
    covariance, _, covariance_meta = auditor.alternate_covariance(
        x, y, beta, bread, clusters, rank, 911
    )

    q = 4
    weights = rng.dirichlet(np.ones(q), size=n)
    physician_max = np.zeros((int(physician.max()) + 1, q))
    facility_seen = np.zeros((int(facility.max()) + 1, q), dtype=bool)
    np.maximum.at(physician_max, physician.astype(int), weights)
    np.logical_or.at(
        facility_seen, facility.astype(int), weights > 0
    )

    checks = [
        {
            "check_id": "beta_independent_paths",
            "passed": bool(
                np.allclose(primary["beta"], beta, rtol=1e-9, atol=1e-10)
            ),
            "max_abs_difference": float(
                np.max(np.abs(primary["beta"] - beta))
            ),
        },
        {
            "check_id": "bread_independent_paths",
            "passed": bool(
                np.allclose(primary["bread"], bread, rtol=1e-9, atol=1e-10)
            ),
            "max_abs_difference": float(
                np.max(np.abs(primary["bread"] - bread))
            ),
        },
        {
            "check_id": "covariance_add_at_vs_bincount",
            "passed": bool(
                np.allclose(
                    primary["covariance"],
                    covariance,
                    rtol=1e-8,
                    atol=1e-10,
                )
            ),
            "max_abs_difference": float(
                np.max(np.abs(primary["covariance"] - covariance))
            ),
        },
        {
            "check_id": "cluster_counts",
            "passed": (
                [
                    primary["covariance_meta"]["cluster_counts"][
                        "physician"
                    ],
                    primary["covariance_meta"]["cluster_counts"]["facility"],
                    primary["covariance_meta"]["cluster_counts"][
                        "physician_facility_intersection"
                    ],
                ]
                == covariance_meta["cluster_counts"]
            ),
            "counts": covariance_meta["cluster_counts"],
        },
        {
            "check_id": "support_maximum_at_primitive",
            "passed": bool(
                (physician_max.max(axis=0) > 0).all()
                and facility_seen.all()
            ),
        },
        {
            "check_id": "projector_symmetric_idempotent",
            "passed": bool(
                np.allclose(projector, projector.T, atol=1e-10)
                and np.allclose(projector @ projector, projector, atol=1e-9)
            ),
        },
    ]
    expected_sources = {
        "x_0_2": [0, 1],
        "x_2_3": [2],
        "y_0_1": [0],
    }

    def provenance_case(
        folder: Path,
        *,
        fallback: bool = False,
        invalid_fallback: bool = False,
        incomplete: bool = False,
    ) -> dict[str, Any]:
        attempts: dict[str, dict[str, Any]] = {}
        for key, source in expected_sources.items():
            if fallback and key == "x_0_2":
                attempts[key] = {
                    "source_columns": source,
                    "strict_tolerance": 1e-8,
                    "strict_maxiter": 10_000,
                    "strict_status": (
                        "CONVERGED"
                        if invalid_fallback
                        else "NONCONVERGED"
                    ),
                    "fallback_tolerance": 1e-6,
                    "fallback_maxiter": 50_000,
                    "fallback_status": "CONVERGED",
                    "final_method": "fallback",
                    "fallback_used": True,
                    "final_status": "CONVERGED",
                }
            else:
                attempts[key] = {
                    "source_columns": source,
                    "strict_tolerance": 1e-8,
                    "strict_maxiter": 10_000,
                    "strict_status": "CONVERGED",
                    "final_method": "strict",
                    "fallback_used": False,
                    "final_status": "CONVERGED",
                }
        if incomplete:
            attempts.pop("y_0_1")
        binding = {"synthetic_matrix": "v1"}
        state = {
            "n_rows": 12,
            "column_indices": [0, 1, 2],
            "completed_local_columns": [0, 1, 2],
            "completed_outcome_columns": ([] if incomplete else [0]),
            "outcomes_completed": not incomplete,
            "convergence": {key: True for key in attempts},
            "demeaning_attempts": attempts,
            "numerical_policy": {
                "strict": {
                    "tolerance": 1e-8,
                    "maxiter": 10_000,
                    "backend": "rust",
                },
                "fallback_only_after_documented_strict_nonconvergence": {
                    "tolerance": 1e-6,
                    "maxiter": 50_000,
                    "backend": "rust",
                },
                "sample_formula_fixed_effects_and_columns_changed": False,
            },
            "checkpoint_binding": binding,
        }
        state_path = folder / "demeaning_state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        fallback_keys = [
            key
            for key, value in attempts.items()
            if value["fallback_used"]
        ]
        metadata = {
            "converged": not incomplete,
            "fallback_used": bool(fallback_keys),
            "fallback_blocks": fallback_keys,
            "checkpoint_binding": binding,
        }
        return matrix_auditor.audit_demeaning_provenance(
            state_path,
            metadata,
            n_rows=12,
            n_columns=3,
            n_outcomes=1,
            block_columns=2,
            checkpoint_binding=binding,
        )

    with tempfile.TemporaryDirectory(
        prefix="directional_demeaning_policy_test_"
    ) as temporary:
        root = Path(temporary)
        cases = (
            ("directional_strict_provenance_passes", {}, "PASS"),
            (
                "directional_documented_fallback_passes",
                {"fallback": True},
                "PASS",
            ),
            (
                "directional_invalid_fallback_fails",
                {"fallback": True, "invalid_fallback": True},
                "FAIL",
            ),
            (
                "directional_incomplete_attempt_grid_fails",
                {"incomplete": True},
                "FAIL",
            ),
        )
        for index, (check_id, options, expected_status) in enumerate(cases):
            folder = root / str(index)
            folder.mkdir()
            observed = provenance_case(folder, **options)
            checks.append(
                {
                    "check_id": check_id,
                    "passed": observed["status"] == expected_status,
                    "expected_status": expected_status,
                    "observed_status": observed["status"],
                    "observed_failures": observed["failures"],
                }
            )
    payload = {
        "test_id": "directional_inference_engine_synthetic_tests_v1",
        "created_utc": now_utc(),
        "status": "PASS" if all(item["passed"] for item in checks) else "FAIL",
        "checks_passed": sum(bool(item["passed"]) for item in checks),
        "checks_total": len(checks),
        "checks": checks,
        "synthetic_rows": n,
        "synthetic_columns": k,
        "rank": rank,
        "estimator_sha256": sha256_file(estimator_path),
        "independent_auditor_sha256": sha256_file(auditor_path),
        "independent_matrix_auditor_sha256": sha256_file(
            matrix_auditor_path
        ),
        "real_outcome_estimates_read": False,
    }
    output = phase2 / "qa" / "directional_inference_engine_tests.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit("Directional inference engine tests failed")


if __name__ == "__main__":
    main()
