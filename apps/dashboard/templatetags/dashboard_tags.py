"""Small template filters used by the dashboard."""

import json

from django import template

from apps.dashboard.permissions import can_run_actions as user_can_run_actions

register = template.Library()


@register.filter
def prettyjson(value):
    try:
        return json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


@register.filter
def tags_for_bootstrap(tags: str) -> str:
    return {"error": "danger", "debug": "secondary"}.get(tags, tags)


@register.filter
def percent(value):
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


@register.filter
def can_run_actions(user):
    return user_can_run_actions(user)
