import datetime as dt

from django.test import TestCase

from apps.core.models import Course, Enrollment, Exam, Student
from apps.core.services.id_generator import make_exam_id, make_id
from apps.scheduling.services.conflict_graph import build_conflict_graph
from apps.scheduling.services.slot_allocator import color_exams
from generator.config import TERM


class ConflictGraphTests(TestCase):
    def setUp(self):
        self.students = [
            Student.objects.create(
                student_id=make_id("student", index),
                full_name=f"Student {index}",
                email=f"student{index}@example.test",
                department="CS",
                year_level=1,
            )
            for index in range(1, 4)
        ]
        self.exams = []
        self.courses = []
        for index in range(1, 4):
            course = Course.objects.create(
                course_id=make_id("course", index),
                course_code=f"CS{100 + index}",
                title=f"Course {index}",
                department="CS",
                credits=3,
            )
            self.courses.append(course)
            self.exams.append(
                Exam.objects.create(
                    exam_id=make_exam_id(index),
                    course=course,
                    title=f"Exam {index}",
                    term=TERM,
                    duration_minutes=120,
                    status=Exam.Status.PLANNED,
                )
            )

    def _enroll(self, index, student, course, *, status="ACTIVE", term=TERM):
        return Enrollment.objects.create(
            enrollment_id=make_id("enrollment", index),
            student=student,
            course=course,
            term=term,
            status=status,
            effective_from=dt.date(2026, 9, 1),
        )

    def test_edge_weights_count_shared_active_students(self):
        self._enroll(1, self.students[0], self.courses[0])
        self._enroll(2, self.students[0], self.courses[1])
        self._enroll(3, self.students[1], self.courses[0])
        self._enroll(4, self.students[1], self.courses[1])
        self._enroll(5, self.students[2], self.courses[0])
        self._enroll(6, self.students[2], self.courses[2])
        graph, students_by_exam = build_conflict_graph(self.exams, TERM)

        self.assertEqual(graph.edge_weight(self.exams[0].exam_id, self.exams[1].exam_id), 2)
        self.assertEqual(graph.edge_weight(self.exams[0].exam_id, self.exams[2].exam_id), 1)
        self.assertEqual(graph.degree[self.exams[0].exam_id], 2)
        self.assertEqual(len(students_by_exam[self.exams[0].exam_id]), 3)

    def test_dropped_and_other_term_enrollments_do_not_create_edges(self):
        self._enroll(
            1, self.students[0], self.courses[0], status=Enrollment.Status.DROPPED
        )
        self._enroll(
            2, self.students[0], self.courses[1], term="2025-FALL"
        )
        graph, students_by_exam = build_conflict_graph(self.exams, TERM)
        self.assertEqual(graph.edge_weight(self.exams[0].exam_id, self.exams[1].exam_id), 0)
        self.assertEqual(students_by_exam[self.exams[0].exam_id], set())

    def test_dsatur_colors_conflicting_exams_into_different_time_groups(self):
        self._enroll(1, self.students[0], self.courses[0])
        self._enroll(2, self.students[0], self.courses[1])
        self._enroll(3, self.students[1], self.courses[0])
        self._enroll(4, self.students[1], self.courses[1])
        self._enroll(5, self.students[2], self.courses[0])
        self._enroll(6, self.students[2], self.courses[2])
        graph, students_by_exam = build_conflict_graph(self.exams, TERM)

        ordered, colors = color_exams(graph, students_by_exam)

        self.assertEqual(len(ordered), len(self.exams))
        for exam_id, neighbors in graph.adj.items():
            for neighbor_id in neighbors:
                self.assertNotEqual(colors[exam_id], colors[neighbor_id])
