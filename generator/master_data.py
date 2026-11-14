"""Django-independent synthetic master-data generators."""

import datetime as dt

from apps.core.services.id_generator import make_exam_id, make_id

from .config import (
    ACC_EFFECTIVE_FROM,
    ACC_EFFECTIVE_TO,
    ACCOMMODATION_PCT,
    DEPARTMENTS,
    EQUIPMENT,
    EXAM_DATES,
    EXAM_DURATIONS,
    EXAM_YEAR,
    SLOT_STARTS,
    TERM,
    TERM_START,
)


def _date(value):
    return dt.date.fromisoformat(value)


def _time(value):
    hour, minute = value.split(":")
    return dt.time(int(hour), int(minute))


def generate_equipment():
    return [dict(code=code, name=name) for code, name in EQUIPMENT.items()]


def generate_timeslots():
    slots = []
    for index, (day, start) in enumerate(
        ((day, start) for day in EXAM_DATES for start in SLOT_STARTS),
        start=1,
    ):
        slots.append(
            dict(
                slot_id=make_id("slot", index),
                slot_date=_date(day),
                start_time=_time(start),
                label=f"{day} {start}",
            )
        )
    return slots


def generate_students(rng, count):
    return [
        dict(
            student_id=make_id("student", index),
            full_name=f"Student {index:05d}",
            email=f"stu{index:06d}@university.example",
            department=rng.choice(DEPARTMENTS),
            year_level=rng.randint(1, 4),
            status="ACTIVE",
        )
        for index in range(1, count + 1)
    ]


def generate_courses(rng, count):
    courses = []
    for index in range(1, count + 1):
        department = DEPARTMENTS[(index - 1) % len(DEPARTMENTS)]
        courses.append(
            dict(
                course_id=make_id("course", index),
                course_code=f"{department}{100 + index}",
                title=f"{department} Course {index}",
                department=department,
                credits=rng.choice([3, 3, 3, 4, 4, 6]),
            )
        )
    return courses


def generate_exams(rng, courses, count):
    return [
        dict(
            exam_id=make_exam_id(index, EXAM_YEAR),
            course_id=courses[index - 1]["course_id"],
            title=f"Exam for {courses[index - 1]['course_code']}",
            term=TERM,
            duration_minutes=rng.choice(EXAM_DURATIONS),
            status="PLANNED",
        )
        for index in range(1, count + 1)
    ]


