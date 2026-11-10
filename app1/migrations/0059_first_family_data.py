"""Existing profiles, events, memories and family photos belong to the first family."""
from django.db import migrations


def forwards(apps, schema_editor):
    fam = apps.get_model("api", "Family").objects.order_by("id").first()
    if fam is None:
        return
    for model in ("Profile", "Event", "Memory", "FamilyPhoto"):
        apps.get_model("app1", model).objects.filter(family__isnull=True).update(family=fam)


class Migration(migrations.Migration):
    dependencies = [("app1", "0058_family_scope"), ("api", "0007_first_family")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
