from django.db import models
from django.urls import reverse
from django.contrib.auth.models import User
from mptt.models import MPTTModel, TreeForeignKey
from django.db import models


# association annual report-------------------

class AnnualReport(models.Model):
    title = models.CharField(max_length=255)
    year = models.CharField(max_length=20, help_text="Example: 2023 - 2024")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.year})"


class AnnualReportPDF(models.Model):
    report = models.ForeignKey(
        AnnualReport,
        on_delete=models.CASCADE,
        related_name='pdfs'
    )
    title = models.CharField(max_length=255)
    pdf = models.FileField(upload_to='annual_reports/pdfs/')

    def __str__(self):
        return self.title

# LIFE MEMBER ---------------------------

class LifeMember(models.Model):
    name = models.CharField(max_length=200)
    membership_no = models.IntegerField(unique=True)  # Changed from CharField to IntegerField

    def __str__(self):
        return f"{self.name} ({self.membership_no})"


# -------------------------------------
class PremiumEvent(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    image = models.ImageField(upload_to='premium_events/')
    description = models.TextField()
    date = models.DateField(blank=True, null=True)  # Optional date
    location = models.CharField(max_length=255, blank=True)  # Optional location

    def __str__(self):
        return self.title

class PremiumEventImage(models.Model):
    event = models.ForeignKey(PremiumEvent, on_delete=models.CASCADE, related_name='gallery_images')
    image = models.ImageField(upload_to='premium_events/gallery/')
    caption = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Image for {self.event.title}"



# class TeamMember(models.Model):
#     name = models.CharField(max_length=100)
#     position = models.CharField(max_length=100)
#     image = models.ImageField(upload_to='team/')
#     bio = models.TextField(blank=True)
#     slug = models.SlugField(unique=True)

#     # Social media links
#     facebook = models.URLField(blank=True)
#     twitter = models.URLField(blank=True)
#     linkedin = models.URLField(blank=True)
#     instagram = models.URLField(blank=True)

#     # New fields
#     is_women_association = models.BooleanField(default=False)
#     gender = models.CharField(
#         max_length=10,
#         choices=(('Male', 'Male'), ('Female', 'Female')),
#         blank=True
#     )

#     def __str__(self):
#         return self.name

class TeamMember(models.Model):
    name = models.CharField(max_length=100)
    position = models.CharField(max_length=100)
    image = models.ImageField(upload_to='team/')
    bio = models.TextField(blank=True)
    slug = models.SlugField(unique=True)

    facebook = models.URLField(blank=True)
    twitter = models.URLField(blank=True)
    linkedin = models.URLField(blank=True)
    instagram = models.URLField(blank=True)

    is_women_association = models.BooleanField(default=False)
    gender = models.CharField(
        max_length=10,
        choices=(('Male', 'Male'), ('Female', 'Female')),
        blank=True
    )
    year = models.CharField(max_length=20, blank=True, help_text="Example: '2011 - 2012'")

    def __str__(self):
        return f"{self.name} ({self.year})"
    

    


class Topic(models.Model):
    title = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class Comment(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    posted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Comment by {self.user.username}'
    
# --------------------------------------------------------------------------#

class Memory(models.Model):
    name = models.CharField(max_length=255)
    birth_date = models.DateField()
    death_date = models.DateField()
    image = models.ImageField(upload_to='memory_images/')
    description = models.TextField()

    def __str__(self):
        return self.name


class Member(MPTTModel):
    GENDER_CHOICES = (
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    date_of_death = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)

    parent = TreeForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    spouses = models.ManyToManyField('self', symmetrical=True, blank=True)
    photo = models.ImageField(upload_to='members/', null=True, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    class MPTTMeta:
        order_insertion_by = ['first_name']

    class Meta:
        verbose_name_plural = 'Members'
        ordering = ['first_name', 'last_name']



# class Person(models.Model):
#     GENDER_CHOICES = (
#         ('M', 'Male'),
#         ('F', 'Female'),
#         ('O', 'Other'),
#     )

#     first_name = models.CharField(max_length=100)
#     last_name = models.CharField(max_length=100)
#     date_of_birth = models.DateField(null=True, blank=True)
#     date_of_death = models.DateField(null=True, blank=True)
#     gender = models.CharField(max_length=1, choices=GENDER_CHOICES)

#     father = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children_by_father')
#     mother = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children_by_mother')
#     spouses = models.ManyToManyField('self', symmetrical=True, blank=True)

#     def __str__(self):
#         return f"{self.first_name} {self.last_name}"




class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    pin_code = models.CharField(max_length=10, blank=True)
    profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True)
    is_approved = models.BooleanField(default=False)  # ✅ New field

    def __str__(self):
        return self.full_name


# Create your models here.
class Gallery(models.Model):
    headline = models.CharField(max_length=255, default='Default Headline')
    subhead =models.CharField(max_length=250)
    image =models.ImageField(upload_to="images/%y")

    def __str__(self):
        return self.headline

    
class Advertisement(models.Model):
    title = models.CharField(max_length=100)
    image = models.ImageField(upload_to='advertisements/')
    link = models.URLField(blank=True, null=True)  # Optional: link when clicked
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
    

# ----------------(event)---------------------
from django.utils import timezone

class Event(models.Model):
    title       = models.CharField(max_length=200)
    category    = models.CharField(max_length=100)
    date        = models.DateField()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']  # newest first

    def __str__(self):
        return self.title

    @property
    def cover_image(self):
        """Returns the first image or None."""
        return self.images.first()


class EventImage(models.Model):
    event   = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='images')
    image   = models.ImageField(upload_to='events/%Y/%m/')  # organised by year/month
    caption = models.CharField(max_length=200, blank=True)
    order   = models.PositiveIntegerField(default=0)        # control display order

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.event.title} — image {self.id}"
