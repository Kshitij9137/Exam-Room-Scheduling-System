import datetime as dt

from django.test import TestCase

from apps.core.models import Course, Exam, Invigilator, Room, Student
from apps.core.services.id_generator import make_exam_id, make_id
from apps.scheduling.models import UnassignedExam
from apps.scheduling.services.context import SchedulingContext
from apps.scheduling.services.invigilator_allocator import allocate_invigilators
from apps.scheduling.services.slot_allocator import buffered_overlap


UTC = dt.timezone.utc


class InvigilatorAllocatorTests(TestCase):
    def setUp(self):
        course = Course.objects.create(
            course_id=make_id("course", 1),
            course_code="CS101",
            title="Course",
            department="CS",
            credits=3,
        )
        self.exam = Exam.objects.create(
            exam_id=make_exam_id(1),
            course=course,
            title="Exam",
            term="2026-FALL",
            duration_minutes=120,
            status=Exam.Status.PLANNED,
        )
        self.room = Room.objects.create(
            room_id=make_id("room", 1),
            building="Block A",
            room_number="A-001",
            room_type=Room.RoomType.CLASSROOM,
        )
        self.student = Student.objects.create(
            student_id=make_id("student", 1),
            full_name="Student",
            email="student@example.test",
            department="CS",
            year_level=1,
        )
        self.invigilator = Invigilator.objects.create(
            invigilator_id=make_id("invigilator", 1),
            full_name="Invigilator",
            email="invigilator@example.test",
            max_daily_hours=2,
        )
        self.start = dt.datetime(2026, 12, 7, 8, tzinfo=UTC)
        self.end = dt.datetime(2026, 12, 7, 10, tzinfo=UTC)

    def context(self, availability, policy=None):
        return SchedulingContext(
            run=type("Run", (), {"run_id": "RUN-000001"})(),
            term="2026-FALL",
            exams=[],
            graph=None,
            students_by_exam={},
            invigilators=[self.invigilator],
            invigilator_avails={
                self.invigilator.invigilator_id: availability
            },
            exam_requirements={},
            policy=policy,
        )

    def test_exact_availability_window_is_sufficient(self):
        context = self.context([(self.start, self.end)])
        assignments, reason = allocate_invigilators(
            context,
            self.exam,
            [(self.room, [self.student])],
            self.start,
            self.end,
        )
        self.assertIsNone(reason)
        self.assertEqual(assignments[0][1], [self.invigilator])

    def test_unavailable_invigilator_has_reason_code(self):
        context = self.context([])
        assignments, reason = allocate_invigilators(
            context,
            self.exam,
            [(self.room, [self.student])],
            self.start,
            self.end,
        )
        self.assertIsNone(assignments)
        self.assertEqual(reason, UnassignedExam.Reason.NO_INVIGILATOR)

    def test_daily_hours_limit_is_respected(self):
        context = self.context([(self.start, self.end)])
        context.invigilator_bookings[self.invigilator.invigilator_id].append(
            (
                dt.datetime(2026, 12, 7, 10, tzinfo=UTC),
                dt.datetime(2026, 12, 7, 11, tzinfo=UTC),
            )
        )
        assignments, reason = allocate_invigilators(
            context,
            self.exam,
            [(self.room, [self.student])],
            self.start,
            self.end,
        )
        self.assertIsNone(assignments)
        self.assertEqual(reason, UnassignedExam.Reason.NO_INVIGILATOR)

    def test_hard_buffer_is_required_between_invigilator_assignments(self):
        candidate_start = dt.datetime(2026, 12, 7, 10, 15, tzinfo=UTC)
        self.assertTrue(
            buffered_overlap(
                self.start,
                self.end,
                candidate_start,
                dt.datetime(2026, 12, 7, 11, tzinfo=UTC),
                30,
            )
        )
        self.assertFalse(
            buffered_overlap(
                self.start,
                self.end,
                candidate_start,
                dt.datetime(2026, 12, 7, 11, tzinfo=UTC),
                15,
            )
        )

    def test_consecutive_hours_limit_is_respected(self):
        candidate_start = self.end
        exact_limit_end = dt.datetime(2026, 12, 7, 12, tzinfo=UTC)
        candidate_end = dt.datetime(2026, 12, 7, 12, 30, tzinfo=UTC)
        self.invigilator.max_daily_hours = 8
        self.invigilator.save(update_fields=["max_daily_hours"])
        exact_limit_context = self.context(
            [(self.start, exact_limit_end)],
            policy={"MAX_CONSECUTIVE_INVIGILATOR_HOURS": 4},
        )
        exact_limit_context.invigilator_bookings[
            self.invigilator.invigilator_id
        ].append((self.start, self.end))
        assignments, reason = allocate_invigilators(
            exact_limit_context,
            self.exam,
            [(self.room, [self.student])],
            candidate_start,
            exact_limit_end,
        )
        self.assertIsNone(reason)
        self.assertEqual(assignments[0][1], [self.invigilator])

        context = self.context(
            [(self.start, candidate_end)],
            policy={"MAX_CONSECUTIVE_INVIGILATOR_HOURS": 4},
        )
        context.invigilator_bookings[self.invigilator.invigilator_id].append(
            (self.start, self.end)
        )

        assignments, reason = allocate_invigilators(
            context,
            self.exam,
            [(self.room, [self.student])],
            candidate_start,
            candidate_end,
        )

        self.assertIsNone(assignments)
        self.assertEqual(reason, UnassignedExam.Reason.NO_INVIGILATOR)
