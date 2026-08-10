# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_PHASE2.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter()]
    [ValidateSet('providers', 'validate', 'descriptive', 'classifications', 'ancillary', 'models', 'postmodels', 'finalize')]
    [string]$StartAt = 'providers',

    [Parameter()]
    [int]$Threads = 12,

    [Parameter()]
    [string]$MemoryLimit = '24GB'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Phase2 = Join-Path $WorkspaceRoot 'outputs\florida_ed_concordance_analysis_20260726'
$Release = Join-Path $WorkspaceRoot 'outputs\florida_ed_full_build_20260724'
$Temp = Join-Path $WorkspaceRoot 'tmp\florida_ed_concordance_analysis_20260726'
$Scripts = Join-Path $Phase2 'scripts'
$Logs = Join-Path $Phase2 'qa\run_logs'
$MatrixRoot = Join-Path $Phase2 'analysis_data\model_matrices'
$ModelScratch = Join-Path $Temp 'model_scratch'
$OutcomeSpecificScratch = Join-Path $Temp 'outcome_specific_model_scratch'

New-Item -ItemType Directory -Force -Path $Logs, $Temp, $ModelScratch, $OutcomeSpecificScratch | Out-Null

if ([string]::IsNullOrWhiteSpace($Python)) {
    $resolvedPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $resolvedPython) {
        throw 'Python was not found on PATH. Supply -Python with an absolute executable path.'
    }
    $Python = $resolvedPython.Source
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python runtime not found: $Python"
}
if (-not (Test-Path -LiteralPath $Release -PathType Container)) {
    throw "Immutable source release not found: $Release"
}

$env:PYTHONPATH = Join-Path $Temp 'pydeps'
$env:PYTHONHASHSEED = '0'
$env:OMP_NUM_THREADS = [string][Math]::Max(1, [Math]::Min($Threads, 16))

$orderedStages = @(
    'providers',
    'validate',
    'descriptive',
    'classifications',
    'ancillary',
    'models',
    'postmodels',
    'finalize'
)
$startIndex = [Array]::IndexOf($orderedStages, $StartAt)

function Invoke-Phase2Step {
    param(
        [Parameter(Mandatory)]
        [string]$Stage,
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    if ([Array]::IndexOf($orderedStages, $Stage) -lt $startIndex) {
        return
    }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $logPath = Join-Path $Logs "${stamp}_${Name}.log"
    "[$(Get-Date -Format o)] START $Name" | Tee-Object -FilePath $logPath
    & $Python @Arguments 2>&1 | Tee-Object -FilePath $logPath -Append
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Step '$Name' failed with exit code $exitCode. See $logPath"
    }
    "[$(Get-Date -Format o)] PASS $Name" | Tee-Object -FilePath $logPath -Append
}

function Script-Path([string]$Name) {
    return (Join-Path $Scripts $Name)
}

Invoke-Phase2Step 'providers' '03b_outcome_specific_policy_tests' @(
    (Script-Path '03b_outcome_specific_policy_tests.py')
)

Invoke-Phase2Step 'providers' '03c_gate_binding_unit_tests' @(
    (Script-Path '03c_gate_binding_unit_tests.py'),
    '--phase2', $Phase2
)

