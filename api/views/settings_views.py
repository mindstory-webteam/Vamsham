"""Association settings, committee list and photo uploads (used by the dashboard)."""
from django.contrib.auth import get_user_model
from django.db.models import Count
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from app1.models import Event, EventImage, FamilyPhoto

from ..models import AssociationSettings
from ..permissions import IsApproved, IsStaff
from .community import abs_url

User = get_user_model()

PUBLIC_FIELDS = ["app_name", "family_name", "association_name", "secretary_whatsapp",
                 "upi_id", "upi_name", "annual_fee", "life_fee"]


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssociationSettings
        fields = PUBLIC_FIELDS + ["receipt_address", "updated_at"]
        read_only_fields = ["updated_at"]


class PublicSettingsView(APIView):
    """GET /settings — names, WhatsApp and UPI details the app shows to members."""
    permission_classes = [IsApproved]

    def get(self, request):
        data = SettingsSerializer(AssociationSettings.load()).data
        return Response({k: data[k] for k in PUBLIC_FIELDS})


class AdminSettingsView(APIView):
    """GET / PATCH /admin/settings"""
    permission_classes = [IsStaff]

    def get(self, request):
        return Response(SettingsSerializer(AssociationSettings.load()).data)

    def patch(self, request):
        ser = SettingsSerializer(AssociationSettings.load(), data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


class CommitteeView(APIView):
    """GET /admin/committee — everyone who can sign in to the dashboard."""
    permission_classes = [IsStaff]

    def get(self, request):
        out = []
        for u in User.objects.filter(is_staff=True, is_active=True).order_by("-is_superuser", "username"):
            profile = getattr(u, "profile", None)
            name = (getattr(profile, "full_name", "") or u.get_full_name() or u.get_username()).strip()
            out.append({"id": u.id, "name": name, "username": u.get_username(), "email": u.email,
                        "full_access": u.is_superuser, "last_login": u.last_login, "is_me": u.id == request.user.id})
        return Response(out)


# ── Photos ───────────────────────────────────────────────────────────────────

def _photo(request, obj):
    return {"id": obj.id, "url": abs_url(request, obj.image), "caption": getattr(obj, "caption", "") or ""}


class AdminPhotosView(APIView):
    """
    GET  /admin/photos            → albums with their photos (events + family photos by year)
    POST /admin/photos            → multipart: photos=<file> (repeat), event=<id> OR year=<2024>, title?
    """
    permission_classes = [IsStaff]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        albums = []
        for e in Event.objects.annotate(n=Count("images")).filter(n__gt=0).order_by("-date"):
            imgs = list(e.images.all())
            albums.append({"key": f"event-{e.id}", "kind": "event", "event_id": e.id, "title": e.title,
                           "date": e.date.isoformat(), "year": str(e.date.year), "count": len(imgs),
                           "photos": [_photo(request, i) for i in imgs[:24]]})
        years = {}
        for p in FamilyPhoto.objects.all():
            years.setdefault(p.year or "Old family photos", []).append(p)
        for y, items in sorted(years.items(), reverse=True):
            albums.append({"key": f"family-{y}", "kind": "family", "event_id": None,
                           "title": f"Family photos {y}" if y[:1].isdigit() else y, "date": None,
                           "year": y, "count": len(items), "photos": [_photo(request, i) for i in items[:24]]})
        return Response(albums)

    def post(self, request):
        files = request.FILES.getlist("photos")
        if not files:
            return Response({"detail": "Choose at least one photo."}, status=400)
        if len(files) > 100:
            return Response({"detail": "Up to 100 photos at once."}, status=400)
        for f in files:
            if not (f.content_type or "").startswith("image/"):
                return Response({"detail": f"{f.name} is not an image."}, status=400)
        caption = str(request.data.get("caption", ""))[:200]
        created = []
        if request.data.get("event"):
            e = Event.objects.filter(pk=request.data.get("event")).first()
            if not e:
                return Response({"detail": "Event not found."}, status=404)
            start = e.images.count()
            for n, f in enumerate(files):
                created.append(EventImage.objects.create(event=e, image=f, caption=caption, order=start + n))
        else:
            year = str(request.data.get("year", "")).strip()[:20]
            title = str(request.data.get("title", "")).strip()[:200] or "Family photo"
            for f in files:
                created.append(FamilyPhoto.objects.create(title=title, image=f, caption=caption, year=year))
        return Response({"added": len(created), "photos": [_photo(request, c) for c in created]}, status=201)


class AdminPhotoDeleteView(APIView):
    """DELETE /admin/photos/<event|family>/<id>"""
    permission_classes = [IsStaff]

    def delete(self, request, kind, pk):
        Model = EventImage if kind == "event" else FamilyPhoto if kind == "family" else None
        obj = Model.objects.filter(pk=pk).first() if Model else None
        if not obj:
            return Response({"detail": "Photo not found."}, status=404)
        obj.image.delete(save=False)
        obj.delete()
        return Response(status=204)
