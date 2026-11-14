import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.validation.services.exporter import (
    export_csv,
    export_json,
    export_sql,
    write_export_manifest,
)
from generator.config import SCALES


class Command(BaseCommand):
    help = "Export generated data to CSV, JSON, and SQL."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="data/exports")
        parser.add_argument("--seed", type=int)
        parser.add_argument("--scale", choices=sorted(SCALES))

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR) / options["out"]
        generation_manifest_path = (
            Path(settings.BASE_DIR) / "data" / "generation_manifest.json"
        )
        generation_manifest = None
        if generation_manifest_path.exists():
            generation_manifest = json.loads(
                generation_manifest_path.read_text(encoding="utf-8")
            )

        seed = options["seed"]
        scale = options["scale"]
        if generation_manifest:
            seed = seed if seed is not None else generation_manifest["seed"]
            scale = scale if scale is not None else generation_manifest["scale"]
        else:
            scale = scale if scale is not None else "unknown"

        export_csv(base / "csv")
        export_json(base / "json")
        export_sql(base / "sql")
        manifest = write_export_manifest(
            base,
            seed=seed,
            scale=scale,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(manifest['files'])} data files to {base}"
            )
        )
