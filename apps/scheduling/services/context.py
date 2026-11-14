"""Preloaded, per-run in-memory scheduling state."""

from collections import defaultdict

from django.db.models import Q

from apps.core.models import (
    Accommodation,
    Exam,
    ExamRequirement,
    ExamRequirementEquipment,
    Invigilator,
    Room,
    RoomCapacity,
    RoomEquipment,
    Student,
)
from apps.core.services.id_generator import make_id
from apps.scheduling.models import (
    Availability,
    InvigilatorAssignment,
    RoomClosure,
    ScheduleEvent,
    StudentRoomAllocation,
    TimeSlot,
    UnassignedExam,
)


def _next_counter(model, field_name):
    last_value = (
        model.objects.order_by(f"-{field_name}")
        .values_list(field_name, flat=True)
        .first()
    )
    if not last_value:
        return 0
    try:
        return int(last_value.rsplit("-", 1)[-1])
    except ValueError as error:
        raise ValueError(f"Invalid {field_name} value in {model._meta.label}.") from error


class SchedulingContext:
    def __init__(
        self,
        *,
        run,
        term,
        exams,
        graph,
        students_by_exam,
        invigilators=(),
        capacities=None,
        invigilator_avails=None,
        exam_requirements=None,
        policy=None,
        rooms=(),
        room_equipment=None,
        exam_equipment=None,
        room_avails=None,
        room_closures=None,
        slots=(),
        accommodations=None,
    ):
        self.run = run
        self.term = term
        self.exams = list(exams)
        self.graph = graph
        self.students_by_exam = students_by_exam
        self.invigilators = list(invigilators)
        self.capacities = capacities or {}
        self.invigilator_avails = invigilator_avails or {}
        self.exam_requirements = exam_requirements or {}
        self.policy = policy or {}
        self.rooms = list(rooms)
        self.room_equipment = room_equipment or {}
        self.exam_equipment = exam_equipment or {}
        self.room_avails = room_avails or {}
        self.room_closures = room_closures or {}
        self.slots = list(slots)
        self.accommodations = accommodations or {}
        self.students = {}

        self.room_bookings = defaultdict(list)
        self.invigilator_bookings = defaultdict(list)
        self.student_intervals = defaultdict(list)
        self.exam_slots = {}
        self.time_groups = {}
        self.last_room_evidence = {}

        self._sra_counter = _next_counter(
            StudentRoomAllocation, "allocation_id"
        )
        self._ias_counter = _next_counter(InvigilatorAssignment, "ias_id")
        self._evt_counter = _next_counter(ScheduleEvent, "event_id")
        self._una_counter = _next_counter(UnassignedExam, "unassigned_id")

    def next_sra(self):
        self._sra_counter += 1
        return make_id("student_allocation", self._sra_counter)

    def next_ias(self):
        self._ias_counter += 1
        return make_id("invigilator_assignment", self._ias_counter)

    def next_evt(self):
        self._evt_counter += 1
        return make_id("event", self._evt_counter)

    def next_una(self):
        self._una_counter += 1
        return make_id("unassigned", self._una_counter)

    def capacity(self, room, on_date):
        effective = [
            (effective_from, capacity)
            for effective_from, effective_to, capacity
            in self.capacities.get(room.room_id, ())
            if effective_from <= on_date
            and (effective_to is None or effective_to >= on_date)
        ]
        return max(effective, default=(None, 0))[1]

def build_context(run, term, policy):
    exams = list(
        Exam.objects.filter(term=term)
        .select_related("course")
        .order_by("exam_id")
    )
    from apps.scheduling.services.conflict_graph import build_conflict_graph

    graph, students_by_exam = build_conflict_graph(exams, term=term)

    capacities = defaultdict(list)
    for capacity in RoomCapacity.objects.order_by("room_id", "effective_from"):
        capacities[capacity.room_id].append(
            (
                capacity.effective_from,
                capacity.effective_to,
                capacity.exam_capacity,
            )
        )

    invigilator_avails = defaultdict(list)
    room_avails = defaultdict(list)
    for availability in Availability.objects.order_by("availability_id"):
        interval = (availability.start_at, availability.end_at)
        if availability.invigilator_id:
            invigilator_avails[availability.invigilator_id].append(interval)
        elif availability.room_id:
            room_avails[availability.room_id].append(interval)

    room_closures = defaultdict(list)
    for closure in RoomClosure.objects.filter(
        Q(run__isnull=True) | Q(run=run)
    ).order_by("closure_id"):
        room_closures[closure.room_id].append(
            (closure.start_at, closure.end_at)
        )

    room_equipment = defaultdict(set)
    for room_id, equipment_id in RoomEquipment.objects.order_by(
        "room_id", "equipment_id"
    ).values_list("room_id", "equipment_id"):
        room_equipment[room_id].add(equipment_id)

    requirements = {
        requirement.exam_id: requirement
        for requirement in ExamRequirement.objects.order_by("requirement_id")
    }
    requirement_equipment = defaultdict(set)
    for requirement_id, equipment_id in ExamRequirementEquipment.objects.values_list(
        "requirement_id", "equipment_id"
    ):
        requirement_equipment[requirement_id].add(equipment_id)
    exam_equipment = {
        exam_id: requirement_equipment[requirement.requirement_id]
        for exam_id, requirement in requirements.items()
    }
    active_student_ids = {
        student_id
        for student_ids in students_by_exam.values()
        for student_id in student_ids
    }

    accommodations = defaultdict(list)
    for accommodation in Accommodation.objects.filter(
        status=Accommodation.Status.ACTIVE
    ).order_by("accommodation_id"):
        accommodations[accommodation.student_id].append(accommodation)

    context = SchedulingContext(
        run=run,
        term=term,
        exams=exams,
        graph=graph,
        students_by_exam=students_by_exam,
        invigilators=Invigilator.objects.filter(
            status=Invigilator.Status.ACTIVE
        ).order_by("invigilator_id"),
        capacities=capacities,
        invigilator_avails=invigilator_avails,
        exam_requirements=requirements,
        policy=policy,
        rooms=Room.objects.filter(status=Room.Status.ACTIVE).order_by("room_id"),
        room_equipment=room_equipment,
        exam_equipment=exam_equipment,
        room_avails=room_avails,
        room_closures=room_closures,
        slots=TimeSlot.objects.order_by("slot_date", "start_time", "slot_id"),
        accommodations=accommodations,
    )
    context.students = Student.objects.in_bulk(active_student_ids)
    return context
