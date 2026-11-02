# Django (Python)

Run `manage.py` inside the project's own environment — its virtualenv, or `uv run python
manage.py …` in a uv project — so the Django version matches the one the migrations were
written against (`python -m django --version`).

## Workflow

```bash
# Generate migration from model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Show migration status
python manage.py showmigrations

# Generate empty migration for custom SQL
python manage.py makemigrations --empty app_name -n description
```

## Data Migration

`atomic = False` is what makes the batching real — without it Django wraps the whole `RunPython`
in one transaction and the loop becomes a single giant transaction wearing a loop.
This example assumes non-empty, non-null `username` values and writers that populate `display_name`.
Use the schema editor's DB alias for every operation. Recheck the empty-value predicate in the
UPDATE and read `username` there, so a concurrent user edit is not overwritten by a stale object.

```python
from django.db import migrations, transaction
from django.db.models import F

def backfill_display_names(apps, schema_editor):
    Member = apps.get_model("accounts", "Member")
    alias = schema_editor.connection.alias
    members = Member.objects.using(alias)
    batch_size = 5000
    while True:
        with transaction.atomic(using=alias):  # one committed transaction per batch
            ids = list(
                members.filter(display_name="").order_by("pk")
                .values_list("pk", flat=True)[:batch_size]
            )
            if not ids:
                break
            members.filter(pk__in=ids, display_name="").update(display_name=F("username"))

def reverse_backfill(apps, schema_editor):
    pass  # data migration — nothing to reverse

class Migration(migrations.Migration):
    atomic = False                          # required: lets each batch commit on its own
    dependencies = [("accounts", "0015_add_display_name")]

    operations = [
        migrations.RunPython(backfill_display_names, reverse_backfill),
    ]
```

## SeparateDatabaseAndState

Remove a column from the Django model without dropping it from the database immediately:

```python
class Migration(migrations.Migration):
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="user", name="legacy_field"),
            ],
            database_operations=[],  # Don't touch the DB yet
        ),
    ]
```
