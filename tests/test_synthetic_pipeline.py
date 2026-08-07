from __future__ import annotations

import csv
import json
from pathlib import Path

from synthetic_demo.generate_synthetic_data import SEED, TOTAL_ROWS, generate
from synthetic_demo.run_demo_pipeline import run


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "synthetic_demo" / "expected_outputs"


def test_synthetic_pipeline_matches_expected_outputs(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "output"
    generate(raw, SEED)
    run(raw, output)

    for name in ("qa_summary.json", "schema_reconciliation.csv", "category_summary.csv"):
        assert (output / name).read_bytes() == (EXPECTED / name).read_bytes()

    qa = json.loads((output / "qa_summary.json").read_text(encoding="utf-8"))
    assert qa["synthetic"] is True
    assert qa["standardized_rows"] == TOTAL_ROWS
    assert qa["overall_status"] == "PASS"
    assert qa["icd_transition_error_rows"] == 0
    assert qa["organization_classified_as_physician_rows"] == 0
    assert qa["historical_hourly_los_imputed_rows"] == 0


def test_synthetic_ids_and_provider_rules_are_explicit(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "output"
    generate(raw, SEED)
    run(raw, output)

    with (output / "standardized_synthetic_encounters.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == TOTAL_ROWS
    assert all(row["synthetic_visit_id"].startswith("SYN-REC-") for row in rows)
    assert all(row["synthetic_provider_id"].startswith("SYN-NPI-") for row in rows)
    assert all(row["synthetic_facility_id"].startswith("SYN-FAC-") for row in rows)
    assert all(
        row["physician_flag"] == "0"
        for row in rows
        if row["provider_entity_type"] == "ORGANIZATION"
    )


def test_generation_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate(first, SEED)
    generate(second, SEED)
    first_files = sorted(path.relative_to(first) for path in first.glob("*"))
    second_files = sorted(path.relative_to(second) for path in second.glob("*"))
    assert first_files == second_files
    for relative in first_files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
