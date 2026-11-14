"""Scheduling models: runs, assignments, availability, closures, allocations, events."""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import Exam, Invigilator, Room, Student
from apps.core.services.id_generator import make_assignment_id
from apps.core.validators import id_validator


class TimeSlot(models.Model):
    slot_id = models.CharField(primary_key=True, max_length=11, validators=[id_validator("slot")])
    slot_date = models.DateField()
    start_time = models.TimeField()
    label = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["slot_date", "start_time"]
        constraints = [models.UniqueConstraint(fields=["slot_date", "start_time"], name="uniq_slot_date_time")]

    def __str__(self):
        return self.slot_id


class RoomClosure(models.Model):
    class Reason(models.TextChoices):
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        EVENT = "EVENT", "Event"
        REPAIR = "REPAIR", "Repair"

    closure_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("closure")])
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="closures")
    run = models.ForeignKey(
        "SchedulerRun",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="room_closures",
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    reason = models.CharField(max_length=12, choices=Reason.choices)

    class Meta:
        ordering = ["start_at"]
        constraints = [models.CheckConstraint(condition=Q(end_at__gt=F("start_at")), name="closure_end_after_start")]
        indexes = [models.Index(fields=["room", "start_at", "end_at"])]

    def clean(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError("end_at must be after start_at.")

    def __str__(self):
        return self.closure_id


class Availability(models.Model):
    """Availability window for EITHER a room OR an invigilator (exactly one)."""

    availability_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("availability")])
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.PROTECT, related_name="availabilities")
    invigilator = models.ForeignKey(
        Invigilator, null=True, blank=True, on_delete=models.PROTECT, related_name="availabilities"
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    class Meta:
        ordering = ["start_at"]
        verbose_name_plural = "availabilities"
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=F("start_at")), name="availability_end_after_start"),
            models.CheckConstraint(
                condition=(Q(room__isnull=False, invigilator__isnull=True)
                           | Q(room__isnull=True, invigilator__isnull=False)),
                name="availability_exactly_one_target",
            ),
        ]
        indexes = [
            models.Index(fields=["room", "start_at", "end_at"]),
            models.Index(fields=["invigilator", "start_at", "end_at"]),
        ]

    def clean(self):
        if (self.room_id is None) == (self.invigilator_id is None):
            raise ValidationError("Set exactly one of room or invigilator.")
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError("end_at must be after start_at.")

    def __str__(self):
        return self.availability_id


class SchedulerRun(models.Model):
    class RunType(models.TextChoices):
        BASELINE = "BASELINE", "Baseline"
        ANOMALY_FIXTURE = "ANOMALY_FIXTURE", "Anomaly fixture"

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    run_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("run")])
    run_type = models.CharField(max_length=16, choices=RunType.choices, default=RunType.BASELINE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    algorithm_version = models.CharField(max_length=20, default="1.0")
    seed = models.BigIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["run_id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(finished_at__gte=F("started_at")),
                name="run_finish_after_start",
            ),
        ]

    def __str__(self):
        return self.run_id


class ScheduleAssignment(models.Model):
    """Bridge Exam N:M Room, one row per exam-room-run."""

    class Status(models.TextChoices):
        ASSIGNED = "ASSIGNED", "Assigned"
        SUPERSEDED = "SUPERSEDED", "Superseded"
        CANCELLED = "CANCELLED", "Cancelled"

    assignment_id = models.CharField(primary_key=True, max_length=64, validators=[id_validator("assignment")])
    run = models.ForeignKey(SchedulerRun, on_delete=models.PROTECT, related_name="assignments")
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="assignments")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="assignments")
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    allocated_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ASSIGNED)

    class Meta:
        ordering = ["assignment_id"]
        constraints = [
            models.UniqueConstraint(fields=["run", "exam", "room"], name="uniq_assignment_run_exam_room"),
            models.CheckConstraint(condition=Q(end_at__gt=F("start_at")), name="assignment_end_after_start"),
            models.CheckConstraint(condition=Q(allocated_count__gte=1), name="assignment_count_positive"),
        ]
        indexes = [
            models.Index(fields=["room", "start_at", "end_at"]),
            models.Index(fields=["run", "exam"]),
            models.Index(fields=["status"]),
        ]

    def clean(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError("end_at must be after start_at.")
        if self.exam_id and self.room_id and self.run_id:
            expected = make_assignment_id(self.exam_id, self.room_id, self.run_id)
            if self.assignment_id != expected:
                raise ValidationError(f"assignment_id must be {expected}.")

    def __str__(self):
        return self.assignment_id


class StudentRoomAllocation(models.Model):
    """Which student sits in which room. run and exam are stored too, so the database
    itself guarantees one student is never placed in two rooms for the same exam."""

    allocation_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("student_allocation")])
    assignment = models.ForeignKey(ScheduleAssignment, on_delete=models.CASCADE, related_name="student_allocations")
    run = models.ForeignKey(SchedulerRun, on_delete=models.PROTECT, related_name="student_allocations")
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="student_allocations")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="room_allocations")
    required_minutes = models.PositiveSmallIntegerField(validators=[MinValueValidator(30)])

    class Meta:
        ordering = ["allocation_id"]
        constraints = [
            models.UniqueConstraint(fields=["assignment", "student"], name="uniq_alloc_assignment_student"),
            models.UniqueConstraint(fields=["run", "exam", "student"], name="uniq_alloc_run_exam_student"),
        ]
        indexes = [models.Index(fields=["student", "run"])]

    def clean(self):
        if self.assignment_id:
            a = ScheduleAssignment.objects.filter(pk=self.assignment_id).first()
            if a and (a.exam_id != self.exam_id or a.run_id != self.run_id):
                raise ValidationError("run and exam must match the assignment.")

    def __str__(self):
        return self.allocation_id


