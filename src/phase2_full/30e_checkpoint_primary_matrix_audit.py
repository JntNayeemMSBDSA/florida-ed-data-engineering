#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/30e_checkpoint_primary_matrix_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Audit one primary-model matrix and freeze a compaction-safe checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_auditor(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "phase2_single_matrix_primary_auditor", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load primary auditor: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError("Expected true or false")


def file_inventory(folder: Path) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": path.relative_to(folder).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    ]


def audit_demeaning_policy(
    phase2: Path,
    primary_scratch: Path,
    scratch_id: str,
    results_root: Path,
    cohort: str,
    matrix_manifest: dict[str, Any],
    result_manifest: dict[str, Any],
    audit_id: str,
) -> tuple[bool, dict[str, Any]]:
    """Independently validate complete strict/fallback demeaning provenance."""
    engine_path = phase2 / "scripts" / "08_estimate_primary_models.py"
    engine_sha256 = sha256_file(engine_path)
    failures: list[str] = []
    model_records: dict[str, Any] = {}
    expected_rows = int(matrix_manifest["n_rows"])
    expected_outcomes = len(matrix_manifest["outcomes"])
    model_ids = list(result_manifest.get("model_ids", []))
    fe_model_ids = [
        model_id
        for model_id in model_ids
        if model_id != "m1_patient_adjusted"
    ]
    if result_manifest.get("inference_engine_sha256") != engine_sha256:
        failures.append("result manifest is not bound to the live engine")
    if len(fe_model_ids) != 2:
        failures.append(
            f"expected two fixed-effect models, found {fe_model_ids}"
        )

    for model_id in fe_model_ids:
        state_path = (
            primary_scratch / scratch_id / model_id / "demeaning_state.json"
        )
        diagnostic_path = (
            results_root / cohort / f"{model_id}_diagnostics.json"
        )
        record: dict[str, Any] = {
            "state_path": str(state_path),
            "diagnostic_path": str(diagnostic_path),
        }
        model_failures: list[str] = []
        if not state_path.is_file() or not diagnostic_path.is_file():
            model_failures.append("state or diagnostic is missing")
            record["failures"] = model_failures
            model_records[model_id] = record
            failures.extend(f"{model_id}: {value}" for value in model_failures)
            continue
        state = json.loads(state_path.read_text(encoding="utf-8"))
        diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        column_indices = list(state.get("column_indices", []))
        completed_columns = list(state.get("completed_local_columns", []))
        completed_outcomes = list(
            state.get("completed_outcome_columns", [])
        )
        attempts = dict(state.get("demeaning_attempts", {}))
        numerical_policy = dict(state.get("numerical_policy", {}))
        strict_policy = dict(numerical_policy.get("strict", {}))
        fallback_policy = dict(
            numerical_policy.get(
                "fallback_only_after_documented_strict_nonconvergence", {}
            )
        )
        diagnostic_demeaning = dict(diagnostic.get("demeaning", {}))
        block_columns = int(
            diagnostic_demeaning.get("block_columns", 0) or 0
        )
        if block_columns <= 0:
            model_failures.append("invalid diagnostic block size")
            block_columns = 4
        expected_attempts: dict[str, list[int]] = {}
        for start in range(0, len(column_indices), block_columns):
            stop = min(len(column_indices), start + block_columns)
            expected_attempts[f"x_{start}_{stop}"] = column_indices[start:stop]
        for start in range(0, expected_outcomes, block_columns):
            stop = min(expected_outcomes, start + block_columns)
            expected_attempts[f"y_{start}_{stop}"] = list(range(start, stop))

        if state.get("n_rows") != expected_rows:
            model_failures.append("state row count mismatch")
        if completed_columns != list(range(len(column_indices))):
            model_failures.append("design demeaning is incomplete")
        if completed_outcomes != list(range(expected_outcomes)):
            model_failures.append("outcome demeaning is incomplete")
        if state.get("outcomes_completed") is not True:
            model_failures.append("outcomes_completed is not true")
        if set(attempts) != set(expected_attempts):
            model_failures.append("attempt grid is incomplete or unexpected")
        convergence = dict(state.get("convergence", {}))
        if set(convergence) != set(expected_attempts) or not all(
            value is True for value in convergence.values()
        ):
            model_failures.append("convergence grid is incomplete or false")
        if strict_policy != {
            "tolerance": 1e-8,
            "maxiter": 10_000,
            "backend": "rust",
        }:
            model_failures.append("strict numerical policy changed")
        if fallback_policy != {
            "tolerance": 1e-6,
            "maxiter": 50_000,
            "backend": "rust",
        }:
            model_failures.append("fallback numerical policy changed")
        if numerical_policy.get(
            "sample_formula_fixed_effects_and_columns_changed"
        ) is not False:
            model_failures.append("scientific specification change recorded")

        fallback_keys: list[str] = []
        for attempt_key, expected_source in expected_attempts.items():
            attempt = dict(attempts.get(attempt_key, {}))
            if attempt.get("source_columns") != expected_source:
                model_failures.append(
                    f"{attempt_key}: source columns do not reconcile"
                )
            if attempt.get("final_status") != "CONVERGED":
                model_failures.append(
                    f"{attempt_key}: final status is not CONVERGED"
                )
            if attempt.get("fallback_used") is True:
                fallback_keys.append(attempt_key)
                if not (
                    attempt.get("strict_status") == "NONCONVERGED"
                    and attempt.get("strict_tolerance") == 1e-8
                    and attempt.get("strict_maxiter") == 10_000
                    and attempt.get("fallback_tolerance") == 1e-6
                    and attempt.get("fallback_maxiter") == 50_000
                    and attempt.get("fallback_status") == "CONVERGED"
                    and attempt.get("final_method") == "fallback"
                ):
                    model_failures.append(
                        f"{attempt_key}: fallback lacks a valid strict failure"
                    )
            elif not (
                attempt.get("strict_status") == "CONVERGED"
                and attempt.get("strict_tolerance") == 1e-8
                and attempt.get("strict_maxiter") == 10_000
                and attempt.get("final_method") == "strict"
                and attempt.get("fallback_used") is False
            ):
                model_failures.append(
                    f"{attempt_key}: strict completion metadata is invalid"
                )

        if set(diagnostic_demeaning.get("fallback_blocks", [])) != set(
            fallback_keys
        ):
            model_failures.append(
                "diagnostic fallback block list does not match state"
            )
        if diagnostic_demeaning.get("fallback_used") is not bool(
            fallback_keys
        ):
            model_failures.append(
                "diagnostic fallback-used flag does not match state"
            )
        if diagnostic_demeaning.get("converged") is not True:
            model_failures.append("diagnostic does not record convergence")
        if (
            diagnostic_demeaning.get("checkpoint_binding")
            != state.get("checkpoint_binding")
        ):
            model_failures.append(
                "diagnostic and state matrix/gate bindings differ"
            )

        if audit_id == "common_primary_race" and model_id.startswith("m2_"):
            retry_path = (
                phase2
                / "qa"
                / "demeaning_failure_checkpoints"
                / "common_primary_race_m2.json"
            )
            record["retry_checkpoint_path"] = str(retry_path)
            if not retry_path.is_file():
                model_failures.append("required retry checkpoint is missing")
            else:
                retry = json.loads(retry_path.read_text(encoding="utf-8"))
                archived_attempt = dict(attempts.get("x_0_4", {}))
                provenance = dict(archived_attempt.get("provenance", {}))
                if not (
                    retry.get("status") == "PASS_RETRY_AUTHORIZED"
                    and retry.get("patched_engine", {}).get("sha256")
                    == engine_sha256
                    and retry.get("model", {}).get("failed_source_columns")
                    == [1, 2, 3, 34]
                    and archived_attempt.get("source_columns")
                    == [1, 2, 3, 34]
                    and archived_attempt.get("strict_status")
                    == "NONCONVERGED"
                    and archived_attempt.get("fallback_used") is True
                    and archived_attempt.get(
                        "strict_attempt_reused_from_checkpoint"
                    )
                    is True
                    and provenance.get("archive_id")
                    == (
                        "common_primary_race_m2_strict_"
                        "nonconvergence_20260727T0221Z"
                    )
                    and provenance.get("failed_log_sha256")
                    == retry.get("preserved_failure", {})
                    .get("failed_model_log", {})
                    .get("sha256")
                    and retry.get("frozen_scientific_specification_changed")
                    is False
                    and retry.get(
                        "sample_formula_outcomes_fixed_effects_clusters_changed"
                    )
                    is False
                ):
                    model_failures.append(
                        "archived race M2 retry provenance does not reconcile"
                    )
                record["retry_checkpoint_sha256"] = sha256_file(retry_path)

        record.update(
            {
                "state_sha256": sha256_file(state_path),
                "diagnostic_sha256": sha256_file(diagnostic_path),
                "design_columns": len(column_indices),
                "outcomes": expected_outcomes,
                "attempts": len(attempts),
                "fallback_blocks": fallback_keys,
                "all_attempts_final_converged": not any(
                    "final status" in value for value in model_failures
                ),
                "failures": model_failures,
            }
        )
        model_records[model_id] = record
        failures.extend(f"{model_id}: {value}" for value in model_failures)

    details = {
        "status": "PASS" if not failures else "FAIL",
        "audit_version": "independent_demeaning_policy_audit_v1",
        "live_engine_sha256": engine_sha256,
        "models": model_records,
        "failures": failures,
        "coefficient_values_interpreted": False,
        "sample_formula_outcomes_fixed_effects_clusters_changed": False,
    }
    return not failures, details


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--primary-scratch", required=True, type=Path)
    parser.add_argument("--scratch-id", required=True)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument(
        "--cohort", required=True, choices=("race", "sex_gender")
    )
    parser.add_argument("--audit-id", required=True)
    parser.add_argument("--expected-analysis-sample", required=True)
    parser.add_argument("--expected-eligibility-policy", required=True)
    parser.add_argument("--expected-outcome", required=True)
    parser.add_argument(
        "--expected-confirmatory", required=True, type=parse_bool
    )
    parser.add_argument("--row-chunk", type=int, default=333_333)
    args = parser.parse_args()

    for value, label in (
        (args.matrix_id, "matrix-id"),
        (args.scratch_id, "scratch-id"),
        (args.audit_id, "audit-id"),
    ):
        if Path(value).name != value or value in {".", ".."}:
            raise SystemExit(f"--{label} must be one safe name")

    phase2 = args.phase2.resolve()
    matrix_root = args.matrix_root.resolve()
    results_root = args.results_root.resolve()
    primary_scratch = args.primary_scratch.resolve()
    matrix_folder = matrix_root / args.matrix_id
    matrix_manifest_path = matrix_folder / "matrix_manifest.json"
    result_manifest_path = (
        results_root
        / args.cohort
        / "primary_models_manifest.json"
    )
    result_coefficients_path = (
        results_root
        / args.cohort
        / "primary_model_coefficients.csv"
    )
    provider_gate_path = (
        phase2 / "qa" / "pre_estimation_measurement_gate.json"
    )
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"
    gender_checkpoint_path = (
        phase2 / "qa" / "provider_gender_measurement_checkpoint.json"
    )
    required_paths = (
        matrix_manifest_path,
        result_manifest_path,
        result_coefficients_path,
        provider_gate_path,
        cohort_gate_path,
        gender_checkpoint_path,
    )
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise SystemExit(f"Missing audit inputs: {missing}")

    live_gate_hashes = {
        "provider_gate_sha256": sha256_file(provider_gate_path),
        "cohort_gate_sha256": sha256_file(cohort_gate_path),
        "gender_checkpoint_sha256": sha256_file(gender_checkpoint_path),
    }
    for gate_path in (
        provider_gate_path,
        cohort_gate_path,
        gender_checkpoint_path,
    ):
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate.get("status") != "PASS":
            raise SystemExit(f"Required gate does not pass: {gate_path}")

    matrix_manifest = json.loads(
        matrix_manifest_path.read_text(encoding="utf-8")
    )
    result_manifest = json.loads(
        result_manifest_path.read_text(encoding="utf-8")
    )
    expected_matrix = {
        "cohort": args.cohort,
        "matrix_id": args.matrix_id,
        "analysis_sample_policy": args.expected_analysis_sample,
        "eligibility_policy": args.expected_eligibility_policy,
        "primary_outcomes": [args.expected_outcome],
        "outcomes": [args.expected_outcome],
        "outcome_specific_sample": True,
        "outcome_specific_confirmatory_sample": (
            args.expected_confirmatory
        ),
        "confirmatory_designated": args.expected_confirmatory,
        "provider_measurement_version": (
            "provider_master_v2_full_name_race_v1"
        ),
        **live_gate_hashes,
    }
    if args.expected_analysis_sample == "common_primary":
        expected_matrix.pop("primary_outcomes")
        expected_matrix.pop("outcomes")
        expected_matrix["outcome_specific_sample"] = False
        expected_matrix["outcome_specific_confirmatory_sample"] = False
        expected_matrix["confirmatory_designated"] = False
    expected_result = {
        "cohort": args.cohort,
        "matrix_id": args.matrix_id,
        "analysis_sample_policy": args.expected_analysis_sample,
        "eligibility_policy": args.expected_eligibility_policy,
        "outcome_specific_sample": (
            args.expected_analysis_sample != "common_primary"
        ),
        "outcome_specific_confirmatory_sample": (
            args.expected_confirmatory
        ),
        "confirmatory_designated": args.expected_confirmatory,
        "provider_measurement_version": (
            "provider_master_v2_full_name_race_v1"
        ),
        **live_gate_hashes,
    }
    structural_pass = all(
        matrix_manifest.get(key) == value
        for key, value in expected_matrix.items()
    ) and all(
        result_manifest.get(key) == value
        for key, value in expected_result.items()
    )
    if args.expected_analysis_sample == "common_primary":
        structural_pass = structural_pass and (
            args.expected_outcome
            in matrix_manifest.get("primary_outcomes", [])
        )

    auditor = load_auditor(
        phase2 / "scripts" / "30_independent_primary_results_audit.py"
    )
    rows, details = auditor.audit_cohort(
        phase2,
        matrix_root,
        primary_scratch,
        args.cohort,
        args.row_chunk,
        matrix_id=args.matrix_id,
        results_root=results_root,
        scratch_id=args.scratch_id,
    )
    demeaning_pass, demeaning_details = audit_demeaning_policy(
        phase2,
        primary_scratch,
        args.scratch_id,
        results_root,
        args.cohort,
        matrix_manifest,
        result_manifest,
        args.audit_id,
    )
    demeaning_row = {
        "cohort": args.cohort,
        "matrix_id": args.matrix_id,
        "analysis_sample_policy": args.expected_analysis_sample,
        "eligibility_policy": args.expected_eligibility_policy,
        "audit_check": "complete_strict_fallback_demeaning_provenance",
        "value": int(demeaning_pass),
        "tolerance": 0,
        "passed": bool(demeaning_pass),
        "details": json.dumps(
            {
                "status": demeaning_details["status"],
                "model_failures": demeaning_details["failures"],
            },
            sort_keys=True,
        ),
    }
    structural_row = {
        "cohort": args.cohort,
        "matrix_id": args.matrix_id,
        "analysis_sample_policy": args.expected_analysis_sample,
        "eligibility_policy": args.expected_eligibility_policy,
        "audit_check": "matrix_result_policy_and_live_gate_binding",
        "value": int(structural_pass),
        "tolerance": 0,
        "passed": bool(structural_pass),
        "details": json.dumps(
            {
                "matrix_expected": expected_matrix,
                "result_expected": expected_result,
            },
            sort_keys=True,
        ),
    }
    table = pd.DataFrame([structural_row, demeaning_row, *rows])
    table["passed"] = table["passed"].map(bool)
    checkpoint_root = phase2 / "qa" / "model_audit_checkpoints"
    csv_path = checkpoint_root / f"{args.audit_id}.csv"
    json_path = checkpoint_root / f"{args.audit_id}.json"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    table.to_csv(csv_path, index=False)
    inventory = file_inventory(results_root / args.cohort)
    payload = {
        "created_utc": now_utc(),
        "audit_id": args.audit_id,
        "audit_type": "single_primary_matrix_independent_recomputation_v1",
        "cohort": args.cohort,
        "matrix_id": args.matrix_id,
        "analysis_sample_policy": args.expected_analysis_sample,
        "eligibility_policy": args.expected_eligibility_policy,
        "expected_outcome": args.expected_outcome,
        "confirmatory_designated": args.expected_confirmatory,
        "checks": len(table),
        "passed_checks": int(table["passed"].sum()),
        "failed_checks": int((~table["passed"]).sum()),
        "all_passed": bool(table["passed"].all()),
        "live_gate_hashes": live_gate_hashes,
        "matrix_manifest": {
            "path": str(matrix_manifest_path),
            "sha256": sha256_file(matrix_manifest_path),
        },
        "result_manifest": {
            "path": str(result_manifest_path),
            "sha256": sha256_file(result_manifest_path),
        },
        "results_inventory": inventory,
        "independent_details": details,
        "independent_demeaning_policy_audit": demeaning_details,
        "check_table": str(csv_path),
    }
    atomic_json(json_path, payload)
    if not payload["all_passed"]:
        raise RuntimeError(
            f"Single-matrix independent audit failed: {args.audit_id}"
        )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
