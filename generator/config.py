"""Deterministic generator configuration."""

SEED_DEFAULT = 20261022
TERM = "2026-FALL"
EXAM_YEAR = 2026

EXAM_DATES = [
    "2026-12-07", "2026-12-08", "2026-12-09", "2026-12-10", "2026-12-11",
    "2026-12-14", "2026-12-15", "2026-12-16", "2026-12-17", "2026-12-18",
]
SLOT_STARTS = ["08:00", "10:30", "13:00", "15:30"]

SCALES = {
    "starter": {
        "students": 200,
        "courses": 30,
        "exams": 20,
        "rooms": 15,
        "invigilators": 25,
    },
    "full": {
        "students": 5000,
        "courses": 300,
        "exams": 300,
        "rooms": 100,
        "invigilators": 200,
    },
}

DEPARTMENTS = ["CS", "EE", "ME", "CE", "BIO", "CHEM", "MATH", "PHY", "BUS", "ARTS"]

EQUIPMENT = {
    "PROJECTOR": "Ceiling projector",
    "COMPUTER": "Desktop computer",
    "LAB_BENCH": "Wet-lab bench",
    "ACCESSIBLE_DESK": "Accessible-height desk",
    "WHITEBOARD": "Whiteboard",
}

EXAM_DURATIONS = [60, 90, 120, 180]

TERM_START = "2026-09-01"
ACC_EFFECTIVE_FROM = "2026-09-01"
ACC_EFFECTIVE_TO = "2026-12-31"

ACCOMMODATION_PCT = 0.09
