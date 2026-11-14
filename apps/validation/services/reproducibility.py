"""Compare canonical persisted data across isolated generator runs."""

import hashlib
import json

from django.db import transaction

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
from apps.core.services.data_generator import (
    clear_generated_data,
    generate_and_persist,
)
from apps.scheduling.models import Availability, RoomClosure, TimeSlot


_CANONICAL_MODELS = [
    Equipment,
    Student,
    Course,
    Room,
    Invigilator,
    TimeSlot,
    RoomCapacity,
    RoomEquipment,
    Availability,
    RoomClosure,
    Accommodation,
    Enrollment,
    Exam,
    ExamRequirement,
    ExamRequirementEquipment,
]


def canonical_snapshot():
    digest = hashlib.sha256()
    row_counts = {}
    for model in _CANONICAL_MODELS:
        rows = model.objects.order_by(model._meta.pk.name).values()
        row_counts[model._meta.db_table] = rows.count()
        for row in rows.iterator():
            digest.update(
                json.dumps(
                    row,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            digest.update(b"\n")
    return {"row_counts": row_counts, "checksum": digest.hexdigest()}


def canonical_checksum():
    return canonical_snapshot()["checksum"]


def _run_once(seed, scale):
    savepoint_id = transaction.savepoint()
    try:
        clear_generated_data()
        generate_and_persist(seed=seed, scale=scale)
        return canonical_snapshot()
    finally:
        transaction.savepoint_rollback(savepoint_id)


def verify_reproducibility(seed, scale):
    with transaction.atomic():
        first = _run_once(seed, scale)
    with transaction.atomic():
        second = _run_once(seed, scale)
    return {
        "seed": seed,
        "scale": scale,
        "checksum_run_1": first["checksum"],
        "checksum_run_2": second["checksum"],
        "row_counts_run_1": first["row_counts"],
        "row_counts_run_2": second["row_counts"],
        "match": (
            first["checksum"] == second["checksum"]
            and first["row_counts"] == second["row_counts"]
        ),
    }
