# Historical 2005-2008 AMI/Greenwood extension

## Scope and interpretation

This is a separately estimated, ED-only historical extension inspired by
Greenwood, Carnahan, and Huang (2018). It is **not** a replication of their
inpatient analysis. The Florida source captures standalone ED encounters and
does not provide inpatient survival after same-hospital admission.

The analysis ran only after the 16-quarter provider-v2 historical
pre-estimation gate passed. It is not pooled with 2010-2024.

## Cohort definitions

- Strict principal: ICD-9-CM `410.X1`.
- Broad principal: ICD-9-CM `410.X0` or `410.X1`.
- Strict any-listed: principal or secondary ICD-9-CM `410.X1`.
- Broad any-listed: principal or secondary ICD-9-CM `410.X0` or `410.X1`.
- ICD-9-CM `410.X2` is excluded.

All models require the recorded patient sex-physician gender historical
eligibility flag. Physician linkage is derived from a unique Florida-license
crosswalk and provider master v2.

## Models

The frozen sex/gender interaction is estimated in two specifications: an
adjusted facility-year-quarter fixed-effect model and a within-physician model
with attending-physician plus facility-year-quarter fixed effects. Both use
two-way physician/facility clustered standard errors. Adjustment includes age
splines, the historical combined patient race/ethnicity category, all available
Elixhauser-condition indicators and the condition count, weekend and off-hours
indicators, payer, patient rurality, arrival-time band, and physician-quarter
volume. The facility-year-quarter model also includes physician ED-specialist
status and experience with a missingness indicator; those time-invariant
physician attributes are absorbed in the physician fixed-effect model. Linear
probability models are used for binary outcomes and OLS for continuous/count
outcomes. Fixed-effect logistic mortality models are optional sensitivity
models when at least 100 ED mortality events are available.

For HDFE numerical convergence, each required OLS/LPM model is first fit with
MAP alternating projections at a fixed-effect tolerance of 1e-8 and a 10,000
iteration ceiling. Only an explicit demeaning nonconvergence is retried with
the identical sample, formula, fixed effects, clustering, and contrast at
pyfixest's standard 1e-6 tolerance and a 50,000 iteration ceiling. Every retry
is recorded in the result and diagnostic tables.

Before fitting, outcome variation is checked within each AMI definition and
outcome-specific sample. A required grid cell with fewer than two observed
outcome values is retained but marked `NON_ESTIMABLE`; its estimate, standard
error, confidence interval, and p-value remain missing. Undefined inference is
never represented as a zero effect or a zero standard error.

## LOS rule

Only `length_of_stay_days` is analyzed. No hourly LOS value is available or
imputed for 2005-2008.

## Measurement limitations

Provider master v2 current registry attributes do not establish historical
employment, affiliation, privilege, specialty, or gender identity. The
patient and physician fields are administrative/proxy measurements.

Gate: `<PHASE2_ROOT>\qa\historical_provider_v2_pre_estimation_gate.json`

Validation: `<PHASE2_ROOT>\qa\historical_ami_validation_report.json`
