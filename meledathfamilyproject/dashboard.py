"""
Serves the Vamsham web dashboard (built from the React Native / Expo frontend)
at /dashboard/ — so the website, Django admin, REST API and dashboard all run
from this one Django server.

The built files live in  backend/dashboard_web/  (made with:  npm run build:dashboard
in the frontend folder). Any path that is not a real file returns index.html,
so links like /dashboard/admin/members work when opened directly.
"""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

DASHBOARD_DIR = Path(getattr(settings, "DASHBOARD_DIR", settings.BASE_DIR / "dashboard_web")).resolve()

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("image/svg+xml", ".svg")

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>Vamsham dashboard</title>
<body style="font-family:system-ui;padding:40px;color:#0B1442;background:#F2F5FF">
<h1>The dashboard has not been built yet</h1>
<p>In the <b>vamsham-frontend</b> folder run:</p>
<pre style="background:#fff;padding:16px;border-radius:12px">npm install
npm run build:dashboard</pre>
<p>Then refresh this page.</p></body>"""


def index(request):
    return redirect("/dashboard/admin")


def _index_html():
    page = DASHBOARD_DIR / "index.html"
    if not page.exists():
        return HttpResponse(NOT_BUILT, status=503)
    return FileResponse(open(page, "rb"), content_type="text/html")


@never_cache
def serve(request, path=""):
    target = (DASHBOARD_DIR / path).resolve()
    if DASHBOARD_DIR not in target.parents and target != DASHBOARD_DIR:
        raise Http404()
    if target.is_file():
        resp = FileResponse(open(target, "rb"), content_type=mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        if "/_expo/" in f"/{path}" or path.startswith("assets/"):
            resp["Cache-Control"] = "public, max-age=31536000, immutable"  # file names contain a hash
        return resp
    if "." in Path(path).name:  # a missing file, not a page
        raise Http404()
    return _index_html()
