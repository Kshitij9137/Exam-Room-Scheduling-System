from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.validators import id_validator


class ValidationRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        PASSED = "PASSED", "Passed"
        FAILED_CHECKS = "FAILED_CHECKS", "Failed checks"
        ERROR = "ERROR", "Error"

    validation_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("validation_run")])
    scheduler_run = models.ForeignKey(
        "scheduling.SchedulerRun", on_delete=models.PROTECT, related_name="validation_runs"
    )
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.RUNNING)
    checks_performed = models.PositiveIntegerField(default=0)
    failures = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["validation_id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")),
                name="valrun_finish_after_start",
            ),
        ]

    def __str__(self):
        return self.validation_id


class DetectedViolation(models.Model):
    class Code(models.TextChoices):
        STUDENT_DOUBLE_BOOKING = "STUDENT_DOUBLE_BOOKING", "Student double booking"
        ROOM_CAPACITY_EXCEEDED = "ROOM_CAPACITY_EXCEEDED", "Room capacity exceeded"
        MISSING_EQUIPMENT = "MISSING_EQUIPMENT", "Missing equipment"
        ROOM_DOUBLE_BOOKED = "ROOM_DOUBLE_BOOKED", "Room double booked"
        INVIGILATOR_DOUBLE_BOOKED = "INVIGILATOR_DOUBLE_BOOKED", "Invigilator double booked"
        INVIGILATOR_UNAVAILABLE = "INVIGILATOR_UNAVAILABLE", "Invigilator unavailable"
        INVIGILATOR_DAILY_LIMIT = "INVIGILATOR_DAILY_LIMIT", "Invigilator daily limit exceeded"
        INVIGILATOR_CONSECUTIVE_LIMIT = "INVIGILATOR_CONSECUTIVE_LIMIT", "Invigilator consecutive limit exceeded"
        INACTIVE_ROOM = "INACTIVE_ROOM", "Inactive room assigned"
        INACTIVE_INVIGILATOR = "INACTIVE_INVIGILATOR", "Inactive invigilator assigned"
        ACCOMMODATION_VIOLATION = "ACCOMMODATION_VIOLATION", "Accommodation violation"
        ROOM_UNAVAILABLE_VIOLATION = "ROOM_UNAVAILABLE_VIOLATION", "Room unavailable"
        STUDENT_ALLOCATION_MISMATCH = "STUDENT_ALLOCATION_MISMATCH", "Student allocation mismatch"
        INVALID_DURATION = "INVALID_DURATION", "Invalid duration"

    violation_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("violation")])
    validation_run = models.ForeignKey(ValidationRun, on_delete=models.CASCADE, related_name="violations")
    violation_code = models.CharField(max_length=30, choices=Code.choices)
    assignment = models.ForeignKey(
        "scheduling.ScheduleAssignment", null=True, blank=True, on_delete=models.PROTECT, related_name="violations"
    )
    entity_id = models.CharField(max_length=64, blank=True)
    detail = models.TextField(blank=True)

    class Meta:
        ordering = ["violation_id"]
        indexes = [models.Index(fields=["validation_run", "violation_code"])]

    def __str__(self):
        return self.violation_id
