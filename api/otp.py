"""Phone numbers, one-time login codes and SMS sending."""
import hashlib
import hmac
import json
import logging
import re
import secrets
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import PhoneOTP

log = logging.getLogger("api")


def normalize_phone(raw):
    """'98765 43210' / '+91-98765-43210' / '919876543210' -> '+919876543210'. Returns '' if invalid."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    if len(digits) < 11 or len(digits) > 15:
        return ""
    return "+" + digits


def mask_phone(phone):
    p = normalize_phone(phone)
    if not p:
        return ""
    return f"{p[:4]} {p[4]}•••• ••{p[-3:]}"


def _hash(phone, code):
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


class OTPError(Exception):
    pass


def create_and_send(phone):
    """Create a code for this phone and send it; returns the code. Raises OTPError when rate-limited."""
    hour_ago = timezone.now() - timedelta(hours=1)
    if PhoneOTP.objects.filter(phone=phone, created_at__gte=hour_ago).count() >= 5:
        raise OTPError("Too many codes requested. Please try again in an hour.")

    if settings.OTP_TEST_PHONE and phone == normalize_phone(settings.OTP_TEST_PHONE):
        code = settings.OTP_TEST_CODE
    else:
        code = f"{secrets.randbelow(10**6):06d}"

    PhoneOTP.objects.filter(phone=phone, used=False).update(used=True)
    PhoneOTP.objects.create(
        phone=phone,
        code_hash=_hash(phone, code),
        expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )
    send_sms_code(phone, code)
    return code


def verify(phone, code):
    """True if the code is right. Counts wrong attempts."""
    otp = PhoneOTP.objects.filter(phone=phone, used=False).first()
    if not otp or not otp.is_valid():
        raise OTPError("This code has expired. Please ask for a new one.")
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        otp.used = True
        otp.save(update_fields=["used"])
        raise OTPError("Too many wrong tries. Please ask for a new code.")
    if not hmac.compare_digest(otp.code_hash, _hash(phone, (code or "").strip())):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        raise OTPError("That code is not right. Please check and try again.")
    otp.used = True
    otp.save(update_fields=["used"])
    return True


def send_sms_code(phone, code):
    backend = settings.SMS_BACKEND
    if backend == "console":
        log.warning("OTP for %s is %s (SMS_BACKEND=console, development only)", phone, code)
        return
    if backend == "msg91":
        # MSG91 OTP API. Check your MSG91 dashboard for the exact template setup.
        url = (
            "https://control.msg91.com/api/v5/otp"
            f"?template_id={settings.MSG91_TEMPLATE_ID}&mobile={phone.lstrip('+')}&otp={code}"
        )
        req = urllib.request.Request(
            url, method="POST", data=b"{}",
            headers={"authkey": settings.MSG91_AUTH_KEY, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read() or b"{}")
                if body.get("type") == "error":
                    log.error("MSG91 error: %s", body)
        except Exception as exc:  # network errors should not crash the request
            log.exception("MSG91 send failed: %s", exc)
        return
    raise RuntimeError(f"Unknown SMS_BACKEND {backend!r}")
