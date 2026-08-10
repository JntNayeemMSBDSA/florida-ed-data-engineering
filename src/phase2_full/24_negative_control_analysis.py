#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/24_negative_control_analysis.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Temporal-arrival negative-control outcome analysis on the full primary cohorts."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class ColumnView:
    def __init__(self, base: Any, columns: list[int]) -> None:
        self.base = base
        self.columns = np.asarray(columns, dtype=np.int64)
        self.shape = (base.shape[0], len(columns))

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, local_columns = key
        selected = self.columns[local_columns]
        return self.base[rows, :][:, selected]


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
    parser.add_argument("--cohort", required=True, choices=("race", "sex_gender"))
    parser.add_argument("--row-chunk", type=int, default=250_000)
    parser.add_argument("--bootstrap-draws", type=int, default=9_999)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    engine = load_engine(phase2 / "scripts" / "08_estimate_primary_models.py")
    root = (args.matrix_root / args.cohort).resolve()
    matrix_manifest_path = root / "matrix_manifest.json"
    manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    matrix_provenance = engine.matrix_binding_provenance(
        manifest, matrix_manifest_path
    )
    names = [item["name"] for item in manifest["design_spec"]]
    groups = [item["group"] for item in manifest["design_spec"]]
    all_outcomes = list(manifest["outcomes"])
    n = int(manifest["n_rows"])
    k = len(names)
    raw = np.memmap(
        root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, k),
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
    base_names = [names[index] for index in base_columns]
    weekend_local = base_names.index("weekend")
    weekend_missing_local = base_names.index("weekend_missing")
    negative_control_keep = [
        index
        for index in range(len(base_names))
        if index not in (weekend_local, weekend_missing_local)
    ]
    negative_names = [base_names[index] for index in negative_control_keep]
    primary_folder = (
        args.primary_scratch.resolve()
        / args.cohort
        / "m2_fully_adjusted_facility_yq_clinical_fe"
    )
    base_x_all = np.memmap(
        primary_folder / "demeaned_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(base_columns)),
    )
    base_x = ColumnView(base_x_all, negative_control_keep)
    weekend_raw = ColumnView(raw, [names.index("weekend")])
    _, weekend_tilde, demeaning_meta = engine.residualize(
        raw,
        weekend_raw,
        fe,
        [names.index("weekend")],
        [1, 2],
        args.scratch.resolve() / args.cohort,
        1,
        1e-8,
        matrix_provenance,
    )
    interaction = (
        "race_interaction"
        if args.cohort == "race"
        else "sex_gender_interaction"
    )
    result, diagnostic = engine.run_model(
        "m2_negative_control_weekend_arrival",
        list(range(len(negative_names))),
        negative_names,
        base_x,
        weekend_raw,
        fe,
        clusters,
        [1, 2],
        args.scratch.resolve() / args.cohort / "unused",
        args.output.resolve() / args.cohort,
        args.row_chunk,
        1,
        1e-8,
        args.bootstrap_draws,
        args.seed,
        args.cohort,
        ["weekend_arrival_flag_negative_control"],
        interaction,
        [interaction],
        (base_x, weekend_tilde, demeaning_meta),
    )
    result["analysis_role"] = "negative_control_outcome"
    result["interpretation_note"] = (
        "Physician concordance cannot plausibly cause whether the patient "
        "arrived on a weekend. A nonzero association is evidence of residual "
        "sorting/selection, not a treatment effect."
    )
    output = args.output.resolve() / args.cohort
    output.mkdir(parents=True, exist_ok=True)
    result.to_csv(output / "negative_control_coefficients.csv", index=False)
    summary = {
        "status": "PASS",
        "cohort": args.cohort,
        "outcome": "weekend arrival",
        "target": interaction,
        "n": diagnostic["n"],
        "causal_interpretation": False,
        "purpose": "residual sorting and model-specification diagnostic",
        **matrix_provenance,
    }
    (output / "negative_control_manifest.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
