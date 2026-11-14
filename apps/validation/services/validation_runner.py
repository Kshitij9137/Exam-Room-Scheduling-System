"""Persist schedule validation runs and scorecards."""

import json
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.services.id_generator import make_id
from apps.core.services.lifecycle import transition
from apps.scheduling.models import SchedulerRun
from apps.validation.models import DetectedViolation, ValidationRun
from apps.validation.services.metrics import compute_business_metrics
from apps.validation.services.schedule_validator import CHECKS


def _next_id(model, field_name, kind):
    last_id = model.objects.order_by(f"-{field_name}").values_list(
        field_name, flat=True
    ).first()
    number = int(last_id.split("-")[-1]) + 1 if last_id else 1
    return make_id(kind, number)


def run_all_checks(run):
    """Run all independent checks and persist their violations and scorecard."""
    if run.status != SchedulerRun.Status.COMPLETED:
        raise ValueError(
            f"Scheduler run {run.run_id} must be COMPLETED before validation."
        )

    with transaction.atomic():
        validation_run = ValidationRun.objects.create(
            validation_id=_next_id(
                ValidationRun, "validation_id", "validation_run"
            ),
            scheduler_run=run,
            status=ValidationRun.Status.RUNNING,
        )
        violation_number = int(
            DetectedViolation.objects.order_by("-violation_id")
            .values_list("violation_id", flat=True)
            .first()
            .split("-")[-1]
        ) if DetectedViolation.objects.exists() else 0

        scorecard = []
        total_checks = 0
        total_failures = 0
        for check_name, check in CHECKS:
            violations, inspected = check(run)
            total_checks += inspected
            total_failures += len(violations)
            scorecard.append(
                {
                    "check": check_name,
                    "checks_performed": inspected,
                    "failures": len(violations),
                    "status": "PASS" if not violations else "FAIL",
                }
            )
            for violation in violations:
                violation_number += 1
                DetectedViolation.objects.create(
                    violation_id=make_id("violation", violation_number),
                    validation_run=validation_run,
                    violation_code=violation["code"],
                    assignment=violation.get("assignment"),
                    entity_id=violation.get("entity_id", ""),
                    detail=violation.get("detail", ""),
                )

        validation_run.checks_performed = total_checks
        validation_run.failures = total_failures
        validation_run.save(update_fields=["checks_performed", "failures"])
        transition(
            validation_run,
            ValidationRun.Status.PASSED
            if total_failures == 0
            else ValidationRun.Status.FAILED_CHECKS,
        )
        validation_run.finished_at = timezone.now()
        validation_run.save(update_fields=["finished_at"])

        result = {
            "validation_id": validation_run.validation_id,
            "scheduler_run": run.run_id,
            "status": validation_run.status,
            "checks_performed": total_checks,
            "failures": total_failures,
            "checks": scorecard,
            "business_metrics": compute_business_metrics(run),
        }

    output = Path(settings.BASE_DIR) / "data" / "validation_scorecard.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return validation_run, result
