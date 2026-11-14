import re

from django.db.models import Count
from django.test import TestCase

from apps.core.models import (
    Accommodation,
    Course,
    Enrollment,
    Exam,
    ExamRequirement,
    Invigilator,
    Room,
    RoomCapacity,
    Student,
)
from apps.core.services.data_generator import (
    clear_generated_data,
    generate_and_persist,
)
from apps.scheduling.models import Availability, ScheduleEvent, SchedulerRun, TimeSlot
from generator.config import SEED_DEFAULT


class GeneratorTests(TestCase):
    def setUp(self):
        self.stats = generate_and_persist(seed=SEED_DEFAULT, scale="starter")

    def test_starter_volumes_and_relationships(self):
        self.assertEqual(self.stats["students"], 200)
        self.assertEqual(self.stats["courses"], 30)
        self.assertEqual(self.stats["exams"], 20)
        self.assertEqual(self.stats["rooms"], 15)
        self.assertEqual(self.stats["invigilators"], 25)
        self.assertEqual(Student.objects.count(), 200)
        self.assertEqual(Course.objects.count(), 30)
        self.assertEqual(Exam.objects.count(), 20)
        self.assertEqual(Room.objects.count(), 15)
        self.assertEqual(Invigilator.objects.count(), 25)
        self.assertEqual(ExamRequirement.objects.count(), 20)
        self.assertEqual(TimeSlot.objects.count(), 40)
        self.assertEqual(RoomCapacity.objects.count(), 15)

    def test_ids_and_unique_course_codes(self):
        self.assertTrue(
            all(re.fullmatch(r"STU-\d{6}", value) for value in
                Student.objects.values_list("student_id", flat=True))
        )
        self.assertTrue(
            all(re.fullmatch(r"CRS-\d{6}", value) for value in
                Course.objects.values_list("course_id", flat=True))
        )
        self.assertTrue(
            all(re.fullmatch(r"EXAM-2026-\d{6}", value) for value in
                Exam.objects.values_list("exam_id", flat=True))
        )
        self.assertEqual(
            Course.objects.values("course_code").distinct().count(),
            Course.objects.count(),
        )
        self.assertEqual(
            Exam.objects.values("course_id").distinct().count(),
            Exam.objects.count(),
        )

    def test_enrollment_loads_are_realistic_and_unique(self):
        loads = (
            Enrollment.objects.values("student_id")
            .annotate(total=Count("enrollment_id"))
        )
        self.assertEqual(loads.count(), Student.objects.count())
        self.assertTrue(all(4 <= row["total"] <= 6 for row in loads))
        self.assertEqual(
            Enrollment.objects.values(
                "student_id", "course_id", "term"
            ).distinct().count(),
            Enrollment.objects.count(),
        )

    def test_generated_domain_values_and_effective_dates(self):
        self.assertTrue(
            all(
                value in [60, 90, 120, 180]
                for value in Exam.objects.values_list(
                    "duration_minutes", flat=True
                )
            )
        )
        self.assertTrue(
            all(
                10 <= value <= 500
                for value in RoomCapacity.objects.values_list(
                    "exam_capacity", flat=True
                )
            )
        )
        self.assertTrue(
            all(
                (row["room_id"] is None) != (row["invigilator_id"] is None)
                for row in Availability.objects.values(
                    "room_id", "invigilator_id"
                )
            )
        )
        self.assertGreater(Availability.objects.count(), 0)
        self.assertGreater(TimeSlot.objects.count(), 0)
        self.assertGreater(Accommodation.objects.count(), 0)
        for accommodation in Accommodation.objects.all():
            if accommodation.accommodation_type == Accommodation.Type.EXTRA_TIME:
                self.assertIn(accommodation.extra_time_percent, [25, 50, 100])
            else:
                self.assertEqual(accommodation.extra_time_percent, 0)

    def test_invalid_scale_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_and_persist(seed=SEED_DEFAULT, scale="unknown")

    def test_clear_refuses_to_delete_append_only_schedule_history(self):
        run = SchedulerRun.objects.create(run_id="RUN-000001")
        ScheduleEvent.objects.create(
            event_id="EVT-000001",
            run=run,
            exam=Exam.objects.first(),
            event_type=ScheduleEvent.EventType.UNASSIGNED,
        )
        with self.assertRaises(RuntimeError):
            clear_generated_data()
        self.assertEqual(Student.objects.count(), 200)
        self.assertEqual(ScheduleEvent.objects.count(), 1)
