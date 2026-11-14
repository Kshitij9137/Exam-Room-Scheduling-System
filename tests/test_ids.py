from django.test import SimpleTestCase

from apps.core.services.id_generator import is_valid, make_assignment_id, make_exam_id, make_id


class IdGeneratorTests(SimpleTestCase):
    def test_zero_padded_formats(self):
        self.assertEqual(make_id("student", 1), "STU-000001")
        self.assertEqual(make_id("room", 100), "ROOM-000100")
        self.assertEqual(make_id("invigilator", 200), "INV-000200")
        self.assertEqual(make_exam_id(1), "EXAM-2026-000001")

    def test_assignment_id_includes_exam_room_run(self):
        self.assertEqual(
            make_assignment_id("EXAM-2026-000001", "ROOM-000001", "RUN-000001"),
            "ASN-EXAM-2026-000001-ROOM-000001-RUN-000001",
        )

    def test_boundaries(self):
        self.assertEqual(make_id("student", 999999), "STU-999999")
        with self.assertRaises(ValueError):
            make_id("student", 0)
        with self.assertRaises(ValueError):
            make_id("student", 1000000)

    def test_validation_accepts_and_rejects(self):
        self.assertTrue(is_valid("student", "STU-000001"))
        self.assertFalse(is_valid("student", "STU-1"))
        self.assertFalse(is_valid("student", "stu-000001"))
        self.assertFalse(is_valid("student", "STU-0000011"))
        self.assertTrue(is_valid("assignment", "ASN-EXAM-2026-000001-ROOM-000001-RUN-000001"))
        self.assertFalse(is_valid("assignment", "ASN-EXAM-2026-000001-ROOM-000001"))
        self.assertFalse(is_valid("exam", None))

    def test_ids_are_deterministic(self):
        self.assertEqual([make_id("course", i) for i in range(1, 4)], [make_id("course", i) for i in range(1, 4)])
