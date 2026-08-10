from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path


SUPPORT = Path(__file__).resolve().parent
PACKAGE = SUPPORT.parent
DATA = PACKAGE / "dashboard_data"
PROJECT_ROOT = Path(
    os.environ.get(
        "FLORIDA_ED_PBI_PROJECT_ROOT",
        str(Path.home() / "Desktop" / "Florida_ED_PBI_Build"),
    )
).resolve()
PROJECT = "Florida_ED_Project_Portfolio_Dashboard"
MODEL = PROJECT_ROOT / f"{PROJECT}.SemanticModel"
REPORT = PROJECT_ROOT / f"{PROJECT}.Report"
THEME_SOURCE = PACKAGE / "powerbi_theme.json"
BASE_THEME_SOURCE = SUPPORT / "CY26SU07.json"

TABLES = [
    "DimPeriod",
    "DimSchemaFamily",
    "DimProjectStage",
    "DimMetric",
    "DimClinicalDomain",
    "DimCodingMap",
    "DimModelSpec",
    "FactProjectCoverage",
    "FactPartitionStatus",
    "FactEnhancementCoverage",
    "FactProviderMeasurement",
    "FactValidationStatus",
    "FactAnalyticalStatus",
    "FactSyntheticDemonstration",
]

RELATIONSHIPS = [
    ("rel_period_partition", "FactPartitionStatus.PeriodKey", "DimPeriod.PeriodKey"),
    ("rel_schema_partition", "FactPartitionStatus.SchemaFamilyKey", "DimSchemaFamily.SchemaFamilyKey"),
    ("rel_stage_validation", "FactValidationStatus.StageKey", "DimProjectStage.StageKey"),
    ("rel_stage_analytical", "FactAnalyticalStatus.StageKey", "DimProjectStage.StageKey"),
    ("rel_metric_project", "FactProjectCoverage.MetricKey", "DimMetric.MetricKey"),
    ("rel_metric_provider", "FactProviderMeasurement.MetricKey", "DimMetric.MetricKey"),
    ("rel_clinical_enhancement", "FactEnhancementCoverage.ClinicalDomainKey", "DimClinicalDomain.ClinicalDomainKey"),
    ("rel_model_analytical", "FactAnalyticalStatus.ModelSpecKey", "DimModelSpec.ModelSpecKey"),
]

SORT_BY = {
    ("DimPeriod", "QuarterLabel"): "Quarter",
    ("DimPeriod", "PeriodGroup"): "PeriodGroupOrder",
    ("DimSchemaFamily", "SchemaFamilyLabel"): "DisplayOrder",
    ("DimProjectStage", "StageName"): "StageOrder",
    ("DimMetric", "MetricName"): "DisplayOrder",
    ("DimClinicalDomain", "ClinicalDomainName"): "DisplayOrder",
    ("DimModelSpec", "ModelLabel"): "ModelOrder",
    ("FactEnhancementCoverage", "EnhancementName"): "DisplayOrder",
    ("FactValidationStatus", "ValidationCheck"): "CheckOrder",
    ("FactAnalyticalStatus", "ComponentStatus"): "StatusOrder",
}

TYPE_MAP = {
    "Whole number": ("int64", "Int64.Type"),
    "Date": ("dateTime", "date"),
    "True/False": ("boolean", "logical"),
    "Text": ("string", "text"),
}

