# Historical 2005-2008 race-concordance sensitivity

This analysis is separate from the 2010-2024 primary cohort. It uses the
provider-v2 full-name race probability model and six prespecified measurement
specifications. Compatible outcomes use day-level LOS; hourly LOS is
structurally unavailable and not imputed. Models use facility-year-quarter and
principal clinical-category fixed effects with two-way physician/facility
clustered standard errors and the full prespecified adjustment set.

Each model is fit in a fresh OS process from a hash-bound prepared parquet
input. Isolation is computational only and does not alter any sample,
covariate, fixed effect, cluster, outcome, or contrast.
