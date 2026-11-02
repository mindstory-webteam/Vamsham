"""Events, photos, memories, reports, blood requests and notifications."""
from datetime import date, datetime, timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app1.models import AnnualReport, Event, FamilyPhoto, Memory

from ..branches import all_models
from ..models import (BLOOD_GROUPS, BloodRequest, BloodResponse, DonorStatus, EventRSVP,
                      MemberLink, MemoryPrayer, Notification)
from ..notify import notify
from ..people import summary
from ..permissions import IsApproved
from .common import paginate


def abs_url(request, f):
    try:
        return request.build_absolute_uri(f.url) if f else None
    except ValueError:
        return None


# ── Events ───────────────────────────────────────────────────────────────────

def event_payload(e, request, full=False):
    totals = e.rsvps.filter(attending=True).aggregate(people=Sum("people"), families=Count("id"))
    mine = e.rsvps.filter(user=request.user).first() if request.user.is_authenticated else None
    images = list(e.images.all())
    data = {
        "id": e.id,
        "title": e.title,
        "category": e.category,
        "date": e.date.isoformat(),
        "time": e.start_time.strftime("%H:%M") if e.start_time else None,
        "location": e.location,
        "is_upcoming": e.date >= date.today(),
        "days_to_go": (e.date - date.today()).days,
        "rsvp_enabled": e.rsvp_enabled,
        "going_people": totals["people"] or 0,
        "going_families": totals["families"] or 0,
        "my_rsvp": {"people": mine.people, "attending": mine.attending} if mine else None,
        "cover": abs_url(request, images[0].image) if images else None,
        "photo_count": len(images),
    }
    if full:
        data["description"] = e.description
        data["programme"] = [line.strip() for line in (e.programme or "").splitlines() if line.strip()]
        data["images"] = [{"url": abs_url(request, i.image), "caption": i.caption} for i in images]
    return data


class EventListView(APIView):
    """GET ?when=upcoming|past"""
    permission_classes = [IsApproved]

    def get(self, request):
        today = date.today()
        qs = Event.objects.prefetch_related("images", "rsvps")
        if request.query_params.get("when") == "past":
            qs = qs.filter(date__lt=today).order_by("-date")
        else:
            qs = qs.filter(date__gte=today).order_by("date")
        return Response([event_payload(e, request) for e in qs[:100]])


class EventDetailView(APIView):
    permission_classes = [IsApproved]

    def get(self, request, pk):
        e = Event.objects.filter(pk=pk).prefetch_related("images", "rsvps").first()
        if not e:
            return Response({"detail": "Event not found."}, status=404)
        return Response(event_payload(e, request, full=True))


class RSVPView(APIView):
    """POST {people: 4, attending: true}"""
    permission_classes = [IsApproved]

    def post(self, request, pk):
        e = Event.objects.filter(pk=pk).first()
        if not e:
            return Response({"detail": "Event not found."}, status=404)
        if not e.rsvp_enabled:
            return Response({"detail": "RSVP is not open for this event."}, status=400)
        try:
            people = max(1, min(50, int(request.data.get("people", 1))))
        except (TypeError, ValueError):
            return Response({"detail": "people must be a number"}, status=400)
        attending = request.data.get("attending", True) not in (False, "false", "0", 0)
        EventRSVP.objects.update_or_create(event=e, user=request.user,
                                           defaults={"people": people, "attending": attending})
        return Response(event_payload(e, request, full=True))


# ── Photos ───────────────────────────────────────────────────────────────────

class AlbumListView(APIView):
    """Event photo albums plus the family photo gallery grouped by year."""
    permission_classes = [IsApproved]

    def get(self, request):
        albums = []
        for e in Event.objects.annotate(n=Count("images")).filter(n__gt=0).prefetch_related("images"):
            first = e.images.first()
            albums.append({"id": f"event-{e.id}", "title": e.title, "year": str(e.date.year),
                           "count": e.n, "cover": abs_url(request, first.image) if first else None})
        years = {}
        for p in FamilyPhoto.objects.all():
            y = p.year or "Other"
            years.setdefault(y, []).append(p)
        for y, photos in years.items():
            albums.append({"id": f"family-{y}", "title": f"Family photos {y}", "year": y,
                           "count": len(photos), "cover": abs_url(request, photos[0].image)})
        year = request.query_params.get("year")
        if year:
            albums = [a for a in albums if a["year"].startswith(year)]
        albums.sort(key=lambda a: a["year"], reverse=True)
        return Response(albums)


