#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/30f_aggregate_model_audit_checkpoints.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Aggregate independently recomputed model checkpoints after compaction."""

from __future__ import annotations

import argparse
import hashlib
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
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def verify_result_inventory(checkpoint: dict[str, Any]) -> bool:
    manifest_path = Path(
        checkpoint["result_manifest"]["path"]
    ).resolve()
    if (
        not manifest_path.exists()
        or sha256_file(manifest_path)
        != checkpoint["result_manifest"]["sha256"]
    ):
        return False
    result_folder = manifest_path.parent
    for item in checkpoint["results_inventory"]:
        path = result_folder / item["relative_path"]
        if (
            not path.exists()
            or path.stat().st_size != int(item["bytes"])
            or sha256_file(path) != item["sha256"]
        ):
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--expected-audit-ids", required=True)
    parser.add_argument("--output-stem", required=True)
    parser.add_argument("--audit-id", required=True)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    qa = phase2 / "qa"
    checkpoint_root = qa / "model_audit_checkpoints"
    expected_ids = [
        value.strip()
        for value in args.expected_audit_ids.split(",")
        if value.strip()
    ]
    if len(expected_ids) != len(set(expected_ids)) or not expected_ids:
        raise SystemExit("Expected audit IDs must be nonempty and unique")
    for value in [*expected_ids, args.output_stem, args.audit_id]:
        if Path(value).name != value or value in {".", ".."}:
            raise SystemExit(f"Unsafe checkpoint/output identifier: {value}")

    live_gate_hashes = {
        "provider_gate_sha256": sha256_file(
            qa / "pre_estimation_measurement_gate.json"
        ),
        "cohort_gate_sha256": sha256_file(
            qa / "cohort_validation_report.json"
        ),
        "gender_checkpoint_sha256": sha256_file(
            qa / "provider_gender_measurement_checkpoint.json"
        ),
    }
    checkpoints: dict[str, Any] = {}
    checkpoint_rows: list[pd.DataFrame] = []
    aggregation_checks: list[dict[str, Any]] = []
    matrix_ids: list[str] = []
    for audit_id in expected_ids:
        checkpoint_path = checkpoint_root / f"{audit_id}.json"
        checkpoint_csv = checkpoint_root / f"{audit_id}.csv"
        if not checkpoint_path.exists() or not checkpoint_csv.exists():
            raise SystemExit(f"Missing checkpoint artifacts: {audit_id}")
        checkpoint = json.loads(
            checkpoint_path.read_text(encoding="utf-8")
        )
        matrix_id = str(checkpoint.get("matrix_id", ""))
        matrix_ids.append(matrix_id)
        compaction_path = (
            qa / "model_intermediate_compaction" / f"{matrix_id}.json"
        )
        compaction = (
            json.loads(compaction_path.read_text(encoding="utf-8"))
            if compaction_path.exists()
            else {}
        )
        passed = (
            checkpoint.get("audit_id") == audit_id
            and checkpoint.get("all_passed") is True
            and checkpoint.get("live_gate_hashes") == live_gate_hashes
            and verify_result_inventory(checkpoint)
            and compaction.get("compaction_passed") is True
            and compaction.get("matrix_id") == matrix_id
            and compaction.get("checkpoint_sha256")
                == sha256_file(checkpoint_path)
            and compaction.get("result_artifacts_preserved_and_reverified")
                is True
            and compaction.get("source_release_modified") is False
        )
        aggregation_checks.append(
            {
                "cohort": checkpoint.get("cohort"),
                "matrix_id": matrix_id,
                "analysis_sample_policy": checkpoint.get(
                    "analysis_sample_policy"
                ),
                "eligibility_policy": checkpoint.get(
                    "eligibility_policy"
                ),
                "audit_check": (
                    "checkpoint_gate_result_and_compaction_revalidation"
                ),
                "value": int(passed),
                "tolerance": 0,
                "passed": bool(passed),
                "details": audit_id,
            }
        )
        checkpoints[audit_id] = {
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_sha256": sha256_file(checkpoint_path),
            "compaction_path": str(compaction_path),
            "matrix_id": matrix_id,
            "cohort": checkpoint.get("cohort"),
            "analysis_sample_policy": checkpoint.get(
                "analysis_sample_policy"
            ),
            "eligibility_policy": checkpoint.get("eligibility_policy"),
            "expected_outcome": checkpoint.get("expected_outcome"),
            "checks": checkpoint.get("checks"),
            "all_passed": checkpoint.get("all_passed"),
        }
        checkpoint_rows.append(pd.read_csv(checkpoint_csv))

    unique_matrix_ids = len(matrix_ids) == len(set(matrix_ids))
    aggregation_checks.append(
        {
            "cohort": "all",
            "matrix_id": "all",
            "analysis_sample_policy": "all",
            "eligibility_policy": "all",
            "audit_check": "expected_checkpoint_and_matrix_ids_unique",
            "value": len(set(matrix_ids)),
            "tolerance": len(expected_ids),
            "passed": unique_matrix_ids,
            "details": json.dumps(matrix_ids),
        }
    )
    table = pd.concat(
        [pd.DataFrame(aggregation_checks), *checkpoint_rows],
        ignore_index=True,
        sort=False,
    )
    table["passed"] = table["passed"].map(
        lambda value: str(value).strip().lower() == "true"
        if not isinstance(value, bool)
        else value
    )
    csv_path = qa / f"{args.output_stem}.csv"
    json_path = qa / f"{args.output_stem}.json"
    table.to_csv(csv_path, index=False)
    summary = {
        "created_utc": now_utc(),
        "audit_id": args.audit_id,
        "aggregation_method": (
            "Each matrix was independently recomputed against stored model "
            "outputs before its large intermediates were removed. This "
            "aggregate revalidates gates, result hashes, checkpoints, and "
            "compaction manifests."
        ),
        "expected_audit_ids": expected_ids,
        "expected_checkpoint_count": len(expected_ids),
        "observed_checkpoint_count": len(checkpoints),
        "checks": len(table),
        "passed_checks": int(table["passed"].sum()),
        "failed_checks": int((~table["passed"]).sum()),
        "all_passed": bool(table["passed"].all()),
        "live_gate_hashes": live_gate_hashes,
        "checkpoints": checkpoints,
        "check_table": str(csv_path),
    }
    atomic_json(json_path, summary)
    if not summary["all_passed"]:
        raise RuntimeError(
            f"Aggregated checkpoint audit failed: {args.audit_id}"
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
