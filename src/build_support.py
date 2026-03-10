# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Helpers for PyInstaller build configuration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_BINARY_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("ffi-8.dll", "libffi-8.dll", "ffi-7.dll", "libffi-7.dll"),
    ("libexpat.dll", "expat.dll"),
)


def project_root() -> Path:
    """Return the repository root."""
    return PROJECT_ROOT


def project_file(*parts: str) -> Path:
    """Resolve a file path relative to the repository root."""
    return PROJECT_ROOT.joinpath(*parts)


def resolve_env_prefix(python_executable: str | Path | None = None) -> Path:
    """Resolve the environment prefix from a Python executable path."""
    executable = Path(python_executable or sys.executable).resolve()
    if executable.is_dir():
        return executable
    if executable.parent.name.lower() == "scripts":
        return executable.parent.parent
    return executable.parent


def iter_runtime_search_dirs(env_prefix: str | Path | None = None) -> tuple[Path, ...]:
    """Return candidate directories that may contain runtime DLLs."""
    prefix = resolve_env_prefix(env_prefix)
    directories = (
        prefix / "Library" / "bin",
        prefix / "DLLs",
        prefix,
        prefix / "bin",
    )
    unique_directories: list[Path] = []
    for directory in directories:
        if directory not in unique_directories:
            unique_directories.append(directory)
    return tuple(unique_directories)


def _find_first_existing_file(search_dirs: Iterable[Path], names: Iterable[str]) -> Path | None:
    """Return the first matching file from the given directories."""
    for search_dir in search_dirs:
        for name in names:
            candidate = search_dir / name
            if candidate.exists():
                return candidate
    return None


def collect_runtime_binaries(env_prefix: str | Path | None = None) -> list[tuple[str, str]]:
    """Collect runtime DLLs that should be bundled by PyInstaller."""
    search_dirs = iter_runtime_search_dirs(env_prefix)
    binaries: list[tuple[str, str]] = []
    for candidates in RUNTIME_BINARY_CANDIDATES:
        matched = _find_first_existing_file(search_dirs, candidates)
        if matched is not None:
            binaries.append((str(matched), "."))
    return binaries
