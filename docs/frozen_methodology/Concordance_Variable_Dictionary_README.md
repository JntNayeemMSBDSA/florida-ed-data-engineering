# Concordance variable dictionary

The machine-readable dictionary is `Concordance_Variable_Dictionary.csv`.
It covers all fields in the normalized Phase 2 visit-level tables, the
versioned procedure-discretion sidecar, both cohort-specific model designs,
and the complete model-outcome catalog.

Important conventions:

- Every table has one row per ED visit and joins one-to-one on
  `visit_key`, `visit_year`, and `visit_quarter`.
- Physician–patient pair names put the physician first.
- Physician race/ethnicity is a Bayesian full-name analytical probability
  proxy without residential geography; it is not BISG or self-identified race.
- Patient sex and physician gender do not measure gender identity.
- Facility-reported charges are not costs, payments, or reimbursement.
- Missing values are never silently changed to zero.
- 2005–2008 historical race/ethnicity semantics are not pooled with the
  2010–2024 primary definitions.
- The exact transformation code is authoritative if a short dictionary label
  cannot express every edge case.
