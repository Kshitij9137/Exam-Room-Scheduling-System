"""Master-data models: Student, Course, Enrollment, Exam, ExamRequirement,
Equipment, Room, RoomCapacity, Invigilator, Accommodation (+ bridge tables)."""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core.validators import (
    code_validator,
    course_code_validator,
    id_validator,
    term_validator,
    validate_multiple_of_15,
)


class Department(models.TextChoices):
    CS = "CS", "Computer Science"
    EE = "EE", "Electrical Engineering"
    ME = "ME", "Mechanical Engineering"
    CE = "CE", "Civil Engineering"
    BIO = "BIO", "Biology"
    CHEM = "CHEM", "Chemistry"
    MATH = "MATH", "Mathematics"
    PHY = "PHY", "Physics"
    BUS = "BUS", "Business"
    ARTS = "ARTS", "Arts"


class Student(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        GRADUATED = "GRADUATED", "Graduated"

    student_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("student")])
    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    department = models.CharField(max_length=10, choices=Department.choices)
    year_level = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["student_id"]
        constraints = [
            models.CheckConstraint(condition=Q(year_level__gte=1, year_level__lte=4), name="student_year_level_1_4"),
        ]
        indexes = [models.Index(fields=["department"])]

    def __str__(self):
        return self.student_id


class Course(models.Model):
    course_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("course")])
    course_code = models.CharField(
        max_length=12, unique=True,
        validators=[course_code_validator],
    )
    title = models.CharField(max_length=200)
    department = models.CharField(max_length=10, choices=Department.choices)
    credits = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(6)])

    class Meta:
        ordering = ["course_id"]
        constraints = [models.CheckConstraint(condition=Q(credits__gte=1, credits__lte=6), name="course_credits_1_6")]
        indexes = [models.Index(fields=["department"])]

    def __str__(self):
        return f"{self.course_id} {self.course_code}"


