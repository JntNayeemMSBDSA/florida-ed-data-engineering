#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/19_heterogeneity_models.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Estimate prespecified full-cohort heterogeneity in primary concordance effects."""

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


class CombinedMatrix:
    def __init__(self, left: Any, right: Any) -> None:
        if left.shape[0] != right.shape[0]:
            raise ValueError("Combined matrices must have the same row count")
        self.left = left
        self.right = right
        self.left_k = left.shape[1]
        self.shape = (left.shape[0], left.shape[1] + right.shape[1])

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, columns = key
        logical = np.arange(self.shape[1])[columns]
        logical_array = np.atleast_1d(logical)
        blocks = []
        for column in logical_array:
            if column < self.left_k:
                blocks.append(np.asarray(self.left[rows, int(column)]))
            else:
                blocks.append(
                    np.asarray(self.right[rows, int(column - self.left_k)])
                )
        result = np.column_stack(blocks)
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
    primary_outcome_names = list(manifest["primary_outcomes"])
    primary_outcome_indices = [
        all_outcomes.index(name) for name in primary_outcome_names
    ]
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
    y = ColumnView(all_y, primary_outcome_indices)
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
    primary_model_id = "m2_fully_adjusted_facility_yq_clinical_fe"
    primary_folder = (
        args.primary_scratch.resolve()
        / args.cohort
        / primary_model_id
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
    base_y = ColumnView(base_y_all, primary_outcome_indices)
    primary_interaction = (
        "race_interaction"
        if args.cohort == "race"
        else "sex_gender_interaction"
    )
    modifiers = [
        "symptom_sign",
        "ed_specialist",
        "age65plus",
        "high_comorbidity",
        "icd10_era",
        "high_experience",
        "high_physician_volume",
        "facility_rural",
        "facility_for_profit",
    ]
    if args.cohort == "race":
        modifiers.insert(1, "uninsured")

    result_frames = []
    manifest_rows = []
    for index, modifier in enumerate(modifiers):
        group = f"heterogeneity_{modifier}"
        modifier_columns = [
            position
            for position, candidate in enumerate(groups)
            if candidate == group
        ]
        modifier_names = [names[position] for position in modifier_columns]
        x_modifier, _, demeaning_meta = engine.residualize(
            raw,
            y,
            fe,
            modifier_columns,
            [1, 2],
            args.scratch.resolve() / args.cohort / modifier,
            4,
            1e-8,
            matrix_provenance,
        )
        combined_x = CombinedMatrix(base_x, x_modifier)
        combined_names = [*base_names, *modifier_names]
        target = f"{modifier}_x_interaction"
        model_id = f"m2_heterogeneity_{modifier}"
        result, diagnostic = engine.run_model(
            model_id,
            list(range(len(combined_names))),
            combined_names,
            combined_x,
            y,
            fe,
            clusters,
            [1, 2],
            args.scratch.resolve() / args.cohort / "unused",
            args.output.resolve() / args.cohort,
            args.row_chunk,
            4,
            1e-8,
            args.bootstrap_draws,
            args.seed + index,
            args.cohort,
            primary_outcome_names,
            target,
            [primary_interaction, target],
            (combined_x, base_y, demeaning_meta),
        )
        result["heterogeneity_modifier"] = modifier
        result["heterogeneity_interpretation"] = (
            "Coefficient on modifier_x_interaction is the difference in the "
            "four-cell concordance contrast between modifier=1 and modifier=0."
        )
        result_frames.append(result)
        manifest_rows.append(
            {
                "modifier": modifier,
                "model_id": model_id,
                "target_term": target,
                "n": diagnostic["n"],
                "rank": diagnostic["explicit_design_rank"],
                "condition_number": diagnostic["xtx_condition_number"],
                "converged": diagnostic["demeaning"]["converged"],
            }
        )

    combined = pd.concat(result_frames, ignore_index=True)
    output = args.output.resolve() / args.cohort
    output.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output / "heterogeneity_model_coefficients.csv", index=False)
    targets = combined.loc[
        combined["term"].str.endswith("_x_interaction")
    ].copy()
    targets.to_csv(output / "heterogeneity_interaction_differences.csv", index=False)
    pd.DataFrame(manifest_rows).to_csv(
        output / "heterogeneity_model_manifest.csv", index=False
    )
    summary = {
        "status": "PASS",
        "cohort": args.cohort,
        "modifiers": modifiers,
        "primary_outcomes_only": primary_outcome_names,
        "confirmatory": False,
        "multiple_testing": "Benjamini-Hochberg within heterogeneity family",
        "clinical_classification_status": (
            "Presentation modifier is provisional and evidence-informed; "
            "clinician review remains required."
        ),
        **matrix_provenance,
    }
    (output / "heterogeneity_manifest.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
