"""
Turning family-member records into API data, plus tree and relationship logic.
"""
from datetime import date

from django.db.models import Q

from .branches import BRANCH_LABELS, all_models, get_model
from .otp import mask_phone

CATEGORY_LABELS = {
    "LM": "Life member",
    "LMF": "Life member family",
    "PM": "Paid member",
    "PMF": "Paid member family",
    "M": "Member",
    "NM": "Not a member",
}

# Fields that may be edited (by admins directly, or by members via change requests)
EDITABLE_FIELDS = [
    "first_name", "last_name", "gender",
    "date_of_birth", "place_of_birth",
    "baptism_date", "baptism_place",
    "communion_date", "communion_place",
    "marriage_date", "marriage_place",
    "date_of_death", "place_of_death", "burial_place", "cause_of_death",
    "mobile_number", "email", "education", "employed", "blood_group",
    "membership_category", "birth_order",
]
# Fields a member may ask to change on their own profile
SELF_EDITABLE_FIELDS = [
    "date_of_birth", "place_of_birth", "baptism_date", "baptism_place",
    "communion_date", "communion_place", "marriage_date", "marriage_place",
    "mobile_number", "email", "education", "employed", "blood_group",
]
COMPLETENESS_FIELDS = ["date_of_birth", "place_of_birth", "baptism_date", "blood_group", "mobile_number", "photo"]


def ref(branch, member):
    return f"{branch}:{member.pk}"


def parse_ref(value):
    """'lonappan:12' -> ('lonappan', 12) or (None, None)."""
    try:
        branch, pk = str(value).split(":", 1)
        return branch, int(pk)
    except (ValueError, AttributeError):
        return None, None


def _d(value):
    return value.isoformat() if value else None


def initials(m):
    return ((m.first_name or "?")[:1] + (m.last_name or "")[:1]).upper()


def full_name(m):
    return f"{m.first_name} {m.last_name}".strip()


def photo_url(m, request=None):
    try:
        if m.photo:
            return request.build_absolute_uri(m.photo.url) if request else m.photo.url
    except ValueError:
        pass
    return None


def completeness(m):
    filled = sum(1 for f in COMPLETENESS_FIELDS if getattr(m, f, None))
    return round(filled * 100 / len(COMPLETENESS_FIELDS))


def can_see_phone(viewer, m, branch):
    from .models import MemberLink
    from .permissions import is_approved
    if viewer is None or not is_approved(viewer):
        return False
    if viewer.is_staff:
        return True
    link = MemberLink.objects.filter(branch=branch, member_id=m.pk).first()
    return link.show_phone if link else True


def summary(m, branch, request=None):
    """Short card used in lists, search results and trees."""
    return {
        "ref": ref(branch, m),
        "id": m.pk,
        "branch": branch,
        "branch_label": BRANCH_LABELS.get(branch, branch),
        "name": full_name(m),
        "first_name": m.first_name,
        "last_name": m.last_name,
        "initials": initials(m),
        "gender": m.gender,
        "generation": (m.level or 0) + 1,
        "birth_year": m.date_of_birth.year if m.date_of_birth else None,
        "death_year": m.date_of_death.year if m.date_of_death else None,
        "is_living": m.date_of_death is None,
        "place": m.place_of_birth or "",
        "blood_group": m.blood_group or "",
        "membership_category": m.membership_category,
        "membership_label": CATEGORY_LABELS.get(m.membership_category, m.membership_category or ""),
        "membership_number": m.membership_number or "",
        "photo": photo_url(m, request),
    }


