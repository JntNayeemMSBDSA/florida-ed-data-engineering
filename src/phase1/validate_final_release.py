# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_full_build_20260724/scripts/validate_final_release.py
# Release and optional dependency roots are supplied by environment.

from __future__ import annotations

import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


DATASET_ROOT = Path(os.environ.get("FL_ED_DATASET_ROOT", "private_data")).expanduser()
OUTPUT_ROOT = Path(
    os.environ.get(
        "FL_ED_PHASE1_OUTPUT",
        str(DATASET_ROOT / "outputs" / "florida_ed_full_build_20260724"),
    )
).expanduser()
PYDEPS = Path(
    os.environ.get(
        "FL_ED_PYDEPS",
        str(DATASET_ROOT / "tmp" / "florida_ed_standardization_20260724" / "pydeps"),
    )
).expanduser()
NBDEPS = Path(
    os.environ.get(
        "FL_ED_NOTEBOOK_DEPS", str(DATASET_ROOT / "tmp" / "nra_package" / "pydeps")
    )
).expanduser()
for dependency in (PYDEPS, NBDEPS):
    if dependency.exists():
        sys.path.insert(0, str(dependency))

import nbformat  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402


EXPECTED_QUARTERS = 76
EXPECTED_YEARS = list(range(2005, 2009)) + list(range(2010, 2025))
STRUCTURAL_NULL_FIELDS = [
    "same_facility_inpatient_admission_flag",
    "revisit_7d_flag",
    "revisit_30d_flag",
    "clinical_triage_level",
]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def workbook_sheet_names(path: Path) -> list[str]:
    namespace = {
        "main": (
            "http://schemas.openxmlformats.org/"
            "spreadsheetml/2006/main"
        )
    }
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(
            archive.read("xl/workbook.xml")
        )
    return [
        sheet.attrib["name"]
        for sheet in root.findall(".//main:sheet", namespace)
    ]


def column_null_counts_from_metadata(
    path: Path, fields: list[str]
) -> tuple[int, dict[str, int | None]]:
    parquet_file = pq.ParquetFile(path)
    metadata = parquet_file.metadata
    schema = parquet_file.schema_arrow
    indexes = {schema.names.index(field): field for field in fields}
    null_counts: dict[str, int | None] = {
        field: 0 for field in fields
    }
    for row_group_index in range(metadata.num_row_groups):
        row_group = metadata.row_group(row_group_index)
        for column_index, field in indexes.items():
            stats = row_group.column(column_index).statistics
            if stats is None or stats.null_count is None:
                null_counts[field] = None
            elif null_counts[field] is not None:
                null_counts[field] = int(null_counts[field]) + int(
                    stats.null_count
                )
    return metadata.num_rows, null_counts


