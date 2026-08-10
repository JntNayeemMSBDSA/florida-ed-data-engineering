# Statistical Analysis Plan

> **Controlled amendment, 2026-07-26:** Physician-dependent Phase 2
> measurement is governed by
> `Provider_Measurement_V2_SAP_Addendum.md` and the estimate-blind
> `Pre_Estimation_Provider_Measurement_Gate.md`. Pre-amendment surname-only
> language below is preserved for audit history but is superseded for the
> 2010–2024 provider-v2 analysis. The research objective, outcomes, contrasts,
> estimators, fixed effects, clustering, AMI/Greenwood analysis, and sensitivity
> framework remain frozen.

## Florida Emergency Department Physician–Patient Concordance Study

**Phase 2 release:** `florida_ed_concordance_analysis_20260726`  
**Source release:** `florida_ed_full_build_20260724`  
**SAP status:** Frozen  
**Frozen:** 2026-07-26T04:55:16Z, before outcome estimation  
**Design:** Retrospective observational study of administrative emergency department encounters

## 1. Purpose and scientific framing

This study evaluates whether physician–patient racial concordance and recorded patient sex–physician gender concordance are associated with differences in emergency department resource use, treatment, and disposition. The study is not designed as a causal analysis. Physician assignment is not known to be random, physician race/ethnicity is measured using an official-dictionary Bayesian full-name analytical probability proxy without residential geography (not BISG and not self-identified race), and the data do not capture all clinical severity or interpersonal mechanisms.

Race is treated as a social and contextual construct. A measured concordance association may reflect communication, language, culture, geography, institutional sorting, clinical uncertainty, access, measurement error, or residual confounding. The reports will use terms such as “associated with,” “adjusted difference,” “within-physician contrast,” and “observed concordance estimate.” They will not characterize an association as an impact, causal effect, discrimination, or proof of a mechanism.

## 2. Research questions and hypotheses

### 2.1 Primary question

Among Florida ED encounters in 2010–2024, is the Black–White patient difference in outcomes different for encounters with a physician whose official-dictionary Bayesian full-name racial/ethnic analytical proxy is Black versus White?

The prespecified interaction contrast is:

`black_black − black_white − white_black + white_white`

where the physician is listed first. All primary hypothesis tests are two-sided. No direction is prespecified.

### 2.2 Secondary questions

1. Is recorded patient sex–physician gender concordance associated with the same outcomes?
2. Do racial-concordance associations differ for symptom/sign-coded versus disease-coded presentations?
3. Do associations differ across evidence-informed clinical-uncertainty or treatment-decision-latitude groupings?
4. Does payer status moderate racial-concordance associations?
5. Is sex/gender concordance associated with outcomes among validated ED encounters with acute myocardial infarction?
6. Do racial and sex/gender concordance interact when measurement quality, overlap, and cell sizes are adequate?

The payer-based hypothesis originating in project emails is exploratory. It will be analyzed as effect modification by payer/uninsured status without attributing a psychological mechanism that the data cannot measure.

## 3. Data source, scope, and source protection

The immutable source release contains 148,686,146 unique encounter rows in 76 quarter partitions covering 2005–2008 and 2010–2024. Years 2009 and 2025 are absent by design. Phase 2 reads the release without modifying it. Derived data are written only inside the versioned Phase 2 directory and retain source encounter keys for restricted audit use.

The 2010–2024 period is primary because patient race and ethnicity are represented separately and direct NPI reporting is available. The 2005–2008 period has historically combined race/ethnicity semantics and license-based physician linkage; it is analyzed separately as a historical sensitivity and is never silently pooled with the primary era.

The independent release audit passed row-count, uniqueness, partition, and ICD-transition checks. One of 76 facility companion workbooks is absent for 2018 Q1; facility-history analyses will flag that quarter. CMS clinician and facility-affiliation fields were refreshed from the official files modified June 26, 2026, while legacy Phase 1 CMS values were retained for audit comparison. CMS group-practice, CMS facility-affiliation, and Florida DOH hospital-privilege fields are contemporary snapshots. They are descriptive attributes or sensitivity covariates and are not interpreted as historical point-in-time affiliations.

## 4. Study cohorts

### 4.1 Primary racial-concordance cohort

An encounter is eligible when all of the following hold:

1. Visit year is 2010–2024.
2. The primary physician role is the attending practitioner.
3. The attending identifier is a check-digit-validated direct NPI.
4. The NPI matches the one-row-per-NPI physician master.
5. The attending is classified as an MD/DO.
6. Recorded patient race is Black or African American or White.
7. Recorded ethnicity is Not Hispanic or Latino.
8. The attending full-name analytical proxy is classified as Black or White under the prespecified five-class posterior model.
9. The maximum surname-imputation probability is at least 0.50.

