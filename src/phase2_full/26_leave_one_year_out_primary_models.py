#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/26_leave_one_year_out_primary_models.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Exact leave-one-year-out M2 HDFE sensitivity for primary outcomes.

The script starts from the validated full-sample M2 residualized matrices and
re-residualizes each retained subset against its own facility-year-quarter and
clinical fixed effects. This is algebraically identical to residualizing the
raw variables on the retained subset because the difference between raw and
full-sample residualized values lies in the retained fixed-effect span.
"""

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
from pyfixest import MapDemeaner
from pyfixest.estimation.internals.demean_ import dispatch_demean


YEARS = tuple(range(2010, 2025))


class ColumnView:
    def __init__(self, base: np.ndarray, columns: list[int]) -> None:
        self.base = base
        self.columns = np.asarray(columns, dtype=np.int64)
        self.shape = (base.shape[0], len(columns))

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, local_columns = key
        selected = self.columns[local_columns]
        if isinstance(rows, slice):
            return self.base[rows, :][:, selected]
        return self.base[np.ix_(np.asarray(rows, dtype=np.int64), selected)]


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


def load_engine(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("phase2_hdfe_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load HDFE engine from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def remove_known_working_files(folder: Path) -> None:
    """Remove only known temporary products inside the requested scratch root."""
    for name in (
        "x_subset.float64.mmap",
        "y_subset.float64.mmap",
        "fe_subset.uint64.mmap",
        "clusters_subset.uint64.mmap",
        "state.json",
    ):
        path = folder / name
        if path.exists() and path.is_file():
            path.unlink()


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


def residualize_subset(
    source: np.ndarray,
    indices: np.ndarray,
    fe: np.ndarray,
    destination: np.memmap,
    block_columns: int,
    tolerance: float,
    state_path: Path,
    state_key: str,
) -> None:
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {}
    )
    completed = set(state.get(state_key, []))
    weights = np.ones(len(indices), dtype=np.float64)
    demeaner = MapDemeaner(
        fixef_maxiter=10_000, fixef_tol=tolerance, backend="rust"
    )
    for start in range(0, source.shape[1], block_columns):
        stop = min(source.shape[1], start + block_columns)
        label = f"{start}:{stop}"
        if label in completed:
            continue
        block = np.ascontiguousarray(
            source[indices, start:stop], dtype=np.float64
        )
        transformed, success, _ = dispatch_demean(
            block,
            np.ascontiguousarray(fe, dtype=np.uint64),
            weights,
            demeaner,
        )
        if not success:
            raise RuntimeError(
                f"Subset demeaning failed for {state_key} block {label}"
            )
        destination[:, start:stop] = transformed
        destination.flush()
        completed.add(label)
        state[state_key] = sorted(completed)
        state["updated_utc"] = now_utc()
        atomic_json(state_path, state)


def validate_subset_redemeaning_identity(output: Path) -> dict[str, Any]:
    rng = np.random.default_rng(20260726)
    n = 3_000
    year = np.repeat(np.arange(3), 1_000)
    facility_time = year * 20 + rng.integers(0, 20, n)
    clinical = rng.integers(0, 17, n)
    fe = np.column_stack([facility_time, clinical]).astype(np.uint64)
    raw = rng.normal(size=(n, 5))
    weights = np.ones(n, dtype=np.float64)
    full_demeaner = MapDemeaner(
        fixef_maxiter=10_000, fixef_tol=1e-11, backend="rust"
    )
    full, full_ok, _ = dispatch_demean(raw, fe, weights, full_demeaner)
    indices = np.flatnonzero(year != 1)
    fe_subset = fe[indices]
    subset_weights = np.ones(len(indices), dtype=np.float64)
    first_demeaner = MapDemeaner(
        fixef_maxiter=10_000, fixef_tol=1e-11, backend="rust"
    )
    from_residuals, residual_ok, _ = dispatch_demean(
        np.ascontiguousarray(full[indices]),
        fe_subset,
        subset_weights,
        first_demeaner,
    )
    second_demeaner = MapDemeaner(
        fixef_maxiter=10_000, fixef_tol=1e-11, backend="rust"
    )
    from_raw, raw_ok, _ = dispatch_demean(
        np.ascontiguousarray(raw[indices]),
        fe_subset,
        subset_weights,
        second_demeaner,
    )
    difference = float(np.max(np.abs(from_residuals - from_raw)))
    payload = {
        "created_utc": now_utc(),
        "test": (
            "subset re-demeaning of full residuals equals direct raw-subset "
            "demeaning"
        ),
        "n": n,
        "maximum_absolute_difference": difference,
        "tolerance": 1e-9,
        "all_demeaning_converged": bool(full_ok and residual_ok and raw_ok),
        "passed": bool(
            full_ok and residual_ok and raw_ok and difference < 1e-9
        ),
    }
    atomic_json(output, payload)
    if not payload["passed"]:
        raise RuntimeError(f"Leave-one-year algebra validation failed: {payload}")
    return payload


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
    validate_subset_redemeaning_identity(
        phase2 / "qa" / "leave_one_year_redemeaning_validation.json"
    )
    engine = load_engine(phase2 / "scripts" / "08_estimate_primary_models.py")
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
    primary_outcome_names = list(manifest["primary_outcomes"])
    primary_indices = [
        all_outcome_names.index(name) for name in primary_outcome_names
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
    o = len(primary_indices)
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
    raw_outcomes = np.memmap(
        root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcome_names)),
    )
    base_y_primary = ColumnView(base_y_all, primary_indices)
    raw = np.memmap(
        root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_names)),
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
    year_values = np.rint(
        raw[:, all_names.index("visit_year_numeric")]
    ).astype(np.int16)

    output = args.output.resolve() / args.cohort
    output.mkdir(parents=True, exist_ok=True)
    rows: list[pd.DataFrame] = []
    year_diagnostics: dict[str, Any] = {}
    for year_offset, year in enumerate(YEARS):
        result_path = output / f"leave_out_{year}_interaction.csv"
        success_path = output / f"leave_out_{year}_SUCCESS.json"
        reuse_validated_result = False
        if success_path.exists() and result_path.exists():
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
                and prior_success.get("all_primary_outcomes_estimated")
                is True
            )
        if reuse_validated_result:
            rows.append(pd.read_csv(result_path))
            year_diagnostics[str(year)] = prior_success
            continue

        indices = np.flatnonzero(year_values != year)
        year_excluded_n = int(n - len(indices))
        subset_fe_for_singletons = np.asarray(
            fe_all[indices, 1:3], dtype=np.uint64
        )
        singleton_keep = iterative_non_singleton_mask(
            subset_fe_for_singletons
        )
        singleton_removed = int(len(indices) - singleton_keep.sum())
        indices = indices[singleton_keep]
        del subset_fe_for_singletons, singleton_keep
        retained = len(indices)
        scratch = (
            args.scratch.resolve()
            / args.cohort
            / f"leave_out_{year}"
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
                int(state.get("excluded_year", -1)) == year
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
            remove_known_working_files(scratch)
            x_mode = "w+"
            atomic_json(
                state_path,
                {
                    "created_utc": now_utc(),
                    "excluded_year": year,
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
            x_mode = "r+"
        x_subset = np.memmap(
            x_path, dtype=np.float64, mode=x_mode, shape=(retained, k)
        )
        y_subset = np.memmap(
            y_path, dtype=np.float64, mode=x_mode, shape=(retained, o)
        )
        fe_subset = np.memmap(
            fe_path, dtype=np.uint64, mode=x_mode, shape=(retained, 2)
        )
        cluster_subset = np.memmap(
            cluster_path, dtype=np.uint64, mode=x_mode, shape=(retained, 3)
        )
        if x_mode == "w+":
            fe_subset[:, :] = fe_all[indices, 1:3]
            cluster_subset[:, :] = clusters_all[indices, :]
            fe_subset.flush()
            cluster_subset.flush()
        residualize_subset(
            base_x,
            indices,
            fe_subset,
            x_subset,
            args.block_columns,
            args.tolerance,
            state_path,
            "x_completed_blocks",
        )
        residualize_subset(
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
            f"m2_leave_out_{year}",
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
            args.seed + year_offset,
            args.cohort,
            primary_outcome_names,
            None,
            None,
            (
                x_subset,
                y_subset,
                {
                    "converged": True,
                    "backend": (
                        "exact subset re-demeaning of full M2 residuals"
                    ),
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
        selected = result.loc[result["term"] == interaction].copy()
        selected["excluded_year"] = year
        selected.to_csv(result_path, index=False)
        rows.append(selected)
        success = {
            "created_utc": now_utc(),
            "cohort": args.cohort,
            "excluded_year": year,
            "retained_n": retained,
            "excluded_year_n": year_excluded_n,
            "total_excluded_n_including_singletons": int(n - retained),
            "iterative_fixed_effect_singletons_removed": singleton_removed,
            "all_primary_outcomes_estimated": (
                set(selected["outcome"]) == set(primary_outcome_names)
            ),
            "demeaning_converged": diagnostic["demeaning"]["converged"],
            "exact_refit": True,
            "bootstrap_draws": args.bootstrap_draws,
            "result_sha256": sha256_file(result_path),
            **matrix_provenance,
        }
        atomic_json(success_path, success)
        year_diagnostics[str(year)] = success
        del (
            x_subset,
            y_subset,
            fe_subset,
            cluster_subset,
            raw_y_selected,
            indices,
        )
        remove_known_working_files(scratch)

    combined = pd.concat(rows, ignore_index=True)
    combined.to_csv(output / "leave_one_year_out_interactions.csv", index=False)
    summary = (
        combined.groupby("outcome", as_index=False)
        .agg(
            minimum_estimate=("estimate", "min"),
            maximum_estimate=("estimate", "max"),
            median_estimate=("estimate", "median"),
            minimum_ci95_low=("ci95_low", "min"),
            maximum_ci95_high=("ci95_high", "max"),
            refits=("excluded_year", "nunique"),
        )
    )
    summary.to_csv(output / "leave_one_year_out_summary.csv", index=False)
    manifest_output = {
        "created_utc": now_utc(),
        "cohort": args.cohort,
        "years_excluded_one_at_a_time": list(YEARS),
        "expected_refits": len(YEARS),
        "completed_refits": int(combined["excluded_year"].nunique()),
        "primary_outcomes": primary_outcome_names,
        "model": "M2 facility-year-quarter and clinical fixed effects",
        "inference": (
            "two-way physician and facility CRV1 plus 9,999-draw facility "
            "wild score bootstrap"
        ),
        "exact_subset_redemeaning": True,
        "all_passed": int(combined["excluded_year"].nunique()) == len(YEARS),
        "year_diagnostics": year_diagnostics,
        **matrix_provenance,
    }
    atomic_json(output / "leave_one_year_out_manifest.json", manifest_output)
    print(json.dumps(manifest_output, indent=2))


if __name__ == "__main__":
    main()
