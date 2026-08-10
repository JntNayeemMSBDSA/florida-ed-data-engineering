#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/03g_seed_common_primary_race_m2_retry_checkpoint.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Seed the audited retry checkpoint for common-primary race M2.

This script does not estimate a model or inspect any coefficient.  It binds
the preserved strict-de-meaning failure to the live matrix, provider/cohort
gates, patched inference engine, tested fallback policy, and exact incomplete
scratch-buffer geometry.  The resulting restart state permits only the exact
failed first block to bypass a wasteful repeat of the already documented
strict attempt.  Every subsequent block must still attempt the strict policy
first.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARCHIVE_ID = "common_primary_race_m2_strict_nonconvergence_20260727T0221Z"
OLD_ENGINE_SHA256 = (
    "376bed006df47acce8b81c9f9b4e4336953632bfc62f616cf96f704af44f98a9"
)
FAILED_SOURCE_COLUMNS = [1, 2, 3, 34]
MODEL_ID = "m2_fully_adjusted_facility_yq_clinical_fe"
FE_INDICES = [1, 2]
BLOCK_COLUMNS = 4
STRICT_TOLERANCE = 1e-8
STRICT_MAXITER = 10_000
FALLBACK_TOLERANCE = 1e-6
FALLBACK_MAXITER = 50_000


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_engine(path: Path) -> Any:
    name = "primary_hdfe_engine_for_retry_checkpoint"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import inference engine: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require_file(path: Path, description: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"{description} is missing: {resolved}")
    return resolved