Invoke-Phase2Step 'providers' '04a_build_provider_master_v2' @(
    (Script-Path '04a_build_provider_master_v2.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--dictionary-root', (Join-Path (Split-Path $WorkspaceRoot -Parent) 'Dictionary'),
    '--temp', (Join-Path $Temp 'provider_master_v2'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit,
    '--hash-large-sources'
)

Invoke-Phase2Step 'providers' '04aa_finalize_provider_source_hashes' @(
    (Script-Path '04aa_finalize_provider_source_hashes.py'),
    '--phase2', $Phase2
)

Invoke-Phase2Step 'providers' '04b_build_physician_race_proxy_v2' @(
    (Script-Path '04b_build_physician_race_proxy_v2.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'physician_race_proxy_v2'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'providers' '04_build_analysis_cohort_provider_v2' @(
    (Script-Path '04_build_analysis_cohort.py'),
    '--release', $Release,
    '--external', (Join-Path $Phase2 'external_sources'),
    '--output', (Join-Path $Phase2 'analysis_data'),
    '--temp', (Join-Path $Temp 'cohort_provider_v2'),
    '--years', '2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024',
    '--quarters', '1,2,3,4',
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit,
    '--provider-master-v2', (Join-Path $Phase2 'analysis_data\dimensions\provider_master_v2.parquet'),
    '--provider-race-proxy-v2', (Join-Path $Phase2 'analysis_data\dimensions\provider_race_proxy_v2.parquet'),
    '--cohort-dir-name', 'concordance_visit_data_provider_v2'
)

Invoke-Phase2Step 'providers' '04c_validate_provider_race_v2' @(
    (Script-Path '04c_validate_provider_race_v2.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'validate' '05_validate_analysis_cohort' @(
    (Script-Path '05_validate_analysis_cohort.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--temp', (Join-Path $Temp 'validate_cohort'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'descriptive' '06_descriptive_analysis' @(
    (Script-Path '06_descriptive_analysis.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'descriptive'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'classifications' '11_build_clinical_classification_review' @(
    (Script-Path '11_build_clinical_classification_review.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--temp', (Join-Path $Temp 'clinical_classification'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'classifications' '12_build_concordance_variable_dictionary' @(
    (Script-Path '12_build_concordance_variable_dictionary.py'),
    '--phase2', $Phase2,
    '--release', $Release
)

Invoke-Phase2Step 'ancillary' '13_build_historical_sensitivity_cohort' @(
    (Script-Path '13_build_historical_sensitivity_cohort.py'),
    '--release', $Release,
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_cohort'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'ancillary' '13b_validate_historical_provider_v2' @(
    (Script-Path '13b_validate_historical_provider_v2.py'),
    '--release', $Release,
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_validation'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'ancillary' '15_linkage_selection_audit' @(
    (Script-Path '15_linkage_selection_audit.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--temp', (Join-Path $Temp 'linkage_selection'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'ancillary' '20_additional_cohort_sensitivities' @(
    (Script-Path '20_additional_cohort_sensitivities.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--temp', (Join-Path $Temp 'additional_cohorts'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'ancillary' '10_ami_validation_and_analysis' @(
    (Script-Path '10_ami_validation_and_analysis.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'ami'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'ancillary' '10b_historical_ami_greenwood_analysis' @(
    (Script-Path '10b_historical_ami_greenwood_analysis.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_ami'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

# All matrix work is delegated to the storage-safe runner. It builds,
# estimates, independently audits, and compacts one matrix family at a time.
# This prevents the legacy block below from accumulating every full-cohort
# matrix and its demeaning scratch products simultaneously.
$safeStart = if ($StartAt -eq 'finalize') { 'finalize' } else { 'common' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (
    Join-Path $Scripts 'RUN_PHASE2_REMAINING_SAFE.ps1'
) `
    -WorkspaceRoot $WorkspaceRoot `
    -Python $Python `
    -StartAt $safeStart `
    -Threads $Threads `
    -MemoryLimit $MemoryLimit
if ($LASTEXITCODE -ne 0) {
    throw "Storage-safe Phase 2 continuation failed with exit code $LASTEXITCODE"
}
"[$(Get-Date -Format o)] RUN_PHASE2 completed through storage-safe delegation." |
    Tee-Object -FilePath (Join-Path $Logs 'RUN_PHASE2_COMPLETE.log')
return

foreach ($cohort in @('race', 'sex_gender')) {
    Invoke-Phase2Step 'models' "07_prepare_primary_model_matrix_${cohort}" @(
        (Script-Path '07_prepare_primary_model_matrix.py'),
        '--phase2', $Phase2,
        '--scratch', $MatrixRoot,
        '--cohort', $cohort,
        '--threads', [string]$Threads,
        '--memory-limit', $MemoryLimit
    )

    Invoke-Phase2Step 'models' "08_estimate_primary_models_${cohort}" @(
        (Script-Path '08_estimate_primary_models.py'),
        '--matrix-root', $MatrixRoot,
        '--scratch', $ModelScratch,
        '--output', (Join-Path $Phase2 'results\models'),
        '--cohort', $cohort,
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )
}

# The common LOS/charge sample above is retained as a robustness analysis.
# These four matrices restore the frozen SAP's outcome-specific confirmatory
# samples so missingness in one outcome never excludes an observed value of
# the other outcome.
$outcomeSpecificSamples = @(
    @{
        Id = 'los'
        Policy = 'los_outcome'
    },
    @{
        Id = 'charge'
        Policy = 'charge_outcome'
    }
)
foreach ($sample in $outcomeSpecificSamples) {
    foreach ($cohort in @('race', 'sex_gender')) {
        $matrixId = "${cohort}__$($sample.Id)"
        Invoke-Phase2Step 'models' "07_prepare_outcome_specific_${cohort}_$($sample.Id)" @(
            (Script-Path '07_prepare_primary_model_matrix.py'),
            '--phase2', $Phase2,
            '--scratch', $MatrixRoot,
            '--cohort', $cohort,
            '--analysis-sample', $sample.Policy,
            '--matrix-id', $matrixId,
            '--threads', [string]$Threads,
            '--memory-limit', $MemoryLimit
        )

        Invoke-Phase2Step 'models' "08_estimate_outcome_specific_${cohort}_$($sample.Id)" @(
            (Script-Path '08_estimate_primary_models.py'),
            '--matrix-root', $MatrixRoot,
            '--matrix-id', $matrixId,
            '--scratch', (Join-Path $OutcomeSpecificScratch $sample.Id),
            '--output', (Join-Path $Phase2 "results\outcome_specific_primary\$($sample.Id)"),
            '--cohort', $cohort,
            '--bootstrap-draws', '9999',
            '--seed', '20260726'
        )
    }
}

$cohortSensitivityVariants = @(
    @{
        Id = 'direct_plus_unique_license_nh_t50'
        Policy = 'race_direct_plus_unique_license_nh_t50'
    },
    @{
        Id = 'race_only_direct_t50'
        Policy = 'race_only_direct_t50'
    }
)
foreach ($variant in $cohortSensitivityVariants) {
    foreach ($sample in $outcomeSpecificSamples) {
        $matrixId = "race__$($variant.Id)__$($sample.Id)"
        Invoke-Phase2Step 'models' "07_prepare_${matrixId}" @(
            (Script-Path '07_prepare_primary_model_matrix.py'),
            '--phase2', $Phase2,
            '--scratch', $MatrixRoot,
            '--cohort', 'race',
            '--analysis-sample', $sample.Policy,
            '--eligibility-policy', $variant.Policy,
            '--matrix-id', $matrixId,
            '--threads', [string]$Threads,
            '--memory-limit', $MemoryLimit
        )

        Invoke-Phase2Step 'models' "08_estimate_${matrixId}" @(
            (Script-Path '08_estimate_primary_models.py'),
            '--matrix-root', $MatrixRoot,
            '--matrix-id', $matrixId,
            '--scratch', (Join-Path $Temp "cohort_definition_model_scratch\$($variant.Id)\$($sample.Id)"),
            '--output', (Join-Path $Phase2 "results\cohort_definition_adjusted\$($variant.Id)\$($sample.Id)"),
            '--cohort', 'race',
            '--bootstrap-draws', '9999',
            '--seed', '20260726'
        )
    }
}

Invoke-Phase2Step 'postmodels' '18_race_threshold_probability_sensitivities' @(
    (Script-Path '18_race_threshold_probability_sensitivities.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--scratch', (Join-Path $Temp 'race_threshold_models'),
    '--output', (Join-Path $Phase2 'results'),
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

foreach ($cohort in @('race', 'sex_gender')) {
    Invoke-Phase2Step 'postmodels' "25_outcome_appropriate_glm_${cohort}" @(
        (Script-Path '25_outcome_appropriate_glm_sensitivities.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--output', (Join-Path $Phase2 'results\outcome_appropriate_glm'),
        '--cohort', $cohort,
        '--target-rows', '2000000',
        '--tolerance', '1e-8',
        '--max-iterations', '100',
        '--seed', '20260726'
    )

    Invoke-Phase2Step 'postmodels' "19_heterogeneity_models_${cohort}" @(
        (Script-Path '19_heterogeneity_models.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $ModelScratch,
        '--scratch', (Join-Path $Temp 'heterogeneity'),
        '--output', (Join-Path $Phase2 'results\heterogeneity'),
        '--cohort', $cohort,
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )

    Invoke-Phase2Step 'postmodels' "26_leave_one_year_out_${cohort}" @(
        (Script-Path '26_leave_one_year_out_primary_models.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $ModelScratch,
        '--scratch', (Join-Path $Temp 'leave_one_year_out'),
        '--output', (Join-Path $Phase2 'results\leave_one_year_out'),
        '--cohort', $cohort,
        '--block-columns', '4',
        '--tolerance', '1e-8',
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )

    Invoke-Phase2Step 'postmodels' "27_exact_subset_sensitivities_${cohort}" @(
        (Script-Path '27_exact_subset_sensitivities.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $ModelScratch,
        '--scratch', (Join-Path $Temp 'exact_subset_sensitivities'),
        '--output', (Join-Path $Phase2 'results\exact_subset_sensitivities'),
        '--cohort', $cohort,
        '--block-columns', '4',
        '--tolerance', '1e-8',
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )
}

Invoke-Phase2Step 'postmodels' '19b_payer_category_heterogeneity' @(
    (Script-Path '19b_payer_category_heterogeneity.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $ModelScratch,
    '--scratch', (Join-Path $Temp 'payer_category_heterogeneity'),
    '--output', (Join-Path $Phase2 'results\payer_category_heterogeneity'),
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

Invoke-Phase2Step 'postmodels' '21_intersectional_analysis' @(
    (Script-Path '21_intersectional_analysis.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--scratch', (Join-Path $Temp 'intersectional'),
    '--output', (Join-Path $Phase2 'results\intersectional'),
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

Invoke-Phase2Step 'postmodels' '23_race_proxy_multiple_imputation' @(
    (Script-Path '23_race_proxy_multiple_imputation.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $ModelScratch,
    '--scratch', (Join-Path $Temp 'race_proxy_mi'),
    '--output', (Join-Path $Phase2 'results\race_proxy_multiple_imputation'),
    '--imputations', '20',
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

foreach ($cohort in @('race', 'sex_gender')) {
    Invoke-Phase2Step 'postmodels' "24_negative_control_${cohort}" @(
        (Script-Path '24_negative_control_analysis.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $ModelScratch,
        '--scratch', (Join-Path $Temp 'negative_control'),
        '--output', (Join-Path $Phase2 'results\negative_control'),
        '--cohort', $cohort,
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )
}

Invoke-Phase2Step 'postmodels' '17_historical_sensitivity_analysis' @(
    (Script-Path '17_historical_sensitivity_analysis.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_analysis'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'postmodels' '17b_historical_sex_gender_sensitivity' @(
    (Script-Path '17b_historical_sex_gender_sensitivity.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_sex_gender'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Phase2Step 'finalize' '30_independent_primary_results_audit' @(
    (Script-Path '30_independent_primary_results_audit.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $ModelScratch,
    '--row-chunk', '333333'
)

Invoke-Phase2Step 'finalize' '30b_independent_outcome_specific_results_audit' @(
    (Script-Path '30b_independent_outcome_specific_results_audit.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $OutcomeSpecificScratch,
    '--row-chunk', '333333'
)

Invoke-Phase2Step 'finalize' '30c_independent_cohort_definition_results_audit' @(
    (Script-Path '30c_independent_cohort_definition_results_audit.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', (Join-Path $Temp 'cohort_definition_model_scratch'),
    '--row-chunk', '333333'
)

Invoke-Phase2Step 'finalize' '30d_independent_payer_heterogeneity_audit' @(
    (Script-Path '30d_independent_payer_heterogeneity_audit.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $ModelScratch,
    '--payer-scratch', (Join-Path $Temp 'payer_category_heterogeneity'),
    '--row-chunk', '333333'
)

Invoke-Phase2Step 'finalize' '31_independent_historical_results_audit' @(
    (Script-Path '31_independent_historical_results_audit.py'),
    '--phase2', $Phase2
)

Invoke-Phase2Step 'finalize' '16_apply_multiple_testing' @(
    (Script-Path '16_apply_multiple_testing.py'),
    '--phase2', $Phase2
)

Invoke-Phase2Step 'finalize' '22_capture_environment' @(
    (Script-Path '22_capture_environment.py'),
    '--phase2', $Phase2
)

"[$(Get-Date -Format o)] RUN_PHASE2 completed successfully." |
    Tee-Object -FilePath (Join-Path $Logs 'RUN_PHASE2_COMPLETE.log')
