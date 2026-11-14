# Business Rules

## 1. Hard constraints (never violated)

| ID | Rule | Violation code (validator) | Unassigned reason code |
|---|---|---|---|
| H1 | A student cannot sit two exams whose time intervals overlap | `STUDENT_DOUBLE_BOOKING` | `NO_CONFLICT_FREE_SLOT` |
| H2 | Students allocated to a room never exceed its effective exam capacity | `ROOM_CAPACITY_EXCEEDED` | `NO_ROOM_CAPACITY` |
| H3 | Room has all equipment the exam requires | `MISSING_EQUIPMENT` | `NO_EQUIPMENT_ROOM` |
| H4 | Room is available for the whole interval and no closure overlaps it | `ROOM_UNAVAILABLE_VIOLATION` | `ROOM_UNAVAILABLE` |
| H5 | Invigilator is available for the whole interval and not double-booked | `INVIGILATOR_DOUBLE_BOOKED`, `INVIGILATOR_UNAVAILABLE` | `NO_INVIGILATOR` |
| H6 | Accommodations are respected (extra time, separate room, accessible room) | `ACCOMMODATION_VIOLATION` | `ACCOMMODATION_UNSATISFIABLE` |
| H7 | A room hosts only one exam at a time | `ROOM_DOUBLE_BOOKED` | `NO_FEASIBLE_ASSIGNMENT` |
| H8 | Room and invigilator assignments must be active status | `INACTIVE_ROOM`, `INACTIVE_INVIGILATOR` | `NO_FEASIBLE_ASSIGNMENT` |
| H9 | Invigilator daily and consecutive hours cannot exceed policy limits | `INVIGILATOR_DAILY_LIMIT`, `INVIGILATOR_CONSECUTIVE_LIMIT` | `NO_INVIGILATOR` |

Additional integrity checks (also hard):

| Check | Violation code |
|---|---|
| Every active enrollment of a scheduled exam has exactly one `StudentRoomAllocation` | `STUDENT_ALLOCATION_MISMATCH` |
| A student is never allocated to two rooms for the same exam | `STUDENT_ALLOCATION_MISMATCH` |
| Assignment interval length >= required duration for its students | `INVALID_DURATION` |

## 2. Soft constraints (quality only, never override hard rules)

| ID | Goal |
|---|---|
| S1 | Avoid back-to-back exams for a student (gap below 30 minutes) |
| S2 | Spread exams across available days |
| S3 | Minimise wasted seats (best-fit room) |
| S4 | Balance invigilator workload |
| S5 | Avoid more than 2 exams per student per day |

## 3. Exam lifecycle and zero-enrollment policy

| Status | Meaning | Next valid states |
|---|---|---|
| `DRAFT` | Not yet entered for scheduling | `PLANNED` |
| `PLANNED` | Eligible to be scheduled | `SCHEDULED`, `UNASSIGNED`, `NOT_REQUIRED` |
| `SCHEDULED` | Successfully assigned to one or more rooms | `PLANNED` |
| `UNASSIGNED` | No feasible assignment found | `PLANNED` |
| `NOT_REQUIRED` | The exam has no active enrollments and is intentionally excluded from coverage | `PLANNED` |

An exam with no active enrollments is treated as `NOT_REQUIRED` rather than `SCHEDULED` and is not counted against coverage/failure rates. The scheduler records a `NOT_REQUIRED` schedule event with the no-enrollment reason.

## 4. Reason codes for unassigned exams

| Code | Meaning |
|---|---|
| `NO_CONFLICT_FREE_SLOT` | Every candidate slot clashes with student exams |
| `NO_ROOM_CAPACITY` | No room or room combination fits the students |
| `NO_EQUIPMENT_ROOM` | No eligible room has the required equipment |
| `ROOM_UNAVAILABLE` | Suitable rooms are closed or unavailable |
| `NO_INVIGILATOR` | Not enough available invigilators |
| `ACCOMMODATION_UNSATISFIABLE` | Extended time or room needs cannot be met |
| `NO_FEASIBLE_ASSIGNMENT` | No complete assignment satisfies all constraints |

The scheduler records the **primary** reason (the most common rejection) and keeps every rejection as evidence.

## 4. Formulas

```
required_duration = base_duration * (1 + extra_time_percent / 100)

required_invigilators(room) = max(1, ceil(allocated_students / invigilators_ratio))   # default ratio = 50

room_seat_utilization    = sum(allocated_students) / sum(capacity of rooms used)
room_time_utilization    = booked_room_minutes / available_room_minutes
invigilator_utilization  = assigned_hours / available_hours
scheduling_coverage      = fully_scheduled_exams / total_exams

precision = TP / (TP + FP)
recall    = TP / (TP + FN)
F1        = 2 * precision * recall / (precision + recall)
```

Reconciliation checks:

```
total_exams = fully_scheduled_exams + unassigned_exams
for every fully scheduled exam: active_enrolled_students = allocated_students
```

## 5. Time rules

- Intervals are **half-open**: `[start, end)`. An exam ending at 11:00 and another starting at 11:00 do NOT overlap.
- Conflict checks use real intervals, not slot labels.
- Hard buffer between exams (same student / room / invigilator): **0 minutes** by default; configurable.
- Soft buffer for students (S1): 30 minutes.
- Enrollment effective dates are treated as valid for the entire exam window when the graph and validators are built. In other words, an enrollment is active for a scheduled exam if `effective_from <= exam date` and (`effective_to` is null or `effective_to >= exam date`) for the actual exam date being evaluated.

## 6. Configurable policy assumptions

These are university policies chosen by us, not given by the problem statement.

| Assumption | Default |
|---|---|
| Term | `2026-FALL` |
| Exam period | 10 consecutive weekdays, 7 Dec 2026 to 18 Dec 2026 |
| Operating hours | 08:00 to 20:00 |
| Slot start times | 08:00, 10:30, 13:00, 15:30 (4 per day, 40 total) |
| Base exam durations | 60, 90, 120, 180 minutes |
| Extra-time options | 0, 25, 50, 100 percent |
| Longest possible exam | 180 x 2 = 360 minutes, so it must start by 14:00 |
| Exams per course | 1 per term |
| Invigilator ratio | 1 per 50 students, minimum 1 per room |
| Invigilator daily limit | 8 hours (`max_daily_hours`) |
| Invigilator consecutive limit | 4 continuous hours; any positive gap resets the consecutive-work period |
| Room turnover buffer | 0 minutes |
| Anomaly-fixture room closures | Scoped to their `SchedulerRun`; null run means a global closure |
| Accommodated student rule | Allocated to rooms whose interval covers their extended time. First implementation reserves the maximum required duration for everyone sharing that room. |
| Separate-room accommodation | Student is placed in a room with only accommodated students |
| Accommodation share | About 8-10 percent of students |
| Synthetic data | No real personal data. Emails use `@university.example` |

## 7. Accommodation rules

| Type | Effect |
|---|---|
| `EXTRA_TIME` | Student's duration = base x (1 + percent/100) |
| `SEPARATE_ROOM` | Student must be in a room with no non-accommodated students |
| `ACCESSIBLE_ROOM` | Student must be in a room where `is_accessible = true` |

Only accommodations where `effective_from <= exam date` and (`effective_to` is null or `>= exam date`) and `status = ACTIVE` apply. A student may have several accommodations; the strictest combination applies.

## 8. Anomaly types (for ground truth)

| `issue_type` | Injected by | Expected `violation_code` |
|---|---|---|
| `STUDENT_OVERLAP` | Moving an exam into a slot overlapping a connected exam | `STUDENT_DOUBLE_BOOKING` |
| `CAPACITY_EXCEEDED` | Assigning an exam to a room smaller than its allocation | `ROOM_CAPACITY_EXCEEDED` |
| `INVIGILATOR_CLASH` | Giving one invigilator two overlapping assignments | `INVIGILATOR_DOUBLE_BOOKED` |
| `INACTIVE_RESOURCE` | Assigning a room or invigilator whose status is not active | `INACTIVE_ROOM`, `INACTIVE_INVIGILATOR` |
| `DAILY_LIMIT_EXCEEDED` | Giving one invigilator more than their daily limit | `INVIGILATOR_DAILY_LIMIT` |
| `CONSECUTIVE_LIMIT_EXCEEDED` | Assigning a long continuous stretch beyond the policy cap | `INVIGILATOR_CONSECUTIVE_LIMIT` |
| `ACCOMMODATION_BREACH` | Cutting an extended-time student's interval short or using an unsuitable room | `ACCOMMODATION_VIOLATION` |
| `ROOM_CLOSED` | Assigning an exam during a room closure | `ROOM_UNAVAILABLE_VIOLATION` |

`issue_type` is the ground-truth label (what we injected). `violation_code` is what the detector must report. Ground-truth rows point to the specific `assignment_id` affected so evaluation is exact.

## 9. Boundary cases the tests must cover

| Scenario | Expected |
|---|---|
| Students = capacity | Accepted |
| Students = capacity + 1 | Rejected |
| Exam B starts exactly when exam A ends | Accepted |
| Room closes mid-exam | Rejected |
| Invigilator availability exactly covers exam | Accepted |
| Invigilator leaves before exam ends | Rejected |
| Accommodation expired | Not applied |
| Accommodation active | Applied |
| No suitable room | Unassigned with reason |
| Rerun scheduler | Earlier run retained |
| Failed assignment transaction | No partial rows |
| Unknown student ID in lookup | Friendly error |