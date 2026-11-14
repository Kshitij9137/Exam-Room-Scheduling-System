"""Persist deterministic synthetic master data in a single transaction."""

import datetime as dt
import random

from django.db import transaction

from apps.core.models import (
    Accommodation,
    Course,
    Enrollment,
    Equipment,
    Exam,
    ExamRequirement,
    ExamRequirementEquipment,
    Invigilator,
    Room,
    RoomCapacity,
    RoomEquipment,
    Student,
)
from apps.scheduling.models import (
    Availability,
    InvigilatorAssignment,
    RoomClosure,
    ScheduleAssignment,
    ScheduleEvent,
    SchedulerRun,
    StudentRoomAllocation,
    TimeSlot,
    UnassignedExam,
)
from apps.validation.models import DetectedViolation, ValidationRun
from generator.config import SCALES, SEED_DEFAULT
from generator.enrollments import generate_enrollments
from generator.master_data import (
    generate_accommodations,
    generate_courses,
    generate_equipment,
    generate_exam_requirements,
    generate_exams,
    generate_invigilator_availability,
    generate_invigilators,
    generate_room_availability,
    generate_room_closures,
    generate_room_equipment_pairs,
    generate_rooms_and_capacities,
    generate_students,
    generate_timeslots,
)


def _as_date(value):
    return dt.date.fromisoformat(value) if isinstance(value, str) else value


@transaction.atomic
def clear_generated_data():
    """Clear generated rows without ever deleting append-only schedule history."""
    if ScheduleEvent.objects.exists():
        raise RuntimeError(
            "ScheduleEvent rows are append-only and exist. "
            "Cannot clear master data; use a fresh database."
        )

    DetectedViolation.objects.all().delete()
    ValidationRun.objects.all().delete()
    UnassignedExam.objects.all().delete()
    InvigilatorAssignment.objects.all().delete()
    StudentRoomAllocation.objects.all().delete()
    ScheduleAssignment.objects.all().delete()
    SchedulerRun.objects.all().delete()
    Availability.objects.all().delete()
    RoomClosure.objects.all().delete()
    TimeSlot.objects.all().delete()
    Accommodation.objects.all().delete()
    Enrollment.objects.all().delete()
    ExamRequirementEquipment.objects.all().delete()
    ExamRequirement.objects.all().delete()
    Exam.objects.all().delete()
    RoomCapacity.objects.all().delete()
    RoomEquipment.objects.all().delete()
    Room.objects.all().delete()
    Invigilator.objects.all().delete()
    Course.objects.all().delete()
    Student.objects.all().delete()
    Equipment.objects.all().delete()


