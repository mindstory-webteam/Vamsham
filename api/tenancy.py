"""
Many families on one server.

Every family-owned record (branches, events, payments, sign-ups, settings …) has a `family`
column. For each request we work out *which* family it is for, and keep it in a context
variable; the `objects` manager of every family-owned model then only ever returns that
family's rows. So a family admin can't see another family even if a query forgets to filter.

Which family a request is for:
  - a signed-in member or family admin → their own family (FamilyAccess), always;
  - the main admin (superuser) → the family picked in the dashboard (X-Family header),
    or the first family when none is picked;
  - not signed in → the X-Family header if the app sent one (only public endpoints);
  - the old website pages → the first family; the Django admin → every family.

Use `Model.all_objects` (no filter) only where every family is meant, e.g. the main-admin
"All families" page or face search across families.
"""
import contextvars

from django.db import models

_current = contextvars.ContextVar("vamsham_family_id", default=None)
_default = {"id": None}


def current_family_id():
    return _current.get()


def set_current_family(family_id):
    return _current.set(family_id)


def reset_current_family(token):
    _current.reset(token)


def default_family_id():
    """The first family (today's Vamsham data)."""
    if _default["id"] is None:
        from .models import Family
        f = Family.objects.order_by("id").values_list("id", flat=True).first()
        _default["id"] = f
    return _default["id"]


def forget_default():
    _default["id"] = None


def family_for_user(user):
    """The family a signed-in person belongs to (None if not set up)."""
    if not user or not user.is_authenticated:
        return None
    acc = getattr(user, "family_access", None)
    try:
        return acc.family_id if acc else None
    except Exception:  # noqa: BLE001
        return None


def resolve_family_id(user, header_value):
    """Work out the family for a request: see the module docstring."""
    from .models import Family
    if user is not None and user.is_authenticated:
        if user.is_superuser:
            if header_value:
                f = Family.objects.filter(models.Q(slug=header_value) | models.Q(pk=int(header_value) if str(header_value).isdigit() else -1)).values_list("id", flat=True).first()
                if f:
                    return f
            return family_for_user(user) or default_family_id()
        return family_for_user(user) or default_family_id()
    if header_value:
        return Family.objects.filter(slug=header_value, is_active=True).values_list("id", flat=True).first()
    return None


class FamilyScopedQuerySet(models.QuerySet):
    pass


class FamilyScopedManager(models.Manager.from_queryset(FamilyScopedQuerySet)):
    """Only the current family's rows (all rows when no family is set, e.g. the Django admin)."""

    def get_queryset(self):
        qs = super().get_queryset()
        fid = current_family_id()
        return qs.filter(family_id=fid) if fid else qs


def fill_family(sender, instance, **kwargs):
    """New rows belong to the current family (or the first family outside a request)."""
    if getattr(instance, "family_id", None) is None:
        instance.family_id = current_family_id() or default_family_id()


class FamilyMiddleware:
    """Sets the family for website pages and anonymous API calls; DRF auth refines it for signed-in API calls."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/api/"):
            fid = None
            header = request.headers.get("X-Family")
            if header:
                try:
                    fid = resolve_family_id(None, header)
                except Exception:  # noqa: BLE001  (database not ready)
                    fid = None
        elif path.startswith("/admin/"):
            fid = None  # Django admin: main admin sees every family
        else:
            try:
                fid = default_family_id()  # the old website shows the first family
            except Exception:  # noqa: BLE001
                fid = None
        token = set_current_family(fid)
        try:
            return self.get_response(request)
        finally:
            reset_current_family(token)


def family_users(qs=None):
    """Users of the current family (all users when no family is set)."""
    from django.contrib.auth import get_user_model
    qs = qs if qs is not None else get_user_model().objects.all()
    fid = current_family_id()
    return qs.filter(family_access__family_id=fid) if fid else qs


def lock_to_user_family(user):
    """After signing someone in, work with their family for the rest of the request."""
    set_current_family(family_for_user(user) or default_family_id())
