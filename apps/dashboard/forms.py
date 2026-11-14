"""Filters used by dashboard pages."""

from django import forms

from apps.core.models import Department, Invigilator, Room


class TimetableFilterForm(forms.Form):
    date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    exam = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "EXAM-2026-000042"}
        ),
    )
    course = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "CS101 or CRS-000042"}
        ),
    )
    room = forms.ModelChoiceField(
        queryset=Room.objects.filter(status=Room.Status.ACTIVE).order_by("room_id"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    invigilator = forms.ModelChoiceField(
        queryset=Invigilator.objects.filter(
            status=Invigilator.Status.ACTIVE
        ).order_by("invigilator_id"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    department = forms.ChoiceField(
        choices=[("", "All departments"), *Department.choices],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
