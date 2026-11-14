"""End-to-end tests for the documented data and scheduling workflow."""

import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.core.services.data_generator import generate_and_persist
from apps.scheduling.models import SchedulerRun
from apps.scheduling.services.scheduler import run_scheduler
from apps.validation.models import ValidationRun
from apps.validation.services.anomaly_injector import inject
from apps.validation.services.data_validator import validate_master_data
from apps.validation.services.evaluator import evaluate
from apps.validation.services.reproducibility import canonical_checksum
from apps.validation.services.validation_runner import run_all_checks
from generator.config import SEED_DEFAULT


class EndToEndWorkflowTests(TestCase):
    def test_full_workflow_from_generation_to_evaluation_and_export(self):
        with tempfile.TemporaryDirectory(prefix="phase7_e2e_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                stats = generate_and_persist(
                    seed=SEED_DEFAULT,
                    scale="starter",
                )
                self.assertEqual(stats["students"], 200)
                self.assertEqual(stats["exams"], 20)

                data_summary = validate_master_data()
                self.assertTrue(data_summary["ok"], msg=data_summary["checks"])
                self.assertEqual(data_summary["failures"], 0)

                baseline = run_scheduler(seed=SEED_DEFAULT)
                self.assertEqual(
                    baseline.status, SchedulerRun.Status.COMPLETED
                )
                baseline_validation, baseline_scorecard = run_all_checks(baseline)
                self.assertEqual(
                    baseline_validation.status, ValidationRun.Status.PASSED
                )
                self.assertEqual(baseline_scorecard["failures"], 0)

                anomaly_run, ground_truth, selected = inject(baseline.run_id)
                self.assertEqual(len(ground_truth), 7)
                self.assertEqual(len(selected), 7)
                validation_run, scorecard = run_all_checks(anomaly_run)
                self.assertEqual(
                    validation_run.status, ValidationRun.Status.FAILED_CHECKS
                )
                self.assertEqual(scorecard["failures"], 7)

                result = evaluate(validation_run)
                self.assertEqual(result["tp"], 7)
                self.assertEqual(result["fp"], 0)
                self.assertEqual(result["fn"], 0)
                self.assertEqual(result["precision"], 1.0)
                self.assertEqual(result["recall"], 1.0)
                self.assertEqual(result["f1"], 1.0)

                baseline.refresh_from_db()
                self.assertEqual(
                    baseline.status, SchedulerRun.Status.COMPLETED
                )
                _recheck, baseline_recheck = run_all_checks(baseline)
                self.assertEqual(baseline_recheck["failures"], 0)

                export_dir = Path(folder) / "data" / "exports"
                call_command("export_data", out=str(export_dir), verbosity=0)
                self.assertTrue((export_dir / "manifest.json").exists())
                self.assertTrue((export_dir / "csv" / "students.csv").exists())
                self.assertTrue((export_dir / "json" / "exams.json").exists())
                self.assertTrue((export_dir / "sql" / "seed.sql").exists())


class ReproducibilityCommandTests(TestCase):
    def test_command_reports_matching_checksums_without_changing_database(self):
        with tempfile.TemporaryDirectory(prefix="phase7_repro_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                from io import StringIO

                checksum_before = canonical_checksum()
                output = StringIO()
                call_command(
                    "verify_reproducibility",
                    seed=SEED_DEFAULT,
                    scale="starter",
                    stdout=output,
                )
                self.assertIn("Reproducible", output.getvalue())
                self.assertEqual(canonical_checksum(), checksum_before)
                report_path = (
                    Path(folder) / "data" / "reproducibility_report.json"
                )
                self.assertTrue(report_path.exists())