def generate_rooms_and_capacities(rng, count):
    rooms = []
    capacities = []
    per_building = max(1, (count + 4) // 5)
    for index in range(1, count + 1):
        building_index = (index - 1) // per_building
        building_letter = chr(65 + building_index)
        room_number = (index - 1) % per_building + 1
        room_type = rng.choices(
            ["LECTURE_HALL", "CLASSROOM", "COMPUTER_LAB", "SCIENCE_LAB"],
            weights=[0.20, 0.50, 0.15, 0.15],
            k=1,
        )[0]
        if room_type == "LECTURE_HALL":
            capacity = rng.randint(200, 500)
        elif room_type == "CLASSROOM":
            capacity = rng.randint(30, 80)
        else:
            capacity = rng.randint(20, 40)

        room_id = make_id("room", index)
        rooms.append(
            dict(
                room_id=room_id,
                building=f"Block {building_letter}",
                room_number=f"{building_letter}-{room_number:03d}",
                room_type=room_type,
                is_accessible=rng.random() < 0.30,
                status="ACTIVE",
            )
        )
        capacities.append(
            dict(
                capacity_id=make_id("capacity", index),
                room_id=room_id,
                exam_capacity=capacity,
                effective_from=_date(TERM_START),
                effective_to=None,
            )
        )
    for room in rooms:
        if room["room_type"] == "LECTURE_HALL":
            room["is_accessible"] = True
    return rooms, capacities


def generate_room_equipment_pairs(rooms):
    pairs = []
    for room in rooms:
        equipment = {"WHITEBOARD"}
        if room["room_type"] == "LECTURE_HALL":
            equipment.update({"COMPUTER", "LAB_BENCH", "PROJECTOR"})
        elif room["room_type"] == "COMPUTER_LAB":
            equipment.update({"COMPUTER", "PROJECTOR"})
        elif room["room_type"] == "SCIENCE_LAB":
            equipment.add("LAB_BENCH")
        if room["is_accessible"]:
            equipment.add("ACCESSIBLE_DESK")
        pairs.extend((room["room_id"], code) for code in sorted(equipment))
    return pairs


def generate_invigilators(rng, count):
    from decimal import Decimal

    return [
        dict(
            invigilator_id=make_id("invigilator", index),
            full_name=f"Invigilator {index:05d}",
            email=f"inv{index:06d}@university.example",
            department=rng.choice(DEPARTMENTS),
            max_daily_hours=Decimal(str(rng.choice([6.0, 7.0, 8.0]))),
            status="ACTIVE",
        )
        for index in range(1, count + 1)
    ]


def generate_room_availability(rooms):
    start = dt.datetime(2026, 12, 7, 8, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 12, 18, 20, tzinfo=dt.timezone.utc)
    return [
        dict(
            availability_id=make_id("availability", index),
            room_id=room["room_id"],
            invigilator_id=None,
            start_at=start,
            end_at=end,
        )
        for index, room in enumerate(rooms, start=1)
    ]


def generate_room_closures(rng, rooms):
    closures = []
    count = max(1, len(rooms) // 20)
    for index, room in enumerate(rng.sample(rooms, min(count, len(rooms))), start=1):
        day = rng.choice(EXAM_DATES)
        start_hour = rng.choice([8, 9, 10, 13, 15])
        end_hour = start_hour + rng.choice([1, 2, 3])
        closures.append(
            dict(
                closure_id=make_id("closure", index),
                room_id=room["room_id"],
                start_at=dt.datetime.fromisoformat(day).replace(
                    hour=start_hour, tzinfo=dt.timezone.utc
                ),
                end_at=dt.datetime.fromisoformat(day).replace(
                    hour=end_hour, tzinfo=dt.timezone.utc
                ),
                reason=rng.choice(["MAINTENANCE", "EVENT", "REPAIR"]),
            )
        )
    return closures


def generate_invigilator_availability(rng, invigilators, start_index=1):
    availability = []
    index = start_index
    for invigilator in invigilators:
        window_count = rng.randint(4, 7)
        for day in rng.sample(EXAM_DATES, min(window_count, len(EXAM_DATES))):
            availability.append(
                dict(
                    availability_id=make_id("availability", index),
                    room_id=None,
                    invigilator_id=invigilator["invigilator_id"],
                    start_at=dt.datetime.fromisoformat(day).replace(
                        hour=8, tzinfo=dt.timezone.utc
                    ),
                    end_at=dt.datetime.fromisoformat(day).replace(
                        hour=20, tzinfo=dt.timezone.utc
                    ),
                )
            )
            index += 1
    return availability


def generate_accommodations(rng, students):
    count = min(len(students), max(1, int(len(students) * ACCOMMODATION_PCT)))
    accommodations = []
    for index, student in enumerate(rng.sample(students, count), start=1):
        accommodation_type = rng.choices(
            ["EXTRA_TIME", "SEPARATE_ROOM", "ACCESSIBLE_ROOM"],
            weights=[0.60, 0.20, 0.20],
            k=1,
        )[0]
        extra_time_percent = (
            rng.choice([25, 50, 100]) if accommodation_type == "EXTRA_TIME" else 0
        )
        accommodations.append(
            dict(
                accommodation_id=make_id("accommodation", index),
                student_id=student["student_id"],
                accommodation_type=accommodation_type,
                extra_time_percent=extra_time_percent,
                effective_from=_date(ACC_EFFECTIVE_FROM),
                effective_to=_date(ACC_EFFECTIVE_TO),
                status="ACTIVE",
            )
        )
    return accommodations


def generate_exam_requirements(rng, exams, courses_by_id):
    requirements = []
    equipment_pairs = []
    for index, exam in enumerate(exams, start=1):
        course = courses_by_id[exam["course_id"]]
        required_equipment = set()
        if course["department"] in ("CS", "BUS"):
            required_equipment.add("COMPUTER")
        if course["department"] in ("BIO", "CHEM", "PHY"):
            required_equipment.add("LAB_BENCH")
        if rng.random() < 0.5:
            required_equipment.add("PROJECTOR")

        requirement_id = make_id("requirement", index)
        requirements.append(
            dict(
                requirement_id=requirement_id,
                exam_id=exam["exam_id"],
                allow_multi_room=True,
                invigilator_ratio=50,
            )
        )
        equipment_pairs.extend(
            (requirement_id, code) for code in sorted(required_equipment)
        )
    return requirements, equipment_pairs
