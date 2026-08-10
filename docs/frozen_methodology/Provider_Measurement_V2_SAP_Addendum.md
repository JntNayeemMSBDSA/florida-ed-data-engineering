# Provider measurement v2 SAP addendum

Date frozen: 2026-07-26  
Status: estimate-blind measurement and coverage amendment

## Scope

This addendum corrects physician linkage coverage and physician demographic
measurement before real-data concordance estimation. It does not change the
research question, primary interaction contrasts, outcomes, model estimators,
fixed effects, clustering, multiple-testing plan, or the separate
AMI/Greenwood analysis.

## Provider universe

The provider master is one row per NPI in the union of:

1. the immutable Phase 1 physician master; and
2. every checksum-validated selected NPI observed in the attending,
   operating/performing, or other-practitioner role in any available Florida ED
   fact partition.

The master retains practitioner role, direct versus unique-license-derived
linkage, first and last observed quarter, visit volume, and observed
provider-facility-year activity. NPPES February 2026, CMS Doctors and
Clinicians June 2026, and Florida DOH attributes are explicitly labelled
cross-sectional. The refreshed CMS fields include specialty, medical school
and graduation year, group-practice fields, recorded gender, and official CMS
facility affiliations; legacy Phase 1 CMS fields remain alongside explicit v2
fields for audit comparison. ED provider-facility-year activity is
encounter-year observed. Neither that activity nor current CMS/DOH affiliation
data are interpreted as proof of historical employment or privileges.

Entity and clinician classifications are mutually exclusive for reporting.
Organizational NPIs cannot be classified as physicians. MD/DO physicians,
nurse practitioners, physician assistants, nursing clinicians, pharmacists,
psychologists, social workers, other individuals, organizations, and NPIs
absent from the current individual snapshot remain distinct.

## Why the primary cohort must be rebuilt

The pre-amendment Phase 2 builder inner-joined the Phase 1 physician master and
required the Phase 1 physician-master match and MD/DO flags before row
inclusion. It also used Phase 1 physician surname race and gender to decide
whether a visit could enter either concordance cohort. Provider linkage
therefore affected row inclusion.

All pre-amendment physician-dependent Phase 2 core checkpoints are
superseded—not deleted—and may be used only as audit comparators. The corrected
2010–2024 cohort is rebuilt directly from the immutable Phase 1 fact and bridge
files. A join-only relabelling of the old cohort is prohibited.

## Physician race/ethnicity measurement

Physician race/ethnicity is an algorithm-inferred analytical probability, not
self-identified identity.

Primary method ID:
`wru_name_likelihoods_aamc_fl_physician_prior_v1`

For race class \(r\), the posterior is:

\[
P(r \mid \text{name}) \propto P(r)
P(\text{surname}\mid r)
P(\text{first name}\mid r)
P(\text{middle name}\mid r).
\]

Only available dictionary-matched name components contribute; an unmatched
component contributes a neutral factor of one. Exact zero likelihoods use a
documented \(10^{-300}\) computational floor. Five posterior probabilities
(White, Black, Hispanic, Asian, and other/multiracial), maximum probability,
Black-plus-White probability mass, conditional Black probability among
Black/White, entropy, match pattern, and cleaning method are retained.

Name likelihoods come from the official wru v2.0.0 first-, middle-, and
augmented-surname dictionaries. The primary prior is the normalized 2020
Florida active-physician distribution reported in the AAMC 2021 State
Physician Workforce Data Report. Because AAMC categories are reported alone or
in combination, the official wru national 2020 prior is mandatory as a
sensitivity.

The AAMC tables used are pages 34, 36, 38, 40, 42, 44, and 46. Every table is
explicitly labelled "alone or in combination." The five-class Florida
endorsement sum is 52,638 of 58,822 active physicians (89.49%). Because the
published margins do not separately identify nonresponse and multiple-category
overlap, the normalized values are treated only as a transparent
target-population empirical prior. They are not described as mutually
exclusive Florida physician prevalence.

The primary method is not called BISG. The official `wru` documentation defines
geography as the individual's state and geographic unit of residence. NPPES
and Florida DOH provide practice or business locations, not residence.
Substituting practice ZIP for residential geography could encode the racial
composition of the facility neighborhood in the physician-race measure and is
therefore rejected for the primary proxy. The source tables, hashes, count
reconciliation, and this decision are checkpointed in
`qa/provider_race_prior_provenance_checkpoint.json`.

