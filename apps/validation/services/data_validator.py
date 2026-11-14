"""Independent data-quality checks over persisted generated records."""

import re

from django.db.models import Count, F, Q, Sum

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
from apps.core.services.id_generator import is_valid
from apps.scheduling.models import Availability, RoomClosure, TimeSlot
from generator.config import TERM


_ID_FIELDS = (
    (Student, "student"),
    (Course, "course"),
    (Enrollment, "enrollment"),
    (Exam, "exam"),
    (ExamRequirement, "requirement"),
    (Room, "room"),
    (RoomCapacity, "capacity"),
    (Invigilator, "invigilator"),
    (Accommodation, "accommodation"),
    (Availability, "availability"),
    (RoomClosure, "closure"),
    (TimeSlot, "slot"),
)


def _check(checks, name, failures):
    checks.append({"check": name, "failures": int(failures)})


def _invalid_choice_count(model, field_name, allowed_values):
    return model.objects.exclude(
        **{f"{field_name}__in": allowed_values}
    ).count()


def _invalid_ids(model, kind):
    field_name = model._meta.pk.name
    return sum(
        not is_valid(kind, value)
        for value in model.objects.values_list(field_name, flat=True)
    )


def _duplicate_group_count(model, fields):
    primary_key = model._meta.pk.name
    return (
        model.objects.values(*fields)
        .annotate(row_count=Count(primary_key))
        .filter(row_count__gt=1)
        .count()
    )


def _orphan_foreign_key_count(model, field_name, parent_model, parent_field=None):
    parent_field = parent_field or parent_model._meta.pk.name
    valid_parent_ids = parent_model.objects.values_list(parent_field, flat=True)
    return model.objects.exclude(
        **{f"{field_name}__in": valid_parent_ids}
    ).count()


def _overlapping_capacity_ranges():
    ranges = {}
    for room_id, start, end in RoomCapacity.objects.order_by(
        "room_id", "effective_from"
    ).values_list("room_id", "effective_from", "effective_to"):
        ranges.setdefault(room_id, []).append((start, end))

    overlaps = 0
    for room_ranges in ranges.values():
        latest_end = None
        has_open_end = False
        for start, end in room_ranges:
            if has_open_end or (latest_end is not None and start <= latest_end):
                overlaps += 1
            if end is None:
                has_open_end = True
            elif latest_end is None or end > latest_end:
                latest_end = end
    return overlaps


