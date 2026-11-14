# Test Report

The Django test runner executes the suite using a separate test database. The
data generator uses the fixed seed `20261022` in tests that need generated
records. Tests that write reports or exports use temporary directories.

Latest local verification (2026-11-14): `python manage.py test` completed
successfully with 134 tests.

## Coverage

| Category | Test module | Verified behavior |
|---|---|---|
| Models and lifecycle | `tests/test_models.py` | Model constraints, relationships, and append-only schedule history |
| Identifiers | `tests/test_ids.py` | ID formats, boundary values, deterministic IDs, and assignment ID composition |
| Synthetic data | `tests/test_generator.py` | Starter-scale counts, generated IDs and relationships, allowed values, and lifecycle guard |
| Master-data validation | `tests/test_data_validator.py` | Clean data passes; missing requirements and invalid enum values are detected |
| Data exports | `tests/test_exporter.py` | CSV, JSON, SQL, manifest output and reproducibility-related export behavior |
| Reproducibility | `tests/test_reproducibility.py`, `tests/test_integration.py` | Fixed-seed checksums match, different seeds differ, and verification rolls back its changes |
| Conflict graph | `tests/test_conflict_graph.py` | Shared-student conflict weights, active-term enrollments, and coloring behavior |
| Accommodations | `tests/test_accommodations.py` | Effective accommodation dates and extra-time, separate-room, and accessibility rules |
| Invigilator allocation | `tests/test_invigilator_allocator.py` | Availability windows, staffing failures, daily/consecutive limits, and buffers |
| Scheduler | `tests/test_scheduler.py`, `tests/test_constraints.py` | Assignment, capacity, availability, closure, invigilator, and persistence-failure behavior |
| Schedule validation | `tests/test_schedule_validator.py` | Baseline checks pass and persisted corruption produces violations |
| Anomaly pipeline | `tests/test_anomalies.py`, `tests/test_integration.py` | Fixture isolation, ground truth, detection, evaluation, and baseline cleanliness |
| Business metrics | `tests/test_metrics.py` | Run-level utilization and reconciliation metrics |
| Dashboard | `tests/test_views.py` | Public pages, timetable filters, exam and student lookup, empty and not-found states |
| Workflow permissions | `tests/test_views.py` | Authentication, role access, POST-only and CSRF behavior, scheduler, validations, export, and anomaly actions |
| End-to-end workflow | `tests/test_integration.py` | Generate, validate, schedule, inject, detect, evaluate, recheck baseline, and export |

## Boundary and failure cases

`tests/test_constraints.py` checks that exactly-full room capacity is accepted,
capacity plus one is rejected with a reason code, half-open adjacent intervals
do not overlap, a one-minute intersection does overlap, a room closure makes
the room unavailable, an exact invigilator availability window is sufficient,
no invigilator yields a documented failure, and a forced persistence failure
does not leave partial schedule rows.

`tests/test_views.py` checks friendly responses for both unknown student IDs
and unknown exam IDs.

## Run the tests

```powershell
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py test tests.test_constraints tests.test_integration -v 2
```

Also run the Django checks and migration consistency check:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```
