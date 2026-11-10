"""Sign-in (phone code or password), the signed-in user's own profile, and device tokens."""
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from app1.models import Profile

from .. import otp
from ..branches import BRANCH_LABELS, SLUGS, get_member
from ..tenancy import current_family_id, default_family_id, lock_to_user_family, set_current_family
from ..models import Family, FamilyAccess, DeviceToken, FaceProfile, DonorStatus, MemberLink, Payment
from ..people import summary
from ..permissions import is_approved

User = get_user_model()


class OTPThrottle(AnonRateThrottle):
    scope = "otp"


class LoginThrottle(AnonRateThrottle):
    scope = "login"


def tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def family_info(user, request=None):
    """The family shown in the app header / dashboard (name, colour, logo)."""
    from ..tenancy import current_family_id, family_for_user
    fid = current_family_id() if user.is_superuser else None
    fid = fid or family_for_user(user) or default_family_id()
    f = Family.objects.filter(pk=fid).first()
    if not f:
        return None
    logo = None
    if f.logo:
        logo = request.build_absolute_uri(f.logo.url) if request else f.logo.url
    return {"id": f.id, "slug": f.slug, "name": f.name, "place": f.place, "color": f.color, "logo": logo}


def family_paused(user):
    """A message if the person's family is paused by the main admin (main admins are never blocked)."""
    if user.is_superuser:
        return None
    from ..tenancy import family_for_user
    fid = family_for_user(user)
    if fid and not Family.objects.filter(pk=fid, is_active=True).exists():
        return "Your family's Vamsham is paused. Please contact the Vamsham team."
    return None


def me_payload(user, request=None):
    profile = getattr(user, "profile", None)
    link = MemberLink.objects.filter(user=user).first()
    member = None
    fee = None
    missing = []
    if link and link.member_id:
        m = get_member(link.branch, link.member_id)
        if m:
            member = summary(m, link.branch, request)
            missing = [label for field, label in (("date_of_birth", "date of birth"), ("blood_group", "blood group"),
                                                  ("mobile_number", "mobile number"), ("photo", "photo"))
                       if not getattr(m, field)]
            year = timezone.localdate().year
            paid = Payment.objects.filter(branch=link.branch, member_id=m.pk, paid_on__year=year,
                                          purpose__in=("annual_fee", "life_membership")).order_by("-paid_on").first()
            fee = {"year": year, "life_member": (m.membership_category or "").startswith("LM"),
                   "paid": bool(paid), "receipt_no": paid.receipt_no if paid else ""}
    donor = DonorStatus.objects.filter(user=user).first()
    if not user.is_active:
        state = "declined"
    elif is_approved(user):
        state = "approved"
    else:
        state = "pending"
    fam = family_info(user, request)
    return {
        "id": user.pk,
        "family": fam,
        "is_main_admin": user.is_superuser,
        "username": user.get_username(),
        "name": (profile.full_name if profile else "") or user.get_full_name() or user.get_username(),
        "phone": profile.phone_number if profile else "",
        "email": user.email,
        "is_staff": user.is_staff,
        "status": state,
        "member": member,
        "claim": {
            "branch": link.branch if link else "",
            "branch_label": BRANCH_LABELS.get(link.branch, "") if link else "",
            "text": link.claim_text if link else "",
        },
        "show_phone": link.show_phone if link else True,
        "face_enrolled": FaceProfile.objects.filter(user=user).exists(),
        "fee": fee,
        "missing_details": missing,
        "donor": {"available": donor.available if donor else False,
                  "last_donated": donor.last_donated.isoformat() if donor and donor.last_donated else None},
    }


def find_user_by_phone(phone):
    for p in Profile.all_objects.select_related("user").exclude(phone_number=""):  # any family
        if otp.normalize_phone(p.phone_number) == phone:
            return p.user
    return None