The feasibility audit identified 49,918,295 eligible visits at the 0.50 threshold. Final counts will be reconciled after the analytical cohort is built.

### 4.2 Race sensitivity cohorts

- Thresholds of 0.70, 0.80, and 0.90.
- Race-only patient definitions that do not restrict ethnicity.
- Direct NPI plus unique Florida license-to-NPI links.
- Non-MD/DO attending clinicians may be studied only as a separately labelled
  exploratory clinician analysis; they are not pooled into physician
  concordance sensitivities.
- Operating/performing and other-practitioner roles, analyzed separately.
- Physician-level multiple imputation using the six retained surname probabilities. One proxy category is drawn per physician per imputation and held constant across all that physician’s visits. Twenty deterministic imputations are combined using Rubin’s rules.
- Probability-based Black-versus-White exposure using normalized Black and White surname probabilities, with the normalization rule documented.

### 4.3 Historical racial-concordance cohort

Visits in 2005–2008 are analyzed in a separately checkpointed provider-v2
historical encounter universe using the historical combined race/ethnicity
definitions and unique-license physician linkage. All 16 quarters must
independently reconcile to the immutable Phase 1 facts before use. Every Phase
1 encounter is retained in the checkpoint; linkage, individual MD/DO,
full-name race-proxy, and recorded patient sex-physician gender eligibility
are represented as flags.

Historical estimates are not treated as directly comparable to 2010–2024 and
are not appended to the primary cohort. Cross-era synthesis is permitted only
as an explicitly secondary heterogeneity or meta-analytic comparison for
outcomes and covariates classified as compatible in the frozen comparability
matrix. Historical hourly LOS is structurally unavailable and must not be
imputed from `length_of_stay_days`.

### 4.4 Sex/gender cohort

The primary sex/gender cohort uses 2010–2024 direct-NPI attending MD/DO
encounters with recorded patient sex of Female or Male and physician gender of
Female or Male recorded in NPPES or CMS. The February 2026 NPPES and June 2026
CMS current snapshots are recorded provider sources. SSA first-name-imputed
physician gender is excluded from the primary cohort and retained as an
expanded measurement sensitivity. Unknown, missing, and ambiguous categories
remain visible in data-quality tables and are excluded only from the binary
inferential cohort. An exact M2 sensitivity excludes NPIs with disagreeing
recorded NPPES and CMS categories.

Terminology is “recorded patient sex–physician gender concordance.” The administrative fields are not treated as measures of gender identity.

### 4.5 AMI cohort

The AMI analysis is an ED-only extension inspired by, not a replication of, Greenwood, Carnahan, and Huang. Their study used inpatient admissions through the ED and survival to hospital discharge, which are not available here.

The strict ICD-9-CM definition is a principal diagnosis `410.X1`. Sensitivities include any-listed `410.X1` and principal `410.X0` or `410.X1`; `410.X2` is excluded from the strict initial-AMI cohort.

The primary ICD-10-CM definition is a principal diagnosis in `I21.0–I21.4` or `I21.9`. Sensitivities add `I21.A1` and `I21.A9`, isolate type 1 MI, and use `I22` only when an `I21` code is present on the same encounter. The ICD transition occurs in 2015 Q4; the type 2 MI coding discontinuity beginning in 2017 Q4 is modeled explicitly.

AMI results are not interpreted until code logic, diagnosis position, transition timing, and yearly counts pass a written validation gate against appropriately scoped benchmarks. Differences from inpatient benchmarks must be explained by setting and coverage.

The 2005–2008 AMI/Greenwood extension is separately gated and estimated using
ICD-9-CM definitions and day-level LOS only. It is never pooled into the
2010–2024 primary AMI cohort by default.

## 5. Exposures

### 5.1 Racial-concordance variables

The analytical data contain mutually exclusive indicators:

- `black_black`: Black physician proxy, Black patient
- `black_white`: Black physician proxy, White patient
- `white_black`: White physician proxy, Black patient
- `white_white`: White physician proxy, White patient

They also contain `race_pair_category`, `black_racial_concordance_flag`, `racial_concordance_flag`, `patient_black_flag`, `physician_black_imputed_flag`, `physician_race_imputation_available_flag`, linkage provenance, full-name posterior probabilities under the primary and population-prior sensitivity models, maximum probability, threshold flags, and measurement-version identifiers.

Saturated cell means are estimated without an intercept, or an explicitly documented reference category is used. The requested interaction contrast is calculated from the full variance–covariance matrix.

### 5.2 Sex/gender-concordance variables

Mutually exclusive indicators are `female_female`, `female_male`, `male_female`, and `male_male`, with physician listed first. The data also contain a four-level pair category and a concordance flag. The corresponding interaction is:

`female_female − female_male − male_female + male_male`.

## 6. Outcomes

