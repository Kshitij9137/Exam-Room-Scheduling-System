"""Persist explainable schedule and unassignment events."""

from apps.scheduling.models import ScheduleEvent


def record_event(context, exam, event_type, detail, assignment=None):
    return ScheduleEvent.objects.create(
        event_id=context.next_evt(),
        run=context.run,
        exam=exam,
        assignment=assignment,
        event_type=event_type,
        detail=detail or {},
    )


def explain_unassigned(exam_id, reason, evidence):
    return {
        "exam_id": exam_id,
        "primary_reason": reason,
        "evidence": evidence,
    }
