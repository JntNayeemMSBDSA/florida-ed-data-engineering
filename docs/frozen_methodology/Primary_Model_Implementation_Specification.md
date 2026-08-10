# Primary Model Implementation Specification

**Project:** Florida Emergency Department physician–patient concordance analysis  
**Specification version:** 1.0  
**Locked before estimation:** 2026-07-26  
**Status:** Operational supplement to the frozen Statistical Analysis Plan  

This document resolves computational details that were intentionally left at a
higher level in the frozen Statistical Analysis Plan. It was written before
estimating any adjusted concordance effects. It does not replace the SAP.

## Primary analytic samples

The primary racial-concordance analysis uses 2010–2024 visits meeting all of
the following:

- attending physician linked by a direct, validated NPI;
- physician-master match and MD/DO flag;
- patient recorded as non-Hispanic Black or non-Hispanic White;
- attending physician official-dictionary Bayesian full-name analytical proxy
  classified as Black or White;
- maximum posterior probability at least 0.50; and
- the outcome being estimated is observed: valid clock-based ED length of
  stay from 0 through 168 hours for the LOS model, or nonnegative
  facility-reported charges standardized to 2024 dollars with the all-items
  CPI-U for the charge model.

The confirmatory analyses handle outcome missingness separately, as required
by the frozen SAP. An encounter with observed LOS is not excluded because its
charge is missing, and an encounter with observed charge is not excluded
because its LOS is missing. The originally implemented common complete-LOS-
and-charge sample is retained and clearly labeled as a robustness analysis,
not the controlling confirmatory estimate.

The primary recorded patient sex–physician gender analysis uses direct,
validated attending NPI links; matched MD/DO physicians; binary recorded
patient sex (Female/Male); binary physician gender (Female/Male) recorded in
NPPES or CMS, including the February 2026 NPPES and June 2026 CMS current
snapshots; and the same outcome-specific availability rule. SSA
first-name-imputed physician gender is excluded from the primary cohort and
retained as an expanded measurement sensitivity. The common-sample secondary
analysis includes an exact M2 subset re-estimation that excludes NPIs with
disagreeing recorded NPPES and CMS categories.

The physician race/ethnicity measure is an official-dictionary Bayesian
full-name analytical proxy without residential geography, not BISG and not
self-reported identity. Patient sex and physician gender are not treated as
measures of gender identity.

## Exposure coding and requested contrast

For race models:

- `patient_black = 1` for a non-Hispanic Black patient and 0 for a
  non-Hispanic White patient;
- `physician_black_proxy = 1` for a physician classified as Black by the
  prespecified full-name posterior model and `0` for White; and
- `race_interaction = patient_black * physician_black_proxy`.

The coefficient on `race_interaction` is exactly:

`black_black - black_white - white_black + white_white`

where the physician category is written first.

For recorded sex–physician gender models, the analogous variables are patient
Female, physician Female, and their product. The interaction coefficient is:

`female_female - female_male - male_female + male_male`

## Covariate implementation

Age is median-imputed within the analytic cohort with a separate missing flag.
Its functional form is a linear spline containing age and positive-part terms
at 18, 45, 65, and 80 years. Values outside 0–120 are set to missing before
imputation.

Years since medical school is restricted to 0–80, median-imputed with a
separate missing flag, and represented by a linear term plus positive-part
terms at 10, 20, and 30 years.

Categorical covariates use an explicit missing/unknown category and a
deterministically selected reference level recorded in each model manifest.
The covariates are:

- patient age spline and missing flag;
- recorded patient sex in race models;
- patient race/ethnicity categories in sex/gender models;
- payer group;
- patient ZIP rurality;
- weekend arrival;
- off-hours arrival;
- arrival time band;
- individual Elixhauser condition indicators and the Elixhauser count;
- attending ED-specialist flag;
- physician experience spline and missing flag; and
- log of attending physician quarterly ED volume.

Procedures, disposition, and charge components are not included as covariates
when they are outcomes or plausible mediators.

