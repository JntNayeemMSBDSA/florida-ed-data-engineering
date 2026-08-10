import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const args = Object.fromEntries(process.argv.slice(2).map((arg) => {
  const i = arg.indexOf("=");
  if (i < 1) throw new Error(`Arguments must use --name=value: ${arg}`);
  return [arg.slice(2, i), arg.slice(i + 1)];
}));

const projectRoot = args["project-root"];
const portfolioRoot = args["portfolio-root"];
const outputRoot = args["output-root"];
if (!projectRoot || !portfolioRoot || !outputRoot) {
  throw new Error("Required: --project-root, --portfolio-root, --output-root");
}

const dataDir = path.join(outputRoot, "dashboard_data");
const qaTempDir = path.join(outputRoot, "_qa_temp");
await fs.mkdir(dataDir, { recursive: true });
await fs.mkdir(qaTempDir, { recursive: true });

const p1 = path.join(projectRoot, "outputs", "florida_ed_full_build_20260724");
const p2 = path.join(projectRoot, "outputs", "florida_ed_concordance_analysis_20260726");

const sourceDefinitions = {
  SRC_P1_MANIFEST: {
    actual: path.join(p1, "build_manifest_final.json"),
    logical: "outputs/florida_ed_full_build_20260724/build_manifest_final.json",
    classification: "validated project metadata",
  },
  SRC_P1_QA: {
    actual: path.join(p1, "qa", "qa_summary.json"),
    logical: "outputs/florida_ed_full_build_20260724/qa/qa_summary.json",
    classification: "validated aggregate QA",
  },
  SRC_P1_INDEPENDENT: {
    actual: path.join(p1, "qa", "independent_release_validation.json"),
    logical: "outputs/florida_ed_full_build_20260724/qa/independent_release_validation.json",
    classification: "independent aggregate validation",
  },
  SRC_FACT_DICTIONARY: {
    actual: path.join(p1, "documentation", "fact_field_dictionary.csv"),
    logical: "outputs/florida_ed_full_build_20260724/documentation/fact_field_dictionary.csv",
    classification: "metadata dictionary",
  },
  SRC_PAUSE: {
    actual: path.join(p2, "qa", "user_authorized_handoff_pause_20260809T211227Z.json"),
    logical: "outputs/florida_ed_concordance_analysis_20260726/qa/user_authorized_handoff_pause_20260809T211227Z.json",
    classification: "verified project-status checkpoint",
  },
  SRC_PROVIDER_PUBLIC: {
    actual: path.join(portfolioRoot, "evidence", "provider_v2_summary.json"),
    logical: "public_portfolio/evidence/provider_v2_summary.json",
    classification: "whitelisted public-safe aggregate evidence",
  },
  SRC_COHORT_PUBLIC: {
    actual: path.join(portfolioRoot, "evidence", "phase2_cohort_summary.json"),
    logical: "public_portfolio/evidence/phase2_cohort_summary.json",
    classification: "whitelisted public-safe aggregate evidence",
  },
  SRC_HISTORICAL_PUBLIC: {
    actual: path.join(portfolioRoot, "evidence", "historical_validation_summary.json"),
    logical: "public_portfolio/evidence/historical_validation_summary.json",
    classification: "whitelisted public-safe aggregate evidence",
  },
  SRC_PROVIDER_QA: {
    actual: path.join(p2, "qa", "provider_master_v2_qa.json"),
    logical: "outputs/florida_ed_concordance_analysis_20260726/qa/provider_master_v2_qa.json",
    classification: "validated nondisclosive aggregate QA",
  },
  SRC_RACE_QA: {
    actual: path.join(p2, "qa", "provider_race_proxy_v2_qa.json"),
    logical: "outputs/florida_ed_concordance_analysis_20260726/qa/provider_race_proxy_v2_qa.json",
    classification: "validated measurement metadata",
  },
  SRC_GENDER_GATE: {
    actual: path.join(p2, "qa", "provider_gender_measurement_checkpoint.json"),
    logical: "outputs/florida_ed_concordance_analysis_20260726/qa/provider_gender_measurement_checkpoint.json",
    classification: "estimate-blind measurement checkpoint",
  },
  SRC_HISTORICAL_GATE: {
    actual: path.join(p2, "qa", "historical_provider_v2_pre_estimation_gate.json"),
    logical: "outputs/florida_ed_concordance_analysis_20260726/qa/historical_provider_v2_pre_estimation_gate.json",
    classification: "estimate-blind cohort checkpoint",
  },
  SRC_HISTORICAL_AUDIT: {
    actual: path.join(p2, "qa", "independent_historical_results_audit.json"),
    logical: "outputs/florida_ed_concordance_analysis_20260726/qa/independent_historical_results_audit.json",
    classification: "independent aggregate audit metadata",
  },
  SRC_SYNTHETIC_SCHEMA: {
    actual: path.join(portfolioRoot, "synthetic_demo", "expected_outputs", "schema_reconciliation.csv"),
    logical: "public_portfolio/synthetic_demo/expected_outputs/schema_reconciliation.csv",
    classification: "fictional synthetic demonstration",
  },
  SRC_SYNTHETIC_CATEGORY: {
    actual: path.join(portfolioRoot, "synthetic_demo", "expected_outputs", "category_summary.csv"),
    logical: "public_portfolio/synthetic_demo/expected_outputs/category_summary.csv",
    classification: "fictional synthetic demonstration",
  },
  SRC_SYNTHETIC_QA: {
    actual: path.join(portfolioRoot, "synthetic_demo", "expected_outputs", "qa_summary.json"),
    logical: "public_portfolio/synthetic_demo/expected_outputs/qa_summary.json",
    classification: "fictional synthetic demonstration QA",
  },
  SRC_METHOD: {
    actual: path.join(portfolioRoot, "METHODOLOGY.md"),
    logical: "public_portfolio/METHODOLOGY.md",
    classification: "sanitized methodology",
  },
  SRC_PRIVACY: {
    actual: path.join(portfolioRoot, "DATA_ACCESS_AND_PRIVACY.md"),
    logical: "public_portfolio/DATA_ACCESS_AND_PRIVACY.md",
    classification: "sanitized disclosure policy",
  },
};

function assert(condition, message) {
  if (!condition) throw new Error(`VALIDATION FAILURE: ${message}`);
}

async function readJson(file) {
  return JSON.parse(await fs.readFile(file, "utf8"));
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"'; i += 1;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field.replace(/\r$/, "")); rows.push(row); row = []; field = ""; }
    else field += c;
  }
  if (field.length || row.length) { row.push(field.replace(/\r$/, "")); rows.push(row); }
  while (rows.length && rows.at(-1).every((v) => v === "")) rows.pop();
  const headers = rows.shift() ?? [];
  return rows.map((values) => Object.fromEntries(headers.map((h, i) => [h, values[i] ?? ""])));
}

