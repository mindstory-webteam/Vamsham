from django.contrib import admin
from mptt.admin import MPTTModelAdmin
from django.utils.html import format_html
from .models import (
    Gallery, Event, Profile, Member, Memory, Topic,
    Comment, TeamMember, PremiumEvent, PremiumEventImage,
    Advertisement, LifeMember, AnnualReport, AnnualReportPDF,
    EventImage, FamilyPhoto,
)


# ── Annual Reports ────────────────────────────────────────────────────────────

class AnnualReportPDFInline(admin.TabularInline):
    model = AnnualReportPDF
    extra = 2


@admin.register(AnnualReport)
class AnnualReportAdmin(admin.ModelAdmin):
    list_display  = ('title', 'year', 'created_at')
    search_fields = ('title', 'year')
    ordering      = ('-created_at',)
    inlines       = [AnnualReportPDFInline]


# ── Premium Events ────────────────────────────────────────────────────────────

@admin.register(PremiumEvent)
class PremiumEventAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("title",)}
    list_display  = ('title', 'slug', 'date', 'location')
    search_fields = ('title', 'location')
    list_filter   = ('date',)


@admin.register(PremiumEventImage)
class PremiumEventImageAdmin(admin.ModelAdmin):
    list_display = ('event', 'caption')


# ── Team Members ─────────────────────────────────────────────────────────────

@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display        = ('name', 'position', 'year', 'is_women_association')
    list_filter         = ('is_women_association', 'year')
    search_fields       = ('name', 'position')
    prepopulated_fields = {'slug': ('name',)}


# ── Discussion ────────────────────────────────────────────────────────────────

@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    pass


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    pass


# ── Memories ─────────────────────────────────────────────────────────────────

@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
    list_display  = ('name', 'birth_date', 'death_date')
    search_fields = ('name',)
    list_filter   = ('birth_date', 'death_date')
    ordering      = ('death_date',)  # or ('-death_date') for most recent first


# ── Family Tree ───────────────────────────────────────────────────────────────

admin.site.register(Member, MPTTModelAdmin)


# ── Profiles ─────────────────────────────────────────────────────────────────

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display  = ('user', 'full_name', 'phone_number', 'pin_code', 'is_approved')
    search_fields = ('user__username', 'full_name', 'phone_number')
    list_filter   = ('is_approved', 'pin_code')
    ordering      = ('user__username',)


# ── Gallery ───────────────────────────────────────────────────────────────────

@admin.register(Gallery)
class GalleryAdmin(admin.ModelAdmin):
    list_display  = ('headline', 'subhead')
    search_fields = ('headline', 'subhead')
    ordering      = ('headline',)


# ── Advertisements ────────────────────────────────────────────────────────────

@admin.register(Advertisement)
class AdvertisementAdmin(admin.ModelAdmin):
    list_display  = ('title', 'created_at')
    search_fields = ('title',)
    ordering      = ('-created_at',)


# ── Life Members ─────────────────────────────────────────────────────────────

@admin.register(LifeMember)
class LifeMemberAdmin(admin.ModelAdmin):
    list_display  = ('name', 'receipt_no')
    search_fields = ('name', 'receipt_no')
    ordering      = ('name',)
# ── Events ───────────────────────────────────────────────────────────────────

class EventImageInline(admin.TabularInline):
    model           = EventImage
    extra           = 3
    fields          = ('image', 'image_preview', 'caption', 'order')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:60px;border-radius:4px;" />',
                obj.image.url
            )
        return "No image yet"
    image_preview.short_description = 'Preview'


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display   = ('title', 'category', 'date', 'image_count', 'created_at')
    list_filter    = ('category', 'date')
    search_fields  = ('title', 'description')
    date_hierarchy = 'date'
    inlines        = [EventImageInline]

    def image_count(self, obj):
        return format_html('<b>{}</b> photo(s)', obj.images.count())
    image_count.short_description = 'Photos'


@admin.register(EventImage)
class EventImageAdmin(admin.ModelAdmin):
    list_display  = ('event', 'image_preview', 'caption', 'order')
    list_filter   = ('event',)
    list_editable = ('caption', 'order')

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:50px;border-radius:4px;" />',
                obj.image.url
            )
        return "-"
    image_preview.short_description = 'Preview'


# ── Family Photos (flat gallery) ──────────────────────────────────────────────

@admin.register(FamilyPhoto)
class FamilyPhotoAdmin(admin.ModelAdmin):
    """
    Upload and manage family photos directly — no album concept.
    Supports bulk caption / order editing from the list view.
    """
    list_display   = ('photo_preview', 'title', 'year', 'caption', 'order', 'uploaded_at')
    list_filter    = ('year',)
    list_editable  = ('title', 'year', 'caption', 'order')
    search_fields  = ('title', 'caption', 'year')
    ordering       = ('order', '-uploaded_at')
    readonly_fields = ('photo_preview_large',)

    fieldsets = (
        (None, {
            'fields': ('title', 'image', 'photo_preview_large', 'caption', 'year', 'order'),
        }),
    )

    def photo_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:56px;width:56px;object-fit:cover;border-radius:6px;" />',
                obj.image.url,
            )
        return "—"
    photo_preview.short_description = 'Photo'

    def photo_preview_large(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:220px;border-radius:8px;margin-top:6px;" />',
                obj.image.url,
            )
        return "No image uploaded yet"
    photo_preview_large.short_description = 'Current Image'