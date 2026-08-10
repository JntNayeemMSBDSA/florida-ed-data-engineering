#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/27_exact_subset_sensitivities.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Exact M2 HDFE subset sensitivities for missingness, outliers, and volume."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {path}")
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
    parser.add_argument(
        "--cohort", required=True, choices=("race", "sex_gender")
    )
    parser.add_argument("--row-chunk", type=int, default=250_000)
    parser.add_argument("--block-columns", type=int, default=4)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--bootstrap-draws", type=int, default=9_999)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    engine = load_module(
        "phase2_hdfe_engine",
        phase2 / "scripts" / "08_estimate_primary_models.py",
    )
    subset_tools = load_module(
        "phase2_subset_tools",
        phase2 / "scripts" / "26_leave_one_year_out_primary_models.py",
    )
    root = (args.matrix_root / args.cohort).resolve()
    matrix_manifest_path = root / "matrix_manifest.json"
    manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    matrix_provenance = engine.matrix_binding_provenance(
        manifest, matrix_manifest_path
    )
    n = int(manifest["n_rows"])
    spec = manifest["design_spec"]
    all_names = [item["name"] for item in spec]
    groups = [item["group"] for item in spec]
    all_outcome_names = list(manifest["outcomes"])
    primary_outcomes = list(manifest["primary_outcomes"])
    m2_columns = [
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
    m2_names = [all_names[index] for index in m2_columns]
    k = len(m2_columns)
    raw = np.memmap(
        root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_names)),
    )
    raw_outcomes = np.memmap(
        root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcome_names)),
    )
    fe_all = np.memmap(
        root / "fe_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    clusters_all = np.memmap(
        root / "cluster_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    primary_folder = (
        args.primary_scratch.resolve()
        / args.cohort
        / "m2_fully_adjusted_facility_yq_clinical_fe"
    )
    base_x = np.memmap(
        primary_folder / "demeaned_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, k),
    )
    base_y_all = np.memmap(
        primary_folder / "demeaned_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcome_names)),
    )

    selections = [
        {
            "id": "los_0_72_hours",
            "mask": raw[:, all_names.index("los_le72")] == 1,
            "outcomes": ["los_hours_primary_0_168"],
            "purpose": "clinically tighter LOS outlier restriction",
        },
        {
            "id": "positive_reported_charge",
            "mask": raw[
                :, all_names.index("positive_reported_charge")
            ]
            == 1,
            "outcomes": ["total_charge_reported_real_2024"],
            "purpose": "positive-charge component of the two-part sensitivity",
        },
        {
            "id": "complete_case_covariates",
            "mask": raw[
                :, all_names.index("complete_case_covariates")
            ]
            == 1,
            "outcomes": primary_outcomes,
            "purpose": "complete-case versus missing-category sensitivity",
        },
        {
            "id": "em_acuity_available",
            "mask": raw[:, all_names.index("em_acuity_available")] == 1,
            "outcomes": ["em_acuity_proxy_level"],
            "source": "design",
            "source_columns": ["em_acuity_value"],
            "purpose": (
                "billing-derived evaluation-and-management acuity proxy; "
                "not clinical triage"
            ),
        },
        {
            "id": "em_critical_care_available",
            "mask": raw[
                :, all_names.index("em_critical_care_available")
            ]
            == 1,
            "outcomes": ["em_critical_care_flag"],
            "source": "design",
            "source_columns": ["em_critical_care_value"],
            "purpose": (
                "billing-derived critical-care indicator; not baseline severity"
            ),
        },
    ]
    if args.cohort == "sex_gender":
        source_conflict_field = "physician_gender_source_no_conflict"
        if source_conflict_field not in all_names:
            raise RuntimeError(
                "Sex/gender matrix is missing the recorded-source conflict "
                f"selection field: {source_conflict_field}"
            )
        selections.append(
            {
                "id": "physician_gender_recorded_sources_no_conflict",
                "mask": raw[
                    :, all_names.index(source_conflict_field)
                ]
                == 1,
                "outcomes": primary_outcomes,
                "purpose": (
                    "exclude NPIs whose recorded NPPES and CMS binary "
                    "physician-gender categories disagree"
                ),
            }
        )
    volume_index = all_names.index("log1p_physician_quarter_volume")
    for threshold in (50, 100, 250):
        selections.append(
            {
                "id": f"minimum_physician_quarter_volume_{threshold}",
                "mask": raw[:, volume_index] >= math.log1p(threshold),
                "outcomes": primary_outcomes,
                "purpose": "minimum physician-volume support sensitivity",
            }
        )

    output = args.output.resolve() / args.cohort
    output.mkdir(parents=True, exist_ok=True)
    result_frames: list[pd.DataFrame] = []
    diagnostic_rows: list[dict[str, Any]] = []
    for sensitivity_offset, selection in enumerate(selections):
        sensitivity_id = str(selection["id"])
        result_path = output / f"{sensitivity_id}_interaction.csv"
        success_path = output / f"{sensitivity_id}_SUCCESS.json"
        reuse_validated_result = False
        if result_path.exists() and success_path.exists():
            prior_success = json.loads(
                success_path.read_text(encoding="utf-8")
            )
            reuse_validated_result = (
                all(
                    prior_success.get(key) == value
                    for key, value in matrix_provenance.items()
                )
                and prior_success.get("result_sha256")
                == sha256_file(result_path)
                and prior_success.get("all_outcomes_estimated") is True
            )
        if reuse_validated_result:
            result_frames.append(pd.read_csv(result_path))
            diagnostic_rows.append(prior_success)
            continue

        indices = np.flatnonzero(np.asarray(selection["mask"], dtype=bool))
        initially_selected = len(indices)
        fe_for_singletons = np.asarray(fe_all[indices, 1:3], dtype=np.uint64)
        singleton_keep = subset_tools.iterative_non_singleton_mask(
            fe_for_singletons
        )
        singleton_removed = int(len(indices) - singleton_keep.sum())
        indices = indices[singleton_keep]
        del fe_for_singletons, singleton_keep
        retained = len(indices)
        outcome_names = list(selection["outcomes"])
        source_type = selection.get("source", "outcomes")
        if source_type == "outcomes":
            outcome_indices = [
                all_outcome_names.index(name) for name in outcome_names
            ]
            base_y = subset_tools.ColumnView(base_y_all, outcome_indices)
            raw_y_source = raw_outcomes
        elif source_type == "design":
            outcome_indices = [
                all_names.index(name)
                for name in selection["source_columns"]
            ]
            base_y = subset_tools.ColumnView(raw, outcome_indices)
            raw_y_source = raw
        else:
            raise RuntimeError(f"Unsupported outcome source: {source_type}")
        o = len(outcome_names)

        scratch = (
            args.scratch.resolve() / args.cohort / sensitivity_id
        )
        scratch.mkdir(parents=True, exist_ok=True)
        x_path = scratch / "x_subset.float64.mmap"
        y_path = scratch / "y_subset.float64.mmap"
        fe_path = scratch / "fe_subset.uint64.mmap"
        cluster_path = scratch / "clusters_subset.uint64.mmap"
        state_path = scratch / "state.json"
        expected_sizes = {
            x_path: retained * k * 8,
            y_path: retained * o * 8,
            fe_path: retained * 2 * 8,
            cluster_path: retained * 3 * 8,
        }
        state_valid = state_path.exists() and all(
            path.exists() and path.stat().st_size == size
            for path, size in expected_sizes.items()
        )
        if state_valid:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state_valid = (
                state.get("sensitivity_id") == sensitivity_id
                and int(state.get("retained_n", -1)) == retained
                and int(state.get("k", -1)) == k
                and int(state.get("o", -1)) == o
                and state.get("matrix_manifest_sha256")
                == matrix_provenance["matrix_manifest_sha256"]
                and state.get("provider_gate_sha256")
                == matrix_provenance["provider_gate_sha256"]
                and state.get("cohort_gate_sha256")
                == matrix_provenance["cohort_gate_sha256"]
            )
        if not state_valid:
            subset_tools.remove_known_working_files(scratch)
            mode = "w+"
            atomic_json(
                state_path,
                {
                    "created_utc": now_utc(),
                    "sensitivity_id": sensitivity_id,
                    "retained_n": retained,
                    "k": k,
                    "o": o,
                    "matrix_manifest_sha256": matrix_provenance[
                        "matrix_manifest_sha256"
                    ],
                    "provider_gate_sha256": matrix_provenance[
                        "provider_gate_sha256"
                    ],
                    "cohort_gate_sha256": matrix_provenance[
                        "cohort_gate_sha256"
                    ],
                    "x_completed_blocks": [],
                    "y_completed_blocks": [],
                },
            )
        else:
            mode = "r+"
        x_subset = np.memmap(
            x_path, dtype=np.float64, mode=mode, shape=(retained, k)
        )
        y_subset = np.memmap(
            y_path, dtype=np.float64, mode=mode, shape=(retained, o)
        )
        fe_subset = np.memmap(
            fe_path, dtype=np.uint64, mode=mode, shape=(retained, 2)
        )
        cluster_subset = np.memmap(
            cluster_path, dtype=np.uint64, mode=mode, shape=(retained, 3)
        )
        if mode == "w+":
            fe_subset[:, :] = fe_all[indices, 1:3]
            cluster_subset[:, :] = clusters_all[indices, :]
            fe_subset.flush()
            cluster_subset.flush()
        subset_tools.residualize_subset(
            base_x,
            indices,
            fe_subset,
            x_subset,
            args.block_columns,
            args.tolerance,
            state_path,
            "x_completed_blocks",
        )
        subset_tools.residualize_subset(
            base_y,
            indices,
            fe_subset,
            y_subset,
            args.block_columns,
            args.tolerance,
            state_path,
            "y_completed_blocks",
        )
        raw_y_selected = np.asarray(
            raw_y_source[np.ix_(indices, outcome_indices)],
            dtype=np.float64,
        )
        model_id = f"m2_subset_{sensitivity_id}"
        result, diagnostic = engine.run_model(
            model_id,
            list(range(k)),
            m2_names,
            x_subset,
            raw_y_selected,
            fe_subset,
            cluster_subset,
            [],
            scratch / "unused",
            output,
            args.row_chunk,
            args.block_columns,
            args.tolerance,
            args.bootstrap_draws,
            args.seed + sensitivity_offset,
            args.cohort,
            outcome_names,
            None,
            None,
            (
                x_subset,
                y_subset,
                {
                    "converged": True,
                    "backend": "exact subset re-demeaning of full M2 residuals",
                    "fixed_effect_dimensions": [1, 2],
                    "algebraic_equivalence_to_raw_subset_demeaning": True,
                },
            ),
        )
        interaction = (
            "race_interaction"
            if args.cohort == "race"
            else "sex_gender_interaction"
        )
        selected_result = result.loc[result["term"] == interaction].copy()
        selected_result["sensitivity_id"] = sensitivity_id
        selected_result["sensitivity_purpose"] = selection["purpose"]
        selected_result.to_csv(result_path, index=False)
        result_frames.append(selected_result)
        success = {
            "created_utc": now_utc(),
            "cohort": args.cohort,
            "sensitivity_id": sensitivity_id,
            "purpose": selection["purpose"],
            "initially_selected_n": initially_selected,
            "retained_n": retained,
            "iterative_fixed_effect_singletons_removed": singleton_removed,
            "outcomes": outcome_names,
            "all_outcomes_estimated": (
                set(selected_result["outcome"]) == set(outcome_names)
            ),
            "demeaning_converged": diagnostic["demeaning"]["converged"],
            "exact_refit": True,
            "result_sha256": sha256_file(result_path),
            **matrix_provenance,
        }
        atomic_json(success_path, success)
        diagnostic_rows.append(success)
        del (
            x_subset,
            y_subset,
            fe_subset,
            cluster_subset,
            raw_y_selected,
            indices,
        )
        subset_tools.remove_known_working_files(scratch)

    combined = pd.concat(result_frames, ignore_index=True)
    combined.to_csv(output / "exact_subset_interactions.csv", index=False)
    manifest_output = {
        "created_utc": now_utc(),
        "cohort": args.cohort,
        "sensitivity_ids": [item["id"] for item in selections],
        "completed_sensitivities": int(
            combined["sensitivity_id"].nunique()
        ),
        "expected_sensitivities": len(selections),
        "model": "M2 facility-year-quarter and clinical fixed effects",
        "exact_subset_redemeaning": True,
        "all_passed": (
            int(combined["sensitivity_id"].nunique()) == len(selections)
            and all(item["all_outcomes_estimated"] for item in diagnostic_rows)
        ),
        "details": diagnostic_rows,
        **matrix_provenance,
    }
    atomic_json(output / "exact_subset_sensitivities_manifest.json", manifest_output)
    print(json.dumps(manifest_output, indent=2))


if __name__ == "__main__":
    main()
