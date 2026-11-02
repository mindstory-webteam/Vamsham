from django.contrib import admin
from mptt.admin import MPTTModelAdmin

from .models import (
    AipuFamily,
    LonappanFamily,
    FrancisFamily,
    VarunnyFamily,
    ThomaFamily,
    ChakoruFamily,
    KochuvareedFamily,
    PorinchuFamily,
    OtherFamily,
)


# ── Membership badge colours for list display ─────────────────────
CATEGORY_COLOURS = {
    'LM':  ('#1a5fa0', '#e8f1fc'),   # dark blue / light blue
    'LMF': ('#0d7a5f', '#e0f7f1'),   # dark green / light green
    'PM':  ('#b45309', '#fef3c7'),   # amber / light amber
    'PMF': ('#7c3aed', '#ede9fe'),   # purple / light purple
    'M':   ('#374151', '#f3f4f6'),   # grey / light grey
}


# ── Shared fieldsets used by all families ─────────────────────────
COMMON_FIELDSETS = (
    ('Personal Info', {
        'fields': (
            'first_name', 'last_name', 'gender',
            'date_of_birth', 'place_of_birth', 'blood_group',
            'photo', 'family_photo',
        )
    }),
    ('Tree Structure', {
        'fields': ('parent', 'spouses', 'birth_order'),
        'description': (
            'Leave "Parent" empty for root (top-level) members. '
            'Add spouse relationships via the spouses field.'
        )
    }),
    ('Membership', {
        'fields': ('membership_category', 'membership_number'),
        'description': (
            '5 categories: '
            'Life Member (LM) | Life Member Family (LMF) | '
            'Paid Member (PM) | Paid Member Family (PMF) | Member (M). '
            'Membership number is auto-generated if left blank.'
        )
    }),
    ('Contact', {
        'fields': ('mobile_number', 'email', 'education', 'employed'),
        'classes': ('collapse',),
    }),
    ('Sacraments', {
        'fields': (
            'baptism_date', 'baptism_place',
            'communion_date', 'communion_place',
            'marriage_date', 'marriage_place',
        ),
        'classes': ('collapse',),
    }),
    ('Death & Burial', {
        'fields': (
            'date_of_death', 'place_of_death',
            'burial_place', 'cause_of_death',
        ),
        'classes': ('collapse',),
    }),
)


class FamilyMemberAdmin(MPTTModelAdmin):
    list_display = (
        'get_full_name',
        'gender',
        'blood_group',
        'mobile_number',
        'birth_order',
        'parent',
        'get_membership_badge',
        'membership_number',
    )
    list_editable  = ('birth_order',)
    list_filter    = ('membership_category', 'gender', 'blood_group')
    search_fields  = ('first_name', 'last_name', 'mobile_number', 'membership_number')
    ordering       = ('first_name', 'last_name')
    list_per_page  = 50
    fieldsets      = COMMON_FIELDSETS

    @admin.display(description='Name', ordering='first_name')
    def get_full_name(self, obj):
        return f"{obj.first_name.upper()} {obj.last_name}"

    @admin.display(description='Membership')
    def get_membership_badge(self, obj):
        colour, bg = CATEGORY_COLOURS.get(obj.membership_category, ('#374151', '#f3f4f6'))
        label = dict(obj.MEMBERSHIP_CATEGORIES).get(obj.membership_category, obj.membership_category)
        return (
            f'<span style="background:{bg};color:{colour};padding:3px 10px;'
            f'border-radius:50px;font-size:11px;font-weight:700;">{label}</span>'
        )
    get_membership_badge.allow_tags = True

    def get_queryset(self, request):
        return super().get_queryset(request).order_by('first_name', 'last_name')


# ── Register all 8 named families ────────────────────────────────
admin.site.register(AipuFamily,        FamilyMemberAdmin)
admin.site.register(ChakoruFamily,     FamilyMemberAdmin)
admin.site.register(FrancisFamily,     FamilyMemberAdmin)
admin.site.register(KochuvareedFamily, FamilyMemberAdmin)
admin.site.register(LonappanFamily,    FamilyMemberAdmin)
admin.site.register(PorinchuFamily,    FamilyMemberAdmin)
admin.site.register(ThomaFamily,       FamilyMemberAdmin)
admin.site.register(VarunnyFamily,     FamilyMemberAdmin)


# ── Other Family ─────────────────────────────────────────────────
class OtherFamilyAdmin(FamilyMemberAdmin):
    list_display = (
        'get_full_name',
        'family_group',
        'gender',
        'blood_group',
        'mobile_number',
        'birth_order',
        'parent',
        'get_membership_badge',
        'membership_number',
    )
    list_filter   = ('family_group', 'membership_category', 'gender', 'blood_group')
    search_fields = ('first_name', 'last_name', 'family_group', 'mobile_number', 'membership_number')
    list_per_page = 50

    fieldsets = (
        ('Family Group', {
            'fields': ('family_group',),
            'description': (
                'Assign a group name like "Mathew Family". '
                'All members with the same group name appear together on the tree page.'
            )
        }),
    ) + COMMON_FIELDSETS


admin.site.register(OtherFamily, OtherFamilyAdmin)


# ── Force custom model ordering in admin sidebar ──────────────────
MODEL_ORDER = [
    'AipuFamily',
    'ChakoruFamily',
    'FrancisFamily',
    'KochuvareedFamily',
    'LonappanFamily',
    'PorinchuFamily',
    'ThomaFamily',
    'VarunnyFamily',
    'OtherFamily',
]


def get_app_list(self, request, app_label=None):
    app_list = self._original_get_app_list(request, app_label)
    for app in app_list:
        if app.get('app_label') == 'family':
            app['models'].sort(
                key=lambda m: (
                    MODEL_ORDER.index(m['object_name'])
                    if m['object_name'] in MODEL_ORDER else 999
                )
            )
    return app_list


admin.AdminSite._original_get_app_list = admin.AdminSite.get_app_list
admin.AdminSite.get_app_list = get_app_list