def validate_master_data():
    checks = []
    counts = {
        "students": Student.objects.count(),
        "courses": Course.objects.count(),
        "exams": Exam.objects.count(),
        "rooms": Room.objects.count(),
        "invigilators": Invigilator.objects.count(),
        "enrollments": Enrollment.objects.count(),
        "active_enrollments": Enrollment.objects.filter(
            status=Enrollment.Status.ACTIVE, term=TERM
        ).count(),
        "accommodations": Accommodation.objects.count(),
        "room_capacities": RoomCapacity.objects.count(),
        "availability": Availability.objects.count(),
        "room_closures": RoomClosure.objects.count(),
        "timeslots": TimeSlot.objects.count(),
        "equipment": Equipment.objects.count(),
        "room_equipment": RoomEquipment.objects.count(),
        "exam_requirement_equipment": ExamRequirementEquipment.objects.count(),
    }

    orphan_foreign_keys = (
        _orphan_foreign_key_count(Enrollment, "student_id", Student)
        + _orphan_foreign_key_count(Enrollment, "course_id", Course)
        + _orphan_foreign_key_count(Exam, "course_id", Course)
        + _orphan_foreign_key_count(
            ExamRequirement, "exam_id", Exam
        )
        + _orphan_foreign_key_count(
            RoomCapacity, "room_id", Room
        )
        + _orphan_foreign_key_count(
            RoomEquipment, "room_id", Room
        )
        + _orphan_foreign_key_count(
            RoomEquipment, "equipment_id", Equipment, "code"
        )
        + _orphan_foreign_key_count(
            ExamRequirementEquipment,
            "requirement_id",
            ExamRequirement,
        )
        + _orphan_foreign_key_count(
            ExamRequirementEquipment, "equipment_id", Equipment, "code"
        )
        + _orphan_foreign_key_count(
            Accommodation, "student_id", Student
        )
        + _orphan_foreign_key_count(
            RoomClosure, "room_id", Room
        )
        + Availability.objects.filter(room_id__isnull=False)
        .exclude(room_id__in=Room.objects.values_list("room_id", flat=True))
        .count()
        + Availability.objects.filter(invigilator_id__isnull=False)
        .exclude(
            invigilator_id__in=Invigilator.objects.values_list(
                "invigilator_id", flat=True
            )
        )
        .count()
    )
    _check(checks, "invalid_foreign_keys", orphan_foreign_keys)

    _check(
        checks,
        "exams_have_course",
        Exam.objects.filter(course__isnull=True).count(),
    )
    _check(
        checks,
        "exams_have_requirement",
        Exam.objects.filter(requirement__isnull=True).count(),
    )
    _check(
        checks,
        "rooms_have_capacity",
        Room.objects.filter(capacities__isnull=True).count(),
    )
    _check(
        checks,
        "accommodations_have_student",
        Accommodation.objects.filter(student__isnull=True).count(),
    )

    _check(
        checks,
        "duplicate_enrollments",
        _duplicate_group_count(
            Enrollment, ["student_id", "course_id", "term"]
        ),
    )
    primary_key_models = (
        Student,
        Course,
        Enrollment,
        Exam,
        ExamRequirement,
        Room,
        RoomCapacity,
        Invigilator,
        Accommodation,
        Availability,
        RoomClosure,
        TimeSlot,
        Equipment,
    )
    _check(
        checks,
        "duplicate_primary_keys",
        sum(
            _duplicate_group_count(model, [model._meta.pk.name])
            for model in primary_key_models
        ),
    )
    _check(
        checks,
        "duplicate_exam_per_course",
        _duplicate_group_count(Exam, ["course_id", "term"]),
    )
    _check(
        checks,
        "duplicate_student_email",
        _duplicate_group_count(Student, ["email"]),
    )
    _check(
        checks,
        "duplicate_invigilator_email",
        _duplicate_group_count(Invigilator, ["email"]),
    )
    _check(
        checks,
        "duplicate_course_code",
        _duplicate_group_count(Course, ["course_code"]),
    )
    _check(
        checks,
        "duplicate_room_building_number",
        _duplicate_group_count(Room, ["building", "room_number"]),
    )
    _check(
        checks,
        "duplicate_timeslot",
        _duplicate_group_count(TimeSlot, ["slot_date", "start_time"]),
    )
    _check(
        checks,
        "duplicate_room_equipment",
        _duplicate_group_count(RoomEquipment, ["room_id", "equipment_id"]),
    )
    _check(
        checks,
        "duplicate_requirement_equipment",
        _duplicate_group_count(
            ExamRequirementEquipment, ["requirement_id", "equipment_id"]
        ),
    )

    exam_course_ids = Exam.objects.values_list("course_id", flat=True)
    _check(
        checks,
        "enrollments_point_to_courses_with_exam",
        Enrollment.objects.exclude(course_id__in=exam_course_ids).count(),
    )
    _check(
        checks,
        "active_enrollment_student_is_active",
        Enrollment.objects.filter(
            status=Enrollment.Status.ACTIVE
        ).exclude(student__status=Student.Status.ACTIVE).count(),
    )
    _check(
        checks,
        "student_course_load_4_to_6",
        Enrollment.objects.filter(
            status=Enrollment.Status.ACTIVE, term=TERM
        )
        .values("student_id")
        .annotate(course_count=Count("enrollment_id"))
        .exclude(course_count__gte=4, course_count__lte=6)
        .count()
        + Student.objects.exclude(
            student_id__in=Enrollment.objects.filter(
                status=Enrollment.Status.ACTIVE, term=TERM
            ).values("student_id")
        ).count(),
    )

    _check(
        checks,
        "capacity_out_of_range",
        RoomCapacity.objects.exclude(
            exam_capacity__gte=10, exam_capacity__lte=500
        ).count(),
    )
    _check(
        checks,
        "room_capacity_dates_ordered",
        RoomCapacity.objects.filter(
            effective_to__lt=F("effective_from")
        ).count(),
    )
    _check(
        checks,
        "room_capacity_ranges_overlap",
        _overlapping_capacity_ranges(),
    )
    _check(
        checks,
        "enrollment_dates_ordered",
        Enrollment.objects.filter(
            effective_to__lt=F("effective_from")
        ).count(),
    )
    _check(
        checks,
        "accommodation_dates_ordered",
        Accommodation.objects.filter(
            effective_to__lt=F("effective_from")
        ).count(),
    )
    _check(
        checks,
        "availability_dates_ordered",
        Availability.objects.filter(end_at__lte=F("start_at")).count(),
    )
    _check(
        checks,
        "room_closure_dates_ordered",
        RoomClosure.objects.filter(end_at__lte=F("start_at")).count(),
    )
    _check(
        checks,
        "accommodation_percent_matches_type",
        Accommodation.objects.filter(
            Q(
                accommodation_type=Accommodation.Type.EXTRA_TIME,
            )
            & ~Q(extra_time_percent__in=[25, 50, 100])
            | (
                ~Q(accommodation_type=Accommodation.Type.EXTRA_TIME)
                & ~Q(extra_time_percent=0)
            )
        ).count(),
    )
    _check(
        checks,
        "availability_has_exactly_one_target",
        Availability.objects.filter(
            Q(room__isnull=False, invigilator__isnull=False)
            | Q(room__isnull=True, invigilator__isnull=True)
        ).count(),
    )

    _check(
        checks,
        "exam_duration_invalid",
        Exam.objects.exclude(duration_minutes__in=[60, 90, 120, 180]).count(),
    )
    _check(
        checks,
        "exam_id_year_mismatch",
        sum(
            exam_id[5:9] != term[:4]
            for exam_id, term in Exam.objects.values_list("exam_id", "term")
        ),
    )
    _check(
        checks,
        "invalid_course_code",
        sum(
            re.fullmatch(r"[A-Z]{2,4}\d{3}", code) is None
            for code in Course.objects.values_list("course_code", flat=True)
        ),
    )
    _check(
        checks,
        "invalid_equipment_code",
        sum(
            re.fullmatch(r"[A-Z_]+", code) is None
            for code in Equipment.objects.values_list("code", flat=True)
        ),
    )

    _check(
        checks,
        "invalid_generated_ids",
        sum(_invalid_ids(model, kind) for model, kind in _ID_FIELDS),
    )

    enum_specs = (
        (Student, "department", [value for value, _ in Student._meta.get_field("department").choices]),
        (Student, "status", [value for value, _ in Student.Status.choices]),
        (Course, "department", [value for value, _ in Course._meta.get_field("department").choices]),
        (Enrollment, "status", [value for value, _ in Enrollment.Status.choices]),
        (Exam, "status", [value for value, _ in Exam.Status.choices]),
        (Room, "room_type", [value for value, _ in Room.RoomType.choices]),
        (Room, "status", [value for value, _ in Room.Status.choices]),
        (Invigilator, "status", [value for value, _ in Invigilator.Status.choices]),
        (
            Accommodation,
            "accommodation_type",
            [value for value, _ in Accommodation.Type.choices],
        ),
        (
            Accommodation,
            "status",
            [value for value, _ in Accommodation.Status.choices],
        ),
        (RoomClosure, "reason", [value for value, _ in RoomClosure.Reason.choices]),
    )
    invalid_enums = sum(
        _invalid_choice_count(model, field_name, allowed_values)
        for model, field_name, allowed_values in enum_specs
    )
    _check(checks, "invalid_enum_values", invalid_enums)
    _check(
        checks,
        "invalid_exam_requirement_ratio",
        ExamRequirement.objects.exclude(
            invigilator_ratio__gte=20, invigilator_ratio__lte=100
        ).count(),
    )
    _check(
        checks,
        "invalid_course_credits",
        Course.objects.exclude(credits__gte=1, credits__lte=6).count(),
    )
    _check(
        checks,
        "invalid_student_year_level",
        Student.objects.exclude(year_level__gte=1, year_level__lte=4).count(),
    )
    _check(
        checks,
        "invalid_invigilator_daily_hours",
        Invigilator.objects.exclude(
            max_daily_hours__gte=1, max_daily_hours__lte=10
        ).count(),
    )
    _check(
        checks,
        "invalid_term_format",
        sum(
            re.fullmatch(r"\d{4}-(FALL|SPRING)", term) is None
            for term in Enrollment.objects.values_list("term", flat=True)
        )
        + sum(
            re.fullmatch(r"\d{4}-(FALL|SPRING)", term) is None
            for term in Exam.objects.values_list("term", flat=True)
        ),
    )

    active_enrollment_rows = Enrollment.objects.filter(
        status=Enrollment.Status.ACTIVE, term=TERM
    ).count()
    reconciled_enrollment_rows = (
        Course.objects.filter(exams__term=TERM)
        .annotate(
            active_count=Count(
                "enrollments",
                filter=Q(
                    enrollments__status=Enrollment.Status.ACTIVE,
                    enrollments__term=TERM,
                ),
            )
        )
        .aggregate(total=Sum("active_count"))["total"]
        or 0
    )
    _check(
        checks,
        "active_enrollment_reconciliation",
        abs(active_enrollment_rows - reconciled_enrollment_rows),
    )

    failures = sum(check["failures"] for check in checks)
    return {
        "counts": counts,
        "checks": checks,
        "failures": failures,
        "ok": failures == 0,
    }