### 6.1 Confirmatory primary outcomes

1. **Clock-derived ED length of stay in hours.** The original integer `length_of_stay_days` is preserved. For valid arrival and discharge hours, hourly LOS is `24 × length_of_stay_days + discharge hour − arrival hour`. Code `99`, missing/invalid hours, negative results, and values above 168 hours are excluded from the primary LOS outcome. All nonnegative values, a 72-hour restriction, and quarter-specific 99.5th-percentile winsorization are sensitivities.
2. **Inflation-adjusted reported total facility charge.** `total_charge_reported` is converted to constant 2024 dollars using the quarterly mean of BLS CPI-U all items, not seasonally adjusted (`CUUR0000SA0`). These are reported/list facility charges, not cost, payment, reimbursement, or actual spending.

The feasibility audit found 124,713,439 nonnegative clock-derived LOS values in 2010–2024, 343,622 negative clock inconsistencies, and 23,309 values above 168 hours before cohort restrictions.

### 6.2 Secondary resource outcomes

- Canonical total charge and component charge sum
- Pharmacy, medical/supply, laboratory, radiology, cardiology, operating-room, anesthesia, recovery, emergency-room, trauma, observation, gastroenterology, lithotripsy, and other reported charges
- Procedure count, any procedure, and quarter-specific high-procedure indicator
- Evaluation-and-management acuity proxy, explicitly labeled as a billing-derived proxy rather than true triage

Nominal charges are preserved. Medical-care CPI (`CUUR0000SAM`) is a sensitivity. Missing charge components are never converted to zero without historical dictionary support.

### 6.3 Secondary disposition outcomes

Routine discharge, transfer, hospice, ED mortality, left/discontinued care, and other interpretable disposition groups are analyzed only when the field definition is valid in the relevant era.

True clinical triage, stable-patient revisits, and confirmed same-facility inpatient admission are structurally unavailable and are not reconstructed.

## 7. Covariates and causal ordering

Primary adjustment uses pre-exposure or baseline measures:

- Flexible age splines and an age-missing flag
- Recorded patient sex in racial-concordance models
- Patient race/ethnicity in sex/gender models
- Payer group
- ZIP-based rurality
- Weekend, off-hours, arrival-hour band, and weekday
- Principal CCS/CCSR clinical category
- Era-appropriate Elixhauser conditions and condition count
- Physician ED-specialist status
- Years since medical school plus a missingness indicator
- Linkage method in expanded-link sensitivity cohorts
- Facility characteristics and calendar time

Procedures, charge components, disposition, and billing-derived E/M acuity are potential downstream measures and are not controls in models where they may mediate the outcome. Their use in severity sensitivities is separately labeled.

Current CMS group-practice and Florida DOH hospital-privilege indicators are not primary historical controls because their timing is not consistently contemporaneous with past visits.

## 8. Descriptive analysis

The full eligible cohort is used for:

- Cohort flow and exclusions
- Pair-group counts and percentages
- Means, standard deviations, medians, interquartile ranges, and selected percentiles
- Missingness and zero-value profiles
- Unadjusted absolute and relative differences with 95% confidence intervals
- Linkage rates and standardized differences between linked and unlinked encounters
- Trends by year
- Physician, facility, payer, and clinical-category composition
- Support among physicians who treat both Black and White patients or both female and male patients

Very small p-values are not interpreted as substantive importance. Estimates are presented in clinically or economically interpretable units.

## 9. Statistical models

### 9.1 Racial-concordance sequence

1. Full-sample unadjusted saturated four-cell means and the prespecified contrast.
2. Patient- and visit-adjusted OLS or linear-probability models.
3. Fully adjusted models with facility-by-year-quarter and principal-clinical-category fixed effects.
4. Physician fixed-effect models with facility-by-year-quarter and principal-clinical-category fixed effects. The physician-proxy main effect is absorbed, while the patient-race-by-physician-proxy interaction remains estimable.

Primary inference uses two-way cluster-robust standard errors by attending NPI and facility. Facility-quarter clustering and a facility-level wild cluster bootstrap are sensitivities. Collinearity, singleton removal, convergence, and cluster counts are stored with each model.

### 9.2 Outcome-specific estimators

- Continuous outcomes: level-scale OLS for the primary absolute-difference estimand.
- Binary outcomes: linear probability models; logistic average marginal effects as sensitivity.
- Counts: Poisson and, if supported by overdispersion diagnostics, negative-binomial-type sensitivity models.
- Skewed charges and LOS: PPML or two-part models, winsorized levels, and `log1p` OLS as sensitivity only.

Model choice is not based on favorability of results.

### 9.3 Sex/gender models

The same specification sequence and inference rules are used for the sex/gender interaction. AMI models are reported separately and only after the AMI validation gate.

