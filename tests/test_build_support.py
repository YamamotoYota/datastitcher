# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Tests for PyInstaller build helpers."""

from __future__ import annotations

from pathlib import Path

from src.build_support import collect_runtime_binaries, resolve_env_prefix


def test_resolve_env_prefix_from_windows_scripts_python_path(tmp_path: Path) -> None:
    env_prefix = tmp_path / "datastitcher"
    python_exe = env_prefix / "Scripts" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_text("", encoding="utf-8")

    assert resolve_env_prefix(python_exe) == env_prefix


def test_collect_runtime_binaries_finds_conda_library_bin_dlls(tmp_path: Path) -> None:
    env_prefix = tmp_path / "datastitcher"
    library_bin = env_prefix / "Library" / "bin"
    library_bin.mkdir(parents=True)

    ffi_dll = library_bin / "ffi-8.dll"
    expat_dll = library_bin / "libexpat.dll"
    ffi_dll.write_text("", encoding="utf-8")
    expat_dll.write_text("", encoding="utf-8")

    binaries = collect_runtime_binaries(env_prefix)

    assert (str(ffi_dll), ".") in binaries
    assert (str(expat_dll), ".") in binaries


def test_collect_runtime_binaries_accepts_libffi_alias(tmp_path: Path) -> None:
    env_prefix = tmp_path / "datastitcher"
    dlls_dir = env_prefix / "DLLs"
    dlls_dir.mkdir(parents=True)

    ffi_dll = dlls_dir / "libffi-8.dll"
    ffi_dll.write_text("", encoding="utf-8")

    binaries = collect_runtime_binaries(env_prefix)

    assert (str(ffi_dll), ".") in binaries
