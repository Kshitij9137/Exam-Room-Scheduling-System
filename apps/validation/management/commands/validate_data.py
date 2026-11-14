import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.validation.services.data_validator import validate_master_data


class Command(BaseCommand):
    help = "Validate generated master data and write a JSON summary."

    def handle(self, *args, **options):
        summary = validate_master_data()
        output = Path(settings.BASE_DIR) / "data" / "validation_summary.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(summary, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

        if not summary["ok"]:
            self.stderr.write(
                self.style.ERROR(
                    f"FAIL - {summary['failures']} validation failures:"
                )
            )
            for check in summary["checks"]:
                if check["failures"]:
                    self.stderr.write(
                        f"  {check['check']}: {check['failures']}"
                    )
            raise CommandError(
                f"Data validation failed; see {output} for details."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"OK - 0 failures across {len(summary['checks'])} checks."
            )
        )
