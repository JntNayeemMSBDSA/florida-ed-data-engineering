#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/48b_aggregate_directional_measurement_sensitivity_audits.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Aggregate the four primary-outcome directional sensitivity audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FAMILIES = ("race_dyads", "intersectional_dyads")
OUTCOMES = (
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    results_root = args.results_root.resolve()
    audits = []
    failures = []
    for family in FAMILIES:
        for outcome in OUTCOMES:
            audit_path = (
                phase2
                / "qa"
                / "directional_measurement_sensitivity_audits"
                / f"{family}__{outcome}.json"
            )
            manifest_path = (
                results_root
                / family
                / outcome
                / "measurement_sensitivity_manifest.json"
            )
            if not audit_path.is_file() or not manifest_path.is_file():
                failures.append(f"{family}/{outcome}:missing")
                continue
            audit = load_json(audit_path)
            manifest = load_json(manifest_path)
            passed = (
                audit.get("status") == "PASS"
                and audit.get("family") == family
                and audit.get("outcome") == outcome
                and audit.get("result_interpretation_authorized") is True
                and manifest.get("status") == "PASS"
                and manifest.get("family") == family
                and manifest.get("outcome") == outcome
            )
            if not passed:
                failures.append(f"{family}/{outcome}:not_pass")
            audits.append(
                {
                    "family": family,
                    "outcome": outcome,
                    "audit_path": str(audit_path),
                    "audit_sha256": sha256_file(audit_path),
                    "manifest_path": str(manifest_path),
                    "manifest_sha256": sha256_file(manifest_path),
                    "passed": passed,
                }
            )
    payload = {
        "audit_id": (
            "aggregate_directional_measurement_sensitivity_audit_v1"
        ),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures and len(audits) == 4 else "FAIL",
        "required_sets": 4,
        "audited_sets": len(audits),
        "audits": audits,
        "failures": failures,
        "scope": (
            "Five-class physician-race measurement sensitivities for the "
            "two frozen primary outcomes in race and expanded "
            "intersectional directional families."
        ),
        "result_interpretation_authorized": (
            not failures and len(audits) == 4
        ),
        "association_language_required": True,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output = (
        phase2
        / "qa"
        / "independent_directional_measurement_sensitivity_audit.json"
    )
    atomic_json(output, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "audited_sets": len(audits),
                "required_sets": 4,
                "failures": failures,
                "result_values_emitted": False,
            },
            indent=2,
        )
    )
    if payload["status"] != "PASS":
        raise SystemExit("Directional sensitivity aggregate audit failed")


if __name__ == "__main__":
    main()
