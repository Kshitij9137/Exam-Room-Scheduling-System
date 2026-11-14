"""Schedule exams and persist each run without overwriting prior history."""

import datetime as dt
import logging
from collections import Counter

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.core.models import Exam
from apps.core.services.id_generator import make_assignment_id, make_id
from apps.core.services.lifecycle import transition
from apps.scheduling.models import (
    InvigilatorAssignment,
    ScheduleAssignment,
    ScheduleEvent,
    SchedulerRun,
    StudentRoomAllocation,
    UnassignedExam,
)
from apps.scheduling.services.accommodation import (
    active_accommodations,
    required_minutes,
)
from apps.scheduling.services.context import build_context
from apps.scheduling.services.explanations import (
    explain_unassigned,
    record_event,
)
from apps.scheduling.services.invigilator_allocator import allocate_invigilators
from apps.scheduling.services.room_allocator import allocate_rooms
from apps.scheduling.services.slot_allocator import (
    buffered_overlap,
    color_exams,
)

logger = logging.getLogger(__name__)


def _next_run_id():
    last_id = SchedulerRun.objects.order_by("-run_id").values_list(
        "run_id", flat=True
    ).first()
    number = int(last_id.rsplit("-", 1)[-1]) + 1 if last_id else 1
    return make_id("run", number)


def _reset_exam_statuses(term):
    for exam in Exam.objects.filter(
        term=term,
        status__in=[
            Exam.Status.SCHEDULED,
            Exam.Status.UNASSIGNED,
            Exam.Status.NOT_REQUIRED,
        ],
    ).order_by("exam_id"):
        transition(exam, Exam.Status.PLANNED)


def _students_for_exam(context, exam, on_date=None):
    periods = getattr(context, "enrollment_periods_by_exam", {}).get(
        exam.exam_id
    )
    if periods is None:
        student_ids = context.students_by_exam.get(exam.exam_id, set())
    else:
        student_ids = {
            student_id
            for student_id, effective_from, effective_to in periods
            if on_date is None
            or (
                effective_from <= on_date
                and (effective_to is None or effective_to >= on_date)
            )
        }
    return [
        context.students[student_id]
        for student_id in sorted(student_ids)
        if student_id in context.students
    ]


def _student_interval_conflict(context, students, start_at, end_at):
    for student, _accommodations in students:
        if any(
            buffered_overlap(
                start_at,
                end_at,
                booked_start,
                booked_end,
                context.policy.get("HARD_BUFFER_MINUTES", 0),
            )
            for booked_start, booked_end in context.student_intervals.get(
                student.student_id, ()
            )
        ):
            return True
    return False


def _candidate_intervals(context, exam, students):
    """Yield fixed-calendar slots with accommodation-aware durations."""
    operating_start = context.policy.get("OPERATING_START", "08:00")
    operating_end = context.policy.get("OPERATING_END", "20:00")
    earliest = dt.time.fromisoformat(operating_start)
    latest = dt.time.fromisoformat(operating_end)
    any_slot = False
    color = context.time_groups.get(exam.exam_id)
    preferred_slot = (
        context.slots[color]
        if color is not None and color < len(context.slots)
        else None
    )
    slots = (
        ([preferred_slot] if preferred_slot else [])
        + [
            slot
            for slot in context.slots
            if slot is not preferred_slot
        ]
    )
    for slot in slots:
        if slot.start_time < earliest or slot.start_time >= latest:
            continue
        active_students = _students_for_exam(context, exam, slot.slot_date)
        if not active_students:
            continue
        start_at = dt.datetime.combine(
            slot.slot_date, slot.start_time, tzinfo=dt.timezone.utc
        )
        student_accommodations = [
            (
                student,
                active_accommodations(
                    context.accommodations.get(student.student_id, ()),
                    slot.slot_date,
                ),
            )
            for student in active_students
        ]
        duration = max(
            (
                required_minutes(exam.duration_minutes, accommodations)
                for _, accommodations in student_accommodations
            ),
            default=exam.duration_minutes,
        )
        end_at = start_at + dt.timedelta(minutes=duration)
        if end_at.date() != slot.slot_date or end_at.time() > latest:
            continue
        if start_at.time() < earliest:
            continue
        any_slot = True
        yield slot, start_at, end_at, student_accommodations

    if not any_slot:
        return


