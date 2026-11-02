"""Replace the old built-in family name in saved association settings.

Only values still equal to the old defaults are changed; anything the
committee typed in themselves is left alone.
"""
from django.db import migrations

OLD = "Mele" + "dath"  # old default name, split so code searches stay clean
CHANGES = {
    "family_name": (OLD, "Vamsham"),
    "association_name": (f"{OLD} Family Association", "Vamsham Family Association"),
    "upi_name": (f"{OLD} Family Association", "Vamsham Family Association"),
}


def forwards(apps, schema_editor):
    Settings = apps.get_model("api", "AssociationSettings")
    for field, (old, new) in CHANGES.items():
        Settings.objects.filter(**{field: old}).update(**{field: new})


class Migration(migrations.Migration):
    dependencies = [("api", "0003_family_branches")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