For the frozen Black–White hard-label contrast, a physician must:

- be an individual MD/DO;
- have matched surname and first-name likelihoods;
- have primary five-class label Black or White; and
- have maximum posterior probability at least 0.50.

The patient must have recorded Black or White race and recorded
non-Hispanic/Latino ethnicity. The primary race cohort continues to require a
direct validated attending NPI. Thresholds 0.70, 0.80, and 0.90,
probability-weighted exposure, alternative-prior estimates, and
physician-level multiple imputation remain required sensitivities.

## Earlier “Harvard” tables

`first_raceNameProbs.csv` contains \(P(\text{first name}\mid r)\) and matches
the official wru first-name likelihood dictionary to floating-point tolerance,
apart from an empty/NA key representation.

`first_nameRaceProbs.csv` contains the opposite conditional,
\(P(r\mid\text{first name})\). The two tables are not interchangeable.
Averaging opposite conditional probabilities or multiplying
\(P(r\mid\text{surname})\) by \(P(r\mid\text{first name})\) without correcting
for the prior is rejected. The earlier 0.5% sample hard label is retained only
as design history and is not an analysis input.

## Physician gender and patient sex

The primary physician field is a binary administrative/provider-source
category recorded in NPPES or CMS. The February 2026 NPPES and June 2026 CMS
current snapshots are treated as recorded provider sources. SSA first-name
imputation at at least 90% probability, used only when NPPES and CMS are
unavailable, is excluded from the primary cohort and retained as an expanded
measurement sensitivity. Categories
outside Female and Male are excluded from binary inference. An exact M2
sensitivity excludes NPIs whose recorded NPPES and CMS categories disagree and
re-demeans the restricted sample rather than deleting observations from
already-residualized data. These fields are not guaranteed to measure
self-identified gender identity and are mostly current snapshots.

Patient sex is the recorded administrative Female/Male field. It is not
assumed to measure gender identity.

## Logged deviations

- SAP-D01: expand the provider universe to all ED-observed validated NPIs.
- SAP-D02: replace primary surname-only race with the official-dictionary
  Bayesian full-name probability model.
- SAP-D03: use a Florida physician prior with the wru national prior as a
  mandatory sensitivity.
- SAP-D04: enforce individual/entity and clinician-type distinctions.
- SAP-D05: supersede physician-dependent Phase 2 checkpoints and rebuild the
  cohort from immutable Phase 1 facts.
- SAP-D06: preserve all 16 available 2005-2008 quarters as a separately
  checkpointed provider-v2 historical encounter universe, retaining every
  Phase 1 encounter and representing provider and concordance eligibility as
  flags rather than row-inclusion rules.
- SAP-D07: prohibit reconstruction of historical hourly LOS from day-level
  LOS. Historical hourly-LOS fields are structurally unavailable and remain
  null; `length_of_stay_days` may be analyzed only as an explicitly day-level
  historical outcome.
- SAP-D08: require an independent, estimate-blind 16-quarter reconciliation
  and cross-period comparability gate before any historical race,
  sex/gender, or AMI/Greenwood estimate is computed.
- SAP-D09: restore outcome-specific confirmatory samples for LOS and charges.
  The common complete-LOS-and-charge models are retained as robustness
  analyses. This supersedes the earlier DEV-003 implementation choice and
  restores the original frozen SAP missing-outcome rule before any real-data
  estimates are generated or viewed.
- SAP-D10: supersede the early proposal to pool all attending clinician types
  in a physician sensitivity analysis. MD/DO physicians remain distinct from
  NP/PA and other clinicians, and organizational NPIs are never physicians.
  Provider-type coverage is reported; any nonphysician concordance work must
  be a separately labeled exploratory clinician analysis.
- SAP-D11: correct the pre-estimation AMI implementation to include recorded
  patient race/ethnicity and all available Elixhauser indicators and to add
  the prespecified attending-physician fixed-effect specification. This
  restores the frozen SAP before any real-data estimate is generated or
  viewed.
