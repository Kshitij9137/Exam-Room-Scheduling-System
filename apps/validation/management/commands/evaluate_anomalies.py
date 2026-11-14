from django.core.management.base import BaseCommand, CommandError

from apps.scheduling.models import SchedulerRun
from apps.validation.models import ValidationRun
from apps.validation.services.evaluator import (
    evaluate,
    write_evaluation_report,
)


class Command(BaseCommand):
    help = "Evaluate anomaly detection precision, recall, and F1."

    def add_arguments(self, parser):
        parser.add_argument("--validation", default=None)
        parser.add_argument("--run", default=None)

    def handle(self, *args, **options):
        if options["validation"]:
            try:
                validation_run = ValidationRun.objects.select_related(
                    "scheduler_run"
                ).get(pk=options["validation"])
            except ValidationRun.DoesNotExist as error:
                raise CommandError(
                    f"Validation run {options['validation']} was not found."
                ) from error
        elif options["run"]:
            validation_run = (
                ValidationRun.objects.filter(
                    scheduler_run_id=options["run"]
                )
                .select_related("scheduler_run")
                .order_by("-validation_id")
                .first()
            )
            if validation_run is None:
                raise CommandError(
                    f"No validation run exists for {options['run']}."
                )
        else:
            validation_run = (
                ValidationRun.objects.filter(
                    scheduler_run__run_type=SchedulerRun.RunType.ANOMALY_FIXTURE
                )
                .select_related("scheduler_run")
                .order_by("-validation_id")
                .first()
            )
            if validation_run is None:
                raise CommandError(
                    "No anomaly validation exists; run detect_violations first."
                )

        if (
            validation_run.scheduler_run.run_type
            != SchedulerRun.RunType.ANOMALY_FIXTURE
        ):
            raise CommandError("Evaluation requires an ANOMALY_FIXTURE run.")
        try:
            result = evaluate(validation_run)
        except (FileNotFoundError, ValueError) as error:
            raise CommandError(str(error)) from error
        report_path = write_evaluation_report(result)
        self.stdout.write(
            self.style.SUCCESS(
                f"{result['validation_id']} on {result['scheduler_run']}: "
                f"TP={result['tp']} FP={result['fp']} FN={result['fn']} "
                f"precision={result['precision']} recall={result['recall']} "
                f"F1={result['f1']}"
            )
        )
        self.stdout.write(f"  report: {report_path}")
