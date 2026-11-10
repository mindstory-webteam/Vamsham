"""Today's data becomes the first family; every existing person gets access to it."""
from django.db import migrations
from django.utils.text import slugify


def forwards(apps, schema_editor):
    Family = apps.get_model("api", "Family")
    Settings = apps.get_model("api", "AssociationSettings")
    s = Settings.objects.order_by("pk").first()
    name = (s.family_name if s and s.family_name else "Vamsham").strip() or "Vamsham"
    fam = Family.objects.order_by("id").first()
    if fam is None:
        fam = Family.objects.create(name=name, slug=slugify(name)[:40] or "vamsham", color="#3FD47A")
    for model in ("FamilyBranch", "MemberLink", "ChangeRequest", "NewMemberRequest", "BloodRequest",
                  "Broadcast", "Payment", "FaceProfile", "AssociationSettings"):
        apps.get_model("api", model).objects.filter(family__isnull=True).update(family=fam)
    User = apps.get_model("auth", "User")
    Access = apps.get_model("api", "FamilyAccess")
    have = set(Access.objects.values_list("user_id", flat=True))
    Access.objects.bulk_create([Access(user_id=u, family=fam) for u in User.objects.exclude(pk__in=have).values_list("pk", flat=True)])
    # admin-scanned faces don't have a user; existing ones do: copy their member link
    Link = apps.get_model("api", "MemberLink")
    for fp in apps.get_model("api", "FaceProfile").objects.filter(user__isnull=False, member_id__isnull=True):
        ln = Link.objects.filter(user_id=fp.user_id).first()
        if ln:
            fp.branch, fp.member_id = ln.branch, ln.member_id
            fp.save(update_fields=["branch", "member_id"])


class Migration(migrations.Migration):
    dependencies = [("api", "0006_families")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
