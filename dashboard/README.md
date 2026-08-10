# Power BI project-status dashboard

Open [`powerbi_project/Florida_ED_Project_Portfolio_Dashboard.pbip`](powerbi_project/Florida_ED_Project_Portfolio_Dashboard.pbip) in Power BI Desktop.

This is a seven-page engineering, methods, validation, and handoff dashboard. It is deliberately not a scientific-results dashboard and contains no unpublished concordance estimates. Its semantic model contains 15 tables, 8 relationships, and 34 measures; the report contains 76 visuals across these pages:

1. Executive Overview
2. Coverage & Standardization
3. Clinical & Visit Enhancements
4. Provider & Facility Measurement
5. Cohort & Analytical Design
6. Validation & Reproducibility
7. Completion & Handoff

All model tables are embedded from the public-safe CSV files in `dashboard_data/`; no external or restricted data connection is required. The build script is retained to make the project generation auditable. The static validator checks structure, data counts, measures, relationships, Power Query syntax, visual bounds, disclosure language, external-source absence, and the render-QA evidence set.

The final static report is [`powerbi_project/POWER_BI_PROJECT_STATIC_VALIDATION.json`](powerbi_project/POWER_BI_PROJECT_STATIC_VALIDATION.json). The Power BI Desktop render review and seven reference screenshots are in [`dashboard_qa/`](dashboard_qa/).

To rerun the static check from the repository root:

```powershell
$env:FLORIDA_ED_PBI_PROJECT_ROOT = (Resolve-Path '.\dashboard\powerbi_project').Path
python dashboard/support/validate_powerbi_project.py
Remove-Item Env:\FLORIDA_ED_PBI_PROJECT_ROOT
```
