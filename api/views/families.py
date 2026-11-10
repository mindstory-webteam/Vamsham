"""
Main admin (superuser): every family on this Vamsham server.

  GET    /super/families                    → all families with their numbers
  POST   /super/families                    {name, place?, color?} → new family (+ settings, first branch)
  PATCH  /super/families/<id>               {name?, place?, color?, is_active?, logo (file)?}
  GET    /super/families/<id>/admins        → the family's dashboard users
  POST   /super/families/<id>/admins        {name, username, email?, phone?, password?} → new family admin
  POST   /super/families/<id>/admins/<uid>/reset   → new temporary password
  DELETE /super/families/<id>/admins/<uid>  → removes their dashboard access

Family admins are normal "staff" users locked to one family (FamilyAccess); they can never
see another family. Temporary passwords are shown once — send them to the admin yourself.
"""
import secrets

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from app1.models import Event, Profile

from .. import branches as B
from ..models import AssociationSettings, FaceProfile, Family, FamilyAccess, FamilyBranch
from ..tenancy import forget_default

User = get_user_model()


class IsMainAdmin(BasePermission):
    message = "Only the main Vamsham admin can do this."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


def temp_password():
    # easy to read out on the phone: no 0/O/1/l
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def family_numbers(f):
    rows = [r for r in B.all_family_rows() if r.family_id == f.id]
    people = 0
    for r in rows:
        M = B._model_for(r)
        if M is not None:
            people += M.objects.count()
    admins = User.objects.filter(is_staff=True, is_active=True, family_access__family=f).count()
    app_users = User.objects.filter(is_active=True, is_staff=False, family_access__family=f, profile__is_approved=True).count()
    return {
        "people": people,
        "branches": len(rows),
        "admins": admins,
        "app_users": app_users,
        "waiting": Profile.all_objects.filter(family=f, is_approved=False, user__is_active=True).count(),
        "events": Event.all_objects.filter(family=f).count(),
        "faces": FaceProfile.all_objects.filter(family=f).count(),
    }


def family_payload(f, request):
    logo = request.build_absolute_uri(f.logo.url) if f.logo else None
    return {"id": f.id, "name": f.name, "slug": f.slug, "place": f.place, "color": f.color, "logo": logo,
            "is_active": f.is_active, "created_at": f.created_at, **family_numbers(f)}


# A family's sign-in link is /dashboard/<slug>, so a slug can't be the name of a dashboard page.
RESERVED_SLUGS = {
    "admin", "admin-login", "main-login", "f", "login", "otp", "welcome", "pending", "index", "home", "me",
    "events", "search", "tree", "settings", "notifications", "today", "reports", "relate", "branches", "blood",
    "memories", "albums", "album", "event", "member", "add-member", "edit-profile", "face-find", "face-setup",
    "assets", "_expo", "favicon", "dashboard", "api", "static", "media",
}


def unique_slug(name):
    base = slugify(name)[:34] or "family"
    if base in RESERVED_SLUGS:
        base = f"{base}-family"
    slug, n = base, 2
    while Family.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def admin_payload(u):
    profile = getattr(u, "profile", None)
    return {"id": u.id, "name": (getattr(profile, "full_name", "") or u.get_full_name() or u.get_username()).strip(),
            "username": u.get_username(), "email": u.email, "last_login": u.last_login, "is_main_admin": u.is_superuser}


class FamiliesView(APIView):
    permission_classes = [IsMainAdmin]

    def get(self, request):
        fams = [family_payload(f, request) for f in Family.objects.all()]
        totals = {k: sum(x[k] for x in fams) for k in ("people", "admins", "app_users", "waiting")}
        return Response({"results": fams, "totals": {**totals, "families": len(fams)}})

    @transaction.atomic
    def post(self, request):
        name = str(request.data.get("name", "")).strip()[:120]
        if len(name) < 2:
            return Response({"detail": "Please give the family a name."}, status=400)
        if Family.objects.filter(name__iexact=name).exists():
            return Response({"detail": f"A family called “{name}” already exists."}, status=400)
        color = str(request.data.get("color") or "#3FD47A")[:9]
        f = Family.objects.create(name=name, slug=unique_slug(name), place=str(request.data.get("place", ""))[:120], color=color)
        AssociationSettings.load(family_id=f.id)
        # one branch to start with, so the family admin can add people straight away
        base = (slugify(name).replace("-", "")[:12] or "fam")
        slug, n = f"{base}main", 2
        while FamilyBranch.all_objects.filter(slug=slug).exists():
            slug = f"{base}main{n}"
            n += 1
        FamilyBranch.all_objects.create(family=f, slug=slug[:20], name=f"{name} family", sort_order=10)
        B.invalidate()
        forget_default()
        return Response(family_payload(f, request), status=201)


