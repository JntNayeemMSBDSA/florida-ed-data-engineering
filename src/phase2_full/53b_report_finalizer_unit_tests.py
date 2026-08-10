#!/usr/bin/env python
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/53b_report_finalizer_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic fail-closed tests for stable report finalization."""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from pypdf import PdfWriter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("report_finalizer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_record(module, staging: Path, name: str) -> dict[str, object]:
    pdf = staging / f"{name}_DRAFT.pdf"
    docx = staging / f"{name}_DRAFT.docx"
    source = staging / f"{name}_MATERIALIZED.md"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as stream:
        writer.write(stream)
    document = Document()
    document.add_paragraph(f"Synthetic document for {name}")
    document.save(docx)
    source.write_text(f"# Synthetic {name}\n", encoding="utf-8")
    return {
        "pdf": str(pdf),
        "pdf_sha256": module.sha256(pdf),
        "docx": str(docx),
        "docx_sha256": module.sha256(docx),
        "source": str(source),
        "source_sha256": module.sha256(source),
        "page_count": 1,
        "page_images": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase2",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    module = load_module(phase2 / "scripts" / "53_finalize_report_release.py")
    checks: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="report_finalizer_test_") as raw:
        root = Path(raw)
        report_root = root / "a" / "b" / "report_production"
        staging = root / "staging"
        report_root.mkdir(parents=True)
        staging.mkdir(parents=True)
        records = [
            make_record(module, staging, name)
            for name in module.REPORT_NAMES
        ]
        invalid = {"reports": [dict(record) for record in records]}
        invalid["reports"][1]["pdf_sha256"] = "0" * 64
        rejected = False
        try:
            module.verify_final_file_set(report_root, invalid)
        except RuntimeError:
            rejected = True
        stable_after_failure = list(report_root.iterdir())
        checks.append(
            {
                "check_id": "invalid_set_rejected_before_stable_write",
                "passed": rejected and not stable_after_failure,
                "evidence": [path.name for path in stable_after_failure],
            }
        )
        valid = {"reports": records}
        rows_first = module.verify_final_file_set(report_root, valid)
        expected = {
            f"{name}.{suffix}"
            for name in module.REPORT_NAMES
            for suffix in ("pdf", "docx", "md")
        }
        observed = {path.name for path in report_root.iterdir()}
        checks.append(
            {
                "check_id": "valid_set_materializes_exact_stable_files",
                "passed": observed == expected and len(rows_first) == 6,
                "evidence": sorted(observed),
            }
        )
        rows_second = module.verify_final_file_set(report_root, valid)
        checks.append(
            {
                "check_id": "identical_second_run_is_idempotent",
                "passed": rows_first == rows_second,
                "evidence": len(rows_second),
            }
        )
    status = "PASS" if all(bool(row["passed"]) for row in checks) else "FAIL"
    payload = {
        "test_id": "report_finalizer_unit_tests_v1",
        "created_utc": utc_now(),
        "status": status,
        "checks_passed": sum(bool(row["passed"]) for row in checks),
        "checks_total": len(checks),
        "checks": checks,
        "synthetic_only": True,
        "real_result_values_read": False,
    }
    output = phase2 / "qa" / "report_finalizer_unit_tests.json"
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
