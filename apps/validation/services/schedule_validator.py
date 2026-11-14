"""Independent validation of persisted schedule assignments."""

from collections import defaultdict

from django.db.models import Count, Q

from apps.core.models import (
    Accommodation,
    Enrollment,
    ExamRequirement,
    ExamRequirementEquipment,
    RoomCapacity,
)
from apps.scheduling.models import (
    Availability,
    InvigilatorAssignment,
    RoomClosure,
    ScheduleAssignment,
    StudentRoomAllocation,
)
from apps.validation.models import DetectedViolation

CODE = DetectedViolation.Code


def _overlap(first_start, first_end, second_start, second_end):
    return first_start < second_end and second_start < first_end


def effective_capacity(room_id, on_date):
    capacity = (
        RoomCapacity.objects.filter(
            room_id=room_id,
            effective_from__lte=on_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .order_by("-effective_from")
        .first()
    )
    return capacity.exam_capacity if capacity else 0


def _assignments(run):
    return ScheduleAssignment.objects.filter(
        run=run,
        status=ScheduleAssignment.Status.ASSIGNED,
    )


def check_student_overlap(run):
    allocations = list(
        StudentRoomAllocation.objects.filter(run=run)
        .select_related("assignment", "exam")
        .order_by("student_id", "assignment_id")
    )
    by_student = defaultdict(list)
    for allocation in allocations:
        by_student[allocation.student_id].append(allocation)

    violations = []
    for student_id, items in by_student.items():
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                if first.exam_id == second.exam_id:
                    continue
                if not _overlap(
                    first.assignment.start_at,
                    first.assignment.end_at,
                    second.assignment.start_at,
                    second.assignment.end_at,
                ):
                    continue
                for assignment, other in (
                    (first.assignment, second.assignment),
                    (second.assignment, first.assignment),
                ):
                    violations.append(
                        {
                            "code": CODE.STUDENT_DOUBLE_BOOKING,
                            "assignment": assignment,
                            "entity_id": student_id,
                            "detail": f"Student overlaps {other.assignment_id}.",
                        }
                    )
    return violations, len(allocations)


def check_room_capacity(run):
    assignments = list(_assignments(run).select_related("room"))
    violations = []
    for assignment in assignments:
        capacity = effective_capacity(
            assignment.room_id, assignment.start_at.date()
        )
        if assignment.allocated_count > capacity:
            violations.append(
                {
                    "code": CODE.ROOM_CAPACITY_EXCEEDED,
                    "assignment": assignment,
                    "entity_id": assignment.room_id,
                    "detail": (
                        f"Allocated {assignment.allocated_count}; "
                        f"effective capacity {capacity}."
                    ),
                }
            )
    return violations, len(assignments)


def check_missing_equipment(run):
    assignments = list(
        _assignments(run).select_related("room", "exam")
    )
    requirements = defaultdict(set)
    requirement_by_exam = dict(
        ExamRequirement.objects.filter(
            exam_id__in={assignment.exam_id for assignment in assignments}
        ).values_list("exam_id", "requirement_id")
    )
    for requirement_id, equipment_id in (
        ExamRequirementEquipment.objects.filter(
            requirement__exam_id__in={a.exam_id for a in assignments}
        ).values_list("requirement_id", "equipment_id")
    ):
        requirements[requirement_id].add(equipment_id)
    violations = []
    for assignment in assignments:
        requirement_id = requirement_by_exam.get(assignment.exam_id)
        needed = requirements.get(requirement_id, set())
        if not needed:
            continue
        available = set(
            assignment.room.equipment.values_list("code", flat=True)
        )
        missing = needed - available
        if missing:
            violations.append(
                {
                    "code": CODE.MISSING_EQUIPMENT,
                    "assignment": assignment,
                    "entity_id": assignment.room_id,
                    "detail": f"Missing equipment: {sorted(missing)}.",
                }
            )
    return violations, len(assignments)


def check_room_double_booking(run):
    assignments = list(_assignments(run).order_by("room_id", "start_at"))
    by_room = defaultdict(list)
    for assignment in assignments:
        by_room[assignment.room_id].append(assignment)

    violations = []
    for room_id, items in by_room.items():
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                if second.start_at >= first.end_at:
                    break
                if not _overlap(
                    first.start_at,
                    first.end_at,
                    second.start_at,
                    second.end_at,
                ):
                    continue
                for assignment, other in (
                    (first, second),
                    (second, first),
                ):
                    violations.append(
                        {
                            "code": CODE.ROOM_DOUBLE_BOOKED,
                            "assignment": assignment,
                            "entity_id": room_id,
                            "detail": f"Overlaps {other.assignment_id}.",
                        }
                    )
    return violations, len(assignments)


def check_invigilator_double_booking(run):
    assignments = list(
        InvigilatorAssignment.objects.filter(
            assignment__run=run,
            assignment__status=ScheduleAssignment.Status.ASSIGNED,
        )
        .select_related("assignment")
        .order_by("invigilator_id", "assignment__start_at")
    )
    by_invigilator = defaultdict(list)
    for assignment in assignments:
        by_invigilator[assignment.invigilator_id].append(
            assignment.assignment
        )

    violations = []
    for invigilator_id, items in by_invigilator.items():
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                if second.start_at >= first.end_at:
                    break
                if first.exam_id == second.exam_id:
                    continue
                if not _overlap(
                    first.start_at,
                    first.end_at,
                    second.start_at,
                    second.end_at,
                ):
                    continue
                for assignment in (first, second):
                    violations.append(
                        {
                            "code": CODE.INVIGILATOR_DOUBLE_BOOKED,
                            "assignment": assignment,
                            "entity_id": invigilator_id,
                            "detail": "Invigilator is assigned to overlapping exams.",
                        }
                    )
    return violations, len(assignments)


def check_invigilator_availability(run):
    assignments = list(
        InvigilatorAssignment.objects.filter(
            assignment__run=run,
            assignment__status=ScheduleAssignment.Status.ASSIGNED,
        ).select_related("assignment")
    )
    violations = []
    for inv_assignment in assignments:
        assignment = inv_assignment.assignment
        available = Availability.objects.filter(
            invigilator_id=inv_assignment.invigilator_id,
            start_at__lte=assignment.start_at,
            end_at__gte=assignment.end_at,
        ).exists()
        if not available:
            violations.append(
                {
                    "code": CODE.INVIGILATOR_UNAVAILABLE,
                    "assignment": assignment,
                    "entity_id": inv_assignment.invigilator_id,
                    "detail": "Invigilator is unavailable for the full interval.",
                }
            )
    return violations, len(assignments)


def check_accommodation(run):
    allocations = list(
        StudentRoomAllocation.objects.filter(run=run)
        .select_related("assignment__room", "exam")
        .order_by("assignment_id", "student_id")
    )
    by_assignment = defaultdict(list)
    for allocation in allocations:
        by_assignment[allocation.assignment_id].append(allocation)
    student_ids = {allocation.student_id for allocation in allocations}
    accommodation_by_student = defaultdict(list)
    for accommodation in Accommodation.objects.filter(
        student_id__in=student_ids,
        status=Accommodation.Status.ACTIVE,
    ).order_by("accommodation_id"):
        accommodation_by_student[accommodation.student_id].append(
            accommodation
        )

    violations = []
    for items in by_assignment.values():
        assignment = items[0].assignment
        on_date = assignment.start_at.date()
        minutes = (assignment.end_at - assignment.start_at).total_seconds() / 60
        accommodations = {
            item.student_id: [
                accommodation
                for accommodation in accommodation_by_student[item.student_id]
                if accommodation.effective_from <= on_date
                and (
                    accommodation.effective_to is None
                    or accommodation.effective_to >= on_date
                )
            ]
            for item in items
        }
        separate_students = {
            student_id
            for student_id, student_accommodations in accommodations.items()
            if any(
                item.accommodation_type == Accommodation.Type.SEPARATE_ROOM
                for item in student_accommodations
            )
        }
        reported = False
        for item in items:
            student_accommodations = accommodations[item.student_id]
            extra_percent = max(
                (
                    acc.extra_time_percent
                    for acc in student_accommodations
                    if acc.accommodation_type == Accommodation.Type.EXTRA_TIME
                ),
                default=0,
            )
            required_minutes = (
                item.exam.duration_minutes * (100 + extra_percent) + 99
            ) // 100
            separate_required = item.student_id in separate_students
            accessible_required = any(
                acc.accommodation_type == Accommodation.Type.ACCESSIBLE_ROOM
                for acc in student_accommodations
            )
            reasons = []
            if minutes < required_minutes:
                reasons.append(
                    f"requires {required_minutes} minutes, got {int(minutes)}"
                )
            if accessible_required and not assignment.room.is_accessible:
                reasons.append("requires an accessible room")
            if separate_required and len(separate_students) != len(items):
                reasons.append("separate-room student shares with other students")
            if (
                not separate_required
                and separate_students
            ):
                reasons.append("non-separate student shares a separate room")
            if reasons and not reported:
                violations.append(
                    {
                        "code": CODE.ACCOMMODATION_VIOLATION,
                        "assignment": assignment,
                        "entity_id": item.student_id,
                        "detail": "; ".join(reasons) + ".",
                    }
                )
                reported = True
    return violations, len(allocations)


def check_room_unavailable(run):
    assignments = list(_assignments(run))
    violations = []
    for assignment in assignments:
        covered = Availability.objects.filter(
            room_id=assignment.room_id,
            start_at__lte=assignment.start_at,
            end_at__gte=assignment.end_at,
        ).exists()
        closed = RoomClosure.objects.filter(
            room_id=assignment.room_id,
        ).filter(
            Q(run__isnull=True) | Q(run=run)
        ).filter(
            start_at__lt=assignment.end_at,
            end_at__gt=assignment.start_at,
        ).exists()
        if not covered or closed:
            detail = (
                "Room availability does not cover the full interval."
                if not covered
                else "Room closure overlaps the assignment."
            )
            violations.append(
                {
                    "code": CODE.ROOM_UNAVAILABLE_VIOLATION,
                    "assignment": assignment,
                    "entity_id": assignment.room_id,
                    "detail": detail,
                }
            )
    return violations, len(assignments)


def check_student_allocation_mismatch(run):
    assignments = list(
        _assignments(run).select_related("exam").order_by("exam_id")
    )
    if not assignments:
        return [], 0
    counts = dict(
        StudentRoomAllocation.objects.filter(run=run)
        .values("assignment_id")
        .annotate(count=Count("allocation_id"))
        .values_list("assignment_id", "count")
    )
    violations = []
    for assignment in assignments:
        actual = counts.get(assignment.assignment_id, 0)
        if actual != assignment.allocated_count:
            violations.append(
                {
                    "code": CODE.STUDENT_ALLOCATION_MISMATCH,
                    "assignment": assignment,
                    "entity_id": assignment.assignment_id,
                    "detail": (
                        f"Allocated count is {assignment.allocated_count}; "
                        f"found {actual} student allocations."
                    ),
                }
            )

    by_exam = defaultdict(list)
    for assignment in assignments:
        by_exam[assignment.exam_id].append(assignment)
    for exam_id, exam_assignments in by_exam.items():
        expected = set(
            Enrollment.objects.filter(
                course_id=exam_assignments[0].exam.course_id,
                term=exam_assignments[0].exam.term,
                status=Enrollment.Status.ACTIVE,
            ).values_list("student_id", flat=True)
        )
        actual = set(
            StudentRoomAllocation.objects.filter(
                run=run, exam_id=exam_id
            ).values_list("student_id", flat=True)
        )
        if actual != expected:
            violations.append(
                {
                    "code": CODE.STUDENT_ALLOCATION_MISMATCH,
                    "assignment": exam_assignments[0],
                    "entity_id": exam_id,
                    "detail": (
                        f"Student roster differs: missing={len(expected - actual)}, "
                        f"unexpected={len(actual - expected)}."
                    ),
                }
            )
    return violations, len(assignments)


def check_invalid_duration(run):
    assignments = list(
        _assignments(run).select_related("exam")
    )
    violations = []
    for assignment in assignments:
        duration = (
            assignment.end_at - assignment.start_at
        ).total_seconds() / 60
        if duration < assignment.exam.duration_minutes:
            violations.append(
                {
                    "code": CODE.INVALID_DURATION,
                    "assignment": assignment,
                    "entity_id": assignment.assignment_id,
                    "detail": (
                        f"Duration {int(duration)} is shorter than the "
                        f"{assignment.exam.duration_minutes}-minute exam."
                    ),
                }
            )
    return violations, len(assignments)


CHECKS = [
    ("student_double_booking", check_student_overlap),
    ("room_capacity", check_room_capacity),
    ("missing_equipment", check_missing_equipment),
    ("room_double_booked", check_room_double_booking),
    ("invigilator_double_booked", check_invigilator_double_booking),
    ("invigilator_unavailable", check_invigilator_availability),
    ("accommodation_violation", check_accommodation),
    ("room_unavailable", check_room_unavailable),
    ("student_allocation_mismatch", check_student_allocation_mismatch),
    ("invalid_duration", check_invalid_duration),
]
