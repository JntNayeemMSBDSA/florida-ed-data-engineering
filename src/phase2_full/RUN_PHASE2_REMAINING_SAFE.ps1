# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_PHASE2_REMAINING_SAFE.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter()]
    [ValidateSet(
        'gate',
        'descriptive',
        'historical',
        'ancillary',
        'common',
        'outcome_specific',
        'cohort_definitions',
        'finalize'
    )]
    [string]$StartAt = 'gate',

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
$ProviderV2Cohort = Join-Path $Phase2 'analysis_data\concordance_visit_data_provider_v2'

New-Item -ItemType Directory -Force -Path $Logs, $Temp | Out-Null

if ([string]::IsNullOrWhiteSpace($Python)) {
    $resolvedPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $resolvedPython) {
        throw 'Python was not found on PATH. Supply -Python explicitly.'
    }
    $Python = $resolvedPython.Source
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python runtime not found: $Python"
}
if (-not (Test-Path -LiteralPath $Release -PathType Container)) {
    throw "Immutable Phase 1 release not found: $Release"
}

$successCount = @(
    Get-ChildItem -LiteralPath $ProviderV2Cohort -Recurse -Filter '_SUCCESS.json' -File -ErrorAction SilentlyContinue
).Count
if ($successCount -ne 60) {
    throw "Provider-v2 primary cohort is incomplete: $successCount of 60 partitions pass."
}

$env:PYTHONPATH = Join-Path $Temp 'pydeps'
$env:PYTHONHASHSEED = '0'
$env:OMP_NUM_THREADS = [string][Math]::Max(1, [Math]::Min($Threads, 16))

$stages = @(
    'gate',
    'descriptive',
    'historical',
    'ancillary',
    'common',
    'outcome_specific',
    'cohort_definitions',
    'finalize'
)
$startIndex = [Array]::IndexOf($stages, $StartAt)

function Should-Run([string]$Stage) {
    return [Array]::IndexOf($stages, $Stage) -ge $startIndex
}

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory)]
        [string]$Stage,
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )
    if (-not (Should-Run $Stage)) {
        return
    }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $log = Join-Path $Logs "${stamp}_${Name}.log"
    "[$(Get-Date -Format o)] START $Name" | Tee-Object -FilePath $log
    $previousErrorAction = $ErrorActionPreference
    $processExitCode = -1
    try {
        # Preserve native stderr in the audit log, but fail on the native
        # process exit code rather than on a warning emitted to stderr.
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 2>&1 | Tee-Object -FilePath $log -Append
        $processExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($processExitCode -ne 0) {
        throw "Step '$Name' failed. See $log"
    }
    "[$(Get-Date -Format o)] PASS $Name" | Tee-Object -FilePath $log -Append
}

function Invoke-Runner {
    param(
        [Parameter(Mandatory)]
        [string]$Stage,
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string]$Runner
    )
    if (-not (Should-Run $Stage)) {
        return
    }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $log = Join-Path $Logs "${stamp}_${Name}.log"
    "[$(Get-Date -Format o)] START $Name" | Tee-Object -FilePath $log
    $previousErrorAction = $ErrorActionPreference
    $processExitCode = -1
    try {
        $ErrorActionPreference = 'Continue'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Runner `
            -WorkspaceRoot $WorkspaceRoot `
            -Python $Python `
            -Threads $Threads `
            -MemoryLimit $MemoryLimit 2>&1 |
            Tee-Object -FilePath $log -Append
        $processExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($processExitCode -ne 0) {
        throw "Runner '$Name' failed. See $log"
    }
    "[$(Get-Date -Format o)] PASS $Name" | Tee-Object -FilePath $log -Append
}

Invoke-PythonStep 'gate' '03_definition_unit_tests' @(
    (Join-Path $Scripts '03_unit_tests.py'),
    '--output', (Join-Path $Phase2 'qa')
)

Invoke-PythonStep 'gate' '03b_outcome_specific_policy_tests' @(
    (Join-Path $Scripts '03b_outcome_specific_policy_tests.py')
)

