#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/19c_classified_subjectivity_sensitivity.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Exact M2 sensitivity among nonambiguous presentation classifications.

This supplements the visit-level symptom/sign heterogeneity model. It excludes
clinical categories labeled ambiguous/mixed in the versioned clinician-review
table and compares the racial or recorded-sex/physician-gender concordance
contrast between the remaining higher- and lower-uncertainty proxy groups.
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
    engine_path = phase2 / "scripts" / "08_estimate_primary_models.py"
    subset_path = phase2 / "scripts" / "26_leave_one_year_out_primary_models.py"
    engine = load_module("phase2_hdfe_engine_subjectivity", engine_path)
    subset_tools = load_module("phase2_subset_tools_subjectivity", subset_path)

    root = (args.matrix_root / args.cohort).resolve()
    matrix_manifest_path = root / "matrix_manifest.json"
    manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    matrix_provenance = engine.matrix_binding_provenance(
        manifest, matrix_manifest_path
    )
    if manifest.get("analysis_sample_policy") != "common_primary":
        raise RuntimeError("Classified-subjectivity sensitivity requires common_primary")
    if manifest.get("eligibility_policy") != "primary":
        raise RuntimeError("Classified-subjectivity sensitivity requires primary eligibility")

    review_path = Path(manifest["subjectivity_review_path"]).resolve()
    if not review_path.is_file():
        raise FileNotFoundError(review_path)
    if sha256_file(review_path) != manifest.get("subjectivity_review_sha256"):
        raise RuntimeError(
            "Presentation-subjectivity review changed after matrix creation"
        )

    spec = list(manifest["design_spec"])
    names = [item["name"] for item in spec]
    groups = [item["group"] for item in spec]
    required_design = {
        "presentation_subjectivity_classified",
        "classified_subjectivity_high",
        "classified_subjectivity_high_x_physician",
        "classified_subjectivity_high_x_patient",
        "classified_subjectivity_high_x_interaction",
    }
    missing_design = required_design - set(names)
    if missing_design:
        raise RuntimeError(
            f"Matrix lacks classified-subjectivity fields: {sorted(missing_design)}"
        )

    all_outcome_names = list(manifest["outcomes"])
    outcome_names = list(manifest["primary_outcomes"])
    outcome_indices = [
        all_outcome_names.index(name) for name in outcome_names
    ]
    n = int(manifest["n_rows"])
    raw = np.memmap(
        root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(names)),
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

    classified_index = names.index("presentation_subjectivity_classified")
    high_index = names.index("classified_subjectivity_high")
    initially_selected_indices = np.flatnonzero(
        np.asarray(raw[:, classified_index]) == 1
    )
    if not len(initially_selected_indices):
        raise RuntimeError("No nonambiguous presentation classifications available")
    high_initial = np.asarray(
        raw[initially_selected_indices, high_index], dtype=np.float64
    )
    if set(np.unique(high_initial)) != {0.0, 1.0}:
        raise RuntimeError(
            "Nonambiguous presentation sample must contain both proxy groups"
        )

    fe_for_singletons = np.asarray(
        fe_all[initially_selected_indices, 1:3], dtype=np.uint64
    )
    singleton_keep = subset_tools.iterative_non_singleton_mask(
        fe_for_singletons
    )
    indices = initially_selected_indices[singleton_keep]
    singletons_removed = int(len(initially_selected_indices) - len(indices))
    del initially_selected_indices, singleton_keep, fe_for_singletons
    if not len(indices):
        raise RuntimeError("All classified rows were fixed-effect singletons")

    high = np.asarray(raw[indices, high_index], dtype=np.float64)
    clinical_codes = np.asarray(fe_all[indices, 2], dtype=np.uint64)
    order = np.argsort(clinical_codes, kind="stable")
    ordered_codes = clinical_codes[order]
    ordered_high = high[order]
    starts = np.r_[0, 1 + np.flatnonzero(np.diff(ordered_codes))]
    minimum = np.minimum.reduceat(ordered_high, starts)
    maximum = np.maximum.reduceat(ordered_high, starts)
    high_varies_within_clinical_fe = bool(np.any(minimum != maximum))
    del high, clinical_codes, order, ordered_codes, ordered_high, starts
    del minimum, maximum

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
    modifier_group = "heterogeneity_classified_subjectivity_high"
    modifier_columns = [
        index
        for index, group in enumerate(groups)
        if group == modifier_group
    ]
    if not high_varies_within_clinical_fe:
        modifier_columns = [
            index
            for index in modifier_columns
            if names[index] != "classified_subjectivity_high"
        ]
    model_columns = [*base_columns, *modifier_columns]
    model_names = [names[index] for index in model_columns]
    target = "classified_subjectivity_high_x_interaction"
    if target not in model_names:
        raise RuntimeError(f"Target term is absent from exact design: {target}")
    source_x = subset_tools.ColumnView(raw, model_columns)
    source_y = subset_tools.ColumnView(raw_outcomes, outcome_indices)

    output = args.output.resolve() / args.cohort
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "classified_subjectivity_model_coefficients.csv"
    target_path = output / "classified_subjectivity_interaction_differences.csv"
    manifest_path = output / "classified_subjectivity_manifest.json"
    if result_path.is_file() and target_path.is_file() and manifest_path.is_file():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        reusable = (
            prior.get("status") == "PASS"
            and prior.get("result_sha256") == sha256_file(result_path)
            and prior.get("target_result_sha256") == sha256_file(target_path)
            and all(
                prior.get(key) == value
                for key, value in matrix_provenance.items()
            )
        )
        if reusable:
            print(json.dumps(prior, indent=2))
            return

    scratch = args.scratch.resolve() / args.cohort
    scratch.mkdir(parents=True, exist_ok=True)
    x_path = scratch / "x_subset.float64.mmap"
    y_path = scratch / "y_subset.float64.mmap"
    fe_path = scratch / "fe_subset.uint64.mmap"
    cluster_path = scratch / "clusters_subset.uint64.mmap"
    state_path = scratch / "state.json"
    retained = len(indices)
    k = len(model_columns)
    o = len(outcome_names)
    expected_sizes = {
        x_path: retained * k * 8,
        y_path: retained * o * 8,
        fe_path: retained * 2 * 8,
        cluster_path: retained * 3 * 8,
    }
    state_valid = state_path.is_file() and all(
        path.is_file() and path.stat().st_size == size
        for path, size in expected_sizes.items()
    )
    if state_valid:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_valid = (
            state.get("cohort") == args.cohort
            and int(state.get("retained_n", -1)) == retained
            and int(state.get("k", -1)) == k
            and int(state.get("o", -1)) == o
            and state.get("model_columns") == model_names
            and all(
                state.get(key) == value
                for key, value in matrix_provenance.items()
            )
        )
    if not state_valid:
        subset_tools.remove_known_working_files(scratch)
        mode = "w+"
        atomic_json(
            state_path,
            {
                "created_utc": now_utc(),
                "cohort": args.cohort,
                "retained_n": retained,
                "k": k,
                "o": o,
                "model_columns": model_names,
                "x_completed_blocks": [],
                "y_completed_blocks": [],
                **matrix_provenance,
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
        source_x,
        indices,
        fe_subset,
        x_subset,
        args.block_columns,
        args.tolerance,
        state_path,
        "x_completed_blocks",
    )
    subset_tools.residualize_subset(
        source_y,
        indices,
        fe_subset,
        y_subset,
        args.block_columns,
        args.tolerance,
        state_path,
        "y_completed_blocks",
    )
    raw_y_selected = np.asarray(
        raw_outcomes[np.ix_(indices, outcome_indices)], dtype=np.float64
    )
    primary_interaction = (
        "race_interaction"
        if args.cohort == "race"
        else "sex_gender_interaction"
    )
    result, diagnostic = engine.run_model(
        "m2_classified_subjectivity_nonambiguous",
        list(range(k)),
        model_names,
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
        args.seed,
        args.cohort,
        outcome_names,
        target,
        [primary_interaction, target],
        (
            x_subset,
            y_subset,
            {
                "converged": True,
                "backend": "exact subset re-demeaning",
                "fixed_effect_dimensions": [
                    "facility_by_year_quarter",
                    "principal_clinical_category",
                ],
                "ambiguous_categories_excluded": True,
            },
        ),
    )
    result["heterogeneity_modifier"] = "classified_subjectivity_high"
    result["classification_status"] = (
        "provisional_evidence_informed_not_clinically_validated"
    )
    result["interpretation"] = (
        "The target term is the difference in the four-cell concordance "
        "contrast between higher- and lower-uncertainty proxy categories, "
        "after excluding ambiguous/mixed categories."
    )
    result.to_csv(result_path, index=False)
    target_result = result.loc[result["term"] == target].copy()
    if set(target_result["outcome"]) != set(outcome_names):
        raise RuntimeError("Classified-subjectivity target outcomes are incomplete")
    target_result.to_csv(target_path, index=False)

    manifest_output = {
        "created_utc": now_utc(),
        "status": "PASS",
        "cohort": args.cohort,
        "model_id": "m2_classified_subjectivity_nonambiguous",
        "target_term": target,
        "initially_classified_n": retained + singletons_removed,
        "retained_n": retained,
        "iterative_fixed_effect_singletons_removed": singletons_removed,
        "higher_subjectivity_proxy_n": int(
            np.sum(np.asarray(raw[indices, high_index]) == 1)
        ),
        "lower_subjectivity_proxy_n": int(
            np.sum(np.asarray(raw[indices, high_index]) == 0)
        ),
        "ambiguous_categories_excluded": True,
        "classification_status": (
            "provisional_evidence_informed_not_clinically_validated"
        ),
        "subjectivity_review_path": str(review_path),
        "subjectivity_review_sha256": sha256_file(review_path),
        "subjectivity_review_version": manifest.get(
            "subjectivity_review_version"
        ),
        "clinical_main_effect_absorbed_by_clinical_fe": (
            not high_varies_within_clinical_fe
        ),
        "model_columns": model_names,
        "outcomes": outcome_names,
        "all_outcomes_estimated": (
            set(target_result["outcome"]) == set(outcome_names)
        ),
        "demeaning_converged": bool(
            diagnostic.get("demeaning", {}).get("converged")
        ),
        "result_sha256": sha256_file(result_path),
        "target_result_sha256": sha256_file(target_path),
        "confirmatory": False,
        "multiple_testing": (
            "Benjamini-Hochberg within the classified-subjectivity "
            "sensitivity family"
        ),
        **matrix_provenance,
    }
    atomic_json(manifest_path, manifest_output)
    print(json.dumps(manifest_output, indent=2))


if __name__ == "__main__":
    main()
