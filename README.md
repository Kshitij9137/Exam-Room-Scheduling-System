# Exam & Room Scheduling System

Django + SQLite + Bootstrap. Status: **Phase 3 complete** (schema, deterministic synthetic data, validation, exports, and reproducibility checks).

## Setup
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py generate_data --seed 20261022 --scale starter
python manage.py validate_data
python manage.py export_data
python manage.py verify_reproducibility --seed 20261022 --scale starter
python manage.py runserver      # http://127.0.0.1:8000  and /admin/
python manage.py test           # all tests
```
See `docs/` for architecture, business rules, ER diagram and data dictionary.

Use `--scale full` to generate the required 5,000-student dataset. To replace
existing generated data before a scheduling history exists, add `--force`.
Exports are written under `data/exports/`; generation metadata, validation and
reproducibility summaries are written under `data/`.
