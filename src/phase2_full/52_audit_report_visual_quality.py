#!/usr/bin/env python
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/52_audit_report_visual_quality.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Fail-closed full-page visual QA for the two staged Florida ED reports.

The script creates contact sheets and a page-level manual inspection ledger
when invoked with ``--initialize-ledger``. The final audit passes only after
every rendered page has a hash-matched, explicit manual PASS row and automated
render, edge, pagination, glyph, and page-count checks also pass.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageStat
from pypdf import PdfReader


LEDGER_FIELDS = [
    "report_id",
    "page_number",
    "page_image",
    "page_image_sha256",
    "inspected_by",
    "inspection_utc",
    "status",
    "clipped_text",
    "overlapping_elements",
    "broken_table",
    "unreadable_chart",
    "missing_glyph",
    "inconsistent_pagination",
    "notes",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8-sig",
        newline="",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(stream.name)
    os.replace(temporary, path)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    evidence: Any,
) -> None:
    checks.append(
        {
            "check_id": check_id,
            "passed": bool(passed),
            "severity": "ERROR",
            "evidence": evidence,
        }
    )


def report_id_from_record(record: dict[str, Any]) -> str:
    return Path(record["pdf"]).stem.replace("_DRAFT", "")


def page_number(path: Path) -> int:
    return int(path.stem.rsplit("-", 1)[-1])


def create_contact_sheets(
    records: list[dict[str, Any]],
    output_root: Path,
) -> list[dict[str, Any]]:
    output_root.mkdir(parents=True, exist_ok=True)
    sheets = []
    for record in records:
        report_id = report_id_from_record(record)
        pages = [Path(value) for value in record["page_images"]]
        for sheet_index in range(0, len(pages), 4):
            subset = pages[sheet_index : sheet_index + 4]
            thumbnails = []
            for page in subset:
                with Image.open(page) as image:
                    converted = image.convert("RGB")
                    converted.thumbnail((620, 800), Image.Resampling.LANCZOS)
                    thumbnails.append((page, converted.copy()))
            canvas = Image.new("RGB", (1320, 1780), "white")
            draw = ImageDraw.Draw(canvas)
            draw.text((35, 20), report_id, fill=(32, 55, 72))
            positions = [(35, 70), (680, 70), (35, 900), (680, 900)]
            for (page, image), (x, y) in zip(thumbnails, positions):
                draw.rectangle(
                    (x - 2, y - 2, x + image.width + 2, y + image.height + 2),
                    outline=(190, 196, 203),
                    width=2,
                )
                canvas.paste(image, (x, y))
                draw.text(
                    (x, y + image.height + 8),
                    f"Page {page_number(page)} | {sha256(page)[:12]}",
                    fill=(70, 80, 90),
                )
            output = (
                output_root
                / f"{report_id}_contact_{sheet_index // 4 + 1:02d}.png"
            )
            canvas.save(output, optimize=True)
            sheets.append(
                {
                    "report_id": report_id,
                    "contact_sheet": str(output),
                    "sha256": sha256(output),
                    "pages": [page_number(page) for page in subset],
                }
            )
    return sheets


