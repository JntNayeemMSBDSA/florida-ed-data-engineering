# Methodology

## Scope and analytical grain

Phase 1 has one row per released Florida emergency-department encounter record. Source quarters are processed independently, reconciled to their inputs, and written as partitioned facts and occurrence bridges. Duplicate released record identifiers are not silently removed; the pipeline creates a unique production visit key that preserves each released row. The in-scope periods are 2005–2008 and 2010–2024. Years 2009 and 2025 are excluded by instruction.

Phase 2 has two distinct tracks. The primary cohort covers 2010–2024, when direct validated attending NPIs are available. The historical track covers 2005–2008 and uses only unique Florida-license-to-NPI links. The historical data are not appended to the primary cohort, and differences in patient race/ethnicity, provider linkage, coding, and outcome availability are treated as measurement limits rather than ignored.

## Source-quarter ingestion and five-schema standardization

Before a quarter is transformed, its column layout is assigned to one of five approved schema families: 2005–2008, 2010–2015 Q3, 2015 Q4–2017, 2018–2022, or 2023–2024. Unrecognized layouts fail rather than entering a best-effort union. The quarter builder then maps era-specific names and encodings into the canonical fact, keeps the source schema identifier, and records a source-to-output reconciliation manifest.

The generated visit key combines source context with a duplicate-aware row sequence. This makes the production key unique without pretending that a source record identifier is a stable patient identifier. It also supports exact reconciliation back to each quarter.

## Diagnosis, procedure, and clinical processing

Diagnosis code system is determined by the official transition boundary: ICD-9-CM through 2015 Q3 and ICD-10-CM beginning in 2015 Q4. The diagnosis bridge retains code, role, position, normalized text, mapping flags, mapped categories, and provenance. ICD-9-CM diagnoses map to CCS; ICD-10-CM diagnoses map to CCSR.

Procedure processing keeps source position and code-system semantics. ICD-9-CM procedures use CCS mappings. ICD-10-PCS procedures use Procedure Classes Refined. CPT/HCPCS records use CCS Services and Procedures plus separately obtained descriptions where permitted. Descriptions are reference aids and are not treated as historical point-in-time codebooks when their source is current.

Elixhauser indicators are constructed from secondary diagnoses only, using separate ICD-9-CM and ICD-10-CM mappings. External-cause fields are not treated as comorbidities. Era-specific fields that do not apply are represented as structural nulls.

## Provider and physician construction

The Phase 1 physician dimension has one row per NPI and retains attending, operating/performing, and other-practitioner roles separately. For the primary period, a valid direct NPI is preferred. Historical linkage is permitted only where a normalized Florida license maps uniquely to one NPI.

Provider master v2 expands the universe to the union of the Phase 1 master and every checksum-valid NPI observed in a selected ED practitioner role. NPPES, CMS Doctors and Clinicians, and Florida Department of Health sources add entity type, taxonomy, specialty, medical-school and graduation information, recorded gender, group affiliation, and facility affiliation. These external snapshots are labeled cross-sectional. ED-observed provider-facility-year activity is encounter-year evidence; a current public affiliation is not treated as proof of historical employment or privileges.

Entity and clinician categories are mutually exclusive for reporting. Organizations cannot be physicians. Individual MD/DO physicians, nurse practitioners, physician assistants, other individual clinicians, and organizations remain distinct. Experience is derived where training or graduation-year information supports it, with implausible or unavailable values handled explicitly.

## Facility and visit enhancement

The facility dimension is keyed by the state facility identifier and retains name and Medicare-number histories. Current CMS attributes are attached only through documented linkage rules. ZIP-centroid geography, RUCA rurality, off-site ED activity, physician composition, charges, and major clinical categories are added with their applicable time caveats.

Visit fields include decoded demographics, geography, payer, disposition, arrival timing, procedure counts, charge reconciliation, and year-specific high-charge or high-procedure flags. `EVALCODE` supports only a labeled evaluation-and-management acuity proxy. Charges are not interpreted as costs or payments.

