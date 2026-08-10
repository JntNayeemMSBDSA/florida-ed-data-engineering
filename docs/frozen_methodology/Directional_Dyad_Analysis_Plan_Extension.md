# Directional Dyad Analysis-Plan Extension

**Frozen:** 2026-07-26T20:55:03.010054+00:00  
**Version:** `directional_dyad_extension_v1_20260726`  
**Manifest SHA-256:** `3574fd278d194042dabddb7abe7a9e9ecf9f3b8e5f06fa9e48d3a44836a00d5a`  
**Gate:** `FROZEN_ESTIMATE_BLIND_PASS`

## Timing and status

This extension was frozen after primary-period descriptive and unadjusted
outputs and some historical inferential outputs existed, but before any
adjusted primary-period model matrix or adjusted primary-period result existed.
The freeze audit inspected file names, timestamps, schemas, manifests, and
hashes only; it did not read coefficient values.

The binary Black/White four-cell race model, the binary four-cell
recorded-sex/physician-gender model, and their interaction contrasts retain
their genuinely original SAP status. New adjusted directional cell
predictions and contrasts are secondary. The expanded five-class race family
is secondary. The expanded race-plus-gender intersectional family is
exploratory. The entire extension must not be called originally prespecified.

## Data reuse decision

All required fields are present in all 60 validated provider-v2 cohort
partitions. Phase 2 cohort rebuilding is unnecessary. Phase 1 remains
immutable. New hash-bound derived matrices will be built from the validated
2010-2024 provider-v2 partitions. The 2005-2008 cohort remains separate and
may use only historically comparable variables; hourly LOS is structurally
unavailable and will not be imputed.

## Families

- Gender: 4 directional cells and 6 frozen pairwise contrasts.
- Race: 25 five-class cells and 68 frozen directional contrasts.
- Intersectional: 100 race-plus-gender by race-plus-sex cells and 359 frozen
  axis-aligned/reference contrasts.

All cells remain visible. Sparse cells are never merged; they are labelled
`LIMITED_SUPPORT` or `NON_ESTIMABLE` under the exact thresholds in the JSON
manifest.

## Measurement

Physician race is a five-class Bayesian full-name probability proxy using the
official `wru` v2.0.0 name dictionaries and no geography. It is not BISG,
self-reported race, or an identity measure. Primary directional race results
require both posterior-mixture probability models and 20 physician-level
multiple imputations. Hard classifications, confidence thresholds, and the
national population prior are sensitivities.

Physician gender uses recorded NPPES/CMS administrative categories in the
primary analysis. Recorded patient sex is not gender identity. Patient
race/ethnicity uses the compatible five-class mapping frozen in the JSON
manifest.

## Estimation and reporting

One joint factorial model is used per family and outcome/sample specification;
the analysis will not fit hundreds of disconnected cell regressions. Results
include unadjusted cell summaries, standardized adjusted predictions or
identified marginal effects, all frozen directional contrasts, 95% confidence
intervals, raw p-values, BH q-values, cell/cluster support, and explicit
estimability status. The original two-outcome Holm confirmatory family is not
expanded.

All estimates are observational associations.
