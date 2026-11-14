"""Create a separate run containing five controlled scheduling anomalies."""

import csv
import datetime as dt
import itertools
import json
from collections import defaultdict
from itertools import islice
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.models import (
    Accommodation,
    ExamRequirementEquipment,
    Invigilator,
    Room,
    RoomCapacity,
)
from apps.core.services.id_generator import make_assignment_id, make_id
from apps.core.services.lifecycle import transition
from apps.scheduling.models import (
    Availability,
    InvigilatorAssignment,
    RoomClosure,
    ScheduleAssignment,
    ScheduleEvent,
    SchedulerRun,
    StudentRoomAllocation,
)
from apps.validation.models import DetectedViolation

CODE = DetectedViolation.Code


def _next_id(model, field_name, kind):
    last_id = model.objects.order_by(f"-{field_name}").values_list(
        field_name, flat=True
    ).first()
    number = int(last_id.split("-")[-1]) + 1 if last_id else 1
    return make_id(kind, number)


class _CopyContext:
    def __init__(self, run):
        self.run = run
        self.sra_number = _last_number(
            StudentRoomAllocation, "allocation_id"
        )
        self.ias_number = _last_number(
            InvigilatorAssignment, "ias_id"
        )
        self.event_number = _last_number(ScheduleEvent, "event_id")
        self.closure_number = _last_number(RoomClosure, "closure_id")
        self.assignments = {}

    def next_sra(self):
        self.sra_number += 1
        return make_id("student_allocation", self.sra_number)

    def next_ias(self):
        self.ias_number += 1
        return make_id("invigilator_assignment", self.ias_number)

    def next_event(self):
        self.event_number += 1
        return make_id("event", self.event_number)

    def next_closure(self):
        self.closure_number += 1
        return make_id("closure", self.closure_number)


def _last_number(model, field_name):
    last_id = model.objects.order_by(f"-{field_name}").values_list(
        field_name, flat=True
    ).first()
    return int(last_id.split("-")[-1]) if last_id else 0


def _effective_capacity(room_id, on_date, capacities):
    return max(
        (
            capacity
            for start, end, capacity in capacities.get(room_id, ())
            if start <= on_date and (end is None or end >= on_date)
        ),
        default=0,
    )


def _covered(intervals, start_at, end_at):
    return any(
        available_start <= start_at and available_end >= end_at
        for available_start, available_end in intervals
    )


def _overlap(first_start, first_end, second_start, second_end):
    return first_start < second_end and second_start < first_end


def _copy_assignment(ctx, baseline_assignment):
    assignment = ScheduleAssignment.objects.create(
        assignment_id=make_assignment_id(
            baseline_assignment.exam_id,
            baseline_assignment.room_id,
            ctx.run.run_id,
        ),
        run=ctx.run,
        exam_id=baseline_assignment.exam_id,
        room_id=baseline_assignment.room_id,
        start_at=baseline_assignment.start_at,
        end_at=baseline_assignment.end_at,
        allocated_count=baseline_assignment.allocated_count,
        status=ScheduleAssignment.Status.ASSIGNED,
    )
    for student_id, required_minutes in (
        StudentRoomAllocation.objects.filter(
            assignment=baseline_assignment
        ).values_list("student_id", "required_minutes")
    ):
        StudentRoomAllocation.objects.create(
            allocation_id=ctx.next_sra(),
            assignment=assignment,
            run=ctx.run,
            exam_id=baseline_assignment.exam_id,
            student_id=student_id,
            required_minutes=required_minutes,
        )
    for invigilator_id, role in (
        InvigilatorAssignment.objects.filter(
            assignment=baseline_assignment
        ).values_list("invigilator_id", "role")
    ):
        InvigilatorAssignment.objects.create(
            ias_id=ctx.next_ias(),
            assignment=assignment,
            invigilator_id=invigilator_id,
            role=role,
        )
    ctx.assignments[baseline_assignment.assignment_id] = assignment
    return assignment


