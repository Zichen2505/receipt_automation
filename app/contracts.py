"""Shared failure contract; all data structures live in schemas.receipt."""


class FeatureNotImplementedError(NotImplementedError):
    """Phase 1 boundary: implementation must not simulate success."""


class ReceiptStorageError(RuntimeError):
    """A local storage operation failed; no durable success may be claimed."""
