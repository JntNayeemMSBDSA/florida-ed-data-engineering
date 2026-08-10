# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_HISTORICAL_PROVIDER_V2.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter()]
    [ValidateSet('build', 'validate', 'models', 'audit')]
    [string]$StartAt = 'build',

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

$env:PYTHONPATH = Join-Path $Temp 'pydeps'
$env:PYTHONHASHSEED = '0'
$env:OMP_NUM_THREADS = [string][Math]::Max(1, [Math]::Min($Threads, 16))

$orderedStages = @('build', 'validate', 'models', 'audit')
$startIndex = [Array]::IndexOf($orderedStages, $StartAt)

function Script-Path([string]$Name) {
    return (Join-Path $Scripts $Name)
}

function Invoke-HistoricalStep {
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
    "[$(Get-Date -Format o)] START $Name" |
        Tee-Object -FilePath $logPath
    $previousErrorAction = $ErrorActionPreference
    $processExitCode = -1
    try {
        # Native tools legitimately write warnings to stderr. Capture those
        # warnings in the log, but use the native exit code—not PowerShell's
        # stderr wrapper record—to determine whether the step failed.
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 2>&1 |
            Tee-Object -FilePath $logPath -Append
        $processExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($processExitCode -ne 0) {
        throw "Historical step '$Name' failed. See $logPath"
    }
    "[$(Get-Date -Format o)] PASS $Name" |
        Tee-Object -FilePath $logPath -Append
}

Invoke-HistoricalStep 'build' '13_build_historical_sensitivity_cohort' @(
    (Script-Path '13_build_historical_sensitivity_cohort.py'),
    '--release', $Release,
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_cohort'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-HistoricalStep 'validate' '13b_validate_historical_provider_v2' @(
    (Script-Path '13b_validate_historical_provider_v2.py'),
    '--release', $Release,
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_validation'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-HistoricalStep 'models' '10b_historical_ami_greenwood_analysis' @(
    (Script-Path '10b_historical_ami_greenwood_analysis.py'),
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_ami'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-HistoricalStep 'models' '17_historical_sensitivity_analysis' @(
    (Script-Path 'run_historical_sensitivity_isolated.py'),
    '--analysis', 'race',
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_analysis'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-HistoricalStep 'models' '17b_historical_sex_gender_sensitivity' @(
    (Script-Path 'run_historical_sensitivity_isolated.py'),
    '--analysis', 'sex_gender',
    '--phase2', $Phase2,
    '--temp', (Join-Path $Temp 'historical_sex_gender'),
    '--threads', [string]$Threads,
    '--memory-limit', $MemoryLimit
)

Invoke-HistoricalStep 'audit' '31_independent_historical_results_audit' @(
    (Script-Path '31_independent_historical_results_audit.py'),
    '--phase2', $Phase2
)

"[$(Get-Date -Format o)] RUN_HISTORICAL_PROVIDER_V2 completed successfully." |
    Tee-Object -FilePath (
        Join-Path $Logs 'RUN_HISTORICAL_PROVIDER_V2_COMPLETE.log'
    )
