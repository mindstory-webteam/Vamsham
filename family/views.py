"""
family/views.py — Vamsham Family Association
All family tree views + global cross-branch search API
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q

from .models import (
    AipuFamily,
    LonappanFamily,
    FrancisFamily,
    VarunnyFamily,
    ThomaFamily,
    ChakoruFamily,
    KochuvareedFamily,
    PorinchuFamily,
    OtherFamily,
)


# ════════════════════════════════════════════════════════════════
# FAMILY TREE VIEWS
# ════════════════════════════════════════════════════════════════

def generic_family_tree(request, FamilyModel, template_name, member_id=None):
    """Shared logic for all 8 family tree views."""
    if member_id is None:
        root_members = FamilyModel.objects.filter(
            parent__isnull=True
        ).prefetch_related('spouses', 'children')
        if root_members.exists():
            member = root_members.first()
        else:
            member = FamilyModel.objects.first()
            if not member:
                return render(request, template_name, {
                    'member': None,
                    'family_name': FamilyModel._meta.verbose_name_plural
                })
    else:
        member = get_object_or_404(
            FamilyModel.objects.prefetch_related('spouses', 'children'),
            pk=member_id
        )
    return render(request, template_name, {
        'member': member,
        'family_name': FamilyModel._meta.verbose_name_plural,
    })


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


# ════════════════════════════════════════════════════════════════
# OTHER FAMILY TREE VIEW
# ════════════════════════════════════════════════════════════════

@login_required(login_url='login')
def other_members_tree(request):
    family_groups = (
        OtherFamily.objects
        .values_list('family_group', flat=True)
        .distinct()
        .order_by('family_group')
    )

    families = []
    for group in family_groups:
        all_members_in_group = list(
            OtherFamily.objects
            .filter(family_group=group)
            .prefetch_related('spouses', 'children')
        )
        if not all_members_in_group:
            continue

        rendered_as_spouse_ids = set()
        for member in all_members_in_group:
            for sp in member.spouses.all():
                if sp.id != member.id:
                    if member.id < sp.id:
                        rendered_as_spouse_ids.add(sp.id)
                    else:
                        rendered_as_spouse_ids.add(member.id)

        roots = [
            m for m in all_members_in_group
            if m.parent_id is None and m.id not in rendered_as_spouse_ids
        ]
        roots.sort(key=lambda m: (m.birth_order, m.first_name))

        if not roots:
            roots = [m for m in all_members_in_group if m.parent_id is None]
            root_ids = {m.id for m in roots}
            exclude = set()
            for m in roots:
                for sp in m.spouses.all():
                    if sp.id in root_ids and sp.id != m.id:
                        exclude.add(max(m.id, sp.id))
            roots = [m for m in roots if m.id not in exclude]
            roots.sort(key=lambda m: (m.birth_order, m.first_name))

        if roots:
            families.append({
                'group': group,
                'roots': roots,
                'slug': group.lower().replace(' ', '-'),
                'member_count': len(all_members_in_group),
            })

    return render(request, 'other_members.html', {
        'families': families,
        'family_name': 'Other Family Members',
    })


# ════════════════════════════════════════════════════════════════
# GLOBAL CROSS-BRANCH SEARCH API
# URL  : /global-search/?q=<query>
# Auth : login required
# Returns: JSON  { results: [...], total: N, query: "..." }
# ════════════════════════════════════════════════════════════════

@login_required(login_url='login')
def global_family_search(request):
    """
    Search any member by name, blood group, mobile, email,
    place of birth, education, employment, membership number,
    baptism place, marriage place, or place of death —
    across all family branches.
    """
    try:
        query = request.GET.get('q', '').strip()

        # Require at least 2 characters
        if len(query) < 2:
            return JsonResponse({
                'results': [], 'total': 0, 'query': query,
                'error': None
            })

        BRANCHES = [
            (LonappanFamily,    'Lonappan Family',    '/lonappan/'),
            (AipuFamily,        'Sr. Aipu Family',    '/aipu/'),
            (FrancisFamily,     'Fr. Francis Family', '/francis/'),
            (VarunnyFamily,     'Varunny Family',     '/varunny/'),
            (ThomaFamily,       'Thoma Family',       '/thoma/'),
            (ChakoruFamily,     'Chakoru Family',     '/chakoru/'),
            (KochuvareedFamily, 'Kochuvareed Family', '/kochuvareed/'),
            (PorinchuFamily,    'Porinchu Family',    '/porinchu/'),
            (OtherFamily,       'Other Family',       '/other-members/'),
        ]

        cat_labels = {
            'LM':  'Life Member',
            'LMF': 'Life Member Family',
            'PM':  'Paid Member',
            'PMF': 'Paid Member Family',
            'M':   'Member',
        }

        search_filter = (
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(mobile_number__icontains=query) |
            Q(email__icontains=query) |
            Q(blood_group__icontains=query) |
            Q(place_of_birth__icontains=query) |
            Q(education__icontains=query) |
            Q(employed__icontains=query) |
            Q(membership_number__icontains=query) |
            Q(baptism_place__icontains=query) |
            Q(marriage_place__icontains=query) |
            Q(place_of_death__icontains=query)
        )

        results = []

        for Model, branch_label, branch_url in BRANCHES:
            try:
                qs = Model.objects.filter(search_filter)[:100]
                for m in qs:
                    try:
                        photo_url = m.photo.url if m.photo else ''
                    except Exception:
                        photo_url = ''

                    results.append({
                        'id':                 m.id,
                        'name':               f"{m.first_name} {m.last_name}".strip(),
                        'first_name':         m.first_name or '',
                        'last_name':          m.last_name or '',
                        'gender':             m.get_gender_display(),
                        'gender_code':        m.gender or '',
                        'date_of_birth':      str(m.date_of_birth) if m.date_of_birth else '',
                        'place_of_birth':     m.place_of_birth or '',
                        'blood_group':        m.blood_group or '',
                        'mobile':             m.mobile_number or '',
                        'email':              m.email or '',
                        'education':          m.education or '',
                        'employed':           m.employed or '',
                        'membership_category':cat_labels.get(m.membership_category, 'Non Member'),
                        'membership_number':  m.membership_number or '',
                        'baptism_date':       str(m.baptism_date) if m.baptism_date else '',
                        'baptism_place':      m.baptism_place or '',
                        'communion_date':     str(m.communion_date) if m.communion_date else '',
                        'marriage_date':      str(m.marriage_date) if m.marriage_date else '',
                        'marriage_place':     m.marriage_place or '',
                        'date_of_death':      str(m.date_of_death) if m.date_of_death else '',
                        'place_of_death':     m.place_of_death or '',
                        'burial_place':       m.burial_place or '',
                        'cause_of_death':     m.cause_of_death or '',
                        'photo':              photo_url,
                        'branch':             branch_label,
                        'branch_url':         branch_url,
                    })
            except Exception as branch_err:
                # If one branch fails, continue with others
                continue

        results.sort(key=lambda x: x['name'].lower())

        return JsonResponse({
            'results': results,
            'total':   len(results),
            'query':   query,
            'error':   None,
        })

    except Exception as e:
        return JsonResponse({
            'results': [],
            'total':   0,
            'query':   request.GET.get('q', ''),
            'error':   str(e),
        }, status=500)