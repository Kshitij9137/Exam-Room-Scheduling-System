"""Boundary and failure cases for scheduling constraints."""

import datetime as dt
from itertools import count
from unittest.mock import patch

from django.test import TestCase

from apps.core.models import (
    Course,
    Enrollment,
    Exam,
    ExamRequirement,
    Invigilator,
    Room,
    RoomCapacity,
    Student,
)
from apps.core.services.id_generator import make_exam_id, make_id
from apps.scheduling.models import (
    Availability,
    InvigilatorAssignment,
    RoomClosure,
    ScheduleAssignment,
    SchedulerRun,
    StudentRoomAllocation,
    TimeSlot,
    UnassignedExam,
)
from apps.scheduling.services.scheduler import run_scheduler
from apps.scheduling.services.slot_allocator import overlap
from generator.config import TERM

UTC = dt.timezone.utc
EXAM_START = dt.datetime(2026, 12, 7, 8, tzinfo=UTC)
EXAM_END = dt.datetime(2026, 12, 18, 20, tzinfo=UTC)


class MinimalSchedulerFixture(TestCase):
    """Create a small, isolated scheduling scenario."""

    def build(
        self,
        *,
        students,
        room_capacity,
        allow_multi_room=False,
        invigilators=1,
        exam_minutes=120,
        room_closures=None,
        invigilator_window=None,
    ):
        course = Course.objects.create(
            course_id=make_id("course", 1),
            course_code="CS101",
            title="Course",
            department="CS",
            credits=3,
        )
        exam = Exam.objects.create(
            exam_id=make_exam_id(1),
            course=course,
            title="Exam",
            term=TERM,
            duration_minutes=exam_minutes,
            status=Exam.Status.PLANNED,
        )
        ExamRequirement.objects.create(
            requirement_id=make_id("requirement", 1),
            exam=exam,
            allow_multi_room=allow_multi_room,
            invigilator_ratio=50,
        )
        room = Room.objects.create(
            room_id=make_id("room", 1),
            building="Block A",
            room_number="A-001",
            room_type=Room.RoomType.CLASSROOM,
        )
        RoomCapacity.objects.create(
            capacity_id=make_id("capacity", 1),
            room=room,
            exam_capacity=room_capacity,
            effective_from=dt.date(2026, 9, 1),
        )
        Availability.objects.create(
            availability_id=make_id("availability", 1),
            room=room,
            start_at=EXAM_START,
            end_at=EXAM_END,
        )

        for index, day in enumerate((7, 8), start=1):
            TimeSlot.objects.create(
                slot_id=make_id("slot", index),
                slot_date=dt.date(2026, 12, day),
                start_time=dt.time(8, 0),
                label=f"2026-12-{day:02d} 08:00",
            )

        for index, (start_at, end_at) in enumerate(room_closures or (), start=1):
            RoomClosure.objects.create(
                closure_id=make_id("closure", index),
                room=room,
                start_at=start_at,
                end_at=end_at,
                reason=RoomClosure.Reason.MAINTENANCE,
            )

        for index in range(1, students + 1):
            student = Student.objects.create(
                student_id=make_id("student", index),
                full_name=f"Student {index}",
                email=f"student{index}@university.example",
                department="CS",
                year_level=1,
            )
            Enrollment.objects.create(
                enrollment_id=make_id("enrollment", index),
                student=student,
                course=course,
                term=TERM,
                status=Enrollment.Status.ACTIVE,
                effective_from=dt.date(2026, 9, 1),
            )

        window = invigilator_window or (EXAM_START, EXAM_END)
        for index in range(1, invigilators + 1):
            invigilator = Invigilator.objects.create(
                invigilator_id=make_id("invigilator", index),
                full_name=f"Invigilator {index}",
                email=f"invigilator{index}@university.example",
                max_daily_hours=8,
            )
            Availability.objects.create(
                availability_id=make_id("availability", 100 + index),
                invigilator=invigilator,
                start_at=window[0],
                end_at=window[1],
            )

        return exam, room


class CapacityBoundaryTests(MinimalSchedulerFixture):
    def test_students_equal_capacity_are_scheduled(self):
        exam, _room = self.build(students=10, room_capacity=10)

        run = run_scheduler(seed=None)

        self.assertEqual(run.status, SchedulerRun.Status.COMPLETED)
        exam.refresh_from_db()
        self.assertEqual(exam.status, Exam.Status.SCHEDULED)
        assignments = ScheduleAssignment.objects.filter(run=run, exam=exam)
        self.assertEqual(
            sum(assignment.allocated_count for assignment in assignments), 10
        )

    def test_students_exceed_capacity_by_one_are_unassigned(self):
        exam, _room = self.build(students=11, room_capacity=10)

        run = run_scheduler(seed=None)

        exam.refresh_from_db()
        self.assertEqual(exam.status, Exam.Status.UNASSIGNED)
        record = UnassignedExam.objects.get(run=run, exam=exam)
        self.assertEqual(
            record.primary_reason_code, UnassignedExam.Reason.NO_ROOM_CAPACITY
        )


class IntervalBoundaryTests(TestCase):
    def test_adjacent_intervals_do_not_overlap(self):
        first_start = dt.datetime(2026, 12, 7, 8, tzinfo=UTC)
        first_end = dt.datetime(2026, 12, 7, 10, tzinfo=UTC)
        second_start = first_end
        second_end = dt.datetime(2026, 12, 7, 12, tzinfo=UTC)

        self.assertFalse(overlap(first_start, first_end, second_start, second_end))

    def test_one_minute_overlap_is_detected(self):
        first_start = dt.datetime(2026, 12, 7, 8, tzinfo=UTC)
        first_end = dt.datetime(2026, 12, 7, 10, tzinfo=UTC)
        second_start = dt.datetime(2026, 12, 7, 9, 59, tzinfo=UTC)
        second_end = dt.datetime(2026, 12, 7, 11, tzinfo=UTC)

        self.assertTrue(overlap(first_start, first_end, second_start, second_end))


