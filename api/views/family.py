"""Family tree, directory search, relationships and member-submitted requests."""
from datetime import date

from django.utils import timezone

from rest_framework.response import Response
from rest_framework.views import APIView

from ..branches import BRANCH_LABELS, all_models, get_model
from ..models import ChangeRequest, MemberLink, NewMemberRequest, RemoveRequest
from ..notify import notify
from ..people import (SELF_EDITABLE_FIELDS, detail, parse_ref, relationship, search,
                      today_items, tree)
from ..permissions import IsApproved
from .common import member_or_404, paginate


class BranchesView(APIView):
    permission_classes = [IsApproved]

    def get(self, request):
        out = []
        for slug, Model, label in all_models():
            out.append({
                "slug": slug, "label": label,
                "members": Model.objects.count(),
                "living": Model.objects.filter(date_of_death__isnull=True).count(),
                "generations": (max(Model.objects.values_list("level", flat=True), default=-1) + 1),
            })
        return Response({"total": sum(b["members"] for b in out), "branches": out})


class MemberSearchView(APIView):
    """GET ?q=&branch=&blood=&category=(LM|PM|NM|life)&living=1&page=&page_size="""
    permission_classes = [IsApproved]

    def get(self, request):
        p = request.query_params
        results = search(
            query=p.get("q", "").strip(),
            branch=p.get("branch") or None,
            blood=p.get("blood") or None,
            category=p.get("category") or None,
            living=True if p.get("living") == "1" else None,
            request=request,
        )
        data = paginate(request, results)
        add_relation_to_me(request, data["results"])
        return Response(data)


def add_relation_to_me(request, items):
    """Add "relation_to_me" (e.g. "Brother", "You") for people in my own branch."""
    link = MemberLink.objects.filter(user=request.user).first()
    if not link or not link.branch or not link.member_id:
        return
    MyModel = get_model(link.branch)
    me = MyModel.objects.filter(pk=link.member_id).first() if MyModel else None
    if not me:
        return
    for it in items:
        if it.get("branch") != link.branch:
            continue
        if it.get("id") == me.pk:
            it["relation_to_me"] = "You"
            continue
        other = get_model(it["branch"]).objects.filter(pk=it["id"]).first()
        if other is None:
            continue
        try:
            r = relationship(link.branch, me, it["branch"], other)
        except Exception:  # never break search because of one odd record
            continue
        if r.get("found") and r.get("relation"):
            it["relation_to_me"] = r["relation"]


class MemberDetailView(APIView):
    permission_classes = [IsApproved]

    def get(self, request, branch, pk):
        _Model, m = member_or_404(branch, pk)
        return Response(detail(m, branch, request))


class TreeView(APIView):
    """GET /tree/<branch>?root=<id>&depth=4"""
    permission_classes = [IsApproved]

    def get(self, request, branch):
        if get_model(branch) is None:
            return Response({"detail": "Unknown family branch."}, status=404)
        try:
            depth = min(8, max(1, int(request.query_params.get("depth", 4))))
            root = int(request.query_params["root"]) if request.query_params.get("root") else None
        except ValueError:
            return Response({"detail": "root and depth must be numbers"}, status=400)
        return Response({
            "branch": branch, "label": BRANCH_LABELS[branch],
            "roots": tree(branch, root_id=root, depth=depth, request=request),
        })


class RelationshipView(APIView):
    """GET ?a=lonappan:12&b=lonappan:40  (a defaults to the signed-in user's own record)"""
    permission_classes = [IsApproved]

    def get(self, request):
        a_ref = request.query_params.get("a")
        if not a_ref:
            link = MemberLink.objects.filter(user=request.user, member_id__isnull=False).first()
            if not link:
                return Response({"detail": "Your account is not linked to the tree yet, so pass ?a=."}, status=400)
            a_ref = f"{link.branch}:{link.member_id}"
        ba, ia = parse_ref(a_ref)
        bb, ib = parse_ref(request.query_params.get("b"))
        if not ba or not bb:
            return Response({"detail": "Use a=branch:id and b=branch:id"}, status=400)
        _ma, a = member_or_404(ba, ia)
        _mb, b = member_or_404(bb, ib)
        from ..people import summary
        result = relationship(ba, a, bb, b, request)
        result["a"] = summary(a, ba, request)
        result["b"] = summary(b, bb, request)
        return Response(result)