def main() -> None:
    success_paths = sorted(
        OUTPUT_ROOT.glob(
            "fact_ed_visits/visit_year=*/visit_quarter=*/_SUCCESS.json"
        )
    )
    check(
        len(success_paths) == EXPECTED_QUARTERS,
        f"Expected 76 success manifests, found {len(success_paths)}",
    )
    check(
        not list(OUTPUT_ROOT.rglob("*.partial")),
        "Partial output files remain in the release",
    )
    check(
        not list(OUTPUT_ROOT.rglob("_FAILED.json")),
        "Failure markers remain in the release",
    )
    manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in success_paths
    ]
    check(
        all(item["reconciliation_passed"] for item in manifests),
        "At least one quarter reconciliation failed",
    )
    periods = {
        (int(item["year"]), int(item["quarter"]))
        for item in manifests
    }
    expected_periods = {
        (year, quarter)
        for year in EXPECTED_YEARS
        for quarter in range(1, 5)
    }
    check(periods == expected_periods, "Quarter coverage differs from scope")

    fact_paths = sorted(
        OUTPUT_ROOT.glob(
            "fact_ed_visits/visit_year=*/visit_quarter=*/ed_visits.parquet"
        )
    )
    bridge_patterns = {
        "visit_diagnosis": (
            "bridges/visit_diagnosis/visit_year=*/"
            "visit_quarter=*/visit_diagnosis.parquet"
        ),
        "visit_diagnosis_category": (
            "bridges/visit_diagnosis_category/visit_year=*/"
            "visit_quarter=*/visit_diagnosis_category.parquet"
        ),
        "visit_procedure": (
            "bridges/visit_procedure/visit_year=*/"
            "visit_quarter=*/visit_procedure.parquet"
        ),
        "visit_elixhauser": (
            "bridges/visit_elixhauser/visit_year=*/"
            "visit_quarter=*/visit_elixhauser.parquet"
        ),
    }
    check(
        len(fact_paths) == EXPECTED_QUARTERS,
        "Fact partition count is not 76",
    )
    for name, pattern in bridge_patterns.items():
        check(
            len(list(OUTPUT_ROOT.glob(pattern))) == EXPECTED_QUARTERS,
            f"{name} partition count is not 76",
        )

    reference_schema = pq.read_schema(fact_paths[0])
    check(len(reference_schema) == 342, "Fact field count is not 342")
    total_rows = 0
    structural_null_pass = True
    for path in fact_paths:
        schema = pq.read_schema(path)
        check(
            reference_schema.equals(schema),
            f"Fact schema mismatch: {path}",
        )
        rows, null_counts = column_null_counts_from_metadata(
            path, STRUCTURAL_NULL_FIELDS
        )
        total_rows += rows
        structural_null_pass = structural_null_pass and all(
            null_counts[field] == rows
            for field in STRUCTURAL_NULL_FIELDS
        )
    manifest_rows = sum(
        int(item["output_fact_row_count"]) for item in manifests
    )
    check(total_rows == manifest_rows, "Fact rows do not match manifests")
    check(
        structural_null_pass,
        "At least one intentionally unavailable measure is nonnull",
    )

    qa_path = OUTPUT_ROOT / "qa" / "qa_summary.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    check(qa["all_required_checks_passed"], "Final QA hard gate failed")
    check(
        int(qa["fact_row_count"]) == total_rows,
        "Final QA fact count differs from reopened metadata",
    )
    cpt_enhancement = json.loads(
        (
            OUTPUT_ROOT
            / "qa"
            / "cpt_description_enhancement_summary.json"
        ).read_text(encoding="utf-8")
    )
    check(
        cpt_enhancement["quarter_files"] == EXPECTED_QUARTERS,
        "CPT description enhancement does not cover 76 quarters",
    )
    check(
        cpt_enhancement["all_row_reconciliations_passed"],
        "CPT description enhancement row reconciliation failed",
    )
    check(
        cpt_enhancement["mapped_after"]
        > cpt_enhancement["mapped_before"],
        "CPT public-use description supplement added no mappings",
    )

    physician_path = (
        OUTPUT_ROOT / "dimensions" / "physician_master.parquet"
    )
    facility_path = (
        OUTPUT_ROOT / "dimensions" / "facility_master.parquet"
    )
    physician_rows = pq.ParquetFile(physician_path).metadata.num_rows
    facility_rows = pq.ParquetFile(facility_path).metadata.num_rows
    check(
        physician_rows == int(qa["physician_master_row_count"]),
        "Physician master row count differs from final QA",
    )
    check(
        facility_rows == int(qa["facility_master_row_count"]),
        "Facility master row count differs from final QA",
    )
    check(
        qa["facility_master_one_row_per_ahca_id_passed"],
        "Facility master one-row-per-AHCA-ID gate failed",
    )

    workbook_path = (
        OUTPUT_ROOT
        / "documentation"
        / "Florida_ED_Standardization_Data_Dictionary.xlsx"
    )
    required_sheets = {
        "Overview",
        "Schema Crosswalk",
        "Value Harmonization",
        "Derived Variables",
        "Release Summary",
        "Fact Field Dictionary",
        "Table Inventory",
        "External Source Snapshots",
        "Analytical Table Schemas",
        "Final QA",
        "Annual Missingness",
        "Mapping Coverage",
        "Physician Linkage",
        "Enhancement Coverage",
        "Annual Summary",
        "Quarter Reconciliation",
    }
    sheet_names = set(workbook_sheet_names(workbook_path))
    check(
        required_sheets.issubset(sheet_names),
        "Final workbook is missing required sheets",
    )

    report_path = OUTPUT_ROOT / "report" / "report.html"
    report_text = report_path.read_text(encoding="utf-8")
    check(
        "Florida ED Standardization: Final Technical QA Report"
        in report_text,
        "Portable report title not found",
    )
    check(
        len(report_text) > 100_000,
        "Portable report is unexpectedly small",
    )
    check(
        "/api/manifest" not in report_text
        and "/api/snapshot" not in report_text,
        "Portable report retains runtime API dependencies",
    )

    notebook_path = (
        OUTPUT_ROOT
        / "notebooks"
        / "Florida_ED_Standardization_QA_and_Summaries.ipynb"
    )
    notebook = nbformat.read(notebook_path, as_version=4)
    code_cells = [
        cell for cell in notebook.cells if cell.cell_type == "code"
    ]
    check(bool(code_cells), "Notebook has no code cells")
    check(
        all(cell.execution_count is not None for cell in code_cells),
        "Notebook has unexecuted code cells",
    )
    check(
        not any(
            output.get("output_type") == "error"
            for cell in code_cells
            for output in cell.get("outputs", [])
        ),
        "Notebook contains execution errors",
    )

    fact_dictionary = pd.read_parquet(
        OUTPUT_ROOT
        / "documentation"
        / "fact_field_dictionary.parquet"
    )
    check(
        len(fact_dictionary) == 342,
        "Fact field dictionary does not contain 342 rows",
    )
    check(
        fact_dictionary["field_name"].is_unique,
        "Fact field dictionary contains duplicate field names",
    )

    result = {
        "validated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "quarter_manifest_count": len(success_paths),
        "fact_partition_count": len(fact_paths),
        "fact_row_count": total_rows,
        "fact_field_count": len(reference_schema),
        "structural_null_measure_check": structural_null_pass,
        "cpt_hcpcs_description_mapped_share_before": cpt_enhancement[
            "mapped_share_before"
        ],
        "cpt_hcpcs_description_mapped_share_after": cpt_enhancement[
            "mapped_share_after"
        ],
        "physician_master_row_count": physician_rows,
        "facility_master_row_count": facility_rows,
        "workbook_sheet_count": len(sheet_names),
        "portable_report_bytes": report_path.stat().st_size,
        "executed_notebook_code_cells": len(code_cells),
        "required_release_artifacts_passed": True,
    }
    destination = (
        OUTPUT_ROOT / "qa" / "independent_release_validation.json"
    )
    destination.write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
