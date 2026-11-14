"""Dashboard presentation and staff-only workflow actions."""

import json
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from apps.core.models import Exam, Enrollment, Student
from apps.scheduling.models import (
    ScheduleAssignment,
    SchedulerRun,
)
from apps.scheduling.services.scheduler import run_scheduler
from apps.validation.models import ValidationRun
from apps.validation.services.anomaly_injector import inject
from apps.validation.services.data_validator import validate_master_data
from apps.validation.services.evaluator import evaluate, write_evaluation_report
from apps.validation.services.exporter import (
    export_csv,
    export_json,
    export_sql,
    write_export_manifest,
)
from apps.validation.services.validation_runner import run_all_checks

from .forms import TimetableFilterForm
from .permissions import staff_required
from .services import (
    conflict_graph_data,
    dashboard_summary,
    exam_detail,
    exceptions_rows,
    latest_run,
    timetable_rows,
    validation_page_data,
)


def home(request):
    return render(request, "dashboard/dashboard.html", dashboard_summary())


def timetable(request):
    run = latest_run()
    if run is None:
        return render(
            request, "dashboard/no_latest_run.html", {"what": "timetable"}
        )
    form = TimetableFilterForm(request.GET or None)
    filters = {}
    if form.is_valid():
        filters = {
            key: value for key, value in form.cleaned_data.items() if value
        }
    return render(
        request,
        "dashboard/timetable.html",
        {
            "run": run,
            "form": form,
            "grouped": timetable_rows(run, filters),
            "filters": filters,
            "has_filter": bool(filters),
        },
    )


def exam_detail_view(request, exam_id):
    exam = (
        Exam.objects.select_related("course")
        .filter(pk=exam_id)
        .first()
    )
    if exam is None:
        return render(
            request,
            "dashboard/not_found.html",
            {"what": f"exam {exam_id}"},
        )
    return render(
        request, "dashboard/exam_detail.html", exam_detail(exam)
    )


def student_lookup(request):
    query = (request.GET.get("q") or "").strip()
    student = None
    enrollments = []
    assignments = []
    if query:
        student = Student.objects.filter(pk=query).first()
        if student is None:
            student = Student.objects.filter(email__iexact=query).first()
        if student:
            enrollments = list(
                student.enrollments.select_related("course")
                .filter(status=Enrollment.Status.ACTIVE)
                .order_by("course__course_code")
            )
            run = latest_run()
            if run:
                assignments = list(
                    ScheduleAssignment.objects.filter(
                        run=run,
                        status=ScheduleAssignment.Status.ASSIGNED,
                        student_allocations__student=student,
                    )
                    .select_related("exam__course", "room")
                    .prefetch_related("invigilator_assignments__invigilator")
                    .order_by("start_at", "room__room_id")
                    .distinct()
                )
    return render(
        request,
        "dashboard/student_lookup.html",
        {
            "query": query,
            "student": student,
            "enrollments": enrollments,
            "assignments": assignments,
            "run": latest_run() if student else None,
        },
    )


def exceptions(request):
    run = latest_run()
    if run is None:
        return render(
            request, "dashboard/no_latest_run.html", {"what": "exceptions"}
        )
    return render(
        request,
        "dashboard/exceptions.html",
        {"run": run, "rows": exceptions_rows(run)},
    )


def validation_page(request):
    return render(
        request, "dashboard/validation.html", validation_page_data()
    )


def conflict_graph(request):
    return render(
        request, "dashboard/conflict_graph.html", conflict_graph_data()
    )


def _back(request):
    fallback = reverse("dashboard:home")
    candidate = request.POST.get("next") or request.META.get("HTTP_REFERER")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


@staff_required
def action_run_scheduler(request):
    seed_value = (request.POST.get("seed") or "").strip()
    try:
        seed = int(seed_value) if seed_value else None
    except ValueError:
        messages.error(request, "Seed must be an integer.")
        return redirect(_back(request))

    run = run_scheduler(seed=seed)
    if run.status == SchedulerRun.Status.COMPLETED:
        messages.success(
            request, f"Ran scheduler: {run.run_id} — {run.notes}"
        )
    else:
        messages.error(
            request, f"Scheduler run {run.run_id} ended with status {run.status}."
        )
    return redirect(_back(request))


