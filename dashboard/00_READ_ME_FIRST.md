# Read this first

## What this package contains

This folder contains a complete, public-safe Power BI build handoff for a seven-page Florida Emergency Department data-engineering and research-analytics portfolio dashboard. It includes 14 import-ready CSV tables, one consolidated Excel import workbook, a documented data model, 33 explicit DAX measures, a theme, a page/visual blueprint, exact click-by-click build instructions, provenance, disclosure controls, automated validation, and a separate final-QA prompt.

## What it does not contain

It contains no encounter-level records, patient identifiers, provider names or NPIs, facility identifiers, purchased source files, model matrices, numerical concordance estimates, confidence intervals, p-values, q-values, or causal treatment-outcome conclusions. It is not the professor handoff, the comprehensive study guide, or the final GitHub release.

No Phase 1 or Phase 2 process was restarted, supervised, or modified. The existing public portfolio, GitHub history, and OneDrive were not changed.

## Controlled project status

Phase 1 complete and independently validated. Phase 2 measurement, cohort construction, historical analyses, and primary race M1-M3 estimation complete; primary gender M1 complete. Remaining primary and sensitivity analyses and the final independent analytical-release audit are pending.

The source portfolio snapshot was older than the verified pause checkpoint. This package uses the August 9 pause checkpoint as the controlling status source while preserving the older repository unchanged.

## Exact order of use

1. Read this file completely.
2. Review DASHBOARD_BLUEPRINT.md for the story and page design.
3. Review POWER_BI_DATA_MODEL.md for tables and relationships.
4. Open POWER_BI_BUILD_CLICKBOOK.md and follow it from the first step.
5. Import dashboard_data/POWER_BI_IMPORT.xlsx; do not import private research files.
6. Use POWER_BI_MEASURES.dax and powerbi_theme.json when instructed.
7. Save the completed PBIX as Florida_ED_Project_Portfolio_Dashboard.pbix in this folder.
8. Run the instructions in POWER_BI_FINAL_QA_PROMPT.txt in a new Codex task.
9. Do not publish until the separate final dashboard QA passes and you explicitly authorize publication.

## File map

- dashboard_data/: 14 UTF-8 CSV tables plus the consolidated Power BI import workbook.
- dashboard_data_dictionary.csv: every table field, type, grain, source, rule, caveat, and intended use.
- POWER_BI_BUILD_CLICKBOOK.md: exact manual build sequence.
- DASHBOARD_BLUEPRINT.md and POWER_BI_VISUAL_SPECIFICATION.csv: page layout and visual contracts.
- POWER_BI_DATA_MODEL.md: relationships, grains, and refresh boundary.
- METRIC_AND_MEASURE_DICTIONARY.csv and POWER_BI_MEASURES.dax: metric definitions and measures.
- POWER_QUERY_TRANSFORMATIONS.md: source and type-handling rules.
- powerbi_theme.json: visual theme.
- DASHBOARD_SOURCE_PROVENANCE.csv: source hashes and extraction decisions.
- PUBLIC_DASHBOARD_DISCLOSURE_AUDIT.json and DASHBOARD_PREPARATION_VALIDATION.json: fail-closed checks.
- DASHBOARD_FILE_MANIFEST.csv and DASHBOARD_FILE_MANIFEST.sha256: package integrity.
- DASHBOARD_QA_CHECKLIST.md and POWER_BI_FINAL_QA_PROMPT.txt: final review workflow.
- NEXT_STEPS_AFTER_DASHBOARD.md: GitHub, OneDrive, professor handoff, and study-guide sequence.
