# Known Limitations

These are deliberate scope and implementation trade-offs for the current
demonstration system.

## Storage and concurrency

- The application uses SQLite, which permits only limited concurrent writes.
  It is appropriate for the generated demonstration dataset, not a
  high-concurrency production service. PostgreSQL is the natural deployment
  alternative.
- There is no run partitioning or archival policy; schedule history remains in
  the same database.
- Do not run scheduler write actions concurrently from the web interface and
  management commands. The app does not provide a queue or distributed
  scheduler lock.

## Runtime and workflow

- Web workflow actions run synchronously in the request. There is no Celery or
  Redis worker, progress reporting, or request cancellation for long-running
  operations.
- Reproducibility verification requires a database without append-only
  schedule events. Run it before scheduling, or use a fresh local database.
- The dashboard is read-only for general users; there are no custom CRUD
  screens. Internal record management belongs in Django admin.
- Read-only timetable and dashboard pages are intentionally public for
  demonstration. Student lookup requires authentication; non-staff accounts
  can only access the record matching their account email, while staff and
  Academic Administrators can look up any student. Exam detail rosters and
  accommodation details are restricted to staff and Academic Administrators.
  Mutating actions require an authenticated staff/superuser or an Academic
  Administrator group member and use POST with CSRF protection.

## Scheduling scope

- The scheduler uses a deterministic DSatur ordering and greedy resource
  allocation. It is a heuristic and does not guarantee a globally optimal
  schedule or maximize every soft preference. Soft rules S1/S2/S5 are
  documented policy goals but are not implemented as active optimization
  constraints in the current scheduler.
- Per-student interval optimization is not implemented. The system does not
  currently search for the best ordering of a student's exams within the same
  day or across the exam window; it remains a documented limitation rather than
  a claimed feature.
- The generator and policy use a fixed 2026 exam calendar and one configured
  term. Supporting other academic calendars or multiple simultaneous terms
  requires changing configuration and reviewing identifier assumptions.
- One exam per course per term is enforced by the data model.
- Some generated exams can remain unassigned when no feasible room, time, or
  invigilator combination exists. The scheduler records a reason and evidence
  rather than silently dropping the exam.

## Data and evaluation

- All included/generated records are synthetic; this project is not connected
  to a live student information system. See `SOURCE_MANIFEST.md`.
- Anomaly fixtures are separate `ANOMALY_FIXTURE` runs. The injector writes
  run-scoped ground-truth output files under `data/`; a later injection
  replaces those files, so retain a copy if an earlier evaluation must be
  archived.
- Validation uses an independent implementation against persisted schedule
  rows, but it does not replace operational review of university policy or
  data quality.

## Dashboard

- The conflict graph displays up to 30 exams with the greatest conflict degree
  to keep the browser view manageable. The Python graph builder can construct
  the graph from the full term data.
- Validation history is limited to the most recent 15 entries.
- The timetable has filters but no pagination. A large number of assignments
  on one date may require pagination for a production deployment.
