"""
╔══════════════════════════════════════════════════════════════════╗
║  UPDATED views.py — Other Members Tree                          ║
║  Supports multiple root members per family_group                ║
║  Each root displays with its spouses & children                 ║
╚══════════════════════════════════════════════════════════════════╝

ADD / REPLACE the other_members_tree view in your views.py
"""

# ─────────────────────────────────────────────────────────────────
# views.py — UPDATED VIEW
# ─────────────────────────────────────────────────────────────────

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import (
    AipuFamily,
    LonappanFamily,
    FrancisFamily,
    VarunnyFamily,
    ThomaFamily,
    ChakoruFamily,
    KochuvareedFamily,
    PorinchuFamily,
    OtherFamily,  # ← New model
)


# ═══════════════════════════════════════════════════════════════
# EXISTING VIEWS (keep as-is)
# ═══════════════════════════════════════════════════════════════

@login_required(login_url='login')
def family_tree(request, member_id=None):
    return generic_family_tree(request, AipuFamily, 'family1.html', member_id)

@login_required(login_url='login')
def lonappan_family_tree(request, member_id=None):
    return generic_family_tree(request, LonappanFamily, 'family2.html', member_id)

@login_required(login_url='login')
def francis_family_tree(request, member_id=None):
    return generic_family_tree(request, FrancisFamily, 'family3.html', member_id)

@login_required(login_url='login')
def varunny_family_tree(request, member_id=None):
    return generic_family_tree(request, VarunnyFamily, 'family4.html', member_id)

@login_required(login_url='login')
def thoma_family_tree(request, member_id=None):
    return generic_family_tree(request, ThomaFamily, 'family5.html', member_id)

@login_required(login_url='login')
def chakoru_family_tree(request, member_id=None):
    return generic_family_tree(request, ChakoruFamily, 'family6.html', member_id)

@login_required(login_url='login')
def kochuvareed_family_tree(request, member_id=None):
    return generic_family_tree(request, KochuvareedFamily, 'family7.html', member_id)

@login_required(login_url='login')
def porinchu_family_tree(request, member_id=None):
    return generic_family_tree(request, PorinchuFamily, 'family8.html', member_id)


def generic_family_tree(request, FamilyModel, template_name, member_id=None):
    if member_id is None:
        root_members = FamilyModel.objects.filter(parent__isnull=True).prefetch_related('spouses', 'children')
        if root_members.exists():
            member = root_members.first()
        else:
            member = FamilyModel.objects.first()
            if not member:
                return render(request, template_name, {'member': None, 'family_name': FamilyModel._meta.verbose_name_plural})
    else:
        member = get_object_or_404(FamilyModel.objects.prefetch_related('spouses', 'children'), pk=member_id)
    
    context = {
        'member': member,
        'family_name': FamilyModel._meta.verbose_name_plural,
    }
    return render(request, template_name, context)


# ═══════════════════════════════════════════════════════════════
# NEW: Other Members Tree View
# ─────────────────────────────────────────────────────────────
# Displays ALL family groups on one page.
# Each family_group can have MULTIPLE root members.
# Each root member shows their spouses + full child tree.
# ═══════════════════════════════════════════════════════════════

@login_required(login_url='login')
def other_members_tree(request):
    """
    Single-page view that renders multiple family trees.
    
    Groups members by `family_group` field.
    Each group can have multiple root members (parent=NULL).
    
    DEDUPLICATION LOGIC:
    The template (other_memb.html) renders spouses automatically
    via `member.spouses.all` with condition `member.id < spouse.id`.
    
    So any member who is ANYONE's spouse (and has the higher ID)
    will already appear as a spouse card. We must NOT also show
    them as a root member, otherwise they appear twice.
    
    We collect ALL spouse IDs across the entire family group
    (not just among roots) and exclude them from the roots list.
    """

    family_groups = (
        OtherFamily.objects
        .values_list('family_group', flat=True)
        .distinct()
        .order_by('family_group')
    )

    families = []
    for group in family_groups:
        # ── Step 1: Get all members in this group ──
        all_members_in_group = list(
            OtherFamily.objects
            .filter(family_group=group)
            .prefetch_related('spouses', 'children')
        )
        
        if not all_members_in_group:
            continue

        # ── Step 2: Build a set of ALL spouse IDs that will be
        #    rendered by the template as a spouse card ──
        #
        # Template condition: {% if member.id < spouse.id %}
        # This means: for every member→spouse pair where
        # member.id < spouse.id, the SPOUSE will be rendered
        # as a spouse card. So we must exclude that spouse
        # from appearing as a root.
        
        rendered_as_spouse_ids = set()
        for member in all_members_in_group:
            for sp in member.spouses.all():
                if sp.id != member.id:
                    if member.id < sp.id:
                        # Template will render sp as a spouse card next to member
                        rendered_as_spouse_ids.add(sp.id)
                    else:
                        # Template will render member as a spouse card next to sp
                        rendered_as_spouse_ids.add(member.id)

        # ── Step 3: Get root members (parent=NULL) and exclude
        #    anyone who will already be shown as a spouse card ──
        
        roots = [
            m for m in all_members_in_group
            if m.parent_id is None and m.id not in rendered_as_spouse_ids
        ]
        roots.sort(key=lambda m: (m.birth_order, m.first_name))

        # ── Step 4: Fallback if no roots found ──
        if not roots:
            # All root members got excluded as spouses.
            # This can happen if every root is someone's spouse.
            # In that case, keep the ones with the lower ID.
            roots = [
                m for m in all_members_in_group
                if m.parent_id is None
            ]
            # Remove only those who are spouse of ANOTHER root
            root_ids = {m.id for m in roots}
            exclude = set()
            for m in roots:
                for sp in m.spouses.all():
                    if sp.id in root_ids and sp.id != m.id:
                        exclude.add(max(m.id, sp.id))
            roots = [m for m in roots if m.id not in exclude]
            roots.sort(key=lambda m: (m.birth_order, m.first_name))

        if roots:
            member_count = len(all_members_in_group)
            families.append({
                'group': group,
                'roots': roots,
                'slug': group.lower().replace(' ', '-'),
                'member_count': member_count,
            })

    return render(request, 'other_members.html', {
        'families': families,
        'family_name': 'Other Family Members',
    })