SCHEMA_VISUAL = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.11.0/schema.json"
SCHEMA_PAGE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
FOOTER = "Public-safe metadata and synthetic demonstration only; no row-level data or numerical concordance estimates."
STATUS_TEXT = (
    "Phase 1 complete and independently validated. Phase 2 measurement, cohort construction, historical analyses, "
    "and primary race M1-M3 estimation complete; primary gender M1 complete. Remaining primary and sensitivity "
    "analyses and the final independent analytical-release audit are pending."
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def dictionary() -> dict[tuple[str, str], str]:
    return {(r["Table"], r["Column"]): r["DataType"] for r in read_csv(PACKAGE / "dashboard_data_dictionary.csv")}


def quote_ident(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def m_text(value: str) -> str:
    return '"' + value.replace('"', '""').replace("\r", "#(cr)").replace("\n", "#(lf)") + '"'


def m_value(value: str, data_type: str) -> str:
    if value == "":
        return "null"
    if data_type == "Whole number":
        return str(int(float(value)))
    if data_type == "True/False":
        return "true" if value.strip().lower() in {"true", "1", "yes"} else "false"
    if data_type == "Date":
        parsed = datetime.fromisoformat(value).date()
        return f"#date({parsed.year}, {parsed.month}, {parsed.day})"
    return m_text(value)


def parse_measures() -> list[tuple[str, str, str, str]]:
    lines = (PACKAGE / "POWER_BI_MEASURES.dax").read_text(encoding="utf-8").splitlines()
    measures: list[tuple[str, str, str, str]] = []
    index = 0
    while index < len(lines):
        match = re.match(r"// DAX\d+ \| Folder: (.+)", lines[index])
        if not match:
            index += 1
            continue
        folder = match.group(1).strip()
        index += 1
        while index < len(lines) and (not lines[index].strip() or lines[index].lstrip().startswith("//")):
            index += 1
        name = lines[index].rsplit("=", 1)[0].strip()
        index += 1
        expression: list[str] = []
        while index < len(lines) and not lines[index].startswith("// Format:"):
            expression.append(lines[index])
            index += 1
        fmt = lines[index].split(":", 1)[1].strip() if index < len(lines) else "General"
        measures.append((name, "\n".join(expression).strip(), folder, fmt))
        index += 1
    measures.append(
        (
            "Selected Provider Category Value",
            'VAR Metric = SELECTEDVALUE(\'DimMetric\'[MetricKey]) RETURN IF(Metric IN {"PM006", "PM007", "PM008", "PM009"}, MAX(\'FactProviderMeasurement\'[MetricValue]), BLANK())',
            "Provider",
            "#,##0",
        )
    )
    return measures


def table_tmdl(table: str, rows: list[dict[str, str]], types: dict[tuple[str, str], str]) -> str:
    headers = list(rows[0])
    out = [f"table {table}"]
    for column in headers:
        declared = types[(table, column)]
        tabular_type, _ = TYPE_MAP[declared]
        out += ["", f"\tcolumn {quote_ident(column)}", f"\t\tdataType: {tabular_type}"]
        if declared == "Date":
            out.append("\t\tformatString: Short Date")
        elif declared == "Whole number":
            out.append("\t\tformatString: #,##0")
        out.append("\t\tsummarizeBy: none")
        out.append(f"\t\tsourceColumn: {column}")
        if (table, column) in SORT_BY:
            out.append(f"\t\tsortByColumn: {SORT_BY[(table, column)]}")
        if column.endswith("Key") or "Order" in column or column in {"SourceArtifactKey", "DisclosureClass", "SourceClass", "FormatString"}:
            out.append("\t\tisHidden: true")

    columns = ", ".join(f"{quote_ident(h)} = {TYPE_MAP[types[(table, h)]][1]}" for h in headers)
    values = []
    for row in rows:
        values.append("{" + ", ".join(m_value(row[h], types[(table, h)]) for h in headers) + "}")
    source = ["let", f"    Source = #table(type table [{columns}], {{"]
    source += ["        " + value + ("," if i < len(values) - 1 else "") for i, value in enumerate(values)]
    source += ["    })", "in", "    Source"]
    out += ["", f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource ="]
    out.extend("\t\t\t\t" + line for line in source)
    out += ["", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def measures_tmdl() -> str:
    out = [
        "table 'Dashboard Measures'",
        "",
        "\tcolumn Placeholder",
        "\t\tdataType: int64",
        "\t\tformatString: 0",
        "\t\tsummarizeBy: none",
        "\t\tsourceColumn: Placeholder",
        "\t\tisHidden: true",
    ]
    for name, expression, folder, fmt in parse_measures():
        compact_expression = " ".join(line.strip() for line in expression.splitlines())
        out += ["", f"\tmeasure {quote_ident(name)} = {compact_expression}"]
        out.append(f"\t\tdisplayFolder: {folder}")
        if fmt and fmt != "General":
            out.append(f"\t\tformatString: {fmt}")
    out += [
        "",
        "\tpartition 'Dashboard Measures' = m",
        "\t\tmode: import",
        "\t\tsource = #table(type table [Placeholder = Int64.Type], {{1}})",
        "",
        "\tannotation PBI_ResultType = Table",
        "",
    ]
    return "\n".join(out)


def build_model() -> None:
    types = dictionary()
    table_dir = MODEL / "definition" / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        rows = read_csv(DATA / f"{table}.csv")
        (table_dir / f"{table}.tmdl").write_text(table_tmdl(table, rows, types), encoding="utf-8")
    (table_dir / "Dashboard Measures.tmdl").write_text(measures_tmdl(), encoding="utf-8")

    refs = TABLES + ["Dashboard Measures"]
    model = [
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures",
        "\tsourceQueryCulture: en-US",
        "\tvalueFilterBehavior: independent",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        "annotation __PBI_TimeIntelligenceEnabled = 0",
        "annotation PBI_QueryOrder = " + json.dumps(refs),
        "annotation PBI_ProTooling = [\"DevMode\"]",
        "",
    ]
    model += [f"ref table {quote_ident(name)}" for name in refs]
    model += ["", "ref cultureInfo en-US", ""]
    (MODEL / "definition" / "model.tmdl").write_text("\n".join(model), encoding="utf-8")

    rel = []
    for name, source, target in RELATIONSHIPS:
        rel += [f"relationship {name}", f"\tfromColumn: {source}", f"\ttoColumn: {target}", ""]
    (MODEL / "definition" / "relationships.tmdl").write_text("\n".join(rel), encoding="utf-8")

    (MODEL / "definition" / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1606\n", encoding="utf-8")
    culture_dir = MODEL / "definition" / "cultures"
    culture_dir.mkdir(parents=True, exist_ok=True)
    (culture_dir / "en-US.tmdl").write_text("cultureInfo en-US\n", encoding="utf-8")
    (MODEL / "definition.pbism").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
                "version": "4.2",
                "settings": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def stable_id(*parts: object) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]


def column(entity: str, prop: str, active: bool | None = None) -> dict:
    projection = {
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
    }
    if active is not None:
        projection["active"] = active
    return projection


def measure(name: str) -> dict:
    return {
        "field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Dashboard Measures"}}, "Property": name}},
        "queryRef": f"Dashboard Measures.{name}",
        "nativeQueryRef": name,
    }


