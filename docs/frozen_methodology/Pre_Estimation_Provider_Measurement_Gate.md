# Pre-estimation provider measurement gate

Status: **PASS**

Created: 2026-07-26T18:16:37.091818+00:00

This checkpoint was produced without reading or interpreting any real-data
model estimate.

## Why the old Phase 2 cohort was stale

The old builder inner-joined the Phase 1 physician master and required the
Phase 1 physician-master match and MD/DO flags before row inclusion. It also
used Phase 1 surname race and physician gender to determine whether a visit
could enter either concordance cohort. Therefore provider linkage affected row
inclusion. The old successful partitions are preserved as superseded audit
artifacts; they are not estimation-ready.

The provider-v2 cohort was rebuilt directly from the immutable Phase 1 fact and
diagnosis bridge files. It was not reconstructed from the old Phase 2 cohort.

## Gate checks

- provider_master_v2_qa: True

- provider_race_proxy_v2_qa: True

- current_cms_large_source_hashes: True

- all_60_v2_partition_manifests_valid: True

- independent_fact_to_cohort_reconciliation: True

- harvard_wru_provenance_comparison: True

- physician_race_prior_provenance_and_disclosure: True

- physician_gender_measurement_and_source_gate: True

- organizational_npis_never_md_do: True

- phase1_release_unchanged_by_workflow: True

- estimand_and_estimators_frozen: True

## Provider universe

- Master NPIs: 1,813,546
- ED-observed NPIs: 83,541
- Newly added ED-observed NPIs: 7,751
- ED-observed individuals: 78,843
- ED-observed organizations: 2,152
- ED-observed MD/DO physicians: 65,912
- ED-observed nurse practitioners: 5,972
- ED-observed physician assistants: 4,028
- Organizational NPIs classified as MD/DO: 0

Detailed counts by year, role, linkage method, entity type, clinician type,
unique NPI, and visit-role link are in
`pre_estimation_phase1_vs_v2_linkage_coverage.csv`.

## Race measurement

The primary physician race measure is an algorithm-inferred Bayesian full-name
probability using official wru v2.0.0 P(name|race) dictionaries and a normalized
Florida active-physician prior from AAMC 2020 counts. It is not self-identified
race and is not BISG because residential geography is unavailable. The wru
national 2020 prior is retained as a mandatory sensitivity.

The AAMC source tables are pages 34, 36, 38, 40, 42, 44, and 46 of the
2021 State Physician Workforce Data Report. Each table is explicitly labelled
"alone or in combination." The five-class Florida endorsement sum is 52,638
of 58,822 active physicians (89.49%). Because the published margins do not
separate nonresponse from multiple-category overlap, the normalized values are
used only as a transparent target-population empirical prior, not as an estimate
of mutually exclusive Florida physician prevalence.

NPPES and Florida DOH locations are practice or business addresses. Official
wru geography inputs refer to residence, so practice ZIP is not substituted for
residential geography; doing so could encode facility-neighborhood composition
in the physician-race measure.

The earlier `first_raceNameProbs.csv` is the official first-name likelihood
table to floating-point tolerance. The earlier `first_nameRaceProbs.csv` has
the opposite conditional, P(race|first). These cannot be averaged or multiplied
as if they were independent likelihoods; that earlier combination is rejected.

## Gender measurement

Primary physician gender uses recorded NPPES or CMS binary administrative
categories only, including the February 2026 NPPES and June 2026 CMS current
snapshots. SSA >=90% first-name imputation is excluded from the primary cohort
and retained as an expanded measurement sensitivity. A separate exact M2
sensitivity excludes NPIs whose recorded NPPES and CMS categories disagree.
None of these fields is guaranteed to measure self-identified gender identity.
Patient sex is the recorded administrative sex field.

- Hierarchy-eligible visits: 119,495,192
- Recorded-source primary visits: 119,495,191
- SSA-expanded-only visits: 1
- Recorded-source conflict visits: 523,608
- Recorded-source conflict NPIs: 179

## Frozen analysis

Provider v2 is a measurement and coverage correction. The research objective,
charges, admission/disposition, length of stay, treatment intensity,
utilization, separate AMI/Greenwood analysis, primary contrasts, and estimators
remain frozen except for the logged measurement-related SAP deviations.

## Remaining limitations

- No public individual-level self-reported physician race/ethnicity validation source was available.

- The primary name-only method is not BISG and has no residential geography.

- AAMC prior categories are reported alone or in combination and require normalization.

- The AAMC Florida five-class endorsement sum is 52,638 of 58,822 active physicians (89.49%); published margins do not separately identify nonresponse and multiple-category overlap.

- NPPES February 2026, CMS June 2026, and Florida DOH identity, specialty, location, affiliation, and gender fields are mostly current snapshots, not encounter-year histories.

- Observed provider-facility-year links show ED encounter activity, not formal employment or privileges.

- Binary physician gender and patient sex fields do not measure gender identity.

- Name-based race probabilities may be differentially calibrated across groups and must not be interpreted as individual identity.

- Provider measurement correction does not resolve nonrandom physician assignment or residual clinical confounding.
