import csv
import json
import tempfile
from pathlib import Path

from django.test import TestCase

from apps.core.services.data_generator import generate_and_persist
from apps.validation.services.exporter import (
    export_csv,
    export_json,
    export_sql,
    write_export_manifest,
)
from generator.config import SEED_DEFAULT


class ExporterTests(TestCase):
    def test_csv_json_sql_and_manifest_exports(self):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            export_csv(base / "csv")
            export_json(base / "json")
            export_sql(base / "sql")
            manifest = write_export_manifest(
                base, seed=SEED_DEFAULT, scale="starter"
            )

            with (base / "csv" / "students.csv").open(
                newline="", encoding="utf-8"
            ) as source:
                student_rows = list(csv.DictReader(source))
            self.assertEqual(len(student_rows), 200)

            exams = json.loads(
                (base / "json" / "exams.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(exams), 20)
            self.assertIn(
                "exam_requirement_equipment.json",
                [path.name for path in (base / "json").iterdir()],
            )
            self.assertIn("sql/seed.sql", manifest["files"])
            self.assertTrue((base / "README.txt").exists())
            self.assertTrue((base / "manifest.json").exists())
