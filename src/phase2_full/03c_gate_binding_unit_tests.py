#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/03c_gate_binding_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Deterministic unit tests for model-matrix gate binding."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_engine(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "phase2_hdfe_gate_test_engine", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load model engine from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expects_system_exit(action: Callable[[], Any]) -> bool:
    try:
        action()
    except SystemExit:
        return True
    return False


def accepts(action: Callable[[], Any]) -> bool:
    try:
        action()
    except Exception:
        return False
    return True


def expects_runtime_error(action: Callable[[], Any]) -> bool:
    try:
        action()
    except RuntimeError:
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    qa = phase2 / "qa"
    engine = load_engine(phase2 / "scripts" / "08_estimate_primary_models.py")
    independent_primary = load_engine(
        phase2 / "scripts" / "30_independent_primary_results_audit.py"
    )
    independent_payer = load_engine(
        phase2 / "scripts" / "30d_independent_payer_heterogeneity_audit.py"
    )
    independent_validators = (
        ("independent_primary_audit", independent_primary.validate_gate_binding),
        ("independent_payer_audit", independent_payer.validate_gate_binding),
    )
    rows: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="phase2_gate_test_") as raw_temp:
        temporary = Path(raw_temp)
        provider_gate = temporary / "provider_gate.json"
        cohort_gate = temporary / "cohort_gate.json"
        gender_checkpoint = temporary / "gender_checkpoint.json"
        pass_payload = {"status": "PASS", "test_fixture": True}
        for gate_path in (
            provider_gate,
            cohort_gate,
            gender_checkpoint,
        ):
            gate_path.write_text(
                json.dumps(pass_payload, sort_keys=True), encoding="utf-8"
            )

        valid = {
            "provider_measurement_version": (
                "provider_master_v2_full_name_race_v1"
            ),
            "provider_gate_path": str(provider_gate),
            "provider_gate_sha256": engine.sha256_file(provider_gate),
            "cohort_gate_path": str(cohort_gate),
            "cohort_gate_sha256": engine.sha256_file(cohort_gate),
            "gender_checkpoint_path": str(gender_checkpoint),
            "gender_checkpoint_sha256": engine.sha256_file(
                gender_checkpoint
            ),
        }

        cases: list[tuple[str, bool, Callable[[], Any]]] = [
            (
                "valid_pass_gates_are_accepted",
                True,
                lambda: engine.validate_matrix_gate_binding(deepcopy(valid)),
            ),
            (
                "wrong_provider_measurement_version_is_rejected",
                False,
                lambda: engine.validate_matrix_gate_binding(
                    {
                        **deepcopy(valid),
                        "provider_measurement_version": "legacy_v1",
                    }
                ),
            ),
            (
                "missing_gate_hash_is_rejected",
                False,
                lambda: engine.validate_matrix_gate_binding(
                    {**deepcopy(valid), "provider_gate_sha256": ""}
                ),
            ),
            (
                "missing_gate_file_is_rejected",
                False,
                lambda: engine.validate_matrix_gate_binding(
                    {
                        **deepcopy(valid),
                        "provider_gate_path": str(
                            temporary / "does_not_exist.json"
                        ),
                    }
                ),
            ),
        ]

        for name, should_pass, action in cases:
            observed = (
                not expects_system_exit(action)
                if should_pass
                else expects_system_exit(action)
            )
            rows.append(
                {
                    "test": name,
                    "expected": "accept" if should_pass else "reject",
                    "status": "PASS" if observed else "FAIL",
                }
            )

        for validator_name, validator in independent_validators:
            rows.extend(
                [
                    {
                        "test": f"{validator_name}_accepts_valid_gates",
                        "expected": "accept",
                        "status": (
                            "PASS"
                            if accepts(lambda v=validator: v(deepcopy(valid)))
                            else "FAIL"
                        ),
                    },
                    {
                        "test": f"{validator_name}_rejects_wrong_version",
                        "expected": "reject",
                        "status": (
                            "PASS"
                            if expects_runtime_error(
                                lambda v=validator: v(
                                    {
                                        **deepcopy(valid),
                                        "provider_measurement_version": "legacy_v1",
                                    }
                                )
                            )
                            else "FAIL"
                        ),
                    },
                ]
            )

        provider_gate.write_text(
            json.dumps({"status": "PASS", "mutated": True}, sort_keys=True),
            encoding="utf-8",
        )
        rows.append(
            {
                "test": "stale_gate_hash_is_rejected",
                "expected": "reject",
                "status": (
                    "PASS"
                    if expects_system_exit(
                        lambda: engine.validate_matrix_gate_binding(
                            deepcopy(valid)
                        )
                    )
                    else "FAIL"
                ),
            }
        )
        for validator_name, validator in independent_validators:
            rows.append(
                {
                    "test": f"{validator_name}_rejects_stale_hash",
                    "expected": "reject",
                    "status": (
                        "PASS"
                        if expects_runtime_error(
                            lambda v=validator: v(deepcopy(valid))
                        )
                        else "FAIL"
                    ),
                }
            )

        gender_checkpoint.write_text(
            json.dumps({"status": "PASS", "mutated": True}, sort_keys=True),
            encoding="utf-8",
        )
        rows.append(
            {
                "test": "stale_gender_checkpoint_hash_is_rejected",
                "expected": "reject",
                "status": (
                    "PASS"
                    if expects_system_exit(
                        lambda: engine.validate_matrix_gate_binding(
                            deepcopy(valid)
                        )
                    )
                    else "FAIL"
                ),
            }
        )
        for validator_name, validator in independent_validators:
            rows.append(
                {
                    "test": (
                        f"{validator_name}_rejects_stale_gender_checkpoint"
                    ),
                    "expected": "reject",
                    "status": (
                        "PASS"
                        if expects_runtime_error(
                            lambda v=validator: v(deepcopy(valid))
                        )
                        else "FAIL"
                    ),
                }
            )
        gender_checkpoint.write_text(
            json.dumps(pass_payload, sort_keys=True), encoding="utf-8"
        )

        provider_gate.write_text(
            json.dumps({"status": "FAIL"}, sort_keys=True), encoding="utf-8"
        )
        failing_gate = {
            **deepcopy(valid),
            "provider_gate_sha256": engine.sha256_file(provider_gate),
        }
        rows.append(
            {
                "test": "nonpassing_live_gate_is_rejected",
                "expected": "reject",
                "status": (
                    "PASS"
                    if expects_system_exit(
                        lambda: engine.validate_matrix_gate_binding(
                            failing_gate
                        )
                    )
                    else "FAIL"
                ),
            }
        )
        for validator_name, validator in independent_validators:
            rows.append(
                {
                    "test": f"{validator_name}_rejects_nonpassing_gate",
                    "expected": "reject",
                    "status": (
                        "PASS"
                        if expects_runtime_error(
                            lambda v=validator: v(deepcopy(failing_gate))
                        )
                        else "FAIL"
                    ),
                }
            )

    status = "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL"
    payload = {
        "test_id": "matrix_gate_binding_unit_tests_v1",
        "created_utc": now_utc(),
        "status": status,
        "tests": rows,
    }
    atomic_json(qa / "matrix_gate_binding_unit_tests.json", payload)
    csv_path = qa / "matrix_gate_binding_unit_tests.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("test", "expected", "status")
        )
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(payload, indent=2))
    if status != "PASS":
        raise SystemExit("Matrix gate-binding unit tests failed")


if __name__ == "__main__":
    main()
