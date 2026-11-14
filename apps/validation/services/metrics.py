"""Scheduling coverage, utilization, and persisted-row reconciliation metrics."""

from collections import defaultdict

from django.conf import settings
from django.db.models import Count

from apps.core.models import Enrollment, Exam
from apps.scheduling.models import (
    Availability,
    InvigilatorAssignment,
    ScheduleAssignment,
    ScheduleEvent,
    StudentRoomAllocation,
    UnassignedExam,
)
from apps.validation.services.schedule_validator import effective_capacity


def _merge_intervals(intervals):
    merged = []
    for start_at, end_at in sorted(intervals):
        if not merged or start_at > merged[-1][1]:
            merged.append([start_at, end_at])
        else:
            merged[-1][1] = max(merged[-1][1], end_at)
    return merged


def _available_minutes(queryset, resource_field, resource_ids, start_at, end_at):
    if not resource_ids or start_at is None or end_at is None:
        return 0
    by_resource = defaultdict(list)
    for resource_id, window_start, window_end in queryset.filter(
        **{f"{resource_field}__in": resource_ids}
    ).values_list(resource_field, "start_at", "end_at"):
        clipped_start = max(window_start, start_at)
        clipped_end = min(window_end, end_at)
        if clipped_start < clipped_end:
            by_resource[resource_id].append((clipped_start, clipped_end))
    return sum(
        int((right - left).total_seconds() // 60)
        for intervals in by_resource.values()
        for left, right in _merge_intervals(intervals)
    )


def compute_business_metrics(run):
    term = settings.SCHEDULER_POLICY["TERM"]
    assignments = list(
        ScheduleAssignment.objects.filter(
            run=run,
            status=ScheduleAssignment.Status.ASSIGNED,
        ).select_related("exam", "room")
    )
    assignment_exam_ids = {assignment.exam_id for assignment in assignments}
    unassigned_rows = list(
        UnassignedExam.objects.filter(run=run).select_related("exam")
    )
    unassigned_exam_ids = {row.exam_id for row in unassigned_rows}
    event_exam_ids = set(
        ScheduleEvent.objects.filter(run=run, exam__isnull=False)
        .exclude(event_type=ScheduleEvent.EventType.CANCELLED)
        .values_list("exam_id", flat=True)
    )
    represented_exam_ids = (
        assignment_exam_ids | unassigned_exam_ids | event_exam_ids
    )
    scheduled_exam_ids = represented_exam_ids - unassigned_exam_ids
    total_exams = len(represented_exam_ids)

    active_enrollments_by_exam = dict(
        Enrollment.objects.filter(
            term=term,
            status=Enrollment.Status.ACTIVE,
            course__exams__exam_id__in=scheduled_exam_ids,
            course__exams__term=term,
        )
        .values("course__exams__exam_id")
        .annotate(count=Count("enrollment_id"))
        .values_list("course__exams__exam_id", "count")
    )
    allocation_counts = dict(
        StudentRoomAllocation.objects.filter(run=run)
        .values("exam_id")
        .annotate(count=Count("allocation_id"))
        .values_list("exam_id", "count")
    )
    active_enrollment_count = sum(active_enrollments_by_exam.values())
    allocation_count = sum(allocation_counts.values())
    student_allocation_rate = (
        allocation_count / active_enrollment_count
        if active_enrollment_count
        else 0.0
    )

    allocated_seats = sum(assignment.allocated_count for assignment in assignments)
    used_capacity = sum(
        effective_capacity(assignment.room_id, assignment.start_at.date())
        for assignment in assignments
    )
    seat_utilization = (
        allocated_seats / used_capacity if used_capacity else 0.0
    )

    assignment_starts = [assignment.start_at for assignment in assignments]
    assignment_ends = [assignment.end_at for assignment in assignments]
    start_at = min(assignment_starts) if assignment_starts else None
    end_at = max(assignment_ends) if assignment_ends else None
    room_ids = {assignment.room_id for assignment in assignments}
    room_booked_minutes = sum(
        (assignment.end_at - assignment.start_at).total_seconds() / 60
        for assignment in assignments
    )
    room_available_minutes = _available_minutes(
        Availability.objects.filter(room__isnull=False),
        "room_id",
        room_ids,
        start_at,
        end_at,
    )
    room_time_utilization = (
        room_booked_minutes / room_available_minutes
        if room_available_minutes
        else 0.0
    )

    invigilator_assignments = list(
        InvigilatorAssignment.objects.filter(
            assignment__run=run,
            assignment__status=ScheduleAssignment.Status.ASSIGNED,
        ).select_related("assignment")
    )
    invigilator_ids = {
        row.invigilator_id for row in invigilator_assignments
    }
    invigilator_booked_minutes = sum(
        (row.assignment.end_at - row.assignment.start_at).total_seconds()
        / 60
        for row in invigilator_assignments
    )
    invigilator_available_minutes = _available_minutes(
        Availability.objects.filter(invigilator__isnull=False),
        "invigilator_id",
        invigilator_ids,
        start_at,
        end_at,
    )
    invigilator_utilization = (
        invigilator_booked_minutes / invigilator_available_minutes
        if invigilator_available_minutes
        else 0.0
    )

    documented_exceptions = sum(
        bool(row.primary_reason_code and row.evidence)
        for row in unassigned_rows
    )
    exception_documentation_rate = (
        documented_exceptions / len(unassigned_rows)
        if unassigned_rows
        else 1.0
    )

    reconciliation_errors = []
    if len(represented_exam_ids) != (
        len(scheduled_exam_ids) + len(unassigned_exam_ids)
    ):
        reconciliation_errors.append(
            "Run exam count does not equal scheduled plus unassigned."
        )
    if scheduled_exam_ids & unassigned_exam_ids:
        reconciliation_errors.append(
            "An exam is both scheduled and marked unassigned."
        )

    assignment_counts = dict(
        StudentRoomAllocation.objects.filter(run=run)
        .values("assignment_id")
        .annotate(count=Count("allocation_id"))
        .values_list("assignment_id", "count")
    )
    for assignment in assignments:
        actual = assignment_counts.get(assignment.assignment_id, 0)
        if actual != assignment.allocated_count:
            reconciliation_errors.append(
                f"{assignment.assignment_id}: allocated_count="
                f"{assignment.allocated_count}, student allocations={actual}."
            )

    for exam_id in sorted(scheduled_exam_ids):
        expected = active_enrollments_by_exam.get(exam_id, 0)
        actual = allocation_counts.get(exam_id, 0)
        if actual != expected:
            reconciliation_errors.append(
                f"{exam_id}: allocated={actual}, active_enrollments={expected}."
            )
    if set(allocation_counts) - scheduled_exam_ids:
        reconciliation_errors.append(
            "Student allocations exist for exams not scheduled in this run."
        )
    if set(unassigned_exam_ids) & set(allocation_counts):
        reconciliation_errors.append(
            "Unassigned exams have persisted student allocations."
        )

    total_exam_count = Exam.objects.filter(term=term).count()
    return {
        "scheduler_run": run.run_id,
        "term": term,
        "total_exams": total_exams,
        "term_exam_count": total_exam_count,
        "scheduled_exams": len(scheduled_exam_ids),
        "unassigned_exams": len(unassigned_exam_ids),
        "scheduling_coverage": round(
            len(scheduled_exam_ids) / total_exams if total_exams else 0.0,
            4,
        ),
        "student_allocation_rate": round(student_allocation_rate, 4),
        "room_seat_utilization": round(seat_utilization, 4),
        "room_time_utilization": round(room_time_utilization, 4),
        "invigilator_utilization": round(invigilator_utilization, 4),
        "exception_documentation_rate": round(
            exception_documentation_rate, 4
        ),
        "reconciliation_ok": not reconciliation_errors,
        "reconciliation_errors": reconciliation_errors,
    }
