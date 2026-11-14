"""Generate deterministic, weighted Student-Course bridge rows."""

from apps.core.services.id_generator import make_id

from .config import TERM, TERM_START


def _weighted_sample(rng, items, weights, count):
    """Sample without replacement using the provided positive weights."""
    remaining_items = list(items)
    remaining_weights = list(weights)
    chosen = []
    for _ in range(min(count, len(remaining_items))):
        total = sum(remaining_weights)
        if total <= 0:
            break
        value = rng.uniform(0, total)
        cumulative = 0.0
        for index, weight in enumerate(remaining_weights):
            cumulative += weight
            if value <= cumulative:
                chosen.append(remaining_items.pop(index))
                remaining_weights.pop(index)
                break
    return chosen


def generate_enrollments(rng, students, courses, courses_with_exams_ids):
    exam_courses = [
        course for course in courses
        if course["course_id"] in courses_with_exams_ids
    ]
    popularity = {
        course["course_id"]: rng.paretovariate(1.5)
        for course in exam_courses
    }

    enrollments = []
    index = 1
    for student in students:
        own_department = [
            course for course in exam_courses
            if course["department"] == student["department"]
        ]
        other_departments = [
            course for course in exam_courses
            if course["department"] != student["department"]
        ]
        target_count = rng.randint(4, 6)
        target_own = max(0, min(target_count - 1, round(target_count * 0.6)))

        chosen = []
        if own_department:
            chosen.extend(
                _weighted_sample(
                    rng,
                    own_department,
                    [popularity[course["course_id"]] for course in own_department],
                    target_own,
                )
            )
        remaining_count = target_count - len(chosen)
        if remaining_count and other_departments:
            chosen.extend(
                _weighted_sample(
                    rng,
                    other_departments,
                    [popularity[course["course_id"]] for course in other_departments],
                    remaining_count,
                )
            )
        if len(chosen) < min(target_count, len(exam_courses)):
            already_chosen = {course["course_id"] for course in chosen}
            fallback = [
                course for course in exam_courses
                if course["course_id"] not in already_chosen
            ]
            chosen.extend(
                _weighted_sample(
                    rng,
                    fallback,
                    [popularity[course["course_id"]] for course in fallback],
                    min(target_count - len(chosen), len(fallback)),
                )
            )

        for course in chosen:
            enrollments.append(
                dict(
                    enrollment_id=make_id("enrollment", index),
                    student_id=student["student_id"],
                    course_id=course["course_id"],
                    term=TERM,
                    status="ACTIVE",
                    effective_from=TERM_START,
                    effective_to=None,
                )
            )
            index += 1
    return enrollments
