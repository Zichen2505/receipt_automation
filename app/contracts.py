"""Shared failure contract; all data structures live in schemas.receipt."""


class FeatureNotImplementedError(NotImplementedError):
    """Phase 1 boundary: implementation must not simulate success."""


class ReceiptStorageError(RuntimeError):
    """A local storage operation failed; no durable success may be claimed."""


class ExtractionConflictError(RuntimeError):
    """An integration reused a request ID with different PDF bytes."""


class ExtractionCapacityError(RuntimeError):
    """The bounded unfinished-job capacity is exhausted."""


class ExtractionExecutionError(RuntimeError):
    """Sanitized failure carrying internal extraction evidence, never an HTTP body."""

    def __init__(self, metadata):
        super().__init__("Structured extraction failed")
        self.metadata = metadata
