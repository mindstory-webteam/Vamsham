"""
Tables used only by the mobile app / REST API.

Family members of the 9 original branches stay in the existing `family` app tables
(AipuFamily, LonappanFamily, ...). Branches created later by the committee keep their
people in `BranchMember`. A member is referred to everywhere in the API as
(branch slug, id) — see api/branches.py.
"""
from django.conf import settings
from django.db import models

from .tenancy import FamilyScopedManager, current_family_id, default_family_id, fill_family
from django.utils import timezone

from family.models import BaseFamilyMember

from . import branches as _branches

User = settings.AUTH_USER_MODEL


class Family(models.Model):
    """One family (association) on this server. Each has its own admins, members, tree and data."""
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=40, unique=True)
    place = models.CharField(max_length=120, blank=True)
    color = models.CharField(max_length=9, default="#3FD47A", help_text="Brand colour, e.g. #3FD47A")
    logo = models.ImageField(upload_to="family_logos/", blank=True, null=True)
    is_active = models.BooleanField(default=True, help_text="Paused families can't sign in")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "Families"

    def __str__(self):
        return self.name


class FamilyAccess(models.Model):
    """Which family a person (member or family admin) belongs to."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="family_access")
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="people")

    class Meta:
        verbose_name = "Family access"
        verbose_name_plural = "Family access"

    def __str__(self):
        return f"{self.user} → {self.family}"


def _family_fk():
    return models.ForeignKey(Family, on_delete=models.CASCADE, null=True, blank=True, related_name="+")


class FamilyBranch(models.Model):
    """A family branch. The committee can add, rename, hide or delete branches."""
    family = _family_fk()
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    slug = models.SlugField(max_length=20, unique=True, help_text="Short code used in links, e.g. 'lonappan'. Can't be changed.")
    name = models.CharField(max_length=100)
    table = models.CharField(max_length=40, blank=True, editable=False,
                             help_text="Original family table (only for the 9 first branches)")
    sort_order = models.PositiveIntegerField(default=0)
    hidden = models.BooleanField(default=False, help_text="Hidden branches don't show anywhere, but their people are kept")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Family branch"
        verbose_name_plural = "Family branches"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        _branches.invalidate()

    def delete(self, *args, **kwargs):
        out = super().delete(*args, **kwargs)
        _branches.invalidate()
        return out


class BranchMember(BaseFamilyMember):
    """People of the branches created from the dashboard (one shared table)."""
    branch = models.ForeignKey(FamilyBranch, on_delete=models.PROTECT, related_name="people")

    class Meta:
        ordering = ["first_name", "last_name"]
        verbose_name = "Family member (new branches)"
        verbose_name_plural = "Family members (new branches)"

    @classmethod
    def next_membership_number(cls, category):
        # numbers must be unique in the whole shared table, not only in one branch
        return BaseFamilyMember.next_membership_number.__func__(BranchMember, category)


class PhoneOTP(models.Model):
    phone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Login code (OTP)"

    def is_valid(self):
        return not self.used and timezone.now() < self.expires_at


class MemberLink(models.Model):
    """Connects an app account to a person in the family tree."""
    family = _family_fk()
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="member_link")
    branch = models.CharField(max_length=20, blank=True)
    member_id = models.PositiveIntegerField(null=True, blank=True)
    claim_text = models.CharField(
        max_length=255, blank=True,
        help_text="What the person said when signing up, e.g. 'wife of Jeevan Thomas'",
    )
    show_phone = models.BooleanField(default=True, help_text="Let approved family members see my phone number")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} → {self.branch}:{self.member_id or '?'}"


STATUS_CHOICES = (("pending", "Pending"), ("approved", "Approved"), ("declined", "Declined"))


class ChangeRequest(models.Model):
    """A member suggests a correction to a profile in the tree."""
    family = _family_fk()
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="change_requests")
    branch = models.CharField(max_length=20)
    member_id = models.PositiveIntegerField()
    field = models.CharField(max_length=50)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    note = models.CharField(max_length=255, blank=True)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class NewMemberRequest(models.Model):
    """A member asks to add a child / spouse / grandchild to the tree."""
    family = _family_fk()
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    RELATIONS = (("child", "Child"), ("spouse", "Husband / wife"))
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="new_member_requests")
    branch = models.CharField(max_length=20)
    relative_id = models.PositiveIntegerField(help_text="Parent (for a child) or partner (for a spouse)")
    relation = models.CharField(max_length=10, choices=RELATIONS, default="child")
    data = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    note = models.CharField(max_length=255, blank=True)
    created_member_id = models.PositiveIntegerField(null=True, blank=True)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class EventRSVP(models.Model):
    event = models.ForeignKey("app1.Event", on_delete=models.CASCADE, related_name="rsvps")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rsvps")
    people = models.PositiveSmallIntegerField(default=1)
    attending = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("event", "user")


class MemoryPrayer(models.Model):
    memory = models.ForeignKey("app1.Memory", on_delete=models.CASCADE, related_name="prayers")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("memory", "user")


BLOOD_GROUPS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")


class BloodRequest(models.Model):
    family = _family_fk()
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    posted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blood_requests")
    blood_group = models.CharField(max_length=4, choices=[(g, g) for g in BLOOD_GROUPS])
    units = models.PositiveSmallIntegerField(default=1)
    hospital = models.CharField(max_length=200)
    patient_name = models.CharField(max_length=120, blank=True)
    needed_by = models.DateTimeField(null=True, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    is_open = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class BloodResponse(models.Model):
    request = models.ForeignKey(BloodRequest, on_delete=models.CASCADE, related_name="responses")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("request", "user")


class DonorStatus(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="donor_status")
    available = models.BooleanField(default=True)
    last_donated = models.DateField(null=True, blank=True)


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=20, default="info")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class DeviceToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_tokens")
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Broadcast(models.Model):
    family = _family_fk()
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    audience = models.CharField(max_length=60)
    channels = models.JSONField(default=list)
    title = models.CharField(max_length=200, default="Vamsham")
    message = models.TextField()
    recipients = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Payment(models.Model):
    family = _family_fk()
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    PURPOSES = (
        ("annual_fee", "Annual fee"),
        ("life_membership", "Life membership"),
        ("donation", "Donation"),
        ("event", "Event"),
        ("other", "Other"),
    )
    METHODS = (("upi", "UPI"), ("cash", "Cash"), ("bank", "Bank transfer"), ("cheque", "Cheque"))
    receipt_no = models.CharField(max_length=20, unique=True, blank=True)
    payer_name = models.CharField(max_length=150)
    branch = models.CharField(max_length=20, blank=True)
    member_id = models.PositiveIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=20, choices=PURPOSES, default="donation")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=10, choices=METHODS, default="upi")
    reference = models.CharField(max_length=100, blank=True, help_text="UPI transaction id, cheque no., …")
    paid_on = models.DateField(default=timezone.localdate)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-id"]

    def save(self, *args, **kwargs):
        if not self.receipt_no:
            highest = 0
            for r in Payment.objects.values_list("receipt_no", flat=True):
                if r and r.startswith("RC-") and r[3:].isdigit():
                    highest = max(highest, int(r[3:]))
            self.receipt_no = f"RC-{highest + 1:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.receipt_no} · {self.payer_name} · ₹{self.amount}"


class AssociationSettings(models.Model):
    """Each family's settings the committee can change from the dashboard (Settings page)."""
    family = models.OneToOneField(Family, on_delete=models.CASCADE, null=True, blank=True, related_name="settings")
    app_name = models.CharField(max_length=60, default="Vamsham")
    family_name = models.CharField(max_length=80, default="Vamsham")
    association_name = models.CharField(max_length=150, default="Vamsham Family Association")
    secretary_whatsapp = models.CharField(max_length=20, blank=True, help_text="Digits with country code, e.g. 919876543210")
    upi_id = models.CharField(max_length=80, blank=True, help_text="e.g. yourfamily@sbi")
    upi_name = models.CharField(max_length=150, blank=True, default="Vamsham Family Association")
    annual_fee = models.DecimalField(max_digits=10, decimal_places=2, default=1000)
    life_fee = models.DecimalField(max_digits=10, decimal_places=2, default=5000)
    receipt_address = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Association settings"
        verbose_name_plural = "Association settings"

    def __str__(self):
        return f"{self.app_name} · {self.association_name}"

    @classmethod
    def load(cls, family_id=None):
        """This family's settings (created with the family's name the first time)."""
        cur = current_family_id()
        fid = family_id or (cur if cur and cur > 0 else None) or default_family_id()
        fam = Family.objects.filter(pk=fid).first() if fid else None
        if fam is None:
            return cls(family_name="Vamsham", association_name="Vamsham")  # no family: defaults, not saved
        obj = cls.objects.filter(family_id=fid).first()
        if obj is None:
            name = fam.name if fam else "Vamsham"
            obj = cls.objects.create(family_id=fid, family_name=name, association_name=f"{name} Family Association", upi_name=f"{name} Family Association")
        return obj


