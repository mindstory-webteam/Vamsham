"""
Run once a day (e.g. cron at 7:00 AM):

    python manage.py send_daily_greetings

Tells every approved app user about today's birthdays, anniversaries and
remembrance days in the family.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q

from api.notify import notify
from api.people import today_items


class Command(BaseCommand):
    help = "Send today's birthdays / anniversaries / remembrance days as app notifications"

    def handle(self, *args, **opts):
        # many families: each family only hears about its own people
        from api.models import Family
        from api.tenancy import reset_current_family, set_current_family
        for fam in Family.objects.filter(is_active=True):
            token = set_current_family(fam.id)
            try:
                self.stdout.write(f"{fam.name}: ")
                self.one_family()
            finally:
                reset_current_family(token)

    def one_family(self):
        t = today_items()
        lines = []
        for b in t["birthdays"]:
            lines.append(f"{b['name']} turns {b['turning']}")
        for a in t["anniversaries"]:
            who = a["person"]["first_name"] + (f" & {a['partner']['first_name']}" if a["partner"] else "")
            lines.append(f"{who}: {a['years']} years married")
        for r in t["remembrance"]:
            lines.append(f"Remembering {r['name']} ({r['years']} years)")
        if not lines:
            self.stdout.write("Nothing to send today.")
            return
        User = get_user_model()
        from api.tenancy import family_users
        users = list(family_users(User.objects.filter(is_active=True).filter(Q(profile__is_approved=True) | Q(is_staff=True))))
        n = notify(users, "Today in the family", " · ".join(lines)[:900], kind="today")
        self.stdout.write(self.style.SUCCESS(f"Sent to {n} people: {len(lines)} items"))
