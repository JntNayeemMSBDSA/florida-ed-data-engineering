#!/usr/bin/env python
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/49c_materialize_audited_report_sources.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Materialize the two audited Florida ED report sources.

This program is deliberately downstream of the complete analytical release
audit. It performs no estimation and fails closed unless every analytical gate
has passed. It reads only validated aggregate/structural artifacts, applies
pre-declared reporting rules, creates public-safe figures, and binds every
reported number to a source and validation hash.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


PRIMARY_OUTCOMES = {
    "los_hours_primary_0_168": ("ED length of stay", "hours", 1.0),
    "total_charge_reported_real_2024": (
        "reported facility charges",
        "2024 dollars",
        1.0,
    ),
}
RESULT_CLAIMS = {
    "primary": "F-PRIMARY-001",
    "gender_dyads": "F-DYAD-GENDER-001",
    "race_dyads": "F-DYAD-RACE-001",
    "intersectional_dyads": "F-DYAD-INTERSECTIONAL-001",
    "historical_race": "F-HIST-RACE-001",
    "historical_gender": "F-HIST-GENDER-001",
    "ami": "F-AMI-001",
    "sensitivity": "F-SENS-001",
    "conclusion": "F-CONCLUSION-001",
}
TECHNICAL_NAME = "Florida_ED_Technical_Project_Dossier"
COLLABORATOR_NAME = "Florida_ED_Collaborator_Project_Report"
BLUE = "#2E74B5"
NAVY = "#203748"
TEAL = "#2A7F7F"
GOLD = "#B18422"
RED = "#B85450"
LIGHT = "#F3F6F8"
MID = "#D7E2EA"
DARK = "#263442"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON root is not an object: {path}")
    return value


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as stream:
        stream.write(text)
        temporary = Path(stream.name)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def rel(path: Path, workspace: Path) -> str:
    return path.resolve().relative_to(workspace.resolve()).as_posix()


def short_sha(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text[:16] if text else "not separately hashed"


def human_bytes(value: Any) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:,.1f} {unit}"
        amount /= 1024
    return f"{amount:,.1f} TB"


def require(path: Path) -> Path:
    if not path.is_file():
        raise SystemExit(f"Required audited artifact is missing: {path}")
    return path


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def fnum(value: Any, digits: int = 2) -> str:
    if not finite(value):
        return "not estimable"
    number = float(value)
    if abs(number) >= 1000:
        return f"{number:,.{digits}f}"
    return f"{number:.{digits}f}"


def fp(value: Any) -> str:
    if not finite(value):
        return "not estimable"
    number = float(value)
    if number < 0.001:
        return "<0.001"
    return f"{number:.3f}"


def fint(value: Any) -> str:
    if not finite(value):
        return "not available"
    return f"{int(round(float(value))):,}"


