import datetime as dt

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.core.models import Accommodation, Enrollment, Exam, Room, RoomCapacity, Student
from apps.core.services.id_generator import make_id
from apps.core.services.lifecycle import InvalidTransition, can_transition, transition
from apps.scheduling.models import (
    Availability, InvigilatorAssignment, RoomClosure, ScheduleAssignment, ScheduleEvent,
    StudentRoomAllocation, UnassignedExam,
)
from apps.validation.models import DetectedViolation, ValidationRun

from .factories import (
    D, dtm, make_accommodation, make_assignment, make_capacity, make_course, make_enrollment,
    make_exam, make_invigilator, make_room, make_run, make_student,
)


class PrimaryKeyTests(TestCase):
    def test_duplicate_primary_key_rejected(self):
        make_student(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_student(1, email="other@university.example")

    def test_bad_id_format_rejected_by_full_clean(self):
        s = Student(student_id="STU-1", full_name="x", email="a@b.example", department="CS", year_level=1)
        with self.assertRaises(ValidationError) as ctx:
            s.full_clean()
        self.assertIn("student_id", ctx.exception.message_dict)

    def test_duplicate_email_rejected(self):
        make_student(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_student(2, email="stu000001@university.example")


class ForeignKeyTests(TestCase):
    def test_enrollment_with_missing_student_fails_validation(self):
        course = make_course(1)
        e = Enrollment(enrollment_id="ENR-000001", student_id="STU-999999", course=course,
                       term="2026-FALL", effective_from=D)
        with self.assertRaises(ValidationError):
            e.full_clean()

    def test_cannot_delete_student_with_enrollment(self):
        s, c = make_student(1), make_course(1)
        make_enrollment(1, s, c)
        with self.assertRaises(ProtectedError):
            s.delete()

    def test_cannot_delete_room_with_assignment(self):
        exam, room, run = make_exam(1), make_room(1), make_run(1)
        make_assignment(exam, room, run)
        with self.assertRaises(ProtectedError):
            room.delete()


class EnrollmentTests(TestCase):
    def test_duplicate_enrollment_rejected(self):
        s, c = make_student(1), make_course(1)
        make_enrollment(1, s, c)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_enrollment(2, s, c)

    def test_same_course_different_term_allowed(self):
        s, c = make_student(1), make_course(1)
        make_enrollment(1, s, c)
        make_enrollment(2, s, c, term="2027-SPRING")
        self.assertEqual(Enrollment.objects.count(), 2)

    def test_end_date_before_start_rejected_by_database(self):
        s, c = make_student(1), make_course(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_enrollment(1, s, c, effective_to=D - dt.timedelta(days=1))

    def test_end_date_equal_start_allowed_boundary(self):
        s, c = make_student(1), make_course(1)
        make_enrollment(1, s, c, effective_to=D)

    def test_inactive_student_cannot_have_active_enrollment(self):
        s, c = make_student(1, status="INACTIVE"), make_course(1)
        e = Enrollment(enrollment_id="ENR-000001", student=s, course=c, term="2026-FALL", effective_from=D)
        with self.assertRaises(ValidationError):
            e.full_clean()


class ExamTests(TestCase):
    def test_duration_boundaries(self):
        for n, minutes in enumerate([30, 240], start=1):
            make_exam(n, duration_minutes=minutes).full_clean()

    def test_invalid_durations_rejected(self):
        for n, minutes in enumerate([0, 29, 241, 100], start=1):
            course = make_course(n)
            exam = Exam(exam_id=f"EXAM-2026-{n:06d}", course=course, title="t", term="2026-FALL",
                        duration_minutes=minutes)
            with self.assertRaises(ValidationError, msg=f"{minutes} should fail"):
                exam.full_clean()

    def test_database_blocks_out_of_range_duration(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_exam(1, duration_minutes=500)

    def test_one_exam_per_course_per_term(self):
        c = make_course(1)
        make_exam(1, course=c)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_exam(2, course=c)

    def test_exam_id_year_must_match_term(self):
        c = make_course(1)
        exam = Exam(exam_id="EXAM-2025-000001", course=c, title="t", term="2026-FALL", duration_minutes=60)
        with self.assertRaises(ValidationError):
            exam.full_clean()


class RoomCapacityTests(TestCase):
    def test_capacity_boundaries(self):
        room = make_room(1)
        for n, cap in enumerate([10, 500], start=1):
            RoomCapacity(capacity_id=f"CAP-{n:06d}", room=make_room(n + 1), exam_capacity=cap,
                         effective_from=D).full_clean()

    def test_invalid_capacity_rejected(self):
        room = make_room(1)
        for cap in (0, 9, 501):
            rc = RoomCapacity(capacity_id="CAP-000001", room=room, exam_capacity=cap, effective_from=D)
            with self.assertRaises(ValidationError, msg=f"{cap} should fail"):
                rc.full_clean()

    def test_overlapping_capacity_ranges_rejected(self):
        room = make_room(1)
        make_capacity(1, room, 50, effective_from=D, effective_to=D + dt.timedelta(days=10))
        overlap = RoomCapacity(capacity_id="CAP-000002", room=room, exam_capacity=60,
                               effective_from=D + dt.timedelta(days=10))
        with self.assertRaises(ValidationError):
            overlap.full_clean()

    def test_adjacent_capacity_ranges_allowed(self):
        room = make_room(1)
        make_capacity(1, room, 50, effective_from=D, effective_to=D + dt.timedelta(days=10))
        ok = RoomCapacity(capacity_id="CAP-000002", room=room, exam_capacity=60,
                          effective_from=D + dt.timedelta(days=11))
        ok.full_clean()


class AvailabilityAndClosureTests(TestCase):
    def test_exactly_one_target_required(self):
        room, inv = make_room(1), make_invigilator(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Availability.objects.create(availability_id="AVL-000001", start_at=dtm(hour=8), end_at=dtm(hour=12))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Availability.objects.create(availability_id="AVL-000002", room=room, invigilator=inv,
                                        start_at=dtm(hour=8), end_at=dtm(hour=12))

    def test_valid_room_and_invigilator_availability(self):
        room, inv = make_room(1), make_invigilator(1)
        Availability.objects.create(availability_id="AVL-000001", room=room, start_at=dtm(hour=8), end_at=dtm(hour=12))
        Availability.objects.create(availability_id="AVL-000002", invigilator=inv, start_at=dtm(hour=8), end_at=dtm(hour=12))
        self.assertEqual(Availability.objects.count(), 2)

    def test_invalid_date_range_rejected(self):
        room = make_room(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Availability.objects.create(availability_id="AVL-000001", room=room, start_at=dtm(hour=12), end_at=dtm(hour=8))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Availability.objects.create(availability_id="AVL-000002", room=room, start_at=dtm(hour=8), end_at=dtm(hour=8))

    def test_closure_end_before_start_rejected(self):
        room = make_room(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoomClosure.objects.create(closure_id="CLS-000001", room=room, start_at=dtm(hour=12),
                                       end_at=dtm(hour=8), reason="REPAIR")


class AccommodationTests(TestCase):
    def test_valid_extra_time_percentages(self):
        s = make_student(1)
        for n, pct in enumerate([25, 50, 100], start=1):
            make_accommodation(n, s, extra_time_percent=pct)
        self.assertEqual(Accommodation.objects.count(), 3)

    def test_invalid_extra_time_percentage_rejected(self):
        s = make_student(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_accommodation(1, s, extra_time_percent=30)

    def test_extra_time_needs_percent(self):
        s = make_student(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_accommodation(1, s, extra_time_percent=0)

    def test_percent_not_allowed_on_room_accommodation(self):
        s = make_student(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_accommodation(1, s, accommodation_type="SEPARATE_ROOM", extra_time_percent=25)
        make_accommodation(2, s, accommodation_type="ACCESSIBLE_ROOM", extra_time_percent=0)

    def test_expiry_before_start_rejected(self):
        s = make_student(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_accommodation(1, s, effective_to=D - dt.timedelta(days=1))


class AssignmentTests(TestCase):
    def setUp(self):
        self.exam, self.room, self.run = make_exam(1), make_room(1), make_run(1)

    def test_assignment_id_must_match_its_parts(self):
        a = ScheduleAssignment(assignment_id="ASN-EXAM-2026-000001-ROOM-000002-RUN-000001", run=self.run,
                               exam=self.exam, room=self.room, start_at=dtm(hour=9), end_at=dtm(hour=11),
                               allocated_count=10)
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_valid_assignment_passes_full_clean(self):
        a = make_assignment(self.exam, self.room, self.run)
        a.full_clean()
        self.assertEqual(a.assignment_id, "ASN-EXAM-2026-000001-ROOM-000001-RUN-000001")

    def test_end_must_be_after_start(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_assignment(self.exam, self.room, self.run, start_at=dtm(hour=11), end_at=dtm(hour=9))

    def test_allocated_count_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_assignment(self.exam, self.room, self.run, allocated_count=0)

    def test_same_exam_room_allowed_in_different_runs_history_kept(self):
        run2 = make_run(2)
        make_assignment(self.exam, self.room, self.run)
        make_assignment(self.exam, self.room, run2)
        self.assertEqual(ScheduleAssignment.objects.count(), 2)

    def test_student_cannot_sit_exam_in_two_rooms_in_same_run(self):
        s = make_student(1)
        room2 = make_room(2)
        a1 = make_assignment(self.exam, self.room, self.run)
        a2 = make_assignment(self.exam, room2, self.run)
        StudentRoomAllocation.objects.create(allocation_id="SRA-000001", assignment=a1, run=self.run,
                                             exam=self.exam, student=s, required_minutes=120)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentRoomAllocation.objects.create(allocation_id="SRA-000002", assignment=a2, run=self.run,
                                                 exam=self.exam, student=s, required_minutes=120)

    def test_allocation_must_match_assignment_exam_and_run(self):
        s = make_student(1)
        other_exam = make_exam(2)
        a = make_assignment(self.exam, self.room, self.run)
        alloc = StudentRoomAllocation(allocation_id="SRA-000001", assignment=a, run=self.run,
                                      exam=other_exam, student=s, required_minutes=120)
        with self.assertRaises(ValidationError):
            alloc.full_clean()

    def test_invigilator_cannot_be_added_twice_to_same_assignment(self):
        inv = make_invigilator(1)
        a = make_assignment(self.exam, self.room, self.run)
        InvigilatorAssignment.objects.create(ias_id="IAS-000001", assignment=a, invigilator=inv)
        with self.assertRaises(IntegrityError), transaction.atomic():
            InvigilatorAssignment.objects.create(ias_id="IAS-000002", assignment=a, invigilator=inv)

    def test_one_unassigned_record_per_exam_per_run(self):
        UnassignedExam.objects.create(unassigned_id="UNA-000001", run=self.run, exam=self.exam,
                                      primary_reason_code="NO_ROOM_CAPACITY")
        with self.assertRaises(IntegrityError), transaction.atomic():
            UnassignedExam.objects.create(unassigned_id="UNA-000002", run=self.run, exam=self.exam,
                                          primary_reason_code="NO_INVIGILATOR")

    def test_invalid_reason_code_rejected_by_full_clean(self):
        u = UnassignedExam(unassigned_id="UNA-000001", run=self.run, exam=self.exam, primary_reason_code="BOGUS")
        with self.assertRaises(ValidationError):
            u.full_clean()


class AppendOnlyEventTests(TestCase):
    def setUp(self):
        self.run, self.exam = make_run(1), make_exam(1)
        self.event = ScheduleEvent.objects.create(event_id="EVT-000001", run=self.run, exam=self.exam,
                                                  event_type="UNASSIGNED", detail={"why": "test"})

    def test_event_cannot_be_modified(self):
        self.event.detail = {"why": "changed"}
        with self.assertRaises(PermissionError):
            self.event.save()

    def test_event_cannot_be_deleted(self):
        with self.assertRaises(PermissionError):
            self.event.delete()

    def test_queryset_update_and_delete_blocked(self):
        with self.assertRaises(PermissionError):
            ScheduleEvent.objects.all().update(event_type="MOVED")
        with self.assertRaises(PermissionError):
            ScheduleEvent.objects.all().delete()
        self.assertEqual(ScheduleEvent.objects.get(pk="EVT-000001").detail, {"why": "test"})

    def test_new_events_can_still_be_appended(self):
        ScheduleEvent.objects.create(event_id="EVT-000002", run=self.run, event_type="ASSIGNED")
        self.assertEqual(ScheduleEvent.objects.count(), 2)


class LifecycleTests(TestCase):
    def test_exam_valid_path(self):
        exam = make_exam(1)
        transition(exam, "PLANNED")
        transition(exam, "SCHEDULED")
        exam.refresh_from_db()
        self.assertEqual(exam.status, "SCHEDULED")

    def test_exam_cannot_skip_planning(self):
        exam = make_exam(1)
        with self.assertRaises(InvalidTransition):
            transition(exam, "SCHEDULED")
        exam.refresh_from_db()
        self.assertEqual(exam.status, "DRAFT")

    def test_assignment_terminal_states(self):
        a = make_assignment(make_exam(1), make_room(1), make_run(1))
        transition(a, "CANCELLED")
        with self.assertRaises(InvalidTransition):
            transition(a, "ASSIGNED")

    def test_exam_can_be_reset_for_rerun(self):
        self.assertTrue(can_transition("Exam", "UNASSIGNED", "PLANNED"))
        self.assertTrue(can_transition("Exam", "SCHEDULED", "PLANNED"))

    def test_dropped_enrollment_cannot_be_reactivated(self):
        e = make_enrollment(1, make_student(1), make_course(1))
        transition(e, "DROPPED")
        with self.assertRaises(InvalidTransition):
            transition(e, "ACTIVE")

    def test_run_lifecycle(self):
        run = make_run(1)
        transition(run, "COMPLETED")
        with self.assertRaises(InvalidTransition):
            transition(run, "RUNNING")


class ValidationModelTests(TestCase):
    def test_violation_links_to_validation_run(self):
        run = make_run(1)
        v = ValidationRun.objects.create(validation_id="VAL-000001", scheduler_run=run)
        DetectedViolation.objects.create(violation_id="VIO-000001", validation_run=v,
                                         violation_code="ROOM_CAPACITY_EXCEEDED", entity_id="ROOM-000001")
        self.assertEqual(v.violations.count(), 1)

    def test_invalid_violation_code_rejected(self):
        run = make_run(1)
        v = ValidationRun.objects.create(validation_id="VAL-000001", scheduler_run=run)
        bad = DetectedViolation(violation_id="VIO-000001", validation_run=v, violation_code="NOPE")
        with self.assertRaises(ValidationError):
            bad.full_clean()


class EnumTests(TestCase):
    def test_invalid_enums_rejected_by_full_clean(self):
        s = Student(student_id="STU-000001", full_name="x", email="a@b.example", department="XX",
                    year_level=1, status="ACTIVE")
        with self.assertRaises(ValidationError):
            s.full_clean()
        s2 = Student(student_id="STU-000002", full_name="x", email="b@b.example", department="CS",
                     year_level=5)
        with self.assertRaises(ValidationError):
            s2.full_clean()

    def test_unique_building_room_number(self):
        make_room(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Room.objects.create(room_id="ROOM-000099", building="Block A", room_number="A-101", room_type="CLASSROOM")