class OTPRequestView(APIView):
    """POST {phone} → sends a 6-digit code by SMS."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [OTPThrottle]

    def post(self, request):
        phone = otp.normalize_phone(request.data.get("phone"))
        if not phone:
            return Response({"detail": "Please enter a valid mobile number."}, status=400)
        try:
            code = otp.create_and_send(phone)
        except otp.OTPError as exc:
            return Response({"detail": str(exc)}, status=429)
        data = {"sent": True, "phone": phone, "expires_in": 300}
        if settings.OTP_DEMO:
            data["demo_code"] = code  # demo/testing only — see OTP_DEMO in settings
        return Response(data)


class OTPVerifyView(APIView):
    """POST {phone, code, name?} → tokens. Creates an account (waiting for approval) if new."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [OTPThrottle]

    @transaction.atomic
    def post(self, request):
        phone = otp.normalize_phone(request.data.get("phone"))
        if not phone:
            return Response({"detail": "Please enter a valid mobile number."}, status=400)
        try:
            otp.verify(phone, request.data.get("code"))
        except otp.OTPError as exc:
            return Response({"detail": str(exc)}, status=400)

        user = find_user_by_phone(phone)
        created = False
        if user is None:
            name = (request.data.get("name") or "").strip()[:150]
            username = "m" + phone.lstrip("+")
            # which family they ask to join: picked in the app (family slug), else the only/first family
            fam = None
            slug = (request.data.get("family") or "").strip()
            if slug:
                fam = Family.objects.filter(slug=slug, is_active=True).first()
                if fam is None:
                    return Response({"detail": "That family isn't on Vamsham. Please pick your family again."}, status=400)
            fam_id = fam.id if fam else (current_family_id() or default_family_id())
            set_current_family(fam_id)  # the new account (and its profile) belong to this family
            user = User.objects.create_user(username=username, first_name=name.split(" ")[0] if name else "")
            user.set_unusable_password()
            user.save()
            FamilyAccess.objects.update_or_create(user=user, defaults={"family_id": fam_id})
            Profile.objects.create(user=user, full_name=name or phone, phone_number=phone, is_approved=False, family_id=fam_id)
            created = True
        if not user.is_active:
            return Response({"detail": "Your request to join was declined. Please contact the secretary."}, status=403)
        blocked = family_paused(user)
        if blocked:
            return Response({"detail": blocked}, status=403)
        lock_to_user_family(user)
        return Response({"created": created, **tokens_for(user), "me": me_payload(user, request)})


class PasswordLoginView(APIView):
    """POST {username, password} → tokens. Used by committee members on the admin panel."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    def post(self, request):
        user = authenticate(request, username=request.data.get("username"), password=request.data.get("password"))
        if user is None:
            # allow signing in with email too
            u = User.objects.filter(email__iexact=request.data.get("username") or "").first()
            if u:
                user = authenticate(request, username=u.get_username(), password=request.data.get("password"))
        if user is None:
            return Response({"detail": "Wrong username or password."}, status=400)
        # the family's own sign-in link (/f/<family>) and the main-admin page only let the right people in
        if request.data.get("main") in (True, "true", "1") and not user.is_superuser:
            return Response({"detail": "This page is only for the main Vamsham admin. Use your family's sign-in link."}, status=403)
        slug = str(request.data.get("family") or "").strip()
        if slug and not user.is_superuser:
            from ..tenancy import family_for_user
            fam = Family.objects.filter(slug=slug).first()
            if fam is None or family_for_user(user) != fam.id:
                name = fam.name if fam else "this family"
                return Response({"detail": f"This account isn't on the {name} committee. Use your own family's sign-in link."}, status=403)
        blocked = family_paused(user)
        if blocked:
            return Response({"detail": blocked}, status=403)
        lock_to_user_family(user)
        return Response({**tokens_for(user), "me": me_payload(user, request)})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(me_payload(request.user, request))

    def patch(self, request):
        """Update name and privacy. Profile details in the tree go through change requests."""
        user = request.user
        profile = getattr(user, "profile", None)
        if "name" in request.data and profile:
            profile.full_name = str(request.data["name"])[:255]
            profile.save(update_fields=["full_name"])
        if "show_phone" in request.data:
            link, _ = MemberLink.objects.get_or_create(user=user)
            link.show_phone = bool(request.data["show_phone"])
            link.save(update_fields=["show_phone"])
        if "donor_available" in request.data:
            ds, _ = DonorStatus.objects.get_or_create(user=user)
            ds.available = bool(request.data["donor_available"])
            ds.save(update_fields=["available"])
        return Response(me_payload(user, request))


class ClaimView(APIView):
    """POST {branch, text, member_ref?} — a new user says which family they belong to."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        branch = request.data.get("branch", "")
        if branch and branch not in SLUGS:
            return Response({"detail": "Unknown family branch."}, status=400)
        link, _ = MemberLink.objects.get_or_create(user=request.user)
        link.branch = branch
        link.claim_text = str(request.data.get("text", ""))[:255]
        link.save()
        return Response(me_payload(request.user, request))


class DeviceTokenView(APIView):
    """POST {token, platform} — register the phone for push notifications."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = str(request.data.get("token", "")).strip()
        if not token:
            return Response({"detail": "token is required"}, status=400)
        DeviceToken.objects.update_or_create(
            token=token, defaults={"user": request.user, "platform": str(request.data.get("platform", ""))[:10]}
        )
        return Response({"ok": True}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        DeviceToken.objects.filter(user=request.user, token=request.data.get("token")).delete()
        return Response(status=204)
