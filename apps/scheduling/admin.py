from django.contrib import admin

from .models import (
    Availability, InvigilatorAssignment, RoomClosure, ScheduleAssignment, ScheduleEvent,
    SchedulerRun, StudentRoomAllocation, TimeSlot, UnassignedExam,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """History tables: browse only, never edit or delete from the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ("slot_id", "slot_date", "start_time", "label")
    list_filter = ("slot_date",)


@admin.register(RoomClosure)
class RoomClosureAdmin(admin.ModelAdmin):
    list_display = ("closure_id", "room", "start_at", "end_at", "reason")
    list_filter = ("reason",)
    date_hierarchy = "start_at"
    search_fields = ("closure_id", "room__room_id")


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ("availability_id", "room", "invigilator", "start_at", "end_at")
    date_hierarchy = "start_at"
    search_fields = ("availability_id", "room__room_id", "invigilator__invigilator_id")


@admin.register(SchedulerRun)
class SchedulerRunAdmin(admin.ModelAdmin):
    list_display = ("run_id", "run_type", "status", "algorithm_version", "seed", "started_at", "finished_at")
    list_filter = ("run_type", "status")
    readonly_fields = ("started_at", "finished_at")


@admin.register(ScheduleAssignment)
class ScheduleAssignmentAdmin(ReadOnlyAdmin):
    list_display = ("assignment_id", "run", "exam", "room", "start_at", "end_at", "allocated_count", "status")
    list_filter = ("run", "status")
    search_fields = ("assignment_id", "exam__exam_id", "room__room_id")
    date_hierarchy = "start_at"
    list_per_page = 50


@admin.register(StudentRoomAllocation)
class StudentRoomAllocationAdmin(ReadOnlyAdmin):
    list_display = ("allocation_id", "assignment", "student", "required_minutes")
    search_fields = ("allocation_id", "student__student_id", "exam__exam_id")
    list_per_page = 50


@admin.register(InvigilatorAssignment)
class InvigilatorAssignmentAdmin(ReadOnlyAdmin):
    list_display = ("ias_id", "assignment", "invigilator", "role")
    search_fields = ("ias_id", "invigilator__invigilator_id")


@admin.register(UnassignedExam)
class UnassignedExamAdmin(ReadOnlyAdmin):
    list_display = ("unassigned_id", "run", "exam", "primary_reason_code")
    list_filter = ("primary_reason_code", "run")


@admin.register(ScheduleEvent)
class ScheduleEventAdmin(ReadOnlyAdmin):
    list_display = ("event_id", "run", "exam", "event_type", "event_at")
    list_filter = ("event_type", "run")
    date_hierarchy = "event_at"
    search_fields = ("event_id", "exam__exam_id")