def initialize_ledger(
    records: list[dict[str, Any]],
    ledger_path: Path,
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        report_id = report_id_from_record(record)
        for value in record["page_images"]:
            page = Path(value)
            rows.append(
                {
                    "report_id": report_id,
                    "page_number": page_number(page),
                    "page_image": str(page),
                    "page_image_sha256": sha256(page),
                    "inspected_by": "",
                    "inspection_utc": "",
                    "status": "PENDING",
                    "clipped_text": "",
                    "overlapping_elements": "",
                    "broken_table": "",
                    "unreadable_chart": "",
                    "missing_glyph": "",
                    "inconsistent_pagination": "",
                    "notes": "",
                }
            )
    atomic_csv(ledger_path, rows)
    return rows


def page_automated_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        gray = rgb.convert("L")
        stat = ImageStat.Stat(gray)
        mean_luminance = float(stat.mean[0])
        histogram = gray.histogram()
        dark_pixels = sum(histogram[:245])
        dark_fraction = dark_pixels / (width * height)
        border = max(3, int(min(width, height) * 0.004))
        edge_regions = [
            gray.crop((0, 0, width, border)),
            gray.crop((0, height - border, width, height)),
            gray.crop((0, 0, border, height)),
            gray.crop((width - border, 0, width, height)),
        ]
        edge_pixels = sum(region.width * region.height for region in edge_regions)
        edge_dark = 0
        for region in edge_regions:
            hist = region.histogram()
            edge_dark += sum(hist[:225])
        edge_dark_fraction = edge_dark / max(edge_pixels, 1)
        return {
            "path": str(path),
            "sha256": sha256(path),
            "width": width,
            "height": height,
            "mean_luminance": mean_luminance,
            "dark_fraction": dark_fraction,
            "edge_dark_fraction": edge_dark_fraction,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase2",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--initialize-ledger", action="store_true")
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    report_root = phase2 / "reports" / "report_production"
    staging = report_root / "staging"
    qa_root = report_root / "qa"
    build_path = staging / "Report_Document_Build_Manifest.json"
    content_path = qa_root / "Report_Content_Accuracy_Audit.json"
    safety_path = qa_root / "Report_Public_Safety_Audit.json"
    ledger_path = (
        report_root / "ledgers" / "Report_Visual_Page_Inspection.csv"
    )
    contact_root = staging / "visual_qa" / "contact_sheets"
    if not build_path.is_file():
        raise SystemExit(f"Staged report build manifest is missing: {build_path}")
    build = load_json(build_path)
    records = build.get("reports", [])
    if len(records) != 2:
        raise SystemExit("Staged build manifest must contain exactly two reports")
    sheets = create_contact_sheets(records, contact_root)
    contact_manifest = {
        "manifest_id": "florida_ed_report_visual_contact_sheets_v1",
        "created_utc": utc_now(),
        "build_manifest_sha256": sha256(build_path),
        "sheets": sheets,
    }
    atomic_json(
        staging / "visual_qa" / "Contact_Sheet_Manifest.json",
        contact_manifest,
    )
    if args.initialize_ledger:
        rows = initialize_ledger(records, ledger_path)
        print(
            json.dumps(
                {
                    "status": "PENDING_MANUAL_INSPECTION",
                    "pages": len(rows),
                    "contact_sheets": len(sheets),
                    "ledger": str(ledger_path),
                },
                indent=2,
            )
        )
        return
    required = [content_path, safety_path, ledger_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"Visual audit prerequisites are missing: {missing}")
    content = load_json(content_path)
    safety = load_json(safety_path)
    ledger = read_csv(ledger_path)
    checks: list[dict[str, Any]] = []
    add_check(
        checks,
        "content_and_public_safety_audits_pass",
        content.get("status") == "PASS" and safety.get("status") == "PASS",
        {
            "content_status": content.get("status"),
            "content_sha256": sha256(content_path),
            "public_safety_status": safety.get("status"),
            "public_safety_sha256": sha256(safety_path),
        },
    )
    expected_pages = []
    for record in records:
        report_id = report_id_from_record(record)
        for value in record["page_images"]:
            path = Path(value)
            expected_pages.append(
                {
                    "report_id": report_id,
                    "page_number": page_number(path),
                    "path": path,
                    "sha256": sha256(path) if path.is_file() else None,
                }
            )
    ledger_index = {
        (row["report_id"], int(row["page_number"])): row for row in ledger
    }
    manual_failures = []
    for expected in expected_pages:
        key = (expected["report_id"], expected["page_number"])
        row = ledger_index.get(key)
        if (
            row is None
            or row.get("page_image_sha256") != expected["sha256"]
            or not row.get("inspected_by", "").strip()
            or not row.get("inspection_utc", "").strip()
            or row.get("status") != "PASS"
            or any(
                row.get(field, "").strip().lower() not in {"false", "no", "0"}
                for field in (
                    "clipped_text",
                    "overlapping_elements",
                    "broken_table",
                    "unreadable_chart",
                    "missing_glyph",
                    "inconsistent_pagination",
                )
            )
        ):
            manual_failures.append({"expected": expected, "ledger_row": row})
    unexpected_ledger = sorted(
        set(ledger_index)
        - {
            (row["report_id"], row["page_number"]) for row in expected_pages
        }
    )
    add_check(
        checks,
        "every_rendered_page_has_hash_matched_manual_pass",
        len(ledger) == len(expected_pages)
        and not manual_failures
        and not unexpected_ledger,
        {
            "expected_pages": len(expected_pages),
            "ledger_rows": len(ledger),
            "failures": manual_failures,
            "unexpected_rows": unexpected_ledger,
        },
    )
    metrics = [
        page_automated_metrics(row["path"]) for row in expected_pages
    ]
    dimension_failures = [
        row
        for row in metrics
        if row["width"] < 1000 or row["height"] < 1000
    ]
    add_check(
        checks,
        "page_renders_have_review_resolution",
        not dimension_failures,
        {
            "pages": len(metrics),
            "dimension_failures": dimension_failures,
        },
    )
    blank_failures = [
        row
        for row in metrics
        if row["dark_fraction"] < 0.001 or row["mean_luminance"] > 254.5
    ]
    add_check(
        checks,
        "no_unexpected_blank_pages",
        not blank_failures,
        blank_failures,
    )
    edge_failures = [
        row for row in metrics if row["edge_dark_fraction"] > 0.004
    ]
    add_check(
        checks,
        "no_automated_edge_clipping_signal",
        not edge_failures,
        edge_failures,
    )
    pagination_failures = []
    glyph_failures = []
    page_count_failures = []
    for record in records:
        pdf = Path(record["pdf"])
        reader = PdfReader(pdf)
        page_count = len(reader.pages)
        if page_count != int(record["page_count"]):
            page_count_failures.append(
                {
                    "pdf": str(pdf),
                    "manifest": record["page_count"],
                    "observed": page_count,
                }
            )
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if "\ufffd" in text or "\u25a1" in text:
                glyph_failures.append(
                    {"pdf": str(pdf), "page": index}
                )
            if index > 1 and f"Page {index} of {page_count}" not in text:
                pagination_failures.append(
                    {
                        "pdf": str(pdf),
                        "page": index,
                        "expected": f"Page {index} of {page_count}",
                    }
                )
    add_check(
        checks,
        "pdf_page_counts_match_render_manifests",
        not page_count_failures,
        page_count_failures,
    )
    add_check(
        checks,
        "page_numbering_is_consistent",
        not pagination_failures,
        pagination_failures,
    )
    add_check(
        checks,
        "no_missing_glyph_markers_in_pdf_text",
        not glyph_failures,
        glyph_failures,
    )
    duplicate_page_hashes = {}
    for row in expected_pages:
        duplicate_page_hashes.setdefault(row["sha256"], []).append(
            (row["report_id"], row["page_number"])
        )
    suspicious_duplicates = {
        digest: pages
        for digest, pages in duplicate_page_hashes.items()
        if len(pages) > 1
    }
    add_check(
        checks,
        "no_duplicate_rendered_pages",
        not suspicious_duplicates,
        suspicious_duplicates,
    )
    status = "PASS" if all(row["passed"] for row in checks) else "FAIL"
    audit = {
        "audit_id": "florida_ed_report_visual_quality_audit_v1",
        "created_utc": utc_now(),
        "status": status,
        "scope": (
            "Every staged PDF page: hash-matched manual inspection plus "
            "automated render-resolution, blank-page, edge-clipping, "
            "pagination, glyph, duplicate-page, and page-count checks."
        ),
        "checks_passed": sum(row["passed"] for row in checks),
        "checks_total": len(checks),
        "checks": checks,
        "pages_inspected": len(expected_pages),
        "contact_sheet_manifest_sha256": sha256(
            staging / "visual_qa" / "Contact_Sheet_Manifest.json"
        ),
        "manual_inspection_ledger_sha256": sha256(ledger_path),
        "content_audit_sha256": sha256(content_path),
        "public_safety_audit_sha256": sha256(safety_path),
        "build_manifest_sha256": sha256(build_path),
    }
    atomic_json(qa_root / "Report_Visual_Quality_Audit.json", audit)
    print(
        json.dumps(
            {
                "status": status,
                "checks": f"{audit['checks_passed']}/{audit['checks_total']}",
                "pages_inspected": audit["pages_inspected"],
            },
            indent=2,
        )
    )
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
