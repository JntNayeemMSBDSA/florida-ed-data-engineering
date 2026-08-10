#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/42_independent_directional_result_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently recompute and audit one directional result family/outcome.

The alternate audit recomputes cross-products, the Moore-Penrose solution,
two-way CRV1 covariance using columnwise ``bincount`` score aggregation,
every reported prediction and contrast, and the facility wild-score
bootstrap.  It writes status/counts only to stdout; coefficient values remain
inside restricted analytical artifacts until the family release gate passes.
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


def pinv_solution(
    xtx: np.ndarray, xty: np.ndarray
) -> tuple[int, np.ndarray, np.ndarray]:
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
    inverse_values = np.zeros_like(eigenvalues)
    inverse_values[positive] = 1.0 / eigenvalues[positive]
    bread = (eigenvectors * inverse_values) @ eigenvectors.T
    projector = eigenvectors[:, positive] @ eigenvectors[:, positive].T
    return int(positive.sum()), bread @ xty, projector


def crossproducts(
    x: np.ndarray, y: np.ndarray, row_chunk: int
) -> tuple[np.ndarray, np.ndarray]:
    k = x.shape[1]
    xtx = np.zeros((k, k), dtype=np.float64)
    xty = np.zeros(k, dtype=np.float64)
    for start, stop in chunks(x.shape[0], row_chunk):
        xb = np.asarray(x[start:stop, :], dtype=np.float64)
        yb = np.asarray(y[start:stop, 0], dtype=np.float64)
        xtx += xb.T @ xb
        xty += xb.T @ yb
    return xtx, xty


def alternate_covariance(
    x: np.ndarray,
    y: np.ndarray,
    beta: np.ndarray,
    bread: np.ndarray,
    clusters: np.memmap,
    rank: int,
    row_chunk: int,
) -> tuple[np.ndarray, list[np.ndarray], dict[str, Any]]:
    n, k = x.shape
    encoded_counts = [
        int(np.max(clusters[:, index])) + 1 for index in range(3)
    ]
    scores = [
        np.zeros((count, k), dtype=np.float64)
        for count in encoded_counts
    ]
    active = [np.zeros(count, dtype=bool) for count in encoded_counts]
    effective_rows = 0
    for start, stop in chunks(n, row_chunk):
        xb = np.asarray(x[start:stop, :], dtype=np.float64)
        yb = np.asarray(y[start:stop, 0], dtype=np.float64)
        residual = yb - xb @ beta
        active_rows = np.any(np.abs(xb) > 1e-12, axis=1)
        effective_rows += int(active_rows.sum())
        for dimension in range(3):
            codes = np.asarray(
                clusters[start:stop, dimension], dtype=np.int64
            )
            active[dimension][codes[active_rows]] = True
            for column in range(k):
                scores[dimension][:, column] += np.bincount(
                    codes,
                    weights=xb[:, column] * residual,
                    minlength=encoded_counts[dimension],
                )
    active_counts = [int(value.sum()) for value in active]
    df_residual = max(effective_rows - rank, 1)
    selected_scores = [
        value[mask, :] for value, mask in zip(scores, active)
    ]
    meats = []
    corrections = []
    for count, value in zip(active_counts, selected_scores):
        correction = (
            count / (count - 1)
            * (effective_rows - 1)
            / df_residual
            if count > 1
            else math.nan
        )
        corrections.append(correction)
        meats.append(correction * (value.T @ value))
    covariance = bread @ (meats[0] + meats[1] - meats[2]) @ bread
    covariance = (covariance + covariance.T) / 2
    return covariance, selected_scores, {
        "effective_rows": effective_rows,
        "cluster_counts": active_counts,
        "corrections": corrections,
        "minimum_cluster_df": min(active_counts[0], active_counts[1]) - 1,
    }


def contrast_vector(
    contrast: dict[str, Any],
    cell_lookup: dict[str, int],
    k: int,
) -> np.ndarray:
    value = np.zeros(k, dtype=np.float64)
    for term in contrast["linear_combination"]:
        value[cell_lookup[term["cell_id"]]] = float(term["weight"])
    return value


def identified(target: np.ndarray, projector: np.ndarray) -> bool:
    error = np.linalg.norm(target - projector @ target) / max(
        np.linalg.norm(target), 1.0
    )
    return bool(error <= 1e-8)


def inference_values(
    target: np.ndarray,
    beta: np.ndarray,
    covariance: np.ndarray,
    projector: np.ndarray,
    df: int,
    anchor: float,
) -> dict[str, Any]:
    estimate = float(anchor + target @ beta)
    variance = float(target @ covariance @ target)
    variance_valid = math.isfinite(variance) and variance >= -1e-12
    standard_error = (
        math.sqrt(max(variance, 0.0)) if variance_valid else math.nan
    )
    statistic = (
        estimate / standard_error
        if standard_error > 0 and df > 0 and identified(target, projector)
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
        "variance": max(variance, 0.0) if variance_valid else variance,
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
        "identified": identified(target, projector),
        "variance_valid": variance_valid,
    }