def _commit_assignment(
    context,
    exam,
    room_allocations,
    invigilator_allocations,
    students_with_accommodations,
    start_at,
    end_at,
):
    created_assignments = []
    students_by_id = {
        student.student_id: accommodations
        for student, accommodations in students_with_accommodations
    }

    for room, students in room_allocations:
        assignment = ScheduleAssignment.objects.create(
            assignment_id=make_assignment_id(
                exam.exam_id, room.room_id, context.run.run_id
            ),
            run=context.run,
            exam=exam,
            room=room,
            start_at=start_at,
            end_at=end_at,
            allocated_count=len(students),
        )
        created_assignments.append(assignment)

        StudentRoomAllocation.objects.bulk_create(
            [
                StudentRoomAllocation(
                    allocation_id=context.next_sra(),
                    assignment=assignment,
                    run=context.run,
                    exam=exam,
                    student=student,
                    required_minutes=required_minutes(
                        exam.duration_minutes,
                        students_by_id[student.student_id],
                    ),
                )
                for student in students
            ],
            batch_size=1000,
        )

        invigilators = next(
            (
                assigned
                for assigned_room, assigned in invigilator_allocations
                if assigned_room.room_id == room.room_id
            ),
            [],
        )
        InvigilatorAssignment.objects.bulk_create(
            [
                InvigilatorAssignment(
                    ias_id=context.next_ias(),
                    assignment=assignment,
                    invigilator=invigilator,
                    role=(
                        InvigilatorAssignment.Role.CHIEF
                        if index == 0
                        else InvigilatorAssignment.Role.ASSISTANT
                    ),
                )
                for index, invigilator in enumerate(invigilators)
            ],
            batch_size=1000,
        )

    transition(exam, Exam.Status.SCHEDULED)
    record_event(
        context,
        exam,
        ScheduleEvent.EventType.ASSIGNED,
        {
            "assignment_ids": [
                assignment.assignment_id for assignment in created_assignments
            ],
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "allocated_count": sum(
                len(students) for _, students in room_allocations
            ),
            "room_count": len(room_allocations),
        },
        assignment=created_assignments[0] if len(created_assignments) == 1 else None,
    )

    # Update feasibility state only after the database writes have succeeded.
    for room, students in room_allocations:
        context.room_bookings[room.room_id].append((start_at, end_at))
        invigilators = next(
            assigned
            for assigned_room, assigned in invigilator_allocations
            if assigned_room.room_id == room.room_id
        )
        for invigilator in invigilators:
            invigilator_id = invigilator.invigilator_id
            context.invigilator_bookings[invigilator_id].append(
                (start_at, end_at)
            )
            workload = getattr(context, "invigilator_workload_minutes", None)
            if workload is None:
                context.invigilator_workload_minutes = workload = Counter()
            workload[invigilator_id] += int(
                (end_at - start_at).total_seconds() // 60
            )
        for student in students:
            context.student_intervals[student.student_id].append(
                (start_at, end_at)
            )

    context.exam_slots[exam.exam_id] = (start_at, end_at)
    return created_assignments


def _record_unassigned(context, exam, reasons, evidence=None):
    if reasons:
        primary_reason, _count = min(
            reasons.items(), key=lambda item: (-item[1], item[0])
        )
    else:
        primary_reason = UnassignedExam.Reason.NO_FEASIBLE_ASSIGNMENT

    valid_reasons = {choice.value for choice in UnassignedExam.Reason}
    if primary_reason not in valid_reasons:
        primary_reason = UnassignedExam.Reason.NO_FEASIBLE_ASSIGNMENT

    detail = {
        "reasons": dict(sorted(reasons.items())),
        "rejection_evidence": evidence or {},
    }
    UnassignedExam.objects.create(
        unassigned_id=context.next_una(),
        run=context.run,
        exam=exam,
        primary_reason_code=primary_reason,
        evidence=explain_unassigned(exam.exam_id, primary_reason, detail),
    )
    transition(exam, Exam.Status.UNASSIGNED)
    record_event(
        context,
        exam,
        ScheduleEvent.EventType.UNASSIGNED,
        {
            "primary_reason": primary_reason,
            **detail,
        },
    )
    return primary_reason


