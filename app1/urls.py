from django.urls import path
from . import views

urlpatterns = [

    # ── Home ────────────────────────────────────────────────
    path("", views.Home, name="home"),

    # ── Static Pages ────────────────────────────────────────
    path("family-pillars/", views.FamilyPillars, name="family_pillars"),
    path("history/",        views.History,        name="history"),

    # ── Annual Reports ──────────────────────────────────────
    path("annual-reports/", views.annual_reports, name="annual_reports"),

    # ── Team ────────────────────────────────────────────────
    path("our-team/",             views.team_list,   name="team"),
    path("our-team/<slug:slug>/", views.team_detail, name="team_detail"),

    # ── Events ──────────────────────────────────────────────
    path("events/", views.event_list, name="events"),

    # ── Gallery ─────────────────────────────────────────────
    path("gallery/", views.gallery_list, name="gallery"),

    # ── Premium Events ──────────────────────────────────────
    path("premium-events/",             views.premium_event_view,   name="premium_event_list"),
    path("premium-events/<slug:slug>/", views.premium_event_detail, name="premium_event_detail"),

    # ── Memory ──────────────────────────────────────────────
    path("memory/<int:id>/", views.memory_detail, name="memory_detail"),

    # ── Family Tree ─────────────────────────────────────────
    path("familytree1/", views.FamilyTree1, name="familytree1"),

    # ── Family Photos (single page, no inner detail) ────────
    path("family-photos/", views.family_photos, name="family_photos"),

    # ── Discussion ──────────────────────────────────────────
    path("discussion/",   views.discussion_view, name="discussion"),
    path("post-comment/", views.post_comment,    name="post_comment"),

    # ── Authentication ──────────────────────────────────────
    path("register/", views.register,      name="register"),
    path("login/",    views.custom_login,  name="login"),
    path("logout/",   views.custom_logout, name="logout"),
]