class FaceProfile(models.Model):
    """A member's face code for face-scan sign in. Only numbers (SFace embeddings), never photos."""
    family = _family_fk()
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="face_profile", null=True, blank=True)
    # set when a family admin scanned the member's face (the member may have no app account yet)
    branch = models.CharField(max_length=20, blank=True)
    member_id = models.PositiveIntegerField(null=True, blank=True)
    embeddings = models.JSONField(default=list)  # 3 x 128 floats (straight, left, right)
    consent_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["branch", "member_id"], condition=models.Q(member_id__isnull=False), name="one_face_per_member")]

    def __str__(self):
        return f"Face code · {self.user or f'{self.branch}:{self.member_id}'}"


class FaceDevice(models.Model):
    """A phone that may sign in with face scan. The phone keeps the secret key; we keep its hash."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="face_devices")
    key_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=60, blank=True)
    failed = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} · {self.name or 'phone'}"


class FaceCheck(models.Model):
    """A face found by face scan on a new phone, waiting for the last 4 digits of the person's phone."""
    token = models.CharField(max_length=64, unique=True)
    profile = models.ForeignKey(FaceProfile, on_delete=models.CASCADE, related_name="checks")
    tries = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)


# New family-owned rows belong to the current family.
for _m in (FamilyBranch, MemberLink, ChangeRequest, NewMemberRequest, BloodRequest, Broadcast, Payment, FaceProfile, AssociationSettings):
    models.signals.pre_save.connect(fill_family, sender=_m, dispatch_uid=f"fill_family_{_m.__name__}")


def _give_family(sender, instance, created, **kwargs):
    """Every new account belongs to a family: the current one, else the first. The main admin
    (superuser) belongs to no family — Vamsham is the app, not a family."""
    if created and not kwargs.get("raw") and not instance.is_superuser:
        fid = current_family_id()
        fid = fid if fid and fid > 0 else default_family_id()
        if fid:
            FamilyAccess.objects.get_or_create(user=instance, defaults={"family_id": fid})


models.signals.post_save.connect(_give_family, sender=User, dispatch_uid="give_family")