class InvigilatorAssignment(models.Model):
    class Role(models.TextChoices):
        CHIEF = "CHIEF", "Chief"
        ASSISTANT = "ASSISTANT", "Assistant"

    ias_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("invigilator_assignment")])
    assignment = models.ForeignKey(ScheduleAssignment, on_delete=models.CASCADE, related_name="invigilator_assignments")
    invigilator = models.ForeignKey(Invigilator, on_delete=models.PROTECT, related_name="assignments")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.ASSISTANT)

    class Meta:
        ordering = ["ias_id"]
        constraints = [
            models.UniqueConstraint(fields=["assignment", "invigilator"], name="uniq_ias_assignment_invigilator"),
        ]

    def __str__(self):
        return self.ias_id


class UnassignedExam(models.Model):
    class Reason(models.TextChoices):
        NO_CONFLICT_FREE_SLOT = "NO_CONFLICT_FREE_SLOT", "No conflict-free slot"
        NO_ROOM_CAPACITY = "NO_ROOM_CAPACITY", "No room capacity"
        NO_EQUIPMENT_ROOM = "NO_EQUIPMENT_ROOM", "No room with equipment"
        ROOM_UNAVAILABLE = "ROOM_UNAVAILABLE", "Room unavailable"
        NO_INVIGILATOR = "NO_INVIGILATOR", "No invigilator"
        ACCOMMODATION_UNSATISFIABLE = "ACCOMMODATION_UNSATISFIABLE", "Accommodation unsatisfiable"
        NO_FEASIBLE_ASSIGNMENT = "NO_FEASIBLE_ASSIGNMENT", "No feasible assignment"

    unassigned_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("unassigned")])
    run = models.ForeignKey(SchedulerRun, on_delete=models.PROTECT, related_name="unassigned_exams")
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="unassigned_records")
    primary_reason_code = models.CharField(max_length=30, choices=Reason.choices)
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["unassigned_id"]
        constraints = [models.UniqueConstraint(fields=["run", "exam"], name="uniq_unassigned_run_exam")]

    def __str__(self):
        return self.unassigned_id


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("ScheduleEvent rows are append-only.")

    def delete(self):
        raise PermissionError("ScheduleEvent rows are append-only.")


class ScheduleEvent(models.Model):
    """Append-only history. Rows can be created, never changed or deleted."""

    class EventType(models.TextChoices):
        ASSIGNED = "ASSIGNED", "Assigned"
        MOVED = "MOVED", "Moved"
        CANCELLED = "CANCELLED", "Cancelled"
        UNASSIGNED = "UNASSIGNED", "Unassigned"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    event_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("event")])
    run = models.ForeignKey(SchedulerRun, on_delete=models.PROTECT, related_name="events")
    assignment = models.ForeignKey(
        ScheduleAssignment, null=True, blank=True, on_delete=models.PROTECT, related_name="events"
    )
    exam = models.ForeignKey(Exam, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=12, choices=EventType.choices)
    detail = models.JSONField(default=dict, blank=True)
    event_at = models.DateTimeField(default=timezone.now)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["event_id"]
        indexes = [models.Index(fields=["run", "exam"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("ScheduleEvent rows are append-only and cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("ScheduleEvent rows are append-only and cannot be deleted.")

    def __str__(self):
        return self.event_id
