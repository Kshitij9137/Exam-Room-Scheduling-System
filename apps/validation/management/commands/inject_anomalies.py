from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from apps.scheduling.models import SchedulerRun
from apps.validation.services.anomaly_injector import inject


class Command(BaseCommand):
    help = "Create a separate anomaly fixture from a completed baseline run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--baseline",
            default=None,
            help="Completed baseline run ID; defaults to the latest baseline.",
        )

    def handle(self, *args, **options):
        if options["baseline"]:
            baseline_id = options["baseline"]
        else:
            baseline = (
                SchedulerRun.objects.filter(
                    run_type=SchedulerRun.RunType.BASELINE,
                    status=SchedulerRun.Status.COMPLETED,
                )
                .order_by("-run_id")
                .first()
            )
            if baseline is None:
                raise CommandError(
                    "No completed baseline exists; run run_scheduler first."
                )
            baseline_id = baseline.run_id

        try:
            anomaly_run, labels, selected = inject(baseline_id)
        except (ValueError, OSError, DatabaseError) as error:
            raise CommandError(f"Anomaly injection failed: {error}") from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {anomaly_run.run_id} (ANOMALY_FIXTURE) "
                f"from {baseline_id}."
            )
        )
        self.stdout.write(
            "  exams: "
            + ", ".join(
                f"{key}={exam_id}" for key, exam_id in selected.items()
            )
        )
        self.stdout.write(f"  ground-truth rows: {len(labels)}")
        for label in labels:
            self.stdout.write(
                f"  {label['anomaly_id']} | {label['issue_type']} | "
                f"{label['expected_violation_code']} | "
                f"{label['assignment_id']}"
            )
