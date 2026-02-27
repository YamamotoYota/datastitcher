# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Custom exceptions for user-facing validation."""


class DataStitcherError(Exception):
    """Base exception for predictable application errors."""


class UserInputError(DataStitcherError):
    """Raised when the current configuration is invalid."""


class FileReadError(DataStitcherError):
    """Raised when a file cannot be read using the current options."""