def aggregate(entity: str, prop: str, function: int = 0) -> dict:
    label = "Sum" if function == 0 else "Count"
    return {
        "field": {
            "Aggregation": {
                "Expression": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
                "Function": function,
            }
        },
        "queryRef": f"{label}({entity}.{prop})",
        "nativeQueryRef": f"{label} of {prop}",
    }


def title_objects(title: str | None) -> dict | None:
    if not title:
        return None
    return {"title": [{"properties": {"text": {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}}}}]}


def data_visual(page: str, key: str, visual_type: str, x: int, y: int, w: int, h: int, query_state: dict, title: str | None = None, objects: dict | None = None, z: int = 0) -> tuple[str, dict]:
    name = stable_id(page, key)
    visual = {"visualType": visual_type, "query": {"queryState": query_state}, "drillFilterOtherVisuals": True}
    if objects:
        visual["objects"] = objects
    container = title_objects(title)
    if container:
        visual["visualContainerObjects"] = container
    return name, {
        "$schema": SCHEMA_VISUAL,
        "name": name,
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": visual,
        "filterConfig": {"filters": []},
    }


def textbox(page: str, key: str, text: str, x: int, y: int, w: int, h: int, size: str = "10pt", color: str = "#1F2937", bold: bool = False, z: int = 0) -> tuple[str, dict]:
    name = stable_id(page, key)
    style = {"fontFamily": "Segoe UI", "fontSize": size, "color": color}
    if bold:
        style["fontWeight"] = "bold"
    return name, {
        "$schema": SCHEMA_VISUAL,
        "name": name,
        "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": text, "textStyle": style}]}]}}]},
            "drillFilterOtherVisuals": True,
        },
    }