def detail(m, branch, request=None):
    viewer = getattr(request, "user", None)
    data = summary(m, branch, request)
    show_phone = can_see_phone(viewer, m, branch)
    data.update({
        "date_of_birth": _d(m.date_of_birth), "place_of_birth": m.place_of_birth or "",
        "baptism_date": _d(m.baptism_date), "baptism_place": m.baptism_place or "",
        "communion_date": _d(m.communion_date), "communion_place": m.communion_place or "",
        "marriage_date": _d(m.marriage_date), "marriage_place": m.marriage_place or "",
        "date_of_death": _d(m.date_of_death), "place_of_death": m.place_of_death or "",
        "burial_place": m.burial_place or "",
        "education": m.education or "", "employed": m.employed or "",
        "email": (m.email or "") if show_phone else "",
        "mobile": (m.mobile_number or "") if show_phone else "",
        "mobile_masked": mask_phone(m.mobile_number) if m.mobile_number else "",
        "birth_order": m.birth_order,
        "completeness": completeness(m),
        "parent": summary(m.parent, branch, request) if m.parent_id else None,
        "spouses": [summary(s, branch, request) for s in m.spouses.all()],
        "children": [summary(c, branch, request) for c in m.get_children()],
        "siblings": [summary(s, branch, request) for s in m.get_siblings()] if m.parent_id else [],
    })
    return data


# ── Search ───────────────────────────────────────────────────────────────────

def search(query="", branch=None, blood=None, category=None, living=None, request=None):
    results = []
    for slug, Model, _label in all_models():
        if branch and branch != slug:
            continue
        qs = Model.objects.all()
        if query:
            q = (Q(first_name__icontains=query) | Q(last_name__icontains=query)
                 | Q(membership_number__iexact=query) | Q(place_of_birth__icontains=query)
                 | Q(employed__icontains=query) | Q(education__icontains=query))
            parts = query.split()
            if len(parts) >= 2:
                q |= Q(first_name__icontains=parts[0], last_name__icontains=parts[-1])
            qs = qs.filter(q)
        if blood:
            qs = qs.filter(blood_group__iexact=blood)
        if category:
            cats = ["LM", "LMF"] if category == "life" else [category]
            qs = qs.filter(membership_category__in=cats)
        if living is True:
            qs = qs.filter(date_of_death__isnull=True)
        results.extend(summary(m, slug, request) for m in qs)
    results.sort(key=lambda r: r["name"].lower())
    return results


# ── Tree ─────────────────────────────────────────────────────────────────────

def _node(m, branch, depth, request):
    node = summary(m, branch, request)
    spouses = list(m.spouses.all())
    node["spouses"] = [summary(s, branch, request) for s in spouses]
    kids = list(m.get_children())
    # Children recorded under a married-in spouse (e.g. a second wife) belong to this couple too
    for s in spouses:
        if s.parent_id is None and s.pk != m.pk:
            kids.extend(c for c in s.get_children() if c not in kids)
    kids.sort(key=lambda k: (k.birth_order, k.first_name))
    node["children_count"] = len(kids)
    node["children"] = [_node(c, branch, depth - 1, request) for c in kids] if depth > 1 else []
    return node


def tree(branch, root_id=None, depth=4, request=None):
    Model = get_model(branch)
    if root_id:
        roots = list(Model.objects.filter(pk=root_id))
    else:
        roots = list(Model.objects.filter(parent__isnull=True).prefetch_related("spouses"))
        # A married-in spouse is stored as a root with no parent: show them next
        # to their partner instead of as a separate tree.
        root_ids = {r.pk for r in roots}
        hide = set()
        for r in roots:
            for s in r.spouses.all():
                if s.pk in root_ids and s.pk != r.pk and r.pk not in hide:
                    hide.add(s.pk)
                elif s.parent_id is not None:  # partner is someone's child in the tree
                    hide.add(r.pk)
        roots = [r for r in roots if r.pk not in hide] or roots
        roots.sort(key=lambda r: (r.birth_order, r.first_name))
    return [_node(r, branch, depth, request) for r in roots]


# ── Relationship ("How are we related?") ─────────────────────────────────────

def _chain(m):
    """[m, parent, grandparent, ...]"""
    out = []
    while m is not None:
        out.append(m)
        m = m.parent if m.parent_id else None
    return out


def _blood_proxy(m):
    """For someone who married in (no parent), use their partner's place in the tree."""
    if m.parent_id is None:
        for s in m.spouses.all():
            if s.parent_id is not None:
                return s, True
    return m, False


def _word(male, female, other, gender):
    return male if gender == "M" else female if gender == "F" else other


def _ordinal(n):
    return {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}.get(n, f"{n}th")


