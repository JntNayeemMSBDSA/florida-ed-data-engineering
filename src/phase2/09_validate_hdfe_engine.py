#!/usr/bin/env python3
# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/09_validate_hdfe_engine.py
# This validator uses synthetic data and command-line runtime paths.

"""Validate the custom out-of-core HDFE path against pyfixest on synthetic data."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyfixest as pf


def load_engine(script_path: Path):
    spec = importlib.util.spec_from_file_location("phase2_hdfe_engine", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load HDFE engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    scratch = args.scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    engine = load_engine(phase2 / "scripts" / "08_estimate_primary_models.py")
    rng = np.random.default_rng(20260726)
    n = 50_000
    physician = rng.integers(0, 600, size=n, dtype=np.uint64)
    facility = rng.integers(0, 40, size=n, dtype=np.uint64)
    clinical = rng.integers(0, 80, size=n, dtype=np.uint64)
    facility_time = (
        facility * 20 + rng.integers(0, 20, size=n, dtype=np.uint64)
    )
    physician_facility_pairs = pd.factorize(
        pd.Series(physician.astype(str))
        + "|"
        + pd.Series(facility.astype(str)),
        sort=False,
    )[0].astype(np.uint64)
    x1 = rng.normal(size=n)
    x2 = rng.binomial(1, 0.35, size=n).astype(float)
    x3 = x1 * x2
    physician_effect = rng.normal(scale=0.5, size=int(physician.max()) + 1)
    facility_time_effect = rng.normal(
        scale=0.4, size=int(facility_time.max()) + 1
    )
    clinical_effect = rng.normal(scale=0.2, size=int(clinical.max()) + 1)
    error = rng.normal(size=n)
    y = (
        0.4 * x1
        - 0.2 * x2
        + 0.75 * x3
        + physician_effect[physician]
        + facility_time_effect[facility_time]
        + clinical_effect[clinical]
        + error
    )

    raw_path = scratch / "raw.mmap"
    y_path = scratch / "y.mmap"
    fe_path = scratch / "fe.mmap"
    cluster_path = scratch / "cluster.mmap"
    raw = np.memmap(raw_path, dtype=np.float64, mode="w+", shape=(n, 3))
    outcomes = np.memmap(y_path, dtype=np.float64, mode="w+", shape=(n, 1))
    fe_codes = np.memmap(fe_path, dtype=np.uint64, mode="w+", shape=(n, 3))
    clusters = np.memmap(
        cluster_path, dtype=np.uint64, mode="w+", shape=(n, 3)
    )
    raw[:, :] = np.column_stack([x1, x2, x3])
    outcomes[:, 0] = y
    fe_codes[:, :] = np.column_stack([physician, facility_time, clinical])
    clusters[:, :] = np.column_stack(
        [physician, facility, physician_facility_pairs]
    )
    for mmap in (raw, outcomes, fe_codes, clusters):
        mmap.flush()

    x_tilde, y_tilde, demean_meta = engine.residualize(
        raw,
        outcomes,
        fe_codes,
        [0, 1, 2],
        [0, 1, 2],
        scratch / "demeaned",
        2,
        1e-10,
    )
    xtx, xty, _, _ = engine.crossproducts(x_tilde, y_tilde, 10_000)
    beta = np.linalg.solve(xtx, xty)[:, 0]
    bread = np.linalg.inv(xtx)
    custom_vcov, custom_meta, _ = engine.selected_cluster_covariance(
        x_tilde,
        y_tilde,
        beta[:, None],
        bread,
        clusters,
        [0, 1, 2],
        10_000,
        20260726,
        999,
    )
    custom_se = np.sqrt(np.diag(custom_vcov[0]))

    frame = pd.DataFrame(
        {
            "y": y,
            "x1": x1,
            "x2": x2,
            "x3": x3,
            "physician": physician,
            "facility_time": facility_time,
            "clinical": clinical,
            "facility": facility,
        }
    )
    reference = pf.feols(
        "y ~ x1 + x2 + x3 | physician + facility_time + clinical",
        data=frame,
        vcov={"CRV1": "physician + facility"},
        demeaner=pf.MapDemeaner(fixef_tol=1e-10, backend="rust"),
    )
    reference_beta = reference.coef().loc[["x1", "x2", "x3"]].to_numpy()
    reference_se = reference.se().loc[["x1", "x2", "x3"]].to_numpy()
    coefficient_max_abs_difference = float(
        np.max(np.abs(beta - reference_beta))
    )
    se_max_relative_difference = float(
        np.max(np.abs(custom_se - reference_se) / reference_se)
    )

    checks = [
        {
            "check": "demeaning_converged",
            "passed": bool(demean_meta["converged"]),
            "observed": demean_meta["converged"],
            "tolerance": "True",
        },
        {
            "check": "coefficients_match_pyfixest",
            "passed": bool(coefficient_max_abs_difference < 1e-8),
            "observed": coefficient_max_abs_difference,
            "tolerance": "<1e-8",
        },
        {
            "check": "multiway_cluster_se_matches_pyfixest",
            "passed": bool(se_max_relative_difference < 0.01),
            "observed": se_max_relative_difference,
            "tolerance": "<1% (allows documented finite-sample convention difference)",
        },
        {
            "check": "interaction_recovery",
            "passed": bool(abs(beta[2] - 0.75) < 0.08),
            "observed": float(beta[2]),
            "tolerance": "within 0.08 of data-generating value 0.75",
        },
    ]
    report = {
        "status": "PASS" if all(item["passed"] for item in checks) else "FAIL",
        "n": n,
        "checks": checks,
        "custom_coefficients": dict(zip(["x1", "x2", "x3"], beta.tolist())),
        "pyfixest_coefficients": dict(
            zip(["x1", "x2", "x3"], reference_beta.tolist())
        ),
        "custom_cluster_se": dict(
            zip(["x1", "x2", "x3"], custom_se.tolist())
        ),
        "pyfixest_cluster_se": dict(
            zip(["x1", "x2", "x3"], reference_se.tolist())
        ),
        "custom_covariance_metadata": custom_meta,
    }
    qa = phase2 / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    (qa / "hdfe_engine_validation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    pd.DataFrame(checks).to_csv(
        qa / "hdfe_engine_validation_checks.csv", index=False
    )
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise SystemExit("HDFE engine validation failed")


if __name__ == "__main__":
    main()
