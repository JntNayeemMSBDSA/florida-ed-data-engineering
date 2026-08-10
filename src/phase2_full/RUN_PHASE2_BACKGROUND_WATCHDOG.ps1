# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_PHASE2_BACKGROUND_WATCHDOG.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (
        Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
    ).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter()]
    [int]$ExistingCanonicalProcessId = 0,

    [Parameter()]
    [int]$ExistingPostCanonicalProcessId = 0,

    [Parameter()]
    [int]$ExistingFinalSupervisorProcessId = 0,

    [Parameter()]
    [int]$Threads = 12,

    [Parameter()]
    [string]$MemoryLimit = '24GB',

    [Parameter()]
    [int]$HashWorkers = 4
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Phase2 = Join-Path $WorkspaceRoot `
    'outputs\florida_ed_concordance_analysis_20260726'
$Scripts = Join-Path $Phase2 'scripts'
$Logs = Join-Path $Phase2 'qa\run_logs\background_watchdog'
$FinalLogs = Join-Path $Phase2 'qa\run_logs\final_analytical_release'
$PassMarker = Join-Path $FinalLogs `
    'ANALYTICAL_RELEASE_COMPLETE_REPORTS_DEFERRED.log'
$FailMarker = Join-Path $FinalLogs `
    'ANALYTICAL_RELEASE_FAILED_CLOSED.log'
$PostFailMarker = Join-Path $Phase2 (
    'qa\run_logs\post_canonical_supervisor\' +
    'POST_CANONICAL_ANALYSIS_FAILED_CLOSED.log'
)
$WatchdogLog = Join-Path $Logs 'BACKGROUND_WATCHDOG.log'

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Write-WatchdogEvent {
    param([Parameter(Mandatory)][string]$Message)
    "[$(Get-Date -Format o)] $Message" |
        Tee-Object -FilePath $WatchdogLog -Append
}

function Require-Hash {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][string]$ExpectedSha256
    )
    $path = Join-Path $Phase2 $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required frozen file is missing: $path"
    }
    $actual = (
        Get-FileHash -LiteralPath $path -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256) {
        throw (
            "Frozen file hash mismatch: $RelativePath; " +
            "expected=$ExpectedSha256 actual=$actual"
        )
    }
}

function Get-LiveProcess {
    param([int]$ProcessId)
    if ($ProcessId -le 0) {
        return $null
    }
    return Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
}

function Quote-ProcessArgument {
    param([Parameter(Mandatory)][string]$Value)
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Start-HiddenPowerShell {
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string]$ScriptArguments,
        [Parameter(Mandatory)][string]$LogStem,
        [Parameter(Mandatory)][string]$RunDirectory
    )
    $powerShell = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    $argumentLine = (
        '-NoProfile -ExecutionPolicy Bypass -File ' +
        (Quote-ProcessArgument $ScriptPath) + ' ' + $ScriptArguments
    )
    $stdout = Join-Path $RunDirectory "${LogStem}_STDOUT.log"
    $stderr = Join-Path $RunDirectory "${LogStem}_STDERR.log"
    return Start-Process -FilePath $powerShell `
        -ArgumentList $argumentLine `
        -WorkingDirectory $WorkspaceRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
}

function Assert-NoTerminalFailure {
    if (Test-Path -LiteralPath $FailMarker -PathType Leaf) {
        throw "Analytical release is already fail-closed: $FailMarker"
    }
    if (Test-Path -LiteralPath $PostFailMarker -PathType Leaf) {
        throw "Post-canonical analysis is already fail-closed: $PostFailMarker"
    }
}

try {
    Write-WatchdogEvent (
        "START watchdog PID=$PID existing canonical=" +
        "$ExistingCanonicalProcessId post=$ExistingPostCanonicalProcessId " +
        "final=$ExistingFinalSupervisorProcessId"
    )

    if (Test-Path -LiteralPath $PassMarker -PathType Leaf) {
        Write-WatchdogEvent 'PASS marker already exists; nothing to resume.'
        exit 0
    }
    Assert-NoTerminalFailure

    Require-Hash 'scripts\RUN_PHASE2_REMAINING_SAFE.ps1' `
        '0ab4cc471f44d324e28f7cde9d5b30b1b443e84c362ee93d65abd64a9074869e'
    Require-Hash 'scripts\RUN_POST_CANONICAL_ANALYSIS_SAFE.ps1' `
        '15d0fb1af175be9d0b195175cc08b4ad0d8fd7458a26db33dcefce1881c0de7c'
    Require-Hash 'scripts\RUN_FINAL_ANALYTICAL_RELEASE_SAFE.ps1' `
        'fba848b5b381a00282f2ea25bcca45c0ae3456d5ba2ca85895dc88b8a8c065ae'
    Require-Hash 'scripts\08_estimate_primary_models.py' `
        'fe6a21ca466dd58919b9e13e6b3ec511dbaf175fbf54f29d5ae38bbb3e6bc8c9'
    Require-Hash 'qa\pre_estimation_measurement_gate.json' `
        '575095a279b632b407792142b6d92ec596a1d073781a6306479cfc695f22c786'
    Require-Hash 'qa\cohort_validation_report.json' `
        '153197dd95d814b5189706f42e8f85bc5b74991266db81185343508acc688275'
    Require-Hash 'qa\provider_gender_measurement_checkpoint.json' `
        'aa973aabe29f03a0af667e84ed8415ee1be4116a9391956c7567e83145baacdf'
    Require-Hash 'analysis_data\model_matrices\race\matrix_manifest.json' `
        'a2cb7ccbfeb2aa8b86b1c3d3b2160c15ea6a2bb9a2a215638f54e5eb07f0295d'
    Require-Hash 'qa\user_authorized_report_deferral_20260727T083046Z.json' `
        'aa8f3d56a6723da9f46ada5c7e987584e09b2ae2371fe0f39018e2d01422cf28'
    Write-WatchdogEvent 'PASS frozen execution and measurement hashes'

    if ([string]::IsNullOrWhiteSpace($Python)) {
        throw 'The Python path must be supplied explicitly.'
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Python runtime is missing: $Python"
    }

    $currentFinal = Get-LiveProcess $ExistingFinalSupervisorProcessId
    if ($null -ne $currentFinal) {
        Write-WatchdogEvent (
            "WAIT existing final supervisor PID=" +
            "$ExistingFinalSupervisorProcessId"
        )
        Wait-Process -Id $ExistingFinalSupervisorProcessId
        Write-WatchdogEvent (
            "EXIT existing final supervisor PID=" +
            "$ExistingFinalSupervisorProcessId"
        )
    }

    if (Test-Path -LiteralPath $PassMarker -PathType Leaf) {
        Write-WatchdogEvent 'PASS existing chain completed analytical release.'
        exit 0
    }
    Assert-NoTerminalFailure

    # Normalize the inherited environment block. Some Codex shells expose
    # both Path and PATH, which Windows PowerShell 5 Start-Process rejects.
    $processPath = [Environment]::GetEnvironmentVariable('Path', 'Process')
    [Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
    [Environment]::SetEnvironmentVariable('Path', $processPath, 'Process')

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $runDirectory = Join-Path $Logs "recovery_$stamp"
    New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null

    $canonical = Get-LiveProcess $ExistingCanonicalProcessId
    $post = Get-LiveProcess $ExistingPostCanonicalProcessId

    if ($null -eq $canonical -and $null -eq $post) {
        Write-WatchdogEvent 'No protected chain remains; resume canonical.'
        $canonicalArguments = (
            '-WorkspaceRoot ' + (Quote-ProcessArgument $WorkspaceRoot) +
            ' -Python ' + (Quote-ProcessArgument $Python) +
            ' -StartAt common -Threads ' + $Threads +
            ' -MemoryLimit ' + $MemoryLimit
        )
        $canonical = Start-HiddenPowerShell `
            -ScriptPath (Join-Path $Scripts 'RUN_PHASE2_REMAINING_SAFE.ps1') `
            -ScriptArguments $canonicalArguments `
            -LogStem 'CANONICAL' `
            -RunDirectory $runDirectory
        $ExistingCanonicalProcessId = $canonical.Id
        Write-WatchdogEvent "START canonical PID=$($canonical.Id)"
    }

    if ($null -eq $post) {
        if ($null -eq $canonical) {
            throw 'Cannot start post-canonical supervisor without canonical.'
        }
        $postArguments = (
            '-WorkspaceRoot ' + (Quote-ProcessArgument $WorkspaceRoot) +
            ' -Python ' + (Quote-ProcessArgument $Python) +
            ' -CanonicalParentProcessId ' + $canonical.Id +
            ' -Threads ' + $Threads +
            ' -MemoryLimit ' + $MemoryLimit
        )
        $post = Start-HiddenPowerShell `
            -ScriptPath (
                Join-Path $Scripts 'RUN_POST_CANONICAL_ANALYSIS_SAFE.ps1'
            ) `
            -ScriptArguments $postArguments `
            -LogStem 'POST_CANONICAL' `
            -RunDirectory $runDirectory
        Write-WatchdogEvent "START post-canonical PID=$($post.Id)"
    }

    $finalArguments = (
        '-WorkspaceRoot ' + (Quote-ProcessArgument $WorkspaceRoot) +
        ' -Python ' + (Quote-ProcessArgument $Python) +
        ' -PostCanonicalSupervisorProcessId ' + $post.Id +
        ' -HashWorkers ' + $HashWorkers
    )
    $final = Start-HiddenPowerShell `
        -ScriptPath (
            Join-Path $Scripts 'RUN_FINAL_ANALYTICAL_RELEASE_SAFE.ps1'
        ) `
        -ScriptArguments $finalArguments `
        -LogStem 'FINAL_RELEASE' `
        -RunDirectory $runDirectory
    Write-WatchdogEvent "START final supervisor PID=$($final.Id)"
    Wait-Process -Id $final.Id
    Write-WatchdogEvent "EXIT final supervisor PID=$($final.Id)"

    if (Test-Path -LiteralPath $PassMarker -PathType Leaf) {
        Write-WatchdogEvent 'PASS analytical release; reports remain deferred.'
        exit 0
    }
    Assert-NoTerminalFailure
    throw 'Final supervisor exited without a terminal PASS or fail marker.'
}
catch {
    $message = $_.Exception.Message
    Write-WatchdogEvent "FAIL_CLOSED $message"
    $failure = Join-Path $Logs 'BACKGROUND_WATCHDOG_FAILED_CLOSED.log'
    "[$(Get-Date -Format o)] $message" |
        Tee-Object -FilePath $failure
    throw
}