def card(page: str, key: str, measure_name: str, x: int, y: int, w: int, h: int, title: str) -> tuple[str, dict]:
    # Current Power BI cards reserve extra internal space. This minimum keeps
    # category labels visible at both Fit-to-page and normal editing zoom.
    h = max(h, 92)
    literal = lambda value: {"expr": {"Literal": {"Value": value}}}
    selector = {"id": "default"}
    objects = {
        "value": [{"properties": {"fontSize": literal("22D"), "bold": literal("true")}, "selector": selector}],
        "label": [{"properties": {"show": literal("true"), "text": literal("'" + title.replace("'", "''") + "'"), "fontSize": literal("10D")}, "selector": selector}],
        "outline": [{"properties": {"show": literal("false")}, "selector": selector}],
    }
    return data_visual(page, key, "cardVisual", x, y, w, h, {"Data": {"projections": [measure(measure_name)]}}, objects=objects)


def slicer(page: str, key: str, entity: str, prop: str, x: int, y: int, w: int, h: int, title: str) -> tuple[str, dict]:
    objects = {"data": [{"properties": {"mode": {"expr": {"Literal": {"Value": "'Dropdown'"}}}}}]}
    return data_visual(page, key, "slicer", x, y, w, h, {"Values": {"projections": [column(entity, prop, True)]}}, title, objects)


def table(page: str, key: str, fields: list[tuple[str, str]], x: int, y: int, w: int, h: int, title: str) -> tuple[str, dict]:
    projections = [measure(name) if entity == "measure" else column(entity, name) for entity, name in fields]
    return data_visual(page, key, "tableEx", x, y, w, h, {"Values": {"projections": projections}}, title)


def matrix(page: str, key: str, rows: list[tuple[str, str]], columns: list[tuple[str, str]], values: list[tuple[str, str, int] | str], x: int, y: int, w: int, h: int, title: str) -> tuple[str, dict]:
    state = {"Rows": {"projections": [column(*field) for field in rows]}}
    if columns:
        state["Columns"] = {"projections": [column(*field) for field in columns]}
    state["Values"] = {"projections": [measure(v) if isinstance(v, str) else aggregate(*v) for v in values]}
    return data_visual(page, key, "pivotTable", x, y, w, h, state, title)


def bar(page: str, key: str, category: tuple[str, str], values: list[tuple[str, str, int] | str], x: int, y: int, w: int, h: int, title: str, visual_type: str = "clusteredBarChart") -> tuple[str, dict]:
    state = {
        "Category": {"projections": [column(*category, True)]},
        "Y": {"projections": [measure(v) if isinstance(v, str) else aggregate(*v) for v in values]},
    }
    return data_visual(page, key, visual_type, x, y, w, h, state, title)


def static_model_status() -> str:
    rows = [r for r in read_csv(DATA / "FactAnalyticalStatus.csv") if r["StageKey"] == "S04"]
    lines = ["MODEL FAMILY  |  STATUS  |  INDEPENDENT AUDIT  |  NEXT ACTION"]
    for row in rows:
        lines.append(f"{row['ComponentName']}  |  {row['ComponentStatus']}  |  {row['IndependentAuditStatus']}  |  {row['NextAction']}")
    return "\n".join(lines)


def page_frame(page: str, title: str, subtitle: str, number: int, visuals: list[tuple[str, dict]]) -> None:
    visuals += [
        textbox(page, "title", title, 24, 6, 1232, 48, "20pt", "#1F2937", True, 0),
        textbox(page, "subtitle", subtitle, 24, 54, 1232, 24, "9pt", "#4B5563", False, 1),
        textbox(page, "footer", f"{FOOTER}  |  Page {number} of 7 — use the report tabs below to navigate.", 24, 642, 1232, 36, "8pt", "#6B7280", False, 99),
    ]


