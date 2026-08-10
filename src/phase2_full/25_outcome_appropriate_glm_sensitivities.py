#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/25_outcome_appropriate_glm_sensitivities.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Validate and estimate deterministic cluster-sample HDFE GLM sensitivities.

The exact full-cohort OLS/HDFE models remain primary. These nonlinear models
are pre-specified robustness checks fitted to a deterministic probability
sample of complete physician clusters because repeatedly fitting nonlinear
HDFE models to more than 100 million visits is not computationally practical.
Sampling is independent of outcomes and retains every visit for an included
physician.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
from scipy.special import expit
from scipy.stats import norm


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def chunks(n: int, size: int) -> Iterable[tuple[int, int]]:
    for start in range(0, n, size):
        yield start, min(n, start + size)


def load_engine(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("phase2_hdfe_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load HDFE engine from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def splitmix64(values: np.ndarray, seed: int) -> np.ndarray:
    """Vectorized SplitMix64, with intentional unsigned overflow."""
    with np.errstate(over="ignore"):
        z = values.astype(np.uint64, copy=True)
        z += np.uint64(seed) + np.uint64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(
            0xBF58476D1CE4E5B9
        )
        z = (z ^ (z >> np.uint64(27))) * np.uint64(
            0x94D049BB133111EB
        )
        return z ^ (z >> np.uint64(31))


def deterministic_physician_cluster_sample(
    physician_codes: np.ndarray,
    target_rows: int,
    seed: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    n = len(physician_codes)
    probability = min(1.0, target_rows / max(n, 1))
    threshold = int(math.floor(probability * (2**64 - 1)))
    hashed = splitmix64(physician_codes, seed)
    mask = hashed <= np.uint64(threshold)
    if not np.any(mask):
        raise RuntimeError("Deterministic physician-cluster sample is empty")
    selected_physicians = np.unique(physician_codes[mask])
    return mask, {
        "method": "SplitMix64 deterministic Bernoulli sampling of physician clusters",
        "seed": seed,
        "target_rows": target_rows,
        "source_rows": n,
        "realized_rows": int(mask.sum()),
        "nominal_cluster_inclusion_probability": probability,
        "realized_physician_clusters": int(len(selected_physicians)),
        "outcome_independent": True,
        "all_visits_retained_for_selected_physicians": True,
    }


def iterative_non_singleton_mask(fe: np.ndarray) -> np.ndarray:
    keep = np.ones(fe.shape[0], dtype=bool)
    while True:
        previous = int(keep.sum())
        indices = np.flatnonzero(keep)
        for dimension in range(fe.shape[1]):
            values = fe[indices, dimension]
            _, inverse, counts = np.unique(
                values, return_inverse=True, return_counts=True
            )
            local_keep = counts[inverse] > 1
            keep[indices[~local_keep]] = False
            indices = np.flatnonzero(keep)
        if int(keep.sum()) == previous:
            return keep


def family_values(
    family: str, eta: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    if family == "poisson_log":
        eta_safe = np.clip(eta, -20.0, 20.0)
        mu = np.exp(eta_safe)
        weight = np.maximum(mu, 1e-10)
        z = eta_safe + (y - mu) / weight
        with np.errstate(divide="ignore", invalid="ignore"):
            part = np.where(y > 0, y * np.log(y / mu) - (y - mu), mu)
        deviance = float(2 * np.sum(part))
    elif family == "binomial_logit":
        eta_safe = np.clip(eta, -25.0, 25.0)
        mu = np.clip(expit(eta_safe), 1e-10, 1 - 1e-10)
        weight = np.maximum(mu * (1 - mu), 1e-10)
        z = eta_safe + (y - mu) / weight
        deviance = float(
            -2
            * np.sum(y * np.log(mu) + (1 - y) * np.log(1 - mu))
        )
    elif family == "gamma_log":
        eta_safe = np.clip(eta, -20.0, 20.0)
        mu = np.exp(eta_safe)
        weight = np.ones_like(mu)
        z = eta_safe + (y - mu) / np.maximum(mu, 1e-10)
        ratio = np.maximum(y / np.maximum(mu, 1e-10), 1e-12)
        deviance = float(2 * np.sum((y - mu) / mu - np.log(ratio)))
    else:
        raise ValueError(f"Unsupported family: {family}")
    return mu, weight, z, deviance


def inverse_link(family: str, eta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if family in ("poisson_log", "gamma_log"):
        mu = np.exp(np.clip(eta, -20.0, 20.0))
        return mu, mu
    mu = np.clip(expit(np.clip(eta, -25.0, 25.0)), 1e-10, 1 - 1e-10)
    return mu, mu * (1 - mu)


def score_factor(family: str, mu: np.ndarray) -> np.ndarray:
    if family == "gamma_log":
        return 1.0 / np.maximum(mu, 1e-10)
    return np.ones_like(mu)


def demean(
    values: np.ndarray,
    fe: np.ndarray,
    weights: np.ndarray,
    tolerance: float,
) -> np.ndarray:
    demeaner = MapDemeaner(
        fixef_maxiter=10_000, fixef_tol=tolerance, backend="rust"
    )
    transformed, success, _ = dispatch_demean(
        np.ascontiguousarray(values, dtype=np.float64),
        np.ascontiguousarray(fe, dtype=np.uint64),
        np.ascontiguousarray(weights, dtype=np.float64),
        demeaner,
    )
    if not success:
        raise RuntimeError("Weighted HDFE demeaning failed to converge")
    return transformed


def initial_eta(y: np.ndarray, family: str) -> np.ndarray:
    mean = float(np.mean(y))
    if family == "binomial_logit":
        mean = float(np.clip(mean, 1e-4, 1 - 1e-4))
        value = math.log(mean / (1 - mean))
    else:
        value = math.log(max(mean, 1e-4))
    return np.full(len(y), value, dtype=np.float64)


def hdfe_glm(
    x: np.ndarray,
    y: np.ndarray,
    fe: np.ndarray,
    family: str,
    tolerance: float,
    max_iterations: int,
) -> dict[str, Any]:
    n, k = x.shape
    beta = np.zeros(k, dtype=np.float64)
    eta = initial_eta(y, family)
    prior_deviance = math.inf
    history: list[dict[str, Any]] = []
    x_tilde = np.empty_like(x)
    weights = np.ones(n, dtype=np.float64)

    for iteration in range(1, max_iterations + 1):
        mu, weights, z, deviance_before = family_values(family, eta, y)
        x_tilde = demean(x, fe, weights, tolerance)
        z_tilde = demean(z[:, None], fe, weights, tolerance)[:, 0]
        wx = x_tilde * weights[:, None]
        xtwx = x_tilde.T @ wx
        xtwz = x_tilde.T @ (weights * z_tilde)
        _, triangular, _ = scipy.linalg.qr(
            xtwx, mode="economic", pivoting=True
        )
        diagonal = np.abs(np.diag(triangular))
        rank = int(
            np.sum(diagonal > max(diagonal.max(initial=0), 1.0) * 1e-11)
        )
        if rank < k:
            raise RuntimeError(
                f"GLM explicit design is rank deficient ({rank}/{k})"
            )
        beta_full_step = np.linalg.solve(xtwx, xtwz)
        q = z - x @ beta_full_step
        q_tilde = demean(q[:, None], fe, weights, tolerance)[:, 0]
        eta_full_step = x @ beta_full_step + q - q_tilde
        beta_candidate = beta_full_step
        eta_candidate = eta_full_step
        _, _, _, candidate_deviance = family_values(
            family, eta_candidate, y
        )

        step = 1.0
        while (
            candidate_deviance > deviance_before * (1 + 1e-10)
            and step > 1 / 128
        ):
            step /= 2
            beta_step = beta + step * (beta_full_step - beta)
            eta_step = eta + step * (eta_full_step - eta)
            _, _, _, step_deviance = family_values(family, eta_step, y)
            beta_candidate = beta_step
            eta_candidate = eta_step
            candidate_deviance = step_deviance

        beta_change = float(np.max(np.abs(beta_candidate - beta)))
        relative_deviance_change = float(
            abs(candidate_deviance - prior_deviance)
            / max(abs(prior_deviance), 1.0)
            if math.isfinite(prior_deviance)
            else math.inf
        )
        history.append(
            {
                "iteration": iteration,
                "deviance": candidate_deviance,
                "maximum_beta_change": beta_change,
                "relative_deviance_change": relative_deviance_change,
                "step": step,
            }
        )
        beta = beta_candidate
        eta = eta_candidate
        prior_deviance = candidate_deviance
        if beta_change < tolerance and relative_deviance_change < tolerance:
            break
    else:
        raise RuntimeError(
            f"{family} HDFE IRLS did not converge in {max_iterations} iterations"
        )

    mu, weights, _, deviance = family_values(family, eta, y)
    x_tilde = demean(x, fe, weights, tolerance)
    bread_inverse = np.linalg.inv(
        x_tilde.T @ (x_tilde * weights[:, None])
    )
    return {
        "beta": beta,
        "eta": eta,
        "mu": mu,
        "weights": weights,
        "x_tilde": x_tilde,
        "bread_inverse": bread_inverse,
        "deviance": deviance,
        "iterations": len(history),
        "history": history,
        "converged": True,
    }


def recode(values: np.ndarray) -> tuple[np.ndarray, int]:
    _, codes = np.unique(values, return_inverse=True)
    return codes.astype(np.int64), int(codes.max(initial=-1) + 1)


def clustered_covariance(
    x_tilde: np.ndarray,
    y: np.ndarray,
    mu: np.ndarray,
    clusters: np.ndarray,
    bread_inverse: np.ndarray,
    family: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    n, k = x_tilde.shape
    scores = x_tilde * (
        score_factor(family, mu) * (y - mu)
    )[:, None]
    meat = np.zeros((k, k), dtype=np.float64)
    counts: dict[str, int] = {}
    dimensions = (
        ("physician", clusters[:, 0], 1.0),
        ("facility", clusters[:, 1], 1.0),
        ("physician_facility_intersection", clusters[:, 2], -1.0),
    )
    for label, raw_codes, sign in dimensions:
        codes, groups = recode(raw_codes)
        counts[label] = groups
        sums = np.zeros((groups, k), dtype=np.float64)
        np.add.at(sums, codes, scores)
        correction = (
            groups / max(groups - 1, 1)
            * (n - 1)
            / max(n - k, 1)
        )
        meat += sign * correction * (sums.T @ sums)
    covariance = bread_inverse @ meat @ bread_inverse
    return covariance, {
        "cluster_counts": counts,
        "two_way_method": (
            "CRV1 physician + CRV1 facility - CRV1 physician-facility "
            "intersection"
        ),
    }


def marginal_pair_contrast(
    x: np.ndarray,
    eta: np.ndarray,
    beta: np.ndarray,
    covariance: np.ndarray,
    physician_index: int,
    patient_index: int,
    interaction_index: int,
    family: str,
) -> dict[str, float]:
    observed = x[:, [physician_index, patient_index, interaction_index]]
    contrast_mu = np.zeros(len(x), dtype=np.float64)
    gradient = np.zeros(len(beta), dtype=np.float64)
    cell_means: dict[str, float] = {}
    for physician, patient, sign, label in (
        (1.0, 1.0, 1.0, "11"),
        (1.0, 0.0, -1.0, "10"),
        (0.0, 1.0, -1.0, "01"),
        (0.0, 0.0, 1.0, "00"),
    ):
        target = np.array([physician, patient, physician * patient])
        eta_cf = eta + (target - observed) @ beta[
            [physician_index, patient_index, interaction_index]
        ]
        mu_cf, derivative = inverse_link(family, eta_cf)
        cell_means[label] = float(np.mean(mu_cf))
        contrast_mu += sign * mu_cf
        gradient_cell = np.mean(derivative[:, None] * x, axis=0)
        mean_derivative = float(np.mean(derivative))
        gradient_cell[physician_index] = physician * mean_derivative
        gradient_cell[patient_index] = patient * mean_derivative
        gradient_cell[interaction_index] = (
            physician * patient * mean_derivative
        )
        gradient += sign * gradient_cell
    estimate = float(np.mean(contrast_mu))
    variance = float(gradient @ covariance @ gradient)
    standard_error = math.sqrt(max(variance, 0.0))
    return {
        "estimate": estimate,
        "standard_error": standard_error,
        "ci95_low": estimate - 1.96 * standard_error,
        "ci95_high": estimate + 1.96 * standard_error,
        "p_value": float(
            2 * norm.sf(abs(estimate / standard_error))
            if standard_error > 0
            else math.nan
        ),
        "cell_mean_11": cell_means["11"],
        "cell_mean_10": cell_means["10"],
        "cell_mean_01": cell_means["01"],
        "cell_mean_00": cell_means["00"],
    }


def validate_engine(output: Path) -> dict[str, Any]:
    import statsmodels.api as sm

    rng = np.random.default_rng(20260726)
    n = 12_000
    facility = rng.integers(0, 18, n)
    clinical = rng.integers(0, 12, n)
    physician = rng.binomial(1, 0.35, n).astype(float)
    patient = rng.binomial(1, 0.30, n).astype(float)
    interaction = physician * patient
    covariate = rng.normal(size=n)
    x = np.column_stack([physician, patient, interaction, covariate])
    beta_true = np.array([0.12, -0.08, 0.20, 0.15])
    facility_effect = rng.normal(0, 0.18, 18)
    clinical_effect = rng.normal(0, 0.12, 12)
    linear_predictor = (
        0.3
        + x @ beta_true
        + facility_effect[facility]
        + clinical_effect[clinical]
    )
    fe = np.column_stack([facility, clinical]).astype(np.uint64)
    dummies = pd.get_dummies(
        pd.DataFrame({"facility": facility, "clinical": clinical}).astype(
            "category"
        ),
        drop_first=True,
        dtype=float,
    )
    dense = np.column_stack([np.ones(n), x, dummies.to_numpy()])
    tests = []
    for family, y, statsmodels_family, truth_tolerance in (
        (
            "poisson_log",
            rng.poisson(np.exp(linear_predictor)).astype(float),
            sm.families.Poisson(),
            0.08,
        ),
        (
            "binomial_logit",
            rng.binomial(1, expit(linear_predictor)).astype(float),
            sm.families.Binomial(),
            0.10,
        ),
        (
            "gamma_log",
            rng.gamma(
                shape=4.0,
                scale=np.exp(linear_predictor) / 4.0,
            ).astype(float),
            sm.families.Gamma(link=sm.families.links.Log()),
            0.10,
        ),
    ):
        fit = hdfe_glm(x, y, fe, family, 1e-9, 100)
        reference = sm.GLM(
            y, dense, family=statsmodels_family
        ).fit(maxiter=100, tol=1e-10)
        reference_beta = reference.params[1:5]
        max_reference_difference = float(
            np.max(np.abs(fit["beta"] - reference_beta))
        )
        max_truth_difference = float(
            np.max(np.abs(fit["beta"] - beta_true))
        )
        tests.append(
            {
                "family": family,
                "true_beta": beta_true.tolist(),
                "estimated_beta": fit["beta"].tolist(),
                "reference_beta": reference_beta.tolist(),
                "maximum_absolute_difference_vs_reference": (
                    max_reference_difference
                ),
                "maximum_absolute_difference_vs_truth": max_truth_difference,
                "reference_tolerance": 2e-5,
                "truth_tolerance": truth_tolerance,
                "passed": (
                    max_reference_difference < 2e-5
                    and max_truth_difference < truth_tolerance
                ),
            }
        )
    passed = all(item["passed"] for item in tests)
    payload = {
        "created_utc": now_utc(),
        "test": (
            "synthetic Poisson, binomial-logit, and Gamma-log HDFE versus "
            "statsmodels explicit dummies"
        ),
        "n": n,
        "tests": tests,
        "passed": passed,
    }
    atomic_json(output / "glm_hdfe_engine_validation.json", payload)
    if not passed:
        raise RuntimeError(f"Nonlinear HDFE engine validation failed: {payload}")
    return payload


def choose_columns(
    manifest: dict[str, Any],
) -> tuple[list[int], list[str]]:
    spec = manifest["design_spec"]
    allowed_groups = {
        "exposure",
        "primary_interaction",
        "patient_visit",
        "patient_risk",
        "physician",
    }
    indices = [
        index
        for index, item in enumerate(spec)
        if item["group"] in allowed_groups
    ]
    names = [spec[index]["name"] for index in indices]
    return indices, names


def estimate_real_data(args: argparse.Namespace) -> None:
    phase2 = args.phase2.resolve()
    engine = load_engine(phase2 / "scripts" / "08_estimate_primary_models.py")
    matrix_root = (args.matrix_root / args.cohort).resolve()
    matrix_manifest_path = matrix_root / "matrix_manifest.json"
    manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    matrix_provenance = engine.matrix_binding_provenance(
        manifest, matrix_manifest_path
    )
    all_names = [item["name"] for item in manifest["design_spec"]]
    all_outcomes = list(manifest["outcomes"])
    n = int(manifest["n_rows"])
    k_all = len(all_names)
    design_indices, design_names = choose_columns(manifest)
    raw = np.memmap(
        matrix_root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, k_all),
    )
    outcomes = np.memmap(
        matrix_root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcomes)),
    )
    fe_all = np.memmap(
        matrix_root / "fe_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    clusters_all = np.memmap(
        matrix_root / "cluster_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    cluster_mask, sampling = deterministic_physician_cluster_sample(
        clusters_all[:, 0], args.target_rows, args.seed
    )
    selected = np.flatnonzero(cluster_mask)
    x_sample = np.asarray(
        raw[np.ix_(selected, design_indices)], dtype=np.float64
    )
    fe_sample = np.asarray(fe_all[selected, 1:3], dtype=np.uint64)
    cluster_sample = np.asarray(clusters_all[selected, :], dtype=np.uint64)
    singleton_keep = iterative_non_singleton_mask(fe_sample)
    x_sample = x_sample[singleton_keep]
    fe_sample = fe_sample[singleton_keep]
    cluster_sample = cluster_sample[singleton_keep]
    selected = selected[singleton_keep]
    sampling["rows_after_iterative_fe_singleton_removal"] = int(len(selected))
    sampling["iterative_fe_singletons_removed"] = int(
        sampling["realized_rows"] - len(selected)
    )

    physician_name = (
        "physician_black_proxy"
        if args.cohort == "race"
        else "physician_female"
    )
    patient_name = (
        "patient_black" if args.cohort == "race" else "patient_female"
    )
    interaction_name = (
        "race_interaction"
        if args.cohort == "race"
        else "sex_gender_interaction"
    )
    physician_index = design_names.index(physician_name)
    patient_index = design_names.index(patient_name)
    interaction_index = design_names.index(interaction_name)
    outcome_specs = [
        ("los_hours_primary_0_168", "poisson_log", "all"),
        (
            "total_charge_reported_real_2024",
            "gamma_log",
            "positive_only",
        ),
        ("procedure_count_analysis", "poisson_log", "all"),
        ("any_procedure_flag", "binomial_logit", "all"),
        ("routine_discharge_flag", "binomial_logit", "all"),
        ("transfer_flag", "binomial_logit", "all"),
        ("mortality_flag", "binomial_logit", "all"),
        ("home_health_flag", "binomial_logit", "all"),
    ]
    output = args.output.resolve() / args.cohort
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {
        "created_utc": now_utc(),
        "cohort": args.cohort,
        "sampling": sampling,
        "design_columns": design_names,
        "fixed_effects": [
            "facility_by_year_quarter",
            "principal_clinical_category",
        ],
        "primary_models_remain_exact_full_cohort_ols_hdfe": True,
        "nonlinear_models_are_robustness_checks": True,
        "models": {},
    }
    for offset, (outcome_name, family, restriction) in enumerate(outcome_specs):
        y_all = np.asarray(
            outcomes[selected, all_outcomes.index(outcome_name)],
            dtype=np.float64,
        )
        restriction_mask = np.ones(len(y_all), dtype=bool)
        if restriction == "positive_only":
            restriction_mask = y_all > 0
        y = y_all[restriction_mask]
        x = x_sample[restriction_mask]
        fe = fe_sample[restriction_mask]
        clusters = cluster_sample[restriction_mask]
        keep = iterative_non_singleton_mask(fe)
        y, x, fe, clusters = y[keep], x[keep], fe[keep], clusters[keep]
        if family == "binomial_logit" and len(np.unique(y)) != 2:
            diagnostics["models"][outcome_name] = {
                "skipped": True,
                "reason": "Outcome did not contain both binary classes",
            }
            continue
        fit = hdfe_glm(
            x,
            y,
            fe,
            family,
            args.tolerance,
            args.max_iterations,
        )
        covariance, covariance_meta = clustered_covariance(
            fit["x_tilde"],
            y,
            fit["mu"],
            clusters,
            fit["bread_inverse"],
            family,
        )
        pair = marginal_pair_contrast(
            x,
            fit["eta"],
            fit["beta"],
            covariance,
            physician_index,
            patient_index,
            interaction_index,
            family,
        )
        beta_interaction = float(fit["beta"][interaction_index])
        se_interaction = math.sqrt(
            max(float(covariance[interaction_index, interaction_index]), 0)
        )
        z_interaction = (
            beta_interaction / se_interaction
            if se_interaction > 0
            else math.nan
        )
        mean_outcome = float(np.mean(y))
        dispersion = (
            float(
                np.sum(
                    (y - fit["mu"]) ** 2
                    / np.maximum(fit["mu"], 1e-10)
                )
                / max(
                    len(y)
                    - len(design_names)
                    - len(np.unique(fe[:, 0]))
                    - len(np.unique(fe[:, 1]))
                    + 1,
                    1,
                )
            )
            if family == "poisson_log"
            else math.nan
        )
        rows.append(
            {
                "cohort": args.cohort,
                "model_id": "nonlinear_m2_cluster_sample_hdfe",
                "outcome": outcome_name,
                "family_link": family,
                "sample_restriction": restriction,
                "term": interaction_name,
                "link_scale_estimate": beta_interaction,
                "clustered_standard_error": se_interaction,
                "ci95_low": beta_interaction - 1.96 * se_interaction,
                "ci95_high": beta_interaction + 1.96 * se_interaction,
                "p_value": (
                    float(2 * norm.sf(abs(z_interaction)))
                    if math.isfinite(z_interaction)
                    else math.nan
                ),
                "exponentiated_interaction": math.exp(beta_interaction),
                "average_marginal_pair_contrast": pair["estimate"],
                "average_marginal_pair_contrast_se": pair["standard_error"],
                "average_marginal_pair_contrast_ci95_low": pair["ci95_low"],
                "average_marginal_pair_contrast_ci95_high": pair["ci95_high"],
                "average_marginal_pair_contrast_p_value": pair["p_value"],
                "average_marginal_pair_contrast_percent_of_mean": (
                    100 * pair["estimate"] / mean_outcome
                    if mean_outcome != 0
                    else math.nan
                ),
                "outcome_mean": mean_outcome,
                "n": len(y),
                "poisson_pearson_dispersion": dispersion,
                **{
                    f"standardized_cell_mean_{key[-2:]}": value
                    for key, value in pair.items()
                    if key.startswith("cell_mean_")
                },
            }
        )
        diagnostics["models"][outcome_name] = {
            "family_link": family,
            "sample_restriction": restriction,
            "n": len(y),
            "converged": fit["converged"],
            "iterations": fit["iterations"],
            "deviance": fit["deviance"],
            "poisson_pearson_dispersion": dispersion,
            "covariance": covariance_meta,
            "coefficient_order": design_names,
            "coefficient_sha256": hashlib.sha256(
                np.asarray(fit["beta"], dtype=np.float64).tobytes()
            ).hexdigest(),
            "iteration_history": fit["history"],
        }
        del fit, covariance, x, y, fe, clusters

    table = pd.DataFrame(rows)
    table.to_csv(output / "outcome_appropriate_glm_sensitivities.csv", index=False)
    atomic_json(
        output / "outcome_appropriate_glm_diagnostics.json", diagnostics
    )
    atomic_json(
        output / "_SUCCESS.json",
        {
            "created_utc": now_utc(),
            "cohort": args.cohort,
            "rows_in_results": len(table),
            "all_fitted_models_converged": all(
                item.get("converged", False)
                for item in diagnostics["models"].values()
                if not item.get("skipped", False)
            ),
            "deterministic_cluster_sample": sampling,
            **matrix_provenance,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--cohort", choices=("race", "sex_gender"), default="race"
    )
    parser.add_argument("--target-rows", type=int, default=2_000_000)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    validation = validate_engine(args.phase2.resolve() / "qa")
    print(json.dumps(validation, indent=2))
    if args.validate_only:
        return
    if args.matrix_root is None or args.output is None:
        parser.error("--matrix-root and --output are required unless --validate-only")
    estimate_real_data(args)


if __name__ == "__main__":
    main()
