# Directional Dyad Model Implementation Specification

**Status:** Estimate-blind implementation checkpoint; no directional treatment-outcome estimate has been fitted or examined.  
**Period:** Primary 2010-2024. Historical 2005-2008 remains separate.  
**Parent plan:** `Directional_Dyad_Analysis_Plan_Extension_FROZEN.json`.

## Purpose

This document translates the frozen directional-dyad extension into an executable, storage-safe model contract. It does not alter the frozen research objective, outcomes, classifications, support rules, contrasts, fixed effects, clustering, multiplicity families, or association-only interpretation.

## 1. Analysis families and cell columns

All primary directional models are joint saturated factorial models. Hundreds of disconnected cell-specific regressions are prohibited.

### 1.1 Recorded gender dyads

For each encounter, construct four mutually exclusive cell indicators:

- physician Male / patient Male
- physician Male / patient Female
- physician Female / patient Male
- physician Female / patient Female

The four indicators sum to one on the recorded-gender eligible sample.

### 1.2 Five-class race dyads

For physician race class \(r\) and compatible recorded patient group \(p\), construct:

`cell_weight(r,p) = physician_race_posterior(r) * I(patient_group = p)`

The 25 columns use the AAMC Florida physician prior posterior vector. They sum to one on the primary probability-eligible sample. Physician race remains algorithm-inferred and probabilistic.

### 1.3 Intersectional race-gender dyads

For physician race \(r\), recorded physician gender \(g\), compatible patient race/ethnicity \(p\), and recorded patient sex \(s\), construct:

`cell_weight(r,g,p,s) = physician_race_posterior(r) * I(physician_gender = g) * I(patient_group = p) * I(patient_sex = s)`

The 100 columns sum to one on the primary intersectional probability-eligible sample.

### 1.4 Sensitivity encodings

- Hard maximum-posterior classifications at t50, t70, t80, and t90.
- wru national-population-prior posterior probabilities.
- National-prior hard classifications.
- Twenty NPI-level multiple imputations. Each draw is made once per NPI and held fixed across that physician's visits.
- Primary physician gender remains recorded NPPES/CMS; SSA >=90% expansion and the no-NPPES/CMS-conflict restriction remain sensitivities.

## 2. Outcomes and samples

Each outcome is estimated on its complete outcome-specific eligible sample. Outcomes are never imputed.

### 2.1 Frozen primary outcomes

- `los_hours_primary_0_168`
- `total_charge_reported_real_2024`

### 2.2 Resource and intensity outcomes

- `procedure_count_analysis`
- `any_procedure_flag`
- `high_procedure_flag`
- `em_acuity_proxy_level`
- `em_critical_care_flag`

### 2.3 Disposition outcomes

- `routine_discharge_flag`
- `transfer_flag`
- `hospice_flag`
- `mortality_flag`
- `left_discontinued_care_flag`

### 2.4 Reported charge components

The 14 inflation-adjusted component fields frozen in the extension are modeled separately. Reported charges are not costs, payments, or reimbursements.

### 2.5 Clinical-discretion outcomes

The frozen five direct fields and two derived higher-minus-lower outcomes remain exploratory pending clinician review.

## 3. Model sequence

### 3.1 U0

Unadjusted weighted or unweighted saturated cell summaries and frozen linear contrasts. Raw cell summaries are retained even when inferential support is insufficient.

### 3.2 M2_DIRECTIONAL

Joint linear or linear-probability model with:

- facility-by-year-quarter fixed effects
- principal clinical-category fixed effects
- the complete directional cell basis
- the frozen patient, visit, risk, and physician covariates

### 3.3 M3_WITHIN_PHYSICIAN

Sensitivity model adding attending-NPI fixed effects to M2. Time-invariant physician-group main effects are absorbed. Only identified within-physician patient simple effects and interaction differences are reported. Absolute physician-group cell predictions are not claimed from M3.

## 4. Covariate encoding

The implementation reuses the validated Phase 2 primary-matrix definitions:

- Age: linear age plus positive-part splines above 18, 45, 65, and 80; age-missing indicator.
- Payer: frozen categorical levels, with the first level as the omitted reference.
- Patient ZIP rurality: frozen categorical levels.
- Weekend and off-hours indicators plus missingness indicators.
- Arrival-time band: frozen categorical levels.
- All validated Elixhauser flags plus condition count.
- Recorded patient sex in non-intersectional race models.
- Compatible recorded patient race/ethnicity in gender models.
- Physician ED-specialist indicator and missingness.
- Years since medical school: linear value plus positive-part splines above 10, 20, and 30; missingness indicator.
- Log1p physician-quarter ED volume and missingness.

