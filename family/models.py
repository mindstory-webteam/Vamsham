from django.db import models
from mptt.models import MPTTModel, TreeForeignKey


class BaseFamilyMember(MPTTModel):
    GENDER_CHOICES = (
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    )

    # ── 5 Membership categories ──────────────────────────────────
    MEMBERSHIP_CATEGORIES = (
        ('LM',  'Life Member'),
        ('LMF', 'Life Member Family'),
        ('PM',  'Paid Member'),
        ('PMF', 'Paid Member Family'),
        ('M',   'Member'),
        ('NM',  'Not a member'),
    )

    # Prefix map for auto-generating membership numbers.
    # 'NM' (not a member) never gets a number.
    MEMBERSHIP_PREFIX = {
        'LM':  'LM',
        'LMF': 'LMF',
        'PM':  'PM',
        'PMF': 'PMF',
        'M':   'M',
    }

    first_name  = models.CharField(max_length=100)
    last_name   = models.CharField(max_length=100)
    gender      = models.CharField(max_length=1, choices=GENDER_CHOICES, default='M')

    date_of_birth  = models.DateField(null=True, blank=True)
    place_of_birth = models.CharField(max_length=255, blank=True, null=True)

    baptism_date  = models.DateField(null=True, blank=True)
    baptism_place = models.CharField(max_length=255, blank=True, null=True)

    communion_date  = models.DateField(null=True, blank=True)
    communion_place = models.CharField(max_length=255, blank=True, null=True)

    marriage_date  = models.DateField(null=True, blank=True)
    marriage_place = models.CharField(max_length=255, blank=True, null=True)

    date_of_death = models.DateField(null=True, blank=True)
    place_of_death = models.CharField(max_length=255, blank=True, null=True)
    burial_place   = models.CharField(max_length=255, blank=True, null=True)
    cause_of_death = models.CharField(max_length=255, blank=True, null=True)

    mobile_number = models.CharField(max_length=20, blank=True, null=True)
    email         = models.EmailField(blank=True, null=True)

    education = models.CharField(max_length=255, blank=True, null=True)
    employed  = models.CharField(max_length=255, blank=True, null=True)
    blood_group = models.CharField(max_length=5, blank=True, null=True)

    photo        = models.ImageField(upload_to='members/',      null=True, blank=True)
    family_photo = models.ImageField(upload_to='family-photo/', null=True, blank=True)

    membership_category = models.CharField(
        max_length=3,                       # ← increased from 2 to 3 for 'LMF'/'PMF'
        choices=MEMBERSHIP_CATEGORIES,
        default='M',
        help_text='Life Member / Life Member Family / Paid Member / Paid Member Family / Member'
    )
    membership_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        unique=True,
        help_text='Auto-generated with category prefix (e.g. LM0001, LMF0001, PM0001, PMF0001, M0001)'
    )

    date_updated = models.DateTimeField(auto_now=True)

    parent = TreeForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='children'
    )
    spouses = models.ManyToManyField('self', symmetrical=True, blank=True)

    birth_order = models.PositiveIntegerField(
        default=0,
        help_text='Order of birth among siblings (1 = firstborn)'
    )

    class MPTTMeta:
        order_insertion_by = ['birth_order', 'first_name']

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @classmethod
    def next_membership_number(cls, category):
        """
        Next free number for a category, e.g. LM0231.

        Uses the highest existing number (not a count), so deleting a member
        can never cause a duplicate. Numbers are unique per family table, the
        same way they were before.
        """
        import re
        prefix = cls.MEMBERSHIP_PREFIX.get(category)
        if not prefix:
            return None
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
        highest = 0
        for num in cls.objects.filter(membership_number__startswith=prefix) \
                              .values_list('membership_number', flat=True):
            m = pattern.match(num or '')
            if m:
                highest = max(highest, int(m.group(1)))
        return f"{prefix}{str(highest + 1).zfill(4)}"

    def save(self, *args, **kwargs):
        # Auto-generate a membership number for categories that get one
        if self.membership_category and not self.membership_number:
            self.membership_number = self.next_membership_number(self.membership_category)

        if self.parent and self.birth_order == 0:
            self.birth_order = self.parent.children.count() + 1

        super().save(*args, **kwargs)


# ── 8 Named family branches ──────────────────────────────────────

class AipuFamily(BaseFamilyMember):
    class Meta:
        verbose_name        = 'Sr. Aipu Family Member'
        verbose_name_plural = 'Sr. Aipu Family Members'
        ordering = ['first_name', 'last_name']


class LonappanFamily(BaseFamilyMember):
    class Meta:
        verbose_name        = 'Lonappan Family Member'
        verbose_name_plural = 'Lonappan Family Members'
        ordering = ['first_name', 'last_name']


class FrancisFamily(BaseFamilyMember):
    class Meta:
        verbose_name        = 'Fr. Francis Family Member'
        verbose_name_plural = 'Fr. Francis Family Members'
        ordering = ['first_name', 'last_name']


class VarunnyFamily(BaseFamilyMember):
    class Meta:
        verbose_name        = 'Varunny Family Member'
        verbose_name_plural = 'Varunny Family Members'
        ordering = ['first_name', 'last_name']


class ThomaFamily(BaseFamilyMember):
    class Meta:
        verbose_name        = 'Thoma Family Member'
        verbose_name_plural = 'Thoma Family Members'
        ordering = ['first_name', 'last_name']


class ChakoruFamily(BaseFamilyMember):
    class Meta:
        verbose_name        = 'Chakoru Family Member'
        verbose_name_plural = 'Chakoru Family Members'
        ordering = ['first_name', 'last_name']


class KochuvareedFamily(BaseFamilyMember):
    class Meta:
        verbose_name        = 'Kochuvareed Family Member'
        verbose_name_plural = 'Kochuvareed Family Members'
        ordering = ['first_name', 'last_name']


class PorinchuFamily(BaseFamilyMember):
    class Meta:
        verbose_name        = 'Porinchu Family Member'
        verbose_name_plural = 'Porinchu Family Members'
        ordering = ['first_name', 'last_name']


# ── Other / flexible family ───────────────────────────────────────

class OtherFamily(BaseFamilyMember):
    """
    Flexible family model grouped by family_group.
    Multiple root members per group are supported.
    """
    family_group = models.CharField(
        max_length=100,
        help_text="Group name, e.g. 'Mathew Family', 'Joseph Family'"
    )

    class Meta:
        verbose_name        = 'Other Family Member'
        verbose_name_plural = 'Other Family Members'
        ordering = ['family_group', 'first_name', 'last_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.family_group})"