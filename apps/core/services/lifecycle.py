"""Lifecycle (state machine) rules. Invalid transitions raise InvalidTransition."""


class InvalidTransition(ValueError):
    pass


ALLOWED_TRANSITIONS = {
    "Exam": {
        "DRAFT": {"PLANNED"},
        "PLANNED": {"SCHEDULED", "UNASSIGNED", "NOT_REQUIRED"},
        "SCHEDULED": {"PLANNED"},      # reset when the scheduler is re-run
        "UNASSIGNED": {"PLANNED"},     # reset when the scheduler is re-run
        "NOT_REQUIRED": {"PLANNED"},   # reset when the scheduler is re-run
    },
    "Enrollment": {
        "ACTIVE": {"DROPPED", "WITHDRAWN", "COMPLETED"},
        "DROPPED": set(),
        "WITHDRAWN": set(),
        "COMPLETED": set(),
    },
    "Student": {
        "ACTIVE": {"INACTIVE", "GRADUATED"},
        "INACTIVE": {"ACTIVE"},
        "GRADUATED": set(),
    },
    "Accommodation": {"ACTIVE": {"REVOKED"}, "REVOKED": set()},
    "ScheduleAssignment": {
        "ASSIGNED": {"SUPERSEDED", "CANCELLED"},
        "SUPERSEDED": set(),
        "CANCELLED": set(),
    },
    "SchedulerRun": {"RUNNING": {"COMPLETED", "FAILED"}, "COMPLETED": set(), "FAILED": set()},
    "ValidationRun": {
        "RUNNING": {"PASSED", "FAILED_CHECKS", "ERROR"},
        "PASSED": set(),
        "FAILED_CHECKS": set(),
        "ERROR": set(),
    },
}


def can_transition(model_name: str, old: str, new: str) -> bool:
    return new in ALLOWED_TRANSITIONS.get(model_name, {}).get(old, set())


def transition(obj, new_status: str, field: str = "status"):
    """Move obj to new_status if the lifecycle allows it, then save only that field."""
    model_name = obj.__class__.__name__
    old = getattr(obj, field)
    if not can_transition(model_name, old, new_status):
        raise InvalidTransition(f"{model_name}: {old} -> {new_status} is not allowed")
    setattr(obj, field, new_status)
    obj.save(update_fields=[field])
    return obj
