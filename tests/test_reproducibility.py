from django.test import TestCase

from apps.core.models import Student
from apps.validation.services.reproducibility import (
    canonical_checksum,
    verify_reproducibility,
)
from generator.config import SEED_DEFAULT


class ReproducibilityTests(TestCase):
    def test_same_seed_has_same_checksum_and_row_counts(self):
        result = verify_reproducibility(
            seed=SEED_DEFAULT, scale="starter"
        )
        self.assertTrue(result["match"])
        self.assertEqual(result["checksum_run_1"], result["checksum_run_2"])
        self.assertEqual(
            result["row_counts_run_1"], result["row_counts_run_2"]
        )

    def test_different_seed_has_different_checksum(self):
        first = verify_reproducibility(
            seed=SEED_DEFAULT, scale="starter"
        )
        second = verify_reproducibility(seed=99999999, scale="starter")
        self.assertNotEqual(
            first["checksum_run_1"], second["checksum_run_1"]
        )

    def test_verification_leaves_existing_database_unchanged(self):
        initial_count = Student.objects.count()
        initial_checksum = canonical_checksum()
        verify_reproducibility(seed=SEED_DEFAULT, scale="starter")
        self.assertEqual(Student.objects.count(), initial_count)
        self.assertEqual(canonical_checksum(), initial_checksum)
