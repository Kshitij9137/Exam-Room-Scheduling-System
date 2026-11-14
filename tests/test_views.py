import tempfile
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.core.models import Student
from apps.core.services.data_generator import generate_and_persist
from apps.dashboard.services import conflict_graph_data, exam_detail
from apps.scheduling.models import ScheduleAssignment
from apps.scheduling.services.scheduler import run_scheduler
from generator.config import SEED_DEFAULT


class PublicPagesTests(TestCase):
    def test_dashboard_loads_anonymously(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Overview")
        self.assertNotContains(response, "Workflow actions")

    def test_login_page_loads(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")

    def test_timetable_shows_empty_state_without_run(self):
        response = self.client.get(reverse("dashboard:timetable"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "needs a scheduler run")

    def test_admin_login_page_loads(self):
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)


class PopulatedPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        cls.scheduler_run = run_scheduler(seed=SEED_DEFAULT)
        cls.assignment = (
            ScheduleAssignment.objects.filter(run=cls.scheduler_run)
            .order_by("start_at")
            .first()
        )

    def setUp(self):
        self.client.force_login(
            User.objects.create_user(
                "viewer",
                password="test-pass-123",
                is_staff=True,
            )
        )

    def test_dashboard_shows_latest_run_and_business_metrics(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.scheduler_run.run_id)
        self.assertContains(response, "Business metrics")

    def test_dashboard_stays_on_baseline_after_anomaly_injection(self):
        from apps.validation.services.anomaly_injector import inject

        with tempfile.TemporaryDirectory(prefix="dashboard_iso_") as tmpdir:
            with override_settings(BASE_DIR=Path(tmpdir)):
                inject(self.scheduler_run.run_id)
        response = self.client.get(reverse("dashboard:home"))
        self.assertContains(response, self.scheduler_run.run_id)
        self.assertContains(response, "BASELINE")

    def test_exam_detail_and_conflict_graph_stay_on_baseline_after_anomaly_injection(
        self,
    ):
        from apps.validation.services.anomaly_injector import inject

        with tempfile.TemporaryDirectory(prefix="dashboard_iso_") as tmpdir:
            with override_settings(BASE_DIR=Path(tmpdir)):
                inject(self.scheduler_run.run_id)

        self.assertEqual(
            exam_detail(self.assignment.exam)["run"],
            self.scheduler_run,
        )

        baseline_slots = {}
        for assignment in ScheduleAssignment.objects.filter(
            run=self.scheduler_run
        ).order_by("start_at", "assignment_id"):
            baseline_slots.setdefault(
                assignment.exam_id, assignment.start_at.isoformat()
            )
        graph = conflict_graph_data(top_n=1000)
        self.assertEqual(
            {node["id"]: node["slot"] for node in graph["nodes"]},
            {
                node["id"]: baseline_slots.get(node["id"], "")
                for node in graph["nodes"]
            },
        )

    def test_timetable_lists_assigned_exam(self):
        response = self.client.get(reverse("dashboard:timetable"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.assignment.exam_id)

    def test_timetable_filter_by_exam_id(self):
        response = self.client.get(
            reverse("dashboard:timetable"), {"exam": self.assignment.exam_id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.assignment.exam_id)

    def test_timetable_filter_with_invalid_date_is_safe(self):
        response = self.client.get(
            reverse("dashboard:timetable"), {"date": "not-a-date"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid date")

    def test_exam_detail_renders_assignment_explanation(self):
        response = self.client.get(
            reverse("dashboard:exam_detail", args=[self.assignment.exam_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Why this assignment?")

    def test_exam_detail_unknown_id_returns_not_found_page(self):
        response = self.client.get(
            reverse(
                "dashboard:exam_detail",
                args=["EXAM-9999-000001"],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No record found")

    def test_student_lookup_returns_enrollments(self):
        response = self.client.get(
            reverse("dashboard:student_lookup"), {"q": "STU-000001"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enrollments")

    def test_non_staff_student_can_only_lookup_their_own_record(self):
        own_student = Student.objects.get(pk="STU-000001")
        user = User.objects.create_user(
            "student_viewer",
            email=own_student.email,
            password="test-password",
        )
        self.client.force_login(user)

        own_response = self.client.get(
            reverse("dashboard:student_lookup"),
            {"q": own_student.student_id},
        )
        other_response = self.client.get(
            reverse("dashboard:student_lookup"),
            {"q": "STU-000002"},
        )

        self.assertEqual(own_response.context["student"], own_student)
        self.assertIsNone(other_response.context["student"])
        self.assertNotContains(other_response, "Student 00002")

    def test_non_staff_exam_detail_does_not_expose_student_roster(self):
        user = User.objects.create_user("regular_viewer", "test-password")

        context = exam_detail(self.assignment.exam, user=user)

        self.assertEqual(context["assigned_students"], [])
        self.assertEqual(context["accommodations"], [])

    def test_student_lookup_accepts_email(self):
        from apps.core.models import Student

        email = Student.objects.get(pk="STU-000001").email
        response = self.client.get(
            reverse("dashboard:student_lookup"), {"q": email}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personal timetable")

    def test_student_lookup_unknown_id_is_friendly(self):
        response = self.client.get(
            reverse("dashboard:student_lookup"), {"q": "STU-999999"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No student found")

    def test_exceptions_page_loads(self):
        response = self.client.get(reverse("dashboard:exceptions"))
        self.assertEqual(response.status_code, 200)

    def test_validation_page_loads(self):
        response = self.client.get(reverse("dashboard:validation"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Validation scorecard")

    def test_conflict_graph_page_loads(self):
        response = self.client.get(reverse("dashboard:conflict_graph"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Conflict graph")


class ActionPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        generate_and_persist(seed=SEED_DEFAULT, scale="starter")
        cls.scheduler_run = run_scheduler(seed=SEED_DEFAULT)

    def setUp(self):
        self.output_dir = tempfile.TemporaryDirectory(prefix="dashboard_test_")
        self.settings_override = override_settings(
            BASE_DIR=Path(self.output_dir.name)
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.output_dir.cleanup()

    def test_anonymous_cannot_run_scheduler(self):
        response = self.client.post(reverse("dashboard:action_run_scheduler"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_non_staff_user_cannot_run_scheduler(self):
        user = User.objects.create_user(username="alice", password="test-pass-123")
        self.client.force_login(user)
        response = self.client.post(
            reverse("dashboard:action_run_scheduler"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "requires the Academic Administrator role")
        self.assertNotContains(response, "Workflow actions")

    def test_action_is_post_only(self):
        staff = User.objects.create_user(
            username="staff-get", password="test-pass-123", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.get(reverse("dashboard:action_run_scheduler"))
        self.assertEqual(response.status_code, 405)

    def test_action_requires_csrf_token(self):
        staff = User.objects.create_user(
            username="staff-csrf", password="test-pass-123", is_staff=True
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(staff)
        response = csrf_client.post(reverse("dashboard:action_run_scheduler"))
        self.assertEqual(response.status_code, 403)

    def test_external_next_url_is_not_followed(self):
        staff = User.objects.create_user(
            username="staff-next", password="test-pass-123", is_staff=True
        )
        self.client.force_login(staff)
        dashboard = self.client.get(reverse("dashboard:home"))
        self.assertContains(dashboard, "Workflow actions")
        response = self.client.post(
            reverse("dashboard:action_run_scheduler"),
            {"seed": "invalid", "next": "https://example.invalid/"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))

    def test_invalid_seed_is_reported(self):
        staff = User.objects.create_user(
            username="staff-invalid-seed", password="test-pass-123", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("dashboard:action_run_scheduler"),
            {"seed": "not-an-integer"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seed must be an integer.")

    def test_staff_can_run_scheduler(self):
        staff = User.objects.create_user(
            username="staff-run", password="test-pass-123", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("dashboard:action_run_scheduler"),
            {"seed": str(SEED_DEFAULT)},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ran scheduler")

    def test_academic_administrator_group_can_run_actions(self):
        call_command("setup_roles", verbosity=0)
        user = User.objects.create_user(username="academic-admin", password="test-pass-123")
        user.groups.add(Group.objects.get(name="Academic Administrator"))
        self.client.force_login(user)
        response = self.client.post(
            reverse("dashboard:action_run_scheduler"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ran scheduler")

    def test_staff_can_validate_schedule(self):
        staff = User.objects.create_user(
            username="staff-validate", password="test-pass-123", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("dashboard:action_validate_schedule"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "VAL-")

    def test_staff_can_validate_master_data(self):
        staff = User.objects.create_user(
            username="staff-data-check", password="test-pass-123", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("dashboard:action_validate_data"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data validation passed")

    def test_staff_can_export_data(self):
        staff = User.objects.create_user(
            username="staff-export", password="test-pass-123", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("dashboard:action_export_data"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Exported")
        self.assertTrue(
            (Path(self.output_dir.name) / "data" / "exports" / "manifest.json").exists()
        )

    def test_staff_can_run_complete_anomaly_workflow(self):
        staff = User.objects.create_user(
            username="staff-anomalies", password="test-pass-123", is_staff=True
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse("dashboard:action_inject_anomalies"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "labelled anomalies")

        response = self.client.post(
            reverse("dashboard:action_detect_violations"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "violations on RUN-")

        response = self.client.post(
            reverse("dashboard:action_evaluate_anomalies"), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Evaluation: TP=")