def close_value(a: Any, b: Any, atol: float = 1e-8) -> bool:
    try:
        left, right = float(a), float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)
    if math.isnan(left) and math.isnan(right):
        return True
    return math.isclose(left, right, rel_tol=1e-7, abs_tol=atol)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--scratch-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--row-chunk", type=int, default=137_777)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    matrix_dir = args.matrix_root.resolve() / args.family / args.outcome
    result_dir = args.results_root.resolve() / args.family / args.outcome
    matrix_manifest_path = matrix_dir / "matrix_manifest.json"
    matrix_audit_path = (
        phase2
        / "qa"
        / "directional_matrix_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    result_manifest_path = result_dir / "directional_estimation_manifest.json"
    required = (
        matrix_manifest_path,
        matrix_audit_path,
        result_manifest_path,
    )
    if not all(path.is_file() for path in required):
        raise SystemExit("Directional audit input missing")
    matrix_manifest = load_json(matrix_manifest_path)
    matrix_audit = load_json(matrix_audit_path)
    result_manifest = load_json(result_manifest_path)
    if (
        matrix_audit.get("status") != "PASS"
        or result_manifest.get("status")
        != "ESTIMATION_COMPLETE_AUDIT_PENDING"
        or result_manifest.get("matrix_manifest_sha256")
        != sha256_file(matrix_manifest_path)
        or result_manifest.get("matrix_audit_sha256")
        != sha256_file(matrix_audit_path)
        or result_manifest.get("result_interpretation_authorized") is not False
    ):
        raise SystemExit("Directional result provenance gate failed")
    file_hash_checks = []
    for item in result_manifest["result_files"]:
        path = Path(item["path"])
        actual = sha256_file(path) if path.is_file() else ""
        file_hash_checks.append(
            {
                "path": str(path),
                "expected_sha256": item["sha256"],
                "actual_sha256": actual,
                "passed": actual == item["sha256"],
            }
        )
    if not all(item["passed"] for item in file_hash_checks):
        raise SystemExit("Directional result file hash failed")

    n = int(matrix_manifest["n_rows"])
    k = int(matrix_manifest["n_design_columns"])
    q = int(matrix_manifest["n_cell_columns"])
    cell_ids = list(matrix_manifest["cell_ids"])
    cell_lookup = {value: index for index, value in enumerate(cell_ids)}
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
    model_arrays = {
        "U0": (raw[:, :q], outcome),
        "M2_DIRECTIONAL": (
            np.memmap(
                scratch
                / "M2_DIRECTIONAL"
                / "demeaned_design.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, k),
            ),
            np.memmap(
                scratch
                / "M2_DIRECTIONAL"
                / "demeaned_outcomes.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, 1),
            ),
        ),
        "M3_WITHIN_PHYSICIAN": (
            np.memmap(
                scratch
                / "M3_WITHIN_PHYSICIAN"
                / "demeaned_design.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, k),
            ),
            np.memmap(
                scratch
                / "M3_WITHIN_PHYSICIAN"
                / "demeaned_outcomes.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, 1),
            ),
        ),
    }
    coefficients = pd.read_csv(result_dir / "model_coefficients_internal.csv")
    predictions = pd.read_csv(
        result_dir / "directional_adjusted_predictions.csv"
    )
    contrast_results = pd.read_csv(
        result_dir / "directional_planned_contrasts.csv"
    )
    bootstrap_results = pd.read_csv(
        result_dir / "m2_primary_outcome_wild_score_bootstrap.csv"
    )
    extension = load_json(
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    family_spec = extension["analysis_families"][args.family]
    contrasts = list(family_spec["contrasts"])
    support = pd.read_csv(
        matrix_audit["outcome_specific_support"]["path"]
    ).set_index("cell_id")
    cell_composition = (
        support.loc[cell_ids, "probability_weighted_visit_mass"]
        .to_numpy(dtype=np.float64)
        / n
    )
    outcome_mean = float(matrix_audit["matrix_checks"]["outcome_sum"] / n)

    failures = []
    model_audits = {}
    independent_objects = {}
    expected_prediction_rows = 2 * q
    expected_contrast_rows = 3 * len(contrasts)
    expected_coefficient_rows = q + 2 * k
    if len(predictions) != expected_prediction_rows:
        failures.append("prediction_row_count")
    if len(contrast_results) != expected_contrast_rows:
        failures.append("contrast_row_count")
    if len(coefficients) != expected_coefficient_rows:
        failures.append("coefficient_row_count")

    for model_id, (x, y) in model_arrays.items():
        xtx, xty = crossproducts(x, y, args.row_chunk)
        rank, beta, projector = pinv_solution(xtx, xty)
        # Derive bread independently from the already verified symmetric X'X.
        eigenvalues, eigenvectors = np.linalg.eigh((xtx + xtx.T) / 2)
        largest = max(float(eigenvalues[-1]), 1.0)
        tolerance = max(xtx.shape) * np.finfo(float).eps * largest * 10
        inverse_values = np.zeros_like(eigenvalues)
        inverse_values[eigenvalues > tolerance] = (
            1.0 / eigenvalues[eigenvalues > tolerance]
        )
        bread = (eigenvectors * inverse_values) @ eigenvectors.T
        covariance, selected_scores, covariance_meta = alternate_covariance(
            x,
            y,
            beta,
            bread,
            clusters,
            rank,
            args.row_chunk,
        )
        saved = np.load(
            result_dir / f"{model_id}__covariance_and_bread.npz"
        )
        beta_rows = coefficients.loc[
            coefficients["model_id"].eq(model_id), "coefficient"
        ].to_numpy(dtype=np.float64)
        beta_match = bool(
            np.allclose(beta, beta_rows, rtol=1e-8, atol=1e-9)
        )
        covariance_match = bool(
            np.allclose(
                covariance,
                saved["covariance"],
                rtol=2e-7,
                atol=1e-8,
            )
        )
        bread_match = bool(
            np.allclose(bread, saved["bread"], rtol=1e-8, atol=1e-9)
        )
        projector_match = bool(
            np.allclose(
                projector, saved["projector"], rtol=1e-8, atol=1e-9
            )
        )
        if not beta_match:
            failures.append(f"{model_id}_beta")
        if not covariance_match:
            failures.append(f"{model_id}_covariance")
        if not bread_match:
            failures.append(f"{model_id}_bread")
        if not projector_match:
            failures.append(f"{model_id}_projector")
        independent_objects[model_id] = {
            "beta": beta,
            "bread": bread,
            "projector": projector,
            "covariance": covariance,
            "scores": selected_scores,
            "df": covariance_meta["minimum_cluster_df"],
        }
        model_audits[model_id] = {
            "rank": rank,
            "beta_match": beta_match,
            "covariance_match": covariance_match,
            "bread_match": bread_match,
            "projector_match": projector_match,
            "cluster_counts": covariance_meta["cluster_counts"],
        }

    inferential_fields = (
        "estimate",
        "variance",
        "standard_error",
        "cluster_df",
        "t_value",
        "p_value_raw",
        "ci95_low",
        "ci95_high",
    )
    prediction_mismatches = []
    for _, row in predictions.iterrows():
        model_id = row["model_id"]
        fit = independent_objects[model_id]
        local_k = len(fit["beta"])
        target = np.zeros(local_k, dtype=np.float64)
        index = cell_lookup[row["cell_id"]]
        if model_id == "U0":
            target[index] = 1.0
            anchor = 0.0
        elif model_id == "M2_DIRECTIONAL":
            target[:q] = -cell_composition
            target[index] += 1.0
            anchor = outcome_mean
        else:
            prediction_mismatches.append(
                f"prohibited_prediction_model:{model_id}"
            )
            continue
        recomputed = inference_values(
            target,
            fit["beta"],
            fit["covariance"],
            fit["projector"],
            fit["df"],
            anchor,
        )
        for field in inferential_fields:
            if not close_value(row[field], recomputed[field]):
                prediction_mismatches.append(
                    f"{model_id}|{row['cell_id']}|{field}"
                )
    if prediction_mismatches:
        failures.append("prediction_recomputation")

    contrast_by_id = {
        item["contrast_id"]: item for item in contrasts
    }
    contrast_mismatches = []
    for _, row in contrast_results.iterrows():
        model_id = row["model_id"]
        fit = independent_objects[model_id]
        contrast = contrast_by_id[row["contrast_id"]]
        target = contrast_vector(
            contrast, cell_lookup, len(fit["beta"])
        )
        recomputed = inference_values(
            target,
            fit["beta"],
            fit["covariance"],
            fit["projector"],
            fit["df"],
            0.0,
        )
        for field in inferential_fields:
            if not close_value(row[field], recomputed[field]):
                contrast_mismatches.append(
                    f"{model_id}|{row['contrast_id']}|{field}"
                )
    if contrast_mismatches:
        failures.append("contrast_recomputation")

    bootstrap_mismatches = []
    if args.outcome in PRIMARY_OUTCOMES:
        m2 = independent_objects["M2_DIRECTIONAL"]
        if len(bootstrap_results) != len(contrasts):
            bootstrap_mismatches.append("row_count")
        else:
            draws = int(bootstrap_results["draws"].iloc[0])
            seed = int(bootstrap_results["seed"].iloc[0])
            targets = np.column_stack(
                [
                    contrast_vector(item, cell_lookup, k)
                    for item in contrasts
                ]
            )
            influence = m2["scores"][1] @ (m2["bread"] @ targets)
            estimates = targets.T @ m2["beta"]
            rng = np.random.default_rng(seed)
            all_delta = np.empty((draws, len(contrasts)), dtype=np.float64)
            offset = 0
            while offset < draws:
                block = min(250, draws - offset)
                signs = rng.choice(
                    np.array([-1.0, 1.0]),
                    size=(block, m2["scores"][1].shape[0]),
                    replace=True,
                )
                all_delta[offset : offset + block, :] = signs @ influence
                offset += block
            for index, contrast in enumerate(contrasts):
                row = bootstrap_results.loc[
                    bootstrap_results["contrast_id"].eq(
                        contrast["contrast_id"]
                    )
                ].iloc[0]
                delta = all_delta[:, index]
                q025, q975 = np.quantile(delta, [0.025, 0.975])
                values = {
                    "bootstrap_score_sd": float(np.std(delta, ddof=1)),
                    "bootstrap_delta_p025": float(q025),
                    "bootstrap_delta_p975": float(q975),
                    "basic_ci95_low": float(estimates[index] - q975),
                    "basic_ci95_high": float(estimates[index] - q025),
                    "two_sided_score_p_value": float(
                        (
                            1
                            + np.sum(
                                np.abs(delta) >= abs(estimates[index])
                            )
                        )
                        / (draws + 1)
                    ),
                }
                for field, value in values.items():
                    if not close_value(row[field], value):
                        bootstrap_mismatches.append(
                            f"{contrast['contrast_id']}|{field}"
                        )
    elif len(bootstrap_results):
        bootstrap_mismatches.append("nonprimary_bootstrap_not_empty")
    if bootstrap_mismatches:
        failures.append("bootstrap_recomputation")

    nonfinite_estimable = 0
    for frame in (predictions, contrast_results):
        estimable = ~frame["estimability_status"].astype(str).str.startswith(
            "NON_ESTIMABLE"
        )
        numeric = frame.loc[
            estimable,
            [
                "estimate",
                "standard_error",
                "ci95_low",
                "ci95_high",
            ],
        ].to_numpy(dtype=np.float64)
        nonfinite_estimable += int((~np.isfinite(numeric)).any(axis=1).sum())
    if nonfinite_estimable:
        failures.append("nonfinite_estimable_inference")

    qa_root = phase2 / "qa" / "directional_result_audits"
    qa_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "audit_id": "independent_directional_result_audit_v1",
        "created_utc": now_utc(),
        "status": "PASS" if not failures else "FAIL",
        "family_id": args.family,
        "outcome": args.outcome,
        "matrix_manifest_sha256": sha256_file(matrix_manifest_path),
        "matrix_audit_sha256": sha256_file(matrix_audit_path),
        "result_manifest_sha256": sha256_file(result_manifest_path),
        "result_file_hash_checks": file_hash_checks,
        "expected_rows": {
            "predictions": expected_prediction_rows,
            "contrasts": expected_contrast_rows,
            "coefficients": expected_coefficient_rows,
        },
        "actual_rows": {
            "predictions": len(predictions),
            "contrasts": len(contrast_results),
            "coefficients": len(coefficients),
            "bootstrap": len(bootstrap_results),
        },
        "model_audits": model_audits,
        "prediction_recomputation_mismatches": prediction_mismatches,
        "contrast_recomputation_mismatches": contrast_mismatches,
        "bootstrap_recomputation_mismatches": bootstrap_mismatches,
        "nonfinite_estimable_rows": nonfinite_estimable,
        "multiplicity_status": "PENDING_FAMILY_AGGREGATION",
        "failures": failures,
        "result_values_emitted_to_stdout": False,
        "result_interpretation_authorized": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output_path = qa_root / f"{args.family}__{args.outcome}.json"
    atomic_json(output_path, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "family_id": args.family,
                "outcome": args.outcome,
                "models_audited": len(model_audits),
                "prediction_rows_audited": len(predictions),
                "contrast_rows_audited": len(contrast_results),
                "bootstrap_rows_audited": len(bootstrap_results),
                "failures": failures,
                "result_values_emitted": False,
                "result_interpretation_authorized": False,
            },
            indent=2,
        ),
        flush=True,
    )
    if payload["status"] != "PASS":
        raise SystemExit("Independent directional result audit failed")


if __name__ == "__main__":
    main()
