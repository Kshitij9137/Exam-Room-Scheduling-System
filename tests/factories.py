"""Tiny helpers that build valid records so each test only changes what it is testing."""
import datetime as dt

from django.utils import timezone

from apps.core.models import Accommodation, Course, Enrollment, Exam, Invigilator, Room, RoomCapacity, Student
from apps.scheduling.models import ScheduleAssignment, SchedulerRun
from apps.core.services.id_generator import make_assignment_id, make_exam_id, make_id

D = dt.date(2026, 12, 7)


def dtm(day=7, hour=9, minute=0):
    return timezone.make_aware(dt.datetime(2026, 12, day, hour, minute))


def make_student(n=1, **kw):
    d = dict(student_id=make_id("student", n), full_name=f"Student {n}", email=f"stu{n:06d}@university.example",
             department="CS", year_level=1)
    d.update(kw)
    return Student.objects.create(**d)


def make_course(n=1, **kw):
    d = dict(course_id=make_id("course", n), course_code=f"CS{100 + n}", title=f"Course {n}",
             department="CS", credits=3)
    d.update(kw)
    return Course.objects.create(**d)


def make_exam(n=1, course=None, **kw):
    course = course or make_course(n)
    d = dict(exam_id=make_exam_id(n), course=course, title=f"Exam {n}", term="2026-FALL", duration_minutes=120)
    d.update(kw)
    return Exam.objects.create(**d)


def make_room(n=1, **kw):
    d = dict(room_id=make_id("room", n), building="Block A", room_number=f"A-{100 + n}", room_type="CLASSROOM")
    d.update(kw)
    return Room.objects.create(**d)


def make_invigilator(n=1, **kw):
    d = dict(invigilator_id=make_id("invigilator", n), full_name=f"Inv {n}", email=f"inv{n:06d}@university.example")
    d.update(kw)
    return Invigilator.objects.create(**d)


def make_run(n=1, **kw):
    return SchedulerRun.objects.create(run_id=make_id("run", n), **kw)


def make_assignment(exam, room, run, **kw):
    d = dict(assignment_id=make_assignment_id(exam.exam_id, room.room_id, run.run_id), run=run, exam=exam,
             room=room, start_at=dtm(hour=9), end_at=dtm(hour=11), allocated_count=30)
    d.update(kw)
    return ScheduleAssignment.objects.create(**d)


def make_enrollment(n, student, course, **kw):
    d = dict(enrollment_id=make_id("enrollment", n), student=student, course=course, term="2026-FALL",
             effective_from=D)
    d.update(kw)
    return Enrollment.objects.create(**d)


def make_capacity(n, room, cap=50, **kw):
    d = dict(capacity_id=make_id("capacity", n), room=room, exam_capacity=cap, effective_from=D)
    d.update(kw)
    return RoomCapacity.objects.create(**d)


def make_accommodation(n, student, **kw):
    d = dict(accommodation_id=make_id("accommodation", n), student=student,
             accommodation_type="EXTRA_TIME", extra_time_percent=50, effective_from=D)
    d.update(kw)
    return Accommodation.objects.create(**d)
