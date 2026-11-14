from django.core.management.base import BaseCommand, CommandError

from apps.scheduling.models import SchedulerRun
from apps.validation.services.validation_runner import run_all_checks


class Command(BaseCommand):
    help = "Independently validate a completed SchedulerRun."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run",
            default=None,
            help="Scheduler run ID; defaults to the latest run.",
        )

    def handle(self, *args, **options):
        run_id = options["run"]
        if run_id:
            try:
                run = SchedulerRun.objects.get(pk=run_id)
            except SchedulerRun.DoesNotExist as error:
                raise CommandError(f"Scheduler run {run_id} was not found.") from error
        else:
            run = SchedulerRun.objects.order_by("-run_id").first()
            if run is None:
                raise CommandError(
                    "No scheduler run exists; run run_scheduler first."
                )

        try:
            validation_run, result = run_all_checks(run)
        except ValueError as error:
            raise CommandError(str(error)) from error

        if result["failures"]:
            for check in result["checks"]:
                if check["failures"]:
                    self.stderr.write(
                        f"  {check['check']}: {check['failures']} failure(s)"
                    )
            raise CommandError(
                f"{validation_run.validation_id}: FAIL — "
                f"{result['checks_performed']} checks, "
                f"{result['failures']} violations."
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"{validation_run.validation_id}: PASS — "
                f"{result['checks_performed']} checks, 0 violations."
            )
        )
        self.stdout.write(
            f"  Scorecard: data/validation_scorecard.json"
        )
        self.stdout.write(
            f"  Business metrics: {result['business_metrics']}"
        )
