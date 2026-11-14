"""Best-fit room allocation with capacity, equipment, and availability checks."""

from apps.scheduling.services.accommodation import (
    needs_accessible_room,
    needs_separate_room,
)
from apps.scheduling.services.slot_allocator import buffered_overlap, overlap
from apps.scheduling.models import UnassignedExam


def _rooms_for_interval(ctx, exam, start_at, end_at):
    on_date = start_at.date()
    equipment_needed = getattr(ctx, "exam_equipment", {}).get(exam.exam_id, set())
    available = []
    rejected = {
        "inactive_or_missing_capacity": 0,
        "missing_equipment": 0,
        "unavailable_or_closed": 0,
        "already_booked": 0,
    }

    for room in ctx.rooms:
        capacity = ctx.capacity(room, on_date)
        if capacity <= 0:
            rejected["inactive_or_missing_capacity"] += 1
            continue
        if not equipment_needed.issubset(
            ctx.room_equipment.get(room.room_id, set())
        ):
            rejected["missing_equipment"] += 1
            continue
        if not any(
            window_start <= start_at and window_end >= end_at
            for window_start, window_end in ctx.room_avails.get(
                room.room_id, ()
            )
        ):
            rejected["unavailable_or_closed"] += 1
            continue
        if any(
            overlap(start_at, end_at, closure_start, closure_end)
            for closure_start, closure_end in ctx.room_closures.get(
                room.room_id, ()
            )
        ):
            rejected["unavailable_or_closed"] += 1
            continue
        if any(
            buffered_overlap(
                start_at,
                end_at,
                booked_start,
                booked_end,
                ctx.policy.get("HARD_BUFFER_MINUTES", 0),
            )
            for booked_start, booked_end in ctx.room_bookings.get(
                room.room_id, ()
            )
        ):
            rejected["already_booked"] += 1
            continue
        available.append((room, capacity))

    return available, rejected


def _place_group(
    ctx,
    students,
    candidate_rooms,
    allocations,
    *,
    separate,
    allow_multi_room,
    require_accessible,
):
    """Place a group in best-fit rooms; return False without partial side effects."""
    remaining = list(students)
    if not remaining:
        return True

    candidates = sorted(
        candidate_rooms,
        key=lambda item: (item[1], item[0].room_id),
    )
    existing = [
        allocation
        for allocation in allocations
        if allocation["separate"] == separate
        and (not require_accessible or allocation["accessible"])
        and allocation["capacity"] > len(allocation["students"])
    ]
    for allocation in existing:
        take = min(
            len(remaining),
            allocation["capacity"] - len(allocation["students"]),
        )
        allocation["students"].extend(remaining[:take])
        remaining = remaining[take:]
        if not remaining:
            return True

    eligible = [
        item for item in candidates
        if item[0].room_id not in {allocation["room"].room_id for allocation in allocations}
    ]
    if not allow_multi_room:
        eligible = [
            item for item in eligible if item[1] >= len(remaining)
        ]
        if not eligible:
            return False
        selected = min(
            eligible,
            key=lambda item: (item[1] - len(remaining), item[0].room_id),
        )
        allocations.append(
            {
                "room": selected[0],
                "capacity": selected[1],
                "students": remaining,
                "separate": separate,
                "accessible": selected[0].is_accessible,
            }
        )
        return True

    while remaining:
        fitting = [item for item in eligible if item[1] >= len(remaining)]
        if fitting:
            selected = min(
                fitting,
                key=lambda item: (item[1] - len(remaining), item[0].room_id),
            )
            take = len(remaining)
        elif eligible:
            selected = max(
                eligible,
                key=lambda item: (item[1], item[0].room_id),
            )
            take = selected[1]
        else:
            return False

        allocations.append(
            {
                "room": selected[0],
                "capacity": selected[1],
                "students": remaining[:take],
                "separate": separate,
                "accessible": selected[0].is_accessible,
            }
        )
        remaining = remaining[take:]
        eligible.remove(selected)

    return True