class Enrollment(models.Model):
    """Bridge table: Student N:M Course."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DROPPED = "DROPPED", "Dropped"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"
        COMPLETED = "COMPLETED", "Completed"

    enrollment_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("enrollment")])
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="enrollments")
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="enrollments")
    term = models.CharField(max_length=12, validators=[term_validator])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["enrollment_id"]
        constraints = [
            models.UniqueConstraint(fields=["student", "course", "term"], name="uniq_enrollment_student_course_term"),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="enrollment_dates_ordered",
            ),
        ]
        indexes = [models.Index(fields=["course", "status"]), models.Index(fields=["student", "status"])]

    def clean(self):
        if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
            raise ValidationError("effective_to cannot be before effective_from.")
        if self.status == self.Status.ACTIVE and self.student_id:
            student = Student.objects.filter(pk=self.student_id).first()
            if student and student.status != Student.Status.ACTIVE:
                raise ValidationError("Only ACTIVE students can have ACTIVE enrollments.")

    def __str__(self):
        return self.enrollment_id


class Exam(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PLANNED = "PLANNED", "Planned"
        SCHEDULED = "SCHEDULED", "Scheduled"
        UNASSIGNED = "UNASSIGNED", "Unassigned"

    exam_id = models.CharField(primary_key=True, max_length=20, validators=[id_validator("exam")])
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="exams")
    title = models.CharField(max_length=200)
    term = models.CharField(max_length=12, validators=[term_validator])
    duration_minutes = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(30), MaxValueValidator(240), validate_multiple_of_15]
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        ordering = ["exam_id"]
        constraints = [
            models.UniqueConstraint(fields=["course", "term"], name="uniq_exam_course_term"),
            models.CheckConstraint(
                condition=Q(duration_minutes__gte=30, duration_minutes__lte=240), name="exam_duration_30_240"
            ),
        ]
        indexes = [models.Index(fields=["status"])]

    def clean(self):
        if self.exam_id and self.term and self.exam_id[5:9] != self.term[:4]:
            raise ValidationError("Year inside exam_id must match the term year.")

    def __str__(self):
        return self.exam_id


class Equipment(models.Model):
    code = models.CharField(primary_key=True, max_length=30, validators=[code_validator])
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "equipment"

    def __str__(self):
        return self.code


class ExamRequirement(models.Model):
    requirement_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("requirement")])
    exam = models.OneToOneField(Exam, on_delete=models.PROTECT, related_name="requirement")
    equipment = models.ManyToManyField(Equipment, through="ExamRequirementEquipment", blank=True)
    allow_multi_room = models.BooleanField(default=True)
    invigilator_ratio = models.PositiveSmallIntegerField(
        default=50, validators=[MinValueValidator(20), MaxValueValidator(100)]
    )

    class Meta:
        ordering = ["requirement_id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(invigilator_ratio__gte=20, invigilator_ratio__lte=100), name="req_ratio_20_100"
            ),
        ]

    def __str__(self):
        return self.requirement_id


class ExamRequirementEquipment(models.Model):
    requirement = models.ForeignKey(ExamRequirement, on_delete=models.CASCADE)
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["requirement", "equipment"], name="uniq_req_equipment")]


class Room(models.Model):
    class RoomType(models.TextChoices):
        LECTURE_HALL = "LECTURE_HALL", "Lecture hall"
        CLASSROOM = "CLASSROOM", "Classroom"
        COMPUTER_LAB = "COMPUTER_LAB", "Computer lab"
        SCIENCE_LAB = "SCIENCE_LAB", "Science lab"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    room_id = models.CharField(primary_key=True, max_length=11, validators=[id_validator("room")])
    building = models.CharField(max_length=60)
    room_number = models.CharField(max_length=10)
    room_type = models.CharField(max_length=20, choices=RoomType.choices)
    is_accessible = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    equipment = models.ManyToManyField(Equipment, through="RoomEquipment", blank=True)

    class Meta:
        ordering = ["room_id"]
        constraints = [models.UniqueConstraint(fields=["building", "room_number"], name="uniq_room_building_number")]

    def __str__(self):
        return self.room_id


class RoomEquipment(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["room", "equipment"], name="uniq_room_equipment")]


class RoomCapacity(models.Model):
    """Exam seating capacity of a room, with effective dates (1 Room : N RoomCapacity)."""

    capacity_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("capacity")])
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="capacities")
    exam_capacity = models.PositiveSmallIntegerField(validators=[MinValueValidator(10), MaxValueValidator(500)])
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["room", "effective_from"]
        verbose_name_plural = "room capacities"
        constraints = [
            models.CheckConstraint(condition=Q(exam_capacity__gte=10, exam_capacity__lte=500), name="capacity_10_500"),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="capacity_dates_ordered",
            ),
        ]

    def clean(self):
        if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
            raise ValidationError("effective_to cannot be before effective_from.")
        if not self.room_id or not self.effective_from:
            return
        others = RoomCapacity.objects.filter(room_id=self.room_id).exclude(pk=self.pk)
        for other in others:
            a_end_ok = other.effective_to is None or self.effective_from <= other.effective_to
            b_end_ok = self.effective_to is None or other.effective_from <= self.effective_to
            if a_end_ok and b_end_ok:
                raise ValidationError("Capacity date range overlaps another range for this room.")

    def __str__(self):
        return self.capacity_id


class Invigilator(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    invigilator_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("invigilator")])
    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    department = models.CharField(max_length=10, choices=Department.choices, blank=True)
    max_daily_hours = models.DecimalField(
        max_digits=3, decimal_places=1, default=8.0, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["invigilator_id"]
        constraints = [
            models.CheckConstraint(condition=Q(max_daily_hours__gte=1, max_daily_hours__lte=10), name="inv_hours_1_10"),
        ]

    def __str__(self):
        return self.invigilator_id


class Accommodation(models.Model):
    class Type(models.TextChoices):
        EXTRA_TIME = "EXTRA_TIME", "Extra time"
        SEPARATE_ROOM = "SEPARATE_ROOM", "Separate room"
        ACCESSIBLE_ROOM = "ACCESSIBLE_ROOM", "Accessible room"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"

    accommodation_id = models.CharField(primary_key=True, max_length=10, validators=[id_validator("accommodation")])
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="accommodations")
    accommodation_type = models.CharField(max_length=20, choices=Type.choices)
    extra_time_percent = models.PositiveSmallIntegerField(default=0)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ["accommodation_id"]
        constraints = [
            models.CheckConstraint(condition=Q(extra_time_percent__in=[0, 25, 50, 100]), name="acc_percent_allowed"),
            models.CheckConstraint(
                condition=(Q(accommodation_type="EXTRA_TIME", extra_time_percent__gt=0)
                           | (~Q(accommodation_type="EXTRA_TIME") & Q(extra_time_percent=0))),
                name="acc_percent_matches_type",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="acc_dates_ordered",
            ),
        ]
        indexes = [models.Index(fields=["student", "status"])]

    def clean(self):
        if self.accommodation_type == self.Type.EXTRA_TIME and self.extra_time_percent not in (25, 50, 100):
            raise ValidationError("EXTRA_TIME needs extra_time_percent of 25, 50 or 100.")
        if self.accommodation_type != self.Type.EXTRA_TIME and self.extra_time_percent != 0:
            raise ValidationError("extra_time_percent must be 0 unless the type is EXTRA_TIME.")
        if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
            raise ValidationError("effective_to cannot be before effective_from.")

    def __str__(self):
        return self.accommodation_id
