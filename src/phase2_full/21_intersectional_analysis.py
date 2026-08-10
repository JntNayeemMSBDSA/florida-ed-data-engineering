#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/21_intersectional_analysis.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Exploratory full-cohort race-by-recorded-sex/physician-gender analysis."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


class FilteredMatrix:
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


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
    selection = names.index("intersectional_eligible")
    row_indices = np.flatnonzero(
        np.asarray(raw[:, selection], dtype=np.float64) == 1
    ).astype(np.int64)
    filtered_raw = FilteredMatrix(raw, row_indices)
    # Expose only the two primary outcomes.
    class OutcomeView:
        shape = (len(row_indices), len(primary_indices))

        def __getitem__(self, key: Any) -> np.ndarray:
            rows, columns = key
            selected = np.asarray(primary_indices)[columns]
            return all_y[
                np.ix_(
                    np.atleast_1d(row_indices[rows]),
                    np.atleast_1d(selected),
                )
            ]

    y = OutcomeView()
    filtered_fe = FilteredMatrix(fe, row_indices)
    filtered_clusters = np.empty((len(row_indices), 3), dtype=np.uint64)
    for dimension in range(3):
        values = np.asarray(clusters[row_indices, dimension], dtype=np.uint64)
        _, inverse = np.unique(values, return_inverse=True)
        filtered_clusters[:, dimension] = inverse.astype(np.uint64)

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
    intersection_columns = [
        index for index, group in enumerate(groups) if group == "intersectional"
    ]
    columns = [*base_columns, *intersection_columns]
    target = "intersection_four_way"
    result, diagnostic = engine.run_model(
        "m2_exploratory_intersectional_four_way",
        columns,
        names,
        filtered_raw,
        y,
        filtered_fe,
        filtered_clusters,
        [1, 2],
        args.scratch.resolve() / "intersectional",
        args.output.resolve(),
        args.row_chunk,
        4,
        1e-8,
        args.bootstrap_draws,
        args.seed,
        "race",
        primary_outcomes,
        target,
        ["race_interaction", "intersection_female_pair", target],
        None,
    )
    result["analysis_tier"] = "exploratory"
    result["interpretation_note"] = (
        "The four-way term tests whether the racial four-cell interaction "
        "differs across physician-gender by recorded-patient-sex cells; it "
        "does not identify a causal mechanism."
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    result.to_csv(output / "intersectional_model_coefficients.csv", index=False)

    core_glob = (
        phase2
        / "analysis_data"
        / "concordance_visit_data_provider_v2"
        / "visit_year=*"
        / "visit_quarter=*"
        / "concordance_visit_core.parquet"
    )
    con = duckdb.connect()
    descriptive = con.execute(
        f"""
        SELECT
            race_pair_category,
            sex_gender_pair_category,
            count(*) AS n,
            avg(los_hours_primary_0_168) AS los_mean,
            avg(total_charge_reported_real_2024) AS real_charge_mean,
            avg(any_procedure_flag::DOUBLE) AS any_procedure_rate,
            avg(mortality_flag::DOUBLE) AS mortality_rate
        FROM read_parquet('{qpath(core_glob)}', hive_partitioning=false)
        WHERE race_primary_eligible_t50_flag = 1
          AND sex_gender_primary_eligible_flag = 1
          AND los_hours_primary_0_168 IS NOT NULL
          AND total_charge_reported_real_2024 IS NOT NULL
        GROUP BY race_pair_category, sex_gender_pair_category
        ORDER BY race_pair_category, sex_gender_pair_category
        """
    ).fetchdf()
    con.close()
    descriptive.to_csv(output / "intersectional_16_cell_descriptive.csv", index=False)
    summary = {
        "status": "PASS",
        "analysis_tier": "exploratory",
        "n": len(row_indices),
        "sixteen_cells_observed": len(descriptive),
        "target": target,
        "multiple_testing_family": "exploratory_intersectional",
        "measurement_warning": (
            "Combines recorded patient race/ethnicity and sex with the "
            "provider-v2 full-name physician race probability proxy and "
            "physician gender category; none should be essentialized, treated "
            "as self-identified race, or interpreted as gender identity."
        ),
        "model_rank": diagnostic["explicit_design_rank"],
        **matrix_provenance,
    }
    (output / "intersectional_manifest.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
