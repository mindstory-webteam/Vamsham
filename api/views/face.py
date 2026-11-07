"""
Face scan sign in.

  POST   /api/auth/face/enroll  (signed in)  {images: [3 base64 photos], consent: true, device_name}
                                            → {device_key}  — the phone keeps this secret key
  POST   /api/auth/face/login   (anyone)     {device_key, image} → tokens + me  (same as the SMS code)
  GET    /api/auth/face         (signed in)  → {enrolled, available}
  DELETE /api/auth/face         (signed in)  → removes the face code and every face-scan phone

Face scan only works on a phone that was set up with it (the secret key), so a photo of someone
on a different phone can't open their account. Too many wrong faces → face scan rests for a while.
"""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .. import face
from ..models import FaceDevice, FaceProfile
from .auth import me_payload, tokens_for

MIN_SAME_PERSON = 0.36  # the 3 set-up photos must look like the same person


class FaceThrottle(AnonRateThrottle):
    scope = "face"


def key_hash(key):
    return hashlib.sha256(str(key).encode()).hexdigest()


def face_error(exc, status=400, **extra):
    return Response({"detail": str(exc), "code": exc.code, **extra}, status=503 if exc.code == "not_ready" else status)


class FaceStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        p = FaceProfile.objects.filter(user=request.user).first()
        return Response({"enrolled": bool(p), "since": p.updated_at.isoformat() if p else None,
                         "available": face.available()})

    def delete(self, request):
        FaceProfile.objects.filter(user=request.user).delete()
        FaceDevice.objects.filter(user=request.user).delete()
        return Response(status=204)


class FaceEnrollView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [FaceThrottle]

    def post(self, request):
        if request.data.get("consent") not in (True, "true", "1", 1):
            return Response({"detail": "Please agree to save your face code first.", "code": "consent"}, status=400)
        images = request.data.get("images") or []
        if not isinstance(images, list) or not 1 <= len(images) <= 5:
            return Response({"detail": "Please send 1 to 5 photos.", "code": "bad_image"}, status=400)
        codes = []
        for i, img in enumerate(images):
            try:
                codes.append(face.embed(img))
            except face.FaceError as exc:
                return face_error(exc, photo=i + 1)
        for c in codes[1:]:
            if face.similarity(codes[0], c) < MIN_SAME_PERSON:
                return Response({"detail": "The photos don't look like the same person. Please start again.",
                                 "code": "mismatch"}, status=400)

        key = secrets.token_urlsafe(32)
        with transaction.atomic():
            FaceProfile.objects.update_or_create(
                user=request.user, defaults={"embeddings": codes, "consent_at": timezone.now()})
            # one face-scan phone per person: setting up again (or on a new phone) replaces the old one
            FaceDevice.objects.filter(user=request.user).delete()
            FaceDevice.objects.create(user=request.user, key_hash=key_hash(key),
                                      name=str(request.data.get("device_name", ""))[:60])
        return Response({"device_key": key, "enrolled": True}, status=201)


class FaceLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FaceThrottle]

    def post(self, request):
        key = request.data.get("device_key")
        device = FaceDevice.objects.select_related("user").filter(key_hash=key_hash(key)).first() if key else None
        if device is None:
            return Response({"detail": "Face scan isn't set up on this phone. Please use your phone number.",
                             "code": "unknown_device"}, status=401)
        now = timezone.now()
        if device.locked_until and device.locked_until > now:
            mins = max(1, int((device.locked_until - now).total_seconds() // 60) + 1)
            return Response({"detail": f"Too many tries. Face scan is resting — try again in {mins} min or use your phone number.",
                             "code": "locked", "retry_in": mins * 60}, status=429)
        user = device.user
        if not user.is_active:
            return Response({"detail": "Your request to join was declined. Please contact the secretary.",
                             "code": "declined"}, status=403)
        profile = FaceProfile.objects.filter(user=user).first()
        if profile is None:
            device.delete()
            return Response({"detail": "Face scan was turned off. Please use your phone number.",
                             "code": "unknown_device"}, status=401)
        try:
            code = face.embed(request.data.get("image"))
        except face.FaceError as exc:
            return face_error(exc)  # no face / too far: doesn't count as a wrong try

        score = face.best_match(code, profile.embeddings)
        if score < settings.FACE_MATCH_THRESHOLD:
            device.failed += 1
            left = settings.FACE_MAX_FAILS - device.failed
            if left <= 0:
                device.failed = 0
                device.locked_until = now + timedelta(minutes=settings.FACE_LOCK_MINUTES)
                device.save(update_fields=["failed", "locked_until"])
                return Response({"detail": f"Face not matched. Face scan is resting for {settings.FACE_LOCK_MINUTES} minutes — use your phone number.",
                                 "code": "locked", "retry_in": settings.FACE_LOCK_MINUTES * 60}, status=429)
            device.save(update_fields=["failed"])
            return Response({"detail": "We couldn't match your face.", "code": "no_match", "tries_left": left}, status=401)

        device.failed = 0
        device.locked_until = None
        device.last_used = now
        device.save(update_fields=["failed", "locked_until", "last_used"])
        return Response({**tokens_for(user), "me": me_payload(user, request)})