class TodayView(APIView):
    """Birthdays, wedding anniversaries and remembrance days for today (or ?date=YYYY-MM-DD)."""
    permission_classes = [IsApproved]

    def get(self, request):
        day = None
        if request.query_params.get("date"):
            try:
                day = date.fromisoformat(request.query_params["date"])
            except ValueError:
                return Response({"detail": "date must be YYYY-MM-DD"}, status=400)
        data = today_items(day, request)
        from app1.models import Memory
        d = day or date.today()
        data["memories"] = [
            {"id": m.id, "name": m.name, "years": d.year - m.death_date.year}
            for m in Memory.objects.filter(death_date__month=d.month, death_date__day=d.day)
        ]
        return Response(data)


class WishView(APIView):
    """POST /members/<branch>/<id>/wish {message?} — sends a notification if they use the app."""
    permission_classes = [IsApproved]

    def post(self, request, branch, pk):
        _M, m = member_or_404(branch, pk)
        link = MemberLink.objects.filter(branch=branch, member_id=m.pk).select_related("user").first()
        sender = getattr(request.user, "profile", None)
        sender_name = sender.full_name if sender else request.user.get_username()
        delivered = 0
        if link:
            msg = str(request.data.get("message") or f"Warm wishes from {sender_name}!")[:300]
            delivered = notify([link.user], f"{sender_name} sent you wishes", msg, kind="wish")
        return Response({"delivered": bool(delivered),
                         "detail": "Wishes sent." if delivered else f"{m.first_name} doesn't use the app yet."})


class ChangeRequestView(APIView):
    """POST {member_ref, field, value, note?} — suggest a correction; the committee approves it."""
    permission_classes = [IsApproved]

    def get(self, request):
        items = ChangeRequest.objects.filter(requested_by=request.user)[:50]
        return Response([{
            "id": c.id, "member_ref": f"{c.branch}:{c.member_id}", "field": c.field,
            "new_value": c.new_value, "status": c.status, "created_at": c.created_at,
        } for c in items])

    def post(self, request):
        branch, pk = parse_ref(request.data.get("member_ref"))
        field = request.data.get("field")
        if field not in SELF_EDITABLE_FIELDS:
            return Response({"detail": f"This field can't be changed here. Allowed: {', '.join(SELF_EDITABLE_FIELDS)}"}, status=400)
        _M, m = member_or_404(branch, pk)
        old = getattr(m, field)
        cr = ChangeRequest.objects.create(
            requested_by=request.user, branch=branch, member_id=m.pk, field=field,
            old_value="" if old is None else str(old), new_value=str(request.data.get("value", ""))[:500],
            note=str(request.data.get("note", ""))[:255],
        )
        return Response({"id": cr.id, "status": cr.status}, status=201)


class RemoveRequestView(APIView):
    """POST {member_ref, reason: duplicate|wrong|not_family|other, note?} — ask the family admin to take
    a person off the tree. Nothing is deleted until the admin approves."""
    permission_classes = [IsApproved]

    def post(self, request):
        branch, pk = parse_ref(request.data.get("member_ref"))
        _M, m = member_or_404(branch, pk)
        reason = request.data.get("reason") if request.data.get("reason") in dict(RemoveRequest.REASONS) else "other"
        note = str(request.data.get("note", "")).strip()[:255]
        if reason == "other" and not note:
            return Response({"detail": "Please tell the family admin why."}, status=400)
        if RemoveRequest.objects.filter(branch=branch, member_id=m.pk, status="pending").exists():
            return Response({"detail": "Someone already asked to remove this person — the family admin will decide."}, status=400)
        r = RemoveRequest.objects.create(requested_by=request.user, branch=branch, member_id=m.pk,
                                         member_name=f"{m.first_name} {m.last_name}".strip(), reason=reason, note=note)
        return Response({"id": r.id, "status": r.status}, status=201)


