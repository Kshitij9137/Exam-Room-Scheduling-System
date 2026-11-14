from django.contrib import admin

from apps.scheduling.admin import ReadOnlyAdmin
from .models import DetectedViolation, ValidationRun


class ViolationInline(admin.TabularInline):
    model = DetectedViolation
    extra = 0
    can_delete = False
    readonly_fields = ("violation_code", "assignment", "entity_id", "detail")


@admin.register(ValidationRun)
class ValidationRunAdmin(ReadOnlyAdmin):
    list_display = ("validation_id", "scheduler_run", "status", "checks_performed", "failures", "started_at")
    list_filter = ("status",)
    inlines = [ViolationInline]


@admin.register(DetectedViolation)
class DetectedViolationAdmin(ReadOnlyAdmin):
    list_display = ("violation_id", "validation_run", "violation_code", "assignment", "entity_id")
    list_filter = ("violation_code",)
    search_fields = ("violation_id", "entity_id")