def try_schedule_exam(context, exam):
    """Try every configured slot, returning ``(scheduled, rejection_counts)``."""
    students = _students_for_exam(context, exam)
    if not students:
        transition(exam, Exam.Status.NOT_REQUIRED)
        record_event(
            context,
            exam,
            ScheduleEvent.EventType.NOT_REQUIRED,
            {"reason": "no_active_enrollments", "allocated_count": 0},
        )
        return True, Counter()

    reasons = Counter()
    evidence = {
        "student_count": len(students),
        "slots_considered": 0,
        "rooms": {},
    }
    for _slot, start_at, end_at, students_with_accommodations in (
        _candidate_intervals(context, exam, students)
    ):
        evidence["slots_considered"] += 1
        if _student_interval_conflict(
            context, students_with_accommodations, start_at, end_at
        ):
            reasons[UnassignedExam.Reason.NO_CONFLICT_FREE_SLOT.value] += 1
            continue

        room_allocations, room_reason = allocate_rooms(
            context,
            exam,
            students_with_accommodations,
            start_at,
            end_at,
        )
        if room_allocations is None:
            reasons[room_reason.value] += 1
            evidence["rooms"][room_reason.value] = (
                context.last_room_evidence
            )
            continue

        invigilator_allocations, staffing_reason = allocate_invigilators(
            context, exam, room_allocations, start_at, end_at
        )
        if invigilator_allocations is None:
            reasons[staffing_reason.value] += 1
            continue

        _commit_assignment(
            context,
            exam,
            room_allocations,
            invigilator_allocations,
            students_with_accommodations,
            start_at,
            end_at,
        )
        return True, reasons

    if evidence["slots_considered"] == 0:
        reasons[UnassignedExam.Reason.NO_FEASIBLE_ASSIGNMENT.value] += 1
        evidence["detail"] = (
            "No exam-calendar slot can contain the required duration "
            "within the configured operating hours."
        )
    _record_unassigned(context, exam, reasons, evidence)
    return False, reasons


@transaction.atomic
def run_scheduler(seed=None, run_type=SchedulerRun.RunType.BASELINE, reset_exams=True):
    """Run the deterministic scheduler and append a new run to history."""
    valid_run_types = {choice.value for choice in SchedulerRun.RunType}
    if run_type not in valid_run_types:
        raise ValueError(f"Unknown run type {run_type!r}.")

    policy = settings.SCHEDULER_POLICY
    term = policy["TERM"]
    if reset_exams:
        _reset_exam_statuses(term)

    run = SchedulerRun.objects.create(
        run_id=_next_run_id(),
        run_type=run_type,
        seed=seed,
        algorithm_version="phase-4-dsatur-1",
        notes=f"term={term}",
    )
    context = build_context(run, term, policy)
    ordered_exams, context.time_groups = color_exams(
        context.graph, context.students_by_exam, context
    )

    scheduled_count = 0
    exams_with_assignments = 0
    not_required_count = 0
    unassigned_count = 0
    failures = []

    for exam in ordered_exams:
        if exam.status != Exam.Status.PLANNED:
            continue
        savepoint_id = transaction.savepoint()
        try:
            scheduled, _reasons = try_schedule_exam(context, exam)
            transaction.savepoint_commit(savepoint_id)
            if exam.status == Exam.Status.NOT_REQUIRED:
                not_required_count += 1
            elif exam.status == Exam.Status.SCHEDULED:
                scheduled_count += 1
                if context.exam_slots.get(exam.exam_id):
                    exams_with_assignments += 1
            else:
                unassigned_count += 1
        except (DatabaseError, ValidationError, ValueError):
            transaction.savepoint_rollback(savepoint_id)
            logger.exception(
                "Could not persist a valid schedule for exam %s.", exam.exam_id
            )
            exam.refresh_from_db()
            failure_evidence = {
                "error": "Schedule persistence failed for this exam.",
            }
            failure_savepoint = transaction.savepoint()
            _record_unassigned(
                context,
                exam,
                Counter(
                    {
                        UnassignedExam.Reason.NO_FEASIBLE_ASSIGNMENT.value: 1
                    }
                ),
                failure_evidence,
            )
            transaction.savepoint_commit(failure_savepoint)
            unassigned_count += 1
            failures.append(exam.exam_id)

    final_status = (
        SchedulerRun.Status.FAILED
        if failures
        else SchedulerRun.Status.COMPLETED
    )
    transition(run, final_status)
    run.finished_at = timezone.now()
    run.notes = (
        f"term={term}; scheduled={scheduled_count}; "
        f"not_required={not_required_count}; "
        f"scheduled_with_assignments={exams_with_assignments}; "
        f"unassigned={unassigned_count}; failed_exam_persistence={len(failures)}"
    )
    run.save(update_fields=["finished_at", "notes"])
    return run
