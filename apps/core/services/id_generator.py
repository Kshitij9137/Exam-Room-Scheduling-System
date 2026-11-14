"""Deterministic, zero-padded ID helpers.

IDs are built from counters (never random) and are never created in Model.save().
"""
import re

PATTERNS = {
    "student": r"^STU-\d{6}$",
    "course": r"^CRS-\d{6}$",
    "enrollment": r"^ENR-\d{6}$",
    "exam": r"^EXAM-\d{4}-\d{6}$",
    "requirement": r"^REQ-\d{6}$",
    "room": r"^ROOM-\d{6}$",
    "capacity": r"^CAP-\d{6}$",
    "closure": r"^CLS-\d{6}$",
    "invigilator": r"^INV-\d{6}$",
    "availability": r"^AVL-\d{6}$",
    "accommodation": r"^ACC-\d{6}$",
    "slot": r"^SLOT-\d{6}$",
    "run": r"^RUN-\d{6}$",
    "assignment": r"^ASN-EXAM-\d{4}-\d{6}-ROOM-\d{6}-RUN-\d{6}$",
    "invigilator_assignment": r"^IAS-\d{6}$",
    "student_allocation": r"^SRA-\d{6}$",
    "unassigned": r"^UNA-\d{6}$",
    "event": r"^EVT-\d{6}$",
    "validation_run": r"^VAL-\d{6}$",
    "violation": r"^VIO-\d{6}$",
}

PREFIXES = {
    "student": "STU",
    "course": "CRS",
    "enrollment": "ENR",
    "requirement": "REQ",
    "room": "ROOM",
    "capacity": "CAP",
    "closure": "CLS",
    "invigilator": "INV",
    "availability": "AVL",
    "accommodation": "ACC",
    "slot": "SLOT",
    "run": "RUN",
    "invigilator_assignment": "IAS",
    "student_allocation": "SRA",
    "unassigned": "UNA",
    "event": "EVT",
    "validation_run": "VAL",
    "violation": "VIO",
}


def make_id(kind: str, number: int) -> str:
    """make_id('student', 1) -> 'STU-000001'."""
    if number < 1 or number > 999999:
        raise ValueError("number must be between 1 and 999999")
    return f"{PREFIXES[kind]}-{number:06d}"


def make_exam_id(number: int, year: int = 2026) -> str:
    """make_exam_id(1) -> 'EXAM-2026-000001'."""
    if number < 1 or number > 999999:
        raise ValueError("number must be between 1 and 999999")
    return f"EXAM-{year}-{number:06d}"


def make_assignment_id(exam_id: str, room_id: str, run_id: str) -> str:
    """ASN-<exam-id>-<room-id>-<run-id>."""
    return f"ASN-{exam_id}-{room_id}-{run_id}"


def is_valid(kind: str, value: str) -> bool:
    return bool(re.match(PATTERNS[kind], value or ""))
