import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.scheduling.models import ScheduleEvent
from apps.validation.services.reproducibility import verify_reproducibility
from generator.config import SCALES, SEED_DEFAULT


class Command(BaseCommand):
    help = (
        "Regenerate twice with a fixed seed and compare checksums. "
        "Database changes are rolled back."
    )

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=SEED_DEFAULT)
        parser.add_argument(
            "--scale", choices=sorted(SCALES), default="starter"
        )

    def handle(self, *args, **options):
        if ScheduleEvent.objects.exists():
            raise CommandError(
                "ScheduleEvent rows exist; reproducibility verification "
                "requires a fresh database."
            )

        result = verify_reproducibility(
            seed=options["seed"],
            scale=options["scale"],
        )
        output = Path(settings.BASE_DIR) / "data" / "reproducibility_report.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )

        if not result["match"]:
            raise CommandError(
                f"Generator is not reproducible; see {output} for details."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Reproducible: {result['checksum_run_1']}"
            )
        )