@transaction.atomic
def generate_and_persist(seed=SEED_DEFAULT, scale="starter"):
    if scale not in SCALES:
        raise ValueError(f"Unknown scale {scale!r}; choose from {', '.join(SCALES)}.")

    rng = random.Random(seed)
    config = SCALES[scale]

    equipment = generate_equipment()
    timeslots = generate_timeslots()
    students = generate_students(rng, config["students"])
    courses = generate_courses(rng, config["courses"])
    exams = generate_exams(rng, courses, config["exams"])
    rooms, capacities = generate_rooms_and_capacities(rng, config["rooms"])
    invigilators = generate_invigilators(rng, config["invigilators"])
    room_equipment = generate_room_equipment_pairs(rooms)
    room_availability = generate_room_availability(rooms)
    room_closures = generate_room_closures(rng, rooms)
    invigilator_availability = generate_invigilator_availability(
        rng,
        invigilators,
        start_index=len(room_availability) + 1,
    )
    accommodations = generate_accommodations(rng, students)

    exam_course_ids = {exam["course_id"] for exam in exams}
    courses_by_id = {course["course_id"]: course for course in courses}
    requirements, requirement_equipment = generate_exam_requirements(
        rng, exams, courses_by_id
    )
    enrollments = generate_enrollments(rng, students, courses, exam_course_ids)

    Equipment.objects.bulk_create([Equipment(**row) for row in equipment])
    Student.objects.bulk_create(
        [Student(**row) for row in students], batch_size=1000
    )
    Course.objects.bulk_create([Course(**row) for row in courses])
    Invigilator.objects.bulk_create(
        [Invigilator(**row) for row in invigilators], batch_size=1000
    )
    Room.objects.bulk_create(
        [
            Room(
                room_id=row["room_id"],
                building=row["building"],
                room_number=row["room_number"],
                room_type=row["room_type"],
                is_accessible=row["is_accessible"],
                status=row["status"],
            )
            for row in rooms
        ]
    )
    RoomCapacity.objects.bulk_create(
        [
            RoomCapacity(
                capacity_id=row["capacity_id"],
                room_id=row["room_id"],
                exam_capacity=row["exam_capacity"],
                effective_from=_as_date(row["effective_from"]),
                effective_to=_as_date(row["effective_to"]),
            )
            for row in capacities
        ]
    )
    RoomEquipment.objects.bulk_create(
        [
            RoomEquipment(room_id=room_id, equipment_id=code)
            for room_id, code in room_equipment
        ]
    )
    TimeSlot.objects.bulk_create([TimeSlot(**row) for row in timeslots])
    Availability.objects.bulk_create(
        [
            Availability(
                availability_id=row["availability_id"],
                room_id=row["room_id"],
                invigilator_id=row["invigilator_id"],
                start_at=row["start_at"],
                end_at=row["end_at"],
            )
            for row in room_availability + invigilator_availability
        ],
        batch_size=1000,
    )
    RoomClosure.objects.bulk_create(
        [
            RoomClosure(
                closure_id=row["closure_id"],
                room_id=row["room_id"],
                start_at=row["start_at"],
                end_at=row["end_at"],
                reason=row["reason"],
            )
            for row in room_closures
        ]
    )
    Accommodation.objects.bulk_create(
        [
            Accommodation(
                accommodation_id=row["accommodation_id"],
                student_id=row["student_id"],
                accommodation_type=row["accommodation_type"],
                extra_time_percent=row["extra_time_percent"],
                effective_from=_as_date(row["effective_from"]),
                effective_to=_as_date(row["effective_to"]),
                status=row["status"],
            )
            for row in accommodations
        ]
    )
    Enrollment.objects.bulk_create(
        [
            Enrollment(
                enrollment_id=row["enrollment_id"],
                student_id=row["student_id"],
                course_id=row["course_id"],
                term=row["term"],
                status=row["status"],
                effective_from=_as_date(row["effective_from"]),
                effective_to=_as_date(row["effective_to"]),
            )
            for row in enrollments
        ],
        batch_size=1000,
    )
    Exam.objects.bulk_create(
        [
            Exam(
                exam_id=row["exam_id"],
                course_id=row["course_id"],
                title=row["title"],
                term=row["term"],
                duration_minutes=row["duration_minutes"],
                status=row["status"],
            )
            for row in exams
        ]
    )
    ExamRequirement.objects.bulk_create(
        [
            ExamRequirement(
                requirement_id=row["requirement_id"],
                exam_id=row["exam_id"],
                allow_multi_room=row["allow_multi_room"],
                invigilator_ratio=row["invigilator_ratio"],
            )
            for row in requirements
        ]
    )
    ExamRequirementEquipment.objects.bulk_create(
        [
            ExamRequirementEquipment(requirement_id=requirement_id, equipment_id=code)
            for requirement_id, code in requirement_equipment
        ]
    )

    return {
        "seed": seed,
        "scale": scale,
        "students": len(students),
        "courses": len(courses),
        "exams": len(exams),
        "rooms": len(rooms),
        "invigilators": len(invigilators),
        "enrollments": len(enrollments),
        "accommodations": len(accommodations),
        "timeslots": len(timeslots),
    }