## 10. Missing data, outliers, and linkage quality

Exposure-defining variables use complete cases in the primary cohort, with every exclusion counted. Unknown categories are retained in data-quality tables. Outcome missingness is handled separately for each outcome. Categorical covariate unknowns are explicit; missing continuous physician experience is imputed within year and specialty strata when feasible, with a missingness flag. No clinical outcome is imputed.

Primary charges retain valid nonnegative values without trimming. Quarter-specific 99.5th- and 99.9th-percentile winsorization and positive-charge/two-part models are sensitivities. Negative charges, if any, are invalid for the main charge outcome and are separately audited.

Direct NPI is primary. Unique-license linkage is a sensitivity. Linked and unlinked visits are compared by year, facility, patient group, payer, diagnosis, severity proxy, and outcome. Inverse-probability-of-linkage weighting is used only if estimated probabilities show adequate positivity, effective sample size remains at least 70% of nominal size after truncation, and no extreme instability is observed. Otherwise, the limitation is documented and no weighting estimate is emphasized.

## 11. Clinical uncertainty and decision latitude

No universal ICD/CCSR classification validates “subjective” versus “objective” diagnoses or high- versus low-discretion treatment. The observable primary grouping is therefore:

- Symptom/sign-coded presentation: ICD-9-CM `780–799` or ICD-10-CM `R00–R99`
- Disease-coded presentation
- Ambiguous or mixed presentation

This is labeled symptom/sign-coded versus disease-coded, not subjective versus objective.

A separate provisional, evidence-informed clinical-uncertainty and guideline-permitted decision-latitude crosswalk will record every source category/code, assigned group, rationale, source, confidence, ambiguity flag, version, date accessed, and clinician-review status. Uncertain entries remain ambiguous. Results using these groupings are exploratory until qualified clinician review.

## 12. Heterogeneity and exploratory analyses

Prespecified secondary heterogeneity includes symptom/sign-coded presentation, payer, ED-specialist status, age group, physician experience, severity proxy, coding era, and facility characteristics. Payer moderation uses a three-way patient-race-by-physician-proxy-by-uninsured interaction.

Race-by-sex/gender intersectional analysis proceeds only if all relevant cells have adequate observations and cluster support. It is exploratory. Leave-one-year-out and influential-facility analyses assess stability.

## 13. Multiple testing

The two confirmatory outcomes form one primary family and are adjusted using Holm’s method. Secondary families are charge components, procedures/treatment decisions, dispositions, heterogeneity, and AMI extension outcomes. Benjamini–Hochberg false-discovery-rate control is applied within each family. Raw p-values, adjusted p-values, confidence intervals, sample sizes, and family identifiers are retained.

## 14. Computational reproducibility and QA

The analytical cohort is partitioned by year and quarter and contains only required fields. The source database is not physically recombined. Deterministic hash samples are used only for transformation tests and model prototypes; final estimates use the full eligible cohort.

Required QA includes:

- Hand-constructed unit tests for physician-first pair indicators and both interaction contrasts
- Exact cohort-flow reconciliation
- Chart-to-table and narrative-to-model reconciliation
- Verification of covariance-based contrasts
- Fixed-effect, singleton, convergence, and influence diagnostics
- Independent audit of the primary counts and models
- Clean-environment rerun
- Package/version capture
- File checksums and final manifest

## 15. Interpretation limits

The study cannot establish causal effects or mechanisms. Major limitations include nonrandom physician assignment, name-based physician race-proxy measurement error, historical incompatibility, incomplete physician linkage, residual clinical confounding, billing-derived rather than clinical acuity, lack of a stable patient identifier, absence of confirmed inpatient admission and post-ED outcomes, coding transitions, and restricted generalizability to reported Florida ED encounters.

The AMI analysis cannot replicate inpatient survival results. ED mortality is not equivalent to survival to hospital discharge.

## 16. Deviations

After this freeze, any change to cohort, exposure, outcome, model, missing-data, outlier, linkage, or multiple-testing rules is entered in `SAP_deviation_log.csv` with date, reason, and anticipated direction before the affected result is inspected.

## 17. Key source basis

- Florida AHCA discharge-data reporting specifications
- CDC/NCHS and CMS ICD-9-CM and ICD-10-CM official guidelines
- BLS CPI official data and methodology
- U.S. Census surname data documentation
- Greenwood, Carnahan, and Huang (2018), PNAS, doi:10.1073/pnas.1800097115
- Ye and Yi (2023), Review of Economics and Statistics, doi:10.1162/rest_a_01236
- Hill, Jones, and Woodworth (2023), Journal of Health Economics, doi:10.1016/j.jhealeco.2023.102821
- RECORD statement and linked-data quality guidance
- Benjamini and Hochberg (1995)
- Manning and Mullahy (2001)
