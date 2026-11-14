"""Build a weighted exam-conflict graph from active term enrollments."""

from collections import defaultdict

from django.conf import settings
from django.db.models import Q

from apps.core.models import Enrollment
from apps.scheduling.models import TimeSlot


class ConflictGraph:
    """Exam vertices; edge weights count students enrolled in both exams."""

    def __init__(self, exams=()):
        self.exams = list(exams)
        self.adj = {exam.exam_id: {} for exam in self.exams}
        self.degree = {exam.exam_id: 0 for exam in self.exams}

    def add_edge(self, first, second, weight=1):
        if first == second:
            return
        self.adj.setdefault(first, {})
        self.adj.setdefault(second, {})
        self.adj[first][second] = self.adj[first].get(second, 0) + weight
        self.adj[second][first] = self.adj[second].get(first, 0) + weight
        self.degree[first] = len(self.adj[first])
        self.degree[second] = len(self.adj[second])

    def neighbors(self, exam_id):
        return self.adj.get(exam_id, {})

    def edge_weight(self, first, second):
        return self.adj.get(first, {}).get(second, 0)


def build_conflict_graph(exams, term=None):
    """Return the graph and active student IDs grouped by exam ID."""
    term = term or settings.SCHEDULER_POLICY["TERM"]
    graph = ConflictGraph(exams)
    exam_by_course = {exam.course_id: exam.exam_id for exam in graph.exams}
    students_by_exam = {exam.exam_id: set() for exam in graph.exams}

    window_start = (
        TimeSlot.objects.order_by("slot_date")
        .values_list("slot_date", flat=True)
        .first()
    )
    window_end = (
        TimeSlot.objects.order_by("-slot_date")
        .values_list("slot_date", flat=True)
        .first()
    )

    enrollment_qs = Enrollment.objects.filter(
        status=Enrollment.Status.ACTIVE,
        term=term,
        course_id__in=exam_by_course,
    )
    if window_start and window_end:
        enrollment_qs = enrollment_qs.filter(
            effective_from__lte=window_end,
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=window_start)
        )

    periods_by_student = defaultdict(lambda: defaultdict(list))
    for student_id, course_id, effective_from, effective_to in (
        enrollment_qs.order_by("student_id", "course_id")
        .values_list(
            "student_id", "course_id", "effective_from", "effective_to"
        )
        .iterator()
    ):
        exam_id = exam_by_course[course_id]
        students_by_exam[exam_id].add(student_id)
        periods_by_student[student_id][exam_id].append(
            (effective_from, effective_to)
        )

    for student_id, exam_periods in periods_by_student.items():
        exam_ids = sorted(exam_periods)
        for index, first in enumerate(exam_ids):
            for second in exam_ids[index + 1:]:
                if any(
                    (first_end is None or first_end >= second_start)
                    and (second_end is None or second_end >= first_start)
                    for first_start, first_end in exam_periods[first]
                    for second_start, second_end in exam_periods[second]
                ):
                    graph.add_edge(first, second)

    return graph, students_by_exam