class AlbumDetailView(APIView):
    permission_classes = [IsApproved]

    def get(self, request, album_id):
        kind, _, key = album_id.partition("-")
        if kind == "event" and key.isdigit():
            e = Event.objects.filter(pk=int(key)).first()
            if not e:
                return Response({"detail": "Album not found."}, status=404)
            photos = [{"url": abs_url(request, i.image), "caption": i.caption} for i in e.images.all()]
            return Response({"id": album_id, "title": e.title, "photos": photos})
        if kind == "family":
            qs = FamilyPhoto.objects.filter(year=key) if key != "Other" else FamilyPhoto.objects.filter(year="")
            photos = [{"url": abs_url(request, p.image), "caption": p.caption or p.title} for p in qs]
            return Response({"id": album_id, "title": f"Family photos {key}", "photos": photos})
        return Response({"detail": "Album not found."}, status=404)


# ── Memories ─────────────────────────────────────────────────────────────────

def memory_payload(m, request, full=False):
    data = {
        "id": m.id, "name": m.name,
        "birth_date": m.birth_date.isoformat(), "death_date": m.death_date.isoformat(),
        "years": f"{m.birth_date.year} – {m.death_date.year}",
        "image": abs_url(request, m.image),
        "prayers": m.prayers.count(),
        "prayed": m.prayers.filter(user=request.user).exists(),
    }
    if full:
        data["description"] = m.description
    return data


class MemoryListView(APIView):
    permission_classes = [IsApproved]

    def get(self, request):
        return Response([memory_payload(m, request) for m in Memory.objects.order_by("-death_date")])


class MemoryDetailView(APIView):
    permission_classes = [IsApproved]

    def get(self, request, pk):
        m = Memory.objects.filter(pk=pk).first()
        if not m:
            return Response({"detail": "Not found."}, status=404)
        return Response(memory_payload(m, request, full=True))

    def post(self, request, pk):
        """Light a candle / say a prayer."""
        m = Memory.objects.filter(pk=pk).first()
        if not m:
            return Response({"detail": "Not found."}, status=404)
        MemoryPrayer.objects.get_or_create(memory=m, user=request.user)
        return Response(memory_payload(m, request, full=True))


# ── Reports ──────────────────────────────────────────────────────────────────

class ReportListView(APIView):
    permission_classes = [IsApproved]

    def get(self, request):
        out = []
        for r in AnnualReport.objects.prefetch_related("pdfs").order_by("-year"):
            out.append({"id": r.id, "title": r.title, "year": r.year,
                        "files": [{"title": p.title, "url": abs_url(request, p.pdf)} for p in r.pdfs.all()]})
        return Response(out)


# ── Blood requests ───────────────────────────────────────────────────────────

def blood_payload(b, request):
    return {
        "id": b.id, "blood_group": b.blood_group, "units": b.units, "hospital": b.hospital,
        "patient_name": b.patient_name, "needed_by": b.needed_by, "is_open": b.is_open,
        "contact_phone": b.contact_phone, "created_at": b.created_at,
        "posted_by": getattr(getattr(b.posted_by, "profile", None), "full_name", "") or b.posted_by.get_username(),
        "donors_confirmed": b.responses.count(),
        "i_responded": b.responses.filter(user=request.user).exists(),
        "mine": b.posted_by_id == request.user.id,
    }


class BloodRequestListView(APIView):
    permission_classes = [IsApproved]

    def get(self, request):
        qs = BloodRequest.objects.select_related("posted_by").prefetch_related("responses")
        if request.query_params.get("all") != "1":
            qs = qs.filter(is_open=True)
        return Response([blood_payload(b, request) for b in qs[:50]])

    def post(self, request):
        group = str(request.data.get("blood_group", "")).upper().replace(" ", "")
        if group not in BLOOD_GROUPS:
            return Response({"detail": f"blood_group must be one of {', '.join(BLOOD_GROUPS)}"}, status=400)
        hospital = str(request.data.get("hospital", "")).strip()
        if not hospital:
            return Response({"detail": "Hospital is required."}, status=400)
        needed_by = request.data.get("needed_by")
        if needed_by:
            try:
                needed_by = datetime.fromisoformat(needed_by)
                if timezone.is_naive(needed_by):
                    needed_by = timezone.make_aware(needed_by)
            except ValueError:
                return Response({"detail": "needed_by must be an ISO date-time"}, status=400)
        b = BloodRequest.objects.create(
            posted_by=request.user, blood_group=group, hospital=hospital[:200],
            units=max(1, min(20, int(request.data.get("units") or 1))),
            patient_name=str(request.data.get("patient_name", ""))[:120],
            contact_phone=str(request.data.get("contact_phone", ""))[:20],
            needed_by=needed_by or None,
        )
        # Tell app users whose tree record has this blood group and who said they are available
        donors = _donor_users(group, exclude=request.user)
        notify(donors, f"Urgent: {group} blood needed", f"{hospital}. Tap to say you can donate.",
               kind="blood", data={"blood_request": b.id})
        return Response(blood_payload(b, request), status=201)


