#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/28_influential_facility_exact_refits.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Exact influential-facility deletion refits for primary M2 outcomes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


M2_ID = "m2_fully_adjusted_facility_yq_clinical_fe"


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
    parser.add_argument("--top-per-outcome", type=int, default=5)
    parser.add_argument("--row-chunk", type=int, default=250_000)
    parser.add_argument("--block-columns", type=int, default=4)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--bootstrap-draws", type=int, default=9_999)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()
    if args.top_per_outcome < 1:
        raise SystemExit("--top-per-outcome must be positive")

    phase2 = args.phase2.resolve()
    engine = load_module(
        "phase2_influence_hdfe_engine",
        phase2 / "scripts" / "08_estimate_primary_models.py",
    )
    subset_tools = load_module(
        "phase2_influence_subset_tools",
        phase2 / "scripts" / "26_leave_one_year_out_primary_models.py",
    )
    subset_tools.validate_subset_redemeaning_identity(
        phase2 / "qa" / "influential_facility_redemeaning_validation.json"
    )

    root = (args.matrix_root / args.cohort).resolve()
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
            "Influential-facility analysis requires the common primary matrix"
        )

    n = int(manifest["n_rows"])
    spec = manifest["design_spec"]
    all_names = [item["name"] for item in spec]
    groups = [item["group"] for item in spec]
    all_outcomes = list(manifest["outcomes"])
    primary_outcomes = list(manifest["primary_outcomes"])
    primary_indices = [
        all_outcomes.index(name) for name in primary_outcomes
    ]
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
    o = len(primary_outcomes)

    primary_folder = (
        args.primary_scratch.resolve() / args.cohort / M2_ID
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
        shape=(n, len(all_outcomes)),
    )
    base_y_primary = subset_tools.ColumnView(base_y_all, primary_indices)
    raw_outcomes = np.memmap(
        root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcomes)),
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

    model_results = (
        phase2 / "results" / "models" / args.cohort
    )
    diagnostics_path = model_results / f"{M2_ID}_diagnostics.json"
    coefficients_path = model_results / "primary_model_coefficients.csv"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    full_coefficients = pd.read_csv(coefficients_path)
    interaction = (
        "race_interaction"
        if args.cohort == "race"
        else "sex_gender_interaction"
    )
    full_interactions = full_coefficients.loc[
        (full_coefficients["model_id"] == M2_ID)
        & (full_coefficients["term"] == interaction)
        & (full_coefficients["outcome"].isin(primary_outcomes))
    ].copy()
    if len(full_interactions) != len(primary_outcomes):
        raise RuntimeError("Full M2 primary interaction rows are incomplete")

    influence_by_outcome: dict[str, list[dict[str, Any]]] = {
        name: [] for name in primary_outcomes
    }
    for item in diagnostics["wild_score_bootstrap"]["outcomes"]:
        index = int(item["outcome_index"])
        if index >= len(all_outcomes):
            raise RuntimeError("Invalid outcome index in M2 diagnostics")
        outcome = all_outcomes[index]
        if outcome not in influence_by_outcome:
            continue
        facility = item["first_order_leave_one_facility_diagnostics"]
        codes = facility["top_internal_facility_cluster_codes"]
        shifts = facility["top_signed_first_order_shifts"]
        influence_by_outcome[outcome] = [
            {
                "facility_code": int(code),
                "first_order_shift": float(shift),
                "rank": rank,
            }
            for rank, (code, shift) in enumerate(
                zip(codes, shifts), start=1
            )
        ][: args.top_per_outcome]

    candidate_rows: list[dict[str, Any]] = []
    for outcome, values in influence_by_outcome.items():
        for value in values:
            candidate_rows.append({"selection_outcome": outcome, **value})
    candidate_frame = pd.DataFrame(candidate_rows)
    if candidate_frame.empty:
        raise RuntimeError("No influential facilities were identified")
    facility_codes = sorted(
        candidate_frame["facility_code"].astype(int).unique().tolist()
    )

    output = args.output.resolve() / args.cohort
    output.mkdir(parents=True, exist_ok=True)
    candidate_frame.to_csv(
        output / "influential_facility_candidates.csv", index=False
    )
    result_frames: list[pd.DataFrame] = []
    refit_diagnostics: list[dict[str, Any]] = []
    facility_values = np.asarray(clusters_all[:, 1], dtype=np.uint64)

    for offset, facility_code in enumerate(facility_codes):
        stem = f"exclude_facility_code_{facility_code}"
        result_path = output / f"{stem}_interaction.csv"
        success_path = output / f"{stem}_SUCCESS.json"
        reuse_validated_result = False
        if result_path.exists() and success_path.exists():
            stored = json.loads(success_path.read_text(encoding="utf-8"))
            reuse_validated_result = (
                stored.get("status") == "PASS"
                and int(stored.get("excluded_facility_code", -1))
                == facility_code
                and all(
                    stored.get(key) == value
                    for key, value in matrix_provenance.items()
                )
                and stored.get("result_sha256") == sha256_file(result_path)
            )
        if reuse_validated_result:
            result_frames.append(pd.read_csv(result_path))
            refit_diagnostics.append(stored)
            continue

        initial_indices = np.flatnonzero(facility_values != facility_code)
        excluded_n = int(n - len(initial_indices))
        if excluded_n <= 0:
            raise RuntimeError(
                f"Candidate facility code has no rows: {facility_code}"
            )
        subset_fe_for_singletons = np.asarray(
            fe_all[initial_indices, 1:3], dtype=np.uint64
        )
        singleton_keep = subset_tools.iterative_non_singleton_mask(
            subset_fe_for_singletons
        )
        singleton_removed = int(
            len(initial_indices) - singleton_keep.sum()
        )
        indices = initial_indices[singleton_keep]
        del initial_indices, subset_fe_for_singletons, singleton_keep
        retained = len(indices)

        scratch = args.scratch.resolve() / args.cohort / stem
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
                int(state.get("excluded_facility_code", -1))
                == facility_code
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
                    "excluded_facility_code": facility_code,
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
            base_y_primary,
            indices,
            fe_subset,
            y_subset,
            args.block_columns,
            args.tolerance,
            state_path,
            "y_completed_blocks",
        )
        raw_y_selected = np.asarray(
            raw_outcomes[np.ix_(indices, primary_indices)],
            dtype=np.float64,
        )
        result, diagnostic = engine.run_model(
            f"m2_{stem}",
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
            args.seed + offset,
            args.cohort,
            primary_outcomes,
            None,
            None,
            (
                x_subset,
                y_subset,
                {
                    "converged": True,
                    "backend": (
                        "exact facility-deletion subset re-demeaning of "
                        "full M2 residuals"
                    ),
                    "fixed_effect_dimensions": [1, 2],
                    "algebraic_equivalence_to_raw_subset_demeaning": True,
                },
            ),
        )
        selected = result.loc[result["term"] == interaction].copy()
        selected["excluded_facility_code"] = facility_code
        selected = selected.merge(
            full_interactions[
                ["outcome", "estimate", "clustered_standard_error"]
            ].rename(
                columns={
                    "estimate": "full_sample_estimate",
                    "clustered_standard_error": (
                        "full_sample_standard_error"
                    ),
                }
            ),
            on="outcome",
            how="left",
            validate="one_to_one",
        )
        selected["exact_estimate_shift"] = (
            selected["estimate"] - selected["full_sample_estimate"]
        )
        selected["absolute_exact_estimate_shift"] = selected[
            "exact_estimate_shift"
        ].abs()
        selected["absolute_shift_in_full_sample_se"] = (
            selected["absolute_exact_estimate_shift"]
            / selected["full_sample_standard_error"]
        )
        selected["sign_changed"] = (
            np.sign(selected["estimate"])
            != np.sign(selected["full_sample_estimate"])
        )
        selected.to_csv(result_path, index=False)
        success = {
            "created_utc": now_utc(),
            "status": "PASS",
            "cohort": args.cohort,
            "excluded_facility_code": facility_code,
            "excluded_facility_rows": excluded_n,
            "retained_n": retained,
            "iterative_fixed_effect_singletons_removed": singleton_removed,
            "outcomes": primary_outcomes,
            "all_primary_outcomes_estimated": (
                set(selected["outcome"]) == set(primary_outcomes)
            ),
            "demeaning_converged": diagnostic["demeaning"]["converged"],
            "exact_refit": True,
            "bootstrap_draws": args.bootstrap_draws,
            "result_sha256": sha256_file(result_path),
            **matrix_provenance,
        }
        atomic_json(success_path, success)
        result_frames.append(selected)
        refit_diagnostics.append(success)
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
    combined.to_csv(
        output / "influential_facility_exact_refits.csv", index=False
    )
    summary = (
        combined.groupby("outcome", as_index=False)
        .agg(
            facilities_refit=("excluded_facility_code", "nunique"),
            maximum_absolute_exact_shift=(
                "absolute_exact_estimate_shift",
                "max",
            ),
            maximum_absolute_shift_in_full_sample_se=(
                "absolute_shift_in_full_sample_se",
                "max",
            ),
            any_sign_change=("sign_changed", "max"),
            minimum_estimate=("estimate", "min"),
            maximum_estimate=("estimate", "max"),
        )
    )
    summary.to_csv(
        output / "influential_facility_exact_refit_summary.csv",
        index=False,
    )
    all_passed = (
        len(refit_diagnostics) == len(facility_codes)
        and all(
            item["status"] == "PASS"
            and item["all_primary_outcomes_estimated"]
            and item["demeaning_converged"]
            for item in refit_diagnostics
        )
    )
    payload = {
        "created_utc": now_utc(),
        "status": "PASS" if all_passed else "FAIL",
        "analysis_id": "exact_influential_facility_deletion_refits_v1",
        "cohort": args.cohort,
        "selection_method": (
            f"Union of top {args.top_per_outcome} absolute first-order "
            "facility influence scores for each confirmatory outcome"
        ),
        "candidate_facility_codes": facility_codes,
        "candidate_facilities": len(facility_codes),
        "completed_exact_refits": len(refit_diagnostics),
        "outcomes": primary_outcomes,
        "model": (
            "Exact M2 refit after facility deletion and iterative singleton "
            "removal, with subset-specific facility-year-quarter and "
            "clinical fixed-effect re-demeaning"
        ),
        "public_reporting": (
            "Only anonymized internal facility cluster codes and aggregate "
            "stability summaries are retained."
        ),
        "all_passed": all_passed,
        "details": refit_diagnostics,
        **matrix_provenance,
    }
    atomic_json(
        output / "influential_facility_exact_refits_manifest.json", payload
    )
    print(json.dumps(payload, indent=2))
    if not all_passed:
        raise RuntimeError("Influential-facility exact refits failed")


if __name__ == "__main__":
    main()
