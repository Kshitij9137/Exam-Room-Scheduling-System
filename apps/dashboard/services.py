"""Read-only aggregation helpers used by dashboard views."""

import json
import logging
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Q

from apps.core.models import (
    Accommodation,
    Course,
    Enrollment,
    Exam,
    ExamRequirementEquipment,
    Invigilator,
    Room,
    Student,
)
from apps.scheduling.models import (
    ScheduleAssignment,
    ScheduleEvent,
    SchedulerRun,
    StudentRoomAllocation,
    UnassignedExam,
)
from apps.scheduling.services.conflict_graph import build_conflict_graph
from apps.validation.models import DetectedViolation, ValidationRun

logger = logging.getLogger(__name__)


def latest_run() -> SchedulerRun | None:
    return SchedulerRun.objects.order_by("-run_id").first()


def latest_completed_run() -> SchedulerRun | None:
    return (
        SchedulerRun.objects.filter(status=SchedulerRun.Status.COMPLETED)
        .order_by("-run_id")
        .first()
    )


def latest_validation(run: SchedulerRun | None = None) -> ValidationRun | None:
    queryset = ValidationRun.objects.order_by("-validation_id")
    if run is not None:
        queryset = queryset.filter(scheduler_run=run)
    return queryset.first()


def load_scorecard() -> dict | None:
    path = Path(settings.BASE_DIR) / "data" / "validation_scorecard.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Could not read dashboard scorecard at %s.", path, exc_info=True)
        return None


def _reason_breakdown(run: SchedulerRun) -> dict[str, int]:
    rows = (
        UnassignedExam.objects.filter(run=run)
        .values("primary_reason_code")
        .annotate(count=Count("unassigned_id"))
    )
    return {row["primary_reason_code"]: row["count"] for row in rows}


def _violation_breakdown(validation_run: ValidationRun | None) -> dict[str, int]:
    if validation_run is None:
        return {}
    rows = (
        DetectedViolation.objects.filter(validation_run=validation_run)
        .values("violation_code")
        .annotate(count=Count("violation_id"))
    )
    return {row["violation_code"]: row["count"] for row in rows}


def dashboard_summary() -> dict:
    counts = {
        "students": Student.objects.count(),
        "courses": Course.objects.count(),
        "exams": Exam.objects.count(),
        "rooms": Room.objects.count(),
        "invigilators": Invigilator.objects.count(),
        "enrollments": Enrollment.objects.count(),
        "accommodations": Accommodation.objects.count(),
    }
    run = latest_run()
    validation = latest_validation(run) if run else None
    scorecard = load_scorecard()
    if scorecard and (
        validation is None
        or scorecard.get("validation_id") != validation.validation_id
    ):
        scorecard = None

    scheduled_exams = (
        ScheduleAssignment.objects.filter(
            run=run, status=ScheduleAssignment.Status.ASSIGNED
        )
        .values("exam_id")
        .distinct()
        .count()
        if run
        else 0
    )
    unassigned_exams = (
        UnassignedExam.objects.filter(run=run).values("exam_id").distinct().count()
        if run
        else 0
    )
    metrics = scorecard.get("business_metrics", {}) if scorecard else {}

    return {
        "counts": counts,
        "latest_run": run,
        "latest_validation": validation,
        "scheduled_exams": scheduled_exams,
        "unassigned_exams": unassigned_exams,
        "unassigned_reasons": _reason_breakdown(run) if run else {},
        "violations_breakdown": _violation_breakdown(validation),
        "scorecard": scorecard,
        "metrics": metrics,
        "hard_violations": validation.failures if validation else None,
    }


def timetable_rows(run: SchedulerRun, filters: dict | None = None) -> dict:
    filters = filters or {}
    queryset = (
        ScheduleAssignment.objects.filter(
            run=run, status=ScheduleAssignment.Status.ASSIGNED
        )
        .select_related("exam__course", "room")
        .prefetch_related(
            "invigilator_assignments__invigilator", "student_allocations"
        )
        .order_by("start_at", "room__room_id")
    )

    if filters.get("date"):
        queryset = queryset.filter(start_at__date=filters["date"])
    if filters.get("exam"):
        queryset = queryset.filter(exam_id=filters["exam"].strip())
    if filters.get("course"):
        code = filters["course"].strip()
        queryset = queryset.filter(
            Q(exam__course_id=code) | Q(exam__course__course_code__iexact=code)
        )
    if filters.get("room"):
        queryset = queryset.filter(room=filters["room"])
    if filters.get("invigilator"):
        queryset = queryset.filter(
            invigilator_assignments__invigilator=filters["invigilator"]
        ).distinct()
    if filters.get("department"):
        queryset = queryset.filter(exam__course__department=filters["department"])

    grouped = defaultdict(list)
    for assignment in queryset:
        grouped[assignment.start_at.date()].append(assignment)
    return dict(sorted(grouped.items()))


