"""Domain exceptions. Handlers translate them into user-facing text."""


class DomainError(Exception):
    """Base class for every expected domain failure."""


class ValidationError(DomainError):
    """Input violates a domain rule."""


class NotFoundError(DomainError):
    """Entity does not exist or does not belong to the requester."""


class PermissionDeniedError(DomainError):
    """Requester may not act on this entity."""


class ContractViolation(DomainError):
    """Outgoing payload breaks a contract the fakes enforce."""


class ScheduleExhaustedError(DomainError):
    """Schedule produces no further occurrences."""


class CategoryInUseError(DomainError):
    """Category still has active reminders."""


class CategoryExistsError(DomainError):
    """Owner already has an active category under this title."""