def _donor_users(group, exclude=None):
    users = []
    for link in MemberLink.objects.filter(member_id__isnull=False).select_related("user"):
        from ..branches import get_member
        m = get_member(link.branch, link.member_id)
        if not m or (m.blood_group or "").upper().replace(" ", "") != group:
            continue
        ds = DonorStatus.objects.filter(user=link.user).first()
        if ds and not ds.available:
            continue
        if exclude and link.user_id == exclude.id:
            continue
        users.append(link.user)
    return users


class BloodRespondView(APIView):
    """POST → 'I can donate'.  DELETE → take it back.  PATCH {is_open:false} → close (poster/staff)."""
    permission_classes = [IsApproved]

    def post(self, request, pk):
        b = BloodRequest.objects.filter(pk=pk, is_open=True).first()
        if not b:
            return Response({"detail": "This request is closed."}, status=404)
        _r, created = BloodResponse.objects.get_or_create(request=b, user=request.user)
        if created:
            name = getattr(getattr(request.user, "profile", None), "full_name", "") or "A family member"
            notify([b.posted_by], f"{name} can donate {b.blood_group}", b.hospital, kind="blood",
                   data={"blood_request": b.id})
        return Response(blood_payload(b, request))

    def delete(self, request, pk):
        BloodResponse.objects.filter(request_id=pk, user=request.user).delete()
        b = BloodRequest.objects.filter(pk=pk).first()
        return Response(blood_payload(b, request) if b else {}, status=200)

    def patch(self, request, pk):
        b = BloodRequest.objects.filter(pk=pk).first()
        if not b:
            return Response({"detail": "Not found."}, status=404)
        if b.posted_by_id != request.user.id and not request.user.is_staff:
            return Response({"detail": "Only the person who posted this can close it."}, status=403)
        b.is_open = bool(request.data.get("is_open", False))
        b.save(update_fields=["is_open"])
        return Response(blood_payload(b, request))


class DonorListView(APIView):
    """GET ?group=B+ — people in the tree with that blood group (living)."""
    permission_classes = [IsApproved]

    def get(self, request):
        group = str(request.query_params.get("group", "")).upper().replace(" ", "")
        if not group:
            # no group → how many living people have each blood group
            counts = {g: 0 for g in BLOOD_GROUPS}
            for _slug, Model, _label in all_models():
                for bg in Model.objects.filter(date_of_death__isnull=True).exclude(blood_group__isnull=True) \
                                      .exclude(blood_group="").values_list("blood_group", flat=True):
                    key = bg.upper().replace(" ", "")
                    if key in counts:
                        counts[key] += 1
            return Response({"counts": counts})
        if group not in BLOOD_GROUPS:
            return Response({"detail": "Unknown blood group, e.g. ?group=B%2B"}, status=400)
        out = []
        for slug, Model, _label in all_models():
            for m in Model.objects.filter(date_of_death__isnull=True).exclude(blood_group__isnull=True).exclude(blood_group=""):
                if m.blood_group.upper().replace(" ", "") != group:
                    continue
                item = summary(m, slug, request)
                link = MemberLink.objects.filter(branch=slug, member_id=m.pk).first()
                ds = DonorStatus.objects.filter(user=link.user).first() if link else None
                item["uses_app"] = bool(link)
                item["available"] = ds.available if ds else None
                item["last_donated"] = ds.last_donated.isoformat() if ds and ds.last_donated else None
                # men can give again after 3 months, women after 4 (Indian blood bank guidance)
                rest_days = 120 if m.gender == "F" else 90
                rest_until = ds.last_donated + timedelta(days=rest_days) if ds and ds.last_donated else None
                item["rest_until"] = rest_until.isoformat() if rest_until and rest_until > date.today() else None
                item["can_give"] = (item["available"] is not False) and not item["rest_until"]
                out.append(item)
        out.sort(key=lambda x: (not x["can_give"], not x["uses_app"], x["name"]))
        return Response(out)


# ── Notifications ────────────────────────────────────────────────────────────

class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(user=request.user)
        items = [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "data": n.data,
                  "read": n.read, "created_at": n.created_at} for n in qs[:200]]
        data = paginate(request, items)
        data["unread"] = qs.filter(read=False).count()
        return Response(data)

    def post(self, request):
        """Mark all as read (or {ids:[...]})."""
        qs = Notification.objects.filter(user=request.user, read=False)
        ids = request.data.get("ids")
        if ids:
            qs = qs.filter(id__in=ids)
        n = qs.update(read=True)
        return Response({"marked": n})