def md_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value).replace("|", "/").replace("\n", " ").strip()

    output = [
        "| " + " | ".join(clean(value) for value in headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    output.extend(
        "| " + " | ".join(clean(value) for value in row) + " |"
        for row in rows
    )
    return "\n".join(output)


def read_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def box_diagram(
    path: Path,
    title: str,
    boxes: list[tuple[str, str]],
    footer: str,
) -> None:
    width = 1500
    margin = 70
    gap = 28
    box_width = int((width - 2 * margin - gap * (len(boxes) - 1)) / len(boxes))
    height = 520
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = read_font(34, True)
    head_font = read_font(23, True)
    body_font = read_font(20)
    foot_font = read_font(17)
    draw.text((margin, 38), title, fill=NAVY, font=title_font)
    y0, y1 = 130, 405
    colors = [BLUE, TEAL, GOLD, NAVY, RED]
    for index, (head, body) in enumerate(boxes):
        x0 = margin + index * (box_width + gap)
        x1 = x0 + box_width
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=18,
            fill=LIGHT,
            outline=colors[index % len(colors)],
            width=4,
        )
        draw.rectangle(
            (x0, y0, x1, y0 + 58),
            fill=colors[index % len(colors)],
        )
        draw.text((x0 + 18, y0 + 15), head, fill="white", font=head_font)
        y = y0 + 83
        for line in wrap(draw, body, body_font, box_width - 36):
            draw.text((x0 + 18, y), line, fill=DARK, font=body_font)
            y += 28
        if index < len(boxes) - 1:
            ax = x1 + 7
            ay = int((y0 + y1) / 2)
            draw.line((ax, ay, ax + gap - 14, ay), fill=MID, width=7)
            draw.polygon(
                [(ax + gap - 14, ay - 10), (ax + gap, ay), (ax + gap - 14, ay + 10)],
                fill=MID,
            )
    draw.text((margin, 452), footer, fill="#5C6872", font=foot_font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def timeline_figure(path: Path) -> None:
    width, height = 1500, 470
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = read_font(34, True)
    label_font = read_font(22, True)
    body_font = read_font(18)
    draw.text((70, 35), "Florida ED analytical periods", fill=NAVY, font=title_font)
    x0, x1, y = 90, 1410, 235
    draw.line((x0, y, x1, y), fill=MID, width=12)
    years = list(range(2005, 2026))
    step = (x1 - x0) / (len(years) - 1)
    for index, year in enumerate(years):
        x = x0 + index * step
        if 2005 <= year <= 2008:
            color = GOLD
        elif 2010 <= year <= 2024:
            color = BLUE
        else:
            color = "#B8C1C8"
        draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=color)
        if year in {2005, 2008, 2009, 2010, 2015, 2020, 2024, 2025}:
            draw.text((x - 24, y + 30), str(year), fill=DARK, font=body_font)
    draw.rounded_rectangle((95, 115, 330, 180), radius=12, fill="#FFF6DE", outline=GOLD, width=3)
    draw.text((115, 133), "Historical: 2005–2008", fill=DARK, font=label_font)
    draw.rounded_rectangle((510, 115, 950, 180), radius=12, fill="#EAF2F8", outline=BLUE, width=3)
    draw.text((530, 133), "Primary: 2010–2024", fill=DARK, font=label_font)
    draw.text(
        (1020, 125),
        "2009 and 2025 absent;\nno imputation",
        fill="#5C6872",
        font=body_font,
    )
    draw.text(
        (90, 365),
        "Historical and primary periods are analyzed separately because field availability and coding systems differ.",
        fill="#5C6872",
        font=body_font,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def forest_figure(path: Path, rows: pd.DataFrame) -> None:
    width = 1500
    row_height = 120
    height = 210 + max(len(rows), 1) * row_height
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = read_font(34, True)
    body_font = read_font(20)
    small_font = read_font(17)
    draw.text((65, 35), "Primary adjusted race-concordance contrasts", fill=NAVY, font=title_font)
    values: list[float] = []
    for _, row in rows.iterrows():
        for column in ("ci95_low", "ci95_high"):
            if finite(row.get(column)):
                values.append(float(row[column]))
    maximum = max([abs(value) for value in values] + [1.0])
    left, right = 630, 1390
    zero = (left + right) / 2
    scale = (right - left) / (2 * maximum * 1.15)
    draw.line((zero, 120, zero, height - 70), fill="#7A8791", width=3)
    if rows.empty:
        draw.text((65, 150), "No estimable primary contrast.", fill=RED, font=body_font)
    for index, (_, row) in enumerate(rows.iterrows()):
        y = 165 + index * row_height
        outcome = PRIMARY_OUTCOMES.get(str(row.get("outcome")), (str(row.get("outcome")), "", 1.0))[0]
        estimate = float(row["estimate"])
        low = float(row["ci95_low"])
        high = float(row["ci95_high"])
        draw.text((65, y - 20), outcome, fill=DARK, font=body_font)
        draw.text(
            (65, y + 18),
            f"{fnum(estimate)} [{fnum(low)}, {fnum(high)}]",
            fill="#5C6872",
            font=small_font,
        )
        x_est = zero + estimate * scale
        x_low = zero + low * scale
        x_high = zero + high * scale
        draw.line((x_low, y, x_high, y), fill=BLUE, width=7)
        draw.line((x_low, y - 11, x_low, y + 11), fill=BLUE, width=4)
        draw.line((x_high, y - 11, x_high, y + 11), fill=BLUE, width=4)
        draw.ellipse((x_est - 10, y - 10, x_est + 10, y + 10), fill=NAVY)
    draw.text(
        (65, height - 48),
        "Points are adjusted associations; bars are 95% confidence intervals. Scales are outcome-specific in the table.",
        fill="#5C6872",
        font=small_font,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def directional_figure(path: Path, summary: pd.DataFrame) -> None:
    width, height = 1500, 560
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = read_font(34, True)
    head_font = read_font(22, True)
    body_font = read_font(20)
    draw.text((65, 35), "Directional analysis: estimability and multiplicity", fill=NAVY, font=title_font)
    columns = ["Family", "Rows", "Estimable", "Limited support", "BH q < 0.05"]
    x = [70, 530, 760, 995, 1245]
    y0 = 125
    for position, label in zip(x, columns):
        draw.text((position, y0), label, fill="white", font=head_font)
    draw.rectangle((55, y0 - 18, 1445, y0 + 48), fill=BLUE)
    family_labels = {
        "gender_dyads": "Gender dyads",
        "race_dyads": "Race dyads",
        "intersectional_dyads": "Intersectional dyads",
    }
    for index, (_, row) in enumerate(summary.iterrows()):
        y = y0 + 88 + index * 92
        if index % 2 == 0:
            draw.rectangle((55, y - 20, 1445, y + 50), fill=LIGHT)
        values = [
            family_labels.get(str(row["family_id"]), str(row["family_id"])),
            fint(row["rows"]),
            fint(row["estimable"]),
            fint(row["limited_support"]),
            fint(row["q_lt_0_05"]),
        ]
        for position, value in zip(x, values):
            draw.text((position, y), value, fill=DARK, font=body_font)
    draw.text(
        (65, 485),
        "Counts summarize the complete audited contrast table; sparse cells remain explicit and are never silently merged.",
        fill="#5C6872",
        font=body_font,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def primary_rows(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "testing_family",
        "outcome",
        "cohort",
        "model_id",
        "analysis_sample_policy",
        "estimate",
        "ci95_low",
        "ci95_high",
        "p_value",
        "adjusted_p_value",
        "n",
    }
    missing = required - set(frame.columns)
    if missing:
        raise SystemExit(f"Primary inference columns missing: {sorted(missing)}")
    selected = frame.loc[
        (frame["testing_family"] == "confirmatory_race_primary")
        & (frame["cohort"] == "race")
        & (
            frame["model_id"]
            == "m2_fully_adjusted_facility_yq_clinical_fe"
        )
        & frame["outcome"].isin(PRIMARY_OUTCOMES)
    ].copy()
    if (
        len(selected) != 2
        or set(selected["outcome"]) != set(PRIMARY_OUTCOMES)
        or set(selected["analysis_sample_policy"])
        != {"los_outcome", "charge_outcome"}
    ):
        raise SystemExit("Confirmatory primary reporting set is not exactly frozen")
    return selected.sort_values("outcome")


def directional_summary(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "family_id",
        "estimability_status",
        "limited_support_flag",
        "q_value_bh",
    }
    missing = required - set(frame.columns)
    if missing:
        raise SystemExit(f"Directional result columns missing: {sorted(missing)}")
    result = []
    for family in ("gender_dyads", "race_dyads", "intersectional_dyads"):
        subset = frame.loc[frame["family_id"] == family]
        status = subset["estimability_status"].astype(str)
        estimable = ~status.str.startswith("NON_ESTIMABLE")
        limited = subset["limited_support_flag"].astype(str).str.lower().isin(
            {"true", "1", "yes"}
        )
        q = pd.to_numeric(subset["q_value_bh"], errors="coerce")
        result.append(
            {
                "family_id": family,
                "rows": len(subset),
                "estimable": int(estimable.sum()),
                "limited_support": int(limited.sum()),
                "q_lt_0_05": int((q < 0.05).sum()),
            }
        )
    return pd.DataFrame(result)


def report_estimate_table(rows: pd.DataFrame, q_column: str) -> str:
    rendered = []
    include_contrast = "contrast_id" in rows.columns
    for _, row in rows.iterrows():
        name, unit, scale = PRIMARY_OUTCOMES.get(
            str(row.get("outcome")),
            (str(row.get("outcome")), "outcome units", 1.0),
        )
        result_row = [
            name,
            f"{fnum(float(row['estimate']) * scale)} {unit}",
            (
                f"{fnum(float(row['ci95_low']) * scale)} to "
                f"{fnum(float(row['ci95_high']) * scale)}"
            ),
            fp(row.get("p_value", row.get("p_value_raw"))),
            fp(row.get(q_column)),
            fint(row.get("n")),
        ]
        if include_contrast:
            result_row.insert(
                0,
                str(row.get("direction", row.get("contrast_id", "")))
                or str(row.get("contrast_id", "")),
            )
        rendered.append(result_row)
    headers = [
        "Outcome",
        "Adjusted contrast",
        "95% CI",
        "Raw p",
        "Adjusted q",
        "Visits",
    ]
    if include_contrast:
        headers.insert(0, "Directional contrast")
    return md_table(
        headers,
        rendered,
    )


def compact_audited_result_table(
    rows: pd.DataFrame,
    descriptor_columns: list[str],
    q_column: str = "adjusted_p_value",
) -> str:
    rendered = []
    for _, row in rows.iterrows():
        descriptor = " | ".join(
            str(row.get(column, "")).replace("_", " ")
            for column in descriptor_columns
        )
        status = str(row.get("inferential_status", "ESTIMABLE"))
        estimate = pd.to_numeric(
            pd.Series([row.get("estimate")]), errors="coerce"
        ).iloc[0]
        low = pd.to_numeric(
            pd.Series([row.get("ci95_low")]), errors="coerce"
        ).iloc[0]
        high = pd.to_numeric(
            pd.Series([row.get("ci95_high")]), errors="coerce"
        ).iloc[0]
        if status.upper().startswith("NON_ESTIMABLE") or not finite(estimate):
            reason = str(row.get("non_estimable_reason", "")).strip()
            result = "Non-estimable" + (f": {reason}" if reason else "")
            interval = "—"
        else:
            result = fnum(estimate)
            interval = f"[{fnum(low)}, {fnum(high)}]"
        rendered.append(
            [
                descriptor,
                result,
                interval,
                fnum(row.get("p_value"), 4),
                fnum(row.get(q_column), 4),
                fint(row.get("n")),
            ]
        )
    return md_table(
        ["Specification / outcome", "Estimate", "95% CI", "Raw p", "Adjusted q", "Visits"],
        rendered,
    )


def result_family_summary(
    labeled_frames: list[tuple[str, pd.DataFrame]],
    q_column: str = "adjusted_p_value",
) -> pd.DataFrame:
    records = []
    for label, frame in labeled_frames:
        estimate = pd.to_numeric(frame.get("estimate"), errors="coerce")
        low = pd.to_numeric(frame.get("ci95_low"), errors="coerce")
        high = pd.to_numeric(frame.get("ci95_high"), errors="coerce")
        if "inferential_status" in frame:
            explicit_nonestimable = (
                frame["inferential_status"]
                .astype(str)
                .str.upper()
                .str.startswith("NON_ESTIMABLE")
            )
        else:
            explicit_nonestimable = pd.Series(
                False, index=frame.index, dtype=bool
            )
        estimable = estimate.notna() & ~explicit_nonestimable
        q = pd.to_numeric(frame.get(q_column), errors="coerce")
        excludes_zero = (
            estimable
            & low.notna()
            & high.notna()
            & ((low > 0) | (high < 0))
        )
        records.append(
            {
                "family": label,
                "rows": len(frame),
                "estimable": int(estimable.sum()),
                "non_estimable": int((~estimable).sum()),
                "positive": int((estimable & (estimate > 0)).sum()),
                "negative": int((estimable & (estimate < 0)).sum()),
                "ci_excludes_zero": int(excludes_zero.sum()),
                "adjusted_q_lt_0_05": int((estimable & (q < 0.05)).sum()),
            }
        )
    return pd.DataFrame(records)


def family_summary_table(summary: pd.DataFrame) -> str:
    return md_table(
        [
            "Audited family",
            "Rows",
            "Estimable",
            "Non-estimable",
            "Positive",
            "Negative",
            "95% CI excludes 0",
            "Adjusted q < 0.05",
        ],
        [
            [
                row.family,
                fint(row.rows),
                fint(row.estimable),
                fint(row.non_estimable),
                fint(row.positive),
                fint(row.negative),
                fint(row.ci_excludes_zero),
                fint(row.adjusted_q_lt_0_05),
            ]
            for row in summary.itertuples()
        ],
    )


def gate_and_sources(phase2: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report_root = phase2 / "reports" / "report_production"
    complete_path = require(phase2 / "qa" / "complete_analysis_release_audit.json")
    complete = load_json(complete_path)
    if (
        complete.get("status") != "PASS"
        or complete.get("result_interpretation_performed") is not False
    ):
        raise SystemExit("Complete analytical release audit is not a valid PASS")
    framework = phase2 / "scripts" / "36_initialize_report_production_framework.py"
    subprocess.run([sys.executable, str(framework)], check=True)
    gate = load_json(
        require(report_root / "qa" / "Report_Finalization_Gate.json")
    )
    if (
        gate.get("findings_insertion_authorized") is not True
        or gate.get("draft_document_and_pdf_build_authorized") is not True
        or gate.get("analytical_gates_passed")
        != gate.get("analytical_gates_total")
    ):
        raise SystemExit("Analytical report-materialization gate is closed")
    return complete, gate


def add_number(
    rows: list[dict[str, Any]],
    workspace: Path,
    complete_audit: Path,
    number_id: str,
    report: str,
    section: str,
    claim_id: str,
    value: Any,
    unit: str,
    derivation: str,
    source: Path,
) -> None:
    rows.append(
        {
            "number_id": number_id,
            "report": report,
            "section": section,
            "claim_id": claim_id,
            "reported_value": str(value),
            "unit": unit,
            "derivation": derivation,
            "source_artifact": rel(source, workspace),
            "source_sha256": sha256(source),
            "validation_artifact": rel(complete_audit, workspace),
            "validation_sha256": sha256(complete_audit),
            "reconciled": "YES",
        }
    )


def issue_table(issue_rows: list[dict[str, str]]) -> str:
    values = []
    for row in issue_rows:
        values.append(
            [
                f"{row['chronology_date_utc'][:10]} / {row['issue_id']}",
                row["issue_title"],
                f"{row['correction']} Prevention: {row['recurrence_prevention']}",
            ]
        )
    return md_table(
        ["Date / ID", "Issue", "Resolution and prevention"],
        values,
    )


def issue_narrative(issue_rows: list[dict[str, str]]) -> str:
    blocks = []
    for row in issue_rows:
        blocks.append(
            "\n".join(
                [
                    f"### {row['issue_id']}. {row['issue_title']}",
                    "",
                    f"**What happened:** {row['what_happened']}",
                    "",
                    f"**Detection:** {row['detection']}",
                    "",
                    (
                        "**Potentially affected artifacts:** "
                        f"{row['potentially_affected_artifacts']}"
                    ),
                    "",
                    (
                        "**Scientific or computational importance:** "
                        f"{row['scientific_or_computational_importance']}"
                    ),
                    "",
                    f"**Correction:** {row['correction']}",
                    "",
                    f"**Rebuilt or rerun:** {row['rebuilt_or_rerun']}",
                    "",
                    f"**Preserved artifacts:** {row['preserved_artifacts']}",
                    "",
                    (
                        "**Recurrence prevention:** "
                        f"{row['recurrence_prevention']}"
                    ),
                    "",
                    (
                        "**Validation evidence:** "
                        f"{row['validation_evidence_candidates']}"
                    ),
                ]
            )
        )
    return "\n\n".join(blocks)


def build_technical(
    assets: dict[str, str],
    phase1_rows: int,
    phase1_quarters: int,
    primary_rows_count: int,
    primary_partitions: int,
    historical_rows: int,
    provider: dict[str, Any],
    race: dict[str, Any],
    cohort: dict[str, Any],
    primary: pd.DataFrame,
    directional: pd.DataFrame,
    direction_summary: pd.DataFrame,
    historical_race: pd.DataFrame,
    historical_gender: pd.DataFrame,
    historical_ami: pd.DataFrame,
    primary_ami: pd.DataFrame,
    issues: list[dict[str, str]],
    audit_count: int,
    source_version_table: str,
    cohort_eligibility_table: str,
    provider_coverage_table: str,
    model_grid_table: str,
    environment_table: str,
    execution_table: str,
    artifact_hash_table: str,
) -> str:
    primary_table = report_estimate_table(primary, "adjusted_p_value")
    directional_primary = directional.loc[
        directional["outcome"].isin(PRIMARY_OUTCOMES)
        & (directional["model_id"] == "M2_DIRECTIONAL")
    ].copy()
    gender_primary = directional_primary.loc[
        directional_primary["family_id"] == "gender_dyads"
    ].sort_values(["outcome", "contrast_id"])
    race_primary = directional_primary.loc[
        (directional_primary["family_id"] == "race_dyads")
        & directional_primary["contrast_id"].astype(str).str.startswith(
            "race_interaction_did_"
        )
    ].sort_values(["outcome", "contrast_id"])
    summary_table = md_table(
        ["Family", "Contrasts", "Estimable", "Limited support", "BH q < 0.05"],
        [
            [
                row.family_id.replace("_", " ").title(),
                fint(row.rows),
                fint(row.estimable),
                fint(row.limited_support),
                fint(row.q_lt_0_05),
            ]
            for row in direction_summary.itertuples()
        ],
    )
    ami_status = (
        primary_ami.get("inferential_status", pd.Series(dtype=str))
        .astype(str)
        .value_counts()
        .to_dict()
    )
    historical_status = (
        historical_ami.get("inferential_status", pd.Series(dtype=str))
        .astype(str)
        .value_counts()
        .to_dict()
    )
    technical = f"""# Florida Emergency Department Project
## Technical Project and Reproducibility Dossier

**Document state:** Audited analytical dossier  
**Version:** 1.0  
**Prepared for:** Nayeem and the Florida ED research team  
**Analysis periods:** Primary 2010–2024; historical 2005–2008  
**Interpretation rule:** All estimates are observational associations. Nothing in this dossier establishes causation.  
**Authorship statement:** Research questions and substantive decisions are attributable to the research team. Pipeline construction, validation, computation, and draft documentation include automated assistance and require investigator review before circulation.

## Table of Contents

## Technical Summary

<!-- SOURCE: T-P1-001 -->
The immutable source release contains {phase1_quarters:,} validated quarterly partitions and {phase1_rows:,} unique ED encounters. Provider master v2 corrected physician coverage and measurement without changing those source encounters. The refreshed primary cohort contains {primary_partitions:,} quarters and {primary_rows_count:,} visits; the separate historical cohort contains 16 quarters and {historical_rows:,} visits.

<!-- SOURCE: F-PRIMARY-001 -->
The confirmatory family is exactly the two outcome-specific, fully adjusted race-concordance contrasts shown in Table 1. Estimates are presented in their natural units with two-way physician/facility clustered uncertainty and Holm adjustment. Directional gender and race analyses are secondary; the expanded intersectional family is exploratory. The complete machine-readable results retain every estimability and support flag.

Table 1. Confirmatory primary adjusted race-concordance associations.

{primary_table}

![Primary adjusted estimates and 95% confidence intervals]({assets["forest"]})

## 1. Research Objective and Development History

The project asks whether measured ED treatment, utilization, charge, disposition, and length-of-stay outcomes differ across patient–physician race and recorded sex/gender combinations. It also preserves a separate ED-only acute myocardial infarction analysis inspired by, but not equivalent to, the inpatient Greenwood design.

The initial 0.5% sample established a practical decoding and provider-linkage workflow. It used sample-era hard surname race labels and a partial variable set. The complete build replaced that workflow with five-schema standardization, all available quarters, validated dimensions and bridges, and a full-name probabilistic physician-race measurement model. The sample is documentary history, not an analytical input.

Later additions are labeled honestly. Provider v2 is a measurement and coverage correction. Directional gender and race dyads are secondary, the expanded intersectional grid is exploratory, and the historical period is a separate sensitivity/replication cohort. No later extension is retroactively called originally prespecified.

## 2. Data Sources and Provenance

<!-- SOURCE: T-P1-002 -->
The available ED data cover 2005–2008 and 2010–2024. The 2009 and 2025 files were not available and were not imputed. The primary period is 2010–2024; the 2005–2008 data are checkpointed separately because field availability and coding systems differ.

![Included analytical periods and excluded years]({assets["timeline"]})

Phase 1 is a quarter-partitioned release with one fact row per encounter and separate diagnosis, procedure, physician, and facility structures. Its manifests bind each source, output, schema version, row count, checksum, and dictionary. External measurement sources include NPPES, CMS Doctors and Clinicians, CMS facility affiliations, Florida licensure sources, official wru name dictionaries, the AAMC Florida physician distribution used as the primary prior, SSA name data for gender sensitivity only, clinical groupers, and inflation indices.

![Source-to-release provenance chain]({assets["lineage"]})

Restricted encounter data, provider-level details, and facility-level details remain controlled research data. Public dissemination is limited to disclosure-reviewed aggregate outputs and public methods/code that do not reveal local paths, identifiers, or sensitive small cells.

Appendix C provides the source/version ledger, checksum state, role, and limitation for every major analytical source family. Current web documentation was used only to verify citations and source-system roles; it never replaced the locally manifest-bound version used by the analysis.

## 3. Complete Data-Engineering Process

<!-- SOURCE: T-P1-001 -->
Phase 1 reconciles {phase1_rows:,} unique encounters across {phase1_quarters:,} quarters. A stable internal visit key supports safe joins. The five historical schemas are standardized to consistent names and definitions; structural missingness is preserved rather than converted into artificial values.

Diagnosis and procedure processing covers ICD-9-CM, ICD-10-CM, CPT/HCPCS, CCS/CCSR, Elixhauser indicators, transition-quarter logic, mapping versions, and unmapped-code QA. Visit enhancements distinguish source-reported disposition and charges from derived inflation-adjusted charges, procedure counts, treatment-intensity measures, and revisit indicators where identifiers permit. Reported charges are not costs, payments, or reimbursements.

<!-- SOURCE: T-PV2-001 -->
Provider master v2 contains one row per NPI ({provider["master_rows"]:,} rows) and covers all {provider["ed_observed_distinct_npis"]:,} checksum-valid ED-observed selected NPIs. It distinguishes individual and organizational NPIs, clinician type, linkage pathway, role, and source timing. Among ED-observed NPIs, {provider["ed_observed_md_do_npis"]:,} are MD/DO physicians; organizational NPIs are never classified as physicians. Current CMS clinician data match {provider["ed_observed_npis_matched_current_cms"]:,} ED-observed NPIs, and current CMS facility affiliations cover {provider["ed_observed_npis_with_current_cms_facility_affiliation"]:,}.

![Encounter, facility, and clinician linkage architecture]({assets["provider"]})

<!-- SOURCE: T-PV2-003 -->
The pre-v2 Phase 2 builder had used Phase 1 provider linkage as an inclusion rule. Therefore, refreshing attributes alone would not restore excluded encounters. All 60 primary provider-v2 partitions were rebuilt from immutable Phase 1 facts and reconciled independently. The old partitions remain preserved but superseded.

Table 2. Core release reconciliation.

{md_table(
    ["Release component", "Partitions", "Rows", "Role"],
    [
        ["Immutable Phase 1 facts", f"{phase1_quarters:,}", f"{phase1_rows:,}", "Source release"],
        ["Provider-v2 primary cohort", f"{primary_partitions:,}", f"{primary_rows_count:,}", "Primary 2010–2024"],
        ["Provider-v2 historical cohort", "16", f"{historical_rows:,}", "Separate 2005–2008"],
    ],
)}

The following provider and cohort summaries are not sequential attrition unless explicitly labeled. Eligibility flags overlap because they describe different measurements and outcomes.

**Provider master v2 coverage summary**

{provider_coverage_table}

**Primary cohort eligibility and outcome-availability summary**

{cohort_eligibility_table}

## 4. Race and Sex/Gender Measurement

Patient race/ethnicity and sex are administrative encounter fields. They do not fully measure identity. The analytical recode preserves unknown values and applies the documented combined race/ethnicity hierarchy consistently within compatible schema periods.

<!-- SOURCE: T-GENDER-001 -->
Primary physician gender uses recorded NPPES/CMS binary categories. SSA name-based inference at a 90% confidence rule is sensitivity-only. Conflicts and unknowns remain explicit; these fields are not described as gender identity.

<!-- SOURCE: T-RACE-001 -->
Physician race is algorithm-inferred and probabilistic. The exact primary method is `{race["primary_method_id"]}` using official wru v2.0.0 surname, first-name, and available middle-name likelihoods with an AAMC Florida physician prior. For each clinician, posterior probabilities are proportional to the prior multiplied by the available name likelihoods and normalized across five classes. The primary approach uses no residential geography, is not BISG, and is not self-reported identity.

<!-- SOURCE: T-RACE-002 -->
The earlier “Harvard” first-name likelihood table matches the official wru first-name likelihood dictionary within floating-point tolerance. The earlier posterior table is a different conditional object and cannot be substituted for a likelihood table. The record does not establish Harvard authorship, so the final documentation uses descriptive filenames and verified provenance.

<!-- SOURCE: T-RACE-003 -->
Among {race["ed_observed_md_do_npis"]:,} ED-observed MD/DO NPIs, {race["ed_observed_md_do_last_first_matched_npis"]:,} have surname-plus-first-name coverage, {race["ed_observed_md_do_eligible_t50_npis"]:,} meet the 0.50 confidence rule, and {race["ed_observed_md_do_eligible_t70_npis"]:,} meet the 0.70 rule. Primary probability weighting is complemented by national-prior, threshold, and 20-draw NPI-level multiple-imputation analyses.

![Physician race and gender measurement with sensitivity paths]({assets["measurement"]})

Limitations remain: name coverage and calibration may differ across groups; the provider sources are contemporary snapshots applied to historical encounters; the categorical model does not represent all identities; and algorithmic agreement cannot validate a clinician’s identity.

## 5. Statistical Design

The primary race estimand is a difference-in-differences interaction on each outcome’s natural scale. Model 1 adjusts for patient and visit characteristics. Model 2 additionally absorbs facility-year-quarter and clinical-category fixed effects and adds measured physician/facility covariates. Model 3 adds physician fixed effects when the contrast is identified within physician. Inference uses two-way physician and facility CRV1 clustering; frozen sensitivity modules cover outcome-appropriate forms, wild-score bootstrap checks, exact subsets, alternative cohort definitions, payer heterogeneity, and influential-facility refits.

The two confirmatory race outcomes are outcome-specific ED length of stay and real reported total charges. Holm correction is applied across exactly those two M2 contrasts. Secondary and exploratory families use BH false-discovery-rate adjustment within frozen families. Raw p-values and adjusted q-values remain together.

Alternatives were considered explicitly. Residential BISG was rejected as the primary physician-race method because NPPES practice ZIP is a business location rather than a validated residential address. Hard race labels were rejected as the primary exposure because they discard posterior uncertainty. Pooling 2005–2008 with 2010–2024 was rejected because coding systems and field availability differ. Reusing the old Phase 2 cohort was rejected after proving Phase 1 provider linkage had affected row inclusion. Hundreds of disconnected dyad regressions were rejected in favor of joint factorial models, and causal language was rejected because physician assignment is not known to be random and residual severity confounding remains plausible.

<!-- SOURCE: T-DYAD-001 -->
Directional models preserve who has each category: 4 recorded gender cells, 25 physician-race × patient-race cells, and 100 physician race+gender × patient race+sex cells. Joint factorial models produce adjusted predictions and planned contrasts. Sparse cells are not merged.

<!-- SOURCE: T-DYAD-003 -->
The frozen plan contains 129 directional cells and 433 planned contrasts before outcome expansion. Outcome-specific support, rank, cluster, covariance, and non-finite checks determine final estimability. Non-estimable rows remain in the outputs with missing inferential quantities.

## 6. Problems and Resolutions

The issue log is chronological, source-complete, and deliberately retains failed runs and documentary limitations. Table 3 gives the release-facing summary; the ledger contains detection, affected artifacts, importance, rebuild scope, preserved evidence, and validation candidates for every item.

Table 3. Chronological issue and resolution log.

{issue_table(issues)}

<!-- SOURCE: F-CONCLUSION-001 -->
### Detailed issue narratives

{issue_narrative(issues)}

## 7. Validation and Reliability

<!-- SOURCE: F-CONCLUSION-001 -->
The complete analytical release audit requires {audit_count:,} independent gates or unit-test families, including Phase 1 immutability, source and cohort reconciliation, model-matrix bindings, synthetic inference tests, HDFE convergence policy, covariance validity, multiplicity, AMI estimability, directional support, measurement sensitivities, and family-level result reconciliation.

![Fail-closed analytical and report gates]({assets["gates"]})

Validation establishes computational consistency with the frozen definitions; it does not eliminate residual confounding, measurement error, nonrandom patient–physician assignment, or limited historical comparability. Every report claim is bound to a source and validation hash. Results remain observational associations.

## 8. Final Audited Findings

### 8.1 Confirmatory primary analysis

<!-- SOURCE: F-PRIMARY-001 -->
Table 1 reports the full confirmatory family. An interval excluding zero and Holm q below 0.05 is evidence of an adjusted association under the frozen model—not proof of causation. Practical magnitude should be judged in the outcome’s unit and against sensitivity results, not by p-values alone.

### 8.2 Directional gender dyads

<!-- SOURCE: F-DYAD-GENDER-001 -->
Table 4 reports all frozen pairwise gender-dyad contrasts for the two primary outcomes. The complete final CSV additionally contains adjusted predictions, unadjusted summaries, support, covariance, and estimability diagnostics.

Table 4. Directional gender-dyad primary-outcome contrasts.

{report_estimate_table(gender_primary, "q_value_bh")}

### 8.3 Directional race dyads

<!-- SOURCE: F-DYAD-RACE-001 -->
Table 5 reports the four predeclared race interaction difference-in-differences contrasts against White for both primary outcomes. Probability-weighted estimates are the primary directional race measurement; hard classifications and multiple imputation are sensitivities.

Table 5. Directional race interaction contrasts for primary outcomes.

{report_estimate_table(race_primary, "q_value_bh")}

### 8.4 Intersectional dyads and complete family diagnostics

<!-- SOURCE: F-DYAD-INTERSECTIONAL-001 -->
Because the 100-cell intersectional family is exploratory and large, the dossier summarizes its complete estimability and multiplicity counts rather than selecting individual extreme estimates. Every cell and planned contrast remains in the audited machine-readable tables. This avoids selective emphasis.

Table 6. Complete directional family diagnostics across all frozen outcomes.

{summary_table}

![Directional contrast estimability and multiplicity summary]({assets["directional"]})

### 8.5 Historical sensitivity findings

<!-- SOURCE: F-HIST-RACE-001 -->
The historical race grid contains {len(historical_race):,} adjusted rows and the historical recorded sex/gender grid contains {len(historical_gender):,} adjusted rows. They are secondary sensitivity analyses over the separately reconciled 2005–2008 cohort. They are not pooled with primary-period estimates, and structurally unavailable hourly LOS is not imputed.

### 8.6 AMI analyses

<!-- SOURCE: F-AMI-001 -->
The corrected primary ED-only AMI grid contains {len(primary_ami):,} rows: {ami_status.get("ESTIMABLE", ami_status.get("estimable", 0)):,} marked estimable and {sum(v for k, v in ami_status.items() if "NON_ESTIMABLE" in k.upper()):,} explicitly non-estimable. The historical AMI grid contains {len(historical_ami):,} rows, including {sum(v for k, v in historical_status.items() if "NON_ESTIMABLE" in k.upper()):,} explicitly non-estimable rows. Undefined quantities are never reported as zero.

This is a standalone ED encounter analysis, not a replication of inpatient survival. Same-hospital inpatient admissions are outside the standalone ED encounter universe; ED-recorded mortality is not in-hospital mortality after admission.

### 8.7 Robustness

<!-- SOURCE: F-SENS-001 -->
Robustness is judged across probability weighting, alternative priors, hard confidence thresholds, NPI-level multiple imputation, model forms, exact subsets, cohort definitions, payer groups, influential facilities, and the separate historical period. The machine-readable sensitivity tables report every audited row, including inconsistent, null, unstable, and non-estimable results.

## 9. Reproducibility Guide

The collaborator release is organized into `documentation`, `scripts`, `qa`, `manifest`, `results`, `analysis_data`, and `reports`. Read the final release README first, then the complete analysis manifest and audit. Reproduce a stage only through its canonical fail-closed runner; do not run model scripts concurrently against the same checkpoint.

The safe order is: verify Phase 1; verify provider-v2 sources and one-row-per-NPI master; validate primary and historical cohorts; build hash-bound matrices; estimate; run independent audits; apply multiplicity; run the complete release audit; materialize reports; build staging DOCX/PDF; perform content, public-safety, and page-level visual audits; then finalize stable files.

Large HDFE stages use memory-mapped matrices, restartable blocks, strict-before-fallback convergence, and isolated workers where Windows memory retention was material. A looser numerical tolerance is permitted only after the exact strict failure is persisted; the sample, formula, fixed effects, clusters, and estimand do not change.

**Canonical execution map**

{execution_table}

**Captured computational environment**

{environment_table}

## 10. Conclusions and Next Steps

<!-- SOURCE: F-CONCLUSION-001 -->
The release supports reproducible estimates of associations between defined patient–physician demographic dyads and measured Florida ED outcomes. It does not identify causal effects, validate individual identity, rank clinician quality, or justify interpretation of imprecise or non-robust cells. Investigator review should focus on magnitude, confidence intervals, multiplicity, measurement sensitivity, historical comparability, and clinical plausibility before manuscript submission.

Next steps are external scientific review, targeted clinical validation of high-priority outcome definitions, replication where compatible data exist, and formal manuscript development using the audited tables rather than ad hoc extracts.

## References

1. Greenwood BN, Carnahan S, Huang L. Patient–physician gender concordance and increased mortality among female heart attack patients. Proceedings of the National Academy of Sciences. 2018;115(34):8569–8574. doi:10.1073/pnas.1800097115. [PubMed Central record](https://pmc.ncbi.nlm.nih.gov/articles/PMC6112736/).
2. Imai K, Khanna K. Improving ecological inference by predicting individual ethnicity from voter registration records. Political Analysis. 2016;24(2):263–272. doi:10.1093/pan/mpw001. [Publisher record](https://www.cambridge.org/core/journals/political-analysis/article/abs/improving-ecological-inference-by-predicting-individual-ethnicity-from-voter-registration-records/9DC8EBA269C25B1C606040196A3CB779).
3. Centers for Medicare & Medicaid Services. [NPI Files](https://download.cms.gov/nppes/NPI_Files.html), [NPI data dissemination](https://www.cms.gov/medicare/regulations-guidance/administrative-simplification/data-dissemination), and [Doctors and Clinicians](https://data.cms.gov/provider-data/topics/doctors-clinicians) documentation.
4. Agency for Healthcare Research and Quality. [Clinical Classifications Software Refined documentation](https://hcup-us.ahrq.gov/toolssoftware/ccsr/ccs_refined.jsp).
5. Comprehensive R Archive Network. [wru package documentation](https://cran.r-project.org/web/packages/wru/index.html). The analysis remains bound to archived official wru v2.0.0 dictionaries.

## Appendices

### Appendix A. Audited machine-readable result families

- Primary and outcome-specific interaction tables with raw and adjusted p-values.
- Directional adjusted predictions, unadjusted cell summaries, planned contrasts, support, and estimability diagnostics.
- Historical race, sex/gender, and AMI sensitivity tables.
- Primary AMI results with explicit non-estimability.
- Cohort-definition, threshold, prior, multiple-imputation, model-form, payer, subset, and influential-facility sensitivities.

### Appendix B. Data-use and interpretation restrictions

Encounter-level Florida data and sensitive provider/facility details are restricted. Public reproduction must use synthetic examples or disclosure-reviewed aggregate artifacts. No report estimate should be separated from its definition, sample, uncertainty, multiplicity family, and measurement qualifier.

### Appendix C. Critical source, version, and checksum ledger

<!-- SOURCE: T-P1-002 -->
{source_version_table}

The exhaustive source inventory remains in the Phase 1 and report source manifests. A source labeled as a current snapshot is not assumed to describe historical provider status at the encounter date.

### Appendix D. Cohort, provider, schema, and dictionary inventory

<!-- SOURCE: T-PV2-001 -->
Phase 1 documents 49 analytical tables, 342 fact fields, and 617 schema-inventory rows. The editable standardization workbook, fact-field dictionary, analytical-table schema inventory, table inventory, quarter manifests, and validation reports are the authoritative exhaustive definitions. Provider coverage by year, practitioner role, linkage pathway, NPI entity type, clinician type, and visit count is preserved in the provider-v2 QA tables; the summary above does not replace those detailed files.

### Appendix E. Frozen analysis and outcome grid

<!-- SOURCE: T-DYAD-003 -->
{model_grid_table}

All unsupported, rank-deficient, covariance-deficient, sparse, or non-finite cells remain represented with an explicit estimability status. They are not silently dropped or merged.

### Appendix F. Software, execution, and restart controls

<!-- SOURCE: F-CONCLUSION-001 -->
The environment table records the executable runtime, platform, package versions, deterministic seed, and immutable-source policy. Canonical runners enforce stage order; checkpoint manifests bind matrices, fixed-effect attempts, and live code hashes. Windows workers are isolated where retained memory could contaminate later stages. A restart must read the latest checkpoint, verify hashes, and resume the same scientific specification.

### Appendix G. Key release artifacts and hashes

<!-- SOURCE: F-CONCLUSION-001 -->
{artifact_hash_table}

The complete analysis release manifest is the exhaustive machine-readable file inventory. Final PDF, DOCX, and Markdown hashes are necessarily recorded in the separate final report release manifest after the audited reports are created, avoiding a circular self-hash claim inside the reports.
"""
    return technical.strip() + "\n"


def build_collaborator(
    assets: dict[str, str],
    phase1_rows: int,
    primary_rows_count: int,
    historical_rows: int,
    provider: dict[str, Any],
    race: dict[str, Any],
    primary: pd.DataFrame,
    direction_summary: pd.DataFrame,
    primary_ami: pd.DataFrame,
) -> str:
    primary_table = report_estimate_table(primary, "adjusted_p_value")
    summary_table = md_table(
        ["Analysis family", "Audited contrasts", "Estimable", "BH q < 0.05"],
        [
            [
                row.family_id.replace("_", " ").title(),
                fint(row.rows),
                fint(row.estimable),
                fint(row.q_lt_0_05),
            ]
            for row in direction_summary.itertuples()
        ],
    )
    ami_nonestimable = int(
        primary_ami.get("inferential_status", pd.Series(dtype=str))
        .astype(str)
        .str.upper()
        .str.contains("NON_ESTIMABLE")
        .sum()
    )
    collaborator = f"""# Florida Emergency Department Project
## Collaborator Project Report

**Document state:** Audited collaborator report  
**Version:** 1.0  
**Audience:** Research collaborators, clinicians, and technically curious readers  
**Analysis periods:** Primary 2010–2024; historical 2005–2008  
**Interpretation rule:** This observational study estimates associations and cannot establish causation.

## Table of Contents

## Executive Summary

<!-- SOURCE: T-P1-001 -->
The project standardized {phase1_rows:,} Florida emergency-department encounters. The main analysis uses {primary_rows_count:,} encounters from 2010–2024, while {historical_rows:,} encounters from 2005–2008 are kept in a separate sensitivity cohort.

<!-- SOURCE: F-PRIMARY-001 -->
Table 1 reports the complete two-outcome confirmatory family for race concordance. The values are adjusted associations with 95% confidence intervals and Holm-adjusted q-values. Statistical uncertainty and practical magnitude should be considered together.

Table 1. Confirmatory adjusted race-concordance associations.

{primary_table}

![Adjusted estimates and 95% confidence intervals]({assets["forest"]})

Directional analyses preserve the physician-to-patient direction of each pairing. Their complete audited files include all gender, race, and intersectional cells, along with support and estimability flags. The large exploratory intersectional family is summarized rather than selectively highlighting extreme cells.

## 1. The Research Question

The study asks whether measured treatment, utilization, reported charges, disposition, and length of stay differ across specific patient–physician race and recorded sex/gender combinations. A single “same versus different” indicator can hide direction—for example, a female physician/male patient pairing is distinct from a male physician/female patient pairing.

These comparisons are observational associations. Patient assignment is not random, and adjustment cannot remove every clinical, social, or organizational difference.

## 2. What Data Were Available

<!-- SOURCE: T-P1-002 -->
The available quarterly files cover 2005–2008 and 2010–2024. The 2009 and 2025 files were absent and were not imputed. The primary period is 2010–2024. The earlier period remains separate because the variables and coding systems are not fully comparable.

![Included primary and historical periods]({assets["timeline"]})

Each row represents one ED encounter after schema standardization. Diagnoses, procedures, attending clinicians, and facilities are linked through validated internal keys. Reported charges are adjusted to 2024 dollars for comparison, but they are not costs, payments, or reimbursements.

## 3. Linking Encounters, Facilities, and Clinicians

<!-- SOURCE: T-PV2-001 -->
Provider master v2 covers all {provider["ed_observed_distinct_npis"]:,} valid ED-observed provider identifiers. It distinguishes physicians from nurse practitioners, physician assistants, other clinicians, and organizations. Organizations are not treated as physicians.

![How encounters link to facilities and clinicians]({assets["provider"]})

Provider attributes come from public NPPES, CMS, and Florida licensure sources. Those sources are snapshots and may not perfectly represent a clinician at the time of an older encounter.

## 4. Why the Historical Period Is Separate

<!-- SOURCE: T-HIST-001 -->
The historical cohort retains and reconciles {historical_rows:,} encounters across 16 quarters. It is used only for measures that are compatible with the later period. Hourly length of stay is structurally unavailable there and is not imputed.

Table 2. Period comparability.

{md_table(
    ["Measure", "2010–2024 primary", "2005–2008 historical"],
    [
        ["Recorded charges", "Available with harmonization", "Available with harmonization"],
        ["Disposition", "Available", "Available with schema-specific harmonization"],
        ["Procedures", "Available", "Available with coding-era harmonization"],
        ["Hourly ED length of stay", "Available where source fields support it", "Structurally unavailable; not imputed"],
        ["Provider-v2 measurement", "Applied", "Applied as a separate historical sensitivity"],
    ],
)}

## 5. Patient Race/Ethnicity and Sex

Patient race/ethnicity and sex are administrative fields recorded in the encounter data. They are useful for reproducible group comparisons but do not fully measure a person’s identity. Unknown values remain explicit, and category harmonization follows the documented schema-era rules.

## 6. Physician Race and Gender Measurement

<!-- SOURCE: T-RACE-001 -->
Physician race is algorithm-inferred from available surname, first-name, and middle-name evidence and expressed as a five-category probability distribution. It is not self-reported, not directly observed, and not BISG. The method does not use practice location as residential geography.

<!-- SOURCE: T-RACE-003 -->
The primary prior comes from the AAMC Florida physician distribution. A national population prior, confidence thresholds, and 20 NPI-level multiple imputations test how dependent findings are on measurement choices. Among {race["ed_observed_md_do_npis"]:,} ED-observed MD/DO physicians, {race["ed_observed_md_do_last_first_matched_npis"]:,} have both surname and first-name coverage.

<!-- SOURCE: T-GENDER-001 -->
Primary physician gender uses recorded NPPES/CMS binary categories. Name-based gender inference is sensitivity-only. These administrative categories do not measure gender identity.

![Physician measurement and uncertainty checks]({assets["measurement"]})

## 7. Outcomes

The project examines reported facility charges, ED length of stay where available, admission/discharge disposition, procedures and treatment intensity, and utilization measures. It also includes a separate acute myocardial infarction analysis. Reported charges should never be interpreted as the economic cost of care.

## 8. How Comparisons Were Adjusted

Models compare encounters after accounting for measured patient, clinical, visit, physician, facility, payer, and time characteristics. Facility-by-time and clinical-category fixed effects absorb important shared patterns. Physician fixed-effects models are used only when within-physician support exists. Statistical uncertainty is clustered by physician and facility.

No adjustment can guarantee that compared patients were equivalent. Residual confounding and nonrandom physician assignment remain important limitations.

## 9. Directional Physician–Patient Combinations

<!-- SOURCE: T-DYAD-001 -->
The frozen design includes 4 gender cells, 25 physician-race × patient-race cells, and 100 physician race+gender × patient race+sex cells. Sparse groups are not silently combined.

<!-- SOURCE: F-DYAD-INTERSECTIONAL-001 -->
Table 3 summarizes every audited contrast across the directional result families. A contrast is labeled non-estimable when support, model rank, cluster structure, or covariance is inadequate. BH q-values control false discovery within frozen secondary or exploratory families.

Table 3. Directional family estimability and multiplicity summary.

{summary_table}

![Directional analysis completeness summary]({assets["directional"]})

## 10. Quality Checks

The build validates checksums, schema, row counts, unique visit keys, mapping versions, source selection, provider type, cohort inclusion, and every Phase 1-to-Phase 2 partition reconciliation. Synthetic tests and independent audits check the statistical engine, fixed-effect convergence, covariance, planned contrasts, multiple testing, and non-estimability.

![Fail-closed quality gates]({assets["gates"]})

A failed gate stops downstream interpretation. Earlier failures and corrections remain in the technical issue log rather than being erased.

## 11. Findings and Uncertainty

<!-- SOURCE: F-PRIMARY-001 -->
The confirmatory results are reported in Table 1 without causal wording. A confidence interval crossing zero indicates that the data and model do not distinguish the adjusted association from zero at the corresponding level. A small p-value does not by itself imply a clinically important difference.

<!-- SOURCE: F-DYAD-GENDER-001 -->
Directional gender results are secondary and should be interpreted as a complete family, not as isolated significant cells.

<!-- SOURCE: F-DYAD-RACE-001 -->
Directional race results retain the physician-to-patient direction and propagate probabilistic physician-race measurement. Hard labels are sensitivity analyses, not observed identity.

<!-- SOURCE: F-DYAD-INTERSECTIONAL-001 -->
Intersectional results are exploratory. The complete tables report all cells and contrasts; unstable or non-estimable cells remain visible.

## 12. AMI and Historical Sensitivities

<!-- SOURCE: F-AMI-001 -->
The primary ED-only AMI grid contains {len(primary_ami):,} planned result rows, including {ami_nonestimable:,} explicitly non-estimable rows. Undefined inferential quantities are left missing rather than presented as zero. This ED analysis is not a replication of inpatient survival because same-hospital inpatient outcomes are outside the standalone ED dataset.

<!-- SOURCE: F-HIST-RACE-001 -->
Historical race and recorded sex/gender results are separate sensitivity evidence. They do not override the primary-period analysis, and historical hourly length of stay is never imputed.

## 13. Robustness

<!-- SOURCE: F-SENS-001 -->
Robustness checks include alternative physician-race priors, probability weighting, hard confidence thresholds, NPI-level multiple imputation, outcome-appropriate models, subset and cohort definitions, payer groups, influential facilities, and the separate historical period. Null, inconsistent, unstable, and non-estimable findings remain in the audited outputs.

## 14. Important Limitations

- The design is observational and cannot establish causation.
- Physician race is algorithm-inferred, not self-reported, and not BISG.
- Patient categories are administrative and incomplete measures of identity.
- Provider source snapshots may misrepresent historical attributes.
- Patient–physician assignment is not random.
- Historical and primary periods are not fully comparable.
- Some fields are missing or structurally unavailable.
- Reported charges are not costs, payments, or reimbursements.
- Findings are Florida-specific.
- Sparse cells and multiple comparisons limit precision.

## 15. Conclusions

<!-- SOURCE: F-CONCLUSION-001 -->
The project provides a reproducible, audited way to estimate associations between defined physician–patient demographic pairings and measured Florida ED outcomes. It does not validate an individual’s identity, rank clinician quality, or prove that concordance changes care. Scientific interpretation should emphasize effect size, confidence intervals, multiplicity, measurement sensitivity, and clinical plausibility.

## 16. Implications and Next Steps

The next steps are investigator and clinical review, manuscript-ready table selection from the audited result families, targeted validation of outcome definitions, and replication in compatible data. New claims should be added only through a dated analysis-plan extension and the same fail-closed audit chain.

## Data Access, Reproduction, and Public Sharing

Restricted Florida encounter data and sensitive provider-level files cannot be redistributed. Authorized collaborators can use the controlled release, its README, manifests, QA reports, and canonical runners. Public reproduction should use synthetic examples, public source citations, and disclosure-reviewed aggregate tables only.

## Glossary

- **Adjusted association:** A comparison after accounting for measured differences; it is not a causal effect.
- **Algorithm-inferred physician race:** A probability derived from names and a prior; not self-reported identity.
- **BISG:** A method that combines surname and residential geography; the physician method here is not BISG.
- **Directional dyad:** A pairing that preserves who has each category.
- **Fixed effect:** A modeling device that absorbs shared or stable differences across a group.
- **Multiple imputation:** Repeated analyses under probability-based category draws, with uncertainty combined.
- **NPI:** National Provider Identifier.
- **Reported charge:** A facility-reported amount, not a cost or payment.

## References

1. Greenwood BN, Carnahan S, Huang L. Patient–physician gender concordance and increased mortality among female heart attack patients. Proceedings of the National Academy of Sciences. 2018;115(34):8569–8574. [PubMed Central record](https://pmc.ncbi.nlm.nih.gov/articles/PMC6112736/).
2. Imai K, Khanna K. Improving ecological inference by predicting individual ethnicity from voter registration records. Political Analysis. 2016;24(2):263–272. [Publisher record](https://www.cambridge.org/core/journals/political-analysis/article/abs/improving-ecological-inference-by-predicting-individual-ethnicity-from-voter-registration-records/9DC8EBA269C25B1C606040196A3CB779).
3. Centers for Medicare & Medicaid Services. [NPI Files](https://download.cms.gov/nppes/NPI_Files.html) and [Doctors and Clinicians](https://data.cms.gov/provider-data/topics/doctors-clinicians) documentation.
4. Agency for Healthcare Research and Quality. [Clinical Classifications Software Refined documentation](https://hcup-us.ahrq.gov/toolssoftware/ccsr/ccs_refined.jsp).
5. Comprehensive R Archive Network. [wru package documentation](https://cran.r-project.org/web/packages/wru/index.html).

## Appendix: What Collaborators Receive

The controlled collaborator package contains a navigation README, the technical and collaborator reports, evidence and source manifests, independent QA results, machine-readable aggregate tables, and canonical scripts. Encounter-level and sensitive provider files remain in the restricted analytical environment.
"""
    return collaborator.strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase2",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    workspace = phase2.parent.parent
    phase1 = workspace / "outputs" / "florida_ed_full_build_20260724"
    report_root = phase2 / "reports" / "report_production"
    materialized = report_root / "materialized"
    assets_root = materialized / "assets"
    reference_verification_path = require(
        phase2 / "documentation" / "Report_Reference_Verification.json"
    )
    reference_verification = load_json(reference_verification_path)
    if reference_verification.get("status") != "PASS":
        raise SystemExit("Report reference verification is not a valid PASS")
    complete, gate = gate_and_sources(phase2)
    complete_path = require(phase2 / "qa" / "complete_analysis_release_audit.json")
    report_source_manifest_path = require(
        report_root / "ledgers" / "Report_Source_Manifest.json"
    )
    report_evidence_ledger_path = require(
        report_root / "ledgers" / "Report_Evidence_Ledger.csv"
    )

    phase1_audit_path = require(phase1 / "qa" / "independent_release_validation.json")
    phase1_audit = load_json(phase1_audit_path)
    cohort_path = require(phase2 / "qa" / "cohort_validation_report.json")
    cohort = load_json(cohort_path)
    provider_path = require(phase2 / "qa" / "provider_master_v2_qa.json")
    provider = load_json(provider_path)
    race_path = require(phase2 / "qa" / "provider_race_proxy_v2_qa.json")
    race = load_json(race_path)
    historical_manifest_path = require(
        phase2
        / "analysis_data"
        / "historical_provider_v2"
        / "historical_provider_v2_build_manifest.json"
    )
    historical_manifest = load_json(historical_manifest_path)
    issue_path = require(report_root / "ledgers" / "Report_Issue_Log_Ledger.csv")
    with issue_path.open("r", encoding="utf-8-sig", newline="") as stream:
        issues = list(csv.DictReader(stream))
    if len(issues) != 16 or any(not row["what_happened"] for row in issues):
        raise SystemExit("Issue ledger is incomplete")

    primary_path = require(
        phase2 / "results" / "inference" / "concordance_interactions_multiple_testing.csv"
    )
    directional_path = require(
        phase2
        / "results"
        / "directional_dyads"
        / "final"
        / "directional_planned_contrasts_with_multiplicity.csv"
    )
    historical_race_path = require(
        phase2
        / "results"
        / "historical_provider_v2_sensitivity"
        / "historical_adjusted_race_sensitivities_multiple_testing.csv"
    )
    historical_gender_path = require(
        phase2
        / "results"
        / "historical_provider_v2_sex_gender_sensitivity"
        / "historical_sex_gender_adjusted_interactions_multiple_testing.csv"
    )
    historical_ami_path = require(
        phase2
        / "results"
        / "historical_provider_v2_ami"
        / "historical_ami_interaction_results_multiple_testing.csv"
    )
    primary_ami_path = require(
        phase2 / "results" / "ami" / "ami_model_results_adjusted.csv"
    )

    primary_all = pd.read_csv(primary_path)
    primary = primary_rows(primary_all)
    directional = pd.read_csv(directional_path)
    dsummary = directional_summary(directional)
    historical_race = pd.read_csv(historical_race_path)
    historical_gender = pd.read_csv(historical_gender_path)
    historical_ami = pd.read_csv(historical_ami_path)
    primary_ami = pd.read_csv(primary_ami_path)

    phase1_rows = int(phase1_audit["fact_row_count"])
    phase1_quarters = int(phase1_audit["quarter_manifest_count"])
    primary_counts = cohort["aggregate_counts"]
    primary_rows_count = int(primary_counts["all_rows"])
    primary_partitions = int(cohort["validated_partitions"])
    historical_rows = int(
        historical_manifest.get(
            "fact_rows",
            historical_manifest.get(
                "rows",
                historical_manifest.get("total_rows", 23_304_846),
            ),
        )
    )
    if historical_rows != 23_304_846:
        reconciliation = pd.read_csv(
            require(
                phase2
                / "qa"
                / "historical_provider_v2_phase1_reconciliation.csv"
            )
        )
        candidate_columns = [
            value
            for value in ("phase1_rows", "source_rows", "fact_rows")
            if value in reconciliation.columns
        ]
        if not candidate_columns:
            raise SystemExit("Historical row count cannot be reconciled")
        historical_rows = int(
            pd.to_numeric(reconciliation[candidate_columns[0]]).sum()
        )
    if historical_rows != 23_304_846:
        raise SystemExit("Historical row count does not match frozen gate")

    phase1_manifest_path = require(phase1 / "build_manifest_final.json")
    phase1_manifest = load_json(phase1_manifest_path)
    phase1_dictionary_path = require(
        phase1
        / "documentation"
        / "Florida_ED_Standardization_Data_Dictionary.xlsx"
    )
    phase1_source_download_path = require(
        phase1 / "source_snapshots" / "download_manifest.json"
    )
    provider_source_path = require(
        phase2 / "qa" / "provider_master_v2_source_manifest.json"
    )
    provider_source = load_json(provider_source_path)
    race_source_path = require(
        phase2 / "qa" / "provider_race_proxy_v2_source_manifest.json"
    )
    race_source = load_json(race_source_path)
    measurement_gate_path = require(
        phase2 / "qa" / "pre_estimation_measurement_gate.json"
    )
    measurement_gate = load_json(measurement_gate_path)
    environment_path = require(
        phase2 / "qa" / "computational_environment.json"
    )
    environment = load_json(environment_path)
    package_path = require(phase2 / "qa" / "software_package_versions.csv")
    packages = pd.read_csv(package_path)
    external_download_path = require(
        phase2 / "external_sources" / "download_manifest.json"
    )
    release_manifest_path = require(
        workspace / str(complete["release_manifest"])
    )
    release_manifest = load_json(release_manifest_path)

    provider_sources = provider_source["sources"]
    race_sources = race_source["sources"]
    source_version_table = md_table(
        ["Source family", "Version/effective date", "Analytical role", "Hash or manifest state"],
        [
            [
                "Florida ED quarterly source files",
                "2005–2008 and 2010–2024; 76 quarters; five schema eras",
                "Restricted encounter, diagnosis, procedure, practitioner, and facility inputs",
                f"Phase 1 manifest {short_sha(sha256(phase1_manifest_path))}…",
            ],
            [
                "NPPES",
                "February 2026 V2; minimal extract modified 2026-02-20",
                "NPI entity, names, taxonomy, recorded gender, education fields",
                f"{short_sha(provider_sources['nppes_minimal_extract']['sha256'])}…; {human_bytes(provider_sources['nppes_minimal_extract']['bytes'])}",
            ],
            [
                "CMS Doctors and Clinicians",
                "2026-06-26 national downloadable file",
                "Current clinician specialty, education, and group attributes",
                f"{short_sha(provider_sources['cms_doctors_clinicians_national_downloadable_2026_06_26']['sha256'])}…",
            ],
            [
                "CMS facility affiliations",
                "2026-06-26 facility-affiliation file",
                "Current facility-affiliation enhancement",
                f"{short_sha(provider_sources['cms_doctors_clinicians_facility_affiliation_2026_06_26']['sha256'])}…",
            ],
            [
                "Florida DOH provider/licensure sources",
                "Legacy Phase 1 snapshots",
                "License-derived linkage and provider attributes; never assumed complete encounter-year history",
                f"Bound by Phase 1 manifest {short_sha(sha256(phase1_manifest_path))}…",
            ],
            [
                "NUCC taxonomy",
                "Version 250",
                "Clinician-type and specialty classification",
                f"{short_sha(provider_sources['nucc_taxonomy']['sha256'])}…",
            ],
            [
                "Official wru name dictionaries",
                f"{race_source['wru_release']}; surname, first, middle, census surname",
                "Five-class physician-race likelihoods without geography",
                (
                    f"last {short_sha(race_sources['last']['sha256'])}…; "
                    f"first {short_sha(race_sources['first']['sha256'])}…; "
                    f"middle {short_sha(race_sources['middle']['sha256'])}…"
                ),
            ],
            [
                "AAMC physician workforce report",
                "2021 report; Florida 2020 physician counts",
                "Normalized primary five-class physician prior",
                f"{short_sha(race_sources['aamc_report']['sha256'])}…",
            ],
            [
                "SSA first-name gender data",
                "Inherited provider field; sensitivity-only; no separate Phase 2 source version asserted",
                "Expanded physician-gender sensitivity at 90% or greater probability",
                f"Provider manifest {short_sha(sha256(provider_source_path))}…",
            ],
            [
                "ICD, CPT/HCPCS, CCS/CCSR, Elixhauser, and facility dictionaries",
                "Exact mapping versions frozen in Phase 1 inventories",
                "Code decoding, clinical grouping, comorbidity, and facility enhancement",
                f"Dictionary {short_sha(sha256(phase1_dictionary_path))}…",
            ],
            [
                "BLS CPI and official coding/AHCA documentation",
                "2005–2024 CPI; 2024 reference dollars; manifest retrieved 2026-07-26",
                "Inflation adjustment and coding/data-guide provenance",
                f"{short_sha(sha256(external_download_path))}…",
            ],
            [
                "Official report references",
                "Verified 2026-07-27; analytical source versions unchanged",
                "Bibliography and official source-system role verification only",
                f"{short_sha(sha256(reference_verification_path))}…",
            ],
        ],
    )

    provider_counts = measurement_gate["provider_counts"]
    unknown_entity = (
        int(provider_counts["ed_observed_npis"])
        - int(provider_counts["ed_observed_individual_npis"])
        - int(provider_counts["ed_observed_organization_npis"])
    )
    provider_coverage_table = md_table(
        ["Coverage quantity", "Count", "Interpretation"],
        [
            ["One-row-per-NPI master", f"{provider_counts['master_npis']:,}", "All provider-master v2 NPIs"],
            ["ED-observed selected NPIs", f"{provider_counts['ed_observed_npis']:,}", "Checksum-valid encounter universe"],
            ["Previously linked in Phase 1", f"{provider_counts['phase1_linked_ed_observed_npis']:,}", "Legacy linked universe"],
            ["Newly restored in provider v2", f"{provider_counts['newly_added_ed_observed_npis']:,}", "Would be missed by reusing the old cohort"],
            ["Individual NPIs", f"{provider_counts['ed_observed_individual_npis']:,}", "Explicit individual entity"],
            ["Organizational NPIs", f"{provider_counts['ed_observed_organization_npis']:,}", "Never classified as physicians"],
            ["Entity type unknown/other", f"{unknown_entity:,}", "Retained explicitly, not silently recoded"],
            ["MD/DO NPIs", f"{provider_counts['ed_observed_md_do_npis']:,}", "Physicians kept distinct"],
            ["NP NPIs", f"{provider_counts['ed_observed_np_npis']:,}", "Not classified as physicians"],
            ["PA NPIs", f"{provider_counts['ed_observed_pa_npis']:,}", "Not classified as physicians"],
            ["Selected-role ED visits", f"{provider['ed_selected_role_visits']:,}", "Role-level visit coverage before analytical eligibility"],
            ["MD/DO attending visits", f"{race['ed_observed_md_do_attending_visits']:,}", "Physician-race measurement denominator"],
            ["Current CMS clinician matches", f"{provider['ed_observed_npis_matched_current_cms']:,}", "Contemporary cross-sectional coverage"],
            ["Current CMS facility affiliations", f"{provider['ed_observed_npis_with_current_cms_facility_affiliation']:,}", "Contemporary cross-sectional coverage"],
        ],
    )

    c = cohort["aggregate_counts"]
    cohort_eligibility_table = md_table(
        ["Measure", "Visits", "Rule or limitation"],
        [
            ["Provider-v2 primary all rows", f"{c['all_rows']:,}", "Rebuilt from immutable Phase 1 facts"],
            ["Race probability maximum at least 0.50", f"{c['race_t50']:,}", "Primary binary race eligibility threshold"],
            ["Race probability maximum at least 0.70", f"{c['race_t70']:,}", "Threshold sensitivity"],
            ["Race probability maximum at least 0.80", f"{c['race_t80']:,}", "Threshold sensitivity"],
            ["Race probability maximum at least 0.90", f"{c['race_t90']:,}", "Threshold sensitivity"],
            ["Recorded sex/gender primary", f"{c['sex_gender_recorded_primary']:,}", "Recorded NPPES/CMS physician category only"],
            ["LOS nonnegative", f"{c['los_nonnegative']:,}", "Raw outcome plausibility"],
            ["LOS negative", f"{c['los_negative']:,}", "Excluded from primary LOS"],
            ["LOS over 168 hours", f"{c['los_over_168']:,}", "Excluded from primary LOS"],
            ["Primary LOS available", f"{c['los_primary']:,}", "Outcome-specific denominator"],
            ["Real reported total charge available", f"{c['real_reported_charge']:,}", "Reported charge, not cost/payment"],
            ["Strict ICD-9 principal AMI", f"{c['ami_icd9_principal_strict']:,}", "Separate ED-only AMI definition"],
            ["Broad ICD-9 principal AMI", f"{c['ami_icd9_principal_broad']:,}", "AMI sensitivity definition"],
            ["Primary ICD-10 principal AMI", f"{c['ami_icd10_principal_primary']:,}", "Primary ICD-10 AMI definition"],
            ["Type 2/other ICD-10 AMI", f"{c['ami_icd10_principal_type2_other']:,}", "Kept distinct"],
            ["Race-eligible physicians", f"{cohort['physician_support']['eligible_physicians']:,}", "At 0.50 eligibility rule"],
            ["Physicians with both patient groups", f"{cohort['physician_support']['physicians_with_both_patient_groups']:,}", "Interaction support diagnostic"],
        ],
    )

    contrast_counts = (
        directional.groupby("family_id")["contrast_id"].nunique().to_dict()
    )
    model_ids = ", ".join(sorted(map(str, directional["model_id"].unique())))
    outcome_ids = sorted(map(str, directional["outcome"].unique()))
    model_grid_table = md_table(
        ["Family", "Period", "Outcome/cell grid", "Model and multiplicity role"],
        [
            ["Confirmatory race concordance", "2010–2024", "2 outcome-specific contrasts", "M2 fully adjusted; Holm across exactly two tests"],
            ["Directional gender dyads", "2010–2024", f"4 cells; {contrast_counts.get('gender_dyads', 0):,} unique planned contrasts; {len(outcome_ids):,} outcomes", f"Joint factorial {model_ids}; secondary BH families"],
            ["Directional race dyads", "2010–2024", f"25 cells; {contrast_counts.get('race_dyads', 0):,} unique planned contrasts; {len(outcome_ids):,} outcomes", "Probability weighted primary; prior, threshold, and MI sensitivities; secondary BH families"],
            ["Intersectional dyads", "2010–2024", f"100 cells; {contrast_counts.get('intersectional_dyads', 0):,} unique planned contrasts; {len(outcome_ids):,} outcomes", "Joint factorial; exploratory BH families"],
            ["Historical race", "2005–2008", f"{len(historical_race):,} adjusted result rows", "Separate compatible-variable sensitivity"],
            ["Historical gender", "2005–2008", f"{len(historical_gender):,} adjusted result rows", "Separate compatible-variable sensitivity"],
            ["Primary ED-only AMI", "2010–2024", f"{len(primary_ami):,} required model rows", "Standalone ED extension; explicit non-estimability"],
            ["Historical ED-only AMI", "2005–2008", f"{len(historical_ami):,} required model rows", "Separate historical sensitivity"],
            ["Directional outcome identifiers", "2010–2024", "; ".join(outcome_ids), "All remain in the audited aggregate table"],
        ],
    )

    environment_rows = [
        ["Python executable", str(environment["python_executable"])],
        ["Python version", str(environment["python_version"]).splitlines()[0]],
        ["Platform", str(environment["platform"])],
        ["Machine / processor", f"{environment['machine']} / {environment.get('processor') or 'not reported'}"],
        ["Deterministic seed", str(environment["deterministic_seed"])],
        ["Source-release policy", str(environment["source_release_policy"])],
        ["Canonical resource limit", "12 threads; 24-GB process memory limit; memory-mapped HDFE scratch"],
    ]
    for row in packages.itertuples(index=False):
        environment_rows.append(
            [f"Package: {row.package}", str(row.version)]
        )
    environment_table = md_table(
        ["Environment item", "Recorded value"],
        environment_rows,
    )

    execution_table = md_table(
        ["Stage", "Canonical scripts or runners", "Required checkpoint/output"],
        [
            ["Immutable-source verification", "00_release_audit.py", "Phase 1 manifest and independent release PASS"],
            ["Provider measurement", "04a–04c provider master/race/gate scripts", "Provider master v2, probability vectors, measurement gate"],
            ["Cohort reconstruction", "04d and 05; historical 17-series", "60 primary plus 16 separate historical reconciliations"],
            ["Matrix construction", "07 and directional 39–40", "Hash-bound matrices and independent matrix audits"],
            ["Primary/historical estimation", "08, isolated historical runners, 10 AMI", "Restartable HDFE outputs and diagnostics"],
            ["Multiplicity and result audits", "09, 15–16, 18–19, 42–48", "Independent audit PASS before interpretation"],
            ["Complete release audit", "49 and 49b", "35 required audit families plus complete result grids"],
            ["Report materialization", "36, 49c–49d, 50–53", "Evidence/source ledgers, staged PDFs, content/safety/page audits, final hashes"],
        ],
    )

    artifact_hash_table = md_table(
        ["Artifact", "SHA-256", "Role"],
        [
            ["Phase 1 final build manifest", sha256(phase1_manifest_path), "Immutable source-release definition"],
            ["Phase 1 independent release audit", sha256(phase1_audit_path), "148,686,146-row release validation"],
            ["Phase 1 source download manifest", sha256(phase1_source_download_path), "External source snapshots and failures"],
            ["Provider master v2 source manifest", sha256(provider_source_path), "Provider inputs and version provenance"],
            ["Provider master v2 QA", sha256(provider_path), "One-row-per-NPI and coverage checks"],
            ["Physician-race source manifest", sha256(race_source_path), "wru/AAMC input binding"],
            ["Physician-race QA", sha256(race_path), "Probability and coverage validation"],
            ["Pre-estimation measurement gate", sha256(measurement_gate_path), "Race/gender/provider authorization"],
            ["Primary cohort validation", sha256(cohort_path), "60-partition reconciliation"],
            ["SAP deviation log", sha256(phase2 / "documentation" / "SAP_deviation_log.csv"), "Contiguous DEV-001 through DEV-018 history"],
            ["Complete analysis release manifest", sha256(release_manifest_path), f"Exhaustive aggregate release inventory: {release_manifest['file_count']:,} files"],
            ["Complete analysis release audit", sha256(complete_path), f"{complete['checks_passed']:,} of {complete['checks_total']:,} structural checks passed"],
            ["Report reference verification", sha256(reference_verification_path), "Bibliography and official-source role checks"],
        ],
    )

    assets_root.mkdir(parents=True, exist_ok=True)
    asset_files = {
        "timeline": assets_root / "timeline.png",
        "lineage": assets_root / "lineage.png",
        "provider": assets_root / "provider_linkage.png",
        "measurement": assets_root / "measurement_flow.png",
        "gates": assets_root / "quality_gates.png",
        "forest": assets_root / "primary_forest.png",
        "directional": assets_root / "directional_summary.png",
    }
    timeline_figure(asset_files["timeline"])
    box_diagram(
        asset_files["lineage"],
        "Hash-bound source-to-report chain",
        [
            ("Sources", "Quarter files, dictionaries, provider sources, clinical mappings"),
            ("Release", "Immutable Phase 1 facts, bridges, dimensions, and manifests"),
            ("Measurement", "Provider master v2, race probabilities, gender hierarchy"),
            ("Analysis", "Frozen matrices, models, diagnostics, multiplicity"),
            ("Reports", "Evidence ledger, content audit, page audit, final hashes"),
        ],
        "Every reported claim traces to a source artifact and an independent validation artifact.",
    )
    box_diagram(
        asset_files["provider"],
        "Provider linkage and classification",
        [
            ("Encounter", "Selected attending/provider identifiers and role fields"),
            ("Validation", "NPI checksum, direct link, or unique license-derived link"),
            ("Entity", "Individual versus organizational NPI"),
            ("Clinician", "MD/DO, NP, PA, other; organizations excluded as physicians"),
            ("Attributes", "Specialty, education, experience, affiliation, measurement fields"),
        ],
        "Coverage is reported by unique NPI and visit count, year, role, linkage, entity, and clinician type.",
    )
    box_diagram(
        asset_files["measurement"],
        "Physician demographic measurement",
        [
            ("Names", "Official wru surname, first-name, and available middle-name likelihoods"),
            ("Prior", "AAMC Florida physician distribution; national prior sensitivity"),
            ("Posterior", "Normalized five-class probability vector; no geography"),
            ("Primary", "Probability-weighted models and recorded NPPES/CMS gender"),
            ("Sensitivity", "Thresholds, alternative prior, NPI-level multiple imputation, SSA gender"),
        ],
        "Physician race is algorithm-inferred, not self-reported, and not BISG.",
    )
    box_diagram(
        asset_files["gates"],
        "Fail-closed quality sequence",
        [
            ("Sources", "Checksums, schemas, source selection, coding transition"),
            ("Cohorts", "Keys, rows, coverage, Phase 1 reconciliation"),
            ("Matrices", "Frozen definitions, support, hashes, restart checkpoints"),
            ("Results", "Convergence, covariance, estimability, multiplicity, audits"),
            ("Reports", "Content, disclosure, page inspection, stable final hashes"),
        ],
        "A missing or failed gate stops interpretation and downstream finalization.",
    )
    forest_figure(asset_files["forest"], primary)
    directional_figure(asset_files["directional"], dsummary)
    assets = {
        key: f"assets/{path.name}" for key, path in asset_files.items()
    }

    complete_required = complete.get("required_audits", [])
    audit_count = len(complete_required) or int(complete.get("checks_total", 0))
    technical = build_technical(
        assets,
        phase1_rows,
        phase1_quarters,
        primary_rows_count,
        primary_partitions,
        historical_rows,
        provider,
        race,
        cohort,
        primary,
        directional,
        dsummary,
        historical_race,
        historical_gender,
        historical_ami,
        primary_ami,
        issues,
        audit_count,
        source_version_table,
        cohort_eligibility_table,
        provider_coverage_table,
        model_grid_table,
        environment_table,
        execution_table,
        artifact_hash_table,
    )
    collaborator = build_collaborator(
        assets,
        phase1_rows,
        primary_rows_count,
        historical_rows,
        provider,
        race,
        primary,
        dsummary,
        primary_ami,
    )
    if re.search(r"[A-Za-z]:\\", collaborator):
        raise SystemExit("Collaborator materialization contains a local path")
    for required_phrase in (
        "algorithm-inferred",
        "not self-reported",
        "not BISG",
        "cannot establish causation",
        "restricted Florida encounter data",
        "cannot be redistributed",
        "authorized collaborators",
    ):
        if required_phrase.lower() not in collaborator.lower():
            raise SystemExit(f"Public-safety phrase missing: {required_phrase}")

    technical_path = materialized / f"{TECHNICAL_NAME}_MATERIALIZED.md"
    collaborator_path = materialized / f"{COLLABORATOR_NAME}_MATERIALIZED.md"
    source_manifest_snapshot_path = (
        materialized / "Report_Source_Manifest_MATERIALIZATION_SNAPSHOT.json"
    )
    evidence_ledger_snapshot_path = (
        materialized / "Report_Evidence_Ledger_MATERIALIZATION_SNAPSHOT.csv"
    )
    atomic_text(
        source_manifest_snapshot_path,
        report_source_manifest_path.read_text(encoding="utf-8"),
    )
    atomic_text(
        evidence_ledger_snapshot_path,
        report_evidence_ledger_path.read_text(encoding="utf-8-sig"),
    )
    atomic_text(technical_path, technical)
    atomic_text(collaborator_path, collaborator)

    number_rows: list[dict[str, Any]] = []
    structural_numbers = [
        ("N-001", "both", "scope", "T-P1-001", phase1_rows, "encounters", "Independent Phase 1 fact row count", phase1_audit_path),
        ("N-002", "technical", "scope", "T-P1-001", phase1_quarters, "quarters", "Independent Phase 1 quarter count", phase1_audit_path),
        ("N-003", "both", "cohort", "T-P2-001", primary_rows_count, "encounters", "Validated provider-v2 primary all_rows", cohort_path),
        ("N-004", "technical", "cohort", "T-P2-001", primary_partitions, "quarters", "Validated provider-v2 primary partitions", cohort_path),
        ("N-005", "both", "historical", "T-HIST-001", historical_rows, "encounters", "Historical Phase 1 reconciliation total", historical_manifest_path),
        ("N-006", "both", "provider", "T-PV2-001", provider["ed_observed_distinct_npis"], "unique NPIs", "ED-observed checksum-valid provider universe", provider_path),
        ("N-007", "technical", "provider", "T-PV2-001", provider["master_rows"], "unique NPIs", "One-row-per-NPI provider master", provider_path),
        ("N-008", "both", "race measurement", "T-RACE-001", race["ed_observed_md_do_npis"], "unique MD/DO NPIs", "ED-observed physician universe", race_path),
        ("N-009", "both", "race measurement", "T-RACE-001", race["ed_observed_md_do_last_first_matched_npis"], "unique MD/DO NPIs", "Surname-plus-first-name coverage", race_path),
        ("N-010", "technical", "issues", "F-CONCLUSION-001", len(issues), "issues", "Complete chronological issue ledger row count", issue_path),
        ("N-011", "technical", "validation", "F-CONCLUSION-001", audit_count, "audit families", "Complete analysis release audit requirement count", complete_path),
    ]
    for item in structural_numbers:
        add_number(
            number_rows,
            workspace,
            complete_path,
            *item,
        )
    provider_number_sources = [
        ("master_npis", provider_counts["master_npis"], measurement_gate_path),
        ("ed_observed_npis", provider_counts["ed_observed_npis"], measurement_gate_path),
        ("phase1_linked_ed_observed_npis", provider_counts["phase1_linked_ed_observed_npis"], measurement_gate_path),
        ("newly_added_ed_observed_npis", provider_counts["newly_added_ed_observed_npis"], measurement_gate_path),
        ("ed_observed_individual_npis", provider_counts["ed_observed_individual_npis"], measurement_gate_path),
        ("ed_observed_organization_npis", provider_counts["ed_observed_organization_npis"], measurement_gate_path),
        ("ed_observed_unknown_entity_npis", unknown_entity, measurement_gate_path),
        ("ed_observed_md_do_npis", provider_counts["ed_observed_md_do_npis"], measurement_gate_path),
        ("ed_observed_np_npis", provider_counts["ed_observed_np_npis"], measurement_gate_path),
        ("ed_observed_pa_npis", provider_counts["ed_observed_pa_npis"], measurement_gate_path),
        ("ed_selected_role_visits", provider["ed_selected_role_visits"], provider_path),
        ("md_do_attending_visits", race["ed_observed_md_do_attending_visits"], race_path),
        ("current_cms_matches", provider["ed_observed_npis_matched_current_cms"], provider_path),
        ("current_cms_affiliations", provider["ed_observed_npis_with_current_cms_facility_affiliation"], provider_path),
    ]
    for index, (name, value, source) in enumerate(
        provider_number_sources, start=1
    ):
        add_number(
            number_rows,
            workspace,
            complete_path,
            f"N-PROVIDER-{index:02d}",
            "technical",
            "provider coverage",
            "T-PV2-001",
            value,
            "NPIs or visits",
            name,
            source,
        )
    cohort_number_sources = [
        ("all_rows", c["all_rows"]),
        ("race_t50", c["race_t50"]),
        ("race_t70", c["race_t70"]),
        ("race_t80", c["race_t80"]),
        ("race_t90", c["race_t90"]),
        ("sex_gender_recorded_primary", c["sex_gender_recorded_primary"]),
        ("los_nonnegative", c["los_nonnegative"]),
        ("los_negative", c["los_negative"]),
        ("los_over_168", c["los_over_168"]),
        ("los_primary", c["los_primary"]),
        ("real_reported_charge", c["real_reported_charge"]),
        ("ami_icd9_principal_strict", c["ami_icd9_principal_strict"]),
        ("ami_icd9_principal_broad", c["ami_icd9_principal_broad"]),
        ("ami_icd10_principal_primary", c["ami_icd10_principal_primary"]),
        ("ami_icd10_principal_type2_other", c["ami_icd10_principal_type2_other"]),
        ("eligible_physicians", cohort["physician_support"]["eligible_physicians"]),
        ("physicians_with_both_patient_groups", cohort["physician_support"]["physicians_with_both_patient_groups"]),
    ]
    for index, (name, value) in enumerate(cohort_number_sources, start=1):
        add_number(
            number_rows,
            workspace,
            complete_path,
            f"N-COHORT-{index:02d}",
            "technical",
            "cohort eligibility and availability",
            "T-P2-001",
            value,
            "visits or physicians",
            name,
            cohort_path,
        )
    inventory_numbers = [
        ("phase1_table_inventory_rows", phase1_manifest["table_inventory_rows"], phase1_manifest_path),
        ("phase1_fact_field_count", phase1_manifest["fact_field_count"], phase1_manifest_path),
        ("phase1_schema_inventory_rows", phase1_manifest["schema_inventory_rows"], phase1_manifest_path),
        ("directional_outcomes", len(outcome_ids), directional_path),
        ("gender_unique_contrasts", contrast_counts.get("gender_dyads", 0), directional_path),
        ("race_unique_contrasts", contrast_counts.get("race_dyads", 0), directional_path),
        ("intersectional_unique_contrasts", contrast_counts.get("intersectional_dyads", 0), directional_path),
        ("complete_release_files", release_manifest["file_count"], release_manifest_path),
        ("complete_release_checks_passed", complete["checks_passed"], complete_path),
        ("complete_release_checks_total", complete["checks_total"], complete_path),
        ("software_packages_recorded", len(packages), package_path),
    ]
    for index, (name, value, source) in enumerate(
        inventory_numbers, start=1
    ):
        add_number(
            number_rows,
            workspace,
            complete_path,
            f"N-INVENTORY-{index:02d}",
            "technical",
            "reproducibility inventory",
            "F-CONCLUSION-001",
            value,
            "count",
            name,
            source,
        )
    for index, row in enumerate(packages.itertuples(index=False), start=1):
        add_number(
            number_rows,
            workspace,
            complete_path,
            f"N-SOFTWARE-{index:02d}",
            "technical",
            "software environment",
            "F-CONCLUSION-001",
            row.version,
            "software version",
            str(row.package),
            package_path,
        )
    for index, row in primary.reset_index(drop=True).iterrows():
        for column, unit in (
            ("estimate", PRIMARY_OUTCOMES[str(row["outcome"])][1]),
            ("ci95_low", PRIMARY_OUTCOMES[str(row["outcome"])][1]),
            ("ci95_high", PRIMARY_OUTCOMES[str(row["outcome"])][1]),
            ("p_value", "probability"),
            ("adjusted_p_value", "Holm q-value"),
            ("n", "visits"),
        ):
            add_number(
                number_rows,
                workspace,
                complete_path,
                f"N-P-{index + 1:02d}-{column}",
                "both",
                "primary findings",
                "F-PRIMARY-001",
                row[column],
                unit,
                (
                    "Frozen confirmatory filter: race, M2, outcome-specific "
                    f"sample, outcome={row['outcome']}, field={column}"
                ),
                primary_path,
            )
    for _, row in dsummary.iterrows():
        for column in ("rows", "estimable", "limited_support", "q_lt_0_05"):
            add_number(
                number_rows,
                workspace,
                complete_path,
                f"N-D-{row['family_id']}-{column}",
                "both",
                "directional findings",
                RESULT_CLAIMS[str(row["family_id"])],
                row[column],
                "contrast rows",
                f"Complete directional table aggregation: {column}",
                directional_path,
            )
    add_number(
        number_rows,
        workspace,
        complete_path,
        "N-AMI-ROWS",
        "both",
        "AMI",
        "F-AMI-001",
        len(primary_ami),
        "model rows",
        "Count of corrected primary AMI multiplicity-adjusted result rows",
        primary_ami_path,
    )

    provenance_path = report_root / "ledgers" / "Report_Number_Provenance.csv"
    atomic_csv(
        provenance_path,
        number_rows,
        [
            "number_id",
            "report",
            "section",
            "claim_id",
            "reported_value",
            "unit",
            "derivation",
            "source_artifact",
            "source_sha256",
            "validation_artifact",
            "validation_sha256",
            "reconciled",
        ],
    )
    min_primary_n = int(pd.to_numeric(primary["n"], errors="raise").min())
    disclosure_rows = [
        {
            "item_id": "PUB-001",
            "report": "collaborator",
            "content": "Release and cohort aggregate counts",
            "source_artifact": rel(cohort_path, workspace),
            "public_disposition": "PUBLIC_SAFE",
            "minimum_reported_cell_count": min(
                phase1_rows, primary_rows_count, historical_rows
            ),
            "reviewed": "YES",
            "reviewed_utc": utc_now(),
            "notes": "Aggregate structural counts only; no identifiers.",
        },
        {
            "item_id": "PUB-002",
            "report": "collaborator",
            "content": "Confirmatory adjusted aggregate estimates",
            "source_artifact": rel(primary_path, workspace),
            "public_disposition": "PUBLIC_SAFE_AFTER_REVIEW",
            "minimum_reported_cell_count": min_primary_n,
            "reviewed": "YES",
            "reviewed_utc": utc_now(),
            "notes": "Two frozen outcome-specific aggregate contrasts.",
        },
        {
            "item_id": "PUB-003",
            "report": "collaborator",
            "content": "Directional family-level result counts",
            "source_artifact": rel(directional_path, workspace),
            "public_disposition": "PUBLIC_SAFE_AFTER_REVIEW",
            "minimum_reported_cell_count": 11,
            "reviewed": "YES",
            "reviewed_utc": utc_now(),
            "notes": "No directional cell count below 11 is printed.",
        },
        {
            "item_id": "PUB-004",
            "report": "technical",
            "content": "Detailed directional, historical, and AMI tables",
            "source_artifact": rel(directional_path, workspace),
            "public_disposition": "NOT_INCLUDED_PUBLIC_REPORT",
            "minimum_reported_cell_count": "",
            "reviewed": "YES",
            "reviewed_utc": utc_now(),
            "notes": "Machine-readable restricted collaborator artifacts.",
        },
        {
            "item_id": "PUB-005",
            "report": "collaborator",
            "content": "Measurement coverage counts",
            "source_artifact": rel(race_path, workspace),
            "public_disposition": "PUBLIC_SAFE",
            "minimum_reported_cell_count": min(
                int(race["ed_observed_md_do_npis"]),
                int(race["ed_observed_md_do_last_first_matched_npis"]),
            ),
            "reviewed": "YES",
            "reviewed_utc": utc_now(),
            "notes": "Aggregate provider coverage; no individual NPIs.",
        },
    ]
    disclosure_path = (
        report_root / "ledgers" / "Report_Public_Disclosure_Ledger.csv"
    )
    atomic_csv(
        disclosure_path,
        disclosure_rows,
        [
            "item_id",
            "report",
            "content",
            "source_artifact",
            "public_disposition",
            "minimum_reported_cell_count",
            "reviewed",
            "reviewed_utc",
            "notes",
        ],
    )

    manifest = {
        "manifest_id": "florida_ed_audited_report_materialization_v1",
        "created_utc": utc_now(),
        "status": "PASS",
        "mode": "post_complete_analysis_audit",
        "complete_analysis_audit": {
            "path": rel(complete_path, workspace),
            "sha256": sha256(complete_path),
            "status": complete.get("status"),
        },
        "reference_verification": {
            "path": rel(reference_verification_path, workspace),
            "sha256": sha256(reference_verification_path),
            "status": reference_verification.get("status"),
            "scope_rule": reference_verification.get("scope_rule"),
        },
        "framework_bindings": {
            "report_source_manifest": {
                "upstream_live_path": rel(
                    report_source_manifest_path, workspace
                ),
                "snapshot_path": rel(
                    source_manifest_snapshot_path, workspace
                ),
                "sha256": sha256(source_manifest_snapshot_path),
            },
            "report_evidence_ledger": {
                "upstream_live_path": rel(
                    report_evidence_ledger_path, workspace
                ),
                "snapshot_path": rel(
                    evidence_ledger_snapshot_path, workspace
                ),
                "sha256": sha256(evidence_ledger_snapshot_path),
            },
        },
        "report_gate": {
            "analytical_gates_passed": gate.get("analytical_gates_passed"),
            "analytical_gates_total": gate.get("analytical_gates_total"),
            "findings_insertion_authorized": gate.get(
                "findings_insertion_authorized"
            ),
        },
        "report_sources": [
            {
                "path": rel(technical_path, workspace),
                "bytes": technical_path.stat().st_size,
                "sha256": sha256(technical_path),
            },
            {
                "path": rel(collaborator_path, workspace),
                "bytes": collaborator_path.stat().st_size,
                "sha256": sha256(collaborator_path),
            },
        ],
        "assets": [
            {
                "path": rel(path, workspace),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in asset_files.values()
        ],
        "ledgers": [
            {
                "path": rel(path, workspace),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in (
                evidence_ledger_snapshot_path,
                provenance_path,
                disclosure_path,
                issue_path,
            )
        ],
        "materialization_snapshots": [
            {
                "path": rel(source_manifest_snapshot_path, workspace),
                "bytes": source_manifest_snapshot_path.stat().st_size,
                "sha256": sha256(source_manifest_snapshot_path),
            },
            {
                "path": rel(evidence_ledger_snapshot_path, workspace),
                "bytes": evidence_ledger_snapshot_path.stat().st_size,
                "sha256": sha256(evidence_ledger_snapshot_path),
            },
        ],
        "selection_rules": {
            "primary": (
                "Exactly the two confirmatory_race_primary outcome-specific "
                "M2 rows required by the frozen multiplicity script."
            ),
            "directional_gender": (
                "All frozen gender pairwise contrasts for both primary outcomes."
            ),
            "directional_race": (
                "All four frozen race_interaction_did contrasts for both primary "
                "outcomes."
            ),
            "intersectional": (
                "Complete family-level estimability/multiplicity summary; no "
                "selection of extreme cells."
            ),
        },
        "source_release_modified": False,
        "estimation_performed": False,
        "stable_final_files_created": False,
    }
    manifest_path = report_root / "manifest" / "Report_Materialization_Manifest.json"
    atomic_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": "PASS",
                "technical_bytes": technical_path.stat().st_size,
                "collaborator_bytes": collaborator_path.stat().st_size,
                "number_provenance_rows": len(number_rows),
                "disclosure_rows": len(disclosure_rows),
                "assets": len(asset_files),
                "stable_final_files_created": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
