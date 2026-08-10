# Project Development History Source Index

**Purpose:** Controlled source map for reconstructing the Florida ED project's
development history in the technical dossier.

**Evidence boundary:** This index documents what was proposed, attempted, or
reported in project communications. It is not evidence that an analysis was
correct, completed, audited, or supported by final results. Any numerical or
substantive finding must instead trace to a final independently audited project
artifact.

## Preserved email extraction

- Internal source: `tmp/email_context_20260725/emails_extracted.txt`
- SHA-256:
  `e4d62f526f39301cbe1243cad4d8a7d7d6a0195b8848b00f49ab0bfa5cdb432a`
- Bytes: 52,426
- Public disposition: **INTERNAL — DO NOT PUBLISH**
- Reason: the extraction contains names, addresses, correspondence, hypotheses,
  and unaudited statements not appropriate for automatic public release.

The paragraph identifiers below are stable labels embedded in the preserved
extraction. They should be cited in working notes as email-history evidence,
then paraphrased conservatively in the dossier.

## Indexed development-history evidence

| Topic | Preserved paragraph labels | What the evidence supports | What it does not support |
|---|---:|---|---|
| Initial provider-decoding plan | P15–P16 | The early plan contemplated NPI/NPPES lookup, provider gender, specialty, affiliation, and supplemental public-source verification. | Completeness or validity of the eventual provider master. |
| 0.5% sample workflow | P32–P76 | A sample-era workflow linked a 2005 Q1 ED sample to physician data, added demographic/clinical/provider enhancements, created a pseudo-patient key, and organized 143 variables. | Reuse of the sample output as an input to the final full-data analysis. |
| Sample-era physician-race method | P58–P64 | The sample used NPI/NPPES and surname-based race inputs and produced hard provider attributes. | Validity of surname-only race as self-reported identity or as the final Phase 2 measurement method. |
| Sample-era revisit proposal | P128–P135 | A de-identified proxy key was proposed because the source lacked a true patient identifier. | Reliable longitudinal patient identity; the final release correctly treats revisit measures as structurally unavailable where a defensible identifier is absent. |
| Requested full-build enhancements and priority | P154–P155 and P289–P309 | The collaborator requested a standardized merged dataset, diagnosis/procedure decoding and CCS/CCSR mapping, an NPI-linked physician file, provider experience/affiliation/specialty/gender/race fields, visit measures, and summary statistics. | That every requested field was available or scientifically valid in every period. |
| Directional race dyads | P172 | Directional Black–Black, Black–White, White–Black, and White–White combinations were requested. | Prespecification of the later full five-class and 100-cell intersectional extension. |
| Quarter-specific analysis example | P236–P247 | A Q4 2018 workflow was described as integrating patient, physician, and facility attributes. | Independent validation of that earlier quarter-specific output. |
| AMI count concern and coding transition | P324–P328 | The research team identified unexpectedly low AMI counts and recognized the 2015 ICD transition as a key validation issue. | The diagnostic-code examples stated in the email as authoritative definitions; final definitions come from the frozen AMI documentation and validated scripts. |
| Early proposed regression and mechanisms | P354 and P379–P385 | Early discussion proposed directional dyads, transformed outcomes, and information/discretion mechanisms. | Causal identification or empirical confirmation of those mechanisms. |
| Collaborator clinical feedback and endpoints | P591–P630 | Later correspondence discussed communication mechanisms and clarified charges/resource utilization as major endpoints. | A causal conclusion or a substitute for audited empirical findings. |

## Required historical classification

The technical dossier must distinguish:

1. sample-era exploratory engineering and hard-label measurement;
2. the immutable complete Phase 1 encounter release;
3. provider-master v2 measurement and coverage corrections;
4. specifications frozen before adjusted primary-period results;
5. the directional extension added after descriptive/unadjusted outputs but
   before adjusted directional results;
6. historical and AMI analyses maintained as separate tracks; and
7. final independently audited findings.

The 0.5% sample and email discussions are design history only. They do not
control the final cohort, physician-race proxy, estimators, or reported
findings unless a later frozen specification explicitly adopts the element.

