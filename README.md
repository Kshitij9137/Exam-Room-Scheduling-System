# Exam & Room Scheduling System

Django + SQLite + Bootstrap 5. Status: **Phases 3–6 implemented**.

## Setup
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_roles
python manage.py createsuperuser
python manage.py generate_data --seed 20261022 --scale starter
python manage.py validate_data
python manage.py verify_reproducibility --seed 20261022 --scale starter
python manage.py run_scheduler --seed 20261022
python manage.py validate_schedule
python manage.py inject_anomalies
python manage.py detect_violations
python manage.py evaluate_anomalies
python manage.py export_data
python manage.py runserver
# Open http://127.0.0.1:8000/ and sign in at /accounts/login/
python manage.py test tests.test_views
python manage.py test            # all tests
```
See `docs/` for architecture, business rules, ER diagram and data dictionary.

Use `--scale full` to generate the required 5,000-student dataset. To replace
existing generated data before scheduling history exists, add `--force`.
Exports are written under `data/exports/`; generation metadata, validation and
reproducibility summaries are written under `data/`. The scheduler creates a
new run and retains its assignment history; exams that cannot satisfy all hard
constraints are reported with reason codes and evidence. Schedule validation
writes `data/validation_scorecard.json`. The anomaly commands create a separate
fixture run, write run-scoped ground truth to `data/ground_truth.csv` and
`data/ground_truth.json`, and report evaluation metrics to
`data/anomaly_evaluation.json`. Room closures attached to an anomaly fixture
are scoped to that run and do not affect baseline schedules.

## Dashboard (Phase 6)

The read-only dashboard pages are available without signing in:

- `/` — overview and latest run metrics
- `/schedule/` — searchable timetable
- `/exams/<exam-id>/` — exam assignments and explanation history
- `/students/?q=<student-id-or-email>` — student enrollments and personal timetable
- `/exceptions/` — unassigned exams and reason evidence
- `/validation/` — scorecard, detected violations, and validation history
- `/conflict-graph/` — interactive exam conflict graph

Workflow actions are available to Django staff/superusers and members of the
**Academic Administrator** group. `setup_roles` creates the documented role
groups; add users to the appropriate group through Django admin. All dashboard
actions are CSRF-protected POST requests. Use `/admin/` for internal record
management.
