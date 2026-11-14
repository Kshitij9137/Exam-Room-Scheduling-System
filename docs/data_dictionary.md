# Data Dictionary

Conventions: PK = primary key, FK = foreign key. "Req" = required. All datetimes are timezone-aware (UTC). All PKs are `CharField` holding the ID formats in `er_diagram.md`. IDs are immutable.

Departments (enum `DEPT`): `CS, EE, ME, CE, BIO, CHEM, MATH, PHY, BUS, ARTS`.

---

## 1. Student

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| student_id | Char(10) PK | Y | `STU-\d{6}` | | Y | regex |
| full_name | Char(150) | Y | synthetic name | | N | non-empty |
| email | Email | Y | `stu000001@university.example` | | Y | valid email |
| department | Char(10) | Y | `DEPT` | | N | in enum |
| year_level | SmallInt | Y | 1-4 | year | N | 1 <= v <= 4 |
| status | Char(12) | Y | `ACTIVE, INACTIVE, GRADUATED` | | N | in enum, default ACTIVE |

## 2. Course

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| course_id | Char(10) PK | Y | `CRS-\d{6}` | | Y | regex |
| course_code | Char(12) | Y | e.g. `CS101` | | Y | `^[A-Z]{2,4}\d{3}$` |
| title | Char(200) | Y | | | N | non-empty |
| department | Char(10) | Y | `DEPT` | | N | in enum |
| credits | SmallInt | Y | 1-6 | credit | N | 1 <= v <= 6 |

## 3. Enrollment (bridge Student-Course)

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| enrollment_id | Char(10) PK | Y | `ENR-\d{6}` | | Y | regex |
| student | FK Student | Y | existing student_id | | | FK exists |
| course | FK Course | Y | existing course_id | | | FK exists |
| term | Char(12) | Y | `2026-FALL` | | | in configured terms |
| status | Char(12) | Y | `ACTIVE, DROPPED, WITHDRAWN, COMPLETED` | | | in enum |
| effective_from | Date | Y | | date | | |
| effective_to | Date | N | | date | | null or >= effective_from |

Unique together: (student, course, term). Inactive/graduated students may not have ACTIVE enrollments.

## 4. Exam

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| exam_id | Char(20) PK | Y | `EXAM-\d{4}-\d{6}` | | Y | regex, year = term year |
| course | FK Course | Y | existing course_id | | | FK exists |
| title | Char(200) | Y | | | N | non-empty |
| term | Char(12) | Y | `2026-FALL` | | | |
| duration_minutes | SmallInt | Y | 60, 90, 120, 180 (valid range 30-240) | minute | N | multiple of 15 |
| status | Char(12) | Y | `DRAFT, PLANNED, SCHEDULED, UNASSIGNED` | | | valid transition |

Unique together: (course, term). Active enrollment count is **derived** from Enrollment, never stored.

## 5. ExamRequirement

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| requirement_id | Char(10) PK | Y | `REQ-\d{6}` | | Y | regex |
| exam | OneToOne Exam | Y | existing exam_id | | Y | FK exists |
| equipment | M2M Equipment via `ExamRequirementEquipment` | N | equipment codes | | | codes exist |
| allow_multi_room | Boolean | Y | true/false | | | default true |
| invigilator_ratio | SmallInt | Y | 20-100 | students per invigilator | | default 50 |

## 6. Room

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| room_id | Char(11) PK | Y | `ROOM-\d{6}` | | Y | regex |
| building | Char(60) | Y | e.g. `Block A` | | N | non-empty |
| room_number | Char(10) | Y | e.g. `A-101` | | N | |
| room_type | Char(20) | Y | `LECTURE_HALL, CLASSROOM, COMPUTER_LAB, SCIENCE_LAB` | | N | in enum |
| is_accessible | Boolean | Y | true/false | | N | default false |
| status | Char(10) | Y | `ACTIVE, INACTIVE` | | N | in enum |
| equipment | M2M Equipment via `RoomEquipment` | N | equipment codes | | | codes exist |

Unique together: (building, room_number).

## 7. RoomCapacity

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| capacity_id | Char(10) PK | Y | `CAP-\d{6}` | | Y | regex |
| room | FK Room | Y | existing room_id | | | FK exists |
| exam_capacity | SmallInt | Y | 10-500 | seat | N | 10 <= v <= 500 |
| effective_from | Date | Y | | date | | |
| effective_to | Date | N | | date | | null or >= effective_from; no overlap per room |

## 8. Invigilator

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| invigilator_id | Char(10) PK | Y | `INV-\d{6}` | | Y | regex |
| full_name | Char(150) | Y | synthetic | | N | non-empty |
| email | Email | Y | `inv000001@university.example` | | Y | valid email |
| department | Char(10) | N | `DEPT` | | N | in enum |
| max_daily_hours | Decimal(3,1) | Y | 1.0-10.0 | hour | N | default 8.0 |
| status | Char(10) | Y | `ACTIVE, INACTIVE` | | N | in enum |

