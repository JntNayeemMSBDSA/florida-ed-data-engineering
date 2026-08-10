# Historical 2005-2008 provider-v2 checkpoint

Generated: 2026-07-26T19:05:08.603787+00:00

## Decision

**PASS**. Historical estimation authorized:
**True**.

This checkpoint is estimate-blind. It did not read model-result files.
The 2005-2008 cohort remains a separate historical sensitivity and is never
silently pooled with the 2010-2024 primary cohort.

## Independent reconciliation

- Expected and reconciled partitions: 16
- Phase 1 encounter rows: 23,304,846
- Historical provider-v2 rows: 23,304,846
- Missing Phase 1 keys: 0
- Extra historical keys: 0
- Selected source-field mismatches: 0
- Non-null or asserted hourly-LOS errors: 0
- Direct-NPI rows in the historical era: 0
- Invalid organizational/non-MD/DO physician eligibility rows:
  0

Every quarter is independently compared with the immutable Phase 1 fact file,
including exact row and encounter-key preservation, selected source fields,
license linkage, provider-v2 MD/DO eligibility, full-name race eligibility,
recorded patient sex-physician gender eligibility, and strict/broad AMI counts.
Checksums are recomputed for Phase 1 facts and historical outputs.

## Provider-v2 coverage by year

|   visit_year |   phase1_encounters |   license_resolved_encounters |   provider_v2_matched_encounters |   provider_v2_md_do_encounters |   race_t50_encounters |   sex_gender_encounters |   license_resolved_unique_npi |   provider_v2_md_do_unique_npi |   race_t50_unique_npi |   sex_gender_unique_npi |   license_resolved_visit_pct |   provider_v2_md_do_visit_pct |   race_t50_visit_pct |   sex_gender_visit_pct |
|-------------:|--------------------:|------------------------------:|---------------------------------:|-------------------------------:|----------------------:|------------------------:|------------------------------:|-------------------------------:|----------------------:|------------------------:|-----------------------------:|------------------------------:|---------------------:|-----------------------:|
|         2005 |         5.74838e+06 |                   3.31442e+06 |                      3.31442e+06 |                    3.2119e+06  |           1.95351e+06 |             3.21186e+06 |                          7103 |                           6282 |                  3881 |                    6282 |                      57.6583 |                       55.875  |              33.9837 |                55.8743 |
|         2006 |         5.81888e+06 |                   3.47024e+06 |                      3.47024e+06 |                    3.36096e+06 |           1.99779e+06 |             3.36095e+06 |                          7071 |                           6268 |                  3793 |                    6268 |                      59.6376 |                       57.7596 |              34.3329 |                57.7594 |
|         2007 |         5.79223e+06 |                   3.50951e+06 |                      3.50951e+06 |                    3.39247e+06 |           1.99498e+06 |             3.39247e+06 |                          6959 |                           6215 |                  3764 |                    6215 |                      60.59   |                       58.5694 |              34.4424 |                58.5694 |
|         2008 |         5.94537e+06 |                   3.59628e+06 |                      3.59628e+06 |                    3.47838e+06 |           2.00495e+06 |             3.47838e+06 |                          7538 |                           6772 |                  4039 |                    6772 |                      60.4887 |                       58.5057 |              33.7229 |                58.5057 |

The full pre-linkage encounter universe is retained. Analytic cohorts are
defined by flags, so linkage loss is visible and can be evaluated rather than
being introduced through an inner join.

## LOS policy

Historical `length_of_stay_days` is retained as a day-level measure.
`ed_discharge_hour`, `los_hours_clock_raw`, and
`los_hours_primary_0_168` are structurally unavailable and must remain null.
No day-to-hour conversion is permitted.

## Measurement limitations

- Historical physician linkage is a unique Florida-license-to-NPI crosswalk,
  not a direct source NPI.
- Provider master v2 uses current registry snapshots. They do not establish
  historical employment, hospital privilege, specialty, or activity.
- Physician race is an algorithm-inferred full-name probability proxy without
  residential geography. It is not BISG and not self-identified race.
- Patient race and ethnicity are historically combined. The code-3/code-4
  comparison is a separate sensitivity and is not measurement-equivalent to
  modern separate race and ethnicity fields.
- Recorded patient sex and physician gender categories are administrative
  measurement fields, not measures of gender identity.