def describe(da, db, g):
    """Name of B as seen from A, where da/db are steps up to the common ancestor."""
    if da == 0 and db == 0:
        return "Same person"
    if da == 0:
        if db == 1:
            return _word("Son", "Daughter", "Child", g)
        base = _word("grandson", "granddaughter", "grandchild", g)
        return ("Great-" * (db - 2)) + (base.capitalize() if db == 2 else base)
    if db == 0:
        if da == 1:
            return _word("Father", "Mother", "Parent", g)
        base = _word("grandfather", "grandmother", "grandparent", g)
        return ("Great-" * (da - 2)) + (base.capitalize() if da == 2 else base)
    if da == 1 and db == 1:
        return _word("Brother", "Sister", "Sibling", g)
    if da == 1:
        base = _word("nephew", "niece", "nephew / niece", g)
        return ("Grand-" * (db - 2)) + (base.capitalize() if db == 2 else base)
    if db == 1:
        base = _word("uncle", "aunt", "uncle / aunt", g)
        return ("Grand-" * (da - 2)) + (base.capitalize() if da == 2 else base)
    degree = min(da, db) - 1
    removed = abs(da - db)
    text = f"{_ordinal(degree)} cousin"
    if removed == 1:
        text += " once removed"
    elif removed == 2:
        text += " twice removed"
    elif removed > 2:
        text += f" {removed} times removed"
    return text


def relationship(branch_a, a, branch_b, b, request=None):
    if branch_a != branch_b:
        return {
            "found": False,
            "message": "These two people are in different family branches. "
                       "The branches are not linked to a common ancestor in the records yet.",
        }
    pa, a_inlaw = _blood_proxy(a)
    pb, b_inlaw = _blood_proxy(b)
    if a.pk == b.pk:
        return {"found": True, "relation": "Same person", "path_a": [], "path_b": [], "ancestor": None}
    if pa.pk == pb.pk:  # married to each other
        return {"found": True, "relation": _word("Husband", "Wife", "Spouse", b.gender),
                "path_a": [], "path_b": [], "ancestor": summary(pa, branch_a, request)}
    ca, cb = _chain(pa), _chain(pb)
    ids_b = {m.pk: i for i, m in enumerate(cb)}
    for da, m in enumerate(ca):
        if m.pk in ids_b:
            db = ids_b[m.pk]
            rel = describe(da, db, b.gender)
            if a_inlaw or b_inlaw:
                rel = f"{rel} (by marriage)"
            return {
                "found": True,
                "relation": rel,
                "ancestor": summary(m, branch_a, request),
                # people from the common ancestor down to each person (not including the ancestor)
                "path_a": [summary(x, branch_a, request) for x in reversed(ca[:da])],
                "path_b": [summary(x, branch_b, request) for x in reversed(cb[:db])],
            }
    return {"found": False, "message": "No common ancestor is recorded for these two people yet."}


# ── Today: birthdays, anniversaries, remembrance ─────────────────────────────

def today_items(day=None, request=None):
    day = day or date.today()
    birthdays, anniversaries, remembrance = [], [], []
    seen_couples = set()
    for slug, Model, _label in all_models():
        for m in Model.objects.filter(date_of_birth__month=day.month, date_of_birth__day=day.day,
                                      date_of_death__isnull=True):
            item = summary(m, slug, request)
            item["turning"] = day.year - m.date_of_birth.year
            birthdays.append(item)
        for m in Model.objects.filter(marriage_date__month=day.month, marriage_date__day=day.day,
                                      date_of_death__isnull=True).prefetch_related("spouses"):
            partner = next(iter(m.spouses.all()), None)
            key = tuple(sorted([m.pk, partner.pk if partner else 0])) + (slug,)
            if key in seen_couples:
                continue
            seen_couples.add(key)
            anniversaries.append({
                "person": summary(m, slug, request),
                "partner": summary(partner, slug, request) if partner else None,
                "years": day.year - m.marriage_date.year,
            })
        for m in Model.objects.filter(date_of_death__month=day.month, date_of_death__day=day.day):
            item = summary(m, slug, request)
            item["years"] = day.year - m.date_of_death.year
            remembrance.append(item)
    return {"date": day.isoformat(), "birthdays": birthdays,
            "anniversaries": anniversaries, "remembrance": remembrance}
