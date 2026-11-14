from django.contrib import admin

from .models import (
    Accommodation, Course, Enrollment, Equipment, Exam, ExamRequirement,
    ExamRequirementEquipment, Invigilator, Room, RoomCapacity, RoomEquipment, Student,
)


class RoomCapacityInline(admin.TabularInline):
    model = RoomCapacity
    extra = 0


class RoomEquipmentInline(admin.TabularInline):
    model = RoomEquipment
    extra = 0


class ReqEquipmentInline(admin.TabularInline):
    model = ExamRequirementEquipment
    extra = 0


class AccommodationInline(admin.TabularInline):
    model = Accommodation
    extra = 0


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("student_id", "full_name", "department", "year_level", "status")
    list_filter = ("department", "year_level", "status")
    search_fields = ("student_id", "full_name", "email")
    inlines = [AccommodationInline]
    list_per_page = 50


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("course_id", "course_code", "title", "department", "credits")
    list_filter = ("department",)
    search_fields = ("course_id", "course_code", "title")
    list_per_page = 50


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("enrollment_id", "student", "course", "term", "status", "effective_from", "effective_to")
    list_filter = ("status", "term")
    search_fields = ("enrollment_id", "student__student_id", "course__course_code")
    date_hierarchy = "effective_from"
    raw_id_fields = ("student", "course")
    list_per_page = 50


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("exam_id", "course", "duration_minutes", "term", "status")
    list_filter = ("status", "term", "duration_minutes")
    search_fields = ("exam_id", "title", "course__course_code")
    raw_id_fields = ("course",)


@admin.register(ExamRequirement)
class ExamRequirementAdmin(admin.ModelAdmin):
    list_display = ("requirement_id", "exam", "allow_multi_room", "invigilator_ratio")
    inlines = [ReqEquipmentInline]
    raw_id_fields = ("exam",)


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("room_id", "building", "room_number", "room_type", "is_accessible", "status")
    list_filter = ("room_type", "is_accessible", "status", "building")
    search_fields = ("room_id", "room_number", "building")
    inlines = [RoomCapacityInline, RoomEquipmentInline]


@admin.register(RoomCapacity)
class RoomCapacityAdmin(admin.ModelAdmin):
    list_display = ("capacity_id", "room", "exam_capacity", "effective_from", "effective_to")
    list_filter = ("effective_from",)
    search_fields = ("capacity_id", "room__room_id")


@admin.register(Invigilator)
class InvigilatorAdmin(admin.ModelAdmin):
    list_display = ("invigilator_id", "full_name", "department", "max_daily_hours", "status")
    list_filter = ("department", "status")
    search_fields = ("invigilator_id", "full_name", "email")


@admin.register(Accommodation)
class AccommodationAdmin(admin.ModelAdmin):
    list_display = ("accommodation_id", "student", "accommodation_type", "extra_time_percent",
                    "effective_from", "effective_to", "status")
    list_filter = ("accommodation_type", "status", "extra_time_percent")
    search_fields = ("accommodation_id", "student__student_id")
    date_hierarchy = "effective_from"
    raw_id_fields = ("student",)