- The Greenwood analysis is an ED-only extension, not an inpatient replication.
- Inverse-probability weighting is not treated as an automatic correction:
  physician concordance is structurally unobserved when linkage or physician
  demographics are absent, so observed linkage propensities alone cannot
  establish a missing-at-random identification assumption. The linked versus
  unlinked profiles are preserved for transparent selection assessment.

## Cross-period comparability matrix

| Domain | Variable/outcome | Status | Permitted use | Restriction |
|---|---|---|---|---|
| encounter identity | visit_key and quarter | fully comparable | reconciliation, fixed effects, trends | All 16 partitions must reconcile exactly to Phase 1. |
| patient demographics | age_years and age bands | comparable with missingness checks | covariate and stratification | Do not infer values when age is missing. |
| patient demographics | recorded patient sex | comparable administrative field | sex/gender concordance and covariate | Not a measure of patient gender identity. |
| patient demographics | race/ethnicity | partially comparable | separate code-3 versus code-4 historical sensitivity | Never pool with modern separate race and ethnicity fields; Hispanic historical codes are excluded from the Black/White contrast. |
| provider linkage | attending NPI | not linkage-equivalent | separate historical sensitivity after linkage audit | No direct source NPI in 2005-2008; only unique Florida-license crosswalk links are eligible. |
| provider measurement | MD/DO, clinician type, specialty | partially comparable | eligibility and sensitivity covariates | Current registry attributes are not proof of historical activity, employment, specialty, or privilege. |
| provider measurement | physician full-name race proxy | method-comparable, construct imperfect | probabilistic and threshold sensitivity analyses | Algorithm-inferred name probabilities without geography; not BISG and not self-identified race/ethnicity. |
| provider measurement | physician recorded/inferred gender category | method-comparable, temporal caveat | recorded patient sex-physician gender concordance | Not a measure of historical gender identity. |
| clinical coding | diagnosis and clinical category | conceptually but not code-identical | era-specific adjustment and separate sensitivity | Do not assume ICD-9 and ICD-10 category equivalence. |
| clinical coding | Elixhauser condition flags | partially comparable | era-specific risk adjustment | Use era-appropriate definitions and report version differences. |
| AMI/Greenwood | AMI cohort | conceptually comparable, code-era specific | separate historical ED-only Greenwood extension | Not an inpatient Greenwood replication. |
| outcome | ED mortality | comparable ED disposition measure | binary outcome including historical AMI | Does not capture post-ED inpatient mortality. |
| outcome | routine discharge, transfer, hospice, left care | comparable after code validation | separate historical outcomes | Report outcome-specific nonmissingness and code semantics. |
| outcome | same-facility inpatient admission | not available | none | Do not treat missing as no admission. |
| outcome | length_of_stay_days | partially comparable | historical day-level LOS outcome only | Do not relabel or convert it to clock-hour LOS. |
| outcome | hourly LOS | not comparable | none | Must remain null; no 24-times-days imputation. |
| outcome | procedure counts and treatment intensity | partially comparable | separate historical outcome and within-era comparisons | Coding opportunities and procedure systems differ by era. |
| outcome | reported/component charges | comparable after inflation adjustment with caveats | nominal and CPI-adjusted historical outcome | Charges are not costs or payments; billing practices may change. |
| utilization | 7-day and 30-day revisit | not available | none | Do not impute or interpret missing as no revisit. |
| severity | true triage level | not available | none | E/M proxies may be separately labeled but are not triage. |
| operations | arrival hour, weekend, off-hours | comparable after missingness checks | covariates and stratification | Arrival hour does not make hourly LOS available. |
| facility | facility identifiers and fixed effects | comparable identifiers with facility-history caveats | fixed effects, clustering, within-era trends | Contemporary facility/provider affiliations are not historical employment. |

## Machine-readable evidence

- `qa/historical_provider_v2_pre_estimation_gate.json`
- `qa/historical_provider_v2_phase1_reconciliation.csv`
- `qa/historical_provider_v2_coverage_by_year.csv`
- `qa/historical_provider_v2_coverage_by_clinician_type.csv`
- `qa/historical_provider_v2_linkage_selection_profile.csv`
- `documentation/Historical_2005_2008_Comparability_Matrix.csv`
- `documentation/Historical_2005_2008_Comparability_Matrix.json`
- `documentation/Historical_Provider_V2_Variable_Dictionary.csv`
