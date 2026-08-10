#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/41_estimate_directional_models.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Estimate one audited directional family/outcome without interpreting it.

The script consumes only a matrix that passed the independent pre-estimation
audit.  It fits the frozen U0, M2_DIRECTIONAL, and M3_WITHIN_PHYSICIAN models,
writes complete coefficient/covariance diagnostics, adjusted predictions,
planned contrasts, and primary-outcome facility wild-score sensitivities.
It emits no coefficient value to stdout.
"""

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
from scipy.stats import t as student_t


FAMILIES = ("gender_dyads", "race_dyads", "intersectional_dyads")
PRIMARY_OUTCOMES = (
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def chunks(n: int, size: int) -> Iterable[tuple[int, int]]:
    for start in range(0, n, size):
        yield start, min(n, start + size)


def rank_pinv_projector(
    xtx: np.ndarray,
) -> tuple[int, float, np.ndarray, np.ndarray, float]:
    symmetric = (xtx + xtx.T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    largest = max(float(eigenvalues[-1]), 1.0)
    tolerance = (
        max(symmetric.shape)
        * np.finfo(np.float64).eps
        * largest
        * 10.0
    )
    positive = eigenvalues > tolerance
    rank = int(positive.sum())
    inverse_values = np.zeros_like(eigenvalues)
    inverse_values[positive] = 1.0 / eigenvalues[positive]
    bread = (eigenvectors * inverse_values) @ eigenvectors.T
    if rank:
        basis = eigenvectors[:, positive]
        projector = basis @ basis.T
        condition = float(eigenvalues[positive].max() / eigenvalues[positive].min())
    else:
        projector = np.zeros_like(symmetric)
        condition = math.inf
    return rank, condition, bread, projector, tolerance


def target_identified(target: np.ndarray, projector: np.ndarray) -> tuple[bool, float]:
    residual = target - projector @ target
    relative = float(
        np.linalg.norm(residual) / max(np.linalg.norm(target), 1.0)
    )
    return relative <= 1e-8, relative


def crossproducts(
    x: np.ndarray, y: np.ndarray, row_chunk: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    k = x.shape[1]
    xtx = np.zeros((k, k), dtype=np.float64)
    xty = np.zeros(k, dtype=np.float64)
    x_norm2 = np.zeros(k, dtype=np.float64)
    y_norm2 = 0.0
    for start, stop in chunks(x.shape[0], row_chunk):
        xb = np.asarray(x[start:stop, :], dtype=np.float64)
        yb = np.asarray(y[start:stop, 0], dtype=np.float64)
        xtx += xb.T @ xb
        xty += xb.T @ yb
        x_norm2 += np.einsum("ij,ij->j", xb, xb)
        y_norm2 += float(yb @ yb)
    return xtx, xty, x_norm2, y_norm2


def full_multiway_covariance(
    x: np.ndarray,
    y: np.ndarray,
    beta: np.ndarray,
    bread: np.ndarray,
    clusters: np.memmap,
    rank: int,
    row_chunk: int,
) -> tuple[np.ndarray, dict[str, Any], list[np.ndarray]]:
    n, k = x.shape
    encoded_counts = [
        int(np.max(clusters[:, dimension])) + 1
        for dimension in range(3)
    ]
    score_sums = [
        np.zeros((count, k), dtype=np.float64)
        for count in encoded_counts
    ]
    active = [np.zeros(count, dtype=bool) for count in encoded_counts]
    sse = 0.0
    effective_rows = 0
    for start, stop in chunks(n, row_chunk):
        xb = np.asarray(x[start:stop, :], dtype=np.float64)
        yb = np.asarray(y[start:stop, 0], dtype=np.float64)
        residual = yb - xb @ beta
        score_block = xb * residual[:, None]
        active_rows = np.any(np.abs(xb) > 1e-12, axis=1)
        effective_rows += int(active_rows.sum())
        sse += float(residual @ residual)
        for dimension in range(3):
            codes = np.asarray(
                clusters[start:stop, dimension], dtype=np.int64
            )
            active[dimension][codes[active_rows]] = True
            np.add.at(score_sums[dimension], codes, score_block)
    active_counts = [int(value.sum()) for value in active]
    df_residual = max(effective_rows - rank, 1)
    corrections = []
    meats = []
    active_scores = []
    for count, scores, mask in zip(active_counts, score_sums, active):
        correction = (
            count / (count - 1)
            * (effective_rows - 1)
            / df_residual
            if count > 1
            else math.nan
        )
        selected = scores[mask, :]
        corrections.append(correction)
        meats.append(correction * (selected.T @ selected))
        active_scores.append(selected)
    meat = meats[0] + meats[1] - meats[2]
    covariance = bread @ meat @ bread
    covariance = (covariance + covariance.T) / 2
    metadata = {
        "n_total_rows": n,
        "n_effective_nonzero_design_rows": effective_rows,
        "zero_design_contribution_rows": n - effective_rows,
        "rank": rank,
        "df_residual": df_residual,
        "cluster_counts": {
            "physician": active_counts[0],
            "facility": active_counts[1],
            "physician_facility_intersection": active_counts[2],
        },
        "encoded_cluster_counts": {
            "physician": encoded_counts[0],
            "facility": encoded_counts[1],
            "physician_facility_intersection": encoded_counts[2],
        },
        "crv1_corrections": corrections,
        "minimum_cluster_df": min(active_counts[0], active_counts[1]) - 1,
        "sse": sse,
        "covariance_symmetric": bool(
            np.allclose(covariance, covariance.T, atol=1e-10, rtol=1e-10)
        ),
        "covariance_finite": bool(np.isfinite(covariance).all()),
    }
    return covariance, metadata, active_scores


def contrast_vector(
    contrast: dict[str, Any],
    cell_lookup: dict[str, int],
    k: int,
) -> np.ndarray:
    value = np.zeros(k, dtype=np.float64)
    for term in contrast["linear_combination"]:
        value[cell_lookup[term["cell_id"]]] = float(term["weight"])
    return value


def infer_target(
    target: np.ndarray,
    beta: np.ndarray,
    covariance: np.ndarray,
    projector: np.ndarray,
    df: int,
    additive_anchor: float = 0.0,
) -> dict[str, Any]:
    identified, rowspace_error = target_identified(target, projector)
    estimate = float(additive_anchor + target @ beta)
    variance = float(target @ covariance @ target)
    variance_valid = math.isfinite(variance) and variance >= -1e-12
    if variance_valid:
        variance = max(variance, 0.0)
        standard_error = math.sqrt(variance)
    else:
        standard_error = math.nan
    statistic = (
        estimate / standard_error
        if identified
        and standard_error > 0
        and math.isfinite(standard_error)
        and df > 0
        else math.nan
    )
    p_value = (
        float(2 * student_t.sf(abs(statistic), df=df))
        if math.isfinite(statistic)
        else math.nan
    )
    critical = float(student_t.ppf(0.975, df=df)) if df > 0 else math.nan
    return {
        "estimate": estimate,
        "variance": variance,
        "standard_error": standard_error,
        "cluster_df": df,
        "t_value": statistic,
        "p_value_raw": p_value,
        "ci95_low": (
            estimate - critical * standard_error
            if math.isfinite(standard_error)
            else math.nan
        ),
        "ci95_high": (
            estimate + critical * standard_error
            if math.isfinite(standard_error)
            else math.nan
        ),
        "identified": identified,
        "rowspace_relative_error": rowspace_error,
        "variance_valid": variance_valid,
    }


def fit_model(
    model_id: str,
    x: np.ndarray,
    y: np.ndarray,
    clusters: np.memmap,
    row_chunk: int,
) -> dict[str, Any]:
    xtx, xty, x_norm2, y_norm2 = crossproducts(x, y, row_chunk)
    rank, condition, bread, projector, rank_tolerance = rank_pinv_projector(
        xtx
    )
    beta = bread @ xty
    covariance, covariance_meta, active_scores = full_multiway_covariance(
        x,
        y,
        beta,
        bread,
        clusters,
        rank,
        row_chunk,
    )
    return {
        "model_id": model_id,
        "beta": beta,
        "covariance": covariance,
        "bread": bread,
        "projector": projector,
        "rank": rank,
        "condition_number": condition,
        "rank_tolerance": rank_tolerance,
        "x_norm2": x_norm2,
        "y_norm2": y_norm2,
        "covariance_meta": covariance_meta,
        "active_cluster_scores": active_scores,
    }


def support_for_cells(
    support: pd.DataFrame, cell_ids: list[str]
) -> tuple[bool, bool, str]:
    selected = support.set_index("cell_id").loc[cell_ids]
    passes = bool(
        selected["outcome_specific_support_status"].eq("PASS").all()
    )
    limited = bool(selected["limited_support_flag"].astype(bool).any())
    status = (
        "NON_ESTIMABLE_SUPPORT"
        if not passes
        else ("LIMITED_SUPPORT" if limited else "PASS")
    )
    return passes, limited, status


def wild_score_bootstrap(
    contrasts: list[dict[str, Any]],
    cell_lookup: dict[str, int],
    k: int,
    beta: np.ndarray,
    bread: np.ndarray,
    facility_scores: np.ndarray,
    draws: int,
    seed: int,
) -> pd.DataFrame:
    if not contrasts:
        return pd.DataFrame()
    targets = np.column_stack(
        [contrast_vector(item, cell_lookup, k) for item in contrasts]
    )
    influence = facility_scores @ (bread @ targets)
    estimates = targets.T @ beta
    rng = np.random.default_rng(seed)
    exceed = np.zeros(len(contrasts), dtype=np.int64)
    lower_buffer = np.empty((draws, len(contrasts)), dtype=np.float64)
    offset = 0
    while offset < draws:
        block = min(250, draws - offset)
        signs = rng.choice(
            np.array([-1.0, 1.0]),
            size=(block, facility_scores.shape[0]),
            replace=True,
        )
        delta = signs @ influence
        lower_buffer[offset : offset + block, :] = delta
        exceed += (np.abs(delta) >= np.abs(estimates)[None, :]).sum(axis=0)
        offset += block
    rows = []
    for index, contrast in enumerate(contrasts):
        delta = lower_buffer[:, index]
        q025, q975 = np.quantile(delta, [0.025, 0.975])
        rows.append(
            {
                "contrast_id": contrast["contrast_id"],
                "contrast_family": contrast["contrast_family"],
                "draws": draws,
                "seed": seed,
                "bootstrap_score_sd": float(np.std(delta, ddof=1)),
                "bootstrap_delta_p025": float(q025),
                "bootstrap_delta_p975": float(q975),
                "basic_ci95_low": float(estimates[index] - q975),
                "basic_ci95_high": float(estimates[index] - q025),
                "two_sided_score_p_value": float(
                    (1 + exceed[index]) / (draws + 1)
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--scratch-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--row-chunk", type=int, default=100_000)
    parser.add_argument("--bootstrap-draws", type=int, default=9_999)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    matrix_dir = args.matrix_root.resolve() / args.family / args.outcome
    manifest_path = matrix_dir / "matrix_manifest.json"
    matrix_audit_path = (
        phase2
        / "qa"
        / "directional_matrix_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    if not manifest_path.is_file() or not matrix_audit_path.is_file():
        raise SystemExit("Directional matrix or independent audit is missing")
    manifest = load_json(manifest_path)
    matrix_audit = load_json(matrix_audit_path)
    if (
        matrix_audit.get("status") != "PASS"
        or matrix_audit.get("matrix_manifest", {}).get("sha256")
        != sha256_file(manifest_path)
        or matrix_audit.get("result_interpretation_authorized") is not False
    ):
        raise SystemExit("Directional matrix independent audit does not authorize fit")
    for item in matrix_audit["matrix_file_audit"]:
        path = Path(item["path"])
        if sha256_file(path) != item["sha256"]:
            raise SystemExit(f"Audited matrix file changed: {path}")

    output = args.output_root.resolve() / args.family / args.outcome
    output.mkdir(parents=True, exist_ok=True)
    success_path = output / "_ESTIMATION_SUCCESS.json"
    estimator_sha256 = sha256_file(Path(__file__).resolve())
    if success_path.is_file():
        existing = load_json(success_path)
        if (
            existing.get("status") == "ESTIMATION_COMPLETE_AUDIT_PENDING"
            and existing.get("matrix_audit_sha256")
            == sha256_file(matrix_audit_path)
            and existing.get("estimator_sha256") == estimator_sha256
        ):
            print(
                json.dumps(
                    {
                        "status": existing["status"],
                        "family_id": args.family,
                        "outcome": args.outcome,
                        "result_values_emitted": False,
                    },
                    indent=2,
                )
            )
            return
        raise SystemExit("Existing directional estimates are stale; preserve them")

    extension_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    extension = load_json(extension_path)
    family_spec = extension["analysis_families"][args.family]
    contrasts = list(family_spec["contrasts"])
    cell_ids = list(manifest["cell_ids"])
    cell_lookup = {value: index for index, value in enumerate(cell_ids)}
    q = len(cell_ids)
    n = int(manifest["n_rows"])
    k = int(manifest["n_design_columns"])
    design_names = [item["name"] for item in manifest["design_spec"]]
    support_path = Path(
        matrix_audit["outcome_specific_support"]["path"]
    )
    support = pd.read_csv(support_path)

    raw = np.memmap(
        matrix_dir / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, k),
    )
    outcome = np.memmap(
        matrix_dir / "outcome.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, 1),
    )
    clusters = np.memmap(
        matrix_dir / "cluster_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    scratch = args.scratch_root.resolve() / args.family / args.outcome
    model_arrays: dict[str, tuple[np.ndarray, np.ndarray]] = {
        "U0": (raw[:, :q], outcome)
    }
    for model_id in ("M2_DIRECTIONAL", "M3_WITHIN_PHYSICIAN"):
        folder = scratch / model_id
        state_path = folder / "demeaning_state.json"
        if not state_path.is_file():
            raise SystemExit(f"Audited demeaning state missing: {state_path}")
        state = load_json(state_path)
        if (
            len(state.get("completed_local_columns", [])) != k
            or state.get("outcomes_completed") is not True
            or not all(state.get("convergence", {}).values())
        ):
            raise SystemExit(f"Audited demeaning incomplete: {model_id}")
        model_arrays[model_id] = (
            np.memmap(
                folder / "demeaned_design.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, k),
            ),
            np.memmap(
                folder / "demeaned_outcomes.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, 1),
            ),
        )

    outcome_mean = float(
        matrix_audit["matrix_checks"]["outcome_sum"] / n
    )
    cell_mass = support.set_index("cell_id").loc[
        cell_ids, "probability_weighted_visit_mass"
    ].to_numpy(dtype=np.float64)
    cell_mean_composition = cell_mass / n
    prediction_rows = []
    contrast_rows = []
    coefficient_rows = []
    model_diagnostics = {}
    covariance_files = []
    fit_objects: dict[str, dict[str, Any]] = {}

    for model_id, (x, y) in model_arrays.items():
        fit = fit_model(model_id, x, y, clusters, args.row_chunk)
        fit_objects[model_id] = fit
        local_k = x.shape[1]
        local_names = (
            [f"cell::{value}" for value in cell_ids]
            if model_id == "U0"
            else design_names
        )
        df = int(fit["covariance_meta"]["minimum_cluster_df"])
        for index, name in enumerate(local_names):
            coefficient_rows.append(
                {
                    "family_id": args.family,
                    "outcome": args.outcome,
                    "model_id": model_id,
                    "term": name,
                    "coefficient": float(fit["beta"][index]),
                    "coefficient_variance": float(
                        fit["covariance"][index, index]
                    ),
                    "identified_column_norm2": float(fit["x_norm2"][index]),
                }
            )
        covariance_path = output / f"{model_id}__covariance_and_bread.npz"
        np.savez_compressed(
            covariance_path,
            covariance=fit["covariance"],
            bread=fit["bread"],
            projector=fit["projector"],
        )
        covariance_files.append(
            {
                "model_id": model_id,
                "path": str(covariance_path),
                "sha256": sha256_file(covariance_path),
                "bytes": covariance_path.stat().st_size,
            }
        )
        if model_id in ("U0", "M2_DIRECTIONAL"):
            for index, cell_id in enumerate(cell_ids):
                target = np.zeros(local_k, dtype=np.float64)
                if model_id == "U0":
                    target[index] = 1.0
                    anchor = 0.0
                else:
                    target[:q] = -cell_mean_composition
                    target[index] += 1.0
                    anchor = outcome_mean
                inference = infer_target(
                    target,
                    fit["beta"],
                    fit["covariance"],
                    fit["projector"],
                    df,
                    anchor,
                )
                support_pass, limited, support_status = support_for_cells(
                    support, [cell_id]
                )
                final_status = (
                    "NON_ESTIMABLE_IDENTIFICATION"
                    if not inference["identified"]
                    else (
                        "NON_ESTIMABLE_VARIANCE"
                        if not inference["variance_valid"]
                        else support_status
                    )
                )
                prediction_rows.append(
                    {
                        "family_id": args.family,
                        "analysis_tier": family_spec["tier"],
                        "measurement_specification": manifest[
                            "measurement_specification"
                        ],
                        "outcome": args.outcome,
                        "outcome_family": manifest["outcome_family"],
                        "model_id": model_id,
                        "cell_id": cell_id,
                        **inference,
                        "support_pass": support_pass,
                        "limited_support_flag": limited,
                        "estimability_status": final_status,
                        "n": n,
                        "outcome_mean_model_sample": outcome_mean,
                    }
                )
        for contrast in contrasts:
            target = contrast_vector(contrast, cell_lookup, local_k)
            inference = infer_target(
                target,
                fit["beta"],
                fit["covariance"],
                fit["projector"],
                df,
            )
            involved = [
                item["cell_id"]
                for item in contrast["linear_combination"]
                if float(item["weight"]) != 0
            ]
            support_pass, limited, support_status = support_for_cells(
                support, involved
            )
            final_status = (
                "NON_ESTIMABLE_IDENTIFICATION"
                if not inference["identified"]
                else (
                    "NON_ESTIMABLE_VARIANCE"
                    if not inference["variance_valid"]
                    else support_status
                )
            )
            contrast_rows.append(
                {
                    "family_id": args.family,
                    "analysis_tier": family_spec["tier"],
                    "measurement_specification": manifest[
                        "measurement_specification"
                    ],
                    "outcome": args.outcome,
                    "outcome_family": manifest["outcome_family"],
                    "model_id": model_id,
                    "contrast_id": contrast["contrast_id"],
                    "contrast_family": contrast["contrast_family"],
                    "direction": contrast["direction"],
                    "estimand": contrast["estimand"],
                    **inference,
                    "support_pass": support_pass,
                    "limited_support_flag": limited,
                    "estimability_status": final_status,
                    "n": n,
                    "outcome_mean_model_sample": outcome_mean,
                    "estimate_percent_of_outcome_mean": (
                        100 * inference["estimate"] / outcome_mean
                        if outcome_mean != 0
                        else math.nan
                    ),
                    "ci95_low_percent_of_outcome_mean": (
                        100 * inference["ci95_low"] / outcome_mean
                        if outcome_mean != 0
                        else math.nan
                    ),
                    "ci95_high_percent_of_outcome_mean": (
                        100 * inference["ci95_high"] / outcome_mean
                        if outcome_mean != 0
                        else math.nan
                    ),
                    "q_value_bh": math.nan,
                    "multiplicity_status": "PENDING_FAMILY_AGGREGATION",
                }
            )
        model_diagnostics[model_id] = {
            "n": n,
            "n_columns": local_k,
            "rank": fit["rank"],
            "nullity": local_k - fit["rank"],
            "condition_number": fit["condition_number"],
            "rank_tolerance": fit["rank_tolerance"],
            "y_norm2": fit["y_norm2"],
            "covariance": fit["covariance_meta"],
            "finite_beta": bool(np.isfinite(fit["beta"]).all()),
            "finite_covariance": bool(np.isfinite(fit["covariance"]).all()),
        }

    prediction_frame = pd.DataFrame(prediction_rows)
    contrast_frame = pd.DataFrame(contrast_rows)
    coefficient_frame = pd.DataFrame(coefficient_rows)
    unadjusted = support.copy()
    unadjusted["weighted_outcome_variance"] = (
        unadjusted["weighted_outcome_second_moment"]
        - np.square(unadjusted["weighted_outcome_mean"])
    ).clip(lower=0)
    unadjusted["weighted_mean_standard_error_naive"] = np.sqrt(
        unadjusted["weighted_outcome_variance"]
        / unadjusted["kish_effective_visits"].clip(lower=1)
    )
    unadjusted["note"] = (
        "Probability-weighted descriptive summary; joint U0 cluster-robust "
        "predictions and contrasts are reported separately."
    )

    prediction_path = output / "directional_adjusted_predictions.csv"
    contrast_path = output / "directional_planned_contrasts.csv"
    coefficient_path = output / "model_coefficients_internal.csv"
    unadjusted_path = output / "directional_unadjusted_cell_summaries.csv"
    prediction_frame.to_csv(prediction_path, index=False)
    contrast_frame.to_csv(contrast_path, index=False)
    coefficient_frame.to_csv(coefficient_path, index=False)
    unadjusted.to_csv(unadjusted_path, index=False)

    bootstrap_path = output / "m2_primary_outcome_wild_score_bootstrap.csv"
    if args.outcome in PRIMARY_OUTCOMES:
        m2 = fit_objects["M2_DIRECTIONAL"]
        bootstrap = wild_score_bootstrap(
            contrasts,
            cell_lookup,
            k,
            m2["beta"],
            m2["bread"],
            m2["active_cluster_scores"][1],
            args.bootstrap_draws,
            args.seed,
        )
    else:
        bootstrap = pd.DataFrame(
            columns=[
                "contrast_id",
                "contrast_family",
                "draws",
                "seed",
                "bootstrap_score_sd",
                "bootstrap_delta_p025",
                "bootstrap_delta_p975",
                "basic_ci95_low",
                "basic_ci95_high",
                "two_sided_score_p_value",
            ]
        )
    bootstrap.to_csv(bootstrap_path, index=False)

    result_files = []
    for path in (
        prediction_path,
        contrast_path,
        coefficient_path,
        unadjusted_path,
        bootstrap_path,
    ):
        result_files.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": len(pd.read_csv(path)),
            }
        )
    result_files.extend(covariance_files)
    manifest_output = {
        "status": "ESTIMATION_COMPLETE_AUDIT_PENDING",
        "created_utc": now_utc(),
        "estimation_version": "directional_estimation_v1_20260726",
        "family_id": args.family,
        "outcome": args.outcome,
        "analysis_tier": family_spec["tier"],
        "measurement_specification": manifest[
            "measurement_specification"
        ],
        "n": n,
        "model_ids": ["U0", "M2_DIRECTIONAL", "M3_WITHIN_PHYSICIAN"],
        "models": model_diagnostics,
        "planned_contrasts": len(contrasts),
        "m2_prediction_rows": int(
            prediction_frame["model_id"].eq("M2_DIRECTIONAL").sum()
        ),
        "m3_identified_contrasts": int(
            contrast_frame.loc[
                contrast_frame["model_id"].eq("M3_WITHIN_PHYSICIAN"),
                "identified",
            ].sum()
        ),
        "bootstrap_draws": (
            args.bootstrap_draws if args.outcome in PRIMARY_OUTCOMES else 0
        ),
        "matrix_manifest_path": str(manifest_path),
        "matrix_manifest_sha256": sha256_file(manifest_path),
        "matrix_audit_path": str(matrix_audit_path),
        "matrix_audit_sha256": sha256_file(matrix_audit_path),
        "estimator_path": str(Path(__file__).resolve()),
        "estimator_sha256": estimator_sha256,
        "result_files": result_files,
        "multiplicity_status": "PENDING_FAMILY_AGGREGATION",
        "independent_result_audit_status": "PENDING",
        "result_interpretation_authorized": False,
        "result_values_emitted_to_stdout": False,
        "language_rule": (
            "Association language only; algorithm-inferred physician race "
            "is never described as self-reported, observed, or BISG."
        ),
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    manifest_output_path = output / "directional_estimation_manifest.json"
    atomic_json(manifest_output_path, manifest_output)
    atomic_json(success_path, manifest_output)
    print(
        json.dumps(
            {
                "status": manifest_output["status"],
                "family_id": args.family,
                "outcome": args.outcome,
                "n": n,
                "models_completed": 3,
                "result_files_written": len(result_files),
                "independent_result_audit_status": "PENDING",
                "result_interpretation_authorized": False,
                "result_values_emitted": False,
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
