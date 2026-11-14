"""DSatur exam ordering and half-open interval helpers."""

import datetime as dt


def overlap(first_start, first_end, second_start, second_end):
    return first_start < second_end and second_start < first_end


def buffered_overlap(
    first_start, first_end, second_start, second_end, buffer_minutes=0
):
    if buffer_minutes < 0:
        raise ValueError("buffer_minutes must be non-negative.")
    buffer = dt.timedelta(minutes=buffer_minutes)
    return overlap(
        first_start - buffer,
        first_end + buffer,
        second_start,
        second_end,
    )


def _restriction_score(exam, context):
    requirement = context.exam_requirements.get(exam.exam_id)
    equipment_count = len(
        getattr(context, "exam_equipment", {}).get(exam.exam_id, ())
    )
    return (
        equipment_count,
        requirement.invigilator_ratio if requirement else 50,
    )


def color_exams(graph, students_by_exam, context=None):
    """Return a deterministic DSatur ordering and a time-group color per exam."""
    remaining = {exam.exam_id: exam for exam in graph.exams}
    colors = {}
    ordered = []

    while remaining:
        def priority(exam):
            neighbor_colors = {
                colors[neighbor]
                for neighbor in graph.neighbors(exam.exam_id)
                if neighbor in colors
            }
            restriction = _restriction_score(exam, context) if context else (0, 50)
            return (
                -len(neighbor_colors),
                -graph.degree.get(exam.exam_id, 0),
                -len(students_by_exam.get(exam.exam_id, ())),
                -restriction[0],
                restriction[1],
                -exam.duration_minutes,
                exam.exam_id,
            )

        exam = min(remaining.values(), key=priority)
        used_colors = {
            colors[neighbor]
            for neighbor in graph.neighbors(exam.exam_id)
            if neighbor in colors
        }
        color = 0
        while color in used_colors:
            color += 1
        colors[exam.exam_id] = color
        ordered.append(exam)
        del remaining[exam.exam_id]

    return ordered, colors


def order_exams(graph, students_by_exam, context=None):
    """Return exams in deterministic DSatur priority order."""
    return color_exams(graph, students_by_exam, context)[0]
