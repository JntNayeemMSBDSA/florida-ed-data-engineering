# Public reproducibility guide

The public reproducibility target is the repository's synthetic demonstration, documentation claims, Power BI project structure, privacy boundary, source provenance, and release inventory. Production estimates cannot be reproduced without restricted data and are intentionally outside this package.

## Environment

Use Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Reproduce the fictional demonstration

```powershell
python synthetic_demo/generate_synthetic_data.py
python synthetic_demo/run_demo_pipeline.py
python -m pytest -q
```

The generator creates 800 fictional rows. The demonstration validates representative standardization and quality-control behavior; it does not recreate production data or estimate concordance effects.

## Validate the dashboard and repository

```powershell
$env:FLORIDA_ED_PBI_PROJECT_ROOT = (Resolve-Path '.\dashboard\powerbi_project').Path
python dashboard/support/validate_powerbi_project.py
Remove-Item Env:\FLORIDA_ED_PBI_PROJECT_ROOT
python scripts/build_repository_inventory.py
python scripts/validate_release_repository.py
```

The checks fail closed on missing required artifacts, hash disagreement, prohibited data types, private paths, identifier-like material in public evidence, broken documentation links, unsubstantiated status claims, or dashboard structural failures.

## Power BI review

Open `dashboard/powerbi_project/Florida_ED_Project_Portfolio_Dashboard.pbip` in Power BI Desktop. It is a source-controlled Power BI Project, not a `.pbix` binary. All dashboard tables are embedded public-safe project metadata. Compare the seven pages with the captures and review record in `dashboard/dashboard_qa/`.

## Expected result

Before publication, the following must all be true:

- the test suite passes;
- dashboard static validation reports 17 of 17 checks passed;
- seven unique render-QA screenshots exist;
- source provenance and repository inventory hashes reconcile;
- privacy/disclosure validation passes;
- the intended Git remote is verified and the working tree is clean;
- the local annotated `READY_TO_PUBLISH_20260810` tag points to the approved release commit.
