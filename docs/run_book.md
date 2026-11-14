# Run Book

This run book covers setup, a baseline schedule, the anomaly demonstration,
dashboard navigation, and recovery from common command-order mistakes.

## 1. First-time setup

From the repository root:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python manage.py migrate
python manage.py setup_roles
python manage.py createsuperuser
```

`setup_roles` is safe to run more than once. It creates the groups Learner,
Instructor, Academic Administrator, Support Staff, and Platform Administrator.
Staff and superusers can run dashboard actions. A non-staff user can run those
actions by joining **Academic Administrator** through Django admin.

## 2. Generate, validate, and schedule

Run reproducibility verification before scheduling, because the command
requires that no append-only `ScheduleEvent` rows exist:

```powershell
python manage.py generate_data --seed 20261022 --scale starter
python manage.py validate_data
python manage.py verify_reproducibility --seed 20261022 --scale starter
python manage.py run_scheduler --seed 20261022
python manage.py validate_schedule
```

For the full dataset, replace `starter` with `full` (5,000 students, 300
courses, 300 exams, 100 rooms, and 200 invigilators).

## 3. Inject and evaluate anomalies

```powershell
python manage.py inject_anomalies
python manage.py detect_violations
python manage.py evaluate_anomalies
```

The starter fixture is expected to label seven findings across five anomaly
types. A successful demonstration reports TP=7, FP=0, FN=0 and F1=1.0.
Ground-truth files and the evaluation report are written beneath `data/`.
Anomaly room closures are scoped to their fixture run; the baseline is
unchanged.

## 4. Dashboard walkthrough

```powershell
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Read-only pages are public; sign in at
`/accounts/login/` to run staff actions.

| Page | URL | Demonstration |
|---|---|---|
| Overview | `/` | Latest run, coverage/utilization metrics, and staff actions |
| Timetable | `/schedule/` | Date-grouped schedule and date/exam/course/room/invigilator/department filters |
| Exam detail | `/exams/<exam-id>/` | Exam rooms, invigilators, allocation, and event explanation |
| Student lookup | `/students/?q=STU-000001` | Enrollments and the student's allocated timetable |
| Exceptions | `/exceptions/` | Unassigned exams, reason codes, and evidence |
| Validation | `/validation/` | Checks, detected violations, and validation history |
| Conflict graph | `/conflict-graph/` | Interactive graph of exams sharing enrolled students |
| Sign in | `/accounts/login/` | Django dashboard authentication |

## 5. Four-to-five-minute demo script

| Time | Show | Action |
|---|---|---|
| 0:00–0:30 | Architecture | Introduce the generator, scheduler, independent validator, and dashboard. Refer to `architecture.md`. |
| 0:30–1:00 | Data | Run `validate_data`; show that the deterministic records pass validation. |
| 1:00–2:00 | Schedule | Sign in, run the scheduler, open the timetable, and demonstrate a filter. |
| 2:00–2:40 | Decision explanation | Open an exam and show its assignment details and schedule event history. |
| 2:40–3:40 | Anomaly evaluation | Inject anomalies, detect violations, evaluate, then inspect the scorecard and ground truth. |
| 3:40–4:15 | Metrics | Show the independent checks and business metrics on the validation and overview pages. |
| 4:15–4:45 | Reproducibility and provenance | Show the reproducibility command/report, `SOURCE_MANIFEST.md`, and this documentation set. |

The anomaly commands can also be run from the staff-only **Workflow actions**
card; each action calls the same service layer as its management command.

## 6. Start over with a clean local database

Stop the development server before removing the SQLite database. From
PowerShell:

```powershell
Remove-Item .\db.sqlite3
python manage.py migrate
python manage.py setup_roles
python manage.py generate_data --seed 20261022 --scale starter
```

Deleting the development database removes local schedule history. Do not use
this procedure against a database containing data you need to preserve.
`generate_data --force` cannot clear generated data once append-only scheduler
events exist; use a fresh database for a clean demonstration.

## 7. Troubleshooting

| Symptom | Cause | Resolution |
|---|---|---|
| `Generated data already exists` | The generator found existing data. | Use `--force` only if no scheduler event history exists; otherwise use a fresh local database. |
| Reproducibility verification refuses to run | `ScheduleEvent` history exists. | Run it before scheduling or use a fresh database. |
| No anomaly fixture exists | Detection was run before injection. | Run `inject_anomalies` first. |
| No validation for anomaly run | Evaluation was run before detection. | Run `detect_violations` first. |
| Workflow action requires the Academic Administrator role | The account is not staff and lacks the group. | Add it to the group in `/admin/`, or use a staff/superuser account. |
| Timetable says it needs a scheduler run | No `SchedulerRun` is available. | Run `run_scheduler` after generating data. |
| Schedule events cannot be updated/deleted | Schedule history is append-only. | This is intentional; create a new run instead. |
