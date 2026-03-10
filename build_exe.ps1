# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

param(
    [string]$PythonExe = "",
    [string]$CondaEnvName = "datastitcher"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:ResolvedPythonExe = $null
$script:UseCondaRun = $false
$script:CondaCommand = $null

function Resolve-PythonCommand {
    if ($PythonExe) {
        if (-not (Test-Path $PythonExe)) {
            throw "Python実行ファイルが見つかりません: $PythonExe"
        }
        $script:ResolvedPythonExe = (Resolve-Path $PythonExe).Path
        return
    }

    if ($env:CONDA_PREFIX -and $env:CONDA_DEFAULT_ENV -eq $CondaEnvName) {
        $candidate = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path $candidate) {
            $script:ResolvedPythonExe = (Resolve-Path $candidate).Path
            return
        }
    }

    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($null -ne $conda) {
        $script:UseCondaRun = $true
        $script:CondaCommand = $conda.Source
        return
    }

    throw "Miniforge の conda 環境 '$CondaEnvName' を特定できません。`conda activate $CondaEnvName` を実行するか、-PythonExe で python.exe を指定してください。"
}

function Invoke-EnvPython {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    if ($script:UseCondaRun) {
        & $script:CondaCommand run --no-capture-output -n $CondaEnvName python @Arguments
    }
    else {
        & $script:ResolvedPythonExe @Arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Python コマンドが失敗しました: $($Arguments -join ' ')"
    }
}

Push-Location $ProjectRoot
try {
    Resolve-PythonCommand

    if ($script:UseCondaRun) {
        Write-Host "使用環境: conda run -n $CondaEnvName"
    }
    else {
        Write-Host "使用 Python: $script:ResolvedPythonExe"
    }

    Invoke-EnvPython -m pip install --upgrade pyinstaller
    Invoke-EnvPython -m PyInstaller --noconfirm --clean .\DataStitcher.spec
}
finally {
    Pop-Location
}

Write-Host "ビルド完了: dist\\DataStitcher\\DataStitcher.exe"
