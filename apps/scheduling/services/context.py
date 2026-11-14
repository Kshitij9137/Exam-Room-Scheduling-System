"""Preloaded, per-run in-memory scheduling state."""

from collections import defaultdict

from django.db.models import Q

from apps.core.models import (
    Accommodation,
    Exam,
    Enrollment,
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


def _existing_numbers(model, field_name):
    numbers = set()
    for value in model.objects.values_list(field_name, flat=True).iterator():
        try:
            numbers.add(int(value.rsplit("-", 1)[-1]))
        except ValueError as error:
            raise ValueError(
                f"Invalid {field_name} value in {model._meta.label}."
            ) from error
    return numbers


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
        enrollment_periods_by_exam=None,
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
        self.enrollment_periods_by_exam = enrollment_periods_by_exam or {}
        self.students = {}

        self.room_bookings = defaultdict(list)
        self.invigilator_bookings = defaultdict(list)
        self.student_intervals = defaultdict(list)
        self.exam_slots = {}
        self.time_groups = {}
        self.last_room_evidence = {}

        self._sra_numbers = _existing_numbers(
            StudentRoomAllocation, "allocation_id"
        )
        self._ias_numbers = _existing_numbers(
            InvigilatorAssignment, "ias_id"
        )
        self._evt_numbers = _existing_numbers(ScheduleEvent, "event_id")
        self._una_numbers = _existing_numbers(
            UnassignedExam, "unassigned_id"
        )
        self._sra_counter = 0
        self._ias_counter = 0
        self._evt_counter = 0
        self._una_counter = 0

    @staticmethod
    def _next_number(numbers, last_number):
        number = last_number + 1
        while number in numbers:
            number += 1
        if number > 999999:
            raise ValueError("ID number space exhausted.")
        numbers.add(number)
        return number

    def next_sra(self):
        self._sra_counter = self._next_number(
            self._sra_numbers, self._sra_counter
        )
        return make_id(
            "student_allocation",
            self._sra_counter,
        )

    def next_ias(self):
        self._ias_counter = self._next_number(
            self._ias_numbers, self._ias_counter
        )
        return make_id(
            "invigilator_assignment",
            self._ias_counter,
        )

    def next_evt(self):
        self._evt_counter = self._next_number(
            self._evt_numbers, self._evt_counter
        )
        return make_id("event", self._evt_counter)

    def next_una(self):
        self._una_counter = self._next_number(
            self._una_numbers, self._una_counter
        )
        return make_id(
            "unassigned",
            self._una_counter,
        )

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
    enrollment_periods_by_exam = defaultdict(list)
    enrollments = Enrollment.objects.filter(
        status=Enrollment.Status.ACTIVE,
        term=term,
        course_id__in={exam.course_id for exam in exams},
    )
    first_slot_date = (
        TimeSlot.objects.order_by("slot_date")
        .values_list("slot_date", flat=True)
        .first()
    )
    last_slot_date = (
        TimeSlot.objects.order_by("-slot_date")
        .values_list("slot_date", flat=True)
        .first()
    )
    if first_slot_date and last_slot_date:
        enrollments = enrollments.filter(
            effective_from__lte=last_slot_date,
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=first_slot_date)
        )
    exam_by_course = {exam.course_id: exam.exam_id for exam in exams}
    for student_id, course_id, effective_from, effective_to in enrollments.values_list(
        "student_id", "course_id", "effective_from", "effective_to"
    ):
        enrollment_periods_by_exam[exam_by_course[course_id]].append(
            (student_id, effective_from, effective_to)
        )

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
        enrollment_periods_by_exam=enrollment_periods_by_exam,
    )
    context.students = Student.objects.in_bulk(active_student_ids)
    return context
