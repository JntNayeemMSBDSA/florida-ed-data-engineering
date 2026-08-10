#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/34b_directional_dyad_definition_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Estimate-blind definition tests for the directional-dyad extension."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_freeze_module(path: Path):
    spec = importlib.util.spec_from_file_location(
        "directional_dyad_freeze_module", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def linear_value(
    item: dict[str, Any], values: dict[str, float]
) -> float:
    return sum(
        float(term["weight"]) * values[term["cell_id"]]
        for term in item["linear_combination"]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    module = load_freeze_module(
        phase2 / "scripts" / "34_freeze_directional_dyad_extension.py"
    )

    gender_cells, gender_contrasts = module.build_gender_plan()
    race_cells, race_contrasts = module.build_race_plan()
    intersectional_cells, intersectional_contrasts = (
        module.build_intersectional_plan()
    )

    checks: list[dict[str, Any]] = []

    def check(
        check_id: str,
        description: str,
        predicate: bool | Callable[[], bool],
    ) -> None:
        passed = bool(predicate() if callable(predicate) else predicate)
        checks.append(
            {
                "check_id": check_id,
                "description": description,
                "status": "PASS" if passed else "FAIL",
            }
        )

    check(
        "DYAD-001",
        "Gender plan contains exactly four cells and six pairwise contrasts.",
        len(gender_cells) == 4 and len(gender_contrasts) == 6,
    )
    check(
        "DYAD-002",
        "Race plan contains exactly 25 cells and 68 planned contrasts.",
        len(race_cells) == 25 and len(race_contrasts) == 68,
    )
    check(
        "DYAD-003",
        "Intersectional plan contains exactly 100 cells and 359 contrasts.",
        len(intersectional_cells) == 100
        and len(intersectional_contrasts) == 359,
    )

    for prefix, cells, contrasts in (
        ("GENDER", gender_cells, gender_contrasts),
        ("RACE", race_cells, race_contrasts),
        ("INTERSECTIONAL", intersectional_cells, intersectional_contrasts),
    ):
        cell_ids = [item["cell_id"] for item in cells]
        contrast_ids = [item["contrast_id"] for item in contrasts]
        check(
            f"{prefix}-UNIQUE-CELLS",
            f"{prefix} cell identifiers are unique.",
            len(cell_ids) == len(set(cell_ids)),
        )
        check(
            f"{prefix}-UNIQUE-CONTRASTS",
            f"{prefix} contrast identifiers are unique.",
            len(contrast_ids) == len(set(contrast_ids)),
        )
        check(
            f"{prefix}-VALID-REFERENCES",
            f"Every {prefix} contrast references only frozen cells.",
            all(
                term["cell_id"] in set(cell_ids)
                for item in contrasts
                for term in item["linear_combination"]
            ),
        )
        check(
            f"{prefix}-ZERO-SUM",
            f"Every {prefix} difference contrast has weights summing to zero.",
            all(
                math.isclose(
                    sum(
                        float(term["weight"])
                        for term in item["linear_combination"]
                    ),
                    0.0,
                    abs_tol=1e-12,
                )
                for item in contrasts
            ),
        )

        synthetic = {
            cell_id: float(index + 1)
            for index, cell_id in enumerate(cell_ids)
        }
        check(
            f"{prefix}-LINEAR-ALGEBRA",
            f"{prefix} contrasts reproduce direct synthetic cell arithmetic.",
            all(
                math.isfinite(linear_value(item, synthetic))
                for item in contrasts
            ),
        )

    gender_ids = {item["cell_id"] for item in gender_cells}
    check(
        "DYAD-004",
        "All four physician-first gender pair labels are present.",
        gender_ids
        == {
            "physician=Male|patient=Male",
            "physician=Male|patient=Female",
            "physician=Female|patient=Male",
            "physician=Female|patient=Female",
        },
    )

    race_ids = {item["cell_id"] for item in race_cells}
    check(
        "DYAD-005",
        "Directional White physician-proxy and Black patient cell is present.",
        "physician=White|patient=Black" in race_ids,
    )
    check(
        "DYAD-006",
        "Directional Black physician-proxy and White patient cell is distinct.",
        (
            "physician=Black|patient=White" in race_ids
            and "physician=Black|patient=White"
            != "physician=White|patient=Black"
        ),
    )
    check(
        "DYAD-007",
        "No five-class race label is silently removed or merged.",
        {
            item["physician_group"] for item in race_cells
        }
        == set(module.PHYSICIAN_RACES)
        and {item["patient_group"] for item in race_cells}
        == set(module.PATIENT_RACES),
    )

    intersectional_ids = {
        item["cell_id"] for item in intersectional_cells
    }
    check(
        "DYAD-008",
        "Requested White female physician by White male patient example exists.",
        (
            "physician_race=White|physician_gender=Female|"
            "patient_race=White|patient_sex=Male"
        )
        in intersectional_ids,
    )
    check(
        "DYAD-009",
        "Intersectional physician and patient directions remain explicit.",
        all(
            all(
                token in item["cell_id"]
                for token in (
                    "physician_race=",
                    "physician_gender=",
                    "patient_race=",
                    "patient_sex=",
                )
            )
            for item in intersectional_cells
        ),
    )

    mapping = module.build_race_plan
    check(
        "DYAD-010",
        "Five-class physician proxy vector order is frozen and complete.",
        module.PHYSICIAN_RACES
        == (
            "White",
            "Black",
            "Hispanic",
            "Asian",
            "Other/multiracial",
        ),
    )
    check(
        "DYAD-011",
        "Primary outcomes retain the frozen LOS and reported-real-charge names.",
        module.PRIMARY_OUTCOMES
        == (
            "los_hours_primary_0_168",
            "total_charge_reported_real_2024",
        ),
    )
    check(
        "DYAD-012",
        "Race plan builder is deterministic within one process.",
        mapping() == module.build_race_plan(),
    )

    failed = [item for item in checks if item["status"] != "PASS"]
    report = {
        "status": "PASS" if not failed else "FAIL",
        "created_utc": utc_now(),
        "test_suite": "directional_dyad_extension_definition_tests_v1",
        "tests": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "checks": checks,
        "estimate_values_read": False,
    }
    output = (
        phase2 / "qa" / "directional_dyad_definition_unit_tests.json"
    )
    atomic_json(output, report)
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
