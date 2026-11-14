import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.core.services.data_generator import generate_and_persist
from apps.scheduling.models import ScheduleAssignment, SchedulerRun
from apps.scheduling.services.scheduler import run_scheduler
from apps.validation.models import DetectedViolation, ValidationRun
from apps.validation.services.anomaly_injector import inject
from apps.validation.services.evaluator import evaluate
from apps.validation.services.validation_runner import run_all_checks
from generator.config import SEED_DEFAULT


class AnomalyPipelineTests(TestCase):
    def test_phase_five_management_commands(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        baseline = run_scheduler(seed=SEED_DEFAULT)
        with tempfile.TemporaryDirectory(prefix="phase5_commands_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                baseline_output = StringIO()
                call_command(
                    "validate_schedule",
                    run=baseline.run_id,
                    stdout=baseline_output,
                )
                self.assertIn("PASS", baseline_output.getvalue())

                injection_output = StringIO()
                call_command(
                    "inject_anomalies",
                    baseline=baseline.run_id,
                    stdout=injection_output,
                )
                self.assertIn("ground-truth rows: 7", injection_output.getvalue())

                detection_output = StringIO()
                call_command("detect_violations", stdout=detection_output)
                self.assertIn("total: 7 violations", detection_output.getvalue())

                evaluation_output = StringIO()
                call_command("evaluate_anomalies", stdout=evaluation_output)
                self.assertIn("TP=7 FP=0 FN=0", evaluation_output.getvalue())
                self.assertTrue(
                    (Path(folder) / "data" / "anomaly_evaluation.json").exists()
                )

    def test_inject_detect_evaluate_and_revalidate_baseline(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        baseline = run_scheduler(seed=SEED_DEFAULT)
        baseline_assignments = list(
            ScheduleAssignment.objects.filter(run=baseline)
            .order_by("assignment_id")
            .values_list("assignment_id", "start_at", "end_at", "room_id")
        )

        with tempfile.TemporaryDirectory(prefix="phase5_outputs_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                anomaly_run, labels, selected = inject(baseline.run_id)
                self.assertEqual(
                    anomaly_run.run_type,
                    SchedulerRun.RunType.ANOMALY_FIXTURE,
                )
                self.assertEqual(len(selected), 7)
                self.assertEqual(len(labels), 7)
                self.assertEqual(
                    {row["issue_type"] for row in labels},
                    {
                        "STUDENT_OVERLAP",
                        "CAPACITY_EXCEEDED",
                        "INVIGILATOR_CLASH",
                        "ACCOMMODATION_BREACH",
                        "ROOM_CLOSED",
                    },
                )
                self.assertEqual(
                    {row["expected_violation_code"] for row in labels},
                    {
                        DetectedViolation.Code.STUDENT_DOUBLE_BOOKING,
                        DetectedViolation.Code.ROOM_CAPACITY_EXCEEDED,
                        DetectedViolation.Code.INVIGILATOR_DOUBLE_BOOKED,
                        DetectedViolation.Code.ACCOMMODATION_VIOLATION,
                        DetectedViolation.Code.ROOM_UNAVAILABLE_VIOLATION,
                    },
                )
                with (Path(folder) / "data" / "ground_truth.json").open(
                    encoding="utf-8"
                ) as file:
                    saved_labels = json.load(file)
                self.assertEqual(len(saved_labels), 7)
                self.assertEqual(
                    {row["run_id"] for row in saved_labels},
                    {anomaly_run.run_id},
                )

                validation_run, scorecard = run_all_checks(anomaly_run)
                self.assertEqual(
                    validation_run.status,
                    ValidationRun.Status.FAILED_CHECKS,
                )
                self.assertEqual(scorecard["failures"], 7)
                result = evaluate(validation_run)

                self.assertEqual(result["tp"], 7, msg=result)
                self.assertEqual(result["fp"], 0, msg=result)
                self.assertEqual(result["fn"], 0, msg=result)
                self.assertEqual(result["precision"], 1.0)
                self.assertEqual(result["recall"], 1.0)
                self.assertEqual(result["f1"], 1.0)
                self.assertTrue(
                    scorecard["business_metrics"]["reconciliation_ok"],
                    msg=scorecard["business_metrics"]["reconciliation_errors"],
                )

                baseline_validation, baseline_scorecard = run_all_checks(
                    baseline
                )

        self.assertEqual(baseline_scorecard["failures"], 0)
        self.assertEqual(
            baseline_validation.status, ValidationRun.Status.PASSED
        )
        self.assertEqual(
            list(
                ScheduleAssignment.objects.filter(run=baseline)
                .order_by("assignment_id")
                .values_list(
                    "assignment_id", "start_at", "end_at", "room_id"
                )
            ),
            baseline_assignments,
        )

    def test_inject_rejects_non_baseline_run(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        baseline = run_scheduler(seed=SEED_DEFAULT)
        with tempfile.TemporaryDirectory(prefix="phase5_outputs_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                anomaly, _labels, _selected = inject(baseline.run_id)

                with self.assertRaisesRegex(ValueError, "not a BASELINE"):
                    inject(anomaly.run_id)

    def test_evaluator_requires_run_scoped_ground_truth(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        baseline = run_scheduler(seed=SEED_DEFAULT)
        with tempfile.TemporaryDirectory(prefix="phase5_outputs_") as folder:
            with override_settings(BASE_DIR=Path(folder)):
                validation_run, _scorecard = run_all_checks(baseline)
                with self.assertRaises(FileNotFoundError):
                    evaluate(validation_run)
