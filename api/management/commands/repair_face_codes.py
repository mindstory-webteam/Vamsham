"""
python manage.py repair_face_codes            # fix
python manage.py repair_face_codes --dry-run  # only show what would change

Puts every saved face code back in its person's own family, and cleans up what earlier versions left:
  - a face code scanned for someone in family A but filed under family B → moved to family A
  - a face code tied to an account of another family (or the main admin) → untied from that account
  - a face code for a person no longer on the tree → kept as the account's own face if it has one,
    otherwise removed (it can't lead to anyone)
  - links from an account to a person in a different family → removed
Safe to run more than once.
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import FaceProfile, Family, MemberLink
from api.views.face import branch_family, family_account, family_of_user, member_of


class Command(BaseCommand):
    help = "Put every face code in its person's own family and clean up old mistakes."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only show what would change.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        names = dict(Family.objects.values_list("id", "name"))
        before = Counter(FaceProfile.all_objects.values_list("family_id", flat=True))
        done = Counter()
        with transaction.atomic():
            for link in MemberLink.all_objects.exclude(member_id=None).select_related("user"):
                bf, uf = branch_family(link.branch), family_of_user(link.user)
                if bf and uf and bf != uf and not link.user.is_superuser:
                    done["wrong links removed"] += 1
                    self.stdout.write(f"  link {link.user} → {link.branch}:{link.member_id}: different family, removed")
                    if not dry:
                        link.delete()
                elif bf and link.user.is_superuser:
                    done["main-admin links removed"] += 1
                    if not dry:
                        link.delete()

            for p in FaceProfile.all_objects.select_related("user").order_by("pk"):
                label = f"face #{p.pk} ({p.branch or '-'}:{p.member_id or '-'}, account {p.user or '-'})"
                if p.member_id:
                    if member_of(p) is None:
                        if p.user_id and not p.user.is_superuser:
                            done["kept as account face (person gone)"] += 1
                            self.stdout.write(f"  {label}: person no longer on the tree → kept for the account only")
                            if not dry:
                                p.branch, p.member_id = "", None
                                p.save()
                        else:
                            done["removed (person gone)"] += 1
                            self.stdout.write(f"  {label}: person no longer on the tree → removed")
                            if not dry:
                                p.delete()
                        continue
                    fam = branch_family(p.branch)
                    if p.user_id and family_account(p.user, fam) is None:
                        done["untied from another family's account"] += 1
                        self.stdout.write(f"  {label}: account is in another family → untied")
                        if not dry:
                            p.user = None
                    if fam and fam != p.family_id:
                        done["moved to the right family"] += 1
                        self.stdout.write(f"  {label}: {names.get(p.family_id)} → {names.get(fam)}")
                    if not dry:
                        p.family_id = fam or p.family_id
                        p.save()
                    continue
                # a face code for an account only (set up on their own phone)
                if p.user_id is None or p.user.is_superuser:
                    if p.user_id is None:
                        done["removed (leads to nobody)"] += 1
                        self.stdout.write(f"  {label}: leads to nobody → removed")
                        if not dry:
                            p.delete()
                    continue
                uf = family_of_user(p.user)
                if uf and uf != p.family_id:
                    done["moved to the right family"] += 1
                    self.stdout.write(f"  {label}: {names.get(p.family_id)} → {names.get(uf)}")
                    if not dry:
                        p.save()  # save() files it under the account's family
            if dry:
                transaction.set_rollback(True)

        after = Counter(FaceProfile.all_objects.values_list("family_id", flat=True))
        self.stdout.write("")
        for what, n in done.items():
            self.stdout.write(f"{what}: {n}")
        if not done:
            self.stdout.write("Everything was already in order.")
        self.stdout.write("\nFace codes per family" + (" (now — dry run, nothing saved)" if dry else "") + ":")
        for fid in sorted(set(before) | set(after), key=lambda f: names.get(f, "")):
            self.stdout.write(f"  {names.get(fid, fid)}: {before.get(fid, 0)} → {after.get(fid, 0)}")