def allocate_rooms(ctx, exam, students_with_acc, start_at, end_at):
    """Return ``(room/student allocations, reason)`` for one exam and slot."""
    compatible_rooms, rejected = _rooms_for_interval(
        ctx, exam, start_at, end_at
    )
    ctx.last_room_evidence = {
        "compatible_room_count": len(compatible_rooms),
        "rejected_room_counts": rejected,
    }
    if not compatible_rooms:
        if rejected["missing_equipment"]:
            return None, UnassignedExam.Reason.NO_EQUIPMENT_ROOM
        if rejected["unavailable_or_closed"] or rejected["already_booked"]:
            return None, UnassignedExam.Reason.ROOM_UNAVAILABLE
        return None, UnassignedExam.Reason.NO_ROOM_CAPACITY

    allocations = []
    separate_students = []
    separate_accessible = []
    accessible_students = []
    regular_students = []
    for student, accommodations in students_with_acc:
        if needs_separate_room(accommodations):
            separate_students.append(student)
            if needs_accessible_room(accommodations):
                separate_accessible.append(student)
        elif needs_accessible_room(accommodations):
            accessible_students.append(student)
        else:
            regular_students.append(student)

    requirement = ctx.exam_requirements.get(exam.exam_id)
    allow_multi_room = requirement.allow_multi_room if requirement else True

    if not allow_multi_room:
        if separate_students and len(separate_students) != len(students_with_acc):
            ctx.last_room_evidence["failure_group"] = "separate_room"
            return None, UnassignedExam.Reason.ACCOMMODATION_UNSATISFIABLE
        needs_accessible = any(
            needs_accessible_room(accommodations)
            for _, accommodations in students_with_acc
        )
        candidates = [
            item for item in compatible_rooms
            if not needs_accessible or item[0].is_accessible
        ]
        candidates = [
            item for item in candidates
            if item[1] >= len(students_with_acc)
        ]
        if not candidates:
            ctx.last_room_evidence["failure_group"] = (
                "accessible_room" if needs_accessible else "room_capacity"
            )
            reason = (
                UnassignedExam.Reason.ACCOMMODATION_UNSATISFIABLE
                if needs_accessible
                else UnassignedExam.Reason.NO_ROOM_CAPACITY
            )
            return None, reason
        room, _capacity = min(
            candidates,
            key=lambda item: (
                item[1] - len(students_with_acc),
                item[0].room_id,
            ),
        )
        return [(room, [student for student, _ in students_with_acc])], None

    accessible_rooms = [
        item for item in compatible_rooms if item[0].is_accessible
    ]
    if separate_accessible:
        if not _place_group(
            ctx,
            separate_accessible,
            accessible_rooms,
            allocations,
            separate=True,
            allow_multi_room=allow_multi_room,
            require_accessible=True,
        ):
            ctx.last_room_evidence["failure_group"] = "separate_accessible"
            return None, UnassignedExam.Reason.ACCOMMODATION_UNSATISFIABLE

    separate_regular = [
        student for student in separate_students
        if student not in set(separate_accessible)
    ]
    if separate_regular and not _place_group(
        ctx,
        separate_regular,
        compatible_rooms,
        allocations,
        separate=True,
        allow_multi_room=allow_multi_room,
        require_accessible=False,
    ):
        ctx.last_room_evidence["failure_group"] = "separate_room"
        return None, UnassignedExam.Reason.ACCOMMODATION_UNSATISFIABLE

    if accessible_students and not _place_group(
        ctx,
        accessible_students,
        accessible_rooms,
        allocations,
        separate=False,
        allow_multi_room=allow_multi_room,
        require_accessible=True,
    ):
        ctx.last_room_evidence["failure_group"] = "accessible_room"
        return None, UnassignedExam.Reason.ACCOMMODATION_UNSATISFIABLE

    # Students without a room restriction may use spare seats in rooms that
    # already contain non-separated accessible students.
    for allocation in allocations:
        if allocation["separate"]:
            continue
        if allocation["capacity"] <= len(allocation["students"]):
            continue
        take = min(
            len(regular_students),
            allocation["capacity"] - len(allocation["students"]),
        )
        allocation["students"].extend(regular_students[:take])
        regular_students = regular_students[take:]
        if not regular_students:
            break

    if regular_students and not _place_group(
        ctx,
        regular_students,
        compatible_rooms,
        allocations,
        separate=False,
        allow_multi_room=allow_multi_room,
        require_accessible=False,
    ):
        ctx.last_room_evidence["failure_group"] = "room_capacity"
        return None, UnassignedExam.Reason.NO_ROOM_CAPACITY

    if len(allocations) == 0:
        return [], None
    return [
        (allocation["room"], allocation["students"])
        for allocation in allocations
    ], None
