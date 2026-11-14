"""Compare persisted violation detections with run-scoped ground truth."""

import csv
import json
from pathlib import Path

from django.conf import settings

from apps.validation.models import DetectedViolation

GROUND_TRUTH_FIELDS = {
    "anomaly_id",
    "issue_type",
    "assignment_id",
    "affected_entity_id",
    "expected_violation_code",
    "run_id",
}


def load_ground_truth(run_id=None):
    path = Path(settings.BASE_DIR) / "data" / "ground_truth.csv"
    if not path.exists():
        raise FileNotFoundError(f"Ground-truth file does not exist: {path}")
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or not GROUND_TRUTH_FIELDS.issubset(
            reader.fieldnames
        ):
            raise ValueError("Ground-truth CSV is missing required columns.")
        rows = list(reader)
    if run_id is not None:
        rows = [row for row in rows if row["run_id"] == run_id]
        if not rows:
            raise ValueError(
                f"No ground-truth rows are recorded for run {run_id}."
            )
    return rows


def evaluate(validation_run):
    ground_truth = load_ground_truth(
        validation_run.scheduler_run.run_id
    )
    detected = list(
        DetectedViolation.objects.filter(validation_run=validation_run)
        .exclude(assignment__isnull=True)
        .values_list("assignment_id", "violation_code")
    )
    expected_set = {
        (
            row["assignment_id"],
            row["expected_violation_code"],
        )
        for row in ground_truth
    }
    detected_set = set(detected)
    true_positives = expected_set & detected_set
    false_positives = detected_set - expected_set
    false_negatives = expected_set - detected_set

    precision = (
        len(true_positives) / (len(true_positives) + len(false_positives))
        if true_positives or false_positives
        else 0.0
    )
    recall = (
        len(true_positives) / (len(true_positives) + len(false_negatives))
        if true_positives or false_negatives
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "validation_id": validation_run.validation_id,
        "scheduler_run": validation_run.scheduler_run_id,
        "ground_truth_count": len(expected_set),
        "detected_count": len(detected_set),
        "tp": len(true_positives),
        "fp": len(false_positives),
        "fn": len(false_negatives),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": sorted(true_positives),
        "false_positives": sorted(false_positives),
        "false_negatives": sorted(false_negatives),
    }


def write_evaluation_report(result):
    output = Path(settings.BASE_DIR) / "data" / "anomaly_evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return output
