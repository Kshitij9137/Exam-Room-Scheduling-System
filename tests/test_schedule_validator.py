import datetime as dt
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from apps.core.models import (
    ExamRequirementEquipment,
    Invigilator,
    RoomEquipment,
)
from apps.core.services.data_generator import generate_and_persist
from apps.scheduling.models import (
    Availability,
    InvigilatorAssignment,
    ScheduleAssignment,
)
from apps.scheduling.services.scheduler import run_scheduler
from apps.validation.models import DetectedViolation, ValidationRun
from apps.validation.services import schedule_validator
from apps.validation.services.validation_runner import run_all_checks
from generator.config import SEED_DEFAULT


class ScheduleValidatorTests(TestCase):
    def test_baseline_schedule_passes_all_independent_checks(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        scheduler_run = run_scheduler(seed=SEED_DEFAULT)
        with tempfile.TemporaryDirectory(prefix="schedule_scorecard_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                validation_run, scorecard = run_all_checks(scheduler_run)

        self.assertEqual(validation_run.status, ValidationRun.Status.PASSED)
        self.assertEqual(scorecard["failures"], 0)
        self.assertEqual(len(scorecard["checks"]), 10)
        self.assertTrue(
            all(check["status"] == "PASS" for check in scorecard["checks"])
        )
        self.assertEqual(
            DetectedViolation.objects.filter(
                validation_run=validation_run
            ).count(),
            0,
        )

    def test_validation_run_is_persisted_with_finish_time(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        scheduler_run = run_scheduler(seed=SEED_DEFAULT)
        before = ValidationRun.objects.count()

        with tempfile.TemporaryDirectory(prefix="schedule_scorecard_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                validation_run, _scorecard = run_all_checks(scheduler_run)

        self.assertEqual(ValidationRun.objects.count(), before + 1)
        self.assertIsNotNone(validation_run.finished_at)

    def test_independent_checks_detect_persisted_row_corruption(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        scheduler_run = run_scheduler(seed=SEED_DEFAULT)
        assignments = list(
            ScheduleAssignment.objects.filter(run=scheduler_run)
            .select_related("exam", "room")
            .order_by("assignment_id")
        )

        equipment_assignment = next(
            assignment
            for assignment in assignments
            if ExamRequirementEquipment.objects.filter(
                requirement__exam_id=assignment.exam_id
            ).exists()
        )
        equipment_id = ExamRequirementEquipment.objects.filter(
            requirement__exam_id=equipment_assignment.exam_id
        ).values_list("equipment_id", flat=True).first()
        RoomEquipment.objects.filter(
            room_id=equipment_assignment.room_id,
            equipment_id=equipment_id,
        ).delete()
        violations, _count = schedule_validator.check_missing_equipment(
            scheduler_run
        )
        self.assertIn(
            equipment_assignment.assignment_id,
            {item["assignment"].assignment_id for item in violations},
        )

        room_assignment = assignments[0]
        Availability.objects.filter(room_id=room_assignment.room_id).delete()
        violations, _count = schedule_validator.check_room_unavailable(
            scheduler_run
        )
        self.assertIn(
            room_assignment.assignment_id,
            {item["assignment"].assignment_id for item in violations},
        )

        allocation_assignment = ScheduleAssignment.objects.get(
            pk=room_assignment.assignment_id
        )
        ScheduleAssignment.objects.filter(
            pk=allocation_assignment.pk
        ).update(allocated_count=allocation_assignment.allocated_count + 1)
        violations, _count = (
            schedule_validator.check_student_allocation_mismatch(
                scheduler_run
            )
        )
        self.assertIn(
            allocation_assignment.assignment_id,
            {item["assignment"].assignment_id for item in violations},
        )

        invalid_end = allocation_assignment.start_at + dt.timedelta(
            minutes=allocation_assignment.exam.duration_minutes - 15
        )
        ScheduleAssignment.objects.filter(
            pk=allocation_assignment.pk
        ).update(end_at=invalid_end)
        violations, _count = schedule_validator.check_invalid_duration(
            scheduler_run
        )
        self.assertIn(
            allocation_assignment.assignment_id,
            {item["assignment"].assignment_id for item in violations},
        )

        room_pair = next(
            (
                (first, second)
                for index, first in enumerate(assignments)
                for second in assignments[index + 1:]
                if first.exam_id != second.exam_id
                and first.room_id != second.room_id
                and not ScheduleAssignment.objects.filter(
                    run=scheduler_run,
                    exam_id=second.exam_id,
                    room_id=first.room_id,
                ).exists()
            ),
            None,
        )
        self.assertIsNotNone(room_pair)
        first, second = room_pair
        ScheduleAssignment.objects.filter(
            pk=second.assignment_id
        ).update(
            room_id=first.room_id,
            start_at=first.start_at,
            end_at=first.end_at,
        )
        violations, _count = schedule_validator.check_room_double_booking(
            scheduler_run
        )
        self.assertIn(
            second.assignment_id,
            {item["assignment"].assignment_id for item in violations},
        )

        inv_assignment = InvigilatorAssignment.objects.filter(
            assignment__run=scheduler_run
        ).select_related("assignment").first()
        unavailable_invigilator = next(
            (
                invigilator
                for invigilator in Invigilator.objects.filter(
                    status=Invigilator.Status.ACTIVE
                )
                if not InvigilatorAssignment.objects.filter(
                    assignment=inv_assignment.assignment,
                    invigilator=invigilator,
                ).exists()
                and not Availability.objects.filter(
                    invigilator=invigilator,
                    start_at__lte=inv_assignment.assignment.start_at,
                    end_at__gte=inv_assignment.assignment.end_at,
                ).exists()
            ),
            None,
        )
        self.assertIsNotNone(unavailable_invigilator)
        InvigilatorAssignment.objects.filter(
            pk=inv_assignment.pk
        ).update(invigilator=unavailable_invigilator)
        violations, _count = (
            schedule_validator.check_invigilator_availability(
                scheduler_run
            )
        )
        self.assertIn(
            inv_assignment.assignment_id,
            {item["assignment"].assignment_id for item in violations},
        )
