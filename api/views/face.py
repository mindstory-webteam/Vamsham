"""
Face scan sign in.

  POST   /api/auth/face/enroll  (signed in)  {images: [3 base64 photos], consent: true, device_name}
                                            → {device_key}  — the phone keeps this secret key
  POST   /api/auth/face/login   (anyone)     {device_key, image} → tokens + me  (same as the SMS code)
  GET    /api/auth/face         (signed in)  → {enrolled, available}
  DELETE /api/auth/face         (signed in)  → removes the face code and every face-scan phone

Face scan only works on a phone that was set up with it (the secret key), so a photo of someone
on a different phone can't open their account. Too many wrong faces → face scan rests for a while.

Many families — find the person by face (no phone number, no family to pick):
  POST /api/auth/face/identify  (anyone)  {image, device_key?}
        → trusted phone: tokens + me (straight to Home)
        → new phone: {need_check, check, first_name, family} — then
  POST /api/auth/face/confirm   (anyone)  {check, last4} → tokens + me + device_key (this phone is trusted)
  POST/DELETE /api/admin/members/<branch>/<id>/face  (family admin) {images, consent} — scan on the spot
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
from ..permissions import IsStaff
from ..models import FaceCheck, FaceDevice, FaceProfile, Family, FamilyAccess, MemberLink
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
            link = MemberLink.all_objects.filter(user=request.user).first()
            p = FaceProfile.all_objects.filter(user=request.user).first()
            if p is None and link and link.member_id:
                # the family admin may have scanned this person already: take that one over
                p = FaceProfile.all_objects.filter(branch=link.branch, member_id=link.member_id).first()
            p = p or FaceProfile(user=request.user)
            p.user, p.embeddings, p.consent_at = request.user, codes, timezone.now()
            if link and link.member_id:
                p.branch, p.member_id = link.branch, link.member_id
            p.save()
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



# ── Many families: find the person by face ───────────────────────────────────

CHECK_MINUTES = 5
CHECK_TRIES = 4


def codes_from_images(images):
    """3 photos → 3 face codes, or a Response explaining the problem."""
    if not isinstance(images, list) or not 1 <= len(images) <= 5:
        return None, Response({"detail": "Please send 1 to 5 photos.", "code": "bad_image"}, status=400)
    codes = []
    for i, img in enumerate(images):
        try:
            codes.append(face.embed(img))
        except face.FaceError as exc:
            return None, face_error(exc, photo=i + 1)
    for c in codes[1:]:
        if face.similarity(codes[0], c) < MIN_SAME_PERSON:
            return None, Response({"detail": "The photos don't look like the same person. Please start again.",
                                   "code": "mismatch"}, status=400)
    return codes, None


def search_faces(code):
    """Best and second-best matching people among every active family's face codes."""
    import numpy as np
    profiles = list(FaceProfile.all_objects.filter(family__is_active=True).exclude(embeddings=[]))
    if not profiles:
        return None, 0.0, 0.0
    q = np.asarray(code, dtype=np.float32)
    q /= (np.linalg.norm(q) or 1.0)
    scores = []
    for p in profiles:
        m = np.asarray(p.embeddings, dtype=np.float32)
        m /= np.linalg.norm(m, axis=1, keepdims=True).clip(min=1e-6)
        scores.append(float((m @ q).max()))
    order = sorted(range(len(profiles)), key=lambda i: scores[i], reverse=True)
    best = profiles[order[0]]
    second = scores[order[1]] if len(order) > 1 else 0.0
    return best, scores[order[0]], second


def person_of(profile):
    """(user or None, member record or None, phone) for a face code."""
    from ..branches import model_for_any
    user = profile.user
    member = None
    if profile.member_id:
        M = model_for_any(profile.branch)
        member = M.objects.filter(pk=profile.member_id).first() if M else None
    if user is None and profile.member_id:
        link = MemberLink.all_objects.filter(branch=profile.branch, member_id=profile.member_id).select_related("user").first()
        user = link.user if link else None
    phone = ""
    if member is not None and member.mobile_number:
        phone = member.mobile_number
    elif user is not None and getattr(user, "profile", None):
        phone = user.profile.phone_number
    return user, member, phone


def digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def family_brief(fid, request):
    f = Family.objects.filter(pk=fid).first()
    if not f:
        return None
    return {"slug": f.slug, "name": f.name, "color": f.color,
            "logo": request.build_absolute_uri(f.logo.url) if f.logo else None}


class FaceIdentifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FaceThrottle]

    def post(self, request):
        try:
            code = face.embed(request.data.get("image"))
        except face.FaceError as exc:
            return face_error(exc)
        best, score, second = search_faces(code)
        if best is None or score < settings.FACE_IDENTIFY_THRESHOLD:
            return Response({"detail": "We couldn't find you. Try again in good light, or use your phone number.",
                             "code": "no_match"}, status=401)
        if score - second < settings.FACE_IDENTIFY_MARGIN:
            return Response({"detail": "We aren't sure it's you. Please use your phone number this time.",
                             "code": "unsure"}, status=401)
        user, member, phone = person_of(best)
        if user is not None and not user.is_active:
            return Response({"detail": "Your request to join was declined. Please contact the secretary.", "code": "declined"}, status=403)

        # a phone already trusted for this person → straight in
        key = request.data.get("device_key")
        if key and user is not None:
            dev = FaceDevice.objects.filter(key_hash=key_hash(key), user=user).first()
            if dev:
                dev.last_used, dev.failed = timezone.now(), 0
                dev.save(update_fields=["last_used", "failed"])
                from ..tenancy import lock_to_user_family
                lock_to_user_family(user)
                return Response({**tokens_for(user), "me": me_payload(user, request), "trusted": True})

        if len(digits(phone)) < 4:
            return Response({"detail": "We found you, but there's no phone number on your record. "
                                       "Ask your family admin to add it, or sign in with your phone number.",
                             "code": "no_phone"}, status=409)
        check = FaceCheck.objects.create(token=secrets.token_urlsafe(32), profile=best)
        first = (member.first_name if member is not None else (user.first_name if user else "")) or ""
        return Response({"need_check": True, "check": check.token, "first_name": first.strip().title(),
                         "family": family_brief(best.family_id, request), "expires_in": CHECK_MINUTES * 60})


