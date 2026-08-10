# AMI cohort validation and interpretation

**Validation status:** `PASS_FOR_ED_ONLY_EXTENSION_NOT_REPLICATION`

The primary ED-only AMI cohort uses a principal diagnosis of ICD-9-CM
`410.X1` before the ICD-10-CM transition and principal ICD-10-CM `I21.0`–
`I21.4` or `I21.9` afterward. Type 2 and other myocardial infarctions
(`I21.A1`, `I21.A9`) are separated in sensitivity analyses. `I22` is counted
only in a sensitivity definition and only when an `I21` code is present on
the same visit.

This analysis is **not a replication** of Greenwood, Carnahan, and Huang
(2018). Their study analyzed Florida hospital admissions through the ED and
survival during the hospitalization. The present source is a standalone
emergency-department encounter file. Florida SEDD-style data exclude patients
admitted as inpatients to the same hospital; ED mortality here is therefore
only death recorded within the standalone ED encounter.

Adjusted linear models include flexible age, recorded patient
race/ethnicity, payer, rurality, visit timing, all available
Elixhauser-condition indicators, and physician-volume measures. The
facility-year-quarter specification also includes physician specialty and
experience measures. A second specification adds attending-physician fixed
effects and omits physician attributes that are absorbed. Both use two-way
physician and facility cluster-robust inference.

For a directional external check, the CDC/NCHS 2019 NHAMCS table estimated
378,000 national ED visits (standard error 96,000), or 0.3% of ED visits, with
acute myocardial infarction as the principal diagnosis. This is not an exact
Florida benchmark because it is a national sample and the encounter universe
differs. The internal audit therefore emphasizes year-to-year continuity,
coding-transition behavior, principal-versus-any-listed definitions, and the
share of all Florida standalone ED encounters.

Sources:

- CDC/NCHS and CMS, ICD-9-CM Official Guidelines for Coding and Reporting:
  https://www.cdc.gov/nchs/data/icd/icd9cm_guidelines_2011.pdf
- CDC/NCHS and CMS, ICD-10-CM Official Guidelines for Coding and Reporting:
  https://stacks.cdc.gov/view/cdc/150422/cdc_150422_DS1.pdf
- CDC/NCHS, 2019 NHAMCS ED Summary Tables:
  https://doi.org/10.15620/cdc:115748
- Locked local benchmark provenance:
  external_sources/ami_benchmark/source_manifest.json
- Greenwood BN, Carnahan S, Huang L. *PNAS*. 2018;115(34):8569–8574.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6112736/
- AHRQ HCUP, Florida SEDD file composition:
  https://hcup-us.ahrq.gov/db/state/sedddist/sedddist_filecompfl.jsp
