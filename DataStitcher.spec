# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota
# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import collect_submodules

SPEC_ROOT = Path(SPECPATH).resolve()
if str(SPEC_ROOT) not in sys.path:
    sys.path.insert(0, str(SPEC_ROOT))

from src.build_support import collect_runtime_binaries, project_file

datas = [(str(project_file("app.py")), ".")]
binaries = collect_runtime_binaries()
hiddenimports = collect_submodules("src")
tmp_ret = collect_all("streamlit")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]


a = Analysis(
    [str(project_file("launcher_datastitcher.py"))],
    pathex=[str(SPEC_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DataStitcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DataStitcher',
)
