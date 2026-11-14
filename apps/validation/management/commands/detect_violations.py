from django.core.management.base import BaseCommand, CommandError

from apps.scheduling.models import SchedulerRun
from apps.validation.models import DetectedViolation
from apps.validation.services.validation_runner import run_all_checks


class Command(BaseCommand):
    help = "Validate an ANOMALY_FIXTURE run and summarize detected violations."

    def add_arguments(self, parser):
        parser.add_argument("--run", default=None)

    def handle(self, *args, **options):
        run_id = options["run"]
        if run_id:
            try:
                run = SchedulerRun.objects.get(pk=run_id)
            except SchedulerRun.DoesNotExist as error:
                raise CommandError(f"Scheduler run {run_id} was not found.") from error
        else:
            run = (
                SchedulerRun.objects.filter(
                    run_type=SchedulerRun.RunType.ANOMALY_FIXTURE
                )
                .order_by("-run_id")
                .first()
            )
            if run is None:
                raise CommandError(
                    "No ANOMALY_FIXTURE run exists; run inject_anomalies first."
                )
        if run.run_type != SchedulerRun.RunType.ANOMALY_FIXTURE:
            raise CommandError(
                f"{run.run_id} is not an ANOMALY_FIXTURE run."
            )

        try:
            validation_run, result = run_all_checks(run)
        except ValueError as error:
            raise CommandError(str(error)) from error

        counts = {}
        for code in (
            DetectedViolation.objects.filter(
                validation_run=validation_run
            ).values_list("violation_code", flat=True)
        ):
            counts[code] = counts.get(code, 0) + 1
        self.stdout.write(
            self.style.SUCCESS(
                f"{validation_run.validation_id}: validated {run.run_id}"
            )
        )
        for code, count in sorted(counts.items()):
            self.stdout.write(f"  {code}: {count}")
        self.stdout.write(f"  total: {result['failures']} violations")
