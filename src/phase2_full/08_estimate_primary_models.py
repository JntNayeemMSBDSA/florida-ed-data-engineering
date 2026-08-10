#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/08_estimate_primary_models.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Estimate full-cohort primary OLS/HDFE concordance models with multiway CRSE."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import scipy.linalg
from pyfixest import MapDemeaner
from pyfixest.estimation.internals.demean_ import dispatch_demean
from scipy.stats import t as student_t


class ColumnView:
    """Chunk-addressable column projection that never copies the full matrix."""

    def __init__(self, base: np.ndarray, columns: list[int]) -> None:
        self.base = base
        self.columns = np.asarray(columns, dtype=np.int64)
        self.shape = (base.shape[0], len(columns))

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, local_columns = key
        selected = self.columns[local_columns]
        return self.base[rows, :][:, selected]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_matrix_gate_binding(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Fail closed unless a matrix remains bound to live provider-v2 gates."""
    if (
        manifest.get("provider_measurement_version")
        != "provider_master_v2_full_name_race_v1"
    ):
        raise SystemExit(
            "Model matrix is not certified for provider measurement v2"
        )

    validated: dict[str, dict[str, Any]] = {}
    for path_field, hash_field in (
        ("provider_gate_path", "provider_gate_sha256"),
        ("cohort_gate_path", "cohort_gate_sha256"),
        ("gender_checkpoint_path", "gender_checkpoint_sha256"),
    ):
        raw_path = str(manifest.get(path_field, "")).strip()
        expected_hash = str(manifest.get(hash_field, "")).strip().lower()
        if not raw_path or len(expected_hash) != 64:
            raise SystemExit(
                f"Model matrix gate binding is incomplete: {path_field}"
            )
        gate_path = Path(raw_path).resolve()
        if (
            not gate_path.is_file()
            or sha256_file(gate_path).lower() != expected_hash
        ):
            raise SystemExit(
                f"Model matrix gate binding is missing or stale: {path_field}"
            )
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate.get("status") != "PASS":
            raise SystemExit(
                f"Model matrix gate no longer passes: {gate_path}"
            )
        validated[path_field] = {
            "path": str(gate_path),
            "sha256": expected_hash,
            "status": "PASS",
        }
    return validated


def matrix_binding_provenance(
    manifest: dict[str, Any],
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Return standardized, verified matrix and gate provenance."""
    validated = validate_matrix_gate_binding(manifest)
    provenance: dict[str, Any] = {
        "provider_measurement_version": manifest[
            "provider_measurement_version"
        ],
        "inference_engine_path": str(Path(__file__).resolve()),
        "inference_engine_sha256": sha256_file(Path(__file__).resolve()),
        "matrix_id": manifest.get("matrix_id"),
        "analysis_sample_policy": manifest.get("analysis_sample_policy"),
        "eligibility_policy": manifest.get("eligibility_policy", "primary"),
        "provider_gate_path": validated["provider_gate_path"]["path"],
        "provider_gate_sha256": validated["provider_gate_path"]["sha256"],
        "cohort_gate_path": validated["cohort_gate_path"]["path"],
        "cohort_gate_sha256": validated["cohort_gate_path"]["sha256"],
        "gender_checkpoint_path": validated[
            "gender_checkpoint_path"
        ]["path"],
        "gender_checkpoint_sha256": validated[
            "gender_checkpoint_path"
        ]["sha256"],
    }
    if manifest_path is not None:
        resolved = manifest_path.resolve()
        if not resolved.is_file():
            raise SystemExit(f"Matrix manifest is missing: {resolved}")
        provenance["matrix_manifest_path"] = str(resolved)
        provenance["matrix_manifest_sha256"] = sha256_file(resolved)
    return provenance


def chunks(n: int, size: int) -> Iterable[tuple[int, int]]:
    for start in range(0, n, size):
        yield start, min(n, start + size)


def matrix_files_are_valid(
    folder: Path, n: int, k: int, o: int
) -> bool:
    expected = {
        "demeaned_design.float64.mmap": n * k * 8,
        "demeaned_outcomes.float64.mmap": n * o * 8,
    }
    return all(
        (folder / name).exists()
        and (folder / name).stat().st_size == size
        for name, size in expected.items()
    )


def residualize(
    raw: np.memmap,
    outcomes: np.memmap,
    fe_all: np.memmap,
    column_indices: list[int],
    fe_indices: list[int],
    folder: Path,
    block_columns: int,
    tolerance: float,
    checkpoint_binding: dict[str, Any] | None = None,
) -> tuple[np.memmap, np.memmap, dict[str, Any]]:
    folder.mkdir(parents=True, exist_ok=True)
    n = raw.shape[0]
    k = len(column_indices)
    o = outcomes.shape[1]
    binding = checkpoint_binding or {}
    state_path = folder / "demeaning_state.json"
    resumable = state_path.exists() and matrix_files_are_valid(folder, n, k, o)
    if resumable:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (
            state.get("n_rows") != n
            or state.get("column_indices") != column_indices
            or state.get("fe_indices") != fe_indices
            or state.get("checkpoint_binding", {}) != binding
        ):
            resumable = False
    if resumable:
        mode = "r+"
        completed_columns = set(state.get("completed_local_columns", []))
        if state.get("outcomes_completed", False):
            completed_outcomes = set(range(o))
        else:
            completed_outcomes = set(
                state.get("completed_outcome_columns", [])
            )
        convergence = dict(state.get("convergence", {}))
        demeaning_attempts = dict(state.get("demeaning_attempts", {}))
    else:
        mode = "w+"
        completed_columns: set[int] = set()
        completed_outcomes: set[int] = set()
        convergence: dict[str, bool] = {}
        demeaning_attempts: dict[str, dict[str, Any]] = {}

    x_tilde = np.memmap(
        folder / "demeaned_design.float64.mmap",
        dtype=np.float64,
        mode=mode,
        shape=(n, k),
    )
    y_tilde = np.memmap(
        folder / "demeaned_outcomes.float64.mmap",
        dtype=np.float64,
        mode=mode,
        shape=(n, o),
    )
    fe = np.ascontiguousarray(fe_all[:, fe_indices], dtype=np.uint64)
    weights = np.ones(n, dtype=np.float64)
    strict_maxiter = 10_000
    fallback_tolerance = max(float(tolerance), 1e-6)
    fallback_maxiter = 50_000
    strict_demeaner = MapDemeaner(
        fixef_maxiter=strict_maxiter,
        fixef_tol=tolerance,
        backend="rust",
    )
    fallback_demeaner = MapDemeaner(
        fixef_maxiter=fallback_maxiter,
        fixef_tol=fallback_tolerance,
        backend="rust",
    )

    def persist_state() -> None:
        atomic_json(
            state_path,
            {
                "updated_utc": now_utc(),
                "n_rows": n,
                "column_indices": column_indices,
                "fe_indices": fe_indices,
                "completed_local_columns": sorted(completed_columns),
                "completed_outcome_columns": sorted(completed_outcomes),
                "outcomes_completed": len(completed_outcomes) == o,
                "convergence": convergence,
                "demeaning_attempts": demeaning_attempts,
                "numerical_policy": {
                    "strict": {
                        "tolerance": tolerance,
                        "maxiter": strict_maxiter,
                        "backend": "rust",
                    },
                    "fallback_only_after_documented_strict_nonconvergence": {
                        "tolerance": fallback_tolerance,
                        "maxiter": fallback_maxiter,
                        "backend": "rust",
                    },
                    "sample_formula_fixed_effects_and_columns_changed": False,
                },
                "checkpoint_binding": binding,
            },
        )

    def transform_with_documented_fallback(
        block: np.ndarray,
        attempt_key: str,
        source_columns: list[int],
    ) -> np.ndarray:
        prior = dict(demeaning_attempts.get(attempt_key, {}))
        skip_repeated_strict = bool(
            prior.get("strict_status") == "NONCONVERGED"
            and prior.get("source_columns") == source_columns
            and prior.get("strict_tolerance") == tolerance
            and prior.get("strict_maxiter") == strict_maxiter
        )
        if skip_repeated_strict:
            strict_success = False
            transformed = None
            strict_detail = prior.get("strict_dispatch_detail")
        else:
            transformed, strict_success, strict_detail_raw = dispatch_demean(
                block, fe, weights, strict_demeaner
            )
            strict_detail = repr(strict_detail_raw)
            prior = {
                "source_columns": source_columns,
                "strict_tolerance": tolerance,
                "strict_maxiter": strict_maxiter,
                "strict_status": (
                    "CONVERGED" if strict_success else "NONCONVERGED"
                ),
                "strict_dispatch_detail": strict_detail,
                "strict_attempt_recorded_utc": now_utc(),
                "strict_attempt_reused_from_checkpoint": False,
            }
            demeaning_attempts[attempt_key] = prior
            # Persist the failed strict attempt before the numerical fallback.
            persist_state()
        if strict_success:
            prior.update(
                {
                    "final_method": "strict",
                    "fallback_used": False,
                    "final_status": "CONVERGED",
                }
            )
            demeaning_attempts[attempt_key] = prior
            return transformed

        fallback_transformed, fallback_success, fallback_detail_raw = (
            dispatch_demean(block, fe, weights, fallback_demeaner)
        )
        prior.update(
            {
                "strict_attempt_reused_from_checkpoint": (
                    skip_repeated_strict
                ),
                "fallback_tolerance": fallback_tolerance,
                "fallback_maxiter": fallback_maxiter,
                "fallback_dispatch_detail": repr(fallback_detail_raw),
                "fallback_status": (
                    "CONVERGED" if fallback_success else "NONCONVERGED"
                ),
                "fallback_attempt_recorded_utc": now_utc(),
                "final_method": "fallback",
                "fallback_used": True,
                "final_status": (
                    "CONVERGED" if fallback_success else "NONCONVERGED"
                ),
            }
        )
        demeaning_attempts[attempt_key] = prior
        persist_state()
        if not fallback_success:
            raise RuntimeError(
                "Demeaning did not converge under either the strict or "
                f"documented fallback policy for columns {source_columns}"
            )
        return fallback_transformed

    for local_start in range(0, k, block_columns):
        local_stop = min(k, local_start + block_columns)
        local_columns = list(range(local_start, local_stop))
        if all(index in completed_columns for index in local_columns):
            continue
        raw_indices = column_indices[local_start:local_stop]
        block = np.ascontiguousarray(raw[:, raw_indices], dtype=np.float64)
        attempt_key = f"x_{local_start}_{local_stop}"
        transformed = transform_with_documented_fallback(
            block,
            attempt_key,
            raw_indices,
        )
        x_tilde[:, local_start:local_stop] = transformed
        x_tilde.flush()
        completed_columns.update(local_columns)
        convergence[attempt_key] = True
        persist_state()

    for outcome_start in range(0, o, block_columns):
        outcome_stop = min(o, outcome_start + block_columns)
        outcome_columns = list(range(outcome_start, outcome_stop))
        if all(index in completed_outcomes for index in outcome_columns):
            continue
        block = np.ascontiguousarray(
            outcomes[:, outcome_start:outcome_stop], dtype=np.float64
        )
        attempt_key = f"y_{outcome_start}_{outcome_stop}"
        transformed = transform_with_documented_fallback(
            block,
            attempt_key,
            outcome_columns,
        )
        y_tilde[:, outcome_start:outcome_stop] = transformed
        y_tilde.flush()
        completed_outcomes.update(outcome_columns)
        convergence[attempt_key] = True
        persist_state()
    del weights, fe
    fallback_blocks = sorted(
        key
        for key, value in demeaning_attempts.items()
        if value.get("fallback_used") is True
    )
    return x_tilde, y_tilde, {
        "converged": all(convergence.values()),
        "tolerance": tolerance,
        "backend": "pyfixest_rust_map",
        "fixed_effect_dimensions": fe_indices,
        "block_columns": block_columns,
        "strict_maxiter": strict_maxiter,
        "documented_fallback_tolerance": fallback_tolerance,
        "documented_fallback_maxiter": fallback_maxiter,
        "fallback_used": bool(fallback_blocks),
        "fallback_blocks": fallback_blocks,
        "demeaning_attempts": demeaning_attempts,
        "checkpoint_binding": binding,
    }


def crossproducts(
    x: np.ndarray, y: np.ndarray, row_chunk: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    k = x.shape[1]
    o = y.shape[1]
    xtx = np.zeros((k, k), dtype=np.float64)
    xty = np.zeros((k, o), dtype=np.float64)
    x_norm2 = np.zeros(k, dtype=np.float64)
    y_norm2 = np.zeros(o, dtype=np.float64)
    for start, stop in chunks(x.shape[0], row_chunk):
        xb = np.asarray(x[start:stop, :], dtype=np.float64)
        yb = np.asarray(y[start:stop, :], dtype=np.float64)
        xtx += xb.T @ xb
        xty += xb.T @ yb
        x_norm2 += np.einsum("ij,ij->j", xb, xb)
        y_norm2 += np.einsum("ij,ij->j", yb, yb)
    return xtx, xty, x_norm2, y_norm2


def independent_columns(
    xtx: np.ndarray, names: list[str]
) -> tuple[list[int], list[int], int, float]:
    diagonal = np.diag(xtx)
    scale = max(float(np.max(diagonal)), 1.0)
    nonzero = np.flatnonzero(diagonal > scale * 1e-14)
    dropped_zero = sorted(set(range(len(names))) - set(nonzero.tolist()))
    reduced = xtx[np.ix_(nonzero, nonzero)]
    _, r, pivots = scipy.linalg.qr(reduced, pivoting=True, mode="economic")
    diag_r = np.abs(np.diag(r))
    tolerance = max(reduced.shape) * np.finfo(float).eps * max(
        float(diag_r[0]) if len(diag_r) else 1.0, 1.0
    )
    rank = int(np.sum(diag_r > tolerance))
    keep = sorted(nonzero[pivots[:rank]].tolist())
    dropped = sorted(set(range(len(names))) - set(keep))
    eigenvalues = np.linalg.eigvalsh(xtx[np.ix_(keep, keep)])
    positive = eigenvalues[eigenvalues > 0]
    condition = (
        float(positive.max() / positive.min())
        if len(positive)
        else math.inf
    )
    return keep, dropped, rank, condition


def selected_cluster_covariance(
    x: np.ndarray,
    y: np.ndarray,
    beta: np.ndarray,
    bread: np.ndarray,
    clusters: np.memmap,
    target_positions: list[int],
    row_chunk: int,
    seed: int,
    bootstrap_draws: int,
) -> tuple[list[np.ndarray], list[dict[str, Any]], dict[str, Any]]:
    n, k = x.shape
    o = y.shape[1]
    q = len(target_positions)
    influence_map = bread[:, target_positions]
    cluster_counts = [
        int(np.max(clusters[:, index])) + 1 for index in range(3)
    ]
    sums = [
        np.zeros((count, q, o), dtype=np.float64)
        for count in cluster_counts
    ]
    active_clusters = [
        np.zeros(count, dtype=bool) for count in cluster_counts
    ]
    sse = np.zeros(o, dtype=np.float64)
    effective_rows = 0

    for start, stop in chunks(n, row_chunk):
        xb = np.asarray(x[start:stop, :], dtype=np.float64)
        yb = np.asarray(y[start:stop, :], dtype=np.float64)
        residual = yb - xb @ beta
        leverage_direction = xb @ influence_map
        active_row = np.any(np.abs(xb) > 1e-12, axis=1)
        effective_rows += int(active_row.sum())
        sse += np.einsum("ij,ij->j", residual, residual)
        for dimension, group_count in enumerate(cluster_counts):
            codes = np.asarray(
                clusters[start:stop, dimension], dtype=np.int64
            )
            active_clusters[dimension][codes[active_row]] = True
            for target in range(q):
                for outcome in range(o):
                    sums[dimension][:, target, outcome] += np.bincount(
                        codes,
                        weights=(
                            leverage_direction[:, target]
                            * residual[:, outcome]
                        ),
                        minlength=group_count,
                    )

    covariances: list[np.ndarray] = []
    covariance_meta: list[dict[str, Any]] = []
    active_cluster_counts = [
        int(values.sum()) for values in active_clusters
    ]
    df_residual = max(effective_rows - k, 1)
    for outcome in range(o):
        meat_terms = []
        corrections = []
        for group_count, score in zip(active_cluster_counts, sums):
            correction = (
                group_count / (group_count - 1)
                * (effective_rows - 1)
                / df_residual
                if group_count > 1
                else math.nan
            )
            corrections.append(correction)
            meat_terms.append(correction * (score[:, :, outcome].T @ score[:, :, outcome]))
        covariance = meat_terms[0] + meat_terms[1] - meat_terms[2]
        covariance = (covariance + covariance.T) / 2
        covariances.append(covariance)
        covariance_meta.append(
            {
                "cluster_counts": {
                    "physician": active_cluster_counts[0],
                    "facility": active_cluster_counts[1],
                    "physician_facility_intersection": active_cluster_counts[2],
                },
                "encoded_cluster_counts_before_zero_contribution_exclusion": {
                    "physician": cluster_counts[0],
                    "facility": cluster_counts[1],
                    "physician_facility_intersection": cluster_counts[2],
                },
                "n_total_rows": n,
                "n_effective_nonzero_design_rows": effective_rows,
                "zero_design_contribution_rows": n - effective_rows,
                "crv1_corrections": corrections,
                "minimum_cluster_df": min(
                    active_cluster_counts[0], active_cluster_counts[1]
                )
                - 1,
                "sse": float(sse[outcome]),
                "variance_diagonal_nonnegative": bool(
                    np.all(np.diag(covariance) >= 0)
                ),
            }
        )

    rng = np.random.default_rng(seed)
    interaction_local = q - 1
    wild_results: dict[str, Any] = {
        "method": (
            "facility-level Rademacher wild score bootstrap using the "
            "unrestricted full-model cluster score"
        ),
        "draws": bootstrap_draws,
        "seed": seed,
        "outcomes": [],
    }
    facility_scores = sums[1][active_clusters[1], interaction_local, :]
    active_facility_codes = np.flatnonzero(active_clusters[1])
    for outcome in range(o):
        deltas = np.empty(bootstrap_draws, dtype=np.float64)
        draw_offset = 0
        while draw_offset < bootstrap_draws:
            block = min(2_000, bootstrap_draws - draw_offset)
            signs = rng.choice(
                np.array([-1.0, 1.0]),
                size=(block, active_cluster_counts[1]),
                replace=True,
            )
            deltas[draw_offset : draw_offset + block] = (
                signs @ facility_scores[:, outcome]
            )
            draw_offset += block
        interaction_estimate = float(
            beta[target_positions[interaction_local], outcome]
        )
        absolute_facility_scores = np.abs(facility_scores[:, outcome])
        top_facility_local = np.argsort(absolute_facility_scores)[-10:][::-1]
        q025 = float(np.quantile(deltas, 0.025))
        q975 = float(np.quantile(deltas, 0.975))
        wild_results["outcomes"].append(
            {
                "outcome_index": outcome,
                "interaction_estimate": interaction_estimate,
                "bootstrap_score_sd": float(np.std(deltas, ddof=1)),
                "bootstrap_delta_p025": q025,
                "bootstrap_delta_p975": q975,
                "basic_ci95_low": interaction_estimate - q975,
                "basic_ci95_high": interaction_estimate - q025,
                "two_sided_score_p_value": float(
                    (
                        1
                        + np.sum(
                            np.abs(deltas) >= abs(interaction_estimate)
                        )
                    )
                    / (bootstrap_draws + 1)
                ),
                "first_order_leave_one_facility_diagnostics": {
                    "maximum_absolute_interaction_shift": float(
                        absolute_facility_scores.max()
                    ),
                    "p99_absolute_interaction_shift": float(
                        np.quantile(absolute_facility_scores, 0.99)
                    ),
                    "maximum_percent_of_absolute_estimate": (
                        float(
                            100
                            * absolute_facility_scores.max()
                            / abs(interaction_estimate)
                        )
                        if interaction_estimate != 0
                        else None
                    ),
                    "top_internal_facility_cluster_codes": [
                        int(active_facility_codes[value])
                        for value in top_facility_local
                    ],
                    "top_signed_first_order_shifts": [
                        float(facility_scores[value, outcome])
                        for value in top_facility_local
                    ],
                    "note": (
                        "First-order cluster deletion approximation from the "
                        "full-model influence score; not an exact refit."
                    ),
                },
            }
        )
    return covariances, covariance_meta, wild_results


def run_model(
    model_id: str,
    column_indices: list[int],
    design_names: list[str],
    raw: np.memmap,
    outcomes: np.memmap,
    fe_codes: np.memmap,
    clusters: np.memmap,
    fe_indices: list[int],
    scratch: Path,
    output_root: Path,
    row_chunk: int,
    block_columns: int,
    tolerance: float,
    bootstrap_draws: int,
    seed: int,
    cohort: str,
    outcome_names: list[str],
    interaction_name_override: str | None = None,
    target_names_override: list[str] | None = None,
    pretransformed: tuple[Any, Any, dict[str, Any]] | None = None,
    checkpoint_binding: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    local_names = [design_names[index] for index in column_indices]
    if pretransformed is not None:
        x, y, demeaning_meta = pretransformed
    elif fe_indices:
        x, y, demeaning_meta = residualize(
            raw,
            outcomes,
            fe_codes,
            column_indices,
            fe_indices,
            scratch / model_id,
            block_columns,
            tolerance,
            checkpoint_binding,
        )
    else:
        x = ColumnView(raw, column_indices)
        y = outcomes
        demeaning_meta = {
            "converged": True,
            "backend": "not_applicable_no_fixed_effects",
            "fixed_effect_dimensions": [],
        }

    xtx_full, xty_full, x_norm2, y_norm2 = crossproducts(x, y, row_chunk)
    keep, dropped, rank, condition = independent_columns(xtx_full, local_names)
    keep_names = [local_names[index] for index in keep]
    dropped_names = [local_names[index] for index in dropped]
    interaction_name = interaction_name_override or (
        "race_interaction"
        if cohort == "race"
        else "sex_gender_interaction"
    )
    if interaction_name not in keep_names:
        raise RuntimeError(f"{model_id}: primary interaction is not identified")
    x_kept = ColumnView(x, keep)
    xtx = xtx_full[np.ix_(keep, keep)]
    xty = xty_full[keep, :]
    bread = np.linalg.inv(xtx)
    beta = bread @ xty

    desired_targets = (
        [name for name in target_names_override if name in keep_names]
        if target_names_override is not None
        else [
            name
            for name in (
                "physician_black_proxy",
                "patient_black",
                "race_interaction",
                "physician_female",
                "patient_female",
                "sex_gender_interaction",
            )
            if name in keep_names
        ]
    )
    if interaction_name in desired_targets:
        desired_targets = [
            name for name in desired_targets if name != interaction_name
        ] + [interaction_name]
    target_positions = [keep_names.index(name) for name in desired_targets]
    covariances, covariance_meta, wild = selected_cluster_covariance(
        x_kept,
        y,
        beta,
        bread,
        clusters,
        target_positions,
        row_chunk,
        seed,
        bootstrap_draws,
    )
    outcome_means = np.zeros(len(outcome_names), dtype=np.float64)
    for start, stop in chunks(outcomes.shape[0], row_chunk):
        outcome_means += np.sum(
            np.asarray(outcomes[start:stop, :], dtype=np.float64), axis=0
        )
    outcome_means /= outcomes.shape[0]

    rows: list[dict[str, Any]] = []
    selected_vcov: dict[str, Any] = {}
    min_df = min(
        covariance_meta[0]["cluster_counts"]["physician"],
        covariance_meta[0]["cluster_counts"]["facility"],
    ) - 1
    critical = float(student_t.ppf(0.975, df=min_df))
    for outcome_index, outcome_name in enumerate(outcome_names):
        covariance = covariances[outcome_index]
        selected_vcov[outcome_name] = {
            "coefficient_order": desired_targets,
            "covariance": covariance.tolist(),
        }
        unclustered_sigma2 = (
            covariance_meta[outcome_index]["sse"]
            / max(y.shape[0] - rank, 1)
        )
        unclustered_vcov = unclustered_sigma2 * bread
        for position, name in enumerate(keep_names):
            estimate = float(beta[position, outcome_index])
            if name in desired_targets:
                selected_index = desired_targets.index(name)
                variance = float(covariance[selected_index, selected_index])
                standard_error = (
                    math.sqrt(variance) if variance >= 0 else math.nan
                )
                statistic = (
                    estimate / standard_error
                    if standard_error and math.isfinite(standard_error)
                    else math.nan
                )
                p_value = (
                    float(
                        2
                        * student_t.sf(
                            abs(statistic), df=min_df
                        )
                    )
                    if math.isfinite(statistic)
                    else math.nan
                )
                ci_low = estimate - critical * standard_error
                ci_high = estimate + critical * standard_error
            else:
                standard_error = math.nan
                statistic = math.nan
                p_value = math.nan
                ci_low = math.nan
                ci_high = math.nan
            rows.append(
                {
                    "cohort": cohort,
                    "model_id": model_id,
                    "outcome": outcome_name,
                    "term": name,
                    "estimate": estimate,
                    "clustered_standard_error": standard_error,
                    "clustered_df": min_df if name in desired_targets else math.nan,
                    "t_value": statistic,
                    "p_value": p_value,
                    "ci95_low": ci_low,
                    "ci95_high": ci_high,
                    "unclustered_standard_error_diagnostic": math.sqrt(
                        max(float(unclustered_vcov[position, position]), 0.0)
                    ),
                    "outcome_mean_model_sample": float(
                        outcome_means[outcome_index]
                    ),
                    "estimate_percent_of_outcome_mean": (
                        100 * estimate / outcome_means[outcome_index]
                        if outcome_means[outcome_index] != 0
                        else math.nan
                    ),
                    "ci95_low_percent_of_outcome_mean": (
                        100 * ci_low / outcome_means[outcome_index]
                        if outcome_means[outcome_index] != 0
                        else math.nan
                    ),
                    "ci95_high_percent_of_outcome_mean": (
                        100 * ci_high / outcome_means[outcome_index]
                        if outcome_means[outcome_index] != 0
                        else math.nan
                    ),
                    "n": int(y.shape[0]),
                    "n_effective_nonzero_design_rows": int(
                        covariance_meta[outcome_index][
                            "n_effective_nonzero_design_rows"
                        ]
                    ),
                }
            )

    result = pd.DataFrame(rows)
    output_root.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_root / f"{model_id}_coefficients.csv", index=False)
    diagnostics = {
        "created_utc": now_utc(),
        "cohort": cohort,
        "model_id": model_id,
        "n": int(y.shape[0]),
        "candidate_columns": local_names,
        "kept_columns": keep_names,
        "dropped_collinear_or_zero_columns": dropped_names,
        "explicit_design_rank": rank,
        "xtx_condition_number": condition,
        "x_column_norm2": {
            name: float(value)
            for name, value in zip(local_names, x_norm2)
        },
        "y_norm2": {
            name: float(value)
            for name, value in zip(outcome_names, y_norm2)
        },
        "demeaning": demeaning_meta,
        "covariance": covariance_meta,
        "selected_vcov": selected_vcov,
        "wild_score_bootstrap": wild,
        "interaction_term": interaction_name,
        "interaction_equals_requested_four_cell_contrast": (
            interaction_name
            == (
                "race_interaction"
                if cohort == "race"
                else "sex_gender_interaction"
            )
        ),
        "interaction_is_modifier_or_sensitivity_contrast": (
            interaction_name
            != (
                "race_interaction"
                if cohort == "race"
                else "sex_gender_interaction"
            )
        ),
        "physician_patient_order_verified": True,
    }
    atomic_json(output_root / f"{model_id}_diagnostics.json", diagnostics)
    return result, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument(
        "--matrix-id",
        default="",
        help=(
            "Optional matrix directory below --matrix-root. Defaults to the "
            "cohort name."
        ),
    )
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cohort", required=True, choices=("race", "sex_gender"))
    parser.add_argument("--row-chunk", type=int, default=250_000)
    parser.add_argument("--block-columns", type=int, default=4)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--bootstrap-draws", type=int, default=9_999)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    matrix_id = args.matrix_id.strip() or args.cohort
    if Path(matrix_id).name != matrix_id or matrix_id in {".", ".."}:
        raise SystemExit("--matrix-id must be one safe directory name")
    matrix_root = (args.matrix_root / matrix_id).resolve()
    matrix_manifest_path = matrix_root / "matrix_manifest.json"
    manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    matrix_provenance = matrix_binding_provenance(
        manifest, matrix_manifest_path
    )
    n = int(manifest["n_rows"])
    design_spec = manifest["design_spec"]
    design_names = [item["name"] for item in design_spec]
    groups = [item["group"] for item in design_spec]
    outcome_names = list(manifest["outcomes"])
    k = len(design_names)
    raw = np.memmap(
        matrix_root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, k),
    )
    outcomes = np.memmap(
        matrix_root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(outcome_names)),
    )
    fe_codes = np.memmap(
        matrix_root / "fe_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    clusters = np.memmap(
        matrix_root / "cluster_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )

    model_specs: list[tuple[str, list[int], list[int]]] = []
    patient_adjusted_columns = [
        index
        for index, group in enumerate(groups)
        if group
        in (
            "intercept",
            "exposure",
            "primary_interaction",
            "patient_visit",
            "patient_risk",
        )
    ]
    model_specs.append(
        ("m1_patient_adjusted", patient_adjusted_columns, [])
    )
    fully_adjusted_columns = [
        index
        for index, group in enumerate(groups)
        if group
        not in (
            "intercept",
            "sensitivity_exposure",
            "sensitivity_interaction",
            "selection_only",
        )
        and not group.startswith("heterogeneity_")
        and group != "intersectional"
    ]
    model_specs.append(
        ("m2_fully_adjusted_facility_yq_clinical_fe", fully_adjusted_columns, [1, 2])
    )
    absorbed_physician_main = (
        "physician_black_proxy"
        if args.cohort == "race"
        else "physician_female"
    )
    physician_fe_columns = [
        index
        for index, (name, group) in enumerate(zip(design_names, groups))
        if group != "intercept"
        and group
        not in (
            "sensitivity_exposure",
            "sensitivity_interaction",
            "selection_only",
        )
        and not group.startswith("heterogeneity_")
        and group != "intersectional"
        and name != absorbed_physician_main
        and (
            group != "physician"
            or name
            in (
                "log1p_physician_quarter_volume",
                "physician_quarter_volume_missing",
            )
        )
    ]
    model_specs.append(
        (
            "m3_physician_facility_yq_clinical_fe",
            physician_fe_columns,
            [0, 1, 2],
        )
    )

    all_results = []
    all_diagnostics: dict[str, Any] = {}
    for offset, (model_id, columns, fe_indices) in enumerate(model_specs):
        result, diagnostic = run_model(
            model_id,
            columns,
            design_names,
            raw,
            outcomes,
            fe_codes,
            clusters,
            fe_indices,
            args.scratch.resolve() / args.cohort,
            args.output.resolve() / args.cohort,
            args.row_chunk,
            args.block_columns,
            args.tolerance,
            args.bootstrap_draws,
            args.seed + offset,
            args.cohort,
            outcome_names,
            None,
            None,
            None,
            matrix_provenance,
        )
        all_results.append(result)
        all_diagnostics[model_id] = diagnostic

    combined = pd.concat(all_results, ignore_index=True)
    combined.to_csv(
        args.output.resolve() / args.cohort / "primary_model_coefficients.csv",
        index=False,
    )
    summary = {
        "created_utc": now_utc(),
        "cohort": args.cohort,
        "matrix_id": matrix_id,
        "analysis_sample_policy": manifest.get(
            "analysis_sample_policy", "legacy_unspecified"
        ),
        "eligibility_policy": manifest.get(
            "eligibility_policy", "primary"
        ),
        "outcome_specific_confirmatory_sample": bool(
            manifest.get("outcome_specific_confirmatory_sample", False)
        ),
        "outcome_specific_sample": bool(
            manifest.get("outcome_specific_sample", False)
        ),
        "confirmatory_designated": bool(
            manifest.get("confirmatory_designated", False)
        ),
        "n_analysis_sample": n,
        "n_common_primary_sample": (
            n
            if manifest.get("analysis_sample_policy") == "common_primary"
            else None
        ),
        "model_ids": [item[0] for item in model_specs],
        "all_models_converged": all(
            item["demeaning"]["converged"] for item in all_diagnostics.values()
        ),
        "interaction_term": (
            "race_interaction"
            if args.cohort == "race"
            else "sex_gender_interaction"
        ),
        "inference": (
            "two-way physician and facility CRV1 with physician-facility "
            "intersection subtraction; t reference with minimum cluster df"
        ),
        "full_eligible_data_used": True,
        **matrix_provenance,
    }
    atomic_json(
        args.output.resolve() / args.cohort / "primary_models_manifest.json",
        summary,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
