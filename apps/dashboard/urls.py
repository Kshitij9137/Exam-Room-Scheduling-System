from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("schedule/", views.timetable, name="timetable"),
    path("exams/<str:exam_id>/", views.exam_detail_view, name="exam_detail"),
    path("students/", views.student_lookup, name="student_lookup"),
    path("exceptions/", views.exceptions, name="exceptions"),
    path("validation/", views.validation_page, name="validation"),
    path("conflict-graph/", views.conflict_graph, name="conflict_graph"),
    path(
        "actions/run-scheduler/",
        views.action_run_scheduler,
        name="action_run_scheduler",
    ),
    path(
        "actions/validate-data/",
        views.action_validate_data,
        name="action_validate_data",
    ),
    path(
        "actions/validate-schedule/",
        views.action_validate_schedule,
        name="action_validate_schedule",
    ),
    path(
        "actions/inject-anomalies/",
        views.action_inject_anomalies,
        name="action_inject_anomalies",
    ),
    path(
        "actions/detect-violations/",
        views.action_detect_violations,
        name="action_detect_violations",
    ),
    path(
        "actions/evaluate-anomalies/",
        views.action_evaluate_anomalies,
        name="action_evaluate_anomalies",
    ),
    path(
        "actions/export-data/",
        views.action_export_data,
        name="action_export_data",
    ),
]
