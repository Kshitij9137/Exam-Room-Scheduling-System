# Exam & Room Scheduling System

Django, SQLite, and Bootstrap 5 application for generating synthetic university
exam data, scheduling exams into rooms, validating schedules, evaluating
deliberately injected anomalies, and reviewing results through a dashboard.
**Phases 3–7 are implemented.**

## Setup and run

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

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
```

Open `http://127.0.0.1:8000/`. Read-only pages are publicly accessible.
Sign in at `/accounts/login/` with a staff/superuser account to run dashboard
workflow actions. Reproducibility verification must be run before scheduling
because it requires no append-only schedule events. See the [run book](docs/run_book.md)
for a clean-state reset and the judge-facing demo walkthrough.

Use `--scale full` instead of `--scale starter` to generate 5,000 students,
300 courses, 300 exams, 100 rooms, and 200 invigilators. The scheduler records
unassigned exams with reason codes and evidence rather than dropping them.
Phase 5 scorecards and anomaly evaluation reports are written under `data/`;
exports are created under `data/exports/`.

## Dashboard

| Page | URL | Contents |
|---|---|---|
| Overview | `/` | Latest run, business metrics, and staff workflow actions |
| Timetable | `/schedule/` | Date-grouped schedule with date, exam, course, room, invigilator, and department filters |
| Exam details | `/exams/<exam-id>/` | Assignments, room and invigilator details, and event history |
| Student lookup | `/students/?q=STU-000001` | Student enrollments and personal timetable; accepts ID or email |
| Exceptions | `/exceptions/` | Unassigned exams, reason codes, and evidence |
| Validation | `/validation/` | Independent checks, violations, and validation history |
| Conflict graph | `/conflict-graph/` | Interactive exam conflicts based on shared students |

Workflow actions are CSRF-protected POST requests and require Django staff
status or membership in the **Academic Administrator** group. Run
`python manage.py setup_roles` to create the role groups. Internal record
management is handled through Django admin.

## Tests and checks

```powershell
python manage.py test
python manage.py test tests.test_constraints tests.test_integration -v 2
python manage.py check
python manage.py makemigrations --check --dry-run
```

The tests use Django's isolated test database. File-producing tests override
the output directory so they do not overwrite local reports.

## Repository map

| Path | Purpose |
|---|---|
| `apps/core/` | Master-data models, identifiers, generation, and export command |
| `apps/scheduling/` | Conflict graph, scheduling policies and allocators, assignments, and run history |
| `apps/validation/` | Independent schedule checks, business metrics, anomaly fixtures, and evaluation |
| `apps/dashboard/` | Public read-only pages, staff workflow actions, templates, and static assets |
| `generator/` | Deterministic synthetic-data generation |
| `tests/` | Model, generator, scheduling, validation, boundary, integration, and dashboard tests |
| `data/` | Generated reports and exports; local exports and temporary output are ignored |
| `SOURCE_MANIFEST.md` | Synthetic data provenance and reproducibility details |

## Documentation

- [Architecture](docs/architecture.md)
- [Business rules](docs/business_rules.md)
- [ER diagram](docs/er_diagram.md)
- [Data dictionary](docs/data_dictionary.md)
- [Test report](docs/test_report.md)
- [Run book and demo script](docs/run_book.md)
- [Known limitations](docs/limitations.md)
- [Recorded reproducibility report](docs/reproducibility_report.txt)
- [Source manifest](SOURCE_MANIFEST.md)
