import datetime as dt

from django.test import TestCase

from apps.core.models import Accommodation, Student
from apps.core.services.id_generator import make_id
from apps.scheduling.services.accommodation import (
    accommodations_active_on,
    needs_accessible_room,
    needs_separate_room,
    required_minutes,
)


class AccommodationTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(
            student_id=make_id("student", 1),
            full_name="Test student",
            email="student@example.test",
            department="CS",
            year_level=1,
        )

    def create_accommodation(self, number, **overrides):
        values = {
            "accommodation_id": make_id("accommodation", number),
            "student": self.student,
            "accommodation_type": Accommodation.Type.EXTRA_TIME,
            "extra_time_percent": 25,
            "effective_from": dt.date(2026, 9, 1),
            "effective_to": dt.date(2026, 12, 31),
        }
        values.update(overrides)
        return Accommodation.objects.create(**values)

    def test_required_time_uses_strictest_active_extension(self):
        twenty_five = self.create_accommodation(1)
        fifty = self.create_accommodation(
            2, extra_time_percent=50
        )
        self.assertEqual(required_minutes(120, [twenty_five, fifty]), 180)
        self.assertEqual(required_minutes(120, []), 120)
        self.assertEqual(required_minutes(180, [fifty]), 270)

    def test_effective_dates_and_status_are_honored(self):
        expired = self.create_accommodation(
            1, effective_to=dt.date(2026, 10, 1)
        )
        future = self.create_accommodation(
            2, effective_from=dt.date(2026, 12, 11)
        )
        revoked = self.create_accommodation(
            3, status=Accommodation.Status.REVOKED
        )
        self.assertEqual(
            accommodations_active_on(
                self.student.student_id, dt.date(2026, 12, 10)
            ),
            [],
        )
        self.assertEqual(
            accommodations_active_on(
                self.student.student_id, dt.date(2026, 12, 11)
            ),
            [future],
        )
        self.assertNotIn(expired, [future, revoked])

    def test_room_accommodation_flags(self):
        separate = self.create_accommodation(
            1,
            accommodation_type=Accommodation.Type.SEPARATE_ROOM,
            extra_time_percent=0,
        )
        accessible = self.create_accommodation(
            2,
            accommodation_type=Accommodation.Type.ACCESSIBLE_ROOM,
            extra_time_percent=0,
        )
        self.assertTrue(needs_separate_room([separate]))
        self.assertFalse(needs_accessible_room([separate]))
        self.assertTrue(needs_accessible_room([accessible]))
