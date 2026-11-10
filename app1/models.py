from django.db import models

from api.tenancy import FamilyScopedManager, fill_family
from django.urls import reverse
from django.contrib.auth.models import User
from mptt.models import MPTTModel, TreeForeignKey
from django.utils import timezone


# ── Annual Report ─────────────────────────────────────────────────────────────

class AnnualReport(models.Model):
    title      = models.CharField(max_length=255)
    year       = models.CharField(max_length=20, help_text="Example: 2023 - 2024")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.year})"


class AnnualReportPDF(models.Model):
    report = models.ForeignKey(AnnualReport, on_delete=models.CASCADE, related_name='pdfs')
    title  = models.CharField(max_length=255)
    pdf    = models.FileField(upload_to='annual_reports/pdfs/')

    def __str__(self):
        return self.title


# ── Life Member ───────────────────────────────────────────────────────────────

class LifeMember(models.Model):
    name          = models.CharField(max_length=200)
    membership_no = models.IntegerField(unique=True)
    receipt_no    = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.membership_no})"


# ── Premium Event ─────────────────────────────────────────────────────────────

class PremiumEvent(models.Model):
    title       = models.CharField(max_length=200)
    slug        = models.SlugField(unique=True)
    image       = models.ImageField(upload_to='premium_events/')
    description = models.TextField()
    date        = models.DateField(blank=True, null=True)
    location    = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.title


class PremiumEventImage(models.Model):
    event   = models.ForeignKey(PremiumEvent, on_delete=models.CASCADE, related_name='gallery_images')
    image   = models.ImageField(upload_to='premium_events/gallery/')
    caption = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Image for {self.event.title}"


# ── Team Member ───────────────────────────────────────────────────────────────

class TeamMember(models.Model):
    name      = models.CharField(max_length=100)
    position  = models.CharField(max_length=100)
    image     = models.ImageField(upload_to='team/')
    bio       = models.TextField(blank=True)
    slug      = models.SlugField(unique=True)
    facebook  = models.URLField(blank=True)
    twitter   = models.URLField(blank=True)
    linkedin  = models.URLField(blank=True)
    instagram = models.URLField(blank=True)
    is_women_association = models.BooleanField(default=False)
    gender = models.CharField(
        max_length=10,
        choices=(('Male', 'Male'), ('Female', 'Female')),
        blank=True,
    )
    year = models.CharField(max_length=20, blank=True, help_text="Example: '2011 - 2012'")

    def __str__(self):
        return f"{self.name} ({self.year})"


# ── Discussion ────────────────────────────────────────────────────────────────

class Topic(models.Model):
    title      = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Comment(models.Model):
    topic     = models.ForeignKey(Topic, on_delete=models.CASCADE)
    user      = models.ForeignKey(User, on_delete=models.CASCADE)
    content   = models.TextField()
    posted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Comment by {self.user.username}'


# ── Memory ────────────────────────────────────────────────────────────────────

class Memory(models.Model):
    family = models.ForeignKey("api.Family", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    name        = models.CharField(max_length=255)
    birth_date  = models.DateField()
    death_date  = models.DateField()
    image       = models.ImageField(upload_to='memory_images/')
    description = models.TextField()

    class Meta:
        ordering = ['death_date']  # ascending; use ['-death_date'] for most recent first

    def __str__(self):
        return self.name


# ── Family Tree (MPTT) ────────────────────────────────────────────────────────

class Member(MPTTModel):
    GENDER_CHOICES = (('M', 'Male'), ('F', 'Female'), ('O', 'Other'))

    first_name    = models.CharField(max_length=100)
    last_name     = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    date_of_death = models.DateField(null=True, blank=True)
    gender        = models.CharField(max_length=1, choices=GENDER_CHOICES)
    parent        = TreeForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    spouses       = models.ManyToManyField('self', symmetrical=True, blank=True)
    photo         = models.ImageField(upload_to='members/', null=True, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    class MPTTMeta:
        order_insertion_by = ['first_name']

    class Meta:
        verbose_name_plural = 'Members'
        ordering = ['first_name', 'last_name']


# ── Profile ───────────────────────────────────────────────────────────────────

class Profile(models.Model):
    family = models.ForeignKey("api.Family", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    user          = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name     = models.CharField(max_length=255)
    phone_number  = models.CharField(max_length=20)
    pin_code      = models.CharField(max_length=10, blank=True)
    profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True)
    is_approved   = models.BooleanField(default=False)
    decided_at    = models.DateTimeField(null=True, blank=True)  # when the committee approved / declined the sign-up

    def __str__(self):
        return self.full_name


# ── Gallery ───────────────────────────────────────────────────────────────────

class Gallery(models.Model):
    headline = models.CharField(max_length=255, default='Default Headline')
    subhead  = models.CharField(max_length=250)
    image    = models.ImageField(upload_to="images/%y")

    def __str__(self):
        return self.headline


# ── Advertisement ─────────────────────────────────────────────────────────────

class Advertisement(models.Model):
    title      = models.CharField(max_length=100)
    image      = models.ImageField(upload_to='advertisements/')
    link       = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


# ── Event ─────────────────────────────────────────────────────────────────────

class Event(models.Model):
    family = models.ForeignKey("api.Family", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    title       = models.CharField(max_length=200)
    category    = models.CharField(max_length=100)
    date        = models.DateField()
    description = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    # Added for the mobile app (all optional, so the website is unaffected)
    location     = models.CharField(max_length=255, blank=True)
    start_time   = models.TimeField(null=True, blank=True)
    programme    = models.TextField(blank=True, help_text="One item per line, e.g. '10:00 Holy Mass'")
    rsvp_enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return self.title

    @property
    def cover_image(self):
        return self.images.first()


class EventImage(models.Model):
    event   = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='images')
    image   = models.ImageField(upload_to='events/%Y/%m/')
    caption = models.CharField(max_length=200, blank=True)
    order   = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.event.title} — image {self.id}"


# ── Family Photo (flat gallery, no albums) ────────────────────────────────────

class FamilyPhoto(models.Model):
    family = models.ForeignKey("api.Family", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    objects = FamilyScopedManager()
    all_objects = models.Manager()
    """
    A single photo in the family gallery.
    No album grouping — flat list filterable by year tag.
    """
    title       = models.CharField(max_length=200, help_text="Short title shown in the lightbox")
    image       = models.ImageField(upload_to='family_photos/%Y/%m/')
    caption     = models.CharField(max_length=255, blank=True, help_text="Optional extra description")
    year        = models.CharField(
        max_length=20, blank=True,
        help_text="e.g. 2023  or  2023–2024 — used for the year filter tabs"
    )
    order       = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['order', '-uploaded_at']
        verbose_name        = 'Family Photo'
        verbose_name_plural = 'Family Photos'

    def __str__(self):
        return self.title

for _m in (Profile, Event, Memory, FamilyPhoto):
    models.signals.pre_save.connect(fill_family, sender=_m, dispatch_uid=f"fill_family_{_m.__name__}")
