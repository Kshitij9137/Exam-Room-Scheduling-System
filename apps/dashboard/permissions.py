"""Role-based helpers backed by Django Groups."""

from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_POST


def user_roles(user) -> set[str]:
    if not user.is_authenticated:
        return set()
    if user.is_superuser or user.is_staff:
        return {settings.ROLE_PLATFORM_ADMIN}
    return set(user.groups.values_list("name", flat=True))


def can_run_actions(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name=settings.ROLE_ADMINISTRATOR).exists()


def staff_required(view_func):
    """Require authentication, POST, and an action-capable role."""

    @wraps(view_func)
    @login_required
    @require_POST
    def wrapper(request, *args, **kwargs):
        if not can_run_actions(request.user):
            messages.error(
                request,
                "This action requires the Academic Administrator role or staff status.",
            )
            return redirect("dashboard:home")
        return view_func(request, *args, **kwargs)

    return wrapper