def exam_detail(exam: Exam) -> dict:
    run = latest_completed_run()
    context = {
        "exam": exam,
        "run": run,
        "assignments": [],
        "unassigned": None,
        "events": [],
        "required_equipment": list(
            ExamRequirementEquipment.objects.filter(
                requirement__exam__exam_id=exam.exam_id
            )
            .values_list("equipment_id", flat=True)
            .order_by("equipment_id")
        ),
        "active_enrollments": Enrollment.objects.filter(
            course=exam.course,
            term=exam.term,
            status=Enrollment.Status.ACTIVE,
        ).count(),
        "accommodations": [],
        "assigned_students": [],
    }
    if run is None:
        return context

    assignments = list(
        ScheduleAssignment.objects.filter(run=run, exam=exam)
        .select_related("room")
        .prefetch_related(
            "invigilator_assignments__invigilator",
            "student_allocations__student",
        )
        .order_by("assignment_id")
    )
    context["assignments"] = assignments
    context["unassigned"] = UnassignedExam.objects.filter(
        run=run, exam=exam
    ).first()
    context["events"] = list(
        ScheduleEvent.objects.filter(run=run, exam=exam).order_by("event_id")
    )

    if assignments:
        exam_date = assignments[0].start_at.date()
        active_accommodations = Accommodation.objects.filter(
            status=Accommodation.Status.ACTIVE,
            effective_from__lte=exam_date,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=exam_date))
        allocated_ids = set(
            StudentRoomAllocation.objects.filter(assignment__in=assignments)
            .values_list("student_id", flat=True)
        )
        context["accommodations"] = list(
            active_accommodations.filter(student_id__in=allocated_ids).select_related(
                "student"
            )
        )
        context["assigned_students"] = list(
            StudentRoomAllocation.objects.filter(assignment__in=assignments)
            .select_related("student", "assignment")
            .order_by("assignment__room_id", "student_id")
        )
    return context


def exceptions_rows(run: SchedulerRun) -> list[UnassignedExam]:
    return list(
        UnassignedExam.objects.filter(run=run)
        .select_related("exam__course")
        .order_by("exam_id")
    )


def validation_page_data() -> dict:
    validation = latest_validation()
    violations = []
    if validation:
        violations = list(
            DetectedViolation.objects.filter(validation_run=validation)
            .select_related("assignment__exam__course", "assignment__room")
            .order_by("violation_id")
        )
    scorecard = load_scorecard()
    if scorecard and (
        validation is None
        or scorecard.get("validation_id") != validation.validation_id
    ):
        scorecard = None
    return {
        "latest_validation": validation,
        "scorecard": scorecard,
        "violations": violations,
        "history": list(ValidationRun.objects.order_by("-validation_id")[:15]),
    }


def conflict_graph_data(top_n: int = 30) -> dict:
    term = settings.SCHEDULER_POLICY["TERM"]
    exams = list(Exam.objects.filter(term=term).select_related("course"))
    if not exams:
        return {"nodes": [], "edges": [], "term": term}

    graph, students_by_exam = build_conflict_graph(exams, term=term)
    top = sorted(graph.degree.items(), key=lambda item: (-item[1], item[0]))[:top_n]
    selected = {exam_id for exam_id, _degree in top}
    exam_by_id = {exam.exam_id: exam for exam in exams}
    slot_by_exam = {}
    run = latest_run()
    if run:
        for assignment in ScheduleAssignment.objects.filter(
            run=run, exam_id__in=selected
        ).order_by("start_at", "assignment_id"):
            slot_by_exam.setdefault(assignment.exam_id, assignment.start_at.isoformat())

    nodes = []
    for exam_id, degree in top:
        exam = exam_by_id[exam_id]
        nodes.append(
            {
                "id": exam_id,
                "label": exam_id,
                "course": exam.course.course_code,
                "degree": degree,
                "enrollment": len(students_by_exam.get(exam_id, ())),
                "slot": slot_by_exam.get(exam_id, ""),
            }
        )

    edges = []
    for first in sorted(selected):
        for second, weight in graph.neighbors(first).items():
            if second in selected and first < second:
                edges.append({"from": first, "to": second, "value": weight})
    return {"nodes": nodes, "edges": edges, "term": term}
