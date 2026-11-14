"""Build a weighted exam-conflict graph from active term enrollments."""

from collections import defaultdict

from django.conf import settings

from apps.core.models import Enrollment


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
    exams_by_student = defaultdict(set)

    enrollments = (
        Enrollment.objects.filter(
            status=Enrollment.Status.ACTIVE,
            term=term,
            course_id__in=exam_by_course,
        )
        .order_by("student_id", "course_id")
        .values_list("student_id", "course_id")
        .iterator()
    )
    for student_id, course_id in enrollments:
        exam_id = exam_by_course[course_id]
        students_by_exam[exam_id].add(student_id)
        exams_by_student[student_id].add(exam_id)

    for exam_ids in exams_by_student.values():
        ordered_ids = sorted(exam_ids)
        for index, first in enumerate(ordered_ids):
            for second in ordered_ids[index + 1:]:
                graph.add_edge(first, second)

    return graph, students_by_exam
