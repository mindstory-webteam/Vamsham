"""Family branches: the committee can create, rename, hide, reorder and delete them."""
from django.db.models import Max
from django.utils.text import slugify
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import branches as B
from ..models import ChangeRequest, FamilyBranch, MemberLink, NewMemberRequest, Payment
from ..permissions import IsStaff


def _count(row):
    Model = B._model_for(row)
    return Model.objects.count() if Model is not None else 0


def branch_payload(b):
    row = B.find(b.slug)
    people = _count(row) if row else 0
    return {
        "id": b.id, "slug": b.slug, "name": b.name, "label": b.name, "hidden": b.hidden,
        "sort_order": b.sort_order, "original": bool(b.table), "members": people,
        "can_delete": people == 0,
    }


def _unique_slug(name):
    base = (slugify(name).replace("-", "")[:16] or "branch")
    slug, n = base, 2
    while FamilyBranch.all_objects.filter(slug=slug).exists():  # slugs are unique across all families
        slug = f"{base[:16]}{n}"
        n += 1
    return slug


class BranchNamesView(APIView):
    """GET /branch-names — every visible branch, for anyone signed in (also people still waiting for approval)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([{"slug": r.slug, "label": r.name} for r in B.visible_rows()])


class AdminBranchListView(APIView):
    """GET all branches (hidden too) · POST {name} creates a new branch."""
    permission_classes = [IsStaff]

    def get(self, request):
        return Response([branch_payload(b) for b in FamilyBranch.objects.all()])

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"detail": "Give the branch a name."}, status=400)
        if len(name) > 100:
            return Response({"detail": "The name is too long (100 letters at most)."}, status=400)
        if FamilyBranch.objects.filter(name__iexact=name).exists():
            return Response({"detail": f"There is already a branch called “{name}”."}, status=400)
        last = FamilyBranch.objects.aggregate(m=Max("sort_order"))["m"] or 0
        b = FamilyBranch.objects.create(name=name, slug=_unique_slug(name), sort_order=last + 10)
        return Response(branch_payload(b), status=201)


class AdminBranchDetailView(APIView):
    """PATCH {name?, hidden?, sort_order?} · DELETE (only when nobody is in the branch)."""
    permission_classes = [IsStaff]

    def _get(self, slug):
        return FamilyBranch.objects.filter(slug=slug).first()

    def patch(self, request, slug):
        b = self._get(slug)
        if not b:
            return Response({"detail": "Branch not found."}, status=404)
        if "name" in request.data:
            name = str(request.data["name"]).strip()
            if not name:
                return Response({"detail": "Give the branch a name."}, status=400)
            if FamilyBranch.objects.filter(name__iexact=name).exclude(pk=b.pk).exists():
                return Response({"detail": f"There is already a branch called “{name}”."}, status=400)
            b.name = name[:100]
        if "hidden" in request.data:
            b.hidden = bool(request.data["hidden"]) and str(request.data["hidden"]).lower() not in ("0", "false")
        if "sort_order" in request.data:
            try:
                b.sort_order = max(0, int(request.data["sort_order"]))
            except (TypeError, ValueError):
                return Response({"detail": "sort_order must be a number."}, status=400)
        b.save()
        return Response(branch_payload(b))

    def delete(self, request, slug):
        b = self._get(slug)
        if not b:
            return Response({"detail": "Branch not found."}, status=404)
        row = B.find(slug)
        people = _count(row) if row else 0
        if people:
            return Response({"detail": f"{people} people are in this branch. Move or delete them first, or hide the branch instead."},
                            status=400)
        # forget links and requests that pointed at the empty branch
        MemberLink.objects.filter(branch=slug).update(branch="")
        Payment.objects.filter(branch=slug).update(branch="", member_id=None)
        ChangeRequest.objects.filter(branch=slug, status="pending").update(status="declined", note="Branch deleted")
        NewMemberRequest.objects.filter(branch=slug, status="pending").update(status="declined", note="Branch deleted")
        b.delete()
        return Response(status=204)
