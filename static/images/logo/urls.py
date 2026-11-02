from django.urls import path
from . import views
from .views import other_members_tree

urlpatterns = [
    # Aipu Family URLs
    path('aipu/', views.family_tree, name='aipu-family'),
    path('aipu/<int:member_id>/', views.family_tree, name='aipu-family-member'),
    
    # Lonappan Family URLs
    path('lonappan/', views.lonappan_family_tree, name='lonappan-family'),
    path('lonappan/<int:member_id>/', views.lonappan_family_tree, name='lonappan-family-member'),
    
    # Francis Family URLs
    path('francis/', views.francis_family_tree, name='francis-family'),
    path('francis/<int:member_id>/', views.francis_family_tree, name='francis-family-member'),
    
    # Varunny Family URLs
    path('varunny/', views.varunny_family_tree, name='varunny-family'),
    path('varunny/<int:member_id>/', views.varunny_family_tree, name='varunny-family-member'),
    
    # Thoma Family URLs
    path('thoma/', views.thoma_family_tree, name='thoma-family'),
    path('thoma/<int:member_id>/', views.thoma_family_tree, name='thoma-family-member'),
    
    # Chakoru Family URLs
    path('chakoru/', views.chakoru_family_tree, name='chakoru-family'),
    path('chakoru/<int:member_id>/', views.chakoru_family_tree, name='chakoru-family-member'),
    
    # Kochuvareed Family URLs
    path('kochuvareed/', views.kochuvareed_family_tree, name='kochuvareed-family'),
    path('kochuvareed/<int:member_id>/', views.kochuvareed_family_tree, name='kochuvareed-family-member'),

    # ✅ Porinchu Family URLs
    path('porinchu/', views.porinchu_family_tree, name='porinchu-family'),
    path('porinchu/<int:member_id>/', views.porinchu_family_tree, name='porinchu-family-member'),

    # ---------(other family member)-----------------
    path('other-members/', other_members_tree, name='other_members_tree'),

    
    # Home URL
    path('', views.family_tree, name='family-home'),
]