#!/usr/bin/env python
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/51b_report_content_audit_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic tests for report source-snapshot fail-closed behavior."""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("report_content_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase2",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    module = load_module(
        phase2 / "scripts" / "51_audit_report_content_and_safety.py"
    )
    checks = []
    with tempfile.TemporaryDirectory(prefix="report_snapshot_test_") as raw:
        workspace = Path(raw)
        first = workspace / "source" / "first.txt"
        second = workspace / "source" / "second.txt"
        first.parent.mkdir(parents=True)
        first.write_text("alpha\n", encoding="utf-8")
        second.write_text("beta\n", encoding="utf-8")
        manifest = {
            "file_count": 2,
            "files": [
                {
                    "workspace_relative_path": "source/first.txt",
                    "sha256": module.sha256(first),
                },
                {
                    "workspace_relative_path": "source/second.txt",
                    "sha256": module.sha256(second),
                },
            ],
        }
        passing = module.audit_source_snapshot(manifest, workspace)
        checks.append(
            {
                "check_id": "matching_snapshot_passes",
                "passed": passing == [],
                "evidence": passing,
            }
        )
        first.write_text("changed\n", encoding="utf-8")
        changed = module.audit_source_snapshot(manifest, workspace)
        checks.append(
            {
                "check_id": "changed_source_fails",
                "passed": len(changed) == 1
                and changed[0]["path"] == "source/first.txt",
                "evidence": changed,
            }
        )
        second.unlink()
        changed_and_missing = module.audit_source_snapshot(
            manifest, workspace
        )
        checks.append(
            {
                "check_id": "missing_source_fails",
                "passed": len(changed_and_missing) == 2
                and any(
                    row["path"] == "source/second.txt"
                    and row["observed"] is None
                    for row in changed_and_missing
                ),
                "evidence": changed_and_missing,
            }
        )
    status = "PASS" if all(row["passed"] for row in checks) else "FAIL"
    payload = {
        "test_id": "report_content_audit_unit_tests_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checks_passed": sum(row["passed"] for row in checks),
        "checks_total": len(checks),
        "checks": checks,
        "synthetic_only": True,
        "real_result_values_read": False,
    }
    output = phase2 / "qa" / "report_content_audit_unit_tests.json"
    output.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