## 9. Availability

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| availability_id | Char(10) PK | Y | `AVL-\d{6}` | | Y | regex |
| room | FK Room | N | existing room_id | | | exactly one of room/invigilator |
| invigilator | FK Invigilator | N | existing invigilator_id | | | exactly one of room/invigilator |
| start_at | DateTime | Y | UTC | datetime | | |
| end_at | DateTime | Y | UTC | datetime | | end_at > start_at |

DB CHECK: `(room IS NULL) <> (invigilator IS NULL)`. An allocation must fit completely inside one window.

## 10. Accommodation

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| accommodation_id | Char(10) PK | Y | `ACC-\d{6}` | | Y | regex |
| student | FK Student | Y | existing student_id | | | FK exists |
| accommodation_type | Char(20) | Y | `EXTRA_TIME, SEPARATE_ROOM, ACCESSIBLE_ROOM` | | | in enum |
| extra_time_percent | SmallInt | Y | 0, 25, 50, 100 | percent | | >0 only if EXTRA_TIME, else 0 |
| effective_from | Date | Y | | date | | |
| effective_to | Date | N | | date | | null or >= effective_from |
| status | Char(10) | Y | `ACTIVE, REVOKED` | | | in enum |

No free-text medical notes are stored.

## 11. ScheduleAssignment (bridge Exam-Room, per run)

| Field | Type | Req | Allowed values / format | Unit | Unique | Validation |
|---|---|---|---|---|---|---|
| assignment_id | Char(64) PK | Y | `ASN-<exam-id>-<room-id>-<run-id>` | | Y | regex, matches its FKs |
| run | FK SchedulerRun | Y | existing run_id | | | FK exists |
| exam | FK Exam | Y | existing exam_id | | | FK exists |
| room | FK Room | Y | existing room_id | | | FK exists |
| start_at | DateTime | Y | UTC | datetime | | within operating hours |
| end_at | DateTime | Y | UTC | datetime | | end_at > start_at; >= required duration |
| allocated_count | SmallInt | Y | >= 1 | student | | equals count of its StudentRoomAllocation rows |
| status | Char(12) | Y | `ASSIGNED, SUPERSEDED, CANCELLED` | | | valid transition |

Unique together: (run, exam, room). All rooms of one exam in a run share the same `start_at`.

---

## Supporting entities (summary)

| Entity | PK | Key fields | Notes |
|---|---|---|---|
| Equipment | code | name | e.g. `PROJECTOR, COMPUTER, LAB_BENCH, ACCESSIBLE_DESK` |
| RoomEquipment | auto | room FK, equipment FK | unique (room, equipment) |
| ExamRequirementEquipment | auto | requirement FK, equipment FK | unique pair |
| RoomClosure | `CLS-` | room FK, start_at, end_at, reason (`MAINTENANCE, EVENT, REPAIR`) | end_at > start_at |
| TimeSlot | `SLOT-` | slot_date, start_time, label | unique (slot_date, start_time) |
| SchedulerRun | `RUN-` | run_type (`BASELINE, ANOMALY_FIXTURE`), status, algorithm_version, seed, started_at, finished_at, notes | never deleted |
| ScheduleEvent | `EVT-` | run FK, assignment FK (null), exam FK, event_type (`ASSIGNED, MOVED, CANCELLED, UNASSIGNED, SUPERSEDED`), detail JSON, event_at | append-only; no update/delete |
| InvigilatorAssignment | `IAS-` | assignment FK, invigilator FK, role (`CHIEF, ASSISTANT`) | unique (assignment, invigilator) |
| StudentRoomAllocation | `SRA-` | assignment FK, student FK, required_minutes | unique (assignment, student) |
| UnassignedExam | `UNA-` | run FK, exam FK, primary_reason_code, evidence JSON | unique (run, exam) |
| ValidationRun | `VAL-` | run FK, status, checks_performed, failures, started_at | |
| DetectedViolation | `VIO-` | validation_run FK, violation_code, assignment FK (null), entity_id, detail | |

## Ground-truth file (NOT a database input)

`data/ground_truth.csv` columns: `anomaly_id, issue_type, assignment_id, affected_entity_id, expected_violation_code`.
It is read only by the evaluator after detection finishes.

## Phase 3 generation assumptions

- The default seed is `20261022`; `starter` creates 200 students, 30 courses,
  20 exams, 15 rooms, and 25 invigilators. `full` creates 5,000 students,
  300 courses/exams, 100 rooms, and 200 invigilators.
- Each course has at most one exam in a term. Starter scale intentionally leaves
  ten courses without an exam; only courses with an exam receive enrollments.
- Each student is enrolled in 4-6 exam courses. Enrollment counts are derived
  from the bridge rows rather than stored separately.
- Generated identities are deterministic counters. Timestamps use the fixed
  UTC exam calendar; no external or personal data is used.
- Assignment-linked anomaly labels are produced with the isolated anomaly
  fixture in the later validation phase, not mixed into this clean baseline.