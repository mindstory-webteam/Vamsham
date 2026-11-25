from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView, TemplateView

from . import dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),      # REST API for the app + dashboard
    path("dashboard/", dashboard.index),     # Vamsham web dashboard
    re_path(r"^dashboard/(?P<path>.+)$", dashboard.serve),
    # the public website: one page about Vamsham and how it works
    path("", TemplateView.as_view(template_name="vamsham/landing.html"), name="home"),
]

# The old single-family website (Meledath pages: history, team, events, gallery, family trees, …) is gone.
# Its addresses now go to the Vamsham page instead of a 404, so old links and bookmarks still land somewhere.
def _old_site_redirects():
    from app1 import urls as old_app1
    from family import urls as old_family
    out = []
    for p in [*old_app1.urlpatterns, *old_family.urlpatterns]:
        route = str(p.pattern)
        if route:
            out.append(path(route, RedirectView.as_view(url="/", permanent=False)))
    return out


urlpatterns += _old_site_redirects()

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