class RoomClosureBoundaryTests(MinimalSchedulerFixture):
    def test_room_closure_overlapping_slots_forces_unassigned(self):
        exam, _room = self.build(
            students=5,
            room_capacity=50,
            room_closures=[(EXAM_START, EXAM_END)],
        )

        run = run_scheduler(seed=None)

        exam.refresh_from_db()
        self.assertEqual(exam.status, Exam.Status.UNASSIGNED)
        record = UnassignedExam.objects.get(run=run, exam=exam)
        self.assertEqual(
            record.primary_reason_code, UnassignedExam.Reason.ROOM_UNAVAILABLE
        )


class InvigilatorBoundaryTests(MinimalSchedulerFixture):
    def test_exact_availability_window_is_sufficient(self):
        exact_window = (
            dt.datetime(2026, 12, 7, 8, tzinfo=UTC),
            dt.datetime(2026, 12, 7, 10, tzinfo=UTC),
        )
        exam, _room = self.build(
            students=5,
            room_capacity=50,
            invigilator_window=exact_window,
        )

        run = run_scheduler(seed=None)

        exam.refresh_from_db()
        self.assertEqual(exam.status, Exam.Status.SCHEDULED)
        assignment = ScheduleAssignment.objects.get(run=run, exam=exam)
        self.assertGreaterEqual(assignment.start_at, exact_window[0])
        self.assertLessEqual(assignment.end_at, exact_window[1])

    def test_no_invigilator_produces_reason_code(self):
        exam, _room = self.build(
            students=5,
            room_capacity=50,
            invigilators=0,
        )

        run = run_scheduler(seed=None)

        exam.refresh_from_db()
        self.assertEqual(exam.status, Exam.Status.UNASSIGNED)
        record = UnassignedExam.objects.get(run=run, exam=exam)
        self.assertEqual(
            record.primary_reason_code, UnassignedExam.Reason.NO_INVIGILATOR
        )


class FailedTransactionBoundaryTests(MinimalSchedulerFixture):
    def test_failed_persistence_leaves_no_partial_allocations(self):
        first_exam, _room = self.build(students=3, room_capacity=50)

        second_course = Course.objects.create(
            course_id=make_id("course", 2),
            course_code="CS102",
            title="Course 2",
            department="CS",
            credits=3,
        )
        second_exam = Exam.objects.create(
            exam_id=make_exam_id(2),
            course=second_course,
            title="Exam 2",
            term=TERM,
            duration_minutes=120,
            status=Exam.Status.PLANNED,
        )
        ExamRequirement.objects.create(
            requirement_id=make_id("requirement", 2),
            exam=second_exam,
            allow_multi_room=False,
            invigilator_ratio=50,
        )
        second_room = Room.objects.create(
            room_id=make_id("room", 2),
            building="Block B",
            room_number="B-001",
            room_type=Room.RoomType.CLASSROOM,
        )
        RoomCapacity.objects.create(
            capacity_id=make_id("capacity", 2),
            room=second_room,
            exam_capacity=50,
            effective_from=dt.date(2026, 9, 1),
        )
        Availability.objects.create(
            availability_id=make_id("availability", 2),
            room=second_room,
            start_at=EXAM_START,
            end_at=EXAM_END,
        )
        for index in range(4, 6):
            student = Student.objects.create(
                student_id=make_id("student", index),
                full_name=f"Student {index}",
                email=f"student{index}@university.example",
                department="CS",
                year_level=1,
            )
            Enrollment.objects.create(
                enrollment_id=make_id("enrollment", index),
                student=student,
                course=second_course,
                term=TERM,
                status=Enrollment.Status.ACTIVE,
                effective_from=dt.date(2026, 9, 1),
            )

        scheduler_module = __import__(
            "apps.scheduling.services.scheduler", fromlist=["_commit_assignment"]
        )
        original_commit = scheduler_module._commit_assignment
        attempts = count()

        def persist_then_fail_first_commit(*args, **kwargs):
            result = original_commit(*args, **kwargs)
            if next(attempts) == 0:
                raise ValueError("forced persistence failure")
            return result

        with self.assertLogs(
            "apps.scheduling.services.scheduler", level="ERROR"
        ) as captured_logs:
            with patch.object(
                scheduler_module,
                "_commit_assignment",
                side_effect=persist_then_fail_first_commit,
            ):
                run = run_scheduler(seed=None)

        self.assertIn("forced persistence failure", captured_logs.output[0])
        self.assertEqual(run.status, SchedulerRun.Status.FAILED)
        for exam in (first_exam, second_exam):
            assignments = ScheduleAssignment.objects.filter(run=run, exam=exam)
            allocations = StudentRoomAllocation.objects.filter(run=run, exam=exam)
            invigilator_rows = InvigilatorAssignment.objects.filter(
                assignment__run=run,
                assignment__exam=exam,
            )
            exam.refresh_from_db()
            if exam.status == Exam.Status.UNASSIGNED:
                self.assertEqual(assignments.count(), 0)
                self.assertEqual(allocations.count(), 0)
                self.assertEqual(invigilator_rows.count(), 0)
                self.assertTrue(
                    UnassignedExam.objects.filter(run=run, exam=exam).exists()
                )
            else:
                self.assertEqual(exam.status, Exam.Status.SCHEDULED)
                self.assertGreater(assignments.count(), 0)
                self.assertEqual(
                    allocations.count(),
                    sum(item.allocated_count for item in assignments),
                )
