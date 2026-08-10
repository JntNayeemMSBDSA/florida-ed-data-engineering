# Historical 2005-2008 provider-v2 track

## Purpose

This track preserves all 16 available 2005-2008 Florida ED quarters as a
separate provider-v2 historical cohort. It supports compatible historical
race-concordance sensitivities and an ED-only AMI/Greenwood extension without
changing or extending the 2010-2024 primary cohort.

## Controlling rules

- Phase 1 is immutable.
- Every Phase 1 historical encounter is retained in the historical checkpoint.
- Provider linkage and analysis eligibility are flags, not row-inclusion rules.
- Historical physician linkage is a unique Florida-license-to-NPI crosswalk,
  not a direct source NPI.
- Organizational NPIs are never physicians; MD/DO, NP, PA, and other
  clinician types remain distinct.
- Patient race and ethnicity have combined historical semantics and are not
  pooled with modern separate fields.
- `length_of_stay_days` may be used as a day-level outcome.
- Hourly LOS is structurally unavailable and is never imputed from days.
- No historical model may run before the 16-quarter reconciliation gate passes.

## Reproducible runner

Run:

```powershell
.\scripts\RUN_HISTORICAL_PROVIDER_V2.ps1 `
  -Python <python-executable> `
  -StartAt build `
  -Threads 12 `
  -MemoryLimit 24GB
```

The runner is resumable by stage: `build`, `validate`, `models`, or `audit`.
Completed partition files are reused only after their size and SHA-256 digest
agree with their success manifest and build-specification version.

## Data

The checkpoint is stored under:

`analysis_data/historical_provider_v2/visit_year=YYYY/visit_quarter=Q/`

Each partition contains `historical_provider_v2_core.parquet` and
`_SUCCESS.json`. The cohort-level build manifest is:

`analysis_data/historical_provider_v2/historical_provider_v2_build_manifest.json`

The Parquet files retain the complete Phase 1 encounter universe and add:

- license-resolution and provider-v2 match flags;
- individual MD/DO eligibility;
- physician entity and clinician type;
- full-name race probabilities under the Florida physician and official wru
  national priors;
- race thresholds at 0.50, 0.70, 0.80, and 0.90;
- recorded patient sex-physician gender eligibility;
- strict and broad principal and any-listed ICD-9-CM AMI flags; and
- explicit structural-unavailability fields for hourly LOS.

## Estimate-blind gate

The controlling gate is:

`qa/historical_provider_v2_pre_estimation_gate.json`

It must report `PASS` and `historical_estimation_authorized: true`. Supporting
evidence includes:

- `qa/historical_provider_v2_phase1_reconciliation.csv`
- `qa/historical_provider_v2_coverage_by_year.csv`
- `qa/historical_provider_v2_coverage_by_clinician_type.csv`
- `qa/historical_provider_v2_linkage_selection_profile.csv`
- `documentation/Historical_2005_2008_Comparability_Matrix.csv`
- `documentation/Historical_2005_2008_Comparability_and_Reconciliation.md`

## Results

Historical race sensitivities:

`results/historical_provider_v2_sensitivity/`

Historical all-diagnosis recorded patient sex-physician gender sensitivities:

`results/historical_provider_v2_sex_gender_sensitivity/`

Historical AMI/Greenwood extension:

`results/historical_provider_v2_ami/`

The independent historical-results audit is:

`qa/independent_historical_results_audit.json`

It must report `PASS` before historical results are released to collaborators.

## Interpretation

These analyses estimate associations in the linked historical population.
Current provider-registry attributes do not prove historical employment,
affiliation, privilege, specialty, activity, or identity. The physician race
measure is a Bayesian full-name probability proxy without residential
geography; it is not BISG and not self-identified race. The AMI analysis is an
ED-only extension and is not an inpatient replication of Greenwood et al.