No post-outcome covariate is introduced. Any change requires a dated deviation before inspecting the affected results.

## 5. Adjusted predictions and contrasts

### 5.1 M2 standardized adjusted cell predictions

Because the complete cell basis sums to one and fixed effects absorb the common level, absolute cell coefficients are not interpreted directly. For outcome-specific sample mean \(\bar y\), empirical mean cell-composition vector \(\bar c\), fitted cell coefficient vector \(\hat\beta\), and target cell vector \(e_j\):

`adjusted_prediction(j) = mean(y) + (e_j - mean(cell_composition))' beta`

This anchors predictions to the observed outcome-specific sample while preserving all identified cell differences. Its variance uses the full selected cell-coefficient covariance:

`Var(prediction_j) = (e_j - mean(cell_composition))' V (e_j - mean(cell_composition))`

### 5.2 Planned directional contrasts

Every frozen contrast is evaluated as \(L'\hat\beta\) using the full selected covariance \(L'VL\). Pairwise contrast weights sum to zero and therefore do not depend on the arbitrary absorbed common level.

### 5.3 M3 reporting

M3 reports only contrast vectors that remain identified after physician fixed effects. Non-identified cell predictions or main effects are marked `NON_ESTIMABLE` rather than reconstructed.

## 6. Inference

- Two-way CRV1 clustering by attending NPI and facility.
- Confidence intervals use the frozen cluster-degree-of-freedom rule.
- Facility wild-score bootstrap sensitivity with 9,999 draws for preselected frozen primary-outcome directional contrasts.
- Covariance matrices must be symmetric, finite, and positive on every reported contrast variance.
- Non-finite or negative inferential quantities fail closed.

## 7. Support and estimability

Primary-period minimums:

- 1,000 visits or probability-weighted Kish effective visits
- 30 physicians or Kish effective physicians
- 20 facilities
- 30 physician clusters
- 20 facility clusters

Cells with fewer than 5,000 effective visits, 50 effective physicians, or 30 facilities are flagged `LIMITED_SUPPORT`. A contrast is estimable only if every nonzero-weight cell passes its outcome-specific thresholds, the design contrast is identified, the covariance is finite/nonnegative, and both cluster dimensions pass. Sparse cells are never silently merged.

Pre-model support is not final estimability. Final status is assigned only from the exact outcome-specific matrix and covariance.

## 8. Multiplicity and classification

- The original confirmatory family remains exactly the two frozen Black/White M2 interaction contrasts for outcome-specific LOS and reported real charges, with Holm adjustment.
- New directional families use the frozen Benjamini-Hochberg families.
- New gender and five-class race directional analyses are secondary extensions, except for explicitly preserved originally prespecified components.
- Expanded intersectional directional analyses are exploratory.
- Raw p-values, adjusted q-values, 95% confidence intervals, tier, family, sample, and estimability status are retained on every result row.

## 9. Storage, restart, and provenance

- Matrices are outcome-specific or grouped only when outcome-availability masks are identical.
- Double precision is used for estimation cross-products and covariance. Any lower-precision storage optimization must be benchmarked against double precision and logged before use.
- Builds are partition-aware, atomic, restartable, and hash-bound.
- Matrix manifests bind the provider master v2, physician-race proxy, cohort, directional base, extension, support gate, outcome definition, design specification, code, and source-partition hashes.
- Validated intermediates may be compacted only after an independent checkpoint certifies their hashes and model outputs.

## 10. Fail-closed audit sequence

1. Independent directional-base audit.
2. Primary cell-support build.
3. Independent cell-support audit.
4. Frozen implementation manifest and definition unit tests.
5. Outcome-specific matrix build.
6. Independent matrix/hash/support/rank audit.
7. Estimation.
8. Independent numerical, covariance, contrast, multiplicity, and result audit.
9. Only then may estimates be viewed, interpreted, or transferred into reports.

Association language is mandatory. No directional estimate is described as a causal effect, impact, discrimination mechanism, or proof of clinician behavior.

