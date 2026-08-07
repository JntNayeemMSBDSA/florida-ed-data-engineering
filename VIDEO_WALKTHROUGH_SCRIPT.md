# Video walkthrough script

Target length: seven to eight minutes.

## Opening — about 35 seconds

This project is a Florida emergency-department data-engineering and observational research workflow. The production database phase is complete: it standardizes 148.7 million encounter records across 76 quarterly partitions. The research phase is still underway, so this walkthrough focuses on the engineering, measurement design, validation, and reproducibility work. I do not show unfinished model findings.

The public repository contains no real encounter rows. What you will see is sanitized production code, aggregate evidence, and a fictional demonstration dataset.

## Research problem — about 40 seconds

The underlying question requires combining patient, physician, facility, clinical, and utilization information over many years. That sounds straightforward until the source changes format, the diagnosis system switches from ICD-9 to ICD-10, provider identifiers behave differently in the historical years, and some attractive outcomes are simply not observable.

My job was to turn that source into a controlled analytical system: preserve every released encounter, standardize the fields, make the joins and clinical mappings auditable, build provider and facility dimensions, and put a hard gate between data preparation and any statistical interpretation.

## Earlier prototype — about 35 seconds

The work began with an approximately 0.5% sample containing 743,767 rows. I used it to develop early decoding, provider and facility enrichment, and reporting ideas for faculty and a physician collaborator.

That sample was useful design history, but I do not present it as a miniature copy of production. Some definitions changed, the provider coverage was narrower, and the final audit framework did not yet exist. The sample data, old outputs, and uncorrected notebooks are not in this repository.

## Production redesign and scale — about 50 seconds

For production, I redesigned the workflow around source quarters. Each quarter is audited, assigned to an approved schema family, transformed independently, and reconciled before it enters the release.

The final Phase 1 fact has 148,686,146 encounter rows, 76 quarterly partitions, and 342 standardized fields. It covers 2005 through 2008 and 2010 through 2024; 2009 and 2025 were excluded by instruction. The generated visit key is unique for every released record, while the source record identifier is never misrepresented as a longitudinal patient ID.

The release passed hard QA and a separate independent validation. Those claims are not typed into the README from memory—the linked evidence files are generated from approved manifests and QA checkpoints and retain their source hashes.

## Five-schema standardization — about 55 seconds

The strongest example of the engineering problem is in `src/phase1/build_ed_partitions.py`. The code recognizes five schema families: the historical 2005–2008 layout, the 2010–2015 Q3 layout, the 2015 Q4–2017 layout, the 2018–2022 layout, and the 2023–2024 layout. An unrecognized schema fails instead of sliding through a loose union.

The same script applies the code-system boundary by quarter: ICD-9-CM through 2015 Q3 and ICD-10-CM beginning in Q4. It creates separate diagnosis, category, procedure, and Elixhauser bridges, and then rejoins aggregate measures to the encounter fact. That structure preserves source slots and mapping provenance without making the main fact impossibly wide.

## Clinical, provider, facility, and visit work — about 55 seconds

Diagnosis categories use CCS for ICD-9 and CCSR for ICD-10. Procedures retain their original system and use the appropriate CCS, ICD-10-PCS, or CPT/HCPCS reference. Elixhauser conditions come from secondary diagnoses with era-specific mappings.

Provider roles stay separate. The dimensions add specialty, experience, hospital and group affiliations, and carefully labeled demographic fields. Facility outputs retain identifier and name history, current CMS attributes, geography, rurality, physician composition, and charge summaries.

The pipeline also makes negative decisions explicit. True triage, same-facility inpatient admission, and reliable revisits are not supported by the source, so they remain structurally unavailable. In the historical years, day-level length of stay is not converted into invented clock hours.

## Provider master v2 — about 60 seconds

Phase 2 starts with provider master v2. It contains 1,813,546 unique NPIs and represents the complete ED-observed NPI universe. The classification rules keep MD/DO physicians, nurse practitioners, physician assistants, other individuals, and organizations distinct. An organization can never be labeled as a physician.

Physician race is a probabilistic, algorithm-inferred full-name measure. It uses official wru name likelihoods, an AAMC Florida physician prior for the primary specification, and the national prior as a sensitivity. It is not BISG because residential geography is not used, and it is not self-reported race.

The primary physician-gender measure uses recorded NPPES or CMS administrative categories. I describe those fields with their limitations; I do not treat them as complete historical or self-identified measures.

## Cohorts, QA, and independent validation — about 55 seconds

The corrected 2010–2024 cohort was rebuilt directly from immutable Phase 1 facts because the earlier Phase 2 version had physician-dependent inclusion rules. All 60 primary-period partitions passed validation, representing 119,543,044 rows.

The 2005–2008 track stays separate. Its 16 partitions and 23,304,846 rows reconcile exactly to Phase 1. Historical linkage relies on a unique Florida license crosswalk rather than a direct source NPI, and the patient race/ethnicity fields are not measurement-equivalent to the modern period. Historical analyses passed an independent audit, but the public repository intentionally withholds their result values.

## Synthetic demonstration — about 40 seconds

For a runnable example, I generate 800 fictional encounters across the five schema eras. Provider labels start with `SYN-NPI`, facilities have clearly fictional names, and no identifier is represented as real.

The demo shows schema mapping, the ICD transition, entity and clinician classification, facility and visit enhancement, and exact input-to-output reconciliation. It does not pretend to reproduce the production scale or the full clinical dictionaries, and it does not estimate concordance associations. The tests compare its aggregate outputs byte for byte with committed expectations.

## Current status and closing — about 45 seconds

The accurate status is: Phase 1 is complete and independently validated. Phase 2 measurement, cohort construction, historical analyses, and analytical specifications are complete. Primary 2010–2024 estimation and final analytical audits remain in progress.

The next work is to finish and independently audit the primary race sequence, then complete the gender, outcome-specific, directional, corrected AMI, multiplicity, and final-release stages. Until those gates pass, I do not report partial coefficients or substantive conclusions.

What this portfolio demonstrates now is the part I can stand behind: a large, schema-aware production build; explicit measurement choices; restartable analytical code; independent QA; conservative interpretation; and a public repository that is reproducible without exposing restricted data.
