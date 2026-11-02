# from django.shortcuts import render, get_object_or_404
# from .models import (
#     AipuFamily,
#     LonappanFamily,
#     FrancisFamily,
#     VarunnyFamily,
#     ThomaFamily,
#     ChakoruFamily,
#     KochuvareedFamily,
# )

# def family_tree(request, member_id=None):
#     return generic_family_tree(request, AipuFamily, 'family1.html', member_id)

# def lonappan_family_tree(request, member_id=None):
#     return generic_family_tree(request, LonappanFamily, 'family2.html', member_id)

# def francis_family_tree(request, member_id=None):
#     return generic_family_tree(request, FrancisFamily, 'family3.html', member_id)

# def varunny_family_tree(request, member_id=None):
#     return generic_family_tree(request, VarunnyFamily, 'family4.html', member_id)

# def thoma_family_tree(request, member_id=None):
#     return generic_family_tree(request, ThomaFamily, 'family5.html', member_id)

# def chakoru_family_tree(request, member_id=None):
#     return generic_family_tree(request, ChakoruFamily, 'family6.html', member_id)

# def kochuvareed_family_tree(request, member_id=None):
#     return generic_family_tree(request, KochuvareedFamily, 'family7.html', member_id)

# def generic_family_tree(request, FamilyModel, template_name, member_id=None):
#     # If no member_id provided, try to find a root member
#     if member_id is None:
#         root_members = FamilyModel.objects.filter(parent__isnull=True)
#         if root_members.exists():
#             member = root_members.first()
#         else:
#             member = FamilyModel.objects.first()
#             if not member:
#                 # Handle case where no members exist yet
#                 return render(request, template_name, {'member': None})
#     else:
#         member = get_object_or_404(FamilyModel, pk=member_id)
    
#     context = {
#         'member': member,
#         'family_name': FamilyModel._meta.verbose_name_plural,
#     }
#     return render(request, template_name, context)

from django.shortcuts import render, get_object_or_404
from .models import (
    AipuFamily,
    LonappanFamily,
    FrancisFamily,
    VarunnyFamily,
    ThomaFamily,
    ChakoruFamily,
    KochuvareedFamily,
)

def family_tree(request, member_id=None):
    return generic_family_tree(request, AipuFamily, 'family1.html', member_id)

def lonappan_family_tree(request, member_id=None):
    return generic_family_tree(request, LonappanFamily, 'family2.html', member_id)

def francis_family_tree(request, member_id=None):
    return generic_family_tree(request, FrancisFamily, 'family3.html', member_id)

def varunny_family_tree(request, member_id=None):
    return generic_family_tree(request, VarunnyFamily, 'family4.html', member_id)

def thoma_family_tree(request, member_id=None):
    return generic_family_tree(request, ThomaFamily, 'family5.html', member_id)

def chakoru_family_tree(request, member_id=None):
    return generic_family_tree(request, ChakoruFamily, 'family6.html', member_id)

def kochuvareed_family_tree(request, member_id=None):
    return generic_family_tree(request, KochuvareedFamily, 'family7.html', member_id)

def generic_family_tree(request, FamilyModel, template_name, member_id=None):
    # If no member_id provided, try to find a root member
    if member_id is None:
        root_members = FamilyModel.objects.filter(parent__isnull=True).prefetch_related('spouses', 'children')
        if root_members.exists():
            member = root_members.first()
        else:
            member = FamilyModel.objects.first()
            if not member:
                # Handle case where no members exist yet
                return render(request, template_name, {'member': None, 'family_name': FamilyModel._meta.verbose_name_plural})
    else:
        member = get_object_or_404(FamilyModel.objects.prefetch_related('spouses', 'children'), pk=member_id)
    
    context = {
        'member': member,
        'family_name': FamilyModel._meta.verbose_name_plural,
    }
    return render(request, template_name, context)