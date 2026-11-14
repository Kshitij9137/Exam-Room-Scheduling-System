from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from apps.core.services.id_generator import PATTERNS


def id_validator(kind: str) -> RegexValidator:
    return RegexValidator(PATTERNS[kind], message=f"Invalid {kind} ID format.")


term_validator = RegexValidator(r"^\d{4}-(FALL|SPRING)$", message="Term must look like 2026-FALL.")
code_validator = RegexValidator(r"^[A-Z_]+$", message="Use upper-case letters and underscores.")


def validate_multiple_of_15(value):
    if value % 15 != 0:
        raise ValidationError("Duration must be a multiple of 15 minutes.")

course_code_validator = RegexValidator(r"^[A-Z]{2,4}\d{3}$", message="Course code must look like CS101.")