def build_pages() -> list[tuple[str, str, list[tuple[str, dict]]]]:
    pages: list[tuple[str, str, list[tuple[str, dict]]]] = []

    p, v = "executive", []
    page_frame(p, "Florida Emergency Department: Production Data Engineering and Research Analytics", "Public-safe portfolio dashboard | Status checkpoint: Aug 9, 2026", 1, v)
    v += [
        card(p, "P1V03", "Total Validated Encounters", 24, 92, 292, 92, "Validated encounter records"),
        card(p, "P1V04", "Completed Quarterly Partitions", 332, 92, 292, 92, "Quarterly partitions"),
        card(p, "P1V05", "Standardized Encounter Fields", 640, 92, 292, 92, "Standardized fields"),
        card(p, "P1V06", "Schema Families", 948, 92, 308, 92, "Schema families"),
        textbox(p, "P1V07", "AUTHORIZED SOURCES  →  SCHEMA VALIDATION  →  STANDARDIZED FACTS + BRIDGES  →  INDEPENDENT QA  →  PROVIDER V2 + COHORTS  →  ANALYSIS", 24, 206, 1232, 78, "12pt", "#1F4E79", True, 10),
        bar(p, "P1V08", ("FactAnalyticalStatus", "ComponentStatus"), [("FactAnalyticalStatus", "AnalyticalStatusKey", 5)], 24, 310, 590, 250, "Components by current status"),
        textbox(p, "P1V09", f"CURRENT CONTROLLED STATUS\n{STATUS_TEXT}", 638, 310, 618, 250, "15pt", "#1F2937", True, 15),
        textbox(p, "P1V10", "No encounter-level data, provider identifiers, facility identifiers, or numerical concordance estimates are included.", 24, 590, 1232, 48, "11pt", "#B45309", True, 20),
    ]
    pages.append((p, "Executive Overview", v))

    p, v = "coverage", []
    page_frame(p, "Data Coverage and Five-Schema Standardization", "Explicitly preserves the 2009 and 2025 exclusions and does not expose annual encounter counts.", 2, v)
    v += [
        slicer(p, "P2V02", "DimPeriod", "PeriodGroup", 24, 82, 240, 48, "Period group"),
        slicer(p, "P2V03", "DimPeriod", "Year", 280, 82, 170, 48, "Year"),
        card(p, "P2V04", "Partition Reconciliation %", 466, 82, 238, 72, "Reconciliation"),
        card(p, "P2V05", "Completed Quarterly Partitions", 720, 82, 238, 72, "Available quarters"),
        card(p, "P2V06", "Excluded Quarter Count", 974, 82, 282, 72, "Excluded quarters"),
        bar(p, "P2V07", ("DimPeriod", "Year"), [("FactPartitionStatus", "AvailableFlag", 0)], 24, 174, 760, 216, "Available quarters by year", "clusteredColumnChart"),
        matrix(p, "P2V08", [("DimPeriod", "Year")], [("DimPeriod", "QuarterLabel")], [("FactPartitionStatus", "AvailableFlag", 0)], 800, 174, 456, 216, "Quarter availability matrix"),
        bar(p, "P2V09", ("DimSchemaFamily", "SchemaFamilyLabel"), [("DimSchemaFamily", "QuarterCount", 0)], 24, 416, 550, 194, "Quarters by schema family"),
        table(p, "P2V10", [("DimSchemaFamily", "SchemaFamilyLabel"), ("DimSchemaFamily", "StartPeriod"), ("DimSchemaFamily", "EndPeriod"), ("DimSchemaFamily", "QuarterCount"), ("DimSchemaFamily", "DiagnosisEra")], 590, 416, 666, 194, "Schema-family boundaries"),
    ]
    pages.append((p, "Coverage & Standardization", v))

    p, v = "enhancements", []
    page_frame(p, "Clinical Decoding and Visit-Level Enhancements", "Implemented, proxy-only, and structurally unavailable measures are shown separately so missing concepts are never fabricated.", 3, v)
    v += [
        card(p, "P3V02", "Implemented Enhancements", 24, 82, 290, 78, "Implemented"),
        card(p, "P3V03", "Proxy-Only Enhancements", 330, 82, 290, 78, "Proxy only"),
        card(p, "P3V04", "Structurally Unavailable Measures", 636, 82, 290, 78, "Structurally unavailable"),
        card(p, "P3V05", "Enhancement Count", 942, 82, 314, 78, "Total documented items"),
        bar(p, "P3V06", ("FactEnhancementCoverage", "ImplementationStatus"), [("FactEnhancementCoverage", "EnhancementKey", 5)], 24, 184, 450, 204, "Enhancements by implementation status"),
        table(p, "P3V07", [("DimCodingMap", "SourceCodeSystem"), ("DimCodingMap", "ApplicablePeriod"), ("DimCodingMap", "TargetGrouping"), ("DimCodingMap", "Guardrail")], 490, 184, 766, 204, "Coding and grouping map"),
        table(p, "P3V08", [("DimClinicalDomain", "ClinicalDomainName"), ("FactEnhancementCoverage", "EnhancementName"), ("FactEnhancementCoverage", "ImplementationStatus"), ("FactEnhancementCoverage", "AvailabilityScope"), ("FactEnhancementCoverage", "InterpretationGuardrail")], 24, 414, 1232, 210, "Enhancement availability and guardrails"),
    ]
    pages.append((p, "Clinical & Visit Enhancements", v))

    p, v = "provider", []
    page_frame(p, "Provider and Facility Measurement", "Provider master v2 corrects measurement and coverage without redefining the frozen analytical contrasts.", 4, v)
    v += [
        card(p, "P4V02", "Provider Master V2 NPIs", 24, 82, 230, 82, "Provider master v2 NPIs"),
        card(p, "P4V03", "ED-Observed NPIs", 270, 82, 230, 82, "ED-observed NPIs"),
        card(p, "P4V04", "Newly Added ED-Observed NPIs", 516, 82, 230, 82, "Newly added NPIs"),
        card(p, "P4V05", "Facility Dimension Rows", 762, 82, 230, 82, "Facility dimension"),
        card(p, "P4V06", "Organizational NPIs Classified as Physicians", 1008, 82, 248, 82, "Organizations called physicians"),
        bar(p, "P4V07", ("DimMetric", "MetricName"), ["Selected Provider Category Value"], 24, 188, 560, 220, "Selected ED-observed provider categories — not a complete distribution"),
        table(p, "P4V08", [("DimMetric", "MetricName"), ("FactProviderMeasurement", "MetricValue"), ("FactProviderMeasurement", "MeasurementScope"), ("FactProviderMeasurement", "MetricStatus")], 600, 188, 656, 220, "Provider measurement controls"),
        textbox(p, "P4V09", "RACE MEASUREMENT\nProbabilistic full-name Bayesian inference using official wru v2.0.0 likelihoods; Florida physician prior primary; national prior sensitivity; no residential geography; not BISG; not self-reported identity.", 24, 438, 394, 170, "9pt", "#1F4E79", True, 20),
        textbox(p, "P4V10", "GENDER MEASUREMENT\nRecorded NPPES/CMS binary administrative categories in the primary definition. These current-source fields are not guaranteed to represent self-identified gender identity.", 434, 438, 394, 170, "9pt", "#B45309", True, 21),
        textbox(p, "P4V11", "FACILITY MEASUREMENT\nOne row per state facility identifier with name/Medicare histories and controlled current enrichments. Current affiliation is not treated as historical employment or privileges.", 844, 438, 412, 170, "9pt", "#4B5563", True, 22),
    ]
    pages.append((p, "Provider & Facility Measurement", v))

    p, v = "cohort", []
    page_frame(p, "Cohort Construction and Analytical Design", "Primary and historical cohorts remain separate; all reported effects are observational associations.", 5, v)
    v += [
        card(p, "P5V02", "Primary Cohort Rows", 24, 82, 300, 82, "Primary cohort rows"),
        card(p, "P5V03", "Historical Cohort Rows", 340, 82, 300, 82, "Historical cohort rows"),
        textbox(p, "P5V04", "PRIMARY: 2010–2024, direct validated attending NPIs.\nHISTORICAL: 2005–2008, unique Florida-license linkage only.\nThe periods are never silently pooled.", 656, 82, 600, 82, "10pt", "#1F4E79", True, 10),
        table(p, "P5V05", [("DimModelSpec", "ModelLabel"), ("DimModelSpec", "PlainLanguageDefinition"), ("DimModelSpec", "FixedEffectsSummary"), ("DimModelSpec", "ClusteringSummary")], 24, 184, 1232, 176, "M1–M3 model progression"),
        textbox(p, "P5V06", static_model_status(), 24, 386, 720, 216, "8pt", "#1F2937", False, 15),
        textbox(p, "P5V07", "FROZEN OUTCOMES AND INTERPRETATION\nCharges, disposition/admission-related measures where supported, length of stay, treatment intensity, utilization, and separate AMI/Greenwood analyses. Physician race is probabilistic; hard labels are sensitivities. Results are observational associations, not causal effects.", 760, 386, 496, 216, "10pt", "#B45309", True, 16),
    ]
    pages.append((p, "Cohort & Analytical Design", v))

    p, v = "validation", []
    page_frame(p, "Validation, Reconciliation, and Reproducibility", "Every published number is restricted to validated project metadata or an explicitly fictional deterministic demonstration.", 6, v)
    v += [
        card(p, "P6V02", "Validation Controls", 24, 82, 280, 78, "Validation controls"),
        card(p, "P6V03", "Validation Pass %", 320, 82, 280, 78, "Validation pass rate"),
        card(p, "P6V04", "Synthetic Input Rows", 616, 82, 280, 78, "Synthetic input rows"),
        card(p, "P6V05", "Synthetic Output Rows", 912, 82, 344, 78, "Synthetic output rows"),
        bar(p, "P6V06", ("DimProjectStage", "StageName"), [("FactValidationStatus", "ValidationKey", 5)], 24, 184, 470, 206, "Checks by project stage"),
        bar(p, "P6V07", ("FactSyntheticDemonstration", "Category"), ["Synthetic Input Rows", "Synthetic Output Rows"], 510, 184, 746, 206, "Synthetic schema reconciliation — fictional", "clusteredColumnChart"),
        table(p, "P6V08", [("DimProjectStage", "StageName"), ("FactValidationStatus", "ValidationCheck"), ("FactValidationStatus", "ValidationStatus"), ("FactValidationStatus", "EvidenceSummary")], 24, 416, 1232, 210, "High-value validation ledger"),
    ]
    pages.append((p, "Validation & Reproducibility", v))

    p, v = "handoff", []
    page_frame(p, "Completion, Safe Pause, and Handoff", "A restart-safe continuation surface: completed work is preserved, pending work is explicit, and Phase 1 remains immutable.", 7, v)
    v += [
        card(p, "P7V02", "Completed Components", 24, 82, 280, 78, "Completed components"),
        card(p, "P7V03", "Pending Components", 320, 82, 280, 78, "Pending components"),
        card(p, "P7V04", "Deferred Components", 616, 82, 280, 78, "Deferred components"),
        textbox(p, "P7V05", f"CONTROLLED PROJECT STATUS\n{STATUS_TEXT}", 912, 82, 344, 126, "10pt", "#1F2937", True, 12),
        bar(p, "P7V06", ("FactAnalyticalStatus", "ComponentStatus"), [("FactAnalyticalStatus", "AnalyticalStatusKey", 5)], 24, 184, 400, 204, "Components by status"),
        table(p, "P7V07", [("DimProjectStage", "StageName"), ("FactAnalyticalStatus", "ComponentName"), ("FactAnalyticalStatus", "ComponentStatus"), ("FactAnalyticalStatus", "IndependentAuditStatus"), ("FactAnalyticalStatus", "NextAction")], 440, 222, 816, 326, "Continuation ledger"),
        textbox(p, "P7V08", "VERIFIED RESTART POINT\nGender M2 has no committed design or outcome columns and must restart from its beginning after validating checkpoint hashes. Phase 1 must remain immutable.", 24, 414, 400, 134, "10pt", "#B45309", True, 16),
        textbox(p, "P7V09", "This dashboard documents engineering, measurement, validation, and work status. It does not report concordance coefficients, confidence intervals, p-values, q-values, or causal treatment-outcome conclusions.", 24, 574, 1232, 64, "10pt", "#1F4E79", True, 17),
    ]
    pages.append((p, "Completion & Handoff", v))
    return pages