@staff_required
def action_validate_data(request):
    try:
        summary = validate_master_data()
    except OSError as error:
        messages.error(request, f"Could not write validation report: {error}")
        return redirect(_back(request))
    if summary["ok"]:
        messages.success(
            request,
            f"Data validation passed — {len(summary['checks'])} checks, 0 failures.",
        )
    else:
        messages.warning(
            request,
            f"Data validation found {summary['failures']} failures; "
            "see data/validation_summary.json.",
        )
    return redirect(_back(request))


@staff_required
def action_validate_schedule(request):
    run = latest_run()
    if run is None:
        messages.error(request, "No scheduler run to validate.")
        return redirect(_back(request))
    try:
        validation_run, result = run_all_checks(run)
    except (ValueError, OSError, DatabaseError) as error:
        messages.error(request, f"Schedule validation failed: {error}")
        return redirect(_back(request))
    if result["failures"] == 0:
        messages.success(
            request, f"{validation_run.validation_id}: PASS — 0 failures."
        )
    else:
        messages.warning(
            request,
            f"{validation_run.validation_id}: "
            f"{result['failures']} violations recorded.",
        )
    return redirect(_back(request))


@staff_required
def action_inject_anomalies(request):
    baseline = (
        SchedulerRun.objects.filter(
            run_type=SchedulerRun.RunType.BASELINE,
            status=SchedulerRun.Status.COMPLETED,
        )
        .order_by("-run_id")
        .first()
    )
    if baseline is None:
        messages.error(request, "No completed BASELINE run to copy.")
        return redirect(_back(request))
    try:
        anomaly_run, labels, _selected = inject(baseline.run_id)
    except (ValueError, OSError, DatabaseError) as error:
        messages.error(request, f"Anomaly injection failed: {error}")
        return redirect(_back(request))
    messages.success(
        request,
        f"Created {anomaly_run.run_id} with {len(labels)} labelled anomalies.",
    )
    return redirect(_back(request))


@staff_required
def action_detect_violations(request):
    run = (
        SchedulerRun.objects.filter(
            run_type=SchedulerRun.RunType.ANOMALY_FIXTURE
        )
        .order_by("-run_id")
        .first()
    )
    if run is None:
        messages.error(
            request, "No ANOMALY_FIXTURE run exists; inject anomalies first."
        )
        return redirect(_back(request))
    try:
        validation_run, result = run_all_checks(run)
    except (ValueError, OSError, DatabaseError) as error:
        messages.error(request, f"Violation detection failed: {error}")
        return redirect(_back(request))
    messages.success(
        request,
        f"{validation_run.validation_id}: {result['failures']} violations "
        f"on {run.run_id}.",
    )
    return redirect(_back(request))


@staff_required
def action_evaluate_anomalies(request):
    validation_run = (
        ValidationRun.objects.filter(
            scheduler_run__run_type=SchedulerRun.RunType.ANOMALY_FIXTURE
        )
        .select_related("scheduler_run")
        .order_by("-validation_id")
        .first()
    )
    if validation_run is None:
        messages.error(request, "No anomaly validation yet; detect violations first.")
        return redirect(_back(request))
    try:
        result = evaluate(validation_run)
        write_evaluation_report(result)
    except (FileNotFoundError, OSError, ValueError) as error:
        messages.error(request, f"Evaluation failed: {error}")
        return redirect(_back(request))
    messages.success(
        request,
        f"Evaluation: TP={result['tp']} FP={result['fp']} FN={result['fn']} "
        f"P={result['precision']} R={result['recall']} F1={result['f1']}",
    )
    return redirect(_back(request))


@staff_required
def action_export_data(request):
    manifest_path = Path(settings.BASE_DIR) / "data" / "generation_manifest.json"
    seed = None
    scale = "unknown"
    if manifest_path.exists():
        try:
            generation_manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            messages.error(
                request, f"Could not read generation manifest: {error}"
            )
            return redirect(_back(request))
        seed = generation_manifest.get("seed")
        scale = generation_manifest.get("scale", "unknown")

    export_dir = Path(settings.BASE_DIR) / "data" / "exports"
    try:
        export_csv(export_dir / "csv")
        export_json(export_dir / "json")
        export_sql(export_dir / "sql")
        manifest = write_export_manifest(export_dir, seed=seed, scale=scale)
    except OSError as error:
        messages.error(request, f"Export failed: {error}")
        return redirect(_back(request))
    messages.success(
        request,
        f"Exported {len(manifest['files'])} data files to {export_dir}.",
    )
    return redirect(_back(request))
