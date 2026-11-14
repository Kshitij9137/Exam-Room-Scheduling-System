from django.shortcuts import render

from apps.core.models import Course, Exam, Invigilator, Room, Student


def home(request):
    """Placeholder landing page. The full dashboard is built in Phase 6."""
    context = {
        "counts": [
            ("Students", Student.objects.count()),
            ("Courses", Course.objects.count()),
            ("Exams", Exam.objects.count()),
            ("Rooms", Room.objects.count()),
            ("Invigilators", Invigilator.objects.count()),
        ]
    }
    return render(request, "dashboard/home.html", context)