def build_report() -> None:
    pages_root = REPORT / "definition" / "pages"
    pages_root.mkdir(parents=True, exist_ok=True)
    order = []
    for logical, display_name, visuals in build_pages():
        page_name = stable_id("page", logical)
        order.append(page_name)
        visual_root = pages_root / page_name / "visuals"
        visual_root.mkdir(parents=True, exist_ok=True)
        page_json = {
            "$schema": SCHEMA_PAGE,
            "name": page_name,
            "displayName": display_name,
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        }
        (visual_root.parent / "page.json").write_text(json.dumps(page_json, indent=2), encoding="utf-8")
        for visual_name, visual_json in visuals:
            directory = visual_root / visual_name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "visual.json").write_text(json.dumps(visual_json, indent=2, ensure_ascii=False), encoding="utf-8")

    pages_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": order,
        "activePageName": order[0],
    }
    (pages_root / "pages.json").write_text(json.dumps(pages_json, indent=2), encoding="utf-8")

    registered = REPORT / "StaticResources" / "RegisteredResources"
    base = REPORT / "StaticResources" / "SharedResources" / "BaseThemes"
    registered.mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(THEME_SOURCE, registered / "FloridaEDResearchPortfolio.json")
    shutil.copyfile(BASE_THEME_SOURCE, base / "CY26SU07.json")
    report_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY26SU07", "reportVersionAtImport": {"visual": "2.11.0", "report": "3.4.0", "page": "2.3.1"}, "type": "SharedResources"},
            "customTheme": {"name": "FloridaEDResearchPortfolio", "reportVersionAtImport": {"visual": "2.11.0", "report": "3.4.0", "page": "2.3.1"}, "type": "RegisteredResources"},
        },
        "objects": {"section": [{"properties": {"verticalAlignment": {"expr": {"Literal": {"Value": "'Top'"}}}}}]},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources", "items": [{"name": "CY26SU07", "path": "BaseThemes/CY26SU07.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": "FloridaEDResearchPortfolio", "path": "FloridaEDResearchPortfolio", "type": "CustomTheme"}]},
        ],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "None", "defaultDrillFilterOtherVisuals": False, "allowChangeFilterTypes": True, "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
    }
    definition = REPORT / "definition"
    (definition / "report.json").write_text(json.dumps(report_json, indent=2), encoding="utf-8")
    (definition / "version.json").write_text(
        json.dumps({"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}, indent=2),
        encoding="utf-8",
    )
    (REPORT / "definition.pbir").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                "version": "4.0",
                "datasetReference": {"byPath": {"path": f"../{PROJECT}.SemanticModel"}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def build_project() -> None:
    if PROJECT_ROOT.exists():
        resolved = PROJECT_ROOT.resolve()
        forbidden = {Path(resolved.anchor).resolve(), Path.home().resolve(), PACKAGE.resolve()}
        if resolved in forbidden or len(resolved.parts) < 4:
            raise RuntimeError(f"Refusing to replace unsafe build path: {resolved}")
        shutil.rmtree(PROJECT_ROOT)
    PROJECT_ROOT.mkdir(parents=True)
    build_model()
    build_report()
    (PROJECT_ROOT / f"{PROJECT}.pbip").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [{"report": {"path": f"{PROJECT}.Report"}}],
                "settings": {"enableAutoRecovery": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (PROJECT_ROOT / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
    print(json.dumps({"project": str(PROJECT_ROOT / f"{PROJECT}.pbip"), "tables": len(TABLES) + 1, "relationships": len(RELATIONSHIPS), "measures": len(parse_measures()), "pages": 7}, indent=2))


if __name__ == "__main__":
    build_project()
