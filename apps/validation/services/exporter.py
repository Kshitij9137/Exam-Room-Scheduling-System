"""Canonical CSV, JSON, and SQLite-compatible SQL exports."""

import csv
import hashlib
import json
from pathlib import Path

from apps.core.models import (
    Accommodation,
    Course,
    Enrollment,
    Equipment,
    Exam,
    ExamRequirement,
    ExamRequirementEquipment,
    Invigilator,
    Room,
    RoomCapacity,
    RoomEquipment,
    Student,
)
from apps.scheduling.models import Availability, RoomClosure, TimeSlot


_MODELS = [
    ("equipment", Equipment),
    ("students", Student),
    ("courses", Course),
    ("rooms", Room),
    ("invigilators", Invigilator),
    ("timeslots", TimeSlot),
    ("room_capacities", RoomCapacity),
    ("room_equipment", RoomEquipment),
    ("availability", Availability),
    ("room_closures", RoomClosure),
    ("accommodations", Accommodation),
    ("enrollments", Enrollment),
    ("exams", Exam),
    ("exam_requirements", ExamRequirement),
    ("exam_requirement_equipment", ExamRequirementEquipment),
]


def _field_names(model):
    return [field.attname for field in model._meta.concrete_fields]


def _rows(model):
    return list(
        model.objects.order_by(model._meta.pk.name).values(*_field_names(model))
    )


def export_csv(outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for name, model in _MODELS:
        rows = _rows(model)
        with (outdir / f"{name}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as output:
            writer = csv.DictWriter(output, fieldnames=_field_names(model))
            writer.writeheader()
            writer.writerows(rows)


def export_json(outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for name, model in _MODELS:
        (outdir / f"{name}.json").write_text(
            json.dumps(_rows(model), indent=2, default=str) + "\n",
            encoding="utf-8",
        )


def _quote_identifier(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _sql_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def export_sql(outdir):
    """Write dependency-ordered INSERT statements for SQLite."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    lines = ["-- Synthetic seed data; generated locally, no external data sources."]
    for _name, model in _MODELS:
        table_name = _quote_identifier(model._meta.db_table)
        fields = model._meta.concrete_fields
        columns = ", ".join(_quote_identifier(field.column) for field in fields)
        for row in _rows(model):
            values = ", ".join(_sql_value(row[field.attname]) for field in fields)
            lines.append(f"INSERT INTO {table_name} ({columns}) VALUES ({values});")
    (outdir / "seed.sql").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_export_manifest(outdir, seed, scale):
    outdir = Path(outdir)
    export_files = sorted(
        path for path in outdir.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "README.txt"}
    )
    files = {}
    for path in export_files:
        content = path.read_bytes()
        files[str(path.relative_to(outdir)).replace("\\", "/")] = {
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    manifest = {
        "seed": seed,
        "scale": scale,
        "generator": "generator.config, generator.master_data, generator.enrollments",
        "source": "synthetic generator; no external datasets",
        "record_counts": {
            name: model.objects.count() for name, model in _MODELS
        },
        "files": files,
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (outdir / "README.txt").write_text(
        "Synthetic examination scheduling data exports\n"
        f"Seed: {seed}\n"
        f"Scale: {scale}\n"
        "Source: locally generated synthetic data; no personal or external data.\n"
        "Formats: CSV and JSON files are in their matching subdirectories; "
        "seed.sql contains dependency-ordered SQLite INSERT statements.\n"
        "See manifest.json for row counts and SHA-256 checksums.\n",
        encoding="utf-8",
    )
    return manifest
