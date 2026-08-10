# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/HANDOFF_LIVE_LEGACY_RUNNER.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter(Mandatory)]
    [int]$LegacyRunnerPid,

    [Parameter(Mandatory)]
    [int]$CohortBuilderPid,

    [Parameter(Mandatory)]
    [string]$Python,

    [Parameter()]
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Phase2 = Join-Path $WorkspaceRoot 'outputs\florida_ed_concordance_analysis_20260726'
$CohortRoot = Join-Path $Phase2 'analysis_data\concordance_visit_data_provider_v2'
$ManifestPath = Join-Path $Phase2 'analysis_data\cohort_build_manifest.json'
$StatePath = Join-Path $Phase2 'qa\live_legacy_runner_handoff.json'
$SafeRunner = Join-Path $PSScriptRoot 'RUN_PHASE2_REMAINING_SAFE.ps1'

function Write-State {
    param(
        [Parameter(Mandatory)]
        [string]$Status,
        [Parameter()]
        [hashtable]$Additional = @{}
    )
    $payload = [ordered]@{
        updated_utc = (Get-Date).ToUniversalTime().ToString('o')
        status = $Status
        monitor_process_id = $PID
        legacy_runner_process_id = $LegacyRunnerPid
        cohort_builder_process_id = $CohortBuilderPid
    }
    foreach ($key in $Additional.Keys) {
        $payload[$key] = $Additional[$key]
    }
    $temporary = "$StatePath.tmp"
    $payload | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $StatePath -Force
}

try {
    $legacy = Get-CimInstance Win32_Process -Filter "ProcessId=$LegacyRunnerPid"
    $builder = Get-CimInstance Win32_Process -Filter "ProcessId=$CohortBuilderPid"
    if (
        $null -eq $legacy -or
        $legacy.CommandLine -notmatch 'RUN_PHASE2\.ps1' -or
        $null -eq $builder -or
        $builder.ParentProcessId -ne $LegacyRunnerPid -or
        $builder.CommandLine -notmatch '04_build_analysis_cohort\.py' -or
        $builder.CommandLine -notmatch 'concordance_visit_data_provider_v2'
    ) {
        throw 'Live process identities do not match the authorized handoff targets.'
    }

    Write-State 'waiting_for_60_provider_v2_partitions'
    while ($true) {
        $builderProcess = Get-Process -Id $CohortBuilderPid -ErrorAction SilentlyContinue
        $successCount = @(
            Get-ChildItem -LiteralPath $CohortRoot -Recurse -Filter '_SUCCESS.json' -File -ErrorAction SilentlyContinue
        ).Count
        if ($successCount -eq 60) {
            break
        }
        if ($null -eq $builderProcess) {
            throw "Cohort builder exited with only $successCount of 60 partitions."
        }
        Start-Sleep -Seconds 10
    }

    # Stop only the legacy PowerShell parent while the completed 60-partition
    # Python writer finishes its manifest. This prevents the old in-memory AST
    # from launching the unsafe all-matrix block.
    $legacy = Get-CimInstance Win32_Process -Filter "ProcessId=$LegacyRunnerPid"
    if (
        $null -ne $legacy -and
        $legacy.CommandLine -match 'RUN_PHASE2\.ps1'
    ) {
        Stop-Process -Id $LegacyRunnerPid -Force
    }
    Write-State 'legacy_parent_stopped_waiting_for_manifest' @{
        provider_v2_partitions = 60
    }

    Wait-Process -Id $CohortBuilderPid -ErrorAction SilentlyContinue

    $manifestReady = $false
    for ($attempt = 0; $attempt -lt 24; $attempt++) {
        if (Test-Path -LiteralPath $ManifestPath -PathType Leaf) {
            $manifest = Get-Content -LiteralPath $ManifestPath -Raw |
                ConvertFrom-Json
            $manifestReady = (
                @($manifest.years).Count -eq 15 -and
                @($manifest.quarters).Count -eq 4 -and
                @($manifest.partitions).Count -eq 60 -and
                $manifest.sample_modulus -eq 0 -and
                $manifest.source_release_modified -eq $false
            )
            if ($manifestReady) {
                break
            }
        }
        Start-Sleep -Seconds 5
    }
    if (-not $manifestReady) {
        throw 'Full provider-v2 cohort manifest did not become valid after the builder exited.'
    }

    Write-State 'starting_storage_safe_continuation' @{
        provider_v2_partitions = 60
        cohort_manifest = $ManifestPath
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SafeRunner `
        -WorkspaceRoot $WorkspaceRoot `
        -Python $Python `
        -StartAt gate `
        -Threads 12 `
        -MemoryLimit '24GB'
    if ($LASTEXITCODE -ne 0) {
        throw "Storage-safe continuation failed with exit code $LASTEXITCODE"
    }
    Write-State 'storage_safe_continuation_complete' @{
        provider_v2_partitions = 60
        cohort_manifest = $ManifestPath
    }
}
catch {
    Write-State 'failed' @{
        error = $_.Exception.Message
        script_stack_trace = $_.ScriptStackTrace
    }
    throw
}
