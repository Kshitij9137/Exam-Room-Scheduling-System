"""Allocate available invigilators without overlaps or daily-hour violations."""

import math

from apps.scheduling.models import UnassignedExam
from apps.scheduling.services.slot_allocator import buffered_overlap


def _available(invigilator, start_at, end_at, context):
    return any(
        window_start <= start_at and window_end >= end_at
        for window_start, window_end in context.invigilator_avails.get(
            invigilator.invigilator_id, ()
        )
    )


def _free(invigilator, start_at, end_at, context):
    return not any(
        buffered_overlap(
            start_at,
            end_at,
            booked_start,
            booked_end,
            context.policy.get("HARD_BUFFER_MINUTES", 0),
        )
        for booked_start, booked_end in context.invigilator_bookings.get(
            invigilator.invigilator_id, ()
        )
    )


def _within_daily_limit(invigilator, start_at, end_at, context):
    assigned_minutes = sum(
        (booked_end - booked_start).total_seconds() / 60
        for booked_start, booked_end in context.invigilator_bookings.get(
            invigilator.invigilator_id, ()
        )
        if booked_start.date() == start_at.date()
    )
    required_minutes = (end_at - start_at).total_seconds() / 60
    return (
        assigned_minutes + required_minutes
        <= float(invigilator.max_daily_hours) * 60
    )


def _within_consecutive_limit(invigilator, start_at, end_at, context):
    limit_hours = context.policy.get("MAX_CONSECUTIVE_INVIGILATOR_HOURS")
    if limit_hours is None:
        return True

    intervals = sorted(
        [
            *context.invigilator_bookings.get(
                invigilator.invigilator_id, ()
            ),
            (start_at, end_at),
        ]
    )
    chain_start, chain_end = intervals[0]
    limit_minutes = float(limit_hours) * 60
    for next_start, next_end in intervals[1:]:
        if next_start > chain_end:
            chain_start, chain_end = next_start, next_end
        else:
            chain_end = max(chain_end, next_end)
        if (chain_end - chain_start).total_seconds() / 60 > limit_minutes:
            return False
    return (chain_end - chain_start).total_seconds() / 60 <= limit_minutes


def allocate_invigilators(context, exam, room_allocations, start_at, end_at):
    """Return per-room staff assignments or a ``NO_INVIGILATOR`` reason."""
    requirement = context.exam_requirements.get(exam.exam_id)
    ratio = requirement.invigilator_ratio if requirement else 50
    used_ids = set()
    result = []

    workloads = getattr(context, "invigilator_workload_minutes", {})
    for room, students in room_allocations:
        needed = max(1, math.ceil(len(students) / ratio))
        eligible = [
            invigilator
            for invigilator in context.invigilators
            if invigilator.invigilator_id not in used_ids
            and _available(invigilator, start_at, end_at, context)
            and _free(invigilator, start_at, end_at, context)
            and _within_daily_limit(
                invigilator, start_at, end_at, context
            )
            and _within_consecutive_limit(
                invigilator, start_at, end_at, context
            )
        ]
        eligible.sort(
            key=lambda invigilator: (
                workloads.get(invigilator.invigilator_id, 0),
                invigilator.invigilator_id,
            )
        )
        selected = eligible[:needed]
        if len(selected) != needed:
            return None, UnassignedExam.Reason.NO_INVIGILATOR
        used_ids.update(inv.invigilator_id for inv in selected)
        result.append((room, selected))

    return result, None
