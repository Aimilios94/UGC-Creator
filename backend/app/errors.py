"""Domain errors shared by services, the worker and the API."""

from __future__ import annotations


class BudgetExceeded(Exception):
    """A paid stage would pass the per-job cost cap or the global daily spend limit.

    Terminal for the job: retrying cannot help until the limit changes or the day ends.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason  # "job_cap" | "daily_limit"
        self.message = message


class UploadRejected(ValueError):
    """The uploaded file failed the type, size or image checks."""


class ProviderNotConfigured(RuntimeError):
    """A real provider was requested but its key or setting is missing."""
