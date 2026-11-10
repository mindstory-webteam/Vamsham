"""
One place that knows where each family branch keeps its people.

Branches are rows in the `FamilyBranch` table, so the committee can create, rename,
hide and delete them from the dashboard (Settings → Family branches, or "+ New branch"
on the Add person page).

Where the people are stored:
  - the 9 original branches keep their own tables (AipuFamily, LonappanFamily, ...),
    so nothing is moved and the old website keeps working;
  - every branch created later stores its people in one shared table, `BranchMember`,
    marked with the branch.

Every member in the API is addressed as  <branch slug> + <id>, for example "lonappan/12".
"""
from django.core.signals import request_started
from django.db.utils import OperationalError, ProgrammingError

# The original branches. Used to fill the FamilyBranch table the first time
# (migration api 0003) and as a fallback while the database is being set up.
BRANCH_DEFS = [
    # slug,          model name,           display name
    ("aipu",        "AipuFamily",        "Sr. Aipu"),
    ("lonappan",    "LonappanFamily",    "Lonappan"),
    ("francis",     "FrancisFamily",     "Fr. Francis"),
    ("varunny",     "VarunnyFamily",     "Varunny"),
    ("thoma",       "ThomaFamily",       "Thoma"),
    ("chakoru",     "ChakoruFamily",     "Chakoru"),
    ("kochuvareed", "KochuvareedFamily", "Kochuvareed"),
    ("porinchu",    "PorinchuFamily",    "Porinchu"),
    ("other",       "OtherFamily",       "Other families"),
]


class _Row:
    __slots__ = ("id", "slug", "name", "table", "hidden", "sort_order", "family_id")

    def __init__(self, id, slug, name, table, hidden, sort_order, family_id=None):  # noqa: A002
        self.id, self.slug, self.name, self.table, self.hidden, self.sort_order = id, slug, name, table, hidden, sort_order
        self.family_id = family_id


_cache = {"rows": None}


def invalidate(**_kwargs):
    _cache["rows"] = None


# Read the table at most once per request.
request_started.connect(invalidate, dispatch_uid="vamsham_branches_cache")


def all_family_rows():
    """Every branch of every family (hidden ones too)."""
    if _cache["rows"] is None:
        try:
            from .models import FamilyBranch
            _cache["rows"] = [
                _Row(b.id, b.slug, b.name, b.table, b.hidden, b.sort_order, b.family_id)
                for b in FamilyBranch.all_objects.order_by("sort_order", "name")
            ]
        except (OperationalError, ProgrammingError):  # table not created yet (first migrate)
            return [_Row(None, s, label, m, False, i) for i, (s, m, label) in enumerate(BRANCH_DEFS)]
    return _cache["rows"]


def rows():
    """This family's branches (hidden ones too), in display order. Many families: see tenancy.py."""
    from .tenancy import current_family_id
    fid = current_family_id()
    all_rows = all_family_rows()
    return [r for r in all_rows if r.family_id == fid] if fid else all_rows


def find_any(slug):
    """A branch of any family (face search across families, main admin)."""
    return next((r for r in all_family_rows() if r.slug == slug), None)


def model_for_any(slug):
    row = find_any(slug)
    return _model_for(row) if row else None


def visible_rows():
    return [r for r in rows() if not r.hidden]


def find(slug):
    return next((r for r in rows() if r.slug == slug), None)


class _Labels(dict):
    """BRANCH_LABELS[slug] → display name, always read from the table."""

    def _data(self):
        return {r.slug: r.name for r in rows()}

    def __getitem__(self, key):
        return self._data()[key]

    def get(self, key, default=None):
        return self._data().get(key, default)

    def __contains__(self, key):
        return key in self._data()

    def __iter__(self):
        return iter(self._data())

    def __len__(self):
        return len(self._data())

    def items(self):
        return self._data().items()


class _Slugs(list):
    """SLUGS: the slugs of the branches that are not hidden."""

    def _data(self):
        return [r.slug for r in visible_rows()]

    def __contains__(self, key):
        return key in self._data()

    def __iter__(self):
        return iter(self._data())

    def __len__(self):
        return len(self._data())


BRANCH_LABELS = _Labels()
SLUGS = _Slugs()

_proxies = {}


def _shared_model(row):
    """A model class for one new branch: the shared BranchMember table, only that branch's rows."""
    key = row.id
    if key in _proxies:
        return _proxies[key]
    from django.db import models
    from .models import BranchMember

    branch_id = row.id

    class _OneBranch(models.Manager):
        def get_queryset(self):
            return super().get_queryset().filter(branch_id=branch_id).order_by("tree_id", "lft")

    def save(self, *args, **kwargs):
        if not self.branch_id:
            self.branch_id = branch_id
        BranchMember.save(self, *args, **kwargs)

    attrs = {
        "__module__": "api.models",
        "objects": _OneBranch(),
        "save": save,
        "Meta": type("Meta", (), {"proxy": True, "app_label": "api",
                                   "verbose_name": f"{row.name} family member"}),
    }
    cls = type(f"BranchMember{branch_id}", (BranchMember,), attrs)
    _proxies[key] = cls
    return cls


def _model_for(row):
    from django.apps import apps
    if row.table:
        return apps.get_model("family", row.table)
    if row.id is None:
        return None
    return _shared_model(row)


def get_model(slug):
    """Return the model class for a branch slug (hidden branches too), or None."""
    row = find(slug)
    return _model_for(row) if row else None


def all_models():
    """[(slug, Model, label), ...] for every branch that is not hidden."""
    return [(r.slug, _model_for(r), r.name) for r in visible_rows()]


def get_member(slug, member_id):
    Model = get_model(slug)
    if Model is None:
        return None
    return Model.objects.filter(pk=member_id).first()