class FamilyDetailView(APIView):
    permission_classes = [IsMainAdmin]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def patch(self, request, pk):
        f = Family.objects.filter(pk=pk).first()
        if not f:
            return Response({"detail": "Not found."}, status=404)
        d = request.data
        if "name" in d:
            name = str(d["name"]).strip()[:120]
            if len(name) < 2:
                return Response({"detail": "Please give the family a name."}, status=400)
            f.name = name
        for k, n in (("place", 120), ("color", 9)):
            if k in d:
                setattr(f, k, str(d[k])[:n])
        if "is_active" in d:
            active = str(d["is_active"]).lower() in ("true", "1", "yes")
            acc = getattr(request.user, "family_access", None)
            if not active and acc and acc.family_id == f.id:
                return Response({"detail": "You can't pause the family you belong to."}, status=400)
            f.is_active = active
        if request.FILES.get("logo"):
            f.logo = request.FILES["logo"]
        if d.get("remove_logo") in (True, "true", "1"):
            f.logo = None
        f.save()
        return Response(family_payload(f, request))


class FamilyAdminsView(APIView):
    permission_classes = [IsMainAdmin]

    def get(self, request, pk):
        users = User.objects.filter(is_staff=True, family_access__family_id=pk).order_by("-is_superuser", "username")
        return Response([admin_payload(u) for u in users if u.is_active])

    @transaction.atomic
    def post(self, request, pk):
        f = Family.objects.filter(pk=pk).first()
        if not f:
            return Response({"detail": "Not found."}, status=404)
        name = str(request.data.get("name", "")).strip()[:150]
        username = str(request.data.get("username", "")).strip().lower()[:150]
        email = str(request.data.get("email", "")).strip()[:254]
        if not name or not username:
            return Response({"detail": "Name and username are needed."}, status=400)
        if User.objects.filter(username__iexact=username).exists():
            return Response({"detail": f"The username “{username}” is taken. Try another."}, status=400)
        if email and User.objects.filter(email__iexact=email).exists():
            return Response({"detail": "Someone already uses that email."}, status=400)
        password = str(request.data.get("password") or "") or temp_password()
        if len(password) < 8:
            return Response({"detail": "The password needs at least 8 characters."}, status=400)
        first, _, last = name.partition(" ")
        from ..tenancy import set_current_family
        set_current_family(f.id)
        u = User.objects.create_user(username=username, email=email, password=password, first_name=first, last_name=last,
                                     is_staff=True)
        FamilyAccess.objects.update_or_create(user=u, defaults={"family": f})
        Profile.all_objects.create(user=u, full_name=name, phone_number=str(request.data.get("phone", ""))[:20],
                                   is_approved=True, family=f)
        return Response({**admin_payload(u), "password": password, "family": f.name}, status=201)


class FamilyAdminDetailView(APIView):
    permission_classes = [IsMainAdmin]

    def _get(self, pk, uid):
        return User.objects.filter(pk=uid, is_staff=True, family_access__family_id=pk).first()

    def post(self, request, pk, uid):
        """reset: a new temporary password"""
        u = self._get(pk, uid)
        if not u:
            return Response({"detail": "Not found."}, status=404)
        if u.is_superuser and u != request.user:
            return Response({"detail": "Another main admin must change their own password."}, status=400)
        password = temp_password()
        u.set_password(password)
        u.save(update_fields=["password"])
        return Response({"password": password, "username": u.get_username()})

    def delete(self, request, pk, uid):
        u = self._get(pk, uid)
        if not u:
            return Response({"detail": "Not found."}, status=404)
        if u.is_superuser:
            return Response({"detail": "Main admins can't be removed here."}, status=400)
        u.is_staff = False
        u.save(update_fields=["is_staff"])
        return Response(status=204)


class MyFamiliesView(APIView):
    """GET /families/mine — the families this person may open in the dashboard (main admin: all)."""

    def get(self, request):
        if request.user.is_superuser:
            qs = Family.objects.all()
        else:
            acc = getattr(request.user, "family_access", None)
            qs = Family.objects.filter(pk=acc.family_id) if acc else Family.objects.none()
        return Response([{"id": f.id, "slug": f.slug, "name": f.name, "color": f.color,
                          "logo": request.build_absolute_uri(f.logo.url) if f.logo else None, "is_active": f.is_active} for f in qs])


class PublicFamiliesView(APIView):
    """GET /families — names for the app's "Which family?" sign-up step (active families only)."""
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        return Response([{"slug": f.slug, "name": f.name, "place": f.place, "color": f.color,
                          "logo": request.build_absolute_uri(f.logo.url) if f.logo else None}
                         for f in Family.objects.filter(is_active=True)])



class PublicFamilyView(APIView):
    """GET /families/<slug> — name, colour and logo for the family's own sign-in page."""
    permission_classes = []
    authentication_classes = []

    def get(self, request, slug):
        f = Family.objects.filter(slug=slug).first()
        if not f:
            return Response({"detail": "There's no family at this link. Check the link with your family admin."}, status=404)
        return Response({"slug": f.slug, "name": f.name, "place": f.place, "color": f.color, "is_active": f.is_active,
                         "logo": request.build_absolute_uri(f.logo.url) if f.logo else None})