- SAP-D12: correct the estimate-blind AMI source-benchmark reconciliation so
  the 2015 transition is applied by quarter: ICD-9-CM through Q3 and
  ICD-10-CM beginning Q4. The model cohort already used row-level code-system
  flags; this correction affects validation counts only.
- SAP-D13: restrict primary physician gender to recorded NPPES/CMS categories;
  retain SSA first-name imputation as an expanded sensitivity and add an exact
  no-NPPES/CMS-conflict M2 sensitivity.
- SAP-D14: refresh CMS clinician and facility-affiliation measurements from
  the June 26, 2026 official files, preserve legacy Phase 1 CMS fields, and
  bind the current source files by SHA-256 before estimation.

SAP-D01 through SAP-D08, SAP-D10, SAP-D13, and SAP-D14 are measurement,
coverage, or historical-comparability corrections. SAP-D09, SAP-D11, and
SAP-D12 are
pre-estimation implementation corrections that restore the frozen
missing-data, AMI adjustment, and ICD-transition rules. None changes the
frozen interaction contrasts or estimator families.

## Estimate-blind gate

No real-data model estimates may be viewed or interpreted unless all of the
following pass:

- provider master uniqueness and 100% ED-NPI-universe coverage;
- no organizational NPI classified as an MD/DO;
- full-name probability bounds and row sums;
- official wru versus earlier-table provenance comparison;
- all 60 provider-v2 partition checksums;
- independent visit-key/count reconciliation to the immutable Phase 1 facts;
- exact agreement of direct, license-derived, race-primary, and
  sex/gender-primary row counts; and
- preservation of the immutable Phase 1 release.

The controlling machine-readable checkpoint is
`qa/pre_estimation_measurement_gate.json`.

## Separate 2005-2008 provider-v2 historical track

The primary 2010-2024 cohort is unchanged by the historical extension. The
2005-2008 data are not appended to the primary cohort and are not used to fill
its time series. They form a distinct historical encounter universe built
directly from the immutable Phase 1 fact and diagnosis-bridge partitions.

Every historical Phase 1 encounter is retained in the provider-v2 checkpoint.
The following are recorded as separate, auditable flags:

- unique Florida-license-to-NPI resolution;
- provider-master-v2 match;
- individual MD/DO eligibility;
- full-name Black/White race-proxy eligibility at each threshold; and
- recorded patient sex-physician gender eligibility.

The historical race sensitivity uses source race/ethnicity code 3 versus code
4 and excludes the historically separate Hispanic codes from that contrast.
It uses unique-license-derived attending NPIs rather than direct source NPIs.
The same full-name physician probability method is applied, but the
historical patient construct and linkage route are not measurement-equivalent
to the primary era.

The historical AMI/Greenwood extension uses ICD-9-CM `410.X1` as the strict
definition. Principal and any-listed `410.X0`/`410.X1` definitions are
sensitivities; `410.X2` is excluded. This is an ED-only extension and cannot be
described as a replication of Greenwood et al.'s inpatient analysis.

A separate all-diagnosis historical recorded patient sex-physician gender
sensitivity is also permitted for compatible outcomes. It remains distinct
from both the 2010-2024 primary cohort and the historical AMI/Greenwood
extension.

Only outcomes and covariates classified as compatible or partially compatible
in `Historical_2005_2008_Comparability_Matrix.csv` may be used. Historical
`length_of_stay_days` is permitted as a day-level outcome. ED discharge hour
and clock-hour LOS are structurally unavailable, must remain null, and may not
be imputed as 24 times the day count. Same-facility admission, revisit, and
true triage measures that are structurally unavailable are not converted to
negative indicators.

Historical estimation is blocked unless
`qa/historical_provider_v2_pre_estimation_gate.json` reports `PASS`, confirms
all 16 quarter partitions, exact Phase 1 encounter-key preservation, provider
eligibility agreement, AMI-count agreement, zero hourly-LOS construction
errors, and unchanged Phase 1 checksums.

## Remaining limitations

No public individual-level self-reported physician race/ethnicity validation
source is available. Name-based probabilities may be differentially calibrated
across groups. Current provider attributes are not complete historical
snapshots. Binary administrative sex/gender fields do not represent all
identities. Provider measurement correction does not solve nonrandom physician
assignment, unmeasured severity, or residual confounding.
