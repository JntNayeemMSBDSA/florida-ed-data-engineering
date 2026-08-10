#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/19b_payer_category_heterogeneity.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Estimate prespecified payer-category heterogeneity for race concordance."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PAYER_LEVELS = (
    "Medicaid",
    "Medicare",
    "Self-pay",
    "Non-payment/charity",
    "Other government",
    "Federal government",
    "Workers compensation",
    "Liability",
    "Other",
    "Unknown",
    "<MISSING>",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "missing"


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_engine(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "phase2_hdfe_engine_payer", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load HDFE engine from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ColumnView:
    def __init__(self, base: Any, columns: list[int]) -> None:
        self.base = base
        self.columns = np.asarray(columns, dtype=np.int64)
        self.shape = (base.shape[0], len(columns))

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, local_columns = key
        selected = self.columns[local_columns]
        return self.base[rows, :][:, selected]


class InteractionMatrix:
    """Virtual saturated payer-by-exposure interaction matrix."""

    def __init__(
        self,
        raw: Any,
        payer_indices: list[int],
        physician_index: int,
        patient_index: int,
        interaction_index: int,
    ) -> None:
        self.raw = raw
        self.payer_indices = payer_indices
        self.physician_index = physician_index
        self.patient_index = patient_index
        self.interaction_index = interaction_index
        self.shape = (raw.shape[0], 3 * len(payer_indices))

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, columns = key
        logical = np.arange(self.shape[1])[columns]
        logical_array = np.atleast_1d(logical)
        physician = np.asarray(
            self.raw[rows, self.physician_index], dtype=np.float64
        )
        patient = np.asarray(
            self.raw[rows, self.patient_index], dtype=np.float64
        )
        interaction = np.asarray(
            self.raw[rows, self.interaction_index], dtype=np.float64
        )
        blocks: list[np.ndarray] = []
        for column in logical_array:
            payer_position, interaction_type = divmod(int(column), 3)
            payer = np.asarray(
                self.raw[rows, self.payer_indices[payer_position]],
                dtype=np.float64,
            )
            base = (physician, patient, interaction)[interaction_type]
            blocks.append(payer * base)
        result = np.column_stack(blocks)
        return result[:, 0] if np.isscalar(logical) else result


class CombinedMatrix:
    def __init__(self, left: Any, right: Any) -> None:
        if left.shape[0] != right.shape[0]:
            raise ValueError("Combined matrices must share their row count")
        self.left = left
        self.right = right
        self.left_k = left.shape[1]
        self.shape = (left.shape[0], left.shape[1] + right.shape[1])

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, columns = key
        logical = np.arange(self.shape[1])[columns]
        logical_array = np.atleast_1d(logical)
        blocks: list[np.ndarray] = []
        for column in logical_array:
            if column < self.left_k:
                blocks.append(np.asarray(self.left[rows, int(column)]))
            else:
                blocks.append(
                    np.asarray(
                        self.right[rows, int(column - self.left_k)]
                    )
                )
        result = np.column_stack(blocks)
        return result[:, 0] if np.isscalar(logical) else result


def residualize_design_only(
    engine: Any,
    raw_interactions: InteractionMatrix,
    fe_all: np.memmap,
    folder: Path,
    tolerance: float,
    checkpoint_binding: dict[str, Any],
    block_columns: int = 3,
) -> tuple[np.memmap, dict[str, Any]]:
    folder.mkdir(parents=True, exist_ok=True)
    n, k = raw_interactions.shape
    path = folder / "demeaned_payer_interactions.float64.mmap"
    state_path = folder / "demeaning_state.json"
    if path.exists() and state_path.exists() and path.stat().st_size == n * k * 8:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (
            state.get("n_rows") == n
            and state.get("n_columns") == k
            and state.get("converged") is True
            and state.get("checkpoint_binding") == checkpoint_binding
        ):
            return (
                np.memmap(
                    path,
                    dtype=np.float64,
                    mode="r+",
                    shape=(n, k),
                ),
                state,
            )
    output = np.memmap(
        path, dtype=np.float64, mode="w+", shape=(n, k)
    )
    fe = np.ascontiguousarray(fe_all[:, [1, 2]], dtype=np.uint64)
    weights = np.ones(n, dtype=np.float64)
    demeaner = engine.MapDemeaner(
        fixef_maxiter=10_000,
        fixef_tol=tolerance,
        backend="rust",
    )
    convergence: dict[str, bool] = {}
    for start in range(0, k, block_columns):
        stop = min(k, start + block_columns)
        block = np.ascontiguousarray(
            raw_interactions[:, start:stop], dtype=np.float64
        )
        transformed, success, _ = engine.dispatch_demean(
            block, fe, weights, demeaner
        )
        if not success:
            raise RuntimeError(
                f"Payer interaction demeaning failed for {start}:{stop}"
            )
        output[:, start:stop] = transformed
        output.flush()
        convergence[f"{start}:{stop}"] = bool(success)
    state = {
        "created_utc": now_utc(),
        "n_rows": n,
        "n_columns": k,
        "fixed_effect_dimensions": [
            "facility_by_year_quarter",
            "principal_clinical_category",
        ],
        "backend": "pyfixest_rust_map",
        "tolerance": tolerance,
        "block_columns": block_columns,
        "block_convergence": convergence,
        "converged": all(convergence.values()),
        "checkpoint_binding": checkpoint_binding,
    }
    atomic_json(state_path, state)
    return output, state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--primary-scratch", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--row-chunk", type=int, default=250_000)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--bootstrap-draws", type=int, default=9_999)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    gate = json.loads(
        (
            phase2 / "qa" / "pre_estimation_measurement_gate.json"
        ).read_text(encoding="utf-8")
    )
    cohort_gate = json.loads(
        (
            phase2 / "qa" / "cohort_validation_report.json"
        ).read_text(encoding="utf-8")
    )
    if gate.get("status") != "PASS" or cohort_gate.get("status") != "PASS":
        raise SystemExit("Provider-v2 and cohort gates must pass")

    engine = load_engine(
        phase2 / "scripts" / "08_estimate_primary_models.py"
    )
    root = args.matrix_root.resolve() / "race"
    matrix_manifest_path = root / "matrix_manifest.json"
    manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    matrix_provenance = engine.matrix_binding_provenance(
        manifest, matrix_manifest_path
    )
    if (
        manifest.get("analysis_sample_policy") != "common_primary"
        or manifest.get("eligibility_policy", "primary") != "primary"
    ):
        raise SystemExit(
            "Payer heterogeneity requires the primary common-sample matrix"
        )
    names = [item["name"] for item in manifest["design_spec"]]
    groups = [item["group"] for item in manifest["design_spec"]]
    outcome_names = list(manifest["primary_outcomes"])
    all_outcomes = list(manifest["outcomes"])
    outcome_indices = [
        all_outcomes.index(name) for name in outcome_names
    ]
    n = int(manifest["n_rows"])
    raw = np.memmap(
        root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(names)),
    )
    outcomes_all = np.memmap(
        root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcomes)),
    )
    outcomes = ColumnView(outcomes_all, outcome_indices)
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
        args.primary_scratch.resolve() / "race" / primary_model_id
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
    base_y = ColumnView(base_y_all, outcome_indices)

    physician_index = names.index("physician_black_proxy")
    patient_index = names.index("patient_black")
    interaction_index = names.index("race_interaction")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    payer_columns = []
    interaction_names: list[str] = []
    target_to_payer: dict[str, str] = {}
    for payer in PAYER_LEVELS:
        payer_name = f"payer__{payer}"
        if payer_name not in names:
            raise RuntimeError(f"Missing payer design column: {payer_name}")
        payer_columns.append(names.index(payer_name))
        payer_slug = slug(payer)
        payer_interactions = [
            f"payer_{payer_slug}_x_physician_black",
            f"payer_{payer_slug}_x_patient_black",
            f"payer_{payer_slug}_x_race_interaction",
        ]
        interaction_names.extend(payer_interactions)
        target_to_payer[payer_interactions[-1]] = payer
    raw_interactions = InteractionMatrix(
        raw,
        payer_columns,
        physician_index,
        patient_index,
        interaction_index,
    )
    x_payer, demeaning = residualize_design_only(
        engine,
        raw_interactions,
        fe,
        args.scratch.resolve() / "saturated_payer_interactions",
        args.tolerance,
        matrix_provenance,
        block_columns=3,
    )
    combined = CombinedMatrix(base_x, x_payer)
    combined_names = [*base_names, *interaction_names]
    targets = ["race_interaction", *target_to_payer]
    model_id = "m2_saturated_payer_category_heterogeneity"
    combined_results, diagnostic = engine.run_model(
        model_id,
        list(range(len(combined_names))),
        combined_names,
        combined,
        outcomes,
        fe,
        clusters,
        [1, 2],
        args.scratch.resolve() / "unused",
        output,
        args.row_chunk,
        3,
        args.tolerance,
        args.bootstrap_draws,
        args.seed,
        "race",
        outcome_names,
        "race_interaction",
        targets,
        (combined, base_y, demeaning),
    )
    combined_results["payer_category"] = combined_results["term"].map(
        target_to_payer
    )
    combined_results["payer_reference_category"] = "Commercial"
    combined_results["heterogeneity_interpretation"] = (
        "The payer-specific race-interaction coefficient is the difference "
        "from Commercial encounters in a jointly saturated payer model."
    )
    combined_results.to_csv(
        output / "payer_category_heterogeneity_coefficients.csv",
        index=False,
    )
    target_results = combined_results.loc[
        combined_results["term"].str.endswith("_x_race_interaction")
    ].copy()
    target_results.to_csv(
        output / "payer_category_interaction_differences.csv",
        index=False,
    )
    diagnostics_frame = pd.DataFrame(
        [
            {
                "model_id": model_id,
                "n": int(diagnostic["n"]),
                "demeaning_converged": bool(
                    diagnostic["demeaning"]["converged"]
                ),
                "payer_targets_expected": len(target_to_payer),
                "payer_targets_identified": sum(
                    target in diagnostic["kept_columns"]
                    for target in target_to_payer
                ),
                "jointly_saturated": True,
            }
        ]
    )
    diagnostics_frame.to_csv(
        output / "payer_category_heterogeneity_diagnostics.csv",
        index=False,
    )
    all_passed = bool(
        len(diagnostics_frame) == 1
        and diagnostics_frame["demeaning_converged"].all()
        and int(
            diagnostics_frame["payer_targets_identified"].iloc[0]
        )
        == len(PAYER_LEVELS)
        and len(target_results) == len(PAYER_LEVELS) * len(outcome_names)
    )
    result_manifest = {
        "created_utc": now_utc(),
        "status": "PASS" if all_passed else "FAIL",
        "analysis_id": "payer_category_race_heterogeneity_v1",
        "confirmatory_status": "secondary/exploratory",
        "black_sheep_hypothesis_status": (
            "secondary; no causal interpretation"
        ),
        "payer_reference": "Commercial",
        "payer_categories": list(PAYER_LEVELS),
        "outcomes": outcome_names,
        "model": (
            "Jointly saturated payer-by-physician-race, payer-by-patient-race, "
            "and payer-by-race-interaction M2 model with "
            "facility-year-quarter and clinical fixed effects and two-way "
            "physician/facility clustered inference"
        ),
        "common_sample_secondary_analysis": True,
        "models_expected": 1,
        "models_completed": len(diagnostics_frame),
        "payer_interaction_targets_expected": len(PAYER_LEVELS),
        "payer_interaction_targets_completed": len(target_results)
        // len(outcome_names),
        "all_models_passed": all_passed,
        **matrix_provenance,
    }
    atomic_json(
        output / "payer_category_heterogeneity_manifest.json",
        result_manifest,
    )
    if not all_passed:
        raise RuntimeError("Payer-category heterogeneity grid failed")
    print(json.dumps(result_manifest, indent=2))


if __name__ == "__main__":
    main()