Invoke-PythonStep 'gate' '03c_gate_binding_unit_tests' @(
    (Join-Path $Scripts '03c_gate_binding_unit_tests.py'),
    '--phase2', $Phase2
)

Invoke-PythonStep 'gate' '03d_storage_safe_checkpoint_unit_tests' @(
    (Join-Path $Scripts '03d_storage_safe_checkpoint_unit_tests.py'),
    '--phase2', $Phase2
)

Invoke-PythonStep 'gate' '03e_inference_engine_unit_tests' @(
    (Join-Path $Scripts '03e_inference_engine_unit_tests.py'),
    '--phase2', $Phase2
)

Invoke-PythonStep 'gate' '09_validate_hdfe_engine_against_pyfixest' @(
    (Join-Path $Scripts '09_validate_hdfe_engine.py'),
    '--phase2', $Phase2,
    '--scratch', (Join-Path $Temp 'hdfe_engine_reference')
)

Invoke-PythonStep 'gate' '04aa_finalize_provider_source_hashes' @(
    (Join-Path $Scripts '04aa_finalize_provider_source_hashes.py'),
    '--phase2', $Phase2
)

Invoke-PythonStep 'gate' '04c_validate_provider_race_v2' @(
    (Join-Path $Scripts '04c_validate_provider_race_v2.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-PythonStep 'gate' '05_validate_analysis_cohort' @(
    (Join-Path $Scripts '05_validate_analysis_cohort.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--temp', (Join-Path $Temp 'validate_cohort'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-PythonStep 'descriptive' '06_descriptive_analysis' @(
    (Join-Path $Scripts '06_descriptive_analysis.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'descriptive'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-PythonStep 'descriptive' '11_build_clinical_classification_review' @(
    (Join-Path $Scripts '11_build_clinical_classification_review.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--temp', (Join-Path $Temp 'clinical_classification'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-PythonStep 'descriptive' '12_build_concordance_variable_dictionary' @(
    (Join-Path $Scripts '12_build_concordance_variable_dictionary.py'),
    '--phase2', $Phase2,
    '--release', $Release
)

Invoke-Runner 'historical' 'RUN_HISTORICAL_PROVIDER_V2' (
    Join-Path $Scripts 'RUN_HISTORICAL_PROVIDER_V2.ps1'
)

Invoke-PythonStep 'ancillary' '15_linkage_selection_audit' @(
    (Join-Path $Scripts '15_linkage_selection_audit.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--temp', (Join-Path $Temp 'linkage_selection'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-PythonStep 'ancillary' '20_additional_cohort_sensitivities' @(
    (Join-Path $Scripts '20_additional_cohort_sensitivities.py'),
    '--phase2', $Phase2,
    '--release', $Release,
    '--temp', (Join-Path $Temp 'additional_cohorts'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-PythonStep 'ancillary' '10_ami_validation_and_analysis' @(
    (Join-Path $Scripts '10_ami_validation_and_analysis.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'ami'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-Runner 'common' 'RUN_COMMON_PRIMARY_SAFE' (
    Join-Path $Scripts 'RUN_COMMON_PRIMARY_SAFE.ps1'
)

Invoke-Runner 'outcome_specific' 'RUN_OUTCOME_SPECIFIC_PRIMARY' (
    Join-Path $Scripts 'RUN_OUTCOME_SPECIFIC_PRIMARY.ps1'
)

Invoke-Runner 'cohort_definitions' 'RUN_COHORT_DEFINITION_SENSITIVITIES' (
    Join-Path $Scripts 'RUN_COHORT_DEFINITION_SENSITIVITIES.ps1'
)

Invoke-PythonStep 'finalize' '16_apply_multiple_testing' @(
    (Join-Path $Scripts '16_apply_multiple_testing.py'),
    '--phase2', $Phase2
)

Invoke-PythonStep 'finalize' '22_capture_environment' @(
    (Join-Path $Scripts '22_capture_environment.py'),
    '--phase2', $Phase2
)

"[$(Get-Date -Format o)] RUN_PHASE2_REMAINING_SAFE completed successfully." |
    Tee-Object -FilePath (Join-Path $Logs 'RUN_PHASE2_REMAINING_SAFE_COMPLETE.log')