## Model sequence

1. **Unadjusted:** saturated four-cell means and the prespecified contrast.
2. **Patient-adjusted:** ordinary least squares with an intercept, exposure
   main effects and interaction, and patient/visit covariates.
3. **Fully adjusted:** ordinary least squares after absorbing
   facility-by-year-quarter and principal clinical-category fixed effects,
   with patient/visit and measured physician covariates.
4. **Physician fixed effect:** ordinary least squares after absorbing
   attending physician, facility-by-year-quarter, and principal
   clinical-category fixed effects. Time-invariant physician main effects are
   omitted because they are absorbed. The interaction remains identified from
   patient composition within physician.

The same sequence is used for race and recorded sex–physician gender.

## Fixed-effect computation and inference

Fixed effects are absorbed using alternating projections implemented by the
Rust backend in `pyfixest`. Convergence tolerance is `1e-8`; the maximum
iteration count is 10,000. Regressions are then solved from double-precision
within-transformed cross-products. Rank and condition diagnostics are saved.

Confirmatory inference uses a two-way cluster-robust sandwich covariance for
attending physician and facility. The physician–facility intersection term is
subtracted under the Cameron–Gelbach–Miller inclusion–exclusion formula.
Finite-cluster CRV1 corrections are applied and their exact cluster counts are
saved. A facility-cluster wild-score bootstrap is a sensitivity analysis for
the primary interaction coefficient.

Because the full design contains many adjustment coefficients, machine-readable
output contains all point estimates and selected covariance blocks for the
exposure main effects and interaction. This is sufficient to reproduce every
reported concordance contrast. Model residualization and score computations
are performed on the full eligible data, never on a sample.

## Gate binding, audit checkpoints, and storage

Every model-matrix manifest stores the SHA-256 hashes and absolute paths of the
provider-measurement gate and cohort-validation gate. Matrix construction,
estimation, postmodel sensitivity scripts, and independent auditors fail closed
if either live gate is missing, no longer reports `PASS`, or no longer matches
the stored hash.

Large model matrices are processed sequentially. Each matrix is constructed,
estimated, independently audited, and checkpointed before its generated
memory-mapped design files and exact model-scratch directory may be compacted.
Compaction requires an explicit execution flag and revalidates the gate hashes,
matrix manifest, result manifest, and complete result-file inventory.
Compaction never removes result tables, diagnostic manifests, audit
checkpoints, code, documentation, or the immutable Phase 1 encounter release.

The common primary matrices are retained until all common-sample secondary
models—including probability, heterogeneity, classified-presentation, payer,
intersectional, multiple-imputation, negative-control, nonlinear,
leave-one-year-out, and exact subset analyses—pass a separate postmodel
artifact audit. For each
confirmatory outcome, the five largest facility-level first-order influence
scores select candidates for exact M2 re-estimation after facility deletion,
subset-specific fixed-effect re-demeaning, and iterative singleton removal.
Outcome-specific
confirmatory and cohort-definition sensitivity matrices are independently
audited and compacted one at a time.

The presentation analysis has two deliberately distinct specifications. The
broad secondary model compares visit-level symptom/sign coding with all other
eligible presentations. A stricter exploratory sensitivity uses the versioned
clinical-category review table, removes every ambiguous/mixed category, and
exactly re-demeans the M2 design within the remaining higher- and
lower-uncertainty proxy groups. The matrix manifest binds the review-table
version and SHA-256 hash so this sensitivity cannot silently reuse a stale
classification.

## Interpretation gates

- Effects are observational associations.
- Statistical significance is not interpreted as clinical importance.
- Both absolute effects and effects relative to the eligible outcome mean are
  reported.
- Holm adjustment is applied across the two confirmatory primary outcomes.
- Secondary families use Benjamini–Hochberg adjustment.
- The AMI analysis remains gated on separate definition and benchmark
  validation.
- Subjectivity and treatment-discretion classifications remain provisional
  and evidence-informed until clinician review.