Some requested measures cannot be supported by the source extracts. True clinical triage, same-facility inpatient admission, and reliable 7- or 30-day revisits remain unavailable. The historical release contains day-level length of stay but not clock-hour LOS; the workflow does not multiply days by 24 or otherwise fabricate an hourly measure.

## Physician race/ethnicity probability

The primary physician race/ethnicity measure is an algorithm-inferred five-class probability based on available surname, first-name, and middle-name likelihoods. For class \(r\), the unnormalized posterior is:

\[
P(r)\,P(\text{surname}\mid r)\,P(\text{first name}\mid r)\,P(\text{middle name}\mid r).
\]

Only matched name components contribute. The official `wru` name-likelihood dictionaries are used. The primary prior is based on the AAMC Florida active-physician distribution; the national `wru` population prior is a required sensitivity. Full posterior probabilities and uncertainty measures are retained for sensitivity work.

This is not BISG because residential geography is not used. A practice or business ZIP code is not substituted for a residence. The field is not self-reported physician race/ethnicity and must not be described as identity. Hard-label thresholds, alternative priors, probability-weighted exposure, and physician-level multiple imputation are measurement sensitivities rather than proof of an underlying identity category.

## Physician gender measurement

The primary physician field uses recorded binary categories from NPPES or CMS. SSA first-name imputation is excluded from the primary cohort and reserved for an expanded sensitivity when recorded sources are absent. A separate sensitivity excludes NPIs whose NPPES and CMS categories disagree and re-estimates the model on the restricted sample. These administrative fields are not guaranteed to measure self-identified gender identity and are mostly current snapshots.

## Cohorts and validation gates

The provider-v2 primary cohort is rebuilt from immutable Phase 1 facts because the earlier Phase 2 implementation used physician-dependent inner-join rules. Rebuilding prevents a join-only relabeling from concealing selection. Every primary partition is hash-bound and independently reconciled on visit keys, counts, selected source fields, provider eligibility, measurement eligibility, and outcome support.

The historical provider-v2 universe preserves every Phase 1 encounter and represents linkage and measurement eligibility as flags. Independent checks cover all historical partitions, exact key preservation, selected-field agreement, provider-type rules, AMI definition agreement, and structural unavailability of hourly LOS.

## Estimation framework

The primary models are observational association models. The code organizes a sequence from patient-adjusted specifications to models with facility-year-quarter and clinical fixed effects, followed by a physician fixed-effect specification. Large matrices are prepared in restartable, double-precision, memory-mapped blocks in the private environment. The public repository includes the matrix and estimator code but no matrix files or fitted results.

Inference uses two-way physician and facility cluster-robust covariance with the physician-facility intersection subtraction. The out-of-core HDFE path is checked against a reference implementation on synthetic data. Measurement-threshold, probability-weighted, alternative-prior, multiple-imputation, outcome-definition, cohort-definition, and historical analyses are maintained as separate sensitivities.

The multiplicity plan applies Holm adjustment to the narrow confirmatory family and Benjamini–Hochberg adjustment within prespecified secondary families. Directional dyad work uses joint factorial models and frozen contrasts rather than hundreds of disconnected cell regressions. The directional extension is labeled secondary or exploratory where appropriate and is not presented as part of the original prespecification.

Independent gates separate measurement, cohort, implementation, estimation, multiplicity, and release stages. Code or output files alone do not establish completion. A component is complete only when its required independent audit reports PASS.

## Current limitations

Provider attributes are incomplete historical snapshots. Name-based race probabilities may be differently calibrated across groups. Binary administrative sex/gender categories do not cover all identities. Linkage and attribute availability vary by year and setting. Standalone ED files do not capture same-hospital inpatient outcomes, and the AMI work is an ED-only extension rather than an inpatient replication. Fixed effects and rich covariates do not solve nonrandom physician assignment, unmeasured severity, or residual confounding. Accordingly, reported work is framed as association analysis, not causal effect estimation.