def ten_digits(raw):
    """Indian mobile → its 10 digits ('' if it isn't a valid 10-digit number)."""
    import re
    d = re.sub(r"\D", "", str(raw or ""))
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if len(d) == 10 and d[0] in "6789" else ""


def who_has_mobile(phone10, skip_request=None):
    """Name of someone in this family (tree or waiting request) already using this mobile, else ''."""
    from .. import branches as B
    if not phone10:
        return ""
    for r in B.rows():
        M = B._model_for(r)
        if M is None:
            continue
        for m in M.objects.filter(mobile_number__contains=phone10[-4:]).only("first_name", "last_name", "mobile_number"):
            if ten_digits(m.mobile_number) == phone10:
                return f"{m.first_name} {m.last_name}".strip()
    for n in NewMemberRequest.objects.filter(status="pending").exclude(pk=skip_request):
        if n.data.get("mobile_number") == phone10:
            return f"{n.data.get('first_name', '')} {n.data.get('last_name', '')}".strip() + " (waiting for approval)"
    return ""


class NewMemberRequestView(APIView):
    """POST {relative_ref, relation: child|spouse, first_name, last_name, gender, mobile_number,
    date_of_birth?, place_of_birth?, face_images?: [3 photos], face_consent?}

    The mobile number is required. The face scan is optional: the photos are turned into face codes
    right away and one photo is kept for the profile picture — all of it is only used if the family
    admin approves (and deleted if they decline)."""
    permission_classes = [IsApproved]

    def post(self, request):
        branch, pk = parse_ref(request.data.get("relative_ref"))
        _M, relative = member_or_404(branch, pk)
        relation = request.data.get("relation", "child")
        if relation not in ("child", "spouse"):
            return Response({"detail": "relation must be child or spouse"}, status=400)
        first = str(request.data.get("first_name", "")).strip()
        if not first:
            return Response({"detail": "First name is required."}, status=400)
        dob = request.data.get("date_of_birth") or None
        if dob:
            try:
                date.fromisoformat(dob)
            except ValueError:
                return Response({"detail": "date_of_birth must be YYYY-MM-DD"}, status=400)
        mobile = ten_digits(request.data.get("mobile_number"))
        if not mobile:
            return Response({"detail": "Please enter their 10-digit mobile number.", "field": "mobile_number"}, status=400)
        taken = who_has_mobile(mobile)
        if taken:
            return Response({"detail": f"This mobile number is already used by {taken}.", "field": "mobile_number"}, status=400)
        data = {
            "first_name": first[:100],
            "last_name": str(request.data.get("last_name", ""))[:100],
            "gender": request.data.get("gender") if request.data.get("gender") in ("M", "F", "O") else "M",
            "date_of_birth": dob,
            "place_of_birth": str(request.data.get("place_of_birth", ""))[:255],
            "mobile_number": mobile,
        }

        # optional face scan, done on the spot
        codes, jpg = [], None
        images = request.data.get("face_images") or []
        if images:
            if request.data.get("face_consent") not in (True, "true", "1", 1):
                return Response({"detail": "Tick the box to show they agree to face sign-in.", "code": "consent"}, status=400)
            from .. import face
            from .face import codes_from_images
            codes, err = codes_from_images(images)
            if err is not None:
                return err
            try:
                jpg = face.portrait(images[0])
            except face.FaceError:
                jpg = None

        req = NewMemberRequest(
            requested_by=request.user, branch=branch, relative_id=relative.pk,
            relation=relation, data=data, note=str(request.data.get("note", ""))[:255],
            face_codes=codes, face_consent_at=timezone.now() if codes else None,
        )
        if jpg:
            import secrets
            from django.core.files.base import ContentFile
            req.face_photo.save(f"new-{secrets.token_hex(6)}.jpg", ContentFile(jpg), save=False)
        req.save()
        return Response({"id": req.id, "status": req.status, "face": bool(codes)}, status=201)
