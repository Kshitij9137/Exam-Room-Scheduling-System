import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from apps.core.models import (
    Accommodation,
    Course,
    Enrollment,
    Equipment,
    Exam,
    ExamRequirement,
    ExamRequirementEquipment,
    Invigilator,
    Room,
    RoomCapacity,
    RoomEquipment,
    Student,
)
from apps.core.services.data_generator import (
    clear_generated_data,
    generate_and_persist,
)
from apps.scheduling.models import Availability, RoomClosure, TimeSlot
from generator.config import SCALES, SEED_DEFAULT


class Command(BaseCommand):
    help = "Generate deterministic synthetic master data."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=SEED_DEFAULT)
        parser.add_argument(
            "--scale", choices=sorted(SCALES), default="starter"
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Clear generated data before generating.",
        )

    def handle(self, *args, **options):
        model_classes = (
            Student, Course, Exam, Room, Invigilator, Enrollment,
            Accommodation, Availability, RoomClosure, TimeSlot, Equipment,
            ExamRequirement, ExamRequirementEquipment, RoomCapacity,
            RoomEquipment,
        )
        has_data = any(model.objects.exists() for model in model_classes)
        if has_data and not options["force"]:
            raise CommandError(
                "Generated data already exists. Use --force to replace it."
            )

        try:
            with transaction.atomic():
                if options["force"]:
                    clear_generated_data()
                stats = generate_and_persist(
                    seed=options["seed"],
                    scale=options["scale"],
                )
        except (RuntimeError, ProtectedError) as error:
            raise CommandError(str(error)) from error

        manifest_path = Path(settings.BASE_DIR) / "data" / "generation_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(stats, indent=2) + "\n",
            encoding="utf-8",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Generated seed={stats['seed']} scale={stats['scale']}: "
                f"{stats['students']} students, {stats['courses']} courses, "
                f"{stats['exams']} exams, {stats['rooms']} rooms, "
                f"{stats['invigilators']} invigilators, "
                f"{stats['enrollments']} enrollments, "
                f"{stats['accommodations']} accommodations, "
                f"{stats['timeslots']} timeslots."
            )
        )
