from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import admin as a
from .views import auth, community as c, family as f, settings_views as st
from .views import branch_views as br
from .views import face as fc
from .views import families as fm

urlpatterns = [
    # ── Sign in ──────────────────────────────────────────────
    path("auth/otp/request", auth.OTPRequestView.as_view()),
    path("auth/otp/verify", auth.OTPVerifyView.as_view()),
    path("auth/login", auth.PasswordLoginView.as_view()),
    path("auth/refresh", TokenRefreshView.as_view()),
    path("families", fm.PublicFamiliesView.as_view()),
    path("families/mine", fm.MyFamiliesView.as_view()),
    path("families/<slug:slug>", fm.PublicFamilyView.as_view()),
    path("super/families", fm.FamiliesView.as_view()),
    path("super/families/<int:pk>", fm.FamilyDetailView.as_view()),
    path("super/families/<int:pk>/admins", fm.FamilyAdminsView.as_view()),
    path("super/families/<int:pk>/admins/<int:uid>", fm.FamilyAdminDetailView.as_view()),
    path("super/families/<int:pk>/admins/<int:uid>/reset", fm.FamilyAdminDetailView.as_view()),
    path("auth/face", fc.FaceStatusView.as_view()),
    path("auth/face/enroll", fc.FaceEnrollView.as_view()),
    path("auth/face/login", fc.FaceLoginView.as_view()),
    path("auth/face/identify", fc.FaceIdentifyView.as_view()),
    path("auth/face/confirm", fc.FaceConfirmView.as_view()),
    path("admin/members/<slug:branch>/<int:pk>/face", fc.AdminMemberFaceView.as_view()),

    # ── Me ───────────────────────────────────────────────────
    path("me", auth.MeView.as_view()),
    path("me/claim", auth.ClaimView.as_view()),
    path("me/devices", auth.DeviceTokenView.as_view()),

    # ── Family ───────────────────────────────────────────────
    path("branches", f.BranchesView.as_view()),
    path("branch-names", br.BranchNamesView.as_view()),
    path("members", f.MemberSearchView.as_view()),
    path("members/<slug:branch>/<int:pk>", f.MemberDetailView.as_view()),
    path("members/<slug:branch>/<int:pk>/wish", f.WishView.as_view()),
    path("tree/<slug:branch>", f.TreeView.as_view()),
    path("relationship", f.RelationshipView.as_view()),
    path("today", f.TodayView.as_view()),
    path("requests/change", f.ChangeRequestView.as_view()),
    path("requests/new-member", f.NewMemberRequestView.as_view()),

    # ── Community ────────────────────────────────────────────
    path("events", c.EventListView.as_view()),
    path("events/<int:pk>", c.EventDetailView.as_view()),
    path("events/<int:pk>/rsvp", c.RSVPView.as_view()),
    path("albums", c.AlbumListView.as_view()),
    path("albums/<str:album_id>", c.AlbumDetailView.as_view()),
    path("memories", c.MemoryListView.as_view()),
    path("memories/<int:pk>", c.MemoryDetailView.as_view()),
    path("reports", c.ReportListView.as_view()),
    path("blood-requests", c.BloodRequestListView.as_view()),
    path("blood-requests/<int:pk>/respond", c.BloodRespondView.as_view()),
    path("blood-donors", c.DonorListView.as_view()),
    path("notifications", c.NotificationListView.as_view()),
    path("settings", st.PublicSettingsView.as_view()),

    # ── Admin (committee only) ───────────────────────────────
    path("admin/dashboard", a.DashboardView.as_view()),
    path("admin/approvals", a.ApprovalListView.as_view()),
    path("admin/approvals/<str:kind>/<int:pk>/<str:decision>", a.ApprovalDecisionView.as_view()),
    path("admin/members", a.AdminMemberListView.as_view()),
    path("admin/members/export", a.AdminMemberExportView.as_view()),
    path("admin/members/<slug:branch>", a.AdminMemberListView.as_view()),
    path("admin/members/<slug:branch>/<int:pk>", a.AdminMemberDetailView.as_view()),
    path("admin/events", a.AdminEventListView.as_view()),
    path("admin/events/<int:pk>", a.AdminEventDetailView.as_view()),
    path("admin/broadcast", a.BroadcastView.as_view()),
    path("admin/payments", a.PaymentListView.as_view()),
    path("admin/payments/export", a.PaymentExportView.as_view()),
    path("admin/payments/unpaid", a.UnpaidView.as_view()),
    path("admin/settings", st.AdminSettingsView.as_view()),
    path("admin/branches", br.AdminBranchListView.as_view()),
    path("admin/branches/<slug:slug>", br.AdminBranchDetailView.as_view()),
    path("admin/committee", st.CommitteeView.as_view()),
    path("admin/photos", st.AdminPhotosView.as_view()),
    path("admin/photos/<str:kind>/<int:pk>", st.AdminPhotoDeleteView.as_view()),
]
