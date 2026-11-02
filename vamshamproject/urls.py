from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from . import dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),      # REST API for the app + dashboard
    path("dashboard/", dashboard.index),     # Vamsham web dashboard
    re_path(r"^dashboard/(?P<path>.+)$", dashboard.serve),
    path("", include("app1.urls")),
    path("", include("family.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
