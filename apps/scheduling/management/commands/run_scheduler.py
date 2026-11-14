from django.core.management.base import BaseCommand, CommandError

from apps.scheduling.models import (
    ScheduleAssignment,
    SchedulerRun,
    UnassignedExam,
)
from apps.scheduling.services.scheduler import run_scheduler


class Command(BaseCommand):
    help = "Schedule exams and persist a new, traceable SchedulerRun."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int)
        parser.add_argument(
            "--run-type",
            choices=[choice.value for choice in SchedulerRun.RunType],
            default=SchedulerRun.RunType.BASELINE,
        )
        parser.add_argument(
            "--no-reset",
            action="store_true",
            help="Schedule only exams currently in PLANNED status.",
        )

    def handle(self, *args, **options):
        run = run_scheduler(
            seed=options["seed"],
            run_type=options["run_type"],
            reset_exams=not options["no_reset"],
        )
        assignment_count = ScheduleAssignment.objects.filter(run=run).count()
        unassigned_count = UnassignedExam.objects.filter(run=run).count()
        output = (
            f"{run.run_id}: {assignment_count} room assignments, "
            f"{unassigned_count} unassigned "
            f"({run.notes})"
        )
        if run.status != SchedulerRun.Status.COMPLETED:
            raise CommandError(f"Scheduling run failed: {output}")
        self.stdout.write(self.style.SUCCESS(output))
