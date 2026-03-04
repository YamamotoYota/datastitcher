# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

param(
    [string]$PythonExe = "C:\Users\yamam\miniforge3\envs\datastitcher\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python実行ファイルが見つかりません: $PythonExe"
}

& $PythonExe -m pip install --upgrade pyinstaller

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --name DataStitcher `
    --onedir `
    --add-data "app.py;." `
    --add-binary "C:\Users\yamam\miniforge3\envs\datastitcher\Library\bin\ffi-8.dll;." `
    --add-binary "C:\Users\yamam\miniforge3\envs\datastitcher\Library\bin\libexpat.dll;." `
    --collect-all streamlit `
    --collect-submodules src `
    launcher_datastitcher.py

Write-Host "ビルド完了: dist\\DataStitcher\\DataStitcher.exe"