class FaceConfirmView(APIView):
    """The last 4 digits of the person's phone → sign in, and trust this phone from now on."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FaceThrottle]

    @transaction.atomic
    def post(self, request):
        from app1.models import Profile
        from ..tenancy import lock_to_user_family
        from .auth import family_paused, find_user_by_phone
        from .. import otp

        check = FaceCheck.objects.select_for_update().select_related("profile").filter(token=str(request.data.get("check", ""))).first()
        if check is None or check.used or check.created_at < timezone.now() - timedelta(minutes=CHECK_MINUTES):
            return Response({"detail": "This face scan has expired. Please scan again.", "code": "expired"}, status=400)
        p = check.profile
        user, member, phone = person_of(p)
        if digits(request.data.get("last4"))[-4:] != digits(phone)[-4:] or len(digits(request.data.get("last4"))) != 4:
            check.tries += 1
            if check.tries >= CHECK_TRIES:
                check.used = True
            check.save(update_fields=["tries", "used"])
            left = max(0, CHECK_TRIES - check.tries)
            return Response({"detail": "Those digits don't match." + (f" {left} {'try' if left == 1 else 'tries'} left." if left else
                             " Please sign in with your phone number."), "code": "wrong_digits" if left else "locked",
                             "tries_left": left}, status=400)
        check.used = True
        check.save(update_fields=["used"])

        if user is None:
            # added by the family admin, never used the app: make their account now (already approved)
            norm = otp.normalize_phone(phone) or phone
            from ..tenancy import set_current_family
            set_current_family(p.family_id)  # the new account belongs to the member's family
            user = find_user_by_phone(norm)
            if user is None:
                name = f"{member.first_name or ''} {member.last_name or ''}".strip() if member is not None else norm
                base = "m" + digits(norm)
                username, n = base, 2
                from django.contrib.auth import get_user_model
                U = get_user_model()
                while U.objects.filter(username=username).exists():
                    username, n = f"{base}-{n}", n + 1
                user = U.objects.create_user(username=username, first_name=(member.first_name if member is not None else "") or "")
                user.set_unusable_password()
                user.save()
                FamilyAccess.objects.update_or_create(user=user, defaults={"family_id": p.family_id})
                Profile.all_objects.create(user=user, full_name=name or norm, phone_number=norm, is_approved=True,
                                           decided_at=timezone.now(), family_id=p.family_id)
            if p.member_id and not MemberLink.all_objects.filter(user=user).exists():
                MemberLink.all_objects.create(user=user, branch=p.branch, member_id=p.member_id, family_id=p.family_id)
        if not user.is_active:
            return Response({"detail": "Your request to join was declined. Please contact the secretary.", "code": "declined"}, status=403)
        blocked = family_paused(user)
        if blocked:
            return Response({"detail": blocked, "code": "paused"}, status=403)

        # the face code now belongs to this account (merge with one they made themselves)
        own = FaceProfile.all_objects.filter(user=user).exclude(pk=p.pk).first()
        if own is not None:
            own.embeddings = (own.embeddings or []) + (p.embeddings or [])
            own.branch, own.member_id = p.branch or own.branch, p.member_id or own.member_id
            p.delete()
            own.save()
        elif p.user_id is None:
            p.user = user
            p.save(update_fields=["user"])

        key = secrets.token_urlsafe(32)
        FaceDevice.objects.create(user=user, key_hash=key_hash(key), name=str(request.data.get("device_name", ""))[:60],
                                  last_used=timezone.now())
        lock_to_user_family(user)
        return Response({**tokens_for(user), "me": me_payload(user, request), "device_key": key})


class AdminMemberFaceView(APIView):
    """Family admin scans a member's face on the spot (camera or uploaded photos)."""
    permission_classes = [IsStaff]

    def _member(self, branch, pk):
        from ..branches import get_member
        return get_member(branch, pk)  # only this family's branches

    def get(self, request, branch, pk):
        if self._member(branch, pk) is None:
            return Response({"detail": "Not found."}, status=404)
        p = FaceProfile.objects.filter(branch=branch, member_id=pk).first()
        return Response({"enrolled": bool(p), "since": p.updated_at if p else None, "available": face.available()})

    @transaction.atomic
    def post(self, request, branch, pk):
        m = self._member(branch, pk)
        if m is None:
            return Response({"detail": "Not found."}, status=404)
        if request.data.get("consent") not in (True, "true", "1", 1):
            return Response({"detail": "The member has to agree first (tick the box).", "code": "consent"}, status=400)
        codes, err = codes_from_images(request.data.get("images") or [])
        if err is not None:
            return err
        link = MemberLink.objects.filter(branch=branch, member_id=pk).first()
        p = FaceProfile.objects.filter(branch=branch, member_id=pk).first()
        if p is None and link:
            p = FaceProfile.all_objects.filter(user=link.user).first()
        p = p or FaceProfile(branch=branch, member_id=pk)
        p.branch, p.member_id, p.embeddings, p.consent_at = branch, pk, codes, timezone.now()
        if link and p.user_id is None:
            p.user = link.user
        p.save()
        return Response({"enrolled": True, "since": p.updated_at, "has_phone": len(digits(m.mobile_number)) >= 4}, status=201)

    def delete(self, request, branch, pk):
        if self._member(branch, pk) is None:
            return Response({"detail": "Not found."}, status=404)
        FaceProfile.objects.filter(branch=branch, member_id=pk).delete()
        return Response(status=204)
