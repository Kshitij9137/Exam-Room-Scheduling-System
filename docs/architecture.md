# Architecture: Exam & Room Scheduling System

**Stack:** Python 3.11+ · Django · Django Templates · Bootstrap 5 · JavaScript · SQLite

## 1. Three tiers

```
┌──────────────────────────────────────────────────────────────┐
│ TIER 1 - PRESENTATION (Frontend)                             │
│ Django Templates + Bootstrap 5 + JavaScript                  │
│ Dashboard · Timetable · Exam detail · Student lookup         │
│ Exceptions centre · Validation scorecard · Conflict graph    │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP request / response (CSRF-protected POST for actions)
┌──────────────────────────────▼───────────────────────────────┐
│ TIER 2 - APPLICATION (Backend)                               │
│ Django Views + Forms  ──calls──►  Python service modules     │
│ Services: data generator · conflict graph · slot allocator · │
│ room allocator · invigilator allocator · accommodation ·     │
│ explanations · schedule validator · anomaly detector ·       │
│ evaluator · metrics                                          │
│ Management commands call the SAME services as the views      │
└──────────────────────────────┬───────────────────────────────┘
                               │ Django ORM + transaction.atomic()
┌──────────────────────────────▼───────────────────────────────┐
│ TIER 3 - DATA                                                │
│ SQLite: 11 core entities + supporting tables                 │
│ Append-only ScheduleEvent history · SchedulerRun records     │
│ ValidationRun / DetectedViolation                            │
│ Files: CSV/JSON/SQL exports · ground_truth.* (kept separate) │
└──────────────────────────────────────────────────────────────┘
```

## 2. Architectural principles

1. Templates only present data.
2. Views only handle HTTP: parse input, call a service, render the result.
3. Business rules live in reusable service modules, never in views or templates.
4. Management commands and web actions call the same service functions.
5. Every scheduling execution is a `SchedulerRun` with its own ID.
6. History is never overwritten: assignments are `SUPERSEDED` or `CANCELLED`, events are append-only.
7. The scheduler never reads ground-truth labels.
8. The validator is an independent implementation that reads persisted rows.
9. Every decision and exception is explainable (reason code plus evidence).
10. Web actions never run shell commands.

## 3. Module responsibilities

| App / package | Responsibility |
|---|---|
| `apps/core` | Master data models, ID generator, data generator service, export command |
| `apps/scheduling` | Scheduling models, conflict graph, slot/room/invigilator allocators, accommodation logic, explanations, `run_scheduler` |
| `apps/validation` | `ValidationRun`, `DetectedViolation`, independent schedule checks, anomaly fixtures, evaluator, and business metrics |
| `apps/dashboard` | Read-only dashboard views, filters, workflow actions, role helpers, templates, and static files |
| Django auth groups | Learner, Instructor, Academic Administrator, Support Staff, and Platform Administrator role labels |
| `generator/` | Pure-Python seeded generation logic (config, master data, enrollments, anomalies) |

## 4. Why the validator is independent

If the scheduler and validator share the same feasibility function, one bug fools both and the report shows "0 violations" when the schedule is wrong. So the scheduler checks feasibility in memory while building, and the validator re-checks the saved database rows with its own queries.

## 5. Baseline vs anomaly isolation

Every `SchedulerRun` has a `run_type`:

- `BASELINE`: the clean schedule. Must show **0 hard violations**.
- `ANOMALY_FIXTURE`: a separate run, copied from the baseline, into which the five labelled anomalies are injected.

The baseline is never modified by the anomaly commands.

## 6. Actors and access

| Actor | Responsibility | Access |
|---|---|---|
| Learner | View exam information | Read-only dashboard pages |
| Instructor | View course and exam information | Read-only dashboard pages |
| Academic Administrator | Run scheduling and validation workflows | Staff actions and exceptions |
| Support Staff | Review accommodation and accessibility information | Read-only dashboard pages |
| Platform Administrator | Users, permissions, settings | Django admin and staff actions |

Dashboard pages are intentionally readable without login for demonstrations.
Mutating workflow actions require a POST request and either Django staff status
or membership in the Academic Administrator group. Internal record management
remains in Django admin.

## 7. Technology notes

- SQLite is enough for 5,000 students, 300 exams and 100 rooms. Limitation: one writer at a time. Production path: PostgreSQL.
- No DRF, React, Celery or PostgreSQL needed. Long actions run synchronously and must finish in a reasonable web-request time.
- All datetimes are timezone-aware and stored in UTC (`USE_TZ = True`).