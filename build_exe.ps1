# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

param(
    [string]$PythonExe = "",
    [string]$CondaEnvName = "datastitcher",
    [switch]$SkipBuildDependencyInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildRequirementsPath = Join-Path $ProjectRoot "requirements-build.txt"
$AppRequirementsPath = Join-Path $ProjectRoot "requirements.txt"
$script:PythonCommand = @()
$script:PythonDescription = ""

function Invoke-ResolvedPython {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    if (-not $script:PythonCommand -or $script:PythonCommand.Count -eq 0) {
        throw "Python command has not been resolved."
    }

    $command = $script:PythonCommand[0]
    $prefixArgs = @()
    if ($script:PythonCommand.Count -gt 1) {
        $prefixArgs = $script:PythonCommand[1..($script:PythonCommand.Count - 1)]
    }

    & $command @prefixArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

function Test-PythonCommand {
    param(
        [string[]]$CommandParts,
        [string]$Description
    )

    if (-not $CommandParts -or $CommandParts.Count -eq 0) {
        return $false
    }

    $command = $CommandParts[0]
    $prefixArgs = @()
    if ($CommandParts.Count -gt 1) {
        $prefixArgs = $CommandParts[1..($CommandParts.Count - 1)]
    }

    $probe = @(
        "import sys"
        "print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
        "print(sys.executable)"
    ) -join "; "

    $output = & $command @prefixArgs -c $probe 2>$null
    if ($LASTEXITCODE -ne 0 -or $null -eq $output -or $output.Count -lt 2) {
        return $false
    }

    try {
        $pythonVersion = [version]("$($output[0]).0")
    }
    catch {
        return $false
    }

    if ($pythonVersion -lt [version]"3.11.0") {
        Write-Host "Skip candidate: $Description (Python $($output[0]) is below 3.11)"
        return $false
    }

    $resolvedExecutable = [string]$output[1]
    $script:PythonCommand = $CommandParts
    $script:PythonDescription = "$Description ($resolvedExecutable)"
    return $true
}

function Resolve-PythonCommand {
    $candidates = New-Object System.Collections.Generic.List[object]

    if ($PythonExe) {
        if (-not (Test-Path $PythonExe)) {
            throw "Python executable was not found: $PythonExe"
        }
        $resolved = (Resolve-Path $PythonExe).Path
        $candidates.Add(@{ Parts = @($resolved); Description = "explicit Python" })
    }

    if ($env:CONDA_PREFIX -and $env:CONDA_DEFAULT_ENV -eq $CondaEnvName) {
        $activeCondaPython = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path $activeCondaPython) {
            $candidates.Add(@{ Parts = @($activeCondaPython); Description = "active conda env '$CondaEnvName'" })
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        $candidates.Add(@{ Parts = @("python"); Description = "python on PATH" })
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        $candidates.Add(@{ Parts = @("py", "-3"); Description = "Python Launcher (py -3)" })
    }

    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($null -ne $conda) {
        $candidates.Add(
            @{
                Parts = @($conda.Source, "run", "--no-capture-output", "-n", $CondaEnvName, "python")
                Description = "conda run -n $CondaEnvName"
            }
        )
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonCommand -CommandParts $candidate.Parts -Description $candidate.Description) {
            return
        }
    }

    throw "Could not resolve a Python 3.11+ interpreter. Use -PythonExe, activate a virtual environment, or make `python`, `py`, or `conda` available."
}

function Assert-AppDependencies {
    $command = @(
        "import importlib.util, sys",
        "modules = ['streamlit', 'pandas', 'openpyxl', 'charset_normalizer']",
        "missing = [name for name in modules if importlib.util.find_spec(name) is None]",
        "print(', '.join(missing))",
        "raise SystemExit(1 if missing else 0)"
    ) -join "; "

    $python = $script:PythonCommand[0]
    $prefixArgs = @()
    if ($script:PythonCommand.Count -gt 1) {
        $prefixArgs = $script:PythonCommand[1..($script:PythonCommand.Count - 1)]
    }

    $missingOutput = & $python @prefixArgs -c $command
    if ($LASTEXITCODE -ne 0) {
        $missingText = (($missingOutput | Where-Object { $_ }) -join ", ").Trim(", ")
        if (-not $missingText) {
            $missingText = "unknown"
        }
        throw "Missing app dependencies: $missingText`nRun `pip install -r $AppRequirementsPath` first."
    }
}

Push-Location $ProjectRoot
try {
    Resolve-PythonCommand
    Write-Host "Using Python: $script:PythonDescription"

    Assert-AppDependencies

    if (-not (Test-Path $BuildRequirementsPath)) {
        throw "Build requirements file was not found: $BuildRequirementsPath"
    }

    if (-not $SkipBuildDependencyInstall) {
        Invoke-ResolvedPython -m pip install -r $BuildRequirementsPath
    }

    Invoke-ResolvedPython -m PyInstaller --noconfirm --clean .\DataStitcher.spec
}
finally {
    Pop-Location
}

Write-Host "Build complete: dist\\DataStitcher\\DataStitcher.exe"
