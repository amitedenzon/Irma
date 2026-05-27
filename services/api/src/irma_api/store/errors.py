"""Typed store-layer exceptions. Routers translate to HTTPException."""

from __future__ import annotations


class StoreError(RuntimeError):
    """Base class for all store-layer failures."""


class NotFoundError(StoreError):
    """Raised when a lookup by id returns no row."""

    def __init__(self, entity: str, key: str) -> None:
        super().__init__(f"{entity} not found: {key!r}")
        self.entity = entity
        self.key = key


class ConflictError(StoreError):
    """Raised on uniqueness, FK, or business-rule violations."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
