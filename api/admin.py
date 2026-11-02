from django.contrib import admin

from mptt.admin import MPTTModelAdmin

from .models import (BloodRequest, BranchMember, Broadcast, ChangeRequest, DeviceToken, EventRSVP, FamilyBranch,
                     MemberLink, NewMemberRequest, Notification, Payment, PhoneOTP)


@admin.register(MemberLink)
class MemberLinkAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "member_id", "claim_text", "show_phone", "created_at")
    list_filter = ("branch",)
    search_fields = ("user__username", "claim_text")


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("branch", "member_id", "field", "new_value", "status", "requested_by", "created_at")
    list_filter = ("status", "branch")


@admin.register(NewMemberRequest)
class NewMemberRequestAdmin(admin.ModelAdmin):
    list_display = ("branch", "relative_id", "relation", "status", "requested_by", "created_at")
    list_filter = ("status", "branch")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "payer_name", "purpose", "amount", "method", "paid_on")
    list_filter = ("purpose", "method")
    search_fields = ("receipt_no", "payer_name", "reference")


@admin.register(BloodRequest)
class BloodRequestAdmin(admin.ModelAdmin):
    list_display = ("blood_group", "hospital", "units", "is_open", "created_at")
    list_filter = ("is_open", "blood_group")


admin.site.register(EventRSVP)
admin.site.register(Notification)
admin.site.register(Broadcast)
admin.site.register(DeviceToken)


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ("phone", "created_at", "expires_at", "attempts", "used")
    readonly_fields = ("phone", "code_hash", "created_at", "expires_at", "attempts", "used")


from .models import AssociationSettings  # noqa: E402
admin.site.register(AssociationSettings)


@admin.register(FamilyBranch)
class FamilyBranchAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order", "hidden", "table")
    list_editable = ("sort_order", "hidden")
    readonly_fields = ("table",)


@admin.register(BranchMember)
class BranchMemberAdmin(MPTTModelAdmin):
    list_display = ("first_name", "last_name", "branch", "membership_category", "membership_number")
    list_filter = ("branch", "membership_category")
    search_fields = ("first_name", "last_name", "membership_number")