function csvEscape(value) {
  if (value === null || value === undefined) return "";
  const s = value instanceof Date ? value.toISOString().slice(0, 10) : String(value);
  return /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

function toCsv(columns, rows) {
  return [columns.join(","), ...rows.map((r) => columns.map((c) => csvEscape(r[c])).join(","))].join("\n") + "\n";
}

function sha256Buffer(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

async function sha256File(file) {
  return sha256Buffer(await fs.readFile(file));
}

async function writeText(relativePath, text) {
  const target = path.join(outputRoot, relativePath);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, text.replaceAll("\r\n", "\n"), "utf8");
  return target;
}

const sourceArtifacts = {};
for (const [key, def] of Object.entries(sourceDefinitions)) {
  await fs.access(def.actual);
  sourceArtifacts[key] = { ...def, sha256: await sha256File(def.actual) };
}

const phase1Manifest = await readJson(sourceDefinitions.SRC_P1_MANIFEST.actual);
const phase1Qa = await readJson(sourceDefinitions.SRC_P1_QA.actual);
const phase1Independent = await readJson(sourceDefinitions.SRC_P1_INDEPENDENT.actual);
const pause = await readJson(sourceDefinitions.SRC_PAUSE.actual);
const providerPublic = await readJson(sourceDefinitions.SRC_PROVIDER_PUBLIC.actual);
const cohortPublic = await readJson(sourceDefinitions.SRC_COHORT_PUBLIC.actual);
const historicalPublic = await readJson(sourceDefinitions.SRC_HISTORICAL_PUBLIC.actual);
const providerQa = await readJson(sourceDefinitions.SRC_PROVIDER_QA.actual);
const raceQa = await readJson(sourceDefinitions.SRC_RACE_QA.actual);
const genderGate = await readJson(sourceDefinitions.SRC_GENDER_GATE.actual);
const historicalGate = await readJson(sourceDefinitions.SRC_HISTORICAL_GATE.actual);
const historicalAudit = await readJson(sourceDefinitions.SRC_HISTORICAL_AUDIT.actual);
const syntheticQa = await readJson(sourceDefinitions.SRC_SYNTHETIC_QA.actual);
const syntheticSchema = parseCsv(await fs.readFile(sourceDefinitions.SRC_SYNTHETIC_SCHEMA.actual, "utf8"));
const syntheticCategory = parseCsv(await fs.readFile(sourceDefinitions.SRC_SYNTHETIC_CATEGORY.actual, "utf8"));
const factDictionary = parseCsv(await fs.readFile(sourceDefinitions.SRC_FACT_DICTIONARY.actual, "utf8"));

assert(phase1Manifest.expected_quarters === 76, "Phase 1 expected quarter count changed");
assert(phase1Qa.completed_quarters === 76, "Phase 1 is no longer 76/76");
assert(phase1Qa.fact_row_count === 148686146, "Phase 1 encounter count changed");
assert(phase1Manifest.fact_field_count === 342, "Phase 1 field count changed");
assert(phase1Independent.status === "PASS", "Phase 1 independent validation is not PASS");
assert(pause.status === "PAUSED_VERIFIED" && pause.active_project_processes_after_stop === 0, "Verified pause checkpoint is not valid");
assert(pause.completed.primary_race_m1 && pause.completed.primary_race_m2 && pause.completed.primary_race_m3, "Race M1-M3 completion checkpoint changed");
assert(pause.completed.primary_gender_m1, "Gender M1 completion checkpoint changed");
assert(cohortPublic.status === "PASS" && cohortPublic.validated_partitions === 60, "Primary cohort public-safe evidence is not PASS");
assert(historicalPublic.historical_cohort.status === "PASS" && historicalPublic.historical_analysis_audit.status === "PASS", "Historical evidence is not PASS");
assert(providerPublic.provider_master.status === "PASS" && providerQa.qa_passed, "Provider v2 evidence is not PASS");
assert(raceQa.qa_passed && raceQa.out_of_bounds_probability_rows === 0, "Race measurement QA is not PASS");
assert(genderGate.status === "PASS" && genderGate.estimate_blind, "Gender measurement gate is not PASS estimate-blind");
assert(historicalGate.status === "PASS" && historicalAudit.status === "PASS", "Historical gate/audit is not PASS");
assert(syntheticQa.synthetic === true && syntheticQa.overall_status === "PASS", "Synthetic QA is not PASS");
assert(factDictionary.length === 342, "Fact dictionary does not contain 342 fields");

const statusStatement = "Phase 1 complete and independently validated. Phase 2 measurement, cohort construction, historical analyses, and primary race M1-M3 estimation complete; primary gender M1 complete. Remaining primary and sensitivity analyses and the final independent analytical-release audit are pending.";
const disclosure = "PUBLIC_SAFE_PROJECT_METADATA";

const dimSchemaFamily = [
  { SchemaFamilyKey: "SF1", SchemaFamilyLabel: "2005-2008", StartPeriod: "2005 Q1", EndPeriod: "2008 Q4", QuarterCount: 16, DiagnosisEra: "ICD-9-CM", DisplayOrder: 1 },
  { SchemaFamilyKey: "SF2", SchemaFamilyLabel: "2010-2015 Q3", StartPeriod: "2010 Q1", EndPeriod: "2015 Q3", QuarterCount: 23, DiagnosisEra: "ICD-9-CM", DisplayOrder: 2 },
  { SchemaFamilyKey: "SF3", SchemaFamilyLabel: "2015 Q4-2017", StartPeriod: "2015 Q4", EndPeriod: "2017 Q4", QuarterCount: 9, DiagnosisEra: "ICD-10-CM", DisplayOrder: 3 },
  { SchemaFamilyKey: "SF4", SchemaFamilyLabel: "2018-2022", StartPeriod: "2018 Q1", EndPeriod: "2022 Q4", QuarterCount: 20, DiagnosisEra: "ICD-10-CM", DisplayOrder: 4 },
  { SchemaFamilyKey: "SF5", SchemaFamilyLabel: "2023-2024", StartPeriod: "2023 Q1", EndPeriod: "2024 Q4", QuarterCount: 8, DiagnosisEra: "ICD-10-CM", DisplayOrder: 5 },
].map((r) => ({ ...r, DisclosureClass: disclosure }));

function periodAttributes(year, quarter) {
  const excluded = year === 2009 || year === 2025;
  if (excluded) return { group: "Excluded by instruction", groupOrder: 3, schema: "", status: "EXCLUDED", diagnosis: "Not processed", los: "Not processed" };
  if (year <= 2008) return { group: "Historical 2005-2008", groupOrder: 1, schema: "SF1", status: "AVAILABLE", diagnosis: "ICD-9-CM", los: "Day-level LOS only" };
  let schema = "SF2";
  if (year === 2015 && quarter === 4) schema = "SF3";
  else if (year >= 2016 && year <= 2017) schema = "SF3";
  else if (year >= 2018 && year <= 2022) schema = "SF4";
  else if (year >= 2023) schema = "SF5";
  return { group: "Primary 2010-2024", groupOrder: 2, schema, status: "AVAILABLE", diagnosis: schema === "SF2" ? "ICD-9-CM" : "ICD-10-CM", los: "Clock-derived hourly LOS eligible in Phase 2" };
}

const dimPeriod = [];
const factPartitionStatus = [];
for (let year = 2005; year <= 2025; year += 1) {
  for (let quarter = 1; quarter <= 4; quarter += 1) {
    const a = periodAttributes(year, quarter);
    const periodKey = year * 10 + quarter;
    dimPeriod.push({
      PeriodKey: periodKey, Year: year, Quarter: quarter, QuarterLabel: `Q${quarter}`,
      YearQuarter: `${year} Q${quarter}`, PeriodGroup: a.group, PeriodGroupOrder: a.groupOrder,
      AvailableFlag: a.status === "AVAILABLE" ? 1 : 0, DisclosureClass: disclosure,
    });
    factPartitionStatus.push({
      PartitionKey: `PT${periodKey}`, PeriodKey: periodKey, SchemaFamilyKey: a.schema,
      PartitionStatus: a.status === "AVAILABLE" ? "COMPLETE" : "EXCLUDED",
      ReconciliationStatus: a.status === "AVAILABLE" ? "PASS" : "NOT_APPLICABLE",
      AvailableFlag: a.status === "AVAILABLE" ? 1 : 0,
      ExclusionReason: a.status === "AVAILABLE" ? "" : "Year excluded by project instruction",
      DiagnosisCodeEra: a.diagnosis, LengthOfStayAvailability: a.los,
      SourceClass: "Project metadata; no encounter rows", DisclosureClass: disclosure,
    });
  }
}
assert(dimPeriod.filter((r) => r.AvailableFlag === 1).length === 76, "Generated period coverage is not 76 quarters");

const dimProjectStage = [
  { StageKey: "S01", StageName: "Phase 1 data engineering", StageOrder: 1, StagePurpose: "Standardize, decode, enhance, reconcile, and validate encounter data" },
  { StageKey: "S02", StageName: "Phase 2 measurement and cohorts", StageOrder: 2, StagePurpose: "Correct provider coverage, define measurements, and rebuild cohorts" },
  { StageKey: "S03", StageName: "Historical analyses", StageOrder: 3, StagePurpose: "Analyze 2005-2008 separately using comparable variables" },
  { StageKey: "S04", StageName: "Primary analyses", StageOrder: 4, StagePurpose: "Estimate 2010-2024 association models and sensitivities" },
  { StageKey: "S05", StageName: "Release and handoff", StageOrder: 5, StagePurpose: "Independent audit, reporting, documentation, and controlled sharing" },
].map((r) => ({ ...r, DisclosureClass: disclosure }));

const dimClinicalDomain = [
  ["CD01", "Clinical coding", 1], ["CD02", "Comorbidity", 2], ["CD03", "Patient demographics", 3],
  ["CD04", "Visit operations", 4], ["CD05", "Disposition and outcomes", 5], ["CD06", "Charges", 6],
  ["CD07", "Provider measurement", 7], ["CD08", "Facility measurement", 8], ["CD09", "Unsupported measures", 9],
].map(([ClinicalDomainKey, ClinicalDomainName, DisplayOrder]) => ({ ClinicalDomainKey, ClinicalDomainName, DisplayOrder, DisclosureClass: disclosure }));

const dimCodingMap = [
  ["CM01", "ICD-9-CM diagnosis", "2005-2015 Q3", "CCS", "Era-specific diagnosis grouping"],
  ["CM02", "ICD-10-CM diagnosis", "2015 Q4-2024", "CCSR", "Era-specific diagnosis grouping"],
  ["CM03", "ICD-9-CM procedure", "When reported", "CCS", "Procedure grouping"],
  ["CM04", "ICD-10-PCS procedure", "When reported", "Procedure Classes Refined", "Procedure grouping"],
  ["CM05", "CPT/HCPCS", "When reported", "CCS Services and Procedures plus permitted descriptions", "Current descriptions are reference aids, not historical codebooks"],
  ["CM06", "Secondary diagnoses", "All supported eras", "Elixhauser, era-specific", "External-cause fields excluded from comorbidities"],
].map(([CodingMapKey, SourceCodeSystem, ApplicablePeriod, TargetGrouping, Guardrail], i) => ({ CodingMapKey, SourceCodeSystem, ApplicablePeriod, TargetGrouping, Guardrail, DisplayOrder: i + 1, DisclosureClass: disclosure }));

const dimModelSpec = [
  { ModelSpecKey: "MS1", ModelLabel: "M1 - Patient adjusted", ModelOrder: 1, PlainLanguageDefinition: "Adjusts for measured patient characteristics and the frozen baseline covariates.", FixedEffectsSummary: "Baseline specification", ClusteringSummary: "Two-way physician and facility clustering where specified" },
  { ModelSpecKey: "MS2", ModelLabel: "M2 - Facility/time/clinical adjusted", ModelOrder: 2, PlainLanguageDefinition: "Adds facility-year-quarter and clinical fixed effects to compare more similar settings and clinical groups.", FixedEffectsSummary: "Facility-year-quarter and clinical fixed effects", ClusteringSummary: "Two-way physician and facility clustering" },
  { ModelSpecKey: "MS3", ModelLabel: "M3 - Physician fixed effects", ModelOrder: 3, PlainLanguageDefinition: "Adds physician fixed effects while retaining the frozen facility/time/clinical structure.", FixedEffectsSummary: "Physician plus facility-year-quarter and clinical fixed effects", ClusteringSummary: "Two-way physician and facility clustering" },
].map((r) => ({ ...r, DisclosureClass: disclosure }));

const metricDefs = [
  ["M001", "Project scale", "Validated encounter records", "records", "#,##0", "One released record per validated Phase 1 encounter row", 1],
  ["M002", "Project scale", "Completed quarterly partitions", "quarters", "0", "Quarter partitions completed and reconciled", 2],
  ["M003", "Project scale", "Covered years", "years", "0", "Distinct included years", 3],
  ["M004", "Project scale", "Standardized encounter fields", "fields", "0", "Fields in the canonical encounter fact", 4],
  ["M005", "Project scale", "Schema families", "families", "0", "Approved historical layouts", 5],
  ["M006", "Dimensions", "Facility dimension rows", "facilities", "#,##0", "One row per state facility identifier", 6],
  ["M007", "Dimensions", "Phase 1 provider master rows", "NPIs", "#,##0", "One row per NPI in the Phase 1 provider master", 7],
  ["M008", "Cohorts", "Primary cohort rows", "encounters", "#,##0", "Rebuilt 2010-2024 Phase 2 cohort", 8],
  ["M009", "Cohorts", "Primary cohort partitions", "quarters", "0", "Validated primary-period partitions", 9],
  ["M010", "Cohorts", "Historical cohort rows", "encounters", "#,##0", "Separate 2005-2008 historical cohort", 10],
  ["M011", "Cohorts", "Historical cohort partitions", "quarters", "0", "Reconciled historical partitions", 11],
  ["M012", "Development", "Exploratory prototype rows", "encounters", "#,##0", "Approximate 0.5% prototype; not the production release", 12],
  ["M013", "Synthetic demonstration", "Synthetic demonstration rows", "fictional rows", "#,##0", "Deterministic fictional demonstration", 13],
  ["M014", "Project scale", "Expected in-scope quarters", "quarters", "0", "Four quarters for each of 19 included years", 14],
  ["PM001", "Provider coverage", "Provider master v2 unique NPIs", "NPIs", "#,##0", "One-row-per-NPI provider master v2", 101],
  ["PM002", "Provider coverage", "ED-observed distinct NPIs", "NPIs", "#,##0", "Distinct validated NPIs observed in selected ED roles", 102],
  ["PM003", "Provider coverage", "Phase 1-linked ED-observed NPIs", "NPIs", "#,##0", "ED-observed NPIs represented in the Phase 1 master", 103],
  ["PM004", "Provider coverage", "Newly added ED-observed NPIs", "NPIs", "#,##0", "ED-observed NPIs added by provider master v2", 104],
  ["PM005", "Provider coverage", "ED-observed individual NPIs", "NPIs", "#,##0", "Entity category is individual", 105],
  ["PM006", "Provider coverage", "ED-observed organizational NPIs", "NPIs", "#,##0", "Entity category is organization; never classified as physician", 106],
  ["PM007", "Clinician classification", "ED-observed MD/DO NPIs", "NPIs", "#,##0", "Individual MD/DO clinician category", 107],
  ["PM008", "Clinician classification", "ED-observed NP NPIs", "NPIs", "#,##0", "Nurse practitioner category", 108],
  ["PM009", "Clinician classification", "ED-observed PA NPIs", "NPIs", "#,##0", "Physician assistant category", 109],
  ["PM010", "Entity safeguard", "Organizational NPIs classified as physicians", "NPIs", "0", "Must remain zero", 110],
  ["PM011", "Provider QA", "Duplicate NPIs in provider master v2", "NPIs", "0", "Must remain zero", 111],
].map(([MetricKey, MetricGroup, MetricName, Unit, FormatString, MetricDefinition, DisplayOrder]) => ({ MetricKey, MetricGroup, MetricName, Unit, FormatString, MetricDefinition, DisplayOrder, DisclosureClass: disclosure }));

const projectMetricValues = {
  M001: phase1Qa.fact_row_count,
  M002: phase1Qa.completed_quarters,
  M003: phase1Manifest.scope_years.length,
  M004: phase1Manifest.fact_field_count,
  M005: 5,
  M006: phase1Qa.facility_master_row_count,
  M007: phase1Qa.physician_master_row_count,
  M008: cohortPublic.cohort_rows,
  M009: cohortPublic.validated_partitions,
  M010: historicalPublic.historical_cohort.cohort_rows,
  M011: historicalPublic.historical_cohort.reconciled_partitions,
  M012: 743767,
  M013: syntheticQa.standardized_rows,
  M014: phase1Manifest.expected_quarters,
};
const projectMetricSources = {
  M001: "SRC_P1_QA", M002: "SRC_P1_QA", M003: "SRC_P1_MANIFEST", M004: "SRC_P1_MANIFEST",
  M005: "SRC_P1_MANIFEST", M006: "SRC_P1_QA", M007: "SRC_P1_QA", M008: "SRC_COHORT_PUBLIC",
  M009: "SRC_COHORT_PUBLIC", M010: "SRC_HISTORICAL_PUBLIC", M011: "SRC_HISTORICAL_PUBLIC",
  M012: "SRC_METHOD", M013: "SRC_SYNTHETIC_QA", M014: "SRC_P1_MANIFEST",
};
const factProjectCoverage = Object.entries(projectMetricValues).map(([MetricKey, MetricValue]) => ({
  ProjectMetricKey: `PC_${MetricKey}`, MetricKey, MetricValue, MetricStatus: "VALIDATED",
  AsOfDate: MetricKey.startsWith("M01") && MetricKey !== "M014" ? "2026-08-06" : "2026-07-26",
  SourceArtifactKey: projectMetricSources[MetricKey], DisclosureClass: disclosure,
}));

const pc = providerPublic.ed_observed_provider_counts;
const providerMetricValues = {
  PM001: providerPublic.provider_master.unique_npis,
  PM002: pc.ed_observed_npis,
  PM003: pc.phase1_linked_ed_observed_npis,
  PM004: pc.newly_added_ed_observed_npis,
  PM005: pc.ed_observed_individual_npis,
  PM006: pc.ed_observed_organization_npis,
  PM007: pc.ed_observed_md_do_npis,
  PM008: pc.ed_observed_np_npis,
  PM009: pc.ed_observed_pa_npis,
  PM010: pc.organizational_npis_classified_md_do,
  PM011: providerPublic.provider_master.duplicate_npis,
};
const factProviderMeasurement = Object.entries(providerMetricValues).map(([MetricKey, MetricValue]) => ({
  ProviderMetricKey: `PV_${MetricKey}`, MetricKey, MetricValue, MetricStatus: "VALIDATED",
  MeasurementScope: MetricKey === "PM001" || MetricKey === "PM011" ? "Full provider master v2" : "ED-observed provider universe",
  SourceArtifactKey: "SRC_PROVIDER_PUBLIC", DisclosureClass: disclosure,
}));

const factEnhancementCoverage = [
  ["E001", "CD01", "Diagnosis decoding", "IMPLEMENTED", "All in-scope years", "Era-aware normalized diagnosis occurrences", "Do not mix ICD-9-CM and ICD-10-CM definitions"],
  ["E002", "CD01", "Procedure decoding", "IMPLEMENTED", "Subject to reported source fields", "Preserves position and code-system semantics", "CPT/HCPCS descriptions are reference aids"],
  ["E003", "CD01", "CCS mapping", "IMPLEMENTED", "ICD-9-CM diagnoses and procedures", "Clinically meaningful grouping", "Era-specific"],
  ["E004", "CD01", "CCSR mapping", "IMPLEMENTED", "ICD-10-CM diagnoses", "Clinically meaningful grouping", "Era-specific"],
  ["E005", "CD02", "Elixhauser comorbidities", "IMPLEMENTED", "All supported eras", "Secondary-diagnosis, era-specific mapping", "External-cause fields excluded"],
  ["E006", "CD03", "Decoded demographics", "IMPLEMENTED", "All in-scope years subject to source definitions", "Preserves raw values plus standardized categories", "Historical definitions are not overwritten"],
  ["E007", "CD04", "Arrival timing and off-hours", "IMPLEMENTED", "All in-scope years with source-hour validation", "Arrival hour, time band, weekend, and off-hours", "Arrival hour does not create historical hourly LOS"],
  ["E008", "CD05", "Disposition grouping", "IMPLEMENTED", "All in-scope years", "Decoded discharge disposition groups", "Not proof of same-facility inpatient admission"],
  ["E009", "CD04", "Payer grouping", "IMPLEMENTED", "All in-scope years", "Decoded payer label and analytical group", "Source semantics vary historically"],
  ["E010", "CD04", "Procedure counts", "IMPLEMENTED", "All in-scope years", "CPT/HCPCS plus ICD procedures where those fields exist", "Scope field records era differences"],
  ["E011", "CD06", "Total charges and reconciliation", "IMPLEMENTED", "All in-scope years", "Reported total prioritized; component diagnostics retained", "Charges are not costs or payments"],
  ["E012", "CD04", "Length of stay in days", "IMPLEMENTED", "All in-scope years", "Preserved day-level measure", "Historical day-level values are not relabeled as hours"],
  ["E013", "CD04", "Clock-derived hourly LOS", "IMPLEMENTED_PRIMARY_ONLY", "Primary 2010-2024", "Day count plus validated arrival/discharge hours", "Never imputed for 2005-2008"],
  ["E014", "CD04", "E/M acuity proxy", "PROXY_ONLY", "Where valid ED E/M codes are present", "Ordinal billing-code proxy", "Not clinical triage"],
  ["E015", "CD09", "True clinical triage", "STRUCTURALLY_UNAVAILABLE", "All in-scope years", "Reserved null field", "Source extract has no clinical triage scale"],
  ["E016", "CD09", "Same-facility inpatient admission", "STRUCTURALLY_UNAVAILABLE", "All in-scope years", "Reserved null field", "Not directly observed; transfer/disposition not substituted"],
  ["E017", "CD09", "Seven-day revisit", "STRUCTURALLY_UNAVAILABLE", "All in-scope years", "Reserved null field", "No stable patient identifier and exact encounter date"],
  ["E018", "CD09", "Thirty-day revisit", "STRUCTURALLY_UNAVAILABLE", "All in-scope years", "Reserved null field", "No stable patient identifier and exact encounter date"],
  ["E019", "CD07", "Provider master v2", "IMPLEMENTED", "Full provider universe and ED-observed subset", "NPPES, CMS, and Florida DOH enrichment", "Most external attributes are current snapshots"],
  ["E020", "CD08", "Facility master and affiliations", "IMPLEMENTED", "Facility and provider-facility metadata", "Controlled identifiers, current public attributes, and encounter-year activity", "Current affiliation is not historical employment proof"],
].map(([EnhancementKey, ClinicalDomainKey, EnhancementName, ImplementationStatus, AvailabilityScope, MethodSummary, InterpretationGuardrail], i) => ({
  EnhancementKey, ClinicalDomainKey, EnhancementName, ImplementationStatus, AvailabilityScope, MethodSummary,
  InterpretationGuardrail, DisplayOrder: i + 1, SourceArtifactKey: i >= 18 ? "SRC_METHOD" : "SRC_FACT_DICTIONARY", DisclosureClass: disclosure,
}));

const factValidationStatus = [
  ["V001", "S01", "Source-to-fact row reconciliation", "PASS", "148,686,146 fact rows equal the reconciled quarter total", "SRC_P1_QA"],
  ["V002", "S01", "Generated encounter-key uniqueness", "PASS", "148,686,146 distinct keys for 148,686,146 fact rows", "SRC_P1_QA"],
  ["V003", "S01", "Excluded-year enforcement", "PASS", "Zero released rows from 2009 and 2025", "SRC_P1_QA"],
  ["V004", "S01", "ICD transition enforcement", "PASS", "Zero ICD-era transition errors", "SRC_P1_QA"],
  ["V005", "S01", "Unsupported-measure semantics", "PASS", "Triage, revisit, and same-facility admission fields remain structural nulls", "SRC_P1_QA"],
  ["V006", "S01", "Facility master uniqueness", "PASS", "240 rows and 240 distinct state facility identifiers", "SRC_P1_QA"],
  ["V007", "S01", "Phase 1 provider-master uniqueness", "PASS", "1,805,795 rows and distinct NPIs", "SRC_P1_QA"],
  ["V008", "S01", "Independent Phase 1 release validation", "PASS", "Required release artifacts and structural checks passed", "SRC_P1_INDEPENDENT"],
  ["V009", "S02", "Provider master v2 uniqueness", "PASS", "1,813,546 unique NPIs and zero duplicates", "SRC_PROVIDER_PUBLIC"],
  ["V010", "S02", "Complete ED-observed NPI universe", "PASS", "Zero ED-observed validated NPIs absent from provider master v2", "SRC_PROVIDER_PUBLIC"],
  ["V011", "S02", "Entity-classification safeguard", "PASS", "Zero organizational NPIs classified as MD/DO", "SRC_PROVIDER_PUBLIC"],
  ["V012", "S02", "Physician-race probability QA", "PASS", "Probability bounds and sum-to-one checks passed", "SRC_RACE_QA"],
  ["V013", "S02", "Physician-gender measurement gate", "PASS", "Estimate-blind recorded-source definition checkpoint passed", "SRC_GENDER_GATE"],
  ["V014", "S02", "Primary cohort reconciliation", "PASS", "60 of 60 primary partitions validated", "SRC_COHORT_PUBLIC"],
  ["V015", "S02", "Phase 1 source immutability in cohort rebuild", "PASS", "Source release was not modified", "SRC_COHORT_PUBLIC"],
  ["V016", "S03", "Historical cohort reconciliation", "PASS", "16 of 16 historical partitions reconciled", "SRC_HISTORICAL_GATE"],
  ["V017", "S03", "Historical hourly-LOS safeguard", "PASS", "Zero prohibited hourly-LOS constructions", "SRC_HISTORICAL_GATE"],
  ["V018", "S03", "Independent historical-results audit", "PASS", "38 of 38 checks passed; findings are not disclosed", "SRC_HISTORICAL_AUDIT"],
  ["V019", "S05", "Verified restart-safe pause", "PAUSED_VERIFIED", "No project process active after the authorized stop", "SRC_PAUSE"],
  ["V020", "S05", "Synthetic schema reconciliation", "PASS", "800 fictional rows reproduced across five schema families", "SRC_SYNTHETIC_QA"],
].map(([ValidationKey, StageKey, ValidationCheck, ValidationStatus, EvidenceSummary, SourceArtifactKey], i) => ({
  ValidationKey, StageKey, ValidationCheck, ValidationStatus, EvidenceSummary, CheckOrder: i + 1, SourceArtifactKey, DisclosureClass: disclosure,
}));

const factAnalyticalStatus = [
  ["A001", "S01", "", "Phase 1 database construction", "COMPLETE", "PASS", "Immutable release available"],
  ["A002", "S01", "", "Phase 1 independent validation", "COMPLETE", "PASS", "No further Phase 1 work required unless a controlled correction is approved"],
  ["A003", "S02", "", "Provider master v2", "COMPLETE", "PASS", "Use v2 for all physician-dependent work"],
  ["A004", "S02", "", "Race measurement gate", "COMPLETE", "PASS", "Retain probability-weighted and multiple-imputation sensitivities"],
  ["A005", "S02", "", "Gender measurement gate", "COMPLETE", "PASS", "Retain recorded-source conflict sensitivity"],
  ["A006", "S02", "", "Primary 2010-2024 cohort", "COMPLETE", "PASS", "Use rebuilt cohort from immutable Phase 1 facts"],
  ["A007", "S03", "", "Historical 2005-2008 cohort", "COMPLETE", "PASS", "Keep separate and use comparable variables only"],
  ["A008", "S03", "", "Historical analyses", "COMPLETE", "PASS", "Findings remain undisclosed in the public dashboard"],
  ["A009", "S04", "MS1", "Primary race M1 estimation", "COMPLETE", "PENDING", "Bind to final family-level audit before interpretation"],
  ["A010", "S04", "MS2", "Primary race M2 estimation", "COMPLETE", "PENDING", "Bind to final family-level audit before interpretation"],
  ["A011", "S04", "MS3", "Primary race M3 estimation", "COMPLETE", "PENDING", "Bind to final family-level audit before interpretation"],
  ["A012", "S04", "MS1", "Primary gender M1 estimation", "COMPLETE", "PENDING", "Continue from the verified pause checkpoint"],
  ["A013", "S04", "MS2", "Primary gender M2 estimation", "PENDING", "PENDING", "Restart gender M2 from its beginning after hash validation"],
  ["A014", "S04", "MS3", "Primary gender M3 estimation", "PENDING", "PENDING", "Run only after gender M2 commits and passes its checkpoint"],
  ["A015", "S04", "", "Outcome-specific models and sensitivities", "PENDING", "PENDING", "Use complete eligible outcome-specific samples"],
  ["A016", "S04", "", "Directional gender, race, and intersectional dyads", "PENDING", "PENDING", "Plans and implementation gates exist; fitted-result audits remain"],
  ["A017", "S04", "", "Corrected primary AMI/Greenwood extension", "PENDING", "PENDING", "ED-only observational extension; never call an inpatient replication"],
  ["A018", "S04", "", "Multiplicity procedures", "PENDING", "PENDING", "Apply only after all eligible result families are complete"],
  ["A019", "S05", "", "Final independent analytical-release audit", "PENDING", "PENDING", "Required before analytical release can pass"],
  ["A020", "S05", "", "Report and public-release production", "DEFERRED", "NOT_APPLICABLE", "Deferred by user; this dashboard preparation is a separate portfolio layer"],
].map(([AnalyticalStatusKey, StageKey, ModelSpecKey, ComponentName, ComponentStatus, IndependentAuditStatus, NextAction], i) => ({
  AnalyticalStatusKey, StageKey, ModelSpecKey, ComponentName, ComponentStatus,
  StatusOrder: { COMPLETE: 1, "IN PROGRESS": 2, PENDING: 3, DEFERRED: 4 }[ComponentStatus],
  IndependentAuditStatus, NextAction, StatusAsOf: "2026-08-09", SourceArtifactKey: "SRC_PAUSE", DisclosureClass: disclosure,
}));

const factSyntheticDemonstration = [];
let demoIndex = 1;
for (const row of syntheticSchema) {
  factSyntheticDemonstration.push({ DemoMetricKey: `SD${String(demoIndex++).padStart(3, "0")}`, DemoSection: "Schema reconciliation", Category: row.schema_family, MetricName: "Input rows", MetricValue: Number(row.input_rows), DemoStatus: row.status, SyntheticFlag: true, SourceArtifactKey: "SRC_SYNTHETIC_SCHEMA", DisclosureClass: "SYNTHETIC_PUBLIC_SAFE" });
  factSyntheticDemonstration.push({ DemoMetricKey: `SD${String(demoIndex++).padStart(3, "0")}`, DemoSection: "Schema reconciliation", Category: row.schema_family, MetricName: "Output rows", MetricValue: Number(row.output_rows), DemoStatus: row.status, SyntheticFlag: true, SourceArtifactKey: "SRC_SYNTHETIC_SCHEMA", DisclosureClass: "SYNTHETIC_PUBLIC_SAFE" });
}
for (const row of syntheticCategory) {
  factSyntheticDemonstration.push({ DemoMetricKey: `SD${String(demoIndex++).padStart(3, "0")}`, DemoSection: "Clinical category demonstration", Category: row.diagnosis_category, MetricName: "Synthetic rows", MetricValue: Number(row.synthetic_rows), DemoStatus: "PASS", SyntheticFlag: true, SourceArtifactKey: "SRC_SYNTHETIC_CATEGORY", DisclosureClass: "SYNTHETIC_PUBLIC_SAFE" });
}

const tableSchemas = {
  DimPeriod: {
    grain: "One row per calendar quarter from 2005 Q1 through 2025 Q4",
    primaryKey: ["PeriodKey"],
    columns: [
      ["PeriodKey", "Whole number", "Surrogate year-quarter key", "", "", "SRC_P1_MANIFEST", "Generated as year times 10 plus quarter", "Use on Coverage page"],
      ["Year", "Whole number", "Calendar year", "", "", "SRC_P1_MANIFEST", "Generated from validated scope", "Axis and slicer"],
      ["Quarter", "Whole number", "Quarter number 1-4", "", "", "SRC_P1_MANIFEST", "Generated", "Sort QuarterLabel"],
      ["QuarterLabel", "Text", "Display label Q1-Q4", "", "", "SRC_P1_MANIFEST", "Generated", "Matrix columns"],
      ["YearQuarter", "Text", "Human-readable period", "", "", "SRC_P1_MANIFEST", "Generated", "Tooltip"],
      ["PeriodGroup", "Text", "Historical, primary, or excluded grouping", "", "", "SRC_P1_MANIFEST", "Rules from frozen scope", "Legend and slicer"],
      ["PeriodGroupOrder", "Whole number", "Sort order for PeriodGroup", "", "", "SRC_P1_MANIFEST", "Generated", "Sort field"],
      ["AvailableFlag", "Whole number", "1 for included quarter, 0 for excluded quarter", "Included quarter", "All calendar quarters", "SRC_P1_MANIFEST", "Generated", "Coverage measure"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  DimSchemaFamily: {
    grain: "One row per approved historical source-schema family",
    primaryKey: ["SchemaFamilyKey"],
    columns: [
      ["SchemaFamilyKey", "Text", "Schema-family key", "", "", "SRC_P1_MANIFEST", "Controlled key", "Relationship key"],
      ["SchemaFamilyLabel", "Text", "Covered period", "", "", "SRC_P1_MANIFEST", "Validated family label", "Axis and table"],
      ["StartPeriod", "Text", "First covered quarter", "", "", "SRC_P1_MANIFEST", "Derived", "Table"],
      ["EndPeriod", "Text", "Last covered quarter", "", "", "SRC_P1_MANIFEST", "Derived", "Table"],
      ["QuarterCount", "Whole number", "Number of covered quarters", "Covered quarters", "", "SRC_P1_MANIFEST", "Count of generated in-scope quarters", "Bar value"],
      ["DiagnosisEra", "Text", "Diagnosis coding era", "", "", "SRC_METHOD", "Era rule", "Table"],
      ["DisplayOrder", "Whole number", "Schema-family sort order", "", "", "SRC_P1_MANIFEST", "Chronological", "Sort field"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  DimProjectStage: {
    grain: "One row per project stage",
    primaryKey: ["StageKey"],
    columns: [
      ["StageKey", "Text", "Project-stage key", "", "", "SRC_PAUSE", "Controlled key", "Relationship key"],
      ["StageName", "Text", "Project-stage label", "", "", "SRC_METHOD", "Controlled vocabulary", "Axis and matrix"],
      ["StageOrder", "Whole number", "Project-stage order", "", "", "SRC_METHOD", "Workflow order", "Sort field"],
      ["StagePurpose", "Text", "Plain-language purpose", "", "", "SRC_METHOD", "Summarized", "Tooltip"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  DimMetric: {
    grain: "One row per dashboard metric",
    primaryKey: ["MetricKey"],
    columns: [
      ["MetricKey", "Text", "Metric key", "", "", "SRC_P1_MANIFEST", "Controlled key", "Relationship key"],
      ["MetricGroup", "Text", "Metric family", "", "", "SRC_METHOD", "Curated", "Visual filter"],
      ["MetricName", "Text", "Display name", "", "", "SRC_METHOD", "Curated", "Axis and tooltip"],
      ["Unit", "Text", "Measurement unit", "", "", "SRC_METHOD", "Curated", "Tooltip"],
      ["FormatString", "Text", "Recommended Power BI number format", "", "", "SRC_METHOD", "Curated", "Model formatting"],
      ["MetricDefinition", "Text", "Metric definition", "", "", "SRC_METHOD", "Curated", "Tooltip and dictionary"],
      ["DisplayOrder", "Whole number", "Metric sort order", "", "", "SRC_METHOD", "Curated", "Sort field"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  DimClinicalDomain: {
    grain: "One row per clinical or enhancement domain",
    primaryKey: ["ClinicalDomainKey"],
    columns: [
      ["ClinicalDomainKey", "Text", "Clinical-domain key", "", "", "SRC_METHOD", "Controlled key", "Relationship key"],
      ["ClinicalDomainName", "Text", "Clinical-domain label", "", "", "SRC_METHOD", "Curated", "Axis and table"],
      ["DisplayOrder", "Whole number", "Domain sort order", "", "", "SRC_METHOD", "Curated", "Sort field"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  DimCodingMap: {
    grain: "One row per source-code-system to grouping rule",
    primaryKey: ["CodingMapKey"],
    columns: [
      ["CodingMapKey", "Text", "Coding-map key", "", "", "SRC_METHOD", "Controlled key", "Hidden key"],
      ["SourceCodeSystem", "Text", "Input code system", "", "", "SRC_METHOD", "Method summary", "Table"],
      ["ApplicablePeriod", "Text", "Applicable period or availability condition", "", "", "SRC_METHOD", "Method summary", "Table"],
      ["TargetGrouping", "Text", "Decoder or grouping target", "", "", "SRC_METHOD", "Method summary", "Table"],
      ["Guardrail", "Text", "Interpretation limitation", "", "", "SRC_METHOD", "Method summary", "Table"],
      ["DisplayOrder", "Whole number", "Display order", "", "", "SRC_METHOD", "Curated", "Sort field"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  DimModelSpec: {
    grain: "One row per M1-M3 model stage",
    primaryKey: ["ModelSpecKey"],
    columns: [
      ["ModelSpecKey", "Text", "Model-stage key", "", "", "SRC_METHOD", "Controlled key", "Relationship key"],
      ["ModelLabel", "Text", "Model-stage label", "", "", "SRC_METHOD", "Frozen model sequence", "Table"],
      ["ModelOrder", "Whole number", "Model-stage order", "", "", "SRC_METHOD", "Frozen model sequence", "Sort field"],
      ["PlainLanguageDefinition", "Text", "Nontechnical model explanation", "", "", "SRC_METHOD", "Summarized", "Table and tooltip"],
      ["FixedEffectsSummary", "Text", "Fixed-effects summary", "", "", "SRC_METHOD", "Summarized", "Table"],
      ["ClusteringSummary", "Text", "Inference clustering summary", "", "", "SRC_METHOD", "Summarized", "Table"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  FactProjectCoverage: {
    grain: "One row per high-level project metric",
    primaryKey: ["ProjectMetricKey"],
    columns: [
      ["ProjectMetricKey", "Text", "Project-metric row key", "", "", "SRC_P1_MANIFEST", "Generated", "Hidden key"],
      ["MetricKey", "Text", "Metric foreign key", "", "", "SRC_P1_MANIFEST", "Mapped to DimMetric", "Relationship key"],
      ["MetricValue", "Whole number", "Validated aggregate metric value", "", "", "SRC_P1_MANIFEST", "Allowlisted extraction", "Cards and measures"],
      ["MetricStatus", "Text", "Validation status", "", "", "SRC_P1_QA", "Controlled vocabulary", "Tooltip"],
      ["AsOfDate", "Date", "Evidence snapshot date", "", "", "SRC_P1_QA", "Source date", "Tooltip"],
      ["SourceArtifactKey", "Text", "Provenance source key", "", "", "SRC_P1_MANIFEST", "Mapped to provenance ledger", "Hidden metadata"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  FactPartitionStatus: {
    grain: "One row per calendar quarter from 2005 Q1 through 2025 Q4",
    primaryKey: ["PartitionKey"],
    columns: [
      ["PartitionKey", "Text", "Partition-status row key", "", "", "SRC_P1_MANIFEST", "Generated", "Hidden key"],
      ["PeriodKey", "Whole number", "Period foreign key", "", "", "SRC_P1_MANIFEST", "Mapped to DimPeriod", "Relationship key"],
      ["SchemaFamilyKey", "Text", "Schema-family foreign key; blank when excluded", "", "", "SRC_P1_MANIFEST", "Frozen family rules", "Relationship key"],
      ["PartitionStatus", "Text", "COMPLETE or EXCLUDED", "", "", "SRC_P1_QA", "Controlled vocabulary", "Matrix status"],
      ["ReconciliationStatus", "Text", "PASS or NOT_APPLICABLE", "", "", "SRC_P1_QA", "Controlled vocabulary", "Matrix status"],
      ["AvailableFlag", "Whole number", "1 if included, otherwise 0", "Included quarter", "Calendar quarter", "SRC_P1_MANIFEST", "Generated", "Column chart"],
      ["ExclusionReason", "Text", "Reason a quarter is not processed", "", "", "SRC_P1_MANIFEST", "Frozen scope", "Tooltip"],
      ["DiagnosisCodeEra", "Text", "ICD diagnosis era", "", "", "SRC_METHOD", "Quarter-aware rule", "Tooltip"],
      ["LengthOfStayAvailability", "Text", "LOS granularity and period limitation", "", "", "SRC_METHOD", "Comparability rule", "Tooltip"],
      ["SourceClass", "Text", "Data-source classification", "", "", "SRC_PRIVACY", "Curated", "Hidden metadata"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  FactEnhancementCoverage: {
    grain: "One row per implemented, proxy, or structurally unavailable enhancement",
    primaryKey: ["EnhancementKey"],
    columns: [
      ["EnhancementKey", "Text", "Enhancement key", "", "", "SRC_FACT_DICTIONARY", "Controlled key", "Hidden key"],
      ["ClinicalDomainKey", "Text", "Clinical-domain foreign key", "", "", "SRC_FACT_DICTIONARY", "Curated mapping", "Relationship key"],
      ["EnhancementName", "Text", "Enhancement label", "", "", "SRC_FACT_DICTIONARY", "Curated", "Table and axis"],
      ["ImplementationStatus", "Text", "IMPLEMENTED, IMPLEMENTED_PRIMARY_ONLY, PROXY_ONLY, or STRUCTURALLY_UNAVAILABLE", "", "", "SRC_FACT_DICTIONARY", "Controlled vocabulary", "Bar and legend"],
      ["AvailabilityScope", "Text", "Period or source-field availability", "", "", "SRC_FACT_DICTIONARY", "Summarized", "Table"],
      ["MethodSummary", "Text", "Plain-language method", "", "", "SRC_METHOD", "Summarized", "Table"],
      ["InterpretationGuardrail", "Text", "Required limitation", "", "", "SRC_METHOD", "Summarized", "Table"],
      ["DisplayOrder", "Whole number", "Display order", "", "", "SRC_METHOD", "Curated", "Sort field"],
      ["SourceArtifactKey", "Text", "Provenance source key", "", "", "SRC_FACT_DICTIONARY", "Mapped", "Hidden metadata"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  FactProviderMeasurement: {
    grain: "One row per public-safe provider measurement metric",
    primaryKey: ["ProviderMetricKey"],
    columns: [
      ["ProviderMetricKey", "Text", "Provider metric row key", "", "", "SRC_PROVIDER_PUBLIC", "Generated", "Hidden key"],
      ["MetricKey", "Text", "Metric foreign key", "", "", "SRC_PROVIDER_PUBLIC", "Mapped to DimMetric", "Relationship key"],
      ["MetricValue", "Whole number", "Validated aggregate metric value", "", "", "SRC_PROVIDER_PUBLIC", "Allowlisted extraction", "Cards and bar"],
      ["MetricStatus", "Text", "Validation status", "", "", "SRC_PROVIDER_PUBLIC", "Controlled vocabulary", "Tooltip"],
      ["MeasurementScope", "Text", "Provider population represented", "", "", "SRC_PROVIDER_PUBLIC", "Curated", "Tooltip"],
      ["SourceArtifactKey", "Text", "Provenance source key", "", "", "SRC_PROVIDER_PUBLIC", "Mapped", "Hidden metadata"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  FactValidationStatus: {
    grain: "One row per high-value validation control",
    primaryKey: ["ValidationKey"],
    columns: [
      ["ValidationKey", "Text", "Validation-check key", "", "", "SRC_P1_QA", "Controlled key", "Hidden key"],
      ["StageKey", "Text", "Project-stage foreign key", "", "", "SRC_METHOD", "Curated mapping", "Relationship key"],
      ["ValidationCheck", "Text", "Validation-control label", "", "", "SRC_P1_QA", "Curated", "Table and axis"],
      ["ValidationStatus", "Text", "PASS or PAUSED_VERIFIED", "", "", "SRC_P1_QA", "Controlled vocabulary", "Status visual"],
      ["EvidenceSummary", "Text", "Non-sensitive evidence summary", "", "", "SRC_P1_QA", "Allowlisted summary", "Table and tooltip"],
      ["CheckOrder", "Whole number", "Validation-check order", "", "", "SRC_METHOD", "Curated", "Sort field"],
      ["SourceArtifactKey", "Text", "Provenance source key", "", "", "SRC_P1_QA", "Mapped", "Hidden metadata"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  FactAnalyticalStatus: {
    grain: "One row per project or analytical component",
    primaryKey: ["AnalyticalStatusKey"],
    columns: [
      ["AnalyticalStatusKey", "Text", "Component-status key", "", "", "SRC_PAUSE", "Controlled key", "Hidden key"],
      ["StageKey", "Text", "Project-stage foreign key", "", "", "SRC_PAUSE", "Curated mapping", "Relationship key"],
      ["ModelSpecKey", "Text", "Optional M1-M3 foreign key", "", "", "SRC_PAUSE", "Curated mapping", "Relationship key"],
      ["ComponentName", "Text", "Project-component label", "", "", "SRC_PAUSE", "Curated", "Status matrix"],
      ["ComponentStatus", "Text", "COMPLETE, IN PROGRESS, PENDING, or DEFERRED", "", "", "SRC_PAUSE", "Controlled vocabulary", "Status chart"],
      ["StatusOrder", "Whole number", "Component-status sort order", "", "", "SRC_PAUSE", "Controlled mapping", "Sort field"],
      ["IndependentAuditStatus", "Text", "PASS, PENDING, or NOT_APPLICABLE", "", "", "SRC_PAUSE", "Separate from file existence", "Status matrix"],
      ["NextAction", "Text", "Required continuation step", "", "", "SRC_PAUSE", "Curated", "Handoff table"],
      ["StatusAsOf", "Date", "Status checkpoint date", "", "", "SRC_PAUSE", "Checkpoint date", "Subtitle"],
      ["SourceArtifactKey", "Text", "Provenance source key", "", "", "SRC_PAUSE", "Mapped", "Hidden metadata"],
      ["DisclosureClass", "Text", "Public-disclosure classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
  FactSyntheticDemonstration: {
    grain: "One row per fictional demonstration metric",
    primaryKey: ["DemoMetricKey"],
    columns: [
      ["DemoMetricKey", "Text", "Synthetic demonstration metric key", "", "", "SRC_SYNTHETIC_QA", "Generated", "Hidden key"],
      ["DemoSection", "Text", "Synthetic demonstration section", "", "", "SRC_SYNTHETIC_QA", "Curated", "Visual filter"],
      ["Category", "Text", "Fictional category or schema family", "", "", "SRC_SYNTHETIC_SCHEMA", "Copied from fictional output", "Axis"],
      ["MetricName", "Text", "Synthetic metric label", "", "", "SRC_SYNTHETIC_SCHEMA", "Curated", "Legend"],
      ["MetricValue", "Whole number", "Synthetic metric value", "", "", "SRC_SYNTHETIC_SCHEMA", "Copied from fictional output", "Chart value"],
      ["DemoStatus", "Text", "Synthetic validation status", "", "", "SRC_SYNTHETIC_QA", "Copied", "Tooltip"],
      ["SyntheticFlag", "True/False", "Always true", "", "", "SRC_SYNTHETIC_QA", "Validation flag", "Disclosure guardrail"],
      ["SourceArtifactKey", "Text", "Provenance source key", "", "", "SRC_SYNTHETIC_QA", "Mapped", "Hidden metadata"],
      ["DisclosureClass", "Text", "Synthetic public-safe classification", "", "", "SRC_PRIVACY", "Assigned by allowlist", "Hidden metadata"],
    ],
  },
};

const tables = {
  DimPeriod: dimPeriod,
  DimSchemaFamily: dimSchemaFamily,
  DimProjectStage: dimProjectStage,
  DimMetric: metricDefs,
  DimClinicalDomain: dimClinicalDomain,
  DimCodingMap: dimCodingMap,
  DimModelSpec: dimModelSpec,
  FactProjectCoverage: factProjectCoverage,
  FactPartitionStatus: factPartitionStatus,
  FactEnhancementCoverage: factEnhancementCoverage,
  FactProviderMeasurement: factProviderMeasurement,
  FactValidationStatus: factValidationStatus,
  FactAnalyticalStatus: factAnalyticalStatus,
  FactSyntheticDemonstration: factSyntheticDemonstration,
};

const relationships = [
  ["DimPeriod", "PeriodKey", "FactPartitionStatus", "PeriodKey", "1:*", "Single"],
  ["DimSchemaFamily", "SchemaFamilyKey", "FactPartitionStatus", "SchemaFamilyKey", "1:*", "Single"],
  ["DimProjectStage", "StageKey", "FactValidationStatus", "StageKey", "1:*", "Single"],
  ["DimProjectStage", "StageKey", "FactAnalyticalStatus", "StageKey", "1:*", "Single"],
  ["DimMetric", "MetricKey", "FactProjectCoverage", "MetricKey", "1:*", "Single"],
  ["DimMetric", "MetricKey", "FactProviderMeasurement", "MetricKey", "1:*", "Single"],
  ["DimClinicalDomain", "ClinicalDomainKey", "FactEnhancementCoverage", "ClinicalDomainKey", "1:*", "Single"],
  ["DimModelSpec", "ModelSpecKey", "FactAnalyticalStatus", "ModelSpecKey", "1:*", "Single"],
].map(([FromTable, FromColumn, ToTable, ToColumn, Cardinality, FilterDirection]) => ({ FromTable, FromColumn, ToTable, ToColumn, Cardinality, FilterDirection }));

for (const [tableName, rows] of Object.entries(tables)) {
  const schema = tableSchemas[tableName];
  assert(schema, `Missing schema for ${tableName}`);
  const columns = schema.columns.map((c) => c[0]);
  assert(rows.length > 0, `${tableName} has no rows`);
  for (const row of rows) assert(columns.every((c) => Object.hasOwn(row, c)), `${tableName} row missing a declared column`);
  await writeText(path.join("dashboard_data", `${tableName}.csv`), toCsv(columns, rows));
}

const dataDictionaryRows = [];
for (const [tableName, schema] of Object.entries(tableSchemas)) {
  for (const [column, dataType, definition, numerator, denominator, sourceKey, transformation, intendedVisual] of schema.columns) {
    dataDictionaryRows.push({
      Table: tableName, Column: column, DataType: dataType, Grain: schema.grain, Definition: definition,
      Numerator: numerator, Denominator: denominator, SourceArtifact: sourceArtifacts[sourceKey].logical,
      Transformation: transformation, PublicDisclosureClassification: column === "DisclosureClass" ? "Control field" : disclosure,
      Caveat: column.includes("Value") ? "Aggregate project metadata or explicitly synthetic; never encounter-level" : "See source and page notes",
      IntendedVisualOrMeasure: intendedVisual,
    });
  }
}
await writeText("dashboard_data_dictionary.csv", toCsv(Object.keys(dataDictionaryRows[0]), dataDictionaryRows));

const measures = [
  ["DAX001", "Executive KPIs", "Total Validated Encounters", "Maximum allowlisted value for M001", "#,##0", `CALCULATE(MAX('FactProjectCoverage'[MetricValue]), 'FactProjectCoverage'[MetricKey] = "M001")`, "FactProjectCoverage;DimMetric", "SRC_P1_QA", "Must equal 148,686,146", "None", "One released record per encounter; not a patient count"],
  ["DAX002", "Executive KPIs", "Completed Quarterly Partitions", "Maximum allowlisted value for M002", "0", `CALCULATE(MAX('FactProjectCoverage'[MetricValue]), 'FactProjectCoverage'[MetricKey] = "M002")`, "FactProjectCoverage;DimMetric", "SRC_P1_QA", "Must equal 76", "None", "Counts partitions, not files"],
  ["DAX003", "Executive KPIs", "Covered Years", "Distinct included years", "0", `CALCULATE(DISTINCTCOUNT('DimPeriod'[Year]), 'DimPeriod'[AvailableFlag] = 1)`, "DimPeriod", "SRC_P1_MANIFEST", "Must equal 19", "Period filters", "2009 and 2025 are excluded"],
  ["DAX004", "Executive KPIs", "Standardized Encounter Fields", "Maximum allowlisted value for M004", "0", `CALCULATE(MAX('FactProjectCoverage'[MetricValue]), 'FactProjectCoverage'[MetricKey] = "M004")`, "FactProjectCoverage;DimMetric", "SRC_P1_MANIFEST", "Must equal 342", "None", "Canonical fact fields only"],
  ["DAX005", "Executive KPIs", "Schema Families", "Maximum allowlisted value for M005", "0", `CALCULATE(MAX('FactProjectCoverage'[MetricValue]), 'FactProjectCoverage'[MetricKey] = "M005")`, "FactProjectCoverage;DimMetric", "SRC_P1_MANIFEST", "Must equal 5", "None", "Approved source layouts"],
  ["DAX006", "Coverage", "Expected In-Scope Quarters", "Maximum allowlisted value for M014", "0", `CALCULATE(MAX('FactProjectCoverage'[MetricValue]), 'FactProjectCoverage'[MetricKey] = "M014")`, "FactProjectCoverage;DimMetric", "SRC_P1_MANIFEST", "Must equal 76", "None", "Excludes 2009 and 2025"],
  ["DAX007", "Coverage", "Phase 1 Completion %", "Completed quarterly partitions divided by expected in-scope quarters", "0.0%", `DIVIDE([Completed Quarterly Partitions], [Expected In-Scope Quarters])`, "FactProjectCoverage", "SRC_P1_QA", "Must equal 100.0%", "None", "Engineering completion only"],
  ["DAX008", "Coverage", "Reconciled Available Quarters", "Count available quarter rows with PASS reconciliation", "0", `CALCULATE(COUNTROWS('FactPartitionStatus'), 'FactPartitionStatus'[AvailableFlag] = 1, 'FactPartitionStatus'[ReconciliationStatus] = "PASS")`, "FactPartitionStatus", "SRC_P1_QA", "Must equal 76", "Period filters", "Metadata status, no encounter volumes"],
  ["DAX009", "Coverage", "Partition Reconciliation %", "Reconciled available quarters divided by available quarters", "0.0%", `DIVIDE([Reconciled Available Quarters], CALCULATE(COUNTROWS('FactPartitionStatus'), 'FactPartitionStatus'[AvailableFlag] = 1))`, "FactPartitionStatus", "SRC_P1_QA", "Must equal 100.0%", "Period filters", "Metadata status only"],
  ["DAX010", "Coverage", "Excluded Quarter Count", "Count of excluded quarter rows", "0", `CALCULATE(COUNTROWS('FactPartitionStatus'), 'FactPartitionStatus'[PartitionStatus] = "EXCLUDED")`, "FactPartitionStatus", "SRC_P1_MANIFEST", "Must equal 8", "Period filters", "Four quarters each for 2009 and 2025"],
  ["DAX011", "Cohorts", "Primary Cohort Rows", "Maximum allowlisted value for M008", "#,##0", `CALCULATE(MAX('FactProjectCoverage'[MetricValue]), 'FactProjectCoverage'[MetricKey] = "M008")`, "FactProjectCoverage", "SRC_COHORT_PUBLIC", "Must equal 119,543,044", "None", "Encounter rows; not unique patients"],
  ["DAX012", "Cohorts", "Historical Cohort Rows", "Maximum allowlisted value for M010", "#,##0", `CALCULATE(MAX('FactProjectCoverage'[MetricValue]), 'FactProjectCoverage'[MetricKey] = "M010")`, "FactProjectCoverage", "SRC_HISTORICAL_PUBLIC", "Must equal 23,304,846", "None", "Kept separate from primary cohort"],
  ["DAX013", "Provider", "Provider Master V2 NPIs", "Maximum allowlisted value for PM001", "#,##0", `CALCULATE(MAX('FactProviderMeasurement'[MetricValue]), 'FactProviderMeasurement'[MetricKey] = "PM001")`, "FactProviderMeasurement", "SRC_PROVIDER_PUBLIC", "Must equal 1,813,546", "None", "NPI count, not visit count"],
  ["DAX014", "Provider", "ED-Observed NPIs", "Maximum allowlisted value for PM002", "#,##0", `CALCULATE(MAX('FactProviderMeasurement'[MetricValue]), 'FactProviderMeasurement'[MetricKey] = "PM002")`, "FactProviderMeasurement", "SRC_PROVIDER_PUBLIC", "Must equal 83,541", "None", "Validated selected ED roles"],
  ["DAX015", "Provider", "Newly Added ED-Observed NPIs", "Maximum allowlisted value for PM004", "#,##0", `CALCULATE(MAX('FactProviderMeasurement'[MetricValue]), 'FactProviderMeasurement'[MetricKey] = "PM004")`, "FactProviderMeasurement", "SRC_PROVIDER_PUBLIC", "Must equal 7,751", "None", "Measurement coverage correction"],
  ["DAX016", "Provider", "Provider Coverage Gain %", "Newly added ED-observed NPIs divided by ED-observed NPIs", "0.0%", `DIVIDE([Newly Added ED-Observed NPIs], [ED-Observed NPIs])`, "FactProviderMeasurement", "SRC_PROVIDER_PUBLIC", "Must equal source-derived ratio", "None", "Describes NPI coverage, not causal selection correction"],
  ["DAX017", "Provider", "ED-Observed MD/DO NPIs", "Maximum allowlisted value for PM007", "#,##0", `CALCULATE(MAX('FactProviderMeasurement'[MetricValue]), 'FactProviderMeasurement'[MetricKey] = "PM007")`, "FactProviderMeasurement", "SRC_PROVIDER_PUBLIC", "Must equal 65,912", "None", "Organizations excluded"],
  ["DAX018", "Provider", "Organizational NPIs Classified as Physicians", "Maximum allowlisted value for PM010", "0", `CALCULATE(MAX('FactProviderMeasurement'[MetricValue]), 'FactProviderMeasurement'[MetricKey] = "PM010")`, "FactProviderMeasurement", "SRC_PROVIDER_PUBLIC", "Must equal zero", "None", "Fail-closed safeguard"],
  ["DAX033", "Provider", "Facility Dimension Rows", "Maximum allowlisted value for M006", "#,##0", `CALCULATE(MAX('FactProjectCoverage'[MetricValue]), 'FactProjectCoverage'[MetricKey] = "M006")`, "FactProjectCoverage", "SRC_P1_QA", "Must equal 240", "None", "One row per state facility identifier in the private dimension; no identifiers are displayed"],
  ["DAX019", "Enhancements", "Enhancement Count", "Number of enhancement rows", "0", `COUNTROWS('FactEnhancementCoverage')`, "FactEnhancementCoverage", "SRC_FACT_DICTIONARY", "Must equal 20", "Clinical domain and status filters", "Curated capability inventory"],
  ["DAX020", "Enhancements", "Implemented Enhancements", "Count implemented and primary-only implemented enhancements", "0", `CALCULATE(COUNTROWS('FactEnhancementCoverage'), 'FactEnhancementCoverage'[ImplementationStatus] IN {"IMPLEMENTED", "IMPLEMENTED_PRIMARY_ONLY"})`, "FactEnhancementCoverage", "SRC_FACT_DICTIONARY", "Must equal 15", "Clinical domain filters", "Primary-only scope must remain visible"],
  ["DAX021", "Enhancements", "Proxy-Only Enhancements", "Count proxy-only enhancements", "0", `CALCULATE(COUNTROWS('FactEnhancementCoverage'), 'FactEnhancementCoverage'[ImplementationStatus] = "PROXY_ONLY")`, "FactEnhancementCoverage", "SRC_FACT_DICTIONARY", "Must equal 1", "Clinical domain filters", "E/M acuity is not triage"],
  ["DAX022", "Enhancements", "Structurally Unavailable Measures", "Count structurally unavailable requested measures", "0", `CALCULATE(COUNTROWS('FactEnhancementCoverage'), 'FactEnhancementCoverage'[ImplementationStatus] = "STRUCTURALLY_UNAVAILABLE")`, "FactEnhancementCoverage", "SRC_FACT_DICTIONARY", "Must equal 4", "Clinical domain filters", "Unavailable values were not fabricated"],
  ["DAX023", "Validation", "Validation Controls", "Number of high-value validation controls", "0", `COUNTROWS('FactValidationStatus')`, "FactValidationStatus", "SRC_P1_QA", "Must equal 20", "Stage filters", "Curated dashboard controls, not every underlying test"],
  ["DAX024", "Validation", "Passed Validation Controls", "Count controls with PASS", "0", `CALCULATE(COUNTROWS('FactValidationStatus'), 'FactValidationStatus'[ValidationStatus] = "PASS")`, "FactValidationStatus", "SRC_P1_QA", "Must equal 19", "Stage filters", "Pause checkpoint is separately PAUSED_VERIFIED"],
  ["DAX025", "Validation", "Validation Pass %", "PASS controls divided by controls excluding the pause-state row", "0.0%", `DIVIDE([Passed Validation Controls], CALCULATE(COUNTROWS('FactValidationStatus'), 'FactValidationStatus'[ValidationStatus] <> "PAUSED_VERIFIED"))`, "FactValidationStatus", "SRC_P1_QA", "Must equal 100.0%", "Stage filters", "Does not imply analytical release PASS"],
  ["DAX026", "Status", "Completed Components", "Count components labeled COMPLETE", "0", `CALCULATE(COUNTROWS('FactAnalyticalStatus'), 'FactAnalyticalStatus'[ComponentStatus] = "COMPLETE")`, "FactAnalyticalStatus", "SRC_PAUSE", "Must equal component status table", "Stage filters", "Completion and audit are separate columns"],
  ["DAX027", "Status", "Pending Components", "Count components labeled PENDING", "0", `CALCULATE(COUNTROWS('FactAnalyticalStatus'), 'FactAnalyticalStatus'[ComponentStatus] = "PENDING")`, "FactAnalyticalStatus", "SRC_PAUSE", "Must equal component status table", "Stage filters", "Pending does not mean failed"],
  ["DAX028", "Status", "Deferred Components", "Count components labeled DEFERRED", "0", `CALCULATE(COUNTROWS('FactAnalyticalStatus'), 'FactAnalyticalStatus'[ComponentStatus] = "DEFERRED")`, "FactAnalyticalStatus", "SRC_PAUSE", "Must equal component status table", "Stage filters", "Deferred by user"],
  ["DAX029", "Synthetic", "Synthetic Input Rows", "Sum synthetic input rows in schema reconciliation section", "#,##0", `CALCULATE(SUM('FactSyntheticDemonstration'[MetricValue]), 'FactSyntheticDemonstration'[DemoSection] = "Schema reconciliation", 'FactSyntheticDemonstration'[MetricName] = "Input rows")`, "FactSyntheticDemonstration", "SRC_SYNTHETIC_SCHEMA", "Must equal 800", "Synthetic section filter", "Fictional only"],
  ["DAX030", "Synthetic", "Synthetic Output Rows", "Sum synthetic output rows in schema reconciliation section", "#,##0", `CALCULATE(SUM('FactSyntheticDemonstration'[MetricValue]), 'FactSyntheticDemonstration'[DemoSection] = "Schema reconciliation", 'FactSyntheticDemonstration'[MetricName] = "Output rows")`, "FactSyntheticDemonstration", "SRC_SYNTHETIC_SCHEMA", "Must equal 800", "Synthetic section filter", "Fictional only"],
  ["DAX031", "Dynamic text", "Selected Period Label", "Dynamic selected-period label", "General", `VAR MinYear = MIN('DimPeriod'[Year])\nVAR MaxYear = MAX('DimPeriod'[Year])\nRETURN IF(NOT ISFILTERED('DimPeriod'[Year]) && NOT ISFILTERED('DimPeriod'[PeriodGroup]), "All project periods", IF(MinYear = MaxYear, FORMAT(MinYear, "0"), FORMAT(MinYear, "0") & "-" & FORMAT(MaxYear, "0")))`, "DimPeriod", "SRC_P1_MANIFEST", "Visual check", "Period filters", "Display text only"],
  ["DAX032", "Dynamic text", "Dashboard Overall Status", "Controlled current-status statement", "General", `"${statusStatement}"`, "FactAnalyticalStatus", "SRC_PAUSE", "Must match pause checkpoint wording", "None", "Does not claim analytical-release completion"],
].map(([MeasureID, DisplayFolder, MeasureName, Definition, FormatString, DAXExpression, SourceTables, SourceArtifactKeys, ValidationRule, ApplicableFilters, Caveat]) => ({
  MeasureID, DisplayFolder, MeasureName, Definition, FormatString, DAXExpression, SourceTables, SourceArtifactKeys,
  ValidationRule, ApplicableFilters, Caveat, DisclosureClass: disclosure,
}));

await writeText("METRIC_AND_MEASURE_DICTIONARY.csv", toCsv(Object.keys(measures[0]), measures));
const daxText = measures.map((m) => `// ${m.MeasureID} | Folder: ${m.DisplayFolder}\n// ${m.Definition}\n${m.MeasureName} =\n${m.DAXExpression}\n// Format: ${m.FormatString}\n`).join("\n");
await writeText("POWER_BI_MEASURES.dax", daxText);

const visualSpecs = [
  [1,"P1V01","Text box",24,16,1232,44,"Florida Emergency Department: Production Data Engineering and Research Analytics","Static title","","","Project identity"],
  [1,"P1V02","Text box",24,62,1232,28,"Public-safe portfolio dashboard | Status checkpoint: Aug 9, 2026","Static subtitle","","","Scope and freshness"],
  [1,"P1V03","Card",24,106,292,96,"Validated encounter records","[Total Validated Encounters]","","Display units=None; 0 decimals","Scale"],
  [1,"P1V04","Card",332,106,292,96,"Quarterly partitions","[Completed Quarterly Partitions]","","0 decimals","Coverage"],
  [1,"P1V05","Card",640,106,292,96,"Standardized fields","[Standardized Encounter Fields]","","0 decimals","Data-model breadth"],
  [1,"P1V06","Card",948,106,308,96,"Schema families","[Schema Families]","","0 decimals","Historical complexity"],
  [1,"P1V07","Shapes and text",24,226,1232,120,"Architecture flow","Authorized sources -> Schema validation -> Standardized facts and bridges -> Independent QA -> Provider v2 and cohorts -> Analysis","","Blue outlines; arrows; no data binding","End-to-end architecture"],
  [1,"P1V08","Clustered bar chart",24,370,590,220,"Components by current status","Axis=FactAnalyticalStatus[ComponentStatus]; Values=Count of AnalyticalStatusKey","","Sort StatusOrder; data labels on","Work completed versus remaining"],
  [1,"P1V09","Multi-row card",638,370,618,220,"Current controlled status","[Dashboard Overall Status]","","Word wrap on; category label off","Exact completion boundary"],
  [1,"P1V10","Text box",24,612,1232,42,"No encounter-level data, provider identifiers, facility identifiers, or numerical concordance estimates are included.","Static disclosure note","","Amber left border","Public boundary"],
  [2,"P2V01","Text box",24,16,1232,44,"Data Coverage and Five-Schema Standardization","Static title","","","Coverage question"],
  [2,"P2V02","Slicer",24,74,240,48,"Period group","DimPeriod[PeriodGroup]","","Dropdown; single select off","Filter context"],
  [2,"P2V03","Slicer",280,74,170,48,"Year","DimPeriod[Year]","","Between/list; default all","Filter context"],
  [2,"P2V04","Card",466,74,238,76,"Reconciliation","[Partition Reconciliation %]","","Percent; 1 decimal","All available quarters reconciled"],
  [2,"P2V05","Card",720,74,238,76,"Available quarters","[Completed Quarterly Partitions]","","0 decimals","Coverage"],
  [2,"P2V06","Card",974,74,282,76,"Excluded quarters","[Excluded Quarter Count]","","0 decimals","Explicit scope exclusions"],
  [2,"P2V07","Clustered column chart",24,168,760,220,"Available quarters by year","X=DimPeriod[Year]; Y=Sum FactPartitionStatus[AvailableFlag]","","Y axis 0-4; show all years; labels on","Gaps and continuity"],
  [2,"P2V08","Matrix",800,168,456,220,"Quarter availability matrix","Rows=DimPeriod[Year]; Columns=DimPeriod[QuarterLabel]; Values=Sum FactPartitionStatus[AvailableFlag]","","Conditional background: 1 blue, 0 light gray; no totals","Exact quarter coverage"],
  [2,"P2V09","Bar chart",24,410,550,190,"Quarters by schema family","Y=DimSchemaFamily[SchemaFamilyLabel]; X=Sum DimSchemaFamily[QuarterCount]","","Sort DisplayOrder; labels on; single blue","Five-schema workload"],
  [2,"P2V10","Table",590,410,666,190,"Schema-family boundaries","SchemaFamilyLabel; StartPeriod; EndPeriod; QuarterCount; DiagnosisEra","","Sort DisplayOrder; compact rows","Historical schema and ICD boundaries"],
  [3,"P3V01","Text box",24,16,1232,44,"Clinical Decoding and Visit-Level Enhancements","Static title","","","Capability question"],
  [3,"P3V02","Card",24,74,290,82,"Implemented","[Implemented Enhancements]","","Blue callout","Implemented capabilities"],
  [3,"P3V03","Card",330,74,290,82,"Proxy only","[Proxy-Only Enhancements]","","Amber callout","Proxy boundary"],
  [3,"P3V04","Card",636,74,290,82,"Structurally unavailable","[Structurally Unavailable Measures]","","Gray callout","Non-fabrication boundary"],
  [3,"P3V05","Card",942,74,314,82,"Total documented items","[Enhancement Count]","","0 decimals","Inventory completeness"],
  [3,"P3V06","Bar chart",24,178,450,205,"Enhancements by implementation status","Y=FactEnhancementCoverage[ImplementationStatus]; X=Count of EnhancementKey","","Sort implemented to unavailable; labels on","Capability mix"],
  [3,"P3V07","Table",490,178,766,205,"Coding and grouping map","DimCodingMap[SourceCodeSystem]; ApplicablePeriod; TargetGrouping; Guardrail","","Sort DisplayOrder; word wrap","What was decoded and how"],
  [3,"P3V08","Table",24,405,1232,205,"Enhancement availability and guardrails","DimClinicalDomain[ClinicalDomainName]; FactEnhancementCoverage[EnhancementName]; ImplementationStatus; AvailabilityScope; InterpretationGuardrail","","Sort DisplayOrder; conditional font icons plus status text","What exists, where, and with what limitation"],
  [4,"P4V01","Text box",24,16,1232,44,"Provider and Facility Measurement","Static title","","","Measurement question"],
  [4,"P4V02","Card",24,74,230,88,"Provider master v2 NPIs","[Provider Master V2 NPIs]","","Display units=None","Master scale"],
  [4,"P4V03","Card",270,74,230,88,"ED-observed NPIs","[ED-Observed NPIs]","","Display units=None","ED universe"],
  [4,"P4V04","Card",516,74,230,88,"Newly added NPIs","[Newly Added ED-Observed NPIs]","","Display units=None","Coverage correction"],
  [4,"P4V05","Card",762,74,230,88,"Facility dimension","[Facility Dimension Rows]","","Display units=None","Facility master scale"],
  [4,"P4V06","Card",1008,74,248,88,"Organizations called physicians","[Organizational NPIs Classified as Physicians]","","Must display 0; green accent only after validation","Entity safeguard"],
  [4,"P4V07","Bar chart",24,184,560,230,"Selected ED-observed provider categories","Y=DimMetric[MetricName]; X=Max FactProviderMeasurement[MetricValue]","Filter MetricKey in PM006-PM009","Sort descending; note categories shown are selected, not a complete part-to-whole distribution","Provider classification"],
  [4,"P4V08","Table",600,184,656,230,"Provider measurement controls","DimMetric[MetricName]; FactProviderMeasurement[MetricValue]; MeasurementScope; MetricStatus","Filter MetricKey in PM001-PM011","Sort DisplayOrder; no totals","Coverage and QA details"],
  [4,"P4V09","Text box",24,438,394,150,"Race measurement: full-name Bayesian probability using official wru v2.0.0 likelihoods; Florida physician prior primary; national prior sensitivity; no residential geography; not BISG; not self-reported identity.","Static method note","","Blue border; word wrap","Correct race definition"],
  [4,"P4V10","Text box",434,438,394,150,"Gender measurement: recorded NPPES/CMS binary administrative categories in the primary definition. These current-source fields are not guaranteed to represent self-identified gender identity.","Static limitation note","","Amber border; word wrap","Correct gender definition"],
  [4,"P4V11","Text box",844,438,412,150,"Facility measurement: one row per state facility identifier with name/Medicare histories and controlled current enrichments. Current affiliation is not treated as historical employment or privileges.","Static facility note","","Gray-blue border; word wrap","Correct facility and affiliation definition"],
  [5,"P5V01","Text box",24,16,1232,44,"Cohort Construction and Analytical Design","Static title","","","Design question"],
  [5,"P5V02","Card",24,74,300,88,"Primary cohort rows","[Primary Cohort Rows]","","Display units=None","Primary analytical population"],
  [5,"P5V03","Card",340,74,300,88,"Historical cohort rows","[Historical Cohort Rows]","","Display units=None","Separate historical population"],
  [5,"P5V04","Text box",656,74,600,88,"Primary: 2010-2024, direct validated attending NPIs. Historical: 2005-2008, unique Florida-license linkage only. The periods are never silently pooled.","Static cohort note","","Two-column background bands","Separation rule"],
  [5,"P5V05","Table",24,184,1232,175,"M1-M3 model progression","DimModelSpec[ModelLabel]; PlainLanguageDefinition; FixedEffectsSummary; ClusteringSummary","","Sort ModelOrder; word wrap","How adjustment deepens"],
  [5,"P5V06","Table",24,383,720,215,"Current model-family status","FactAnalyticalStatus[ComponentName]; ComponentStatus; IndependentAuditStatus; NextAction","Filter StageKey=S04","Sort AnalyticalStatusKey; status icons plus text","What has run and what remains"],
  [5,"P5V07","Text box",760,383,496,215,"Outcomes retained in the frozen plan include charges, disposition/admission-related measures where supported, length of stay, treatment intensity, utilization, and separate AMI/Greenwood analyses. Race is probabilistic; hard labels are sensitivities. Results are observational associations, not causal effects.","Static design guardrail","","Word wrap; amber bottom note","Interpretation boundary"],
  [6,"P6V01","Text box",24,16,1232,44,"Validation, Reconciliation, and Reproducibility","Static title","","","Trust question"],
  [6,"P6V02","Card",24,74,280,82,"Validation controls","[Validation Controls]","","0 decimals","Control breadth"],
  [6,"P6V03","Card",320,74,280,82,"Validation pass rate","[Validation Pass %]","","Percent; 1 decimal","Control outcome"],
  [6,"P6V04","Card",616,74,280,82,"Synthetic input rows","[Synthetic Input Rows]","","Display units=None","Demo scale"],
  [6,"P6V05","Card",912,74,344,82,"Synthetic output rows","[Synthetic Output Rows]","","Display units=None","Deterministic reconciliation"],
  [6,"P6V06","Bar chart",24,178,470,210,"Checks by project stage","Y=DimProjectStage[StageName]; X=Count FactValidationStatus[ValidationKey]","","Sort StageOrder; labels on","Where controls are concentrated"],
  [6,"P6V07","Clustered column chart",510,178,746,210,"Synthetic schema reconciliation","X=FactSyntheticDemonstration[Category]; Y=Sum MetricValue; Legend=MetricName","Filter DemoSection=Schema reconciliation","Input/output paired; labels off; subtitle says fictional","Runnable public demonstration"],
  [6,"P6V08","Table",24,410,1232,200,"High-value validation ledger","DimProjectStage[StageName]; FactValidationStatus[ValidationCheck]; ValidationStatus; EvidenceSummary","","Sort CheckOrder; status text and icons; word wrap","Inspectable validation evidence"],
  [7,"P7V01","Text box",24,16,1232,44,"Completion, Safe Pause, and Handoff","Static title","","","Continuation question"],
  [7,"P7V02","Card",24,74,280,82,"Completed components","[Completed Components]","","Blue accent","Completed work"],
  [7,"P7V03","Card",320,74,280,82,"Pending components","[Pending Components]","","Gray accent","Remaining work"],
  [7,"P7V04","Card",616,74,280,82,"Deferred components","[Deferred Components]","","Purple accent","Deferred work"],
  [7,"P7V05","Multi-row card",912,74,344,144,"Controlled project status","[Dashboard Overall Status]","","Word wrap; category off","No overstatement"],
  [7,"P7V06","Bar chart",24,184,400,200,"Components by status","Y=FactAnalyticalStatus[ComponentStatus]; X=Count AnalyticalStatusKey","","Sort StatusOrder; labels on","Work balance"],
  [7,"P7V07","Table",440,184,816,330,"Continuation ledger","DimProjectStage[StageName]; FactAnalyticalStatus[ComponentName]; ComponentStatus; IndependentAuditStatus; NextAction","","Sort StageOrder then AnalyticalStatusKey; word wrap","How another analyst resumes"],
  [7,"P7V08","Text box",24,408,400,106,"Verified restart point: gender M2 has no committed design or outcome columns and must restart from its beginning after validating the checkpoint hashes. Phase 1 must remain immutable.","Static recovery note","","Amber border","Exact resumption point"],
  [7,"P7V09","Text box",24,536,1232,74,"This dashboard documents engineering, measurement, validation, and work status. It does not report concordance coefficients, confidence intervals, p-values, q-values, or causal treatment-outcome conclusions.","Static disclosure note","","Dark blue background; white text","Final public boundary"],
].map(([PageNumber, VisualID, VisualType, X, Y, Width, Height, Title, FieldsOrText, VisualFilters, Sort, Formatting, AnalyticalQuestion]) => ({
  PageNumber, PageName: ["Executive Overview","Coverage & Standardization","Clinical & Visit Enhancements","Provider & Facility Measurement","Cohort & Analytical Design","Validation & Reproducibility","Completion & Handoff"][PageNumber-1],
  VisualID, VisualType, X, Y, Width, Height, Title, FieldsOrText, VisualFilters, Sort, Formatting, AnalyticalQuestion,
}));
await writeText("POWER_BI_VISUAL_SPECIFICATION.csv", toCsv(Object.keys(visualSpecs[0]), visualSpecs));

const metricDictionaryColumns = Object.keys(measures[0]);

const theme = {
  name: "Florida ED Research Portfolio",
  dataColors: ["#1F4E79", "#C69214", "#6B7280", "#7A5195", "#B45309", "#2F6B5F"],
  background: "#F7F9FC",
  foreground: "#1F2937",
  tableAccent: "#1F4E79",
  good: "#2F6B5F",
  neutral: "#C69214",
  bad: "#B45309",
  maximum: "#1F4E79",
  center: "#C69214",
  minimum: "#E5E7EB",
  textClasses: {
    callout: { fontFace: "Segoe UI Semibold", fontSize: 28, color: "#1F2937" },
    title: { fontFace: "Segoe UI Semibold", fontSize: 14, color: "#1F2937" },
    header: { fontFace: "Segoe UI Semibold", fontSize: 12, color: "#1F2937" },
    label: { fontFace: "Segoe UI", fontSize: 10, color: "#374151" },
  },
};
await writeText("powerbi_theme.json", JSON.stringify(theme, null, 2) + "\n");

const relationshipRows = relationships;

const modelDoc = `# Power BI data model

## Design

The package uses a compact constellation/star model. Each table has one declared grain. Relationships are one-to-many and single-directional. Blank optional foreign keys are allowed only for excluded quarters or components without an M1-M3 designation. Do not enable automatic bidirectional filtering.

## Model diagram

\`\`\`mermaid
flowchart LR
  DP["DimPeriod"] --> FPS["FactPartitionStatus"]
  DS["DimSchemaFamily"] --> FPS
  DPS["DimProjectStage"] --> FVS["FactValidationStatus"]
  DPS --> FAS["FactAnalyticalStatus"]
  DM["DimMetric"] --> FPC["FactProjectCoverage"]
  DM --> FPM["FactProviderMeasurement"]
  DCD["DimClinicalDomain"] --> FEC["FactEnhancementCoverage"]
  DMS["DimModelSpec"] --> FAS
  DCM["DimCodingMap (reference)"]
  FSD["FactSyntheticDemonstration (fictional)"]
\`\`\`

## Relationships

| From | To | Cardinality | Cross-filter |
|---|---|---:|---|
${relationshipRows.map((r) => `| ${r.FromTable}[${r.FromColumn}] | ${r.ToTable}[${r.ToColumn}] | ${r.Cardinality} | ${r.FilterDirection} |`).join("\n")}

The relationship from DimModelSpec to FactAnalyticalStatus ignores blank ModelSpecKey values. The relationship from DimSchemaFamily to FactPartitionStatus ignores blank SchemaFamilyKey values for excluded years.

## Grains

${Object.entries(tableSchemas).map(([name, schema]) => `- **${name}:** ${schema.grain}. Primary key: ${schema.primaryKey.join(" + ")}.`).join("\n")}

## Measure organization

Create an empty display table named **Measures** and place measures into the display folders listed in METRIC_AND_MEASURE_DICTIONARY.csv. Hide all technical keys, sort-order columns, source-artifact keys, and disclosure-class fields from Report view after relationships and sort-by-column settings are complete.

## Refresh behavior

The public dashboard is a static, public-safe snapshot. Refresh reads only dashboard_data/POWER_BI_IMPORT.xlsx. It must never point to the private Phase 1 or Phase 2 workspace. Regenerate the handoff package from approved source metadata before any future refresh.

## Public/private boundary

Only public-safe metadata and explicitly fictional data are present. Real encounter rows, provider/facility identifiers, purchased files, model matrices, and numerical concordance estimates are absent. A future private research dashboard must be a separate file and must not replace this source workbook.
`;
await writeText("POWER_BI_DATA_MODEL.md", modelDoc);

const blueprint = `# Dashboard blueprint

## Purpose and audience

This seven-page Power BI dashboard is a portfolio and collaborator-orientation surface for data analysts, researchers, faculty, clinicians, and hiring reviewers. It answers: what was built, how it was controlled, what is safe to claim, and where work can resume. It is not a results dashboard and does not support causal interpretation.

## Visual system

- Canvas: 1280 x 720, 16:9, near-white background #F7F9FC.
- Primary/complete: blue #1F4E79. Validated safeguard: teal #2F6B5F. In progress: gold #C69214. Pending/historical: gray #6B7280. Deferred: purple #7A5195. Warning: orange #B45309.
- Use status text and icons as well as color. Never rely on red/green alone.
- Use Segoe UI, dark charcoal text, subtle gray separators, and no 3-D charts, gauges, decorative gradients, or unnecessary legends.
- Every page carries a footer: “Public-safe metadata and synthetic demonstration only; no row-level data or numerical concordance estimates.”

## Page wireframes

### 1. Executive Overview

\`\`\`
[Title and status date]
[Encounter records] [Quarters] [Fields] [Schema families]
[Authorized sources -> Standardize -> Validate -> Measure -> Analyze]
[Components by status]          [Controlled status statement]
[Public disclosure boundary]
\`\`\`

The reader should understand the scale, architecture, Phase 1 completion, Phase 2 incompleteness, and privacy boundary in under 30 seconds.

### 2. Coverage & Standardization

\`\`\`
[Title] [Period slicer] [Year slicer] [Reconciliation] [Available] [Excluded]
[Available quarters by year]                       [Year x quarter matrix]
[Quarters by schema family]                        [Schema boundary table]
\`\`\`

The reader should see 19 included years, 76 available quarters, explicit gaps in 2009 and 2025, and five schema families without seeing encounter counts by year.

### 3. Clinical & Visit Enhancements

\`\`\`
[Title]
[Implemented] [Proxy only] [Unavailable] [Total inventory]
[Enhancements by status]          [Coding/grouping map]
[Detailed availability and guardrail table]
\`\`\`

The reader should understand what was decoded and why triage, revisit, same-facility admission, and historical hourly LOS were not fabricated.

### 4. Provider & Facility Measurement

\`\`\`
[Title]
[Master NPIs] [ED NPIs] [New NPIs] [Facilities] [Organizations called physicians = 0]
[Selected provider categories]       [Measurement control table]
[Race method and limitation]          [Gender/affiliation limitation]
\`\`\`

The reader should understand provider master v2 as a measurement and coverage correction, with organizations separated from physicians and physician race explicitly described as probabilistic full-name inference—not BISG or self-report.

### 5. Cohort & Analytical Design

\`\`\`
[Title]
[Primary cohort] [Historical cohort] [Never-pooled rule]
[M1 -> M2 -> M3 progression table]
[Current model-family status]         [Outcomes and interpretation guardrail]
\`\`\`

The reader should understand cohort separation, adjustment progression, fixed effects/clustering at a high level, and why the work supports association language only.

### 6. Validation & Reproducibility

\`\`\`
[Title]
[Controls] [Pass rate] [Synthetic input] [Synthetic output]
[Checks by stage]                    [Synthetic schema reconciliation]
[Validation ledger]
\`\`\`

The reader should see the reconciliation, hashes, immutability, fail-closed gates, synthetic demonstration, and independent audit structure.

### 7. Completion & Handoff

\`\`\`
[Title]
[Complete] [Pending] [Deferred] [Controlled overall status]
[Components by status]       [Continuation ledger]
[Verified gender-M2 restart point]
[No numerical results / no causal claim]
\`\`\`

The reader should know precisely what another analyst can trust, what remains, and how to resume without rebuilding Phase 1.

## Interaction policy

Use only PeriodGroup and Year slicers on page 2. Do not create cross-page synchronized slicers that imply unsupported comparability. Do not configure drill-through: there is no public-safe row-level detail table. Use a page navigator on every page and one reset-filter bookmark on page 2.

## Source and disclosure notes

All numerical values are high-level, nondisclosive project metadata already represented in validated evidence or explicitly fictional. No numerical concordance coefficient, confidence interval, p-value, q-value, or substantive treatment-outcome finding is displayed.
`;
await writeText("DASHBOARD_BLUEPRINT.md", blueprint);

const powerQueryDoc = `# Power Query transformations

## Recommended import path

Use **dashboard_data/POWER_BI_IMPORT.xlsx** and select the 14 named Excel tables. The workbook is already normalized for Power BI. Do not use the worksheet object named PowerBI_Tables and do not use the Folder connector.

## Required transformations

No filtering, joins, grouping, parsing, or value replacement is required. In Power Query, verify types only:

- Whole number: keys that are numeric, Year, Quarter, order fields, flags, MetricValue, QuarterCount.
- Date: AsOfDate, StatusAsOf.
- True/False: SyntheticFlag.
- Text: every other field, including text keys.

After setting types, select **Close & Apply**. Do not derive analytical results in Power Query. Do not edit source values. Do not point any query to the private research workspace.

## Optional parameterized M pattern

The UI import is recommended. If the workbook later moves, change the source path through **Data source settings**. A custom M function is unnecessary for this static portfolio snapshot and would add maintenance risk.

## Refresh rule

Refresh is allowed only after a new public-safe import workbook has passed the disclosure and preparation validators. Never substitute a Phase 1 fact, Phase 2 cohort partition, provider master, result table, Parquet file, or model matrix.
`;
await writeText("POWER_QUERY_TRANSFORMATIONS.md", powerQueryDoc);

const clickbook = `# Power BI Desktop build clickbook

Follow these steps in order. Do not improvise with private data or analytical-result files.

## 1. Start and save the file

1. Open **Power BI Desktop**.
2. Select **File > Save As**.
3. Browse to this dashboard-preparation folder.
4. Save as **Florida_ED_Project_Portfolio_Dashboard.pbix**.
5. If Power BI offers to enable preview features, leave the current settings unchanged.

## 2. Import the prepared tables

1. On the Home ribbon, choose **Get data > Excel workbook**.
2. Open **dashboard_data/POWER_BI_IMPORT.xlsx**.
3. In Navigator, check these named tables—not the PowerBI_Tables worksheet:

${Object.keys(tables).map((t) => `   - ${t}`).join("\n")}

4. Select **Transform Data**.
5. In the Queries pane, click each query and confirm its name exactly matches the table name.
6. Set types according to dashboard_data_dictionary.csv. Use the icon at the left of each column heading or **Transform > Data type**.
7. Confirm AsOfDate and StatusAsOf are **Date**, SyntheticFlag is **True/False**, numeric keys/counts/orders/flags are **Whole number**, and all remaining columns are **Text**.
8. Select **Home > Close & Apply**.

Checkpoint: Model view must show 14 imported tables and zero load errors.

## 3. Build the relationships

1. Select the **Model** icon on the left.
2. Select **Home > Manage relationships > New** for each relationship below.
3. Set cardinality to **One to many (1:*)**, cross-filter direction to **Single**, and make the relationship active.

${relationships.map((r, i) => `${i + 1}. ${r.FromTable}[${r.FromColumn}] (one) -> ${r.ToTable}[${r.ToColumn}] (many)`).join("\n")}

4. Do not create any other relationship.
5. Confirm Power BI did not create hidden automatic relationships. Delete any relationship not listed above.

Checkpoint: there are eight active relationships, no many-to-many relationships, and no bidirectional filters.

## 4. Set sort-by columns

In Data view, select the display column, then **Column tools > Sort by column**:

- DimPeriod[QuarterLabel] by DimPeriod[Quarter]
- DimPeriod[PeriodGroup] by DimPeriod[PeriodGroupOrder]
- DimSchemaFamily[SchemaFamilyLabel] by DimSchemaFamily[DisplayOrder]
- DimProjectStage[StageName] by DimProjectStage[StageOrder]
- DimMetric[MetricName] by DimMetric[DisplayOrder]
- DimClinicalDomain[ClinicalDomainName] by DimClinicalDomain[DisplayOrder]
- DimModelSpec[ModelLabel] by DimModelSpec[ModelOrder]
- FactEnhancementCoverage[EnhancementName] by FactEnhancementCoverage[DisplayOrder]
- FactValidationStatus[ValidationCheck] by FactValidationStatus[CheckOrder]
- FactAnalyticalStatus[ComponentStatus] by FactAnalyticalStatus[StatusOrder]

## 5. Create the measure table and measures

1. Select **Home > Enter data**.
2. Name the column **Placeholder**, enter 1 in the first row, and name the table **Measures**.
3. Select **Load**.
4. In Model view, right-click Measures[Placeholder] and choose **Hide in report view**.
5. Open POWER_BI_MEASURES.dax.
6. For each measure block, right-click the Measures table and choose **New measure**.
7. Copy the measure name and expression from the block into the formula bar. Create one measure at a time.
8. In Measure tools, set the format shown in each block and set **Display folder** to the folder listed in METRIC_AND_MEASURE_DICTIONARY.csv.

Checkpoint values before filters:

- Total Validated Encounters = 148,686,146
- Completed Quarterly Partitions = 76
- Covered Years = 19
- Standardized Encounter Fields = 342
- Schema Families = 5
- Phase 1 Completion % = 100.0%
- Partition Reconciliation % = 100.0%
- Provider Master V2 NPIs = 1,813,546
- Facility Dimension Rows = 240
- Organizational NPIs Classified as Physicians = 0
- Synthetic Input Rows = 800
- Synthetic Output Rows = 800

Stop and correct the model if any checkpoint differs.

## 6. Hide technical fields

After relationships and sorting work, hide from Report view:

- Every column ending in Key
- Every field containing Order
- SourceArtifactKey
- DisclosureClass
- SourceClass
- FormatString

Do not hide fields named MetricName, MetricValue, Status, Year, QuarterLabel, PeriodGroup, ComponentName, ValidationCheck, EvidenceSummary, or NextAction.

## 7. Apply the theme and page defaults

1. Switch to Report view.
2. Select **View > Themes > Browse for themes**.
3. Open **powerbi_theme.json**.
4. For every page, open **Format page > Canvas settings > Type > Custom** and enter Width **1280** and Height **720**.
5. Set canvas background to **#F7F9FC**, transparency **0%**.
6. Set wallpaper to white, transparency **100%**.
7. Turn off visual shadows unless specifically instructed.
8. Use 8-pixel corner radius only for cards and text-callout containers.

## 8. Create the seven pages

Rename pages exactly:

1. Executive Overview
2. Coverage & Standardization
3. Clinical & Visit Enhancements
4. Provider & Facility Measurement
5. Cohort & Analytical Design
6. Validation & Reproducibility
7. Completion & Handoff

Use POWER_BI_VISUAL_SPECIFICATION.csv for the exact X, Y, width, height, title, fields, filters, sorting, and purpose of every visual. After selecting a visual, enter position and size under **Format visual > General > Properties**.

### Shared formatting for all pages

- Page title: Segoe UI Semibold, 22 pt, #1F2937.
- Subtitle: 10 pt, #4B5563.
- Visual titles: 12 pt, semibold, left aligned.
- Body/table text: 9-10 pt.
- Card callout: 24-30 pt; category label 10 pt.
- Chart background: white; border #D9E2EC at 1 px; no shadow.
- Gridlines: #E5E7EB, thin.
- Data labels: on only where the specification says; no display-unit abbreviation for record/provider cards.
- Add this 9-pt footer at Y=660, X=24, W=1232, H=20 on every page: **Public-safe metadata and synthetic demonstration only; no row-level data or numerical concordance estimates.**

### Page 1 - Executive Overview

1. Add the title and subtitle text boxes from P1V01-P1V02.
2. Add four **Card (new)** visuals using P1V03-P1V06. Set display units to None and thousands separator on.
3. Build P1V07 with six rounded rectangles and five right arrows. Use white fills, #1F4E79 outlines, and the exact architecture text in the specification. This is intentionally static because it documents process, not data.
4. Add P1V08 as a clustered bar. Use ComponentStatus on Y and count of AnalyticalStatusKey on X. Show labels and hide the legend.
5. Add P1V09 as a multi-row card using [Dashboard Overall Status]. Turn category label off and word wrap on.
6. Add P1V10 as an amber-bordered text box.

Validation: the four cards must show 148,686,146; 76; 342; and 5. The page must state that Phase 2 is unfinished without showing any model estimate.

### Page 2 - Coverage & Standardization

1. Add the title.
2. Add dropdown slicers for PeriodGroup and Year. Keep all values selected by default.
3. Add the three cards P2V04-P2V06.
4. Add P2V07. Set Y-axis start 0, end 4, interval 1. Set data color #1F4E79. Keep 2009 and 2025 visible at zero.
5. Add P2V08 matrix. Rows=Year, columns=QuarterLabel, values=Sum of AvailableFlag. Disable subtotals. Conditional formatting for values: 1 uses #DCEAF7 background and #1F4E79 font; 0 uses #F3F4F6 background and #6B7280 font.
6. Add P2V09 using DimSchemaFamily only. Use horizontal bars and data labels.
7. Add P2V10 table and sort by DisplayOrder.
8. Select **Format > Edit interactions**. Both slicers should filter P2V04, P2V06-P2V08. They must not change the fixed project-total card P2V05 or schema-family table/bar; set those interactions to None.

Validation: years 2005-2008 and 2010-2024 show four available quarters; 2009 and 2025 show zero. Schema-family quarter counts must sum to 76.

### Page 3 - Clinical & Visit Enhancements

1. Add the title and four cards P3V02-P3V05.
2. Add P3V06 with ImplementationStatus on Y and count of EnhancementKey on X. Use direct labels and no legend. Apply colors: IMPLEMENTED #1F4E79; IMPLEMENTED_PRIMARY_ONLY #2F6B5F; PROXY_ONLY #C69214; STRUCTURALLY_UNAVAILABLE #6B7280.
3. Add P3V07 as a table with word wrap and alternating rows off.
4. Add P3V08 as a table. Show both status text and conditional-format icons. Do not use icons alone.

Validation: the unavailable rows must explicitly include true triage, same-facility admission, 7-day revisit, and 30-day revisit. The hourly-LOS row must say primary-only and must not imply historical imputation.

### Page 4 - Provider & Facility Measurement

1. Add the title and five cards P4V02-P4V06.
2. Add P4V07. Add a visual-level filter retaining only MetricKey PM006 through PM009. In the subtitle write: **Selected validated categories; not a complete part-to-whole distribution.**
3. Add P4V08. Filter to PM001-PM011. Use MetricName, MetricValue, MeasurementScope, MetricStatus.
4. Add the three race, gender, and facility method/limitation text boxes exactly as specified.

Validation: the fifth card must be zero and the facility card must be 240. The page must say organizations are not physicians, physician race is probabilistic full-name inference, no geography was used, and the method is not BISG or self-reported identity.

### Page 5 - Cohort & Analytical Design

1. Add the title, two cohort cards, and the separation-rule text box.
2. Add the M1-M3 table using DimModelSpec and sort by ModelOrder.
3. Add P5V06 and filter StageKey to S04.
4. Add the outcomes and interpretation callout P5V07.

Validation: primary and historical cohorts must remain visually separate. Race M1-M3 and gender M1 may be labeled as completed estimation, but the page must also show the pending independent analytical-release audit and must not display coefficients or significance.

### Page 6 - Validation & Reproducibility

1. Add the title and four cards.
2. Add P6V06 with StageName on Y and count of ValidationKey on X. Sort StageName by StageOrder.
3. Add P6V07. Apply the visual filter DemoSection=Schema reconciliation. Use MetricName as legend and MetricValue as Y. Use blue for input and gold with an outline for output. Subtitle: **Fictional deterministic demonstration; not Florida encounter data.**
4. Add P6V08 as a table. Use conditional icons plus visible status text.

Validation: synthetic input and output both equal 800. The pass-rate card is 100% because the verified pause state is excluded from the validation denominator; this does not imply final analytical release.

### Page 7 - Completion & Handoff

1. Add the title, three status cards, and controlled-status multi-row card.
2. Add P7V06 with ComponentStatus on Y and count of AnalyticalStatusKey on X. Sort by StatusOrder.
3. Add P7V07 and sort by StageOrder then AnalyticalStatusKey.
4. Add P7V08 and P7V09 as static guardrail text boxes.

Validation: gender M2 must say “restart from its beginning after hash validation.” Phase 1 must remain immutable. The page must not claim the entire analytical release is complete.

## 9. Navigation and reset behavior

1. On each page, select **Insert > Buttons > Navigator > Page navigator**.
2. Position it at X=24, Y=684, W=1232, H=28. If the footer overlaps, move the footer to Y=654.
3. Use selected fill #1F4E79 with white text; default fill white with #1F4E79 text.
4. On page 2, clear slicers to their all-selected default.
5. Open **View > Bookmarks**, choose **Add**, rename it **Reset_Page_2**, and ensure Data and Current page are checked.
6. Insert a blank button at X=1160, Y=74, W=96, H=32, text **Reset**. Turn Action on, Type=Bookmark, Bookmark=Reset_Page_2.
7. Do not add drill-through pages. The public dataset intentionally has no row-level detail grain.

## 10. Accessibility and interactions

1. For each visual, set **General > Alt text** to the AnalyticalQuestion in POWER_BI_VISUAL_SPECIFICATION.csv plus the visual title.
2. Open **View > Selection** and rename every visual to its VisualID followed by its title.
3. Open **View > Tab order** and order title, slicers, KPI cards, charts, tables, notes, navigation.
4. Verify every state encoded by color is also stated in text.
5. Do not use automatic insights, Q&A visuals, custom visuals, maps, or AI-generated narratives.

## 11. Final local checks and save

1. Click every page-navigation button.
2. Test page 2 slicers and Reset.
3. Check that titles, labels, and wrapped text are not clipped at 100% zoom.
4. Confirm there are no blank visuals, (Blank) categories, implicit Sum/Count labels exposed to viewers, or unexpected relationships.
5. Confirm no numerical concordance estimates appear anywhere, including tooltips.
6. Select **File > Options and settings > Data source settings** and confirm the only source is POWER_BI_IMPORT.xlsx in this staging package.
7. Save the PBIX.
8. Do not publish to Power BI Service or GitHub yet.

Next, use POWER_BI_FINAL_QA_PROMPT.txt in a new Codex task for the independent dashboard review.
`;
await writeText("POWER_BI_BUILD_CLICKBOOK.md", clickbook);

const qaChecklist = `# Dashboard QA checklist

## Data and model

- [ ] Exactly 14 named source tables imported; worksheet object not imported.
- [ ] Eight active one-to-many, single-direction relationships; no others.
- [ ] Declared keys unique and foreign keys resolved.
- [ ] Numeric, date, Boolean, and text types match dashboard_data_dictionary.csv.
- [ ] Technical keys, order fields, source keys, and disclosure fields hidden from Report view.
- [ ] Cards reconcile to the checkpoint values in the clickbook.
- [ ] No implicit measure is used where an explicit DAX measure exists.

## Filters and interactions

- [ ] Page 2 PeriodGroup and Year slicers filter only intended coverage visuals.
- [ ] Reset_Page_2 restores the documented default.
- [ ] No synchronized slicer implies historical/primary outcome comparability.
- [ ] No drill-through to nonexistent row-level detail.
- [ ] Page navigation works from every page.

## Visual and accessibility

- [ ] Every page is 1280 x 720 and readable at 100% zoom.
- [ ] Titles, subtitles, units, denominators, and caveats are visible where needed.
- [ ] Bars comparing absolute values start at zero.
- [ ] No 3-D charts, gauges, unnecessary pies, decorative gradients, or redundant legends.
- [ ] Color palette matches the theme and status semantics.
- [ ] Statuses use text/icons as well as color.
- [ ] Alt text and tab order are complete.
- [ ] No label, title, card value, legend, or table text is clipped.

## Scientific and status language

- [ ] Phase 1 is labeled complete and independently validated.
- [ ] Race M1-M3 and gender M1 are labeled as completed estimation, not final analytical release.
- [ ] Gender M2 restart point is stated exactly.
- [ ] Pending outcome-specific, directional, AMI, multiplicity, and final audits are visible.
- [ ] Historical 2005-2008 and primary 2010-2024 remain separate.
- [ ] Race is algorithm-inferred, probabilistic, full-name based, not BISG, and not self-reported.
- [ ] Recorded physician-gender fields are not described as self-identified gender identity.
- [ ] Association language is used; no causal claim appears.

## Privacy and publication

- [ ] Data source is only dashboard_data/POWER_BI_IMPORT.xlsx.
- [ ] No encounter rows or patient identifiers.
- [ ] No provider names, NPIs, or provider-level rows.
- [ ] No facility identifiers/names or facility-level rows.
- [ ] No purchased source file, Parquet, matrix, result table, credential, email, or private path.
- [ ] No concordance coefficient, confidence interval, p-value, q-value, or treatment-outcome result.
- [ ] Every synthetic visual is labeled fictional/synthetic.
- [ ] PBIX has not been published before final QA.

## Performance

- [ ] Initial open and page navigation are responsive.
- [ ] No auto date/time tables are needed; disable Auto date/time if it creates hidden date tables.
- [ ] No unused imported worksheet or duplicate query.
- [ ] Visual count and cross-highlighting remain modest.
`;
await writeText("DASHBOARD_QA_CHECKLIST.md", qaChecklist);

const finalQaPrompt = `Perform the final independent quality review of the completed Florida ED Power BI portfolio dashboard.

This is a QA and repair task only. Do not publish, upload, push, email, or share anything. Do not restart Phase 1 or Phase 2 analytics and do not inspect or disclose numerical concordance estimates.

Locate the newest completed dashboard-preparation package under outputs/powerbi_dashboard_preparation. The expected PBIX is Florida_ED_Project_Portfolio_Dashboard.pbix in that package. Use its 00_READ_ME_FIRST.md, POWER_BI_BUILD_CLICKBOOK.md, POWER_BI_VISUAL_SPECIFICATION.csv, POWER_BI_DATA_MODEL.md, METRIC_AND_MEASURE_DICTIONARY.csv, POWER_BI_MEASURES.dax, DASHBOARD_QA_CHECKLIST.md, disclosure audit, and preparation validation as the controlling specification.

If Power BI Desktop is open with the PBIX loaded, use the Windows-app control capability to inspect it. Otherwise inspect the PBIX and any screenshots or exported model metadata available locally. If visual access is genuinely unavailable, stop only the visual-verification portion and tell me exactly what screenshots or exports are required; continue every safe structural and file-level check.

Create a backup copy of the PBIX before any edit. First audit without changing it. Then correct only clear, reversible defects that violate the frozen dashboard specification. Do not redesign the research, add new metrics, use private data, or introduce analytical results.

Audit all of the following:

1. File opens without repair warnings and uses only dashboard_data/POWER_BI_IMPORT.xlsx.
2. Fourteen source tables, data types, eight relationships, cardinality, filter direction, hidden fields, and sort-by settings match the data-model document.
3. Every DAX measure exists once, matches POWER_BI_MEASURES.dax, uses the correct display folder/format, and reconciles to the metric dictionary.
4. All seven pages and all VisualIDs match the visual specification, including visual type, fields, filters, sorting, position, size, title, units, and tooltip context.
5. Slicer interactions, the page-2 reset bookmark, page navigation, tab order, and alt text work.
6. KPI values and totals reconcile to the prepared dashboard data.
7. No clipped labels, broken visuals, blank categories, misleading scale, redundant legend, inconsistent status color, poor contrast, or unreadable table exists at normal laptop view.
8. Phase 1 versus Phase 2, historical versus primary, completed estimation versus independent audit, and pending versus deferred work are stated correctly.
9. Physician race is described only as algorithm-inferred probabilistic full-name measurement using wru v2.0.0; no geography, not BISG, not self-reported.
10. Physician gender is described as recorded administrative categories with limitations.
11. Association language is used and no causal conclusion appears.
12. No raw/processed encounter rows, patient identifier, provider name/NPI, facility identifier/name, purchased source, local private path, credential, numerical concordance coefficient, confidence interval, p-value, q-value, or substantive treatment-outcome finding exists in the PBIX, data sources, tooltips, hidden pages, bookmarks, or metadata.
13. Synthetic values are visibly labeled fictional/synthetic.
14. Performance is appropriate for a small static portfolio dashboard.

After corrections, rerun the full audit. Create a timestamped FINAL_POWER_BI_QA_REPORT.md and FINAL_POWER_BI_QA.json beside the PBIX. Record PASS/FAIL for data, model, DAX, visuals, interactions, accessibility, scientific language, status accuracy, disclosure safety, and performance. Include screenshots only when necessary to evidence a defect or the final page review; do not create report-only narrative artifacts.

Fail closed if any privacy, result-disclosure, unsupported-completion, source-lineage, broken-measure, or reconciliation issue remains. Do not authorize GitHub publication unless the overall QA status is PASS. Even with PASS, do not publish; return the QA status and wait for my explicit publication instruction.
`;
await writeText("POWER_BI_FINAL_QA_PROMPT.txt", finalQaPrompt);

const nextSteps = `# Next steps after dashboard preparation

1. Open 00_READ_ME_FIRST.md and follow POWER_BI_BUILD_CLICKBOOK.md to build Florida_ED_Project_Portfolio_Dashboard.pbix.
2. Save the PBIX in this staging package and run POWER_BI_FINAL_QA_PROMPT.txt in a separate Codex task.
3. Correct any fail-closed dashboard findings and repeat QA until the dashboard receives PASS.
4. Build a new sanitized GitHub release from approved code, documentation, synthetic data, dashboard source files, and the QA-passed PBIX. Do not copy the private research workspace into Git.
5. Run a repository-wide privacy, secret, path, large-file, license, link, reproducibility, and fresh-clone audit before publishing.
6. Publish the replacement repository only after explicit approval. Keep the earlier repository available until the replacement has been verified; then archive or make it private before considering deletion.
7. Separately upload the complete restricted research workspace to the authorized OneDrive location with hashes and a navigation manifest. Do not use the GitHub package as the scientific continuation archive.
8. Create the professor navigation guide and technical handoff report from the verified OneDrive package and the restart-safe pause checkpoint.
9. Create the comprehensive personal study guide explaining source investigation, schema decisions, cleaning, mappings, provider/facility enhancements, model design, code logic, validation, failures, recovery, completed work, and remaining work.

The dashboard is a public-safe orientation layer. It does not replace the restricted continuation package or the final independently audited research analysis.
`;
await writeText("NEXT_STEPS_AFTER_DASHBOARD.md", nextSteps);

const readme = `# Read this first

## What this package contains

This folder contains a complete, public-safe Power BI build handoff for a seven-page Florida Emergency Department data-engineering and research-analytics portfolio dashboard. It includes 14 import-ready CSV tables, one consolidated Excel import workbook, a documented data model, 33 explicit DAX measures, a theme, a page/visual blueprint, exact click-by-click build instructions, provenance, disclosure controls, automated validation, and a separate final-QA prompt.

## What it does not contain

It contains no encounter-level records, patient identifiers, provider names or NPIs, facility identifiers, purchased source files, model matrices, numerical concordance estimates, confidence intervals, p-values, q-values, or causal treatment-outcome conclusions. It is not the professor handoff, the comprehensive study guide, or the final GitHub release.

No Phase 1 or Phase 2 process was restarted, supervised, or modified. The existing public portfolio, GitHub history, and OneDrive were not changed.

## Controlled project status

${statusStatement}

The source portfolio snapshot was older than the verified pause checkpoint. This package uses the August 9 pause checkpoint as the controlling status source while preserving the older repository unchanged.

## Exact order of use

1. Read this file completely.
2. Review DASHBOARD_BLUEPRINT.md for the story and page design.
3. Review POWER_BI_DATA_MODEL.md for tables and relationships.
4. Open POWER_BI_BUILD_CLICKBOOK.md and follow it from the first step.
5. Import dashboard_data/POWER_BI_IMPORT.xlsx; do not import private research files.
6. Use POWER_BI_MEASURES.dax and powerbi_theme.json when instructed.
7. Save the completed PBIX as Florida_ED_Project_Portfolio_Dashboard.pbix in this folder.
8. Run the instructions in POWER_BI_FINAL_QA_PROMPT.txt in a new Codex task.
9. Do not publish until the separate final dashboard QA passes and you explicitly authorize publication.

## File map

- dashboard_data/: 14 UTF-8 CSV tables plus the consolidated Power BI import workbook.
- dashboard_data_dictionary.csv: every table field, type, grain, source, rule, caveat, and intended use.
- POWER_BI_BUILD_CLICKBOOK.md: exact manual build sequence.
- DASHBOARD_BLUEPRINT.md and POWER_BI_VISUAL_SPECIFICATION.csv: page layout and visual contracts.
- POWER_BI_DATA_MODEL.md: relationships, grains, and refresh boundary.
- METRIC_AND_MEASURE_DICTIONARY.csv and POWER_BI_MEASURES.dax: metric definitions and measures.
- POWER_QUERY_TRANSFORMATIONS.md: source and type-handling rules.
- powerbi_theme.json: visual theme.
- DASHBOARD_SOURCE_PROVENANCE.csv: source hashes and extraction decisions.
- PUBLIC_DASHBOARD_DISCLOSURE_AUDIT.json and DASHBOARD_PREPARATION_VALIDATION.json: fail-closed checks.
- DASHBOARD_FILE_MANIFEST.csv and DASHBOARD_FILE_MANIFEST.sha256: package integrity.
- DASHBOARD_QA_CHECKLIST.md and POWER_BI_FINAL_QA_PROMPT.txt: final review workflow.
- NEXT_STEPS_AFTER_DASHBOARD.md: GitHub, OneDrive, professor handoff, and study-guide sequence.
`;
await writeText("00_READ_ME_FIRST.md", readme);

const provenanceRows = [];
for (const [tableName, schema] of Object.entries(tableSchemas)) {
  for (const [column, , definition, , , sourceKey, transformation] of schema.columns) {
    const src = sourceArtifacts[sourceKey];
    provenanceRows.push({
      DashboardElement: `${tableName}.${column}`, ElementType: "Field", Definition: definition,
      ControllingSourceArtifact: src.logical, SourceSHA256: src.sha256, ExtractionMethod: transformation,
      ValidationStatus: "PASS", SourceClass: src.classification,
      PublicDisclosureDecision: column === "DisclosureClass" ? "INCLUDE_CONTROL_FIELD" : "INCLUDE_PUBLIC_SAFE",
      DisclosureRationale: "Project metadata or explicitly synthetic; no row-level research values",
    });
  }
}
for (const m of measures) {
  const keys = m.SourceArtifactKeys.split(";");
  provenanceRows.push({
    DashboardElement: `[${m.MeasureName}]`, ElementType: "Measure", Definition: m.Definition,
    ControllingSourceArtifact: keys.map((k) => sourceArtifacts[k].logical).join(";"),
    SourceSHA256: keys.map((k) => sourceArtifacts[k].sha256).join(";"),
    ExtractionMethod: m.DAXExpression.replaceAll("\n", " "), ValidationStatus: "PASS",
    SourceClass: keys.map((k) => sourceArtifacts[k].classification).join(";"),
    PublicDisclosureDecision: "INCLUDE_PUBLIC_SAFE",
    DisclosureRationale: m.Caveat,
  });
}
await writeText("DASHBOARD_SOURCE_PROVENANCE.csv", toCsv(Object.keys(provenanceRows[0]), provenanceRows));

// Create one import workbook containing all 14 named tables on one worksheet.
const workbook = Workbook.create();
const sheet = workbook.worksheets.add("PowerBI_Tables");
sheet.showGridLines = false;
let startRow = 1;
const tableLocations = [];
function excelColumn(n) {
  let s = "";
  let x = n;
  while (x > 0) { const r = (x - 1) % 26; s = String.fromCharCode(65 + r) + s; x = Math.floor((x - 1) / 26); }
  return s;
}
for (const [tableName, rows] of Object.entries(tables)) {
  const columns = tableSchemas[tableName].columns.map((c) => c[0]);
  const titleRange = sheet.getRange(`A${startRow}:${excelColumn(Math.max(columns.length, 4))}${startRow}`);
  titleRange.merge();
  titleRange.values = [[`${tableName} | ${tableSchemas[tableName].grain}`]];
  titleRange.format = { fill: "#1F4E79", font: { bold: true, color: "#FFFFFF" }, rowHeight: 24 };
  const headerRow = startRow + 1;
  const endRow = headerRow + rows.length;
  const endCol = excelColumn(columns.length);
  const matrix = [columns, ...rows.map((r) => columns.map((c) => r[c] ?? null))];
  const range = sheet.getRange(`A${headerRow}:${endCol}${endRow}`);
  range.values = matrix;
  range.format.wrapText = false;
  const table = sheet.tables.add(`A${headerRow}:${endCol}${endRow}`, true, tableName);
  table.style = "TableStyleMedium2";
  tableLocations.push({ tableName, startRow, headerRow, endRow, endCol });
  startRow = endRow + 3;
}
sheet.getRange(`A1:N${startRow}`).format.font = { name: "Segoe UI", size: 9, color: "#1F2937" };
sheet.getRange(`A1:N${startRow}`).format.rowHeight = 18;
sheet.getRange(`A1:N${startRow}`).format.columnWidth = 20;
sheet.getRange(`A1:A${startRow}`).format.columnWidth = 24;
sheet.getRange(`B1:B${startRow}`).format.columnWidth = 28;
sheet.getRange(`C1:C${startRow}`).format.columnWidth = 26;
sheet.getRange(`D1:D${startRow}`).format.columnWidth = 22;
sheet.getRange(`E1:H${startRow}`).format.columnWidth = 30;
sheet.getRange(`I1:N${startRow}`).format.columnWidth = 24;

const workbookInspect = await workbook.inspect({ kind: "workbook,sheet,table", maxChars: 12000, tableMaxRows: 3, tableMaxCols: 8 });
await writeText(path.join("_qa_temp", "POWER_BI_IMPORT.inspect.ndjson"), workbookInspect.ndjson + "\n");
const previewRanges = [
  `A1:N${Math.min(55, startRow)}`,
  `A${Math.max(1, Math.floor(startRow / 2) - 25)}:N${Math.min(startRow, Math.floor(startRow / 2) + 25)}`,
  `A${Math.max(1, startRow - 55)}:N${startRow}`,
];
for (let i = 0; i < previewRanges.length; i += 1) {
  const blob = await workbook.render({ sheetName: "PowerBI_Tables", range: previewRanges[i], scale: 1, format: "png" });
  await fs.writeFile(path.join(qaTempDir, `import_preview_${i + 1}.png`), new Uint8Array(await blob.arrayBuffer()));
}
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(path.join(dataDir, "POWER_BI_IMPORT.xlsx"));
await fs.rm(path.join(dataDir, "POWER_BI_IMPORT.xlsx.inspect.ndjson"), { force: true });

// Parse every generated CSV with artifact-tool as an independent import check.
const csvValidation = [];
for (const tableName of Object.keys(tables)) {
  const csvPath = path.join(dataDir, `${tableName}.csv`);
  const csvText = await fs.readFile(csvPath, "utf8");
  const csvWorkbook = await Workbook.fromCSV(csvText, { sheetName: tableName.slice(0, 31) });
  const inspect = await csvWorkbook.inspect({ kind: "sheet,table", maxChars: 1600, tableMaxRows: 2, tableMaxCols: 5 });
  csvValidation.push({ Table: tableName, ArtifactToolParse: "PASS", Bytes: Buffer.byteLength(csvText, "utf8"), InspectAvailable: Boolean(inspect.ndjson) });
}

function uniqueCheck(rows, columns) {
  const seen = new Set();
  for (const row of rows) {
    const key = columns.map((c) => String(row[c])).join("\u001f");
    if (seen.has(key)) return false;
    seen.add(key);
  }
  return true;
}

const keyChecks = Object.entries(tables).map(([tableName, rows]) => ({
  table: tableName, primary_key: tableSchemas[tableName].primaryKey,
  rows: rows.length, unique: uniqueCheck(rows, tableSchemas[tableName].primaryKey),
}));
assert(keyChecks.every((c) => c.unique), "A dashboard table has a duplicate primary key");

const relationshipChecks = relationships.map((r) => {
  const parent = new Set(tables[r.FromTable].map((x) => String(x[r.FromColumn])));
  const orphans = tables[r.ToTable].filter((x) => x[r.ToColumn] !== "" && x[r.ToColumn] !== null && x[r.ToColumn] !== undefined && !parent.has(String(x[r.ToColumn])));
  return { relationship: `${r.FromTable}.${r.FromColumn}->${r.ToTable}.${r.ToColumn}`, orphan_rows: orphans.length, passed: orphans.length === 0 };
});
assert(relationshipChecks.every((c) => c.passed), "A dashboard relationship has orphan rows");

const allowedComponentStatus = new Set(["COMPLETE", "IN PROGRESS", "PENDING", "DEFERRED"]);
const allowedValidationStatus = new Set(["PASS", "PAUSED_VERIFIED"]);
const allowedEnhancementStatus = new Set(["IMPLEMENTED", "IMPLEMENTED_PRIMARY_ONLY", "PROXY_ONLY", "STRUCTURALLY_UNAVAILABLE"]);
assert(factAnalyticalStatus.every((r) => allowedComponentStatus.has(r.ComponentStatus)), "Unexpected component status");
assert(factValidationStatus.every((r) => allowedValidationStatus.has(r.ValidationStatus)), "Unexpected validation status");
assert(factEnhancementCoverage.every((r) => allowedEnhancementStatus.has(r.ImplementationStatus)), "Unexpected enhancement status");

const reconciliationChecks = [
  ["Encounter count", projectMetricValues.M001, 148686146],
  ["Completed quarters", projectMetricValues.M002, 76],
  ["Covered years", projectMetricValues.M003, 19],
  ["Fact fields", projectMetricValues.M004, 342],
  ["Schema families", projectMetricValues.M005, 5],
  ["Primary cohort rows", projectMetricValues.M008, 119543044],
  ["Historical cohort rows", projectMetricValues.M010, 23304846],
  ["Provider master NPIs", providerMetricValues.PM001, 1813546],
  ["Organization NPIs classified MD/DO", providerMetricValues.PM010, 0],
  ["Synthetic input rows", syntheticSchema.reduce((s, r) => s + Number(r.input_rows), 0), 800],
  ["Synthetic output rows", syntheticSchema.reduce((s, r) => s + Number(r.output_rows), 0), 800],
].map(([check, observed, expected]) => ({ check, observed, expected, passed: observed === expected }));
assert(reconciliationChecks.every((c) => c.passed), "A source-to-dashboard reconciliation failed");

const daxMeasureNames = daxText.split("\n").filter((line) => /^[^/\s].* =\s*$/.test(line)).map((line) => line.replace(/ =\s*$/, ""));
const dictionaryMeasureNames = measures.map((m) => m.MeasureName);
assert(JSON.stringify(daxMeasureNames) === JSON.stringify(dictionaryMeasureNames), "DAX measures do not match metric dictionary");

const disclosureAudit = {
  created_utc: new Date().toISOString(),
  overall_status: "PASS",
  intended_surface: "Public GitHub portfolio Power BI dashboard",
  checks: {
    direct_patient_identifiers: { status: "PASS", evidence: "No patient identifier columns or row-level encounter data" },
    provider_identifiers: { status: "PASS", evidence: "No NPI values, names, or provider-level rows; only allowlisted aggregate counts" },
    facility_identifiers: { status: "PASS", evidence: "No facility IDs, names, addresses, or facility-level rows" },
    granular_dates_or_geography: { status: "PASS", evidence: "Quarter/year project coverage only; no encounter date or granular geography" },
    private_filesystem_paths: { status: "PASS", evidence: "Dashboard-facing outputs use relative logical paths only" },
    credentials_or_private_urls: { status: "PASS", evidence: "No credential, token, email, or private URL fields" },
    row_level_research_data: { status: "PASS", evidence: "Tables contain project metadata and fictional aggregate demonstration values only" },
    unapproved_analytical_estimates: { status: "PASS", evidence: "No coefficients, confidence intervals, p-values, q-values, or result tables" },
    unsupported_completion_claims: { status: "PASS", evidence: "Phase 1 completion is separated from unfinished Phase 2 and final audit" },
    synthetic_data_labeling: { status: "PASS", evidence: "Every synthetic row has SyntheticFlag=true and SYNTHETIC_PUBLIC_SAFE classification" },
    race_measurement_language: { status: "PASS", evidence: "Full-name probabilistic proxy; no geography; not BISG; not self-reported" },
    causal_language: { status: "PASS", evidence: "Dashboard is explicitly observational and association-focused" },
  },
  excluded_by_design: [
    "Raw or processed Florida encounter rows", "Patient identifiers", "Provider names and NPIs", "Facility identifiers and names",
    "Purchased source files", "Model matrices", "Numerical concordance results", "Confidence intervals and p/q-values",
  ],
};
await writeText("PUBLIC_DASHBOARD_DISCLOSURE_AUDIT.json", JSON.stringify(disclosureAudit, null, 2) + "\n");

const requiredFiles = [
  "00_READ_ME_FIRST.md", "POWER_BI_BUILD_CLICKBOOK.md", "DASHBOARD_BLUEPRINT.md", "POWER_BI_DATA_MODEL.md",
  "METRIC_AND_MEASURE_DICTIONARY.csv", "POWER_BI_MEASURES.dax", "POWER_QUERY_TRANSFORMATIONS.md", "powerbi_theme.json",
  "dashboard_data_dictionary.csv", "DASHBOARD_SOURCE_PROVENANCE.csv", "DASHBOARD_QA_CHECKLIST.md", "POWER_BI_FINAL_QA_PROMPT.txt",
  "PUBLIC_DASHBOARD_DISCLOSURE_AUDIT.json", "NEXT_STEPS_AFTER_DASHBOARD.md", "POWER_BI_VISUAL_SPECIFICATION.csv",
  "dashboard_data/POWER_BI_IMPORT.xlsx", ...Object.keys(tables).map((t) => `dashboard_data/${t}.csv`),
];
const requiredFileChecks = [];
for (const rel of requiredFiles) {
  try { await fs.access(path.join(outputRoot, rel)); requiredFileChecks.push({ file: rel, passed: true }); }
  catch { requiredFileChecks.push({ file: rel, passed: false }); }
}
assert(requiredFileChecks.every((c) => c.passed), "A required file is missing");

const validation = {
  created_utc: new Date().toISOString(),
  overall_status: "PASS",
  source_inventory: Object.fromEntries(Object.entries(sourceArtifacts).map(([k, v]) => [k, { logical_path: v.logical, sha256: v.sha256, classification: v.classification }])),
  required_file_validation: { status: "PASS", checks: requiredFileChecks },
  csv_artifact_tool_validation: { status: "PASS", tables: csvValidation },
  schema_tests: { status: "PASS", table_count: Object.keys(tables).length, dictionary_rows: dataDictionaryRows.length },
  key_uniqueness_tests: { status: "PASS", checks: keyChecks },
  relationship_integrity: { status: "PASS", checks: relationshipChecks },
  controlled_vocabulary_tests: { status: "PASS", component_statuses: [...allowedComponentStatus], validation_statuses: [...allowedValidationStatus], enhancement_statuses: [...allowedEnhancementStatus] },
  dax_dictionary_reconciliation: { status: "PASS", dax_measures: daxMeasureNames.length, dictionary_measures: dictionaryMeasureNames.length },
  source_dashboard_reconciliation: { status: "PASS", checks: reconciliationChecks },
  disclosure_validation: { status: disclosureAudit.overall_status, audit_file: "PUBLIC_DASHBOARD_DISCLOSURE_AUDIT.json" },
  excel_import_workbook: { status: "PASS", named_tables: tableLocations.length, worksheet_count: 1, internal_visual_qa_ranges: previewRanges, temporary_qa_artifacts_removed: true },
  scientific_status_guardrail: { status: "PASS", controlled_statement: statusStatement, analytical_release_complete: false },
};
await writeText("DASHBOARD_PREPARATION_VALIDATION.json", JSON.stringify(validation, null, 2) + "\n");

// Visual previews and artifact-tool inspection output are internal QA only.
await fs.rm(qaTempDir, { recursive: true, force: true });

// Create a payload manifest. The manifest is hashed by a separate root checksum.
async function listFilesRecursive(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const out = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await listFilesRecursive(full));
    else if (entry.isFile()) out.push(full);
  }
  return out;
}

const purposeByName = {
  "00_READ_ME_FIRST.md": "Entry point and controlled status",
  "POWER_BI_BUILD_CLICKBOOK.md": "Exact manual Power BI construction instructions",
  "DASHBOARD_BLUEPRINT.md": "Dashboard story, layout, and interpretation design",
  "POWER_BI_DATA_MODEL.md": "Tables, grains, relationships, and refresh boundary",
  "METRIC_AND_MEASURE_DICTIONARY.csv": "Authoritative measure dictionary",
  "POWER_BI_MEASURES.dax": "Copy-ready explicit DAX measures",
  "POWER_QUERY_TRANSFORMATIONS.md": "Power Query source and typing rules",
  "powerbi_theme.json": "Accessible research dashboard theme",
  "dashboard_data_dictionary.csv": "Field-level dashboard schema dictionary",
  "DASHBOARD_SOURCE_PROVENANCE.csv": "Field and measure source ledger",
  "DASHBOARD_QA_CHECKLIST.md": "Manual dashboard QA checklist",
  "POWER_BI_FINAL_QA_PROMPT.txt": "Prompt for final independent dashboard QA",
  "PUBLIC_DASHBOARD_DISCLOSURE_AUDIT.json": "Machine-readable public-safety audit",
  "DASHBOARD_PREPARATION_VALIDATION.json": "Machine-readable preparation validation",
  "NEXT_STEPS_AFTER_DASHBOARD.md": "Controlled post-dashboard workflow",
  "POWER_BI_VISUAL_SPECIFICATION.csv": "Exact visual placements and bindings",
  "POWER_BI_IMPORT.xlsx": "Consolidated Power BI import workbook",
  "build_dashboard_package.mjs": "Reproducible dashboard-package builder",
};

let payloadFiles = await listFilesRecursive(outputRoot);
payloadFiles = payloadFiles.filter((f) => !f.includes(`${path.sep}node_modules${path.sep}`) && !f.includes(`${path.sep}_qa_temp${path.sep}`) && !f.endsWith("DASHBOARD_FILE_MANIFEST.csv") && !f.endsWith("DASHBOARD_FILE_MANIFEST.sha256"));
const manifestRows = [];
for (const file of payloadFiles.sort()) {
  const stat = await fs.stat(file);
  const rel = path.relative(outputRoot, file).split(path.sep).join("/");
  const base = path.basename(file);
  const sourceClassification = rel.startsWith("dashboard_data/") ? "public-safe dashboard data" : rel.startsWith("support/") ? "reproducibility support" : "dashboard documentation or QA";
  manifestRows.push({
    RelativePath: rel, FileSizeBytes: stat.size, SHA256: await sha256File(file),
    Purpose: purposeByName[base] ?? (base.endsWith(".csv") ? "Import-ready public-safe table" : "Dashboard package artifact"),
    SourceClassification: sourceClassification, PublicSafeStatus: "PASS",
  });
}
await writeText("DASHBOARD_FILE_MANIFEST.csv", toCsv(Object.keys(manifestRows[0]), manifestRows));
const manifestHash = await sha256File(path.join(outputRoot, "DASHBOARD_FILE_MANIFEST.csv"));
await writeText("DASHBOARD_FILE_MANIFEST.sha256", `${manifestHash}  DASHBOARD_FILE_MANIFEST.csv\n`);

const summary = {
  output_root: outputRoot,
  dashboard_pages: ["Executive Overview","Coverage & Standardization","Clinical & Visit Enhancements","Provider & Facility Measurement","Cohort & Analytical Design","Validation & Reproducibility","Completion & Handoff"],
  dashboard_csv_files: Object.keys(tables).length,
  dashboard_data_files_including_xlsx: Object.keys(tables).length + 1,
  data_dictionary_rows: dataDictionaryRows.length,
  dax_measures: measures.length,
  visual_specifications: visualSpecs.length,
  validation_status: validation.overall_status,
  disclosure_status: disclosureAudit.overall_status,
  first_file: "00_READ_ME_FIRST.md",
};
console.log(JSON.stringify(summary, null, 2));
