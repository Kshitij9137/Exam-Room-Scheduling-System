import datetime as dt
from collections import defaultdict

from django.db.models import Count, Q
from django.test import TestCase

from apps.core.models import (
    Accommodation,
    Enrollment,
    Exam,
    ExamRequirementEquipment,
    RoomCapacity,
    RoomEquipment,
)
from apps.core.services.data_generator import generate_and_persist
from apps.scheduling.models import (
    Availability,
    InvigilatorAssignment,
    RoomClosure,
    ScheduleAssignment,
    ScheduleEvent,
    SchedulerRun,
    StudentRoomAllocation,
    UnassignedExam,
)
from apps.scheduling.services.scheduler import run_scheduler
from generator.config import SEED_DEFAULT, TERM


class SchedulerTests(TestCase):
    def setUp(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")

    def test_run_schedules_exams_and_persists_allocation_rows(self):
        run = run_scheduler(seed=SEED_DEFAULT)
        self.assertEqual(run.status, SchedulerRun.Status.COMPLETED)
        statuses = set(
            Exam.objects.filter(term=TERM).values_list("status", flat=True)
        )
        self.assertLessEqual(
            statuses,
            {Exam.Status.SCHEDULED, Exam.Status.UNASSIGNED, Exam.Status.NOT_REQUIRED},
        )
        self.assertEqual(
            Exam.objects.filter(
                term=TERM,
                status__in=[
                    Exam.Status.SCHEDULED,
                    Exam.Status.UNASSIGNED,
                    Exam.Status.NOT_REQUIRED,
                ],
            ).count(),
            Exam.objects.filter(term=TERM).count(),
        )
        self.assertGreater(ScheduleAssignment.objects.filter(run=run).count(), 0)
        self.assertGreater(
            StudentRoomAllocation.objects.filter(run=run).count(), 0
        )
        self.assertGreater(
            InvigilatorAssignment.objects.filter(
                assignment__run=run
            ).count(),
            0,
        )
        self.assertEqual(
            ScheduleEvent.objects.filter(run=run).count(),
            Exam.objects.filter(term=TERM).count(),
        )

    def test_allocations_reconcile_with_active_enrollments(self):
        run = run_scheduler(seed=SEED_DEFAULT)
        allocated = dict(
            StudentRoomAllocation.objects.filter(run=run)
            .values("exam_id")
            .annotate(count=Count("allocation_id"))
            .values_list("exam_id", "count")
        )
        enrolled = dict(
            Enrollment.objects.filter(
                term=TERM, status=Enrollment.Status.ACTIVE
            )
            .values("course__exams__exam_id")
            .annotate(count=Count("enrollment_id"))
            .values_list("course__exams__exam_id", "count")
        )
        scheduled_exam_ids = set(
            Exam.objects.filter(
                term=TERM, status=Exam.Status.SCHEDULED
            ).values_list("exam_id", flat=True)
        )
        unassigned_exam_ids = set(
            UnassignedExam.objects.filter(run=run).values_list(
                "exam_id", flat=True
            )
        )
        self.assertEqual(
            len(scheduled_exam_ids) + len(unassigned_exam_ids),
            Exam.objects.filter(term=TERM).count(),
        )
        self.assertFalse(scheduled_exam_ids & unassigned_exam_ids)
        for exam_id in scheduled_exam_ids:
            self.assertEqual(
                allocated.get(exam_id, 0), enrolled.get(exam_id, 0), msg=exam_id
            )
        self.assertTrue(
            set(allocated).issubset(scheduled_exam_ids),
            "Unassigned exams must not retain partial student allocations.",
        )

    def test_zero_enrollment_exam_is_marked_not_required(self):
        exam = Exam.objects.filter(term=TERM).order_by("exam_id").first()
        Enrollment.objects.filter(
            course=exam.course,
            term=exam.term,
        ).update(status=Enrollment.Status.DROPPED)

        run = run_scheduler(seed=SEED_DEFAULT)
        exam.refresh_from_db()

        self.assertEqual(exam.status, Exam.Status.NOT_REQUIRED)
        self.assertFalse(
            ScheduleAssignment.objects.filter(run=run, exam=exam).exists()
        )
        self.assertFalse(
            StudentRoomAllocation.objects.filter(run=run, exam=exam).exists()
        )
        self.assertFalse(
            UnassignedExam.objects.filter(run=run, exam=exam).exists()
        )
        self.assertTrue(
            ScheduleEvent.objects.filter(
                run=run,
                exam=exam,
                event_type=ScheduleEvent.EventType.NOT_REQUIRED,
            ).exists()
        )

    def test_only_effective_enrollments_are_allocated_on_scheduled_date(self):
        exam = Exam.objects.filter(term=TERM).order_by("exam_id").first()
        start = dt.date(2026, 12, 15)
        end = dt.date(2026, 12, 18)
        Enrollment.objects.filter(
            course=exam.course,
            term=exam.term,
            status=Enrollment.Status.ACTIVE,
        ).update(effective_from=start, effective_to=end)

        run = run_scheduler(seed=SEED_DEFAULT)
        assignment = ScheduleAssignment.objects.filter(
            run=run,
            exam=exam,
        ).first()

        self.assertIsNotNone(assignment)
        self.assertGreaterEqual(assignment.start_at.date(), start)
        self.assertLessEqual(assignment.start_at.date(), end)
        expected_students = set(
            Enrollment.objects.filter(
                course=exam.course,
                term=exam.term,
                status=Enrollment.Status.ACTIVE,
                effective_from__lte=assignment.start_at.date(),
            )
            .filter(
                Q(effective_to__isnull=True)
                | Q(effective_to__gte=assignment.start_at.date())
            )
            .values_list("student_id", flat=True)
        )
        allocated_students = set(
            StudentRoomAllocation.objects.filter(
                run=run,
                exam=exam,
            ).values_list("student_id", flat=True)
        )
        self.assertEqual(allocated_students, expected_students)

    def test_unassigned_rows_always_include_reason_and_evidence(self):
        run = run_scheduler(seed=SEED_DEFAULT)
        for row in UnassignedExam.objects.filter(run=run):
            self.assertIn(
                row.primary_reason_code,
                {choice.value for choice in UnassignedExam.Reason},
            )
            self.assertTrue(row.evidence)

    def test_rerun_preserves_previous_history_and_is_deterministic(self):
        first_run = run_scheduler(seed=SEED_DEFAULT)
        first_assignments = list(
            ScheduleAssignment.objects.filter(run=first_run)
            .order_by("exam_id", "room_id")
            .values_list("exam_id", "room_id", "start_at", "end_at")
        )
        first_events = ScheduleEvent.objects.filter(run=first_run).count()

        second_run = run_scheduler(seed=SEED_DEFAULT)
        second_assignments = list(
            ScheduleAssignment.objects.filter(run=second_run)
            .order_by("exam_id", "room_id")
            .values_list("exam_id", "room_id", "start_at", "end_at")
        )
        self.assertEqual(first_assignments, second_assignments)
        self.assertEqual(
            ScheduleAssignment.objects.filter(run=first_run).count(),
            len(first_assignments),
        )
        self.assertEqual(
            ScheduleEvent.objects.filter(run=first_run).count(), first_events
        )
        self.assertNotEqual(first_run.run_id, second_run.run_id)

    def test_rerun_skips_high_existing_invigilator_assignment_id(self):
        first_run = run_scheduler(seed=SEED_DEFAULT)
        assignment = ScheduleAssignment.objects.filter(
            run=first_run
        ).first()
        invigilator = (
            InvigilatorAssignment.objects.exclude(
                assignment=assignment
            )
            .values_list("invigilator_id", flat=True)
            .first()
        )
        self.assertIsNotNone(invigilator)
        InvigilatorAssignment.objects.create(
            ias_id="IAS-999999",
            assignment=assignment,
            invigilator_id=invigilator,
        )

        second_run = run_scheduler(seed=SEED_DEFAULT)

        self.assertEqual(second_run.status, SchedulerRun.Status.COMPLETED)
        self.assertIn("failed_exam_persistence=0", second_run.notes)
        self.assertGreater(
            ScheduleAssignment.objects.filter(run=second_run).count(),
            0,
        )

    def test_schedule_obeys_room_staff_student_and_accommodation_constraints(self):
        run = run_scheduler(seed=SEED_DEFAULT)
        room_intervals = defaultdict(list)
        staff_intervals = defaultdict(list)
        student_intervals = defaultdict(list)

        for assignment in ScheduleAssignment.objects.filter(run=run):
            room = assignment.room
            start_at, end_at = assignment.start_at, assignment.end_at
            room_intervals[room.room_id].append((start_at, end_at))

            capacity = RoomCapacity.objects.filter(
                room=room,
                effective_from__lte=start_at.date(),
            ).filter(
                Q(effective_to__isnull=True)
                | Q(effective_to__gte=start_at.date())
            ).first()
            self.assertIsNotNone(capacity)
            self.assertLessEqual(
                assignment.allocated_count, capacity.exam_capacity
            )
            self.assertTrue(
                set(
                    ExamRequirementEquipment.objects.filter(
                        requirement__exam=assignment.exam
                    ).values_list("equipment_id", flat=True)
                ).issubset(
                    set(
                        RoomEquipment.objects.filter(room=room).values_list(
                            "equipment_id", flat=True
                        )
                    )
                )
            )
            self.assertTrue(
                Availability.objects.filter(
                    room=room,
                    start_at__lte=start_at,
                    end_at__gte=end_at,
                ).exists()
            )
            self.assertFalse(
                RoomClosure.objects.filter(
                    room=room,
                    start_at__lt=end_at,
                    end_at__gt=start_at,
                ).exists()
            )

            allocations = list(
                StudentRoomAllocation.objects.filter(
                    assignment=assignment
                ).select_related("student")
            )
            self.assertEqual(len(allocations), assignment.allocated_count)
            for allocation in allocations:
                self.assertGreaterEqual(
                    (end_at - start_at).total_seconds() / 60,
                    allocation.required_minutes,
                )
                student_intervals[allocation.student_id].append(
                    (start_at, end_at)
                )

            exam_date = start_at.date()
            accommodations_by_student = {
                allocation.student_id: list(
                    Accommodation.objects.filter(
                        student_id=allocation.student_id,
                        status=Accommodation.Status.ACTIVE,
                        effective_from__lte=exam_date,
                    ).filter(
                        Q(effective_to__isnull=True)
                        | Q(effective_to__gte=exam_date)
                    )
                )
                for allocation in allocations
            }
            if any(
                any(
                    accommodation.accommodation_type
                    == Accommodation.Type.SEPARATE_ROOM
                    for accommodation in student_accommodations
                )
                for student_accommodations in accommodations_by_student.values()
            ):
                self.assertTrue(
                    all(
                        any(
                            accommodation.accommodation_type
                            == Accommodation.Type.SEPARATE_ROOM
                            for accommodation in student_accommodations
                        )
                        for student_accommodations
                        in accommodations_by_student.values()
                    )
                )
            if any(
                any(
                    accommodation.accommodation_type
                    == Accommodation.Type.ACCESSIBLE_ROOM
                    for accommodation in student_accommodations
                )
                for student_accommodations in accommodations_by_student.values()
            ):
                self.assertTrue(room.is_accessible)

            for inv_assignment in InvigilatorAssignment.objects.filter(
                assignment=assignment
            ).select_related("invigilator"):
                self.assertTrue(
                    Availability.objects.filter(
                        invigilator=inv_assignment.invigilator,
                        start_at__lte=start_at,
                        end_at__gte=end_at,
                    ).exists()
                )
                staff_intervals[
                    inv_assignment.invigilator_id
                ].append((start_at, end_at))

        for intervals_by_resource in (
            room_intervals,
            staff_intervals,
            student_intervals,
        ):
            for intervals in intervals_by_resource.values():
                intervals.sort()
                for first, second in zip(intervals, intervals[1:]):
                    self.assertLessEqual(first[1], second[0])

    def test_failed_run_type_is_rejected(self):
        with self.assertRaises(ValueError):
            run_scheduler(run_type="INVALID")