def _replace_assignment_room(ctx, assignment, target_room_id):
    students = list(
        assignment.student_allocations.values_list(
            "student_id", "required_minutes"
        )
    )
    invigilators = list(
        assignment.invigilator_assignments.values_list(
            "invigilator_id", "role"
        )
    )
    old_id = assignment.assignment_id
    assignment.delete()
    replacement = ScheduleAssignment.objects.create(
        assignment_id=make_assignment_id(
            assignment.exam_id, target_room_id, ctx.run.run_id
        ),
        run=ctx.run,
        exam_id=assignment.exam_id,
        room_id=target_room_id,
        start_at=assignment.start_at,
        end_at=assignment.end_at,
        allocated_count=assignment.allocated_count,
        status=ScheduleAssignment.Status.ASSIGNED,
    )
    for student_id, required_minutes in students:
        StudentRoomAllocation.objects.create(
            allocation_id=ctx.next_sra(),
            assignment=replacement,
            run=ctx.run,
            exam_id=assignment.exam_id,
            student_id=student_id,
            required_minutes=required_minutes,
        )
    for invigilator_id, role in invigilators:
        InvigilatorAssignment.objects.create(
            ias_id=ctx.next_ias(),
            assignment=replacement,
            invigilator_id=invigilator_id,
            role=role,
        )
    ctx.assignments[old_id] = replacement
    return replacement


def _replace_invigilators(ctx, assignment, invigilator_ids):
    InvigilatorAssignment.objects.filter(assignment=assignment).delete()
    for index, invigilator_id in enumerate(invigilator_ids):
        InvigilatorAssignment.objects.create(
            ias_id=ctx.next_ias(),
            assignment=assignment,
            invigilator_id=invigilator_id,
            role=(
                InvigilatorAssignment.Role.CHIEF
                if index == 0
                else InvigilatorAssignment.Role.ASSISTANT
            ),
        )


