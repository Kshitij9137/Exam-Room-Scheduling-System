import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from apps.core.services.data_generator import generate_and_persist
from apps.scheduling.services.scheduler import run_scheduler
from apps.validation.services.metrics import compute_business_metrics
from generator.config import SEED_DEFAULT


class BusinessMetricsTests(TestCase):
    def test_metrics_reconcile_baseline_assignments_and_unassigned_exams(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        run = run_scheduler(seed=SEED_DEFAULT)
        with tempfile.TemporaryDirectory(prefix="phase5_metrics_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                metrics = compute_business_metrics(run)

        self.assertEqual(
            metrics["total_exams"],
            metrics["scheduled_exams"] + metrics["unassigned_exams"],
        )
        self.assertEqual(metrics["term_exam_count"], 20)
        self.assertEqual(metrics["scheduling_coverage"], 0.75)
        self.assertAlmostEqual(metrics["student_allocation_rate"], 1.0)
        self.assertTrue(
            metrics["reconciliation_ok"],
            msg=metrics["reconciliation_errors"],
        )
        for metric in (
            "room_seat_utilization",
            "room_time_utilization",
            "invigilator_utilization",
        ):
            self.assertGreaterEqual(metrics[metric], 0.0)
