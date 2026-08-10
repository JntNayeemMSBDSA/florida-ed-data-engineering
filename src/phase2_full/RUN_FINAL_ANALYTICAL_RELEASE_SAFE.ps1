# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_FINAL_ANALYTICAL_RELEASE_SAFE.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (
        Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
    ).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter(Mandatory)]
    [int]$PostCanonicalSupervisorProcessId,

    [Parameter()]
    [int]$HashWorkers = 4
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Phase1 = Join-Path $WorkspaceRoot 'outputs\florida_ed_full_build_20260724'
$Phase2 = Join-Path $WorkspaceRoot `
    'outputs\florida_ed_concordance_analysis_20260726'
$Scripts = Join-Path $Phase2 'scripts'
$Logs = Join-Path $Phase2 'qa\run_logs\final_analytical_release'
$SupervisorMarker = Join-Path $Phase2 (
    'qa\run_logs\post_canonical_supervisor\' +
    'POST_CANONICAL_ANALYSIS_COMPLETE_PENDING_FINAL_RELEASE_AUDIT.log'
)
$SupervisorFailure = Join-Path $Phase2 (
    'qa\run_logs\post_canonical_supervisor\' +
    'POST_CANONICAL_ANALYSIS_FAILED_CLOSED.log'
)
$Start = Get-Date

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

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

$env:PYTHONPATH = Join-Path $WorkspaceRoot `
    'tmp\florida_ed_concordance_analysis_20260726\pydeps'
$env:PYTHONHASHSEED = '0'
$env:OMP_NUM_THREADS = '4'

function Write-Event {
    param([Parameter(Mandatory)][string]$Message)
    "[$(Get-Date -Format o)] $Message" |
        Tee-Object -FilePath (Join-Path $Logs 'FINAL_SUPERVISOR.log') -Append
}

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $log = Join-Path $Logs "${stamp}_${Name}.log"
    Write-Event "START $Name"
    $previousErrorAction = $ErrorActionPreference
    $exitCode = -1
    try {
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 2>&1 |
            Tee-Object -FilePath $log
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode. See $log"
    }
    Write-Event "PASS $Name"
}

try {
    Write-Event (
        "WAIT post-canonical supervisor PID " +
        "$PostCanonicalSupervisorProcessId"
    )
    $supervisor = Get-Process `
        -Id $PostCanonicalSupervisorProcessId `
        -ErrorAction SilentlyContinue
    if ($null -ne $supervisor) {
        Wait-Process -Id $PostCanonicalSupervisorProcessId
    }
    if (
        Test-Path -LiteralPath $SupervisorFailure -PathType Leaf
    ) {
        $failureItem = Get-Item -LiteralPath $SupervisorFailure
        if ($failureItem.LastWriteTime -ge $Start) {
            throw 'Post-canonical supervisor failed closed.'
        }
    }
    if (-not (Test-Path -LiteralPath $SupervisorMarker -PathType Leaf)) {
        throw 'Fresh post-canonical completion marker is missing.'
    }
    $marker = Get-Item -LiteralPath $SupervisorMarker
    if ($marker.LastWriteTime -lt $Start) {
        throw 'Post-canonical completion marker predates this final supervisor.'
    }
    $markerText = Get-Content -LiteralPath $SupervisorMarker -Raw
    if (
        $markerText -notmatch
        'PASS corrected primary AMI and complete directional'
    ) {
        throw 'Post-canonical completion marker content is invalid.'
    }
    Write-Event 'PASS post-canonical completion gate'

    Invoke-PythonStep '54b_global_multiplicity_tests' @(
        (Join-Path $Scripts `
            '54b_independent_global_multiplicity_audit_unit_tests.py')
    )
    Invoke-PythonStep '55b_phase1_immutability_tests' @(
        (Join-Path $Scripts `
            '55b_independent_phase1_immutability_audit_unit_tests.py')
    )
    Invoke-PythonStep '49b_complete_release_tests' @(
        (Join-Path $Scripts '49b_complete_release_audit_unit_tests.py')
    )
    Invoke-PythonStep '54_global_multiplicity_audit' @(
        (Join-Path $Scripts `
            '54_independent_global_multiplicity_audit.py'),
        '--phase2', $Phase2
    )
    Invoke-PythonStep '55_phase1_immutability_audit' @(
        (Join-Path $Scripts `
            '55_independent_phase1_immutability_audit.py'),
        '--phase1', $Phase1,
        '--phase2', $Phase2,
        '--workers', [string]$HashWorkers
    )
    Invoke-PythonStep '49_complete_analysis_release_audit' @(
        (Join-Path $Scripts '49_complete_analysis_release_audit.py'),
        '--phase2', $Phase2,
        '--phase1', $Phase1
    )
    Invoke-PythonStep '56_finalize_split_release_status' @(
        (Join-Path $Scripts '56_finalize_analytical_release_status.py'),
        '--phase2', $Phase2,
        '--phase1', $Phase1
    )

    $completeMarker = Join-Path $Logs (
        'ANALYTICAL_RELEASE_COMPLETE_REPORTS_DEFERRED.log'
    )
    (
        "[$(Get-Date -Format o)] PASS ANALYTICAL_RELEASE=" +
        "PASS_INDEPENDENTLY_AUDITED; REPORT_AND_PUBLIC_RELEASE=" +
        "DEFERRED_BY_USER_BUDGET"
    ) | Tee-Object -FilePath $completeMarker
}
catch {
    $message = $_.Exception.Message
    Write-Event "FAIL_CLOSED $message"
    $failedMarker = Join-Path $Logs `
        'ANALYTICAL_RELEASE_FAILED_CLOSED.log'
    "[$(Get-Date -Format o)] $message" |
        Tee-Object -FilePath $failedMarker
    throw
}
