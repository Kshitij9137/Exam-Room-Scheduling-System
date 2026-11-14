from django.test import TestCase

from apps.core.models import ExamRequirement, Student
from apps.core.services.data_generator import generate_and_persist
from apps.validation.services.data_validator import validate_master_data
from generator.config import SEED_DEFAULT


class DataValidatorTests(TestCase):
    def setUp(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")

    def test_clean_data_passes(self):
        summary = validate_master_data()
        self.assertTrue(summary["ok"], msg=summary["checks"])
        self.assertEqual(summary["failures"], 0)
        self.assertGreater(summary["counts"]["active_enrollments"], 0)

    def test_missing_requirement_is_detected(self):
        ExamRequirement.objects.first().delete()
        summary = validate_master_data()
        self.assertFalse(summary["ok"])
        self.assertGreater(
            next(
                check["failures"]
                for check in summary["checks"]
                if check["check"] == "exams_have_requirement"
            ),
            0,
        )

    def test_invalid_enum_value_is_detected(self):
        Student.objects.filter(student_id="STU-000001").update(status="INVALID")
        summary = validate_master_data()
        self.assertFalse(summary["ok"])
        self.assertGreater(
            next(
                check["failures"]
                for check in summary["checks"]
                if check["check"] == "invalid_enum_values"
            ),
            0,
        )
