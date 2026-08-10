#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/18_race_threshold_probability_sensitivities.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Run full-cohort physician-race threshold and probability sensitivities."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class RemappedMatrix:
    """Expose selected base columns under alternative logical columns."""

    def __init__(self, base: Any, remap: dict[int, int]) -> None:
        self.base = base
        self.remap = remap
        self.shape = base.shape

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, columns = key
        logical = np.arange(self.shape[1])[columns]
        physical = np.asarray(
            [self.remap.get(int(index), int(index)) for index in np.atleast_1d(logical)]
        )
        result = self.base[rows, :][:, physical]
        return result[:, 0] if np.isscalar(columns) else result


class FilteredMatrix:
    """Row-filtered memory-map view with bounded column reads."""

    def __init__(self, base: Any, row_indices: np.ndarray) -> None:
        self.base = base
        self.row_indices = row_indices
        self.shape = (len(row_indices), base.shape[1])

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, columns = key
        original_rows = np.atleast_1d(self.row_indices[rows])
        logical_columns = np.arange(self.shape[1])[columns]
        if np.isscalar(logical_columns):
            return self.base[original_rows, int(logical_columns)]
        return self.base[np.ix_(original_rows, np.asarray(logical_columns))]


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
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--row-chunk", type=int, default=250_000)
    parser.add_argument("--block-columns", type=int, default=4)
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
    n = int(manifest["n_rows"])
    names = [item["name"] for item in manifest["design_spec"]]
    groups = [item["group"] for item in manifest["design_spec"]]
    outcomes_names = list(manifest["outcomes"])
    k = len(names)
    raw = np.memmap(
        root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, k),
    )
    outcomes = np.memmap(
        root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(outcomes_names)),
    )
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
    results = []
    diagnostics = {}

    hard_physician = names.index("physician_black_proxy")
    hard_interaction = names.index("race_interaction")
    probability_physician = names.index("physician_black_probability")
    probability_interaction = names.index("race_probability_interaction")
    probability_raw = RemappedMatrix(
        raw,
        {
            hard_physician: probability_physician,
            hard_interaction: probability_interaction,
        },
    )
    result, diagnostic = engine.run_model(
        "m2_probability_weighted_physician_race",
        base_columns,
        names,
        probability_raw,
        outcomes,
        fe,
        clusters,
        [1, 2],
        args.scratch.resolve() / "race_sensitivities",
        args.output.resolve() / "race_sensitivities",
        args.row_chunk,
        args.block_columns,
        1e-8,
        args.bootstrap_draws,
        args.seed,
        "race",
        outcomes_names,
        None,
        None,
    )
    result["sensitivity_definition"] = (
        "conditional Black probability = pBlack/(pBlack+pWhite), Florida "
        "physician prior, same primary t50 cohort"
    )
    results.append(result)
    diagnostics["probability_weighted"] = diagnostic

    population_probability_physician = names.index(
        "physician_black_probability_population_prior"
    )
    population_probability_interaction = names.index(
        "race_probability_interaction_population_prior"
    )
    population_probability_raw = RemappedMatrix(
        raw,
        {
            hard_physician: population_probability_physician,
            hard_interaction: population_probability_interaction,
        },
    )
    result, diagnostic = engine.run_model(
        "m2_probability_weighted_physician_race_population_prior",
        base_columns,
        names,
        population_probability_raw,
        outcomes,
        fe,
        clusters,
        [1, 2],
        args.scratch.resolve() / "race_sensitivities",
        args.output.resolve() / "race_sensitivities",
        args.row_chunk,
        args.block_columns,
        1e-8,
        args.bootstrap_draws,
        args.seed + 1_000,
        "race",
        outcomes_names,
        None,
        None,
    )
    result["sensitivity_definition"] = (
        "conditional Black probability = pBlack/(pBlack+pWhite), official "
        "wru national 2020 population prior, same primary t50 cohort"
    )
    results.append(result)
    diagnostics["probability_weighted_population_prior"] = diagnostic

    for threshold, selection_name in (
        (0.70, "eligible_t70"),
        (0.80, "eligible_t80"),
        (0.90, "eligible_t90"),
    ):
        selection_column = names.index(selection_name)
        row_indices = np.flatnonzero(
            np.asarray(raw[:, selection_column], dtype=np.float64) == 1
        ).astype(np.int64)
        filtered_raw = FilteredMatrix(raw, row_indices)
        filtered_outcomes = FilteredMatrix(outcomes, row_indices)
        filtered_fe = FilteredMatrix(fe, row_indices)
        filtered_clusters = np.empty(
            (len(row_indices), 3), dtype=np.uint64
        )
        for dimension in range(3):
            values = np.asarray(
                clusters[row_indices, dimension], dtype=np.uint64
            )
            _, inverse = np.unique(values, return_inverse=True)
            filtered_clusters[:, dimension] = inverse.astype(np.uint64)
        model_id = f"m2_race_proxy_threshold_t{int(threshold * 100)}"
        result, diagnostic = engine.run_model(
            model_id,
            base_columns,
            names,
            filtered_raw,
            filtered_outcomes,
            filtered_fe,
            filtered_clusters,
            [1, 2],
            args.scratch.resolve() / "race_sensitivities",
            args.output.resolve() / "race_sensitivities",
            args.row_chunk,
            args.block_columns,
            1e-8,
            args.bootstrap_draws,
            args.seed + int(threshold * 100),
            "race",
            outcomes_names,
            None,
            None,
        )
        result["sensitivity_definition"] = (
            f"maximum full-name proxy probability >= {threshold:.2f}"
        )
        results.append(result)
        diagnostics[f"threshold_{threshold:.2f}"] = diagnostic

    combined = pd.concat(results, ignore_index=True)
    output = args.output.resolve() / "race_sensitivities"
    output.mkdir(parents=True, exist_ok=True)
    combined.to_csv(
        output / "race_threshold_probability_coefficients.csv", index=False
    )
    interaction = combined.loc[combined["term"] == "race_interaction"].copy()
    interaction.to_csv(
        output / "race_threshold_probability_interactions.csv", index=False
    )
    summary = {
        "status": "PASS",
        "full_cohort_models": True,
        "probability_sensitivity_sample": (
            "Same complete primary t50 cohort; this isolates probability "
            "coding and prior choice from changes in cohort membership."
        ),
        "model_ids": sorted(combined["model_id"].unique().tolist()),
        "interaction_rows": len(interaction),
        "physician_race_measure": (
            "Bayesian full-name analytical proxy; probability model is not "
            "self-reported physician identity."
        ),
        "prior_sensitivities": {
            "primary": "AAMC 2020 Florida active-physician prior",
            "mandatory_alternative": (
                "official wru national 2020 population prior, evaluated as "
                "a continuous Black/White probability exposure on the same "
                "primary t50 cohort"
            ),
        },
        **matrix_provenance,
    }
    (output / "race_threshold_probability_manifest.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
