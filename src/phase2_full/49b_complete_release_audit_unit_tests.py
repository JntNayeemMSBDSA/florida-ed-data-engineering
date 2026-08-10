# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/49b_complete_release_audit_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).with_name("49_complete_analysis_release_audit.py")
SPEC = importlib.util.spec_from_file_location(
    "complete_release_audit",
    SCRIPT,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to import {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def record(
    checks: list[dict[str, Any]],
    check_id: str,
    condition: bool,
    evidence: Any,
) -> None:
    checks.append(
        {
            "check_id": check_id,
            "passed": bool(condition),
            "evidence": evidence,
        }
    )


def main() -> None:
    phase2 = Path(__file__).resolve().parents[1]
    output = (
        phase2 / "qa" / "complete_release_audit_unit_tests.json"
    )
    checks: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(
        prefix="release_audit_unit_",
        dir=phase2.parent.parent / "tmp",
    ) as temporary:
        root = Path(temporary)
        passing = root / "pass.json"
        read_only = root / "read_only.json"
        invalid = root / "invalid.json"
        passing.write_text('{"status":"PASS"}\n', encoding="utf-8")
        read_only.write_text(
            '{"read_only_audit_passed":true}\n',
            encoding="utf-8",
        )
        invalid.write_text("{", encoding="utf-8")

        pass_state = MODULE.status_and_hash(passing)
        read_only_state = MODULE.status_and_hash(read_only)
        missing_state = MODULE.status_and_hash(root / "missing.json")
        invalid_state = MODULE.status_and_hash(invalid)

        record(
            checks,
            "status_reader_accepts_explicit_pass",
            pass_state[0] is True
            and pass_state[1] == "PASS"
            and pass_state[3] is None,
            pass_state,
        )
        record(
            checks,
            "status_reader_accepts_read_only_release_pass",
            read_only_state[0] is True
            and read_only_state[1] == "PASS"
            and read_only_state[3] is None,
            read_only_state,
        )
        record(
            checks,
            "status_reader_fails_closed_on_missing_or_invalid_json",
            missing_state[0] is False
            and missing_state[3] == "missing"
            and invalid_state[0] is True
            and invalid_state[1] is None
            and str(invalid_state[3]).startswith("unreadable:"),
            {
                "missing": missing_state,
                "invalid": invalid_state,
            },
        )

        synthetic_phase2 = root / "phase2"
        included = [
            synthetic_phase2 / "results" / "result.csv",
            synthetic_phase2 / "qa" / "audit.json",
            synthetic_phase2
            / "documentation"
            / "Scientific_SAP_FROZEN.json",
        ]
        excluded = [
            synthetic_phase2 / "qa" / "run_logs" / "worker.log",
            synthetic_phase2 / "qa" / "notes.txt",
            synthetic_phase2 / "documentation" / "unrelated.txt",
        ]
        for path in included + excluded:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        collected = set(MODULE.collect_release_files(synthetic_phase2))
        record(
            checks,
            "release_manifest_scope_includes_results_and_audits_but_excludes_logs",
            all(path.resolve() in collected for path in included)
            and all(path.resolve() not in collected for path in excluded),
            {
                "collected": sorted(str(path) for path in collected),
            },
        )

    directional_stems = [
        f"{family}__{outcome}"
        for family in MODULE.DIRECTIONAL_FAMILIES
        for outcome in MODULE.ALL_DIRECTIONAL_OUTCOMES
    ]
    measurement_stems = [
        f"{family}__{outcome}"
        for family in ["race_dyads", "intersectional_dyads"]
        for outcome in MODULE.PRIMARY_OUTCOMES
    ]
    record(
        checks,
        "frozen_directional_grid_dimensions_are_exact",
        len(MODULE.DIRECTIONAL_FAMILIES) == 3
        and len(MODULE.ALL_DIRECTIONAL_OUTCOMES) == 33
        and len(directional_stems) == 99
        and len(set(directional_stems)) == 99
        and len(measurement_stems) == 4
        and len(set(measurement_stems)) == 4,
        {
            "families": len(MODULE.DIRECTIONAL_FAMILIES),
            "outcomes": len(MODULE.ALL_DIRECTIONAL_OUTCOMES),
            "directional_result_sets": len(directional_stems),
            "measurement_result_sets": len(measurement_stems),
        },
    )

    audit_ids = [item.audit_id for item in MODULE.REQUIRED_AUDITS]
    audit_paths = [item.relative_path for item in MODULE.REQUIRED_AUDITS]
    record(
        checks,
        "required_audit_registry_is_unique",
        len(audit_ids) == len(set(audit_ids))
        and len(audit_paths) == len(set(audit_paths))
        and all(item.expected_status == "PASS" for item in MODULE.REQUIRED_AUDITS),
        {
            "audit_count": len(audit_ids),
            "unique_ids": len(set(audit_ids)),
            "unique_paths": len(set(audit_paths)),
        },
    )
    record(
        checks,
        "sap_deviation_gate_requires_current_contiguous_history",
        MODULE.EXPECTED_SAP_DEVIATION_IDS
        == [f"DEV-{number:03d}" for number in range(1, 20)],
        MODULE.EXPECTED_SAP_DEVIATION_IDS,
    )
    sap_path = phase2 / "documentation" / "SAP_deviation_log.csv"
    with sap_path.open("r", encoding="utf-8-sig", newline="") as stream:
        observed_sap_ids = [
            str(row.get("deviation_id", "")).strip()
            for row in csv.DictReader(stream)
        ]
    record(
        checks,
        "current_sap_deviation_log_matches_release_gate",
        observed_sap_ids == MODULE.EXPECTED_SAP_DEVIATION_IDS,
        observed_sap_ids,
    )

    global_freeze_path = (
        phase2
        / "documentation"
        / "Independent_Global_Multiplicity_Audit_Code_FROZEN.json"
    )
    global_freeze = json.loads(
        global_freeze_path.read_text(encoding="utf-8")
    )
    global_code_checks = []
    for item in global_freeze["code_inventory"]:
        path = phase2 / item["path"]
        global_code_checks.append(
            {
                "path": item["path"],
                "passed": path.is_file()
                and MODULE.sha256(path) == item["sha256"],
            }
        )
    global_test = global_freeze["synthetic_validation"]
    global_test_path = phase2 / global_test["path"]
    record(
        checks,
        "global_multiplicity_code_freeze_matches_live_files",
        global_freeze.get("status") == "PASS"
        and global_freeze.get("freeze_state")
        == "FROZEN_ESTIMATE_BLIND_PASS"
        and len(global_code_checks) == 3
        and all(item["passed"] for item in global_code_checks)
        and global_test_path.is_file()
        and MODULE.sha256(global_test_path) == global_test["sha256"],
        {
            "code_checks": global_code_checks,
            "synthetic_validation": global_test,
        },
    )

    phase1_freeze_path = (
        phase2
        / "documentation"
        / "Independent_Phase1_Immutability_Audit_Code_FROZEN.json"
    )
    phase1_freeze = json.loads(
        phase1_freeze_path.read_text(encoding="utf-8")
    )
    phase1_code_checks = []
    for item in phase1_freeze["code_inventory"]:
        path = phase2 / item["path"]
        phase1_code_checks.append(
            {
                "path": item["path"],
                "passed": path.is_file()
                and MODULE.sha256(path) == item["sha256"],
            }
        )
    phase1_test = phase1_freeze["synthetic_validation"]
    phase1_test_path = phase2 / phase1_test["path"]
    phase1_roots = phase1_freeze["frozen_phase1_roots"]
    file_manifest_path = (
        phase2 / phase1_roots["file_manifest_path"]
    ).resolve()
    build_manifest_path = (
        phase2 / phase1_roots["build_manifest_path"]
    ).resolve()
    source_binding = phase1_freeze[
        "independent_pre_deferral_source_binding"
    ]
    source_binding_path = (phase2 / source_binding["path"]).resolve()
    record(
        checks,
        "phase1_immutability_code_freeze_matches_live_files",
        phase1_freeze.get("status") == "PASS"
        and phase1_freeze.get("freeze_state")
        == "FROZEN_PRE_FINAL_AUDIT_PASS"
        and len(phase1_code_checks) == 2
        and all(item["passed"] for item in phase1_code_checks)
        and phase1_test_path.is_file()
        and MODULE.sha256(phase1_test_path) == phase1_test["sha256"]
        and file_manifest_path.is_file()
        and MODULE.sha256(file_manifest_path)
        == phase1_roots["file_manifest_sha256"]
        and build_manifest_path.is_file()
        and MODULE.sha256(build_manifest_path)
        == phase1_roots["build_manifest_sha256"]
        and source_binding_path.is_file()
        and MODULE.sha256(source_binding_path) == source_binding["sha256"],
        {
            "code_checks": phase1_code_checks,
            "synthetic_validation": phase1_test,
            "file_manifest": str(file_manifest_path),
            "build_manifest": str(build_manifest_path),
            "source_binding": str(source_binding_path),
        },
    )

    passed = sum(check["passed"] for check in checks)
    payload = {
        "test_id": "complete_release_audit_unit_tests_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if passed == len(checks) else "FAIL",
        "checks_passed": passed,
        "checks_total": len(checks),
        "checks": checks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit("Complete release audit unit tests failed")


if __name__ == "__main__":
    main()
