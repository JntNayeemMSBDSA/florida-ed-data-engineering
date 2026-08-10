#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/23_race_proxy_multiple_imputation.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Twenty physician-level probabilistic race-proxy imputations with Rubin pooling."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import t as student_t


class ColumnView:
    def __init__(self, base: Any, columns: list[int]) -> None:
        self.base = base
        self.columns = np.asarray(columns, dtype=np.int64)
        self.shape = (base.shape[0], len(columns))

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, local_columns = key
        selected = self.columns[local_columns]
        return self.base[rows, :][:, selected]


class OverrideMatrix:
    def __init__(
        self,
        base: Any,
        override: Any,
        position_map: dict[int, int],
    ) -> None:
        self.base = base
        self.override = override
        self.position_map = position_map
        self.shape = base.shape

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, columns = key
        logical = np.arange(self.shape[1])[columns]
        logical_array = np.atleast_1d(logical)
        result = np.asarray(self.base[rows, :][:, logical_array]).copy()
        for output_column, logical_column in enumerate(logical_array):
            if int(logical_column) in self.position_map:
                result[:, output_column] = self.override[
                    rows, self.position_map[int(logical_column)]
                ]
        return result[:, 0] if np.isscalar(logical) else result


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
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--primary-scratch", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--imputations", type=int, default=20)
    parser.add_argument("--row-chunk", type=int, default=250_000)
    parser.add_argument("--bootstrap-draws", type=int, default=9_999)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    engine = load_engine(phase2 / "scripts" / "08_estimate_primary_models.py")
    root = (args.matrix_root / "race").resolve()
    matrix_manifest_path = root / "matrix_manifest.json"
    manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    matrix_provenance = engine.matrix_binding_provenance(
        manifest, matrix_manifest_path
    )
    names = [item["name"] for item in manifest["design_spec"]]
    groups = [item["group"] for item in manifest["design_spec"]]
    all_outcomes = list(manifest["outcomes"])
    primary_outcomes = list(manifest["primary_outcomes"])
    primary_indices = [all_outcomes.index(name) for name in primary_outcomes]
    n = int(manifest["n_rows"])
    k = len(names)
    raw = np.memmap(
        root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, k),
    )
    all_y = np.memmap(
        root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcomes)),
    )
    y = ColumnView(all_y, primary_indices)
    fe = np.memmap(
        root / "fe_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    clusters = np.memmap(
        root / "cluster_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    base_columns = [
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
    base_names = [names[index] for index in base_columns]
    primary_folder = (
        args.primary_scratch.resolve()
        / "race"
        / "m2_fully_adjusted_facility_yq_clinical_fe"
    )
    base_x = np.memmap(
        primary_folder / "demeaned_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(base_columns)),
    )
    base_y_all = np.memmap(
        primary_folder / "demeaned_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcomes)),
    )
    base_y = ColumnView(base_y_all, primary_indices)
    hard_physician_position = base_names.index("physician_black_proxy")
    hard_interaction_position = base_names.index("race_interaction")
    probability_column = names.index("physician_black_probability")
    patient_column = names.index("patient_black")
    physician_codes = clusters[:, 0]
    physician_count = int(np.max(physician_codes)) + 1
    probabilities = np.full(physician_count, np.nan, dtype=np.float64)
    for start in range(0, n, args.row_chunk):
        stop = min(n, start + args.row_chunk)
        codes = np.asarray(physician_codes[start:stop], dtype=np.int64)
        values = np.asarray(
            raw[start:stop, probability_column], dtype=np.float64
        )
        probabilities[codes] = values
    if np.isnan(probabilities).any():
        raise RuntimeError("Missing physician probability after cluster mapping")
    probabilities_sha256 = hashlib.sha256(
        np.ascontiguousarray(probabilities).tobytes()
    ).hexdigest()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = args.scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    all_results = []
    for imputation in range(1, args.imputations + 1):
        imputation_folder = scratch / f"imputation={imputation:02d}"
        imputation_folder.mkdir(parents=True, exist_ok=True)
        raw_exposure_path = imputation_folder / "raw_exposure.float64.mmap"
        raw_exposure = np.memmap(
            raw_exposure_path,
            dtype=np.float64,
            mode=(
                "r+"
                if raw_exposure_path.exists()
                and raw_exposure_path.stat().st_size == n * 2 * 8
                else "w+"
            ),
            shape=(n, 2),
        )
        assignment_path = imputation_folder / "physician_assignment.uint8.npy"
        assignment_manifest_path = (
            imputation_folder / "physician_assignment_manifest.json"
        )
        assignment_reusable = False
        if assignment_path.exists() and assignment_manifest_path.exists():
            assignment_manifest = json.loads(
                assignment_manifest_path.read_text(encoding="utf-8")
            )
            assignment_reusable = (
                assignment_manifest.get("imputation") == imputation
                and assignment_manifest.get("seed") == args.seed
                and assignment_manifest.get("probabilities_sha256")
                == probabilities_sha256
                and all(
                    assignment_manifest.get(key) == value
                    for key, value in matrix_provenance.items()
                )
                and assignment_manifest.get("assignment_sha256")
                == engine.sha256_file(assignment_path)
            )
        if assignment_reusable:
            physician_assignment = np.load(assignment_path)
        else:
            imputation_rng = np.random.default_rng(
                np.random.SeedSequence([args.seed, imputation])
            )
            physician_assignment = imputation_rng.binomial(
                1, probabilities
            ).astype(np.uint8)
            np.save(assignment_path, physician_assignment)
            engine.atomic_json(
                assignment_manifest_path,
                {
                    "imputation": imputation,
                    "seed": args.seed,
                    "physician_count": physician_count,
                    "probabilities_sha256": probabilities_sha256,
                    "assignment_sha256": engine.sha256_file(
                        assignment_path
                    ),
                    **matrix_provenance,
                },
            )
        if (
            physician_assignment.shape != (physician_count,)
            or not np.isin(physician_assignment, [0, 1]).all()
        ):
            raise RuntimeError(
                "Physician-level imputation assignment is invalid"
            )
        for start in range(0, n, args.row_chunk):
            stop = min(n, start + args.row_chunk)
            codes = np.asarray(
                physician_codes[start:stop], dtype=np.int64
            )
            physician = physician_assignment[codes].astype(np.float64)
            patient = np.asarray(
                raw[start:stop, patient_column], dtype=np.float64
            )
            raw_exposure[start:stop, 0] = physician
            raw_exposure[start:stop, 1] = physician * patient
        raw_exposure.flush()

        x_imputed, _, demeaning_meta = engine.residualize(
            raw_exposure,
            y,
            fe,
            [0, 1],
            [1, 2],
            imputation_folder / "demeaned",
            2,
            1e-8,
            matrix_provenance,
        )
        combined = OverrideMatrix(
            base_x,
            x_imputed,
            {
                hard_physician_position: 0,
                hard_interaction_position: 1,
            },
        )
        model_id = f"m2_race_proxy_mi_{imputation:02d}"
        result, _ = engine.run_model(
            model_id,
            list(range(len(base_names))),
            base_names,
            combined,
            y,
            fe,
            clusters,
            [1, 2],
            imputation_folder / "unused",
            output / "imputations",
            args.row_chunk,
            2,
            1e-8,
            args.bootstrap_draws,
            args.seed + imputation,
            "race",
            primary_outcomes,
            "race_interaction",
            ["race_interaction"],
            (combined, base_y, demeaning_meta),
        )
        result["imputation"] = imputation
        result["probability_definition"] = (
            "pBlack/(pBlack+pWhite), one Bernoulli draw per attending NPI"
        )
        all_results.append(result.loc[result["term"] == "race_interaction"])

    estimates = pd.concat(all_results, ignore_index=True)
    estimates.to_csv(output / "race_proxy_mi_interaction_estimates.csv", index=False)
    pooled_rows = []
    for outcome, block in estimates.groupby("outcome"):
        q = block["estimate"].to_numpy(float)
        u = np.square(block["clustered_standard_error"].to_numpy(float))
        m = len(block)
        q_bar = float(q.mean())
        u_bar = float(u.mean())
        between = float(q.var(ddof=1))
        total_variance = u_bar + (1 + 1 / m) * between
        se = math.sqrt(total_variance)
        if between > 0:
            degrees_freedom = (m - 1) * (
                1 + u_bar / ((1 + 1 / m) * between)
            ) ** 2
        else:
            degrees_freedom = math.inf
        critical = (
            float(student_t.ppf(0.975, degrees_freedom))
            if math.isfinite(degrees_freedom)
            else 1.95996398454
        )
        statistic = q_bar / se if se > 0 else math.nan
        p_value = (
            float(
                2
                * student_t.sf(
                    abs(statistic),
                    degrees_freedom if math.isfinite(degrees_freedom) else 1e9,
                )
            )
            if math.isfinite(statistic)
            else math.nan
        )
        pooled_rows.append(
            {
                "outcome": outcome,
                "term": "race_interaction",
                "estimate_pooled": q_bar,
                "standard_error_pooled": se,
                "ci95_low": q_bar - critical * se,
                "ci95_high": q_bar + critical * se,
                "p_value": p_value,
                "within_imputation_variance": u_bar,
                "between_imputation_variance": between,
                "total_variance": total_variance,
                "rubin_degrees_freedom": degrees_freedom,
                "relative_increase_variance": (
                    (1 + 1 / m) * between / u_bar if u_bar > 0 else math.nan
                ),
                "imputations": m,
                "n_each_imputation": int(block["n"].iloc[0]),
            }
        )
    pooled = pd.DataFrame(pooled_rows)
    pooled.to_csv(output / "race_proxy_mi_pooled_results.csv", index=False)
    summary = {
        "status": "PASS",
        "imputations": args.imputations,
        "imputation_level": "attending_npi",
        "full_primary_cohort_each_imputation": True,
        "pooling": "Rubin rules using multiway-clustered within-imputation variances",
        "interpretation": (
            "Probabilistic sensitivity for full-name proxy classification "
            "uncertainty; not imputation of self-reported physician identity."
        ),
        **matrix_provenance,
    }
    (output / "race_proxy_mi_manifest.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
