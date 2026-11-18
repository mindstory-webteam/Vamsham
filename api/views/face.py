"""
Face scan sign in — works across every family on this Vamsham server.

On a phone that was set up with face scan:
  POST   /api/auth/face/enroll  (signed in)  {images: [1–5 base64 photos], consent: true, device_name}
                                            → {device_key}  — the phone keeps this secret key
  POST   /api/auth/face/login   (anyone)     {device_key, image} → tokens + me (+ "also": other families)
  GET    /api/auth/face         (signed in)  → {enrolled, available}
  DELETE /api/auth/face         (signed in)  → removes the face code and every face-scan phone

Find the person by face, in any family (no phone number, no family to pick):
  POST /api/auth/face/scan      (anyone)  {image, mode: "identify" | "login", device_key?}
        ONE request per camera frame: checks the face and — the moment it's good — matches it too.
        → {seen}                 face not good yet (where it is + why), keep scanning
        → {seen, outcome: {status, data}}   the answer /identify or /login would have given — stop
  POST /api/auth/face/detect    (anyone)  {image} → where the face is, and whether it's good enough
  POST /api/auth/face/identify  (anyone)  {image, device_key?}
        → one family, trusted phone: tokens + me (straight to Home)
        → one family, new phone:     {need_check, check, first_name, family}
        → more than one family:      {need_family, choices: [{check, family, first_name, trusted}]}
        → nobody:                    401 no_match · two people too alike: 401 unsure
  POST /api/auth/face/confirm   (anyone)  {check, last4 | device_key} → tokens + me + device_key

Family admin scans a member on the spot (camera or uploaded photos):
  GET/POST/DELETE /api/admin/members/<branch>/<id>/face  {images, consent, set_photo?}

How a face is matched (rank_faces → family_matches):
  1. The photo must have exactly one clear face (face.embed turns it upright, checks light and blur).
  2. Its face code is compared with the face codes of EVERY active family — never only the family the
     request came from. Faces of people no longer on the tree, and the main admin's own face, are left out.
  3. The best match in each family above FACE_IDENTIFY_THRESHOLD counts — unless, in that family, a
     DIFFERENT person looks almost as alike (within FACE_IDENTIFY_MARGIN): then it isn't safe to say who.
     Two face codes of the same person (their own set-up + the admin's scan) are the same person.
  4. One family → that family's person. Several families → the person picks ("Which family?").
Every face code is stored in its person's own family (FaceProfile.save), so it is always found there.
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
from ..models import FaceCheck, FaceDevice, FaceProfile, Family, FamilyAccess, FamilyBranch, MemberLink
from .auth import me_payload, tokens_for

MIN_SAME_PERSON = 0.36  # the set-up photos must look like the same person
CHECK_MINUTES = 5
CHECK_TRIES = 4


class FaceThrottle(AnonRateThrottle):
    scope = "face"


class FaceDetectThrottle(AnonRateThrottle):
    scope = "face_detect"


def key_hash(key):
    return hashlib.sha256(str(key).encode()).hexdigest()


def face_error(exc, status=400, **extra):
    return Response({"detail": str(exc), "code": exc.code, **extra}, status=503 if exc.code == "not_ready" else status)


def digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


# ── Families, people and accounts ────────────────────────────────────────────

def branch_family(slug):
    """The family a branch (and so everyone in it) belongs to."""
    if not slug:
        return None
    return FamilyBranch.all_objects.filter(slug=slug).values_list("family_id", flat=True).first()


def family_of_user(user):
    from ..tenancy import family_for_user
    return family_for_user(user) if user is not None else None


def family_account(user, family_id):
    """`user` only if it is a normal account of this family. A face matched in one family must never
    sign in to an account of another family, or to the main admin (same phone number, old links…)."""
    if user is None or user.is_superuser:
        return None
    return user if family_of_user(user) == family_id else None


def member_of(profile):
    """The person on the tree this face code is for (any family), or None."""
    if not profile.member_id or not profile.branch:
        return None
    from ..branches import model_for_any
    M = model_for_any(profile.branch)
    return M.objects.filter(pk=profile.member_id).first() if M else None


def person_of(profile):
    """(account or None, person on the tree or None, phone) for a face code — all of its own family."""
    member = member_of(profile)
    user = profile.user
    if user is None and profile.member_id:
        for link in MemberLink.all_objects.filter(branch=profile.branch, member_id=profile.member_id).select_related("user"):
            if family_account(link.user, profile.family_id):
                user = link.user
                break
    user = family_account(user, profile.family_id)
    phone = ""
    if member is not None and member.mobile_number:
        phone = member.mobile_number
    elif user is not None and getattr(user, "profile", None):
        phone = user.profile.phone_number
    return user, member, phone


def is_live(profile):
    """Can this face code still lead to someone? (Not a person deleted from the tree, not the main admin.)"""
    if profile.member_id:
        return member_of(profile) is not None
    u = profile.user
    return u is not None and u.is_active and not u.is_superuser


def person_key(profile):
    """Which person a face code is for — two face codes of the same person give the same key."""
    if profile.member_id:
        return ("m", profile.branch, profile.member_id)
    link = MemberLink.all_objects.filter(user_id=profile.user_id).exclude(member_id=None).first() if profile.user_id else None
    if link and branch_family(link.branch) == profile.family_id:
        return ("m", link.branch, link.member_id)
    return ("u", profile.user_id)


def family_brief(fid, request):
    f = Family.objects.filter(pk=fid).first()
    if not f:
        return None
    return {"slug": f.slug, "name": f.name, "color": f.color, "place": f.place,
            "logo": request.build_absolute_uri(f.logo.url) if f.logo else None}


def attach_user(p, user):
    """Tie face code `p` to `user` (one face code per account). Only an account of p's own family.
    A face code the account already has: merged in (same family, not someone else's) or let go."""
    if user is None or family_account(user, p.family_id) is None or p.user_id == user.id:
        return p
    other = FaceProfile.all_objects.filter(user=user).exclude(pk=p.pk).first()
    if other is not None:
        if other.family_id == p.family_id and not other.member_id:
            p.embeddings = (p.embeddings or []) + (other.embeddings or [])  # their own set-up photos too
            other.delete()
        else:
            other.user = None
            other.save(update_fields=["user"])
    p.user = user
    return p


# ── Matching across every family ─────────────────────────────────────────────

def codes_from_images(images):
    """1–5 photos → face codes, or a Response explaining the problem (which photo, what's wrong)."""
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


# Every face code of every active family, as one ready-made matrix — rebuilt only when a face code is
# added, changed or deleted, or a family is switched on/off (one tiny query tells). Matching a face is
# then a single matrix multiply (well under 1 ms for thousands of people) instead of reading and
# parsing every face code from the database on every scan.
_bank = {"key": None, "rows": None, "starts": None, "ids": None}
_bank_lock = __import__("threading").Lock()
RANK_FLOOR = 0.25   # people less alike than this are never a match or a rival: not loaded at all
RANK_MAX = 40       # at most this many people are loaded per scan


def _bank_queryset():
    return (FaceProfile.all_objects.filter(family__is_active=True).exclude(embeddings=[])
            .exclude(member_id__isnull=True, user__isnull=True)                  # leads to nobody
            .exclude(member_id__isnull=True, user__is_superuser=True))           # the main admin's own face


def _face_bank():
    """→ (rows: N×128 unit vectors, starts: first row of each profile, ids: profile ids)."""
    import numpy as np
    from django.db.models import Count, Max, Sum
    qs = _bank_queryset()
    agg = qs.aggregate(n=Count("id"), s=Sum("id"), t=Max("updated_at"))
    active = tuple(Family.objects.filter(is_active=True).order_by("id").values_list("id", flat=True)) \
        if hasattr(Family, "is_active") else ()
    key = (agg["n"], agg["s"], agg["t"], active)
    with _bank_lock:
        if _bank["key"] == key:
            return _bank["rows"], _bank["starts"], _bank["ids"]
    rows, starts, ids = [], [], []
    for pid, emb in qs.order_by("id").values_list("id", "embeddings"):
        try:
            m = np.asarray(emb, dtype=np.float32).reshape(-1, 128)
        except (ValueError, TypeError):
            continue  # a damaged face code: skip it
        if not len(m):
            continue
        starts.append(sum(len(r) for r in rows))
        rows.append(m)
        ids.append(pid)
    mat = np.concatenate(rows) if rows else np.zeros((0, 128), np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True).clip(min=1e-6)
    out = (mat, np.asarray(starts, dtype=np.int64), ids)
    with _bank_lock:
        _bank.update(key=key, rows=out[0], starts=out[1], ids=out[2])
    return out


def rank_faces(code):
    """[(face code, score)] from EVERY active family, best first. score = how alike (cosine, −1…1),
    using the closest of that person's saved photos. Only the people that could matter (score ≥
    RANK_FLOOR, at least the best two) are loaded from the database."""
    import numpy as np
    rows, starts, ids = _face_bank()
    if not ids:
        return []
    q = np.asarray(code, dtype=np.float32).reshape(-1)
    if q.shape[0] != rows.shape[1]:
        return []
    q /= (np.linalg.norm(q) or 1.0)
    per = np.maximum.reduceat(rows @ q, starts)         # best photo of each person
    order = np.argsort(-per)
    keep = [i for i in order[:RANK_MAX] if per[i] >= RANK_FLOOR] or list(order[:2])
    keep = keep if len(keep) >= 2 else list(order[:2])
    want = {ids[i]: float(per[i]) for i in keep}
    profiles = _bank_queryset().filter(id__in=list(want)).select_related("user", "family")
    return sorted(((p, want[p.id]) for p in profiles), key=lambda x: x[1], reverse=True)


def search_faces(code):
    """Best and second-best matching face codes (used by the approval checks)."""
    ranked = [(p, s) for p, s in rank_faces(code) if is_live(p)]
    if not ranked:
        return None, 0.0, 0.0
    return ranked[0][0], ranked[0][1], ranked[1][1] if len(ranked) > 1 else 0.0


def family_matches(ranked):
    """→ [(face code, score)]: the matching person in each family, best family first.
    A family is left out when a different person there looks almost as alike (can't say who)."""
    t, margin = settings.FACE_IDENTIFY_THRESHOLD, settings.FACE_IDENTIFY_MARGIN
    near = [(p, s) for p, s in ranked if s >= t - margin and is_live(p)]
    out, seen = [], set()
    for p, sc in near:
        if sc < t:
            break
        if p.family_id in seen:
            continue
        seen.add(p.family_id)
        me = person_key(p)
        rival = next((s2 for p2, s2 in near if p2.family_id == p.family_id and person_key(p2) != me), 0.0)
        if sc - rival >= margin:
            out.append((p, sc))
    return out


def trusted_on(key, user):
    """Is this phone (face device key) already trusted for this account?"""
    return bool(key and user is not None and FaceDevice.objects.filter(key_hash=key_hash(key), user=user).exists())


def first_name_of(member, user):
    return ((member.first_name if member is not None else (user.first_name if user else "")) or "").strip().title()


def family_choice(p, request, key=None):
    """One "Which family?" option: a short face check for that family's person."""
    user, member, _phone = person_of(p)
    check = FaceCheck.objects.create(token=secrets.token_urlsafe(32), profile=p)
    return {"check": check.token, "family": family_brief(p.family_id, request), "first_name": first_name_of(member, user),
            "trusted": trusted_on(key, user)}


# ── Own face scan on this phone ──────────────────────────────────────────────

class FaceStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        p = FaceProfile.all_objects.filter(user=request.user).first()
        return Response({"enrolled": bool(p), "since": p.updated_at.isoformat() if p else None,
                         "available": face.available()})

    def delete(self, request):
        FaceProfile.all_objects.filter(user=request.user).delete()
        FaceDevice.objects.filter(user=request.user).delete()
        return Response(status=204)


class FaceEnrollView(APIView):
    """Set up face scan on my own phone. The face code goes to MY family, for MY person on the tree."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [FaceThrottle]

    def post(self, request):
        if request.data.get("consent") not in (True, "true", "1", 1):
            return Response({"detail": "Please agree to save your face code first.", "code": "consent"}, status=400)
        codes, err = codes_from_images(request.data.get("images") or [])
        if err is not None:
            return err

        user = request.user
        fam = family_of_user(user)
        key = secrets.token_urlsafe(32)
        with transaction.atomic():
            # my person on the tree — only if they are in my own family
            link = MemberLink.all_objects.filter(user=user).exclude(member_id=None).first()
            if link and fam and branch_family(link.branch) != fam:
                link = None
            p = FaceProfile.all_objects.filter(user=user).first()
            if p is not None and fam and p.family_id != fam and (p.member_id and branch_family(p.branch) != fam):
                # an old face code tied to someone in another family: leave that one to its family
                p.user = None
                p.save(update_fields=["user"])
                p = None
            if link:
                scanned = FaceProfile.all_objects.filter(branch=link.branch, member_id=link.member_id).first()
                if p is None:
                    p = scanned  # the family admin scanned me already: take that one over
                elif scanned is not None and scanned.pk != p.pk:
                    scanned.delete()  # my own new set-up replaces the admin's scan
            p = p or FaceProfile(user=user)
            p.user, p.embeddings, p.consent_at = user, codes, timezone.now()
            if link:
                p.branch, p.member_id = link.branch, link.member_id
            p.save()  # → stored in my person's family
            # one face-scan phone per person: setting up again (or on a new phone) replaces the old one
            FaceDevice.objects.filter(user=user).delete()
            FaceDevice.objects.create(user=user, key_hash=key_hash(key), name=str(request.data.get("device_name", ""))[:60])
        return Response({"device_key": key, "enrolled": True}, status=201)


def login_answer(request, key, get_code):
    """"Welcome back" for the phone with this device_key. get_code() → the face code (or FaceError).
    → Response. Shared by /face/login and /face/scan."""
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
    profile = FaceProfile.all_objects.filter(user=user).first()
    if profile is not None and profile.member_id and family_account(user, profile.family_id) is None:
        # this phone was tied to an account of another family (or the main admin) for a family
        # member's face — start over with a fresh face check so they land in the right family
        device.delete()
        return Response({"detail": "Please scan again to open your family.", "code": "unknown_device"}, status=401)
    if profile is None or not profile.embeddings:
        device.delete()
        return Response({"detail": "Face scan was turned off. Please use your phone number.",
                         "code": "unknown_device"}, status=401)
    try:
        code = get_code()
    except face.FaceError as exc:
        return face_error(exc)  # no face / too dark / blurry: doesn't count as a wrong try

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
    # the same face in other families too? → the app asks "Which family?" before opening
    mine = family_of_user(user)
    also = [family_choice(p, request, key) for p, _ in family_matches(rank_faces(code)) if p.family_id != mine]
    return Response({**tokens_for(user), "me": me_payload(user, request), "also": also})


class FaceLoginView(APIView):
    """"Welcome back" — 1:1 check of the face against the account this phone is set up for."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FaceThrottle]

    def post(self, request):
        return login_answer(request, request.data.get("device_key"), lambda: face.embed(request.data.get("image")))


# ── Find the person by face, in any family ───────────────────────────────────

class FaceDetectView(APIView):
    """POST /auth/face/detect {image} → where the face is (x, y, w, h as 0..1 of the upright photo) and
    whether it's good enough to scan. Called several times a second while the camera is open, so the app
    can draw the "detecting" box and scan by itself the moment a face is good. Keeps nothing."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FaceDetectThrottle]

    def post(self, request):
        try:
            return Response(face.detect(request.data.get("image")))
        except face.FaceError as exc:
            return face_error(exc)


def identify_answer(request, get_code):
    """Find whose face this is, in any family. get_code() → the face code (or FaceError). → Response.
    Shared by /face/identify and /face/scan."""
    try:
        code = get_code()  # exactly one clear face, or why not
    except face.FaceError as exc:
        return face_error(exc)
    ranked = rank_faces(code)
    if not ranked or ranked[0][1] < settings.FACE_IDENTIFY_THRESHOLD:
        return Response({"detail": "We couldn't find you. Try again in good light, or use your phone number.",
                         "code": "no_match"}, status=401)
    matches = family_matches(ranked)
    if not matches:
        if not any(is_live(p) for p, s in ranked if s >= settings.FACE_IDENTIFY_THRESHOLD):
            return Response({"detail": "We couldn't find you. Try again in good light, or use your phone number.",
                             "code": "no_match"}, status=401)
        return Response({"detail": "We aren't sure it's you. Please use your phone number this time.",
                         "code": "unsure"}, status=401)
    key = request.data.get("device_key")
    if len(matches) > 1:
        # the same face is in more than one family: let the person choose which to open
        return Response({"need_family": True, "choices": [family_choice(p, request, key) for p, _ in matches],
                         "expires_in": CHECK_MINUTES * 60})
    best = matches[0][0]
    user, member, phone = person_of(best)
    if user is not None and not user.is_active:
        return Response({"detail": "Your request to join was declined. Please contact the secretary.", "code": "declined"}, status=403)

    # a phone already trusted for this person → straight in
    if key and user is not None:
        dev = FaceDevice.objects.filter(key_hash=key_hash(key), user=user).first()
        if dev:
            dev.last_used, dev.failed = timezone.now(), 0
            dev.save(update_fields=["last_used", "failed"])
            from ..tenancy import lock_to_user_family
            lock_to_user_family(user)
            return Response({**tokens_for(user), "me": me_payload(user, request), "trusted": True,
                             "family": family_brief(best.family_id, request)})

    if len(digits(phone)) < 4:
        return Response({"detail": "We found you, but there's no phone number on your record. "
                                   "Ask your family admin to add it, or sign in with your phone number.",
                         "code": "no_phone", "family": family_brief(best.family_id, request)}, status=409)
    check = FaceCheck.objects.create(token=secrets.token_urlsafe(32), profile=best)
    return Response({"need_check": True, "check": check.token, "first_name": first_name_of(member, user),
                     "family": family_brief(best.family_id, request), "expires_in": CHECK_MINUTES * 60})


class FaceIdentifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FaceThrottle]

    def post(self, request):
        return identify_answer(request, lambda: face.embed(request.data.get("image")))


class FaceScanView(APIView):
    """POST /auth/face/scan {image, mode, device_key?} — one request per camera frame. The photo is
    opened and checked once; if the face is good it is matched straight away from the same photo (no
    second upload, no second request). The app stops scanning the moment "outcome" comes back."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FaceDetectThrottle]

    def post(self, request):
        mode = request.data.get("mode") or "identify"
        if mode not in ("identify", "login"):
            return Response({"detail": "mode must be identify or login", "code": "bad_mode"}, status=400)
        try:
            a = face.analyse(request.data.get("image"))
        except face.FaceError as exc:
            return face_error(exc)
        seen = face.seen_of(a)
        if not seen["ok"]:
            return Response({"seen": seen})
        # a real try at matching: counts against the (much smaller) face-match limit
        limit = FaceThrottle()
        if not limit.allow_request(request, self):
            wait = limit.wait()
            return Response({"seen": seen, "outcome": {"status": 429, "data": {
                "detail": "Too many tries. Please wait a little, or use your phone number.", "code": "throttled",
                "retry_in": int(wait or 60)}}})
        get_code = lambda: face.code_of(a)  # noqa: E731
        if mode == "login":
            r = login_answer(request, request.data.get("device_key"), get_code)
        else:
            r = identify_answer(request, get_code)
        return Response({"seen": seen, "outcome": {"status": r.status_code, "data": r.data}})


class FaceConfirmView(APIView):
    """The last 4 digits of the person's phone (or a phone already trusted for them) → sign in to
    THEIR family's account, and trust this phone from now on."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [FaceThrottle]

    @transaction.atomic
    def post(self, request):
        from app1.models import Profile
        from ..tenancy import lock_to_user_family, set_current_family
        from .auth import family_paused, find_user_by_phone
        from .. import otp

        check = FaceCheck.objects.select_for_update().select_related("profile").filter(token=str(request.data.get("check", ""))).first()
        if check is None or check.used or check.created_at < timezone.now() - timedelta(minutes=CHECK_MINUTES):
            return Response({"detail": "This face scan has expired. Please scan again.", "code": "expired"}, status=400)
        p = check.profile
        user, member, phone = person_of(p)  # only an account of the family the face belongs to
        trusted = trusted_on(request.data.get("device_key"), user)
        last4 = digits(request.data.get("last4"))
        if not trusted and (len(last4) != 4 or last4 != digits(phone)[-4:]):
            if not request.data.get("last4"):
                return Response({"detail": "Enter the last 4 digits of your phone number.", "code": "need_digits",
                                 "first_name": first_name_of(member, user), "family": family_brief(p.family_id, request)}, status=400)
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
            # added by the family admin, never used the app: make their account now, in their family
            norm = otp.normalize_phone(phone) or phone
            set_current_family(p.family_id)
            user = find_user_by_phone(norm, family_id=p.family_id)
            if user is None:
                from django.contrib.auth import get_user_model
                U = get_user_model()
                name = f"{member.first_name or ''} {member.last_name or ''}".strip() if member is not None else norm
                base = "m" + digits(norm)
                username, n = base, 2
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
        if p.member_id:
            # links made earlier from another family's account to this person are wrong: remove them
            MemberLink.all_objects.filter(branch=p.branch, member_id=p.member_id).exclude(user=user) \
                .exclude(user__family_access__family_id=p.family_id).delete()
        if not user.is_active:
            return Response({"detail": "Your request to join was declined. Please contact the secretary.", "code": "declined"}, status=403)
        blocked = family_paused(user)
        if blocked:
            return Response({"detail": blocked, "code": "paused"}, status=403)

        # the face code now belongs to this account (their own earlier set-up in this family is merged in)
        attach_user(p, user)
        p.save()

        if trusted:
            key = request.data.get("device_key")
            FaceDevice.objects.filter(key_hash=key_hash(key), user=user).update(last_used=timezone.now(), failed=0)
        else:
            key = secrets.token_urlsafe(32)
            FaceDevice.objects.create(user=user, key_hash=key_hash(key), name=str(request.data.get("device_name", ""))[:60],
                                      last_used=timezone.now())
        lock_to_user_family(user)
        return Response({**tokens_for(user), "me": me_payload(user, request), "device_key": key,
                         "family": family_brief(p.family_id, request)})


# ── Family admin scans a member ──────────────────────────────────────────────

class AdminMemberFaceView(APIView):
    """Family admin scans a member's face on the spot (camera or uploaded photos).
    The face code always goes to the member's own family — never to a linked account's other family."""
    permission_classes = [IsStaff]

    def _member(self, branch, pk):
        from ..branches import get_member
        return get_member(branch, pk)  # only this family's branches

    def get(self, request, branch, pk):
        if self._member(branch, pk) is None:
            return Response({"detail": "Not found."}, status=404)
        p = FaceProfile.all_objects.filter(branch=branch, member_id=pk).first()
        return Response({"enrolled": bool(p and p.embeddings), "since": p.updated_at if p else None, "available": face.available()})

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
        fam = branch_family(branch)
        p = FaceProfile.all_objects.filter(branch=branch, member_id=pk).first()
        if p is None:
            # the member set up face scan themselves (no person attached yet)? use that one — same family only
            for link in MemberLink.all_objects.filter(branch=branch, member_id=pk).select_related("user"):
                if family_account(link.user, fam):
                    p = FaceProfile.all_objects.filter(user=link.user, family_id=fam, member_id__isnull=True).first()
                    if p:
                        break
        p = p or FaceProfile(branch=branch, member_id=pk)
        p.branch, p.member_id, p.embeddings, p.consent_at = branch, pk, codes, timezone.now()
        p.family_id = fam
        if p.user_id is None:
            for link in MemberLink.all_objects.filter(branch=branch, member_id=pk).select_related("user"):
                if family_account(link.user, fam):
                    attach_user(p, link.user)
                    break
        elif family_account(p.user, fam) is None:
            p.user = None  # was tied to another family's account
        p.save()  # → stored in the member's family

        photo = None
        if request.data.get("set_photo") in (True, "true", "1", 1):
            # the straight-on scan photo becomes the member's profile picture (cut around the face)
            from django.core.files.base import ContentFile
            try:
                jpg = face.portrait(request.data["images"][0])
            except face.FaceError:
                jpg = None
            if jpg:
                old = m.photo.name if m.photo else None
                m.photo.save(f"face-{branch}-{pk}-{secrets.token_hex(4)}.jpg", ContentFile(jpg), save=False)
                m.save(update_fields=["photo"])
                if old and old != m.photo.name:
                    transaction.on_commit(lambda: m.photo.storage.delete(old))
                photo = request.build_absolute_uri(m.photo.url)
        return Response({"enrolled": True, "since": p.updated_at, "has_phone": len(digits(m.mobile_number)) >= 4,
                         "photo": photo, "family": family_brief(p.family_id, request)}, status=201)

    def delete(self, request, branch, pk):
        if self._member(branch, pk) is None:
            return Response({"detail": "Not found."}, status=404)
        FaceProfile.all_objects.filter(branch=branch, member_id=pk).delete()
        return Response(status=204)