def _write_ground_truth(rows, run):
    data_dir = Path(settings.BASE_DIR) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "anomaly_id",
        "issue_type",
        "assignment_id",
        "affected_entity_id",
        "expected_violation_code",
        "run_id",
    ]
    enriched = [{**row, "run_id": run.run_id} for row in rows]
    csv_path = data_dir / "ground_truth.csv"
    json_path = data_dir / "ground_truth.json"
    csv_temp = csv_path.with_suffix(".csv.tmp")
    json_temp = json_path.with_suffix(".json.tmp")
    with csv_temp.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(enriched)
    json_temp.write_text(
        json.dumps(enriched, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_temp.replace(csv_path)
    json_temp.replace(json_path)


def _anomaly_row(anomaly_id, issue_type, assignment_id, entity_id, code):
    return {
        "anomaly_id": anomaly_id,
        "issue_type": issue_type,
        "assignment_id": assignment_id,
        "affected_entity_id": entity_id,
        "expected_violation_code": code,
    }


def inject(baseline_run_id):
    """Clone selected baseline assignments and add five labeled anomalies."""
    with transaction.atomic():
        try:
            baseline = SchedulerRun.objects.get(pk=baseline_run_id)
        except SchedulerRun.DoesNotExist as error:
            raise ValueError(
                f"Baseline scheduler run {baseline_run_id} was not found."
            ) from error
        if baseline.run_type != SchedulerRun.RunType.BASELINE:
            raise ValueError(f"{baseline_run_id} is not a BASELINE run.")
        if baseline.status != SchedulerRun.Status.COMPLETED:
            raise ValueError(f"{baseline_run_id} is not COMPLETED.")

        selection = _select_fixture(baseline)
        run = SchedulerRun.objects.create(
            run_id=_next_id(SchedulerRun, "run_id", "run"),
            run_type=SchedulerRun.RunType.ANOMALY_FIXTURE,
            status=SchedulerRun.Status.RUNNING,
            seed=baseline.seed,
            algorithm_version="phase-5-anomaly-fixture-1",
            notes=f"Anomaly fixture copied from {baseline.run_id}.",
        )
        ctx = _CopyContext(run)
        exam_ids = {
            selection[key].exam_id
            for key in ("A", "B", "C", "D", "E", "F", "G")
        }
        source_assignments = list(
            ScheduleAssignment.objects.filter(
                run=baseline,
                status=ScheduleAssignment.Status.ASSIGNED,
                exam_id__in=exam_ids,
            ).order_by("exam_id", "assignment_id")
        )
        for source in source_assignments:
            _copy_assignment(ctx, source)

        a = ctx.assignments[selection["A"].assignment_id]
        b = ctx.assignments[selection["B"].assignment_id]
        b.start_at = a.start_at
        b.end_at = a.end_at
        b.save(update_fields=["start_at", "end_at"])
        _replace_invigilators(
            ctx, b, selection["B_invigilators"]
        )

        c = _replace_assignment_room(
            ctx,
            ctx.assignments[selection["C"].assignment_id],
            selection["C_room"].room_id,
        )

        d = ctx.assignments[selection["D"].assignment_id]
        e = ctx.assignments[selection["E"].assignment_id]
        e.start_at = d.start_at
        e.end_at = d.end_at
        e.save(update_fields=["start_at", "end_at"])
        _replace_invigilators(
            ctx, e, selection["E_invigilators"]
        )

        f = ctx.assignments[selection["F"].assignment_id]
        f.end_at = f.start_at + dt.timedelta(
            minutes=f.exam.duration_minutes
        )
        f.save(update_fields=["end_at"])

        g = ctx.assignments[selection["G"].assignment_id]
        RoomClosure.objects.create(
            closure_id=ctx.next_closure(),
            room_id=g.room_id,
            run=run,
            start_at=g.start_at - dt.timedelta(minutes=10),
            end_at=g.start_at + dt.timedelta(minutes=10),
            reason=RoomClosure.Reason.MAINTENANCE,
        )

        selected_assignments = list(
            ScheduleAssignment.objects.filter(run=run).order_by(
                "exam_id", "assignment_id"
            )
        )
        for exam_id in sorted(exam_ids):
            exam_assignments = [
                assignment
                for assignment in selected_assignments
                if assignment.exam_id == exam_id
            ]
            ScheduleEvent.objects.create(
                event_id=ctx.next_event(),
                run=run,
                exam_id=exam_id,
                assignment=(
                    exam_assignments[0]
                    if len(exam_assignments) == 1
                    else None
                ),
                event_type=ScheduleEvent.EventType.ASSIGNED,
                detail={
                    "fixture": True,
                    "assignment_ids": [
                        assignment.assignment_id
                        for assignment in exam_assignments
                    ],
                },
            )

        shared_student = selection["shared_student"]
        shared_invigilator = selection["D_invigilator"]
        rows = [
            _anomaly_row(
                "EDGE-001",
                "STUDENT_OVERLAP",
                a.assignment_id,
                shared_student,
                CODE.STUDENT_DOUBLE_BOOKING.value,
            ),
            _anomaly_row(
                "EDGE-001",
                "STUDENT_OVERLAP",
                b.assignment_id,
                shared_student,
                CODE.STUDENT_DOUBLE_BOOKING.value,
            ),
            _anomaly_row(
                "EDGE-002",
                "CAPACITY_EXCEEDED",
                c.assignment_id,
                c.room_id,
                CODE.ROOM_CAPACITY_EXCEEDED.value,
            ),
            _anomaly_row(
                "EDGE-003",
                "INVIGILATOR_CLASH",
                d.assignment_id,
                shared_invigilator,
                CODE.INVIGILATOR_DOUBLE_BOOKED.value,
            ),
            _anomaly_row(
                "EDGE-003",
                "INVIGILATOR_CLASH",
                e.assignment_id,
                shared_invigilator,
                CODE.INVIGILATOR_DOUBLE_BOOKED.value,
            ),
            _anomaly_row(
                "EDGE-004",
                "ACCOMMODATION_BREACH",
                f.assignment_id,
                selection["F_student"],
                CODE.ACCOMMODATION_VIOLATION.value,
            ),
            _anomaly_row(
                "EDGE-005",
                "ROOM_CLOSED",
                g.assignment_id,
                g.room_id,
                CODE.ROOM_UNAVAILABLE_VIOLATION.value,
            ),
        ]
        transition(run, SchedulerRun.Status.COMPLETED)
        run.finished_at = timezone.now()
        run.save(update_fields=["finished_at"])

    _write_ground_truth(rows, run)
    return run, rows, {
        key: selection[key].exam_id
        for key in ("A", "B", "C", "D", "E", "F", "G")
    }


def _select_fixture(baseline):
    assignments = list(
        ScheduleAssignment.objects.filter(
            run=baseline,
            status=ScheduleAssignment.Status.ASSIGNED,
        )
        .select_related("exam", "room", "exam__requirement")
        .order_by("exam_id", "assignment_id")
    )
    if len({assignment.exam_id for assignment in assignments}) < 7:
        raise ValueError(
            "At least seven assigned exams are required to build the fixture."
        )

    assignment_students = defaultdict(set)
    assignment_required = defaultdict(dict)
    for assignment_id, student_id, required_minutes in (
        StudentRoomAllocation.objects.filter(run=baseline).values_list(
            "assignment_id", "student_id", "required_minutes"
        )
    ):
        assignment_students[assignment_id].add(student_id)
        assignment_required[assignment_id][student_id] = required_minutes
    assignment_invigilators = defaultdict(list)
    for assignment_id, invigilator_id in (
        InvigilatorAssignment.objects.filter(
            assignment__run=baseline
        ).values_list("assignment_id", "invigilator_id")
    ):
        assignment_invigilators[assignment_id].append(invigilator_id)
    assignments_by_exam = defaultdict(list)
    for assignment in assignments:
        assignments_by_exam[assignment.exam_id].append(assignment)

    equipment_by_exam = defaultdict(set)
    for exam_id, equipment_id in (
        ExamRequirementEquipment.objects.filter(
            requirement__exam_id__in=assignments_by_exam
        ).values_list("requirement__exam_id", "equipment_id")
    ):
        equipment_by_exam[exam_id].add(equipment_id)
    capacities = defaultdict(list)
    for room_id, start, end, capacity in RoomCapacity.objects.values_list(
        "room_id", "effective_from", "effective_to", "exam_capacity"
    ):
        capacities[room_id].append((start, end, capacity))
    rooms = {
        room.room_id: room
        for room in Room.objects.filter(status=Room.Status.ACTIVE).prefetch_related(
            "equipment"
        )
    }
    room_equipment = {
        room_id: {equipment.code for equipment in room.equipment.all()}
        for room_id, room in rooms.items()
    }
    room_availability = defaultdict(list)
    invigilator_availability = defaultdict(list)
    for room_id, invigilator_id, start_at, end_at in Availability.objects.values_list(
        "room_id", "invigilator_id", "start_at", "end_at"
    ):
        if room_id:
            room_availability[room_id].append((start_at, end_at))
        if invigilator_id:
            invigilator_availability[invigilator_id].append(
                (start_at, end_at)
            )
    closures = defaultdict(list)
    for room_id, start_at, end_at in RoomClosure.objects.filter(
        run__isnull=True
    ).values_list(
        "room_id", "start_at", "end_at"
    ):
        closures[room_id].append((start_at, end_at))
    active_invigilators = list(
        Invigilator.objects.filter(status=Invigilator.Status.ACTIVE)
        .order_by("invigilator_id")
        .values_list("invigilator_id", flat=True)
    )
    accommodations_by_student = defaultdict(list)
    for accommodation in Accommodation.objects.filter(
        status=Accommodation.Status.ACTIVE
    ):
        accommodations_by_student[accommodation.student_id].append(
            accommodation
        )

    def accommodations_for(student_id, on_date):
        return [
            accommodation
            for accommodation in accommodations_by_student[student_id]
            if accommodation.effective_from <= on_date
            and (
                accommodation.effective_to is None
                or accommodation.effective_to >= on_date
            )
        ]

    def required_for(assignment_id):
        return max(
            assignment_required[assignment_id].values(),
            default=0,
        )

    def staff_count(assignment):
        requirement = getattr(assignment.exam, "requirement", None)
        ratio = requirement.invigilator_ratio if requirement else 50
        return max(1, (assignment.allocated_count + ratio - 1) // ratio)

    overlap_candidates = []
    for first in assignments:
        first_exam_students = set().union(
            *(
                assignment_students[row.assignment_id]
                for row in assignments_by_exam[first.exam_id]
            )
        )
        for second in assignments:
            if (
                first.exam_id == second.exam_id
                or first.room_id == second.room_id
            ):
                continue
            shared = assignment_students[first.assignment_id] & assignment_students[
                second.assignment_id
            ]
            if not shared:
                continue
            other_first_rooms = first_exam_students - assignment_students[
                first.assignment_id
            ]
            if assignment_students[second.assignment_id] & other_first_rooms:
                continue
            if required_for(second.assignment_id) > (
                first.end_at - first.start_at
            ).total_seconds() / 60:
                continue
            if not _covered(
                room_availability[second.room_id],
                first.start_at,
                first.end_at,
            ):
                continue
            if any(
                _overlap(
                    first.start_at,
                    first.end_at,
                    closure_start,
                    closure_end,
                )
                for closure_start, closure_end in closures[second.room_id]
            ):
                continue
            overlap_candidates.append((first, second, min(shared)))
    overlap_candidates.sort(
        key=lambda item: (
            len(
                assignment_students[item[0].assignment_id]
                & assignment_students[item[1].assignment_id]
            ),
            item[0].assignment_id,
            item[1].assignment_id,
        )
    )

    capacity_candidates = []
    for assignment in assignments:
        needed = equipment_by_exam[assignment.exam_id]
        accessible_students = {
            student_id
            for student_id in assignment_students[assignment.assignment_id]
            if any(
                accommodation.accommodation_type
                == Accommodation.Type.ACCESSIBLE_ROOM
                for accommodation in accommodations_for(
                    student_id, assignment.start_at.date()
                )
            )
        }
        for room_id, room in rooms.items():
            if room_id in {
                row.room_id
                for row in assignments_by_exam[assignment.exam_id]
            }:
                continue
            capacity = _effective_capacity(
                room_id, assignment.start_at.date(), capacities
            )
            if (
                capacity <= 0
                or capacity >= assignment.allocated_count
                or not needed.issubset(room_equipment[room_id])
                or (accessible_students and not room.is_accessible)
                or not _covered(
                    room_availability[room_id],
                    assignment.start_at,
                    assignment.end_at,
                )
                or any(
                    _overlap(
                        assignment.start_at,
                        assignment.end_at,
                        closure_start,
                        closure_end,
                    )
                    for closure_start, closure_end in closures[room_id]
                )
            ):
                continue
            capacity_candidates.append((assignment, room))

    extra_time_candidates = []
    for assignment in assignments:
        if assignment.exam.duration_minutes >= (
            assignment.end_at - assignment.start_at
        ).total_seconds() / 60:
            continue
        for student_id in assignment_students[assignment.assignment_id]:
            if assignment_required[assignment.assignment_id].get(
                student_id, 0
            ) <= assignment.exam.duration_minutes:
                continue
            if any(
                accommodation.accommodation_type
                == Accommodation.Type.EXTRA_TIME
                for accommodation in accommodations_for(
                    student_id, assignment.start_at.date()
                )
            ):
                extra_time_candidates.append((assignment, student_id))
    if not overlap_candidates or not capacity_candidates or not extra_time_candidates:
        raise ValueError(
            "Baseline does not contain suitable student-overlap, capacity, "
            "and extra-time candidates for the anomaly fixture."
        )

    invigilator_sets = {
        assignment.assignment_id: set(
            assignment_invigilators[assignment.assignment_id]
        )
        for assignment in assignments
    }
    chosen = None
    for a, b, shared_student in overlap_candidates:
        b_staff_needed = max(
            staff_count(b), len(assignment_invigilators[b.assignment_id])
        )
        b_staff_pool = [
            invigilator_id
            for invigilator_id in active_invigilators
            if invigilator_id not in invigilator_sets[a.assignment_id]
            and _covered(
                invigilator_availability[invigilator_id],
                a.start_at,
                a.end_at,
            )
        ]
        b_staff_candidates = list(
            islice(
                itertools.combinations(b_staff_pool, b_staff_needed),
                16,
            )
        )
        if not b_staff_candidates:
            continue
        for c, c_room in capacity_candidates:
            used = {a.exam_id, b.exam_id, c.exam_id}
            if len(used) != 3:
                continue
            for d in assignments:
                if d.exam_id in used:
                    continue
                d_invigilators = assignment_invigilators[d.assignment_id]
                for e in assignments:
                    if (
                        e.exam_id in used
                        or e.exam_id == d.exam_id
                        or e.room_id == d.room_id
                        or not d_invigilators
                    ):
                        continue
                    if assignment_students[d.assignment_id] & assignment_students[
                        e.assignment_id
                    ]:
                        continue
                    if required_for(e.assignment_id) > (
                        d.end_at - d.start_at
                    ).total_seconds() / 60:
                        continue
                    if not _covered(
                        room_availability[e.room_id], d.start_at, d.end_at
                    ) or any(
                        _overlap(
                            d.start_at,
                            d.end_at,
                            closure_start,
                            closure_end,
                        )
                        for closure_start, closure_end in closures[e.room_id]
                    ):
                        continue
                    e_staff_needed = max(
                        staff_count(e),
                        len(assignment_invigilators[e.assignment_id]),
                        1,
                    )
                    d_staff_set = set().union(
                        *(
                            invigilator_sets[row.assignment_id]
                            for row in assignments_by_exam[d.exam_id]
                        )
                    )
                    e_staff_pool = [
                        invigilator_id
                        for invigilator_id in active_invigilators
                        if invigilator_id not in d_staff_set
                        and invigilator_id not in {d_invigilators[0]}
                        and _covered(
                            invigilator_availability[invigilator_id],
                            d.start_at,
                            d.end_at,
                        )
                    ]
                    e_staff_candidates = [
                        (d_invigilators[0], *other_staff)
                        for other_staff in islice(
                            itertools.combinations(
                                e_staff_pool, e_staff_needed - 1
                            ),
                            16,
                        )
                    ]
                    if not e_staff_candidates:
                        continue
                    for f, f_student in extra_time_candidates:
                        used_with_f = used | {d.exam_id, e.exam_id, f.exam_id}
                        if len(used_with_f) != 6:
                            continue
                        for g in assignments:
                            if g.exam_id in used_with_f:
                                continue
                            selection = {
                                "A": a,
                                "B": b,
                                "C": c,
                                "C_room": c_room,
                                "D": d,
                                "E": e,
                                "F": f,
                                "F_student": f_student,
                                "G": g,
                                "shared_student": shared_student,
                                "D_invigilator": d_invigilators[0],
                            }
                            for b_staff in b_staff_candidates:
                                for e_staff in e_staff_candidates:
                                    selection["B_invigilators"] = b_staff
                                    selection["E_invigilators"] = e_staff
                                    if _fixture_is_valid(
                                        selection,
                                        assignments_by_exam,
                                        assignment_students,
                                        assignment_invigilators,
                                        assignment_required,
                                        invigilator_availability,
                                        room_availability,
                                        closures,
                                        capacities,
                                        rooms,
                                        room_equipment,
                                        equipment_by_exam,
                                        accommodations_for,
                                    ):
                                        chosen = selection.copy()
                                        break
                                if chosen:
                                    break
                            if chosen:
                                break
                        if chosen:
                            break
                    if chosen:
                        break
                if chosen:
                    break
            if chosen:
                break
        if chosen:
            break
    if chosen is None:
        raise ValueError(
            "Could not select seven compatible exams for the anomaly fixture."
        )
    return chosen


def _fixture_is_valid(
    selection,
    assignments_by_exam,
    assignment_students,
    assignment_invigilators,
    assignment_required,
    invigilator_availability,
    room_availability,
    closures,
    capacities,
    rooms,
    room_equipment,
    equipment_by_exam,
    accommodations_for,
):
    selected_exam_ids = {
        selection[key].exam_id for key in ("A", "B", "C", "D", "E", "F", "G")
    }
    records = []
    for exam_id in selected_exam_ids:
        for assignment in assignments_by_exam[exam_id]:
            assignment_id = assignment.assignment_id
            record = {
                "source": assignment,
                "key": assignment_id,
                "exam_id": exam_id,
                "room_id": assignment.room_id,
                "start_at": assignment.start_at,
                "end_at": assignment.end_at,
                "students": assignment_students[assignment_id],
                "invigilators": set(assignment_invigilators[assignment_id]),
            }
            if assignment_id == selection["B"].assignment_id:
                record["start_at"] = selection["A"].start_at
                record["end_at"] = selection["A"].end_at
                record["invigilators"] = set(
                    selection["B_invigilators"]
                )
            if assignment_id == selection["C"].assignment_id:
                record["room_id"] = selection["C_room"].room_id
            if assignment_id == selection["E"].assignment_id:
                record["start_at"] = selection["D"].start_at
                record["end_at"] = selection["D"].end_at
                record["invigilators"] = set(
                    selection["E_invigilators"]
                )
            if assignment_id == selection["F"].assignment_id:
                record["end_at"] = record["start_at"] + dt.timedelta(
                    minutes=assignment.exam.duration_minutes
                )
            records.append(record)

    expected_student_pair = {
        selection["A"].assignment_id,
        selection["B"].assignment_id,
    }
    expected_invigilator_pair = {
        selection["D"].assignment_id,
        selection["E"].assignment_id,
    }
    for record in records:
        assignment = record["source"]
        interval_minutes = (
            record["end_at"] - record["start_at"]
        ).total_seconds() / 60
        room = rooms.get(record["room_id"])
        if room is None:
            return False
        if not _covered(
            room_availability[record["room_id"]],
            record["start_at"],
            record["end_at"],
        ):
            return False
        if any(
            _overlap(
                record["start_at"],
                record["end_at"],
                closure_start,
                closure_end,
            )
            for closure_start, closure_end in closures[record["room_id"]]
        ):
            return False
        capacity = _effective_capacity(
            record["room_id"], record["start_at"].date(), capacities
        )
        if (
            record["key"] != selection["C"].assignment_id
            and assignment.allocated_count > capacity
        ):
            return False
        if not equipment_by_exam[record["exam_id"]].issubset(
            room_equipment[record["room_id"]]
        ):
            return False
        accommodations = {
            student_id: accommodations_for(
                student_id, record["start_at"].date()
            )
            for student_id in record["students"]
        }
        separate_students = {
            student_id
            for student_id, student_accommodations in accommodations.items()
            if any(
                item.accommodation_type == Accommodation.Type.SEPARATE_ROOM
                for item in student_accommodations
            )
        }
        if separate_students and len(separate_students) != len(
            record["students"]
        ):
            return False
        if any(
            item.accommodation_type == Accommodation.Type.ACCESSIBLE_ROOM
            for student_accommodations in accommodations.values()
            for item in student_accommodations
        ) and not room.is_accessible:
            return False
        if (
            record["key"] != selection["F"].assignment_id
            and any(
                assignment_required[record["key"]].get(student_id, 0)
                > interval_minutes
                for student_id in record["students"]
            )
        ):
            return False
        if interval_minutes < assignment.exam.duration_minutes:
            return False
        for invigilator_id in record["invigilators"]:
            if not _covered(
                invigilator_availability[invigilator_id],
                record["start_at"],
                record["end_at"],
            ):
                return False

    for index, first in enumerate(records):
        for second in records[index + 1:]:
            if first["exam_id"] == second["exam_id"]:
                continue
            if not _overlap(
                first["start_at"],
                first["end_at"],
                second["start_at"],
                second["end_at"],
            ):
                continue
            pair = {first["key"], second["key"]}
            if first["room_id"] == second["room_id"]:
                return False
            if (
                first["students"] & second["students"]
                and pair != expected_student_pair
            ):
                return False
            if (
                first["invigilators"] & second["invigilators"]
                and pair != expected_invigilator_pair
            ):
                return False
    return True
