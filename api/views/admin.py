"""Endpoints for committee members (is_staff) — the admin panel."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from app1.models import Event, Profile

from ..branches import BRANCH_LABELS, SLUGS, all_models, get_member, get_model
from ..tenancy import family_users
from ..models import (FaceProfile, AssociationSettings, BloodRequest, Broadcast, ChangeRequest, EventRSVP, MemberLink,
                      NewMemberRequest, Payment)
from ..notify import notify
from ..people import CATEGORY_LABELS, EDITABLE_FIELDS, detail, parse_ref, search, summary
from ..permissions import IsStaff
from .common import member_or_404, paginate
from .community import event_payload

User = get_user_model()


# ── Dashboard ────────────────────────────────────────────────────────────────

def dashboard_data(request):
    """Numbers for the overview page (shared by the API and the web panel)."""
    branches, cats = [], {}
    total = living = dob = photo = mobile = blood = 0
    on_app = dict(MemberLink.objects.filter(user__profile__is_approved=True).exclude(branch="")
                  .values_list("branch").annotate(c=Count("id")))
    for slug, Model, label in all_models():
        qs = Model.objects.all()
        n = qs.count()
        total += n
        living += qs.filter(date_of_death__isnull=True).count()
        dob += qs.filter(date_of_birth__isnull=False).count()
        photo += qs.exclude(photo="").exclude(photo__isnull=True).count()
        mobile += qs.exclude(mobile_number="").exclude(mobile_number__isnull=True).count()
        blood += qs.exclude(blood_group="").exclude(blood_group__isnull=True).count()
        for row in qs.values("membership_category").annotate(c=Count("id")):
            cats[row["membership_category"]] = cats.get(row["membership_category"], 0) + row["c"]
        branches.append({"slug": slug, "label": label, "members": n,
                         "living": qs.filter(date_of_death__isnull=True).count(),
                         "app_users": on_app.get(slug, 0)})
    branches.sort(key=lambda b: -b["members"])

    pending_signups = Profile.objects.filter(is_approved=False, user__is_active=True, user__is_staff=False).count()
    pending_changes = ChangeRequest.objects.filter(status="pending").count()
    pending_new = NewMemberRequest.objects.filter(status="pending").count()
    next_event = Event.objects.filter(date__gte=date.today()).order_by("date").first()
    pct = lambda x: round(x * 100 / total) if total else 0  # noqa: E731
    return {
        "members": {"total": total, "living": living, "remembered": total - living},
        "branches": branches,
        "membership": [{"code": k, "label": CATEGORY_LABELS.get(k, k), "count": v}
                       for k, v in sorted(cats.items(), key=lambda kv: -kv[1])],
        "pending": {"signups": pending_signups, "changes": pending_changes, "new_members": pending_new,
                    "total": pending_signups + pending_changes + pending_new},
        "completeness": {
            "date_of_birth": {"count": dob, "percent": pct(dob)},
            "photo": {"count": photo, "percent": pct(photo)},
            "mobile": {"count": mobile, "percent": pct(mobile)},
            "blood_group": {"count": blood, "percent": pct(blood)},
        },
        "app_users": Profile.objects.filter(is_approved=True, user__is_staff=False).count(),  # members, not the committee
        "next_event": event_payload(next_event, request) if next_event else None,
        "open_blood_requests": BloodRequest.objects.filter(is_open=True).count(),
        "payments": _payments_this_year(),
        "new_app_users_this_month": Profile.objects.filter(user__is_staff=False).filter(
            is_approved=True, user__date_joined__gte=date.today().replace(day=1)).count(),
        "upcoming_events": Event.objects.filter(date__gte=date.today()).count(),
        "generations": _generations(),
        "week": _week_ahead(),
        "settings": {"app_name": AssociationSettings.load().app_name,
                     "family_name": AssociationSettings.load().family_name},
    }


def _week_ahead(days=7):
    """Birthdays and wedding anniversaries for today and the next 6 days (living people)."""
    start = date.today()
    wanted = {}
    for i in range(days):
        d = date.fromordinal(start.toordinal() + i)
        wanted[(d.month, d.day)] = d
    out = {d: {"date": d.isoformat(), "birthdays": [], "anniversaries": []} for d in wanted.values()}
    for slug, Model, label in all_models():
        rows = Model.objects.filter(date_of_death__isnull=True).filter(
            Q(date_of_birth__isnull=False) | Q(marriage_date__isnull=False)
        ).values("id", "first_name", "last_name", "date_of_birth", "marriage_date")
        for r in rows:
            name = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()
            b = r["date_of_birth"]
            if b and (b.month, b.day) in wanted:
                d = wanted[(b.month, b.day)]
                out[d]["birthdays"].append({"ref": f"{slug}:{r['id']}", "name": name, "branch_label": label,
                                            "turning": d.year - b.year})
            w = r["marriage_date"]
            if w and (w.month, w.day) in wanted:
                d = wanted[(w.month, w.day)]
                out[d]["anniversaries"].append({"ref": f"{slug}:{r['id']}", "name": name, "branch_label": label,
                                                "years": d.year - w.year})
    return [out[d] for d in sorted(out)]


def _payments_this_year():
    year = date.today().year
    qs = Payment.objects.filter(paid_on__year=year)
    total = qs.aggregate(s=Sum("amount"))["s"] or 0
    return {"year": year, "total": f"{total:.2f}", "receipts": qs.count()}


def _generations():
    from django.db.models import Max
    levels = [Model.objects.aggregate(d=Max("level"))["d"] for _s, Model, _l in all_models()]
    return max((lv for lv in levels if lv is not None), default=-1) + 1


class DashboardView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        return Response(dashboard_data(request))


# ── Approvals ────────────────────────────────────────────────────────────────

def _suggest_matches(user, link, request):
    """Possible tree records for a new sign-up (same branch, matching first name)."""
    profile = getattr(user, "profile", None)
    name = (profile.full_name if profile else "") or user.first_name
    first = (name or "").split(" ")[0]
    if not first or not link or not link.branch:
        return []
    return search(query=first, branch=link.branch, request=request)[:3]


def approval_items(request):
    """All pending items: sign-ups, profile changes and new family members."""
    items = []
    for p in Profile.objects.filter(is_approved=False, user__is_active=True, user__is_staff=False).select_related("user"):
        link = MemberLink.objects.filter(user=p.user).first()
        items.append({
            "type": "signup", "id": p.user_id, "name": p.full_name, "phone": p.phone_number,
            "branch": link.branch if link else "", "branch_label": BRANCH_LABELS.get(link.branch, "") if link else "",
            "claim": link.claim_text if link else "", "created_at": p.user.date_joined,
            "matches": _suggest_matches(p.user, link, request),
        })
    for c in ChangeRequest.objects.filter(status="pending").select_related("requested_by"):
        m = get_member(c.branch, c.member_id)
        items.append({
            "type": "change", "id": c.id, "name": f"{m.first_name} {m.last_name}" if m else "(deleted)",
            "member": summary(m, c.branch, request) if m else None,
            "field": c.field, "old_value": c.old_value, "new_value": c.new_value, "note": c.note,
            "requested_by": getattr(getattr(c.requested_by, "profile", None), "full_name", "") or c.requested_by.get_username(),
            "created_at": c.created_at,
        })
    for n in NewMemberRequest.objects.filter(status="pending").select_related("requested_by"):
        rel = get_member(n.branch, n.relative_id)
        items.append({
            "type": "new_member", "id": n.id,
            "name": f"{n.data.get('first_name', '')} {n.data.get('last_name', '')}".strip(),
            "relation": n.relation, "data": n.data, "branch": n.branch,
            "branch_label": BRANCH_LABELS.get(n.branch, n.branch),
            "relative": summary(rel, n.branch, request) if rel else None,
            "requested_by": getattr(getattr(n.requested_by, "profile", None), "full_name", "") or n.requested_by.get_username(),
            "created_at": n.created_at,
        })
    items.sort(key=lambda i: i["created_at"], reverse=True)
    return items


class ApprovalListView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        items = approval_items(request)
        return Response({"count": len(items), "results": items, "done_this_month": decided_this_month()})


def decided_this_month():
    """How many requests the committee approved / declined since the 1st of this month."""
    start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    approved = declined = 0
    for p in Profile.objects.filter(decided_at__gte=start).select_related("user"):
        if p.is_approved:
            approved += 1
        else:
            declined += 1
    for Model in (ChangeRequest, NewMemberRequest):
        approved += Model.objects.filter(decided_at__gte=start, status="approved").count()
        declined += Model.objects.filter(decided_at__gte=start, status="declined").count()
    return {"approved": approved, "declined": declined, "total": approved + declined}


class ApprovalDecisionView(APIView):
    """POST /admin/approvals/<type>/<id>/<approve|decline> {member_ref?, note?}"""
    permission_classes = [IsStaff]

    @transaction.atomic
    def post(self, request, kind, pk, decision):
        if decision not in ("approve", "decline"):
            return Response({"detail": "decision must be approve or decline"}, status=400)
        ok = decision == "approve"
        note = str(request.data.get("note", ""))[:255]

        if kind == "signup":
            user = family_users(User.objects.filter(pk=pk)).first()
            profile = getattr(user, "profile", None) if user else None
            if not profile:
                return Response({"detail": "Not found."}, status=404)
            profile.decided_at = timezone.now()
            if ok:
                profile.is_approved = True
                profile.save(update_fields=["is_approved", "decided_at"])
                ref = request.data.get("member_ref")
                if ref:
                    branch, mid = parse_ref(ref)
                    member_or_404(branch, mid)
                    link, _ = MemberLink.objects.get_or_create(user=user)
                    link.branch, link.member_id = branch, mid
                    link.save()
                notify([user], f"Welcome to {AssociationSettings.load().app_name}!",
                       "Your account has been approved. You can now see the family tree.", kind="approval")
            else:
                profile.save(update_fields=["decided_at"])
                user.is_active = False
                user.save(update_fields=["is_active"])
            return Response({"ok": True, "status": "approved" if ok else "declined"})

        if kind == "change":
            c = ChangeRequest.objects.filter(pk=pk, status="pending").first()
            if not c:
                return Response({"detail": "Not found or already decided."}, status=404)
            if ok:
                _M, m = member_or_404(c.branch, c.member_id)
                value = c.new_value or None
                if c.field.endswith("_date") or c.field == "date_of_birth":
                    try:
                        value = date.fromisoformat(value) if value else None
                    except ValueError:
                        return Response({"detail": f"'{c.new_value}' is not a valid date (YYYY-MM-DD)."}, status=400)
                setattr(m, c.field, value)
                m.save()
            c.status = "approved" if ok else "declined"
            c.decided_by, c.decided_at, c.note = request.user, timezone.now(), note or c.note
            c.save()
            notify([c.requested_by], "Your change was " + ("accepted" if ok else "not accepted"),
                   f"{c.field.replace('_', ' ').capitalize()}: {c.new_value}", kind="approval")
            return Response({"ok": True, "status": c.status})

        if kind == "new_member":
            n = NewMemberRequest.objects.filter(pk=pk, status="pending").first()
            if not n:
                return Response({"detail": "Not found or already decided."}, status=404)
            created = None
            if ok:
                Model, relative = member_or_404(n.branch, n.relative_id)
                d = dict(n.data)
                dob = date.fromisoformat(d["date_of_birth"]) if d.get("date_of_birth") else None
                created = Model(
                    first_name=d.get("first_name", ""), last_name=d.get("last_name", ""),
                    gender=d.get("gender", "M"), date_of_birth=dob, place_of_birth=d.get("place_of_birth") or None,
                    membership_category="NM",
                )
                if n.relation == "child":
                    created.parent = relative
                if hasattr(created, "family_group"):
                    created.family_group = relative.family_group
                created.save()
                if n.relation == "spouse":
                    created.spouses.add(relative)
                n.created_member_id = created.pk
            n.status = "approved" if ok else "declined"
            n.decided_by, n.decided_at, n.note = request.user, timezone.now(), note or n.note
            n.save()
            notify([n.requested_by],
                   f"{n.data.get('first_name')} was added to the tree" if ok else "Your request was not accepted",
                   "" if ok else note, kind="approval")
            return Response({"ok": True, "status": n.status,
                             "member": summary(created, n.branch, request) if created else None})

        return Response({"detail": "Unknown approval type."}, status=404)


# ── Members (create / edit / delete) ─────────────────────────────────────────

def member_serializer_for(Model):
    class MemberWriteSerializer(serializers.ModelSerializer):
        parent = serializers.PrimaryKeyRelatedField(queryset=Model.objects.all(), required=False, allow_null=True)
        spouse_ids = serializers.ListField(child=serializers.IntegerField(), required=False, write_only=True)

        class Meta:
            model = Model
            fields = EDITABLE_FIELDS + ["parent", "photo", "spouse_ids"] + (
                ["family_group"] if hasattr(Model, "family_group") else [])

        def save_spouses(self, instance):
            ids = self.validated_data.get("spouse_ids")
            if ids is not None:
                instance.spouses.set(Model.objects.filter(pk__in=ids).exclude(pk=instance.pk))

        def create(self, validated):
            validated.pop("spouse_ids", None)
            obj = super().create(validated)
            self.save_spouses(obj)
            return obj

        def update(self, instance, validated):
            validated.pop("spouse_ids", None)
            obj = super().update(instance, validated)
            self.save_spouses(obj)
            return obj

    return MemberWriteSerializer


class AdminMemberListView(APIView):
    """GET search (same filters as /members) incl. completeness; POST /admin/members/<branch> creates."""
    permission_classes = [IsStaff]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request, branch=None):
        p = request.query_params
        wanted = branch or p.get("branch") or None
        if wanted and get_model(wanted) is None:  # not a branch of this family
            return Response({"detail": "Not found."}, status=404)
        rows = search(query=p.get("q", "").strip(), branch=wanted,
                      category=p.get("category") or None, blood=p.get("blood") or None, request=request)
        missing = p.get("missing")  # e.g. date_of_birth — show only people without it
        if missing in ("date_of_birth", "mobile_number", "blood_group", "photo", "place_of_birth", "baptism_date"):
            rows = [r for r in rows if not getattr(get_member(r["branch"], r["id"]), missing, None)]
        page = paginate(request, rows)
        from ..people import completeness
        for r in page["results"]:  # completeness + phone only for the rows on this page
            m = get_member(r["branch"], r["id"])
            r["completeness"] = completeness(m)
            r["mobile"] = m.mobile_number or ""
        return Response(page)

    def post(self, request, branch=None):
        Model = get_model(branch)
        if Model is None:
            return Response({"detail": "Choose a family branch."}, status=400)
        ser = member_serializer_for(Model)(data=request.data)
        ser.is_valid(raise_exception=True)
        m = ser.save()
        return Response(detail(m, branch, request), status=201)


def csv_response(filename, header, rows):
    """A CSV download that opens cleanly in Excel (UTF-8 with BOM, so Malayalam names work)."""
    import csv
    from django.http import HttpResponse
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("\ufeff")
    w = csv.writer(resp)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return resp


class AdminMemberExportView(APIView):
    """GET /admin/members/export?branch=&q=&category=&missing= → members.csv (same filters as the list)."""
    permission_classes = [IsStaff]

    def get(self, request):
        p = request.query_params
        rows = search(query=p.get("q", "").strip(), branch=p.get("branch") or None,
                      category=p.get("category") or None, blood=p.get("blood") or None, request=request)
        out = []
        for r in rows:
            m = get_member(r["branch"], r["id"])
            if m is None:
                continue
            missing = p.get("missing")
            if missing and getattr(m, missing, None):
                continue
            out.append([
                f"{m.first_name or ''} {m.last_name or ''}".strip(), BRANCH_LABELS.get(r["branch"], r["branch"]),
                (m.level + 1) if getattr(m, "level", None) is not None else "",
                CATEGORY_LABELS.get(m.membership_category, m.membership_category or ""), m.membership_number or "",
                m.mobile_number or "", m.email or "", m.date_of_birth or "", m.blood_group or "",
                m.place_of_birth or "", m.date_of_death or "",
            ])
        return csv_response(f"vamsham-members-{date.today().isoformat()}.csv",
                            ["Name", "Branch", "Generation", "Membership", "Membership no.", "Mobile", "Email",
                             "Date of birth", "Blood group", "Place of birth", "Date of death"], out)


class AdminMemberDetailView(APIView):
    permission_classes = [IsStaff]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request, branch, pk):
        _M, m = member_or_404(branch, pk)
        data = detail(m, branch, request)
        data["mobile"] = m.mobile_number or ""
        data["email"] = m.email or ""
        link = MemberLink.objects.filter(branch=branch, member_id=m.pk).select_related("user").first()
        data["app_user"] = {"id": link.user_id, "username": link.user.get_username()} if link else None
        data["pending_changes"] = ChangeRequest.objects.filter(branch=branch, member_id=m.pk, status="pending").count()
        data["face_enrolled"] = FaceProfile.objects.filter(branch=branch, member_id=m.pk).exists()
        return Response(data)

    def patch(self, request, branch, pk):
        Model, m = member_or_404(branch, pk)
        ser = member_serializer_for(Model)(m, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        m = ser.save()
        return Response(detail(m, branch, request))

    def delete(self, request, branch, pk):
        _M, m = member_or_404(branch, pk)
        if m.get_children().exists() and request.query_params.get("force") != "1":
            return Response({"detail": "This person has children in the tree. Move or remove them first, "
                                       "or add ?force=1 to delete the whole branch below them."}, status=400)
        m.delete()
        return Response(status=204)


# ── Events ───────────────────────────────────────────────────────────────────

class EventWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["title", "category", "date", "start_time", "location", "description", "programme", "rsvp_enabled"]


class AdminEventListView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        qs = Event.objects.prefetch_related("images", "rsvps").order_by("-date")
        return Response([event_payload(e, request) for e in qs[:200]])

    def post(self, request):
        ser = EventWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        e = ser.save()
        if request.data.get("notify"):
            users = family_users(User.objects.filter(profile__is_approved=True, is_active=True))
            notify(list(users), f"New event: {e.title}", f"{e.date:%d %b %Y}" + (f" · {e.location}" if e.location else ""),
                   kind="event", data={"event": e.id})
        return Response(event_payload(e, request, full=True), status=201)


class AdminEventDetailView(APIView):
    permission_classes = [IsStaff]

    def get(self, request, pk):
        e = Event.objects.filter(pk=pk).first()
        if not e:
            return Response({"detail": "Not found."}, status=404)
        data = event_payload(e, request, full=True)
        data["guests"] = [{"name": getattr(getattr(r.user, "profile", None), "full_name", "") or r.user.get_username(),
                           "people": r.people, "attending": r.attending}
                          for r in EventRSVP.objects.filter(event=e).select_related("user")]
        return Response(data)

    def patch(self, request, pk):
        e = Event.objects.filter(pk=pk).first()
        if not e:
            return Response({"detail": "Not found."}, status=404)
        ser = EventWriteSerializer(e, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(event_payload(e, request, full=True))

    def delete(self, request, pk):
        Event.objects.filter(pk=pk).delete()
        return Response(status=204)


# ── Broadcast messages ───────────────────────────────────────────────────────

def audience_users(audience):
    """
    'all' | 'branch:<slug>' | 'life_members' | 'blood:<group>'
    Returns approved app users in that audience.
    """
    users = family_users(User.objects.filter(is_active=True).filter(Q(profile__is_approved=True) | Q(is_staff=True)))
    if audience == "all":
        return list(users)
    links = MemberLink.objects.filter(user__in=users)
    if audience.startswith("branch:"):
        return [l.user for l in links.filter(branch=audience.split(":", 1)[1]).select_related("user")]
    out = []
    for l in links.filter(member_id__isnull=False).select_related("user"):
        m = get_member(l.branch, l.member_id)
        if not m:
            continue
        if audience == "life_members" and m.membership_category in ("LM", "LMF"):
            out.append(l.user)
        elif audience.startswith("blood:") and (m.blood_group or "").upper() == audience.split(":", 1)[1].upper():
            out.append(l.user)
    return out


class BroadcastView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        """GET ?audience=... previews the number of people; without it lists past messages."""
        aud = request.query_params.get("audience")
        if aud:
            return Response({"audience": aud, "recipients": len(audience_users(aud))})
        return Response([{"id": b.id, "audience": b.audience, "channels": b.channels, "title": b.title,
                          "message": b.message, "recipients": b.recipients, "created_at": b.created_at}
                         for b in Broadcast.objects.all()[:50]])

    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response({"detail": "Message can't be empty."}, status=400)
        audience = str(request.data.get("audience", "all"))
        if audience.startswith("branch:") and audience.split(":", 1)[1] not in SLUGS:
            return Response({"detail": "Unknown branch."}, status=400)
        channels = request.data.get("channels") or ["app"]
        title = str(request.data.get("title") or AssociationSettings.load().app_name)[:200]
        users = audience_users(audience)
        sent = 0
        if "app" in channels:
            if "{first name}" in message:
                # personal greeting: "Dear {first name}" → "Dear Anil"
                for u in users:
                    if u is None:
                        continue
                    prof = getattr(u, "profile", None)
                    first = ((prof.full_name if prof else "") or u.first_name or "family").split(" ")[0]
                    sent += notify([u], title, message.replace("{first name}", first), kind="broadcast")
            else:
                sent = notify(users, title, message, kind="broadcast")
        # SMS / WhatsApp: connect a provider here (MSG91, Gupshup, Twilio...). Stored for the record.
        b = Broadcast.objects.create(sent_by=request.user, audience=audience, channels=channels,
                                     title=title, message=message, recipients=sent)
        return Response({"id": b.id, "recipients": sent,
                         "note": "Only app notifications are sent automatically. Connect an SMS/WhatsApp provider in api/views/admin.py."},
                        status=201)


# ── Payments ─────────────────────────────────────────────────────────────────

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "receipt_no", "payer_name", "branch", "member_id", "purpose", "amount",
                  "method", "reference", "paid_on", "created_at"]
        read_only_fields = ["id", "receipt_no", "created_at"]


class PaymentListView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        qs = Payment.objects.all()
        year = request.query_params.get("year")
        if year and year.isdigit():
            qs = qs.filter(paid_on__year=int(year))
        total = qs.aggregate(s=Sum("amount"))["s"] or 0
        by_purpose = list(qs.values("purpose").annotate(total=Sum("amount"), count=Count("id")))
        page = paginate(request, PaymentSerializer(qs, many=True).data)
        page["total_amount"] = f"{total:.2f}"
        page["by_purpose"] = [{**b, "total": f"{b['total']:.2f}"} for b in by_purpose]
        months = {}
        for paid_on, amount in qs.values_list("paid_on", "amount"):
            months[paid_on.month] = months.get(paid_on.month, 0) + amount
        page["by_month"] = [{"month": m, "total": f"{months.get(m, 0):.2f}"} for m in range(1, 13)]
        return Response(page)

    def post(self, request):
        ser = PaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        p = ser.save(recorded_by=request.user)
        return Response(PaymentSerializer(p).data, status=201)


class PaymentExportView(APIView):
    """GET /admin/payments/export?year=2026 → payments.csv"""
    permission_classes = [IsStaff]

    def get(self, request):
        qs = Payment.objects.all()
        year = request.query_params.get("year")
        if year and year.isdigit():
            qs = qs.filter(paid_on__year=int(year))
        purposes, methods = dict(Payment.PURPOSES), dict(Payment.METHODS)
        rows = [[x.receipt_no, x.paid_on, x.payer_name, BRANCH_LABELS.get(x.branch, x.branch), purposes.get(x.purpose, x.purpose),
                 methods.get(x.method, x.method), x.reference, f"{x.amount:.2f}"] for x in qs]
        return csv_response(f"vamsham-payments-{year or 'all'}.csv",
                            ["Receipt", "Date", "Paid by", "Branch", "For", "Method", "Reference", "Amount (Rs)"], rows)


ANNUAL_CATEGORIES = ("PM", "PMF", "M")  # members who pay the fee every year (life members pay once)


def unpaid_members(year):
    """Living annual-fee members with no annual-fee payment recorded for them this year."""
    paid = set(Payment.objects.filter(purpose="annual_fee", paid_on__year=year, member_id__isnull=False)
               .values_list("branch", "member_id"))
    out = []
    for slug, Model, _label in all_models():
        for m in Model.objects.filter(date_of_death__isnull=True, membership_category__in=ANNUAL_CATEGORIES):
            if (slug, m.pk) not in paid:
                out.append((slug, m))
    return out


class UnpaidView(APIView):
    """
    GET  /admin/payments/unpaid?year=2026 → {count, on_app, year}
    POST /admin/payments/unpaid {year} → reminds the ones who use the app (notification)
    """
    permission_classes = [IsStaff]

    def _year(self, request):
        y = str(request.data.get("year") or request.query_params.get("year") or date.today().year)
        return int(y) if y.isdigit() else date.today().year

    def _users(self, rows):
        keys = {(slug, m.pk) for slug, m in rows}
        links = MemberLink.objects.filter(user__is_active=True, user__profile__is_approved=True).select_related("user")
        return [lk.user for lk in links if (lk.branch, lk.member_id) in keys]

    def get(self, request):
        year = self._year(request)
        rows = unpaid_members(year)
        return Response({"year": year, "count": len(rows), "on_app": len(self._users(rows))})

    def post(self, request):
        year = self._year(request)
        users = self._users(unpaid_members(year))
        s = AssociationSettings.load()
        sent = notify(users, f"{s.app_name}: annual fee {year}",
                      f"A gentle reminder — your annual fee of ₹{s.annual_fee:,.0f} for {year} is due. Thank you!"
                      if getattr(s, "annual_fee", None) else f"A gentle reminder — your annual fee for {year} is due. Thank you!",
                      kind="fee")
        return Response({"sent": sent, "detail": f"Reminder sent to {sent} {'person' if sent == 1 else 'people'}."})
