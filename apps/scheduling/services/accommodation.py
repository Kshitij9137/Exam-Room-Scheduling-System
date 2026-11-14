"""Resolve effective student accommodations for an exam date."""

from django.db.models import Q

from apps.core.models import Accommodation


def accommodations_active_on(student_id, on_date):
    return list(
        Accommodation.objects.filter(
            student_id=student_id,
            status=Accommodation.Status.ACTIVE,
            effective_from__lte=on_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=on_date))
        .order_by("accommodation_id")
    )


def active_accommodations(accommodations, on_date):
    """Filter preloaded accommodations without issuing per-student queries."""
    return [
        accommodation
        for accommodation in accommodations
        if accommodation.status == Accommodation.Status.ACTIVE
        and accommodation.effective_from <= on_date
        and (
            accommodation.effective_to is None
            or accommodation.effective_to >= on_date
        )
    ]


def required_minutes(base_minutes, accommodations):
    extra_time_percent = max(
        (
            accommodation.extra_time_percent
            for accommodation in accommodations
            if accommodation.accommodation_type == Accommodation.Type.EXTRA_TIME
        ),
        default=0,
    )
    return (base_minutes * (100 + extra_time_percent) + 99) // 100


def needs_separate_room(accommodations):
    return any(
        accommodation.accommodation_type == Accommodation.Type.SEPARATE_ROOM
        for accommodation in accommodations
    )


def needs_accessible_room(accommodations):
    return any(
        accommodation.accommodation_type == Accommodation.Type.ACCESSIBLE_ROOM
        for accommodation in accommodations
    )