def file_record(path: Path, relative_to: Path | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    display = (
        resolved.relative_to(relative_to.resolve()).as_posix()
        if relative_to is not None
        else str(resolved)
    )
    return {
        "path": display,
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def expected_file_size(rows: int, columns: int, itemsize: int = 8) -> int:
    return rows * columns * itemsize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--scratch-root", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    matrix_root = args.matrix_root.resolve()
    scratch_root = args.scratch_root.resolve()
    if not (phase2 / "scripts").is_dir():
        raise SystemExit(f"Invalid Phase 2 directory: {phase2}")

    archive = (
        phase2 / "audit_history" / ARCHIVE_ID
    ).resolve()
    archive_manifest_path = require_file(
        archive / "ARCHIVE_MANIFEST.json", "Preserved failure manifest"
    )
    failed_log_path = require_file(
        archive / "08_estimate_common_primary_race_FAILED.log",
        "Preserved failed model log",
    )
    parent_log_path = require_file(
        archive / "RUN_COMMON_PRIMARY_SAFE_FAILED.log",
        "Preserved failed wrapper log",
    )
    archive_manifest = load_json(archive_manifest_path)
    if (
        archive_manifest.get("archive_id") != ARCHIVE_ID
        or archive_manifest.get("status") != "PRESERVED_FAILED_ATTEMPT"
        or archive_manifest.get("results_written_for_failed_model") is not False
        or archive_manifest.get("coefficient_values_read_or_interpreted")
        is not False
    ):
        raise SystemExit("Preserved failure manifest is not an eligible retry")
    if (
        archive_manifest.get("inference_engine_at_failure", {}).get("sha256")
        != OLD_ENGINE_SHA256
    ):
        raise SystemExit("Old inference-engine hash does not reconcile")
    archived_file_hashes = {
        item["name"]: item["sha256"]
        for item in archive_manifest.get("files", [])
    }
    for log_path in (failed_log_path, parent_log_path):
        if sha256_file(log_path) != archived_file_hashes.get(log_path.name):
            raise SystemExit(f"Preserved log hash mismatch: {log_path.name}")
    failed_log_bytes = failed_log_path.read_bytes()
    failed_log = (
        failed_log_bytes.decode("utf-16")
        if b"\x00" in failed_log_bytes[:256]
        else failed_log_bytes.decode("utf-8", errors="replace")
    )
    failure_pattern = re.escape(
        "Demeaning did not converge for columns [1, 2, 3, 34]"
    )
    if re.search(failure_pattern, failed_log) is None:
        raise SystemExit("Exact archived strict failure is not present")

    fallback_test_path = require_file(
        phase2 / "qa" / "demeaning_fallback_unit_tests.json",
        "Demeaning fallback unit-test report",
    )
    fallback_test = load_json(fallback_test_path)
    if (
        fallback_test.get("status") != "PASS"
        or fallback_test.get("checks_passed") != 4
        or fallback_test.get("checks_total") != 4
        or fallback_test.get("real_data_loaded") is not False
        or fallback_test.get("result_values_read") is not False
    ):
        raise SystemExit("Demeaning fallback tests do not pass exactly")

    engine_path = require_file(
        phase2 / "scripts" / "08_estimate_primary_models.py",
        "Patched inference engine",
    )
    engine = load_engine(engine_path)
    engine_hash = sha256_file(engine_path)
    if engine_hash == OLD_ENGINE_SHA256:
        raise SystemExit("Inference engine was not patched after the failure")

    matrix_dir = (matrix_root / "race").resolve()
    matrix_manifest_path = require_file(
        matrix_dir / "matrix_manifest.json", "Race matrix manifest"
    )
    matrix_manifest = load_json(matrix_manifest_path)
    if (
        matrix_manifest.get("cohort") != "race"
        or matrix_manifest.get("matrix_id") != "race"
        or matrix_manifest.get("analysis_sample_policy") != "common_primary"
        or matrix_manifest.get("provider_measurement_version")
        != "provider_master_v2_full_name_race_v1"
    ):
        raise SystemExit("Live matrix is not the certified common-primary race matrix")
    matrix_binding = engine.matrix_binding_provenance(
        matrix_manifest, matrix_manifest_path
    )
    rows = int(matrix_manifest["n_rows"])
    outcomes = list(matrix_manifest["outcomes"])
    design_spec = list(matrix_manifest["design_spec"])
    design_names = [item["name"] for item in design_spec]
    groups = [item["group"] for item in design_spec]
    fully_adjusted_columns = [
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
    if fully_adjusted_columns[:BLOCK_COLUMNS] != FAILED_SOURCE_COLUMNS:
        raise SystemExit(
            "Current M2 first block no longer matches the archived failure: "
            f"{fully_adjusted_columns[:BLOCK_COLUMNS]}"
        )
    failed_design_names = [
        design_names[index] for index in FAILED_SOURCE_COLUMNS
    ]

    live_matrix_files = {
        "raw_design.float64.mmap": expected_file_size(
            rows, len(design_spec)
        ),
        "model_outcomes.float64.mmap": expected_file_size(
            rows, len(outcomes)
        ),
        "fe_codes.uint64.mmap": expected_file_size(rows, 3),
        "cluster_codes.uint64.mmap": expected_file_size(rows, 3),
    }
    for name, expected_bytes in live_matrix_files.items():
        path = require_file(matrix_dir / name, f"Live matrix file {name}")
        if path.stat().st_size != expected_bytes:
            raise SystemExit(
                f"Live matrix geometry mismatch for {name}: "
                f"{path.stat().st_size} != {expected_bytes}"
            )

    model_scratch = (scratch_root / "race" / MODEL_ID).resolve()
    if not model_scratch.is_dir():
        raise SystemExit(f"Failed-model scratch directory is missing: {model_scratch}")
    state_path = model_scratch / "demeaning_state.json"
    if state_path.exists():
        raise SystemExit(
            "Retry state already exists; refusing to overwrite it. "
            "Validate and resume the existing checkpoint."
        )
    scratch_expected = {
        "demeaned_design.float64.mmap": expected_file_size(
            rows, len(fully_adjusted_columns)
        ),
        "demeaned_outcomes.float64.mmap": expected_file_size(
            rows, len(outcomes)
        ),
    }
    archived_scratch = {
        item["name"]: int(item["bytes"])
        for item in archive_manifest.get("incomplete_restart_scratch", [])
    }
    scratch_records: list[dict[str, Any]] = []
    for name, expected_bytes in scratch_expected.items():
        path = require_file(model_scratch / name, f"Incomplete scratch buffer {name}")
        actual_bytes = path.stat().st_size
        if (
            actual_bytes != expected_bytes
            or actual_bytes != archived_scratch.get(name)
        ):
            raise SystemExit(
                f"Scratch geometry does not reconcile for {name}: "
                f"actual={actual_bytes}, expected={expected_bytes}, "
                f"archived={archived_scratch.get(name)}"
            )
        scratch_records.append(
            {
                "path": str(path),
                "bytes": actual_bytes,
                "content_status": "INCOMPLETE_RESTART_BUFFER_NOT_RESULT",
                "content_hash_omitted_reason": (
                    "The 74-GB combined incomplete buffers are overwriteable "
                    "restart storage; their exact geometry and preserved "
                    "failure provenance, not their incomplete contents, bind "
                    "the retry."
                ),
            }
        )

    output_root = phase2 / "results" / "models" / "race"
    prohibited_outputs = (
        output_root / f"{MODEL_ID}_diagnostics.json",
        output_root / "primary_model_coefficients.csv",
        output_root / "primary_models_manifest.json",
    )
    if any(path.exists() for path in prohibited_outputs):
        raise SystemExit(
            "A completed or combined race M2 output already exists; "
            "checkpoint seeding is no longer authorized"
        )

    created = now_utc()
    state: dict[str, Any] = {
        "updated_utc": created,
        "n_rows": rows,
        "column_indices": fully_adjusted_columns,
        "fe_indices": FE_INDICES,
        "completed_local_columns": [],
        "completed_outcome_columns": [],
        "outcomes_completed": False,
        "convergence": {},
        "demeaning_attempts": {
            "x_0_4": {
                "source_columns": FAILED_SOURCE_COLUMNS,
                "source_column_names": failed_design_names,
                "strict_tolerance": STRICT_TOLERANCE,
                "strict_maxiter": STRICT_MAXITER,
                "strict_status": "NONCONVERGED",
                "strict_dispatch_detail": (
                    "Reconstructed from the hash-verified archived traceback; "
                    "the pre-patch dispatcher returned success=False and did "
                    "not emit its internal iteration detail to the log."
                ),
                "strict_attempt_recorded_utc": archive_manifest["created_utc"],
                "strict_attempt_reused_from_checkpoint": False,
                "provenance": {
                    "archive_id": ARCHIVE_ID,
                    "archive_manifest_sha256": sha256_file(
                        archive_manifest_path
                    ),
                    "failed_log_sha256": sha256_file(failed_log_path),
                    "engine_sha256_at_failure": OLD_ENGINE_SHA256,
                },
            }
        },
        "numerical_policy": {
            "strict": {
                "tolerance": STRICT_TOLERANCE,
                "maxiter": STRICT_MAXITER,
                "backend": "rust",
            },
            "fallback_only_after_documented_strict_nonconvergence": {
                "tolerance": FALLBACK_TOLERANCE,
                "maxiter": FALLBACK_MAXITER,
                "backend": "rust",
            },
            "sample_formula_fixed_effects_and_columns_changed": False,
        },
        "checkpoint_binding": matrix_binding,
    }
    atomic_json(state_path, state)

    checkpoint: dict[str, Any] = {
        "status": "PASS_RETRY_AUTHORIZED",
        "checkpoint_id": "common_primary_race_m2_numerical_retry_v1",
        "created_utc": created,
        "purpose": (
            "Bind the documented strict failure for the exact first M2 block "
            "to a one-time numerical fallback retry without changing sample, "
            "formula, outcomes, fixed effects, clusters, or estimands."
        ),
        "model": {
            "cohort": "race",
            "model_id": MODEL_ID,
            "n_rows": rows,
            "outcomes": outcomes,
            "n_outcomes": len(outcomes),
            "n_design_columns": len(fully_adjusted_columns),
            "fixed_effect_indices": FE_INDICES,
            "failed_source_columns": FAILED_SOURCE_COLUMNS,
            "failed_source_column_names": failed_design_names,
            "block_columns": BLOCK_COLUMNS,
        },
        "frozen_scientific_specification_changed": False,
        "sample_formula_outcomes_fixed_effects_clusters_changed": False,
        "preserved_failure": {
            "archive_manifest": file_record(
                archive_manifest_path, phase2
            ),
            "failed_model_log": file_record(failed_log_path, phase2),
            "failed_wrapper_log": file_record(parent_log_path, phase2),
            "engine_sha256_at_failure": OLD_ENGINE_SHA256,
            "results_written_for_failed_model": False,
            "coefficient_values_read_or_interpreted": False,
        },
        "patched_engine": file_record(engine_path, phase2),
        "fallback_test": {
            **file_record(fallback_test_path, phase2),
            "status": fallback_test["status"],
            "checks_passed": fallback_test["checks_passed"],
            "checks_total": fallback_test["checks_total"],
            "real_data_loaded": fallback_test["real_data_loaded"],
        },
        "matrix": {
            "manifest": file_record(matrix_manifest_path, phase2),
            "binding": matrix_binding,
            "live_matrix_file_geometry": live_matrix_files,
        },
        "incomplete_scratch": scratch_records,
        "seeded_state": file_record(state_path),
        "retry_policy": {
            "x_0_4": (
                "Reuse the hash-bound strict nonconvergence and attempt the "
                "1e-6/50000 fallback directly."
            ),
            "all_other_blocks": (
                "Attempt strict 1e-8/10000 first; use 1e-6/50000 only after "
                "the new strict failure is persisted."
            ),
            "fail_closed_if_fallback_does_not_converge": True,
        },
        "real_result_values_read": False,
        "real_result_values_emitted": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    checkpoint_path = (
        phase2
        / "qa"
        / "demeaning_failure_checkpoints"
        / "common_primary_race_m2.json"
    )
    atomic_json(checkpoint_path, checkpoint)
    print(
        json.dumps(
            {
                "status": checkpoint["status"],
                "checkpoint": str(checkpoint_path),
                "checkpoint_sha256": sha256_file(checkpoint_path),
                "seeded_state": str(state_path),
                "seeded_state_sha256": sha256_file(state_path),
                "failed_source_columns": FAILED_SOURCE_COLUMNS,
                "n_rows": rows,
                "real_result_values_read": False,
                "real_result_values_emitted": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
