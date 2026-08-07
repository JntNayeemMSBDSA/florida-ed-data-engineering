# Synthetic demonstration

This directory exercises a small, deterministic version of the standardization and QA workflow. Every provider, facility, identifier, and encounter is fictional. Provider IDs begin with `SYN-NPI-`; they are labels for the demonstration and are not represented as real clinicians or valid NPIs.

From the repository root:

```bash
python synthetic_demo/generate_synthetic_data.py
python synthetic_demo/run_demo_pipeline.py
```

The generator writes five schema-era CSV inputs plus fictional provider and facility references under `synthetic_demo/generated/`. The pipeline standardizes those layouts, applies the 2015 Q3/Q4 ICD boundary, separates organizations from individual clinician types, adds facility and visit fields, and writes reconciliation and QA summaries under `synthetic_demo/output/`.

This is a teaching fixture, not the production pipeline. It simplifies source parsing, reference dictionaries, provider matching, and clinical grouping. It does not estimate concordance associations, create model matrices, or reproduce any research result. The production code excerpts in `src/` retain the fuller logic but require restricted data and licensed or separately obtained reference files.
