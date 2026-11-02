from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from .models import (
    Gallery, Event, Profile, Member, Memory, Topic, Comment,
    TeamMember, PremiumEvent, Advertisement, LifeMember,
    AnnualReport, FamilyPhoto,
)
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from collections import defaultdict
from django.core.paginator import Paginator


# ── Annual Reports ────────────────────────────────────────────────────────────

def annual_reports(request):
    reports = AnnualReport.objects.prefetch_related('pdfs').order_by('-year')
    return render(request, 'annual-reports.html', {'reports': reports})


# ── History / Life Members ────────────────────────────────────────────────────

def History(request):
    members = LifeMember.objects.all().order_by('name')
    return render(request, 'our-history.html', {'members': members})


# ── Our Team ─────────────────────────────────────────────────────────────────

def team_list(request):
    general_qs = TeamMember.objects.filter(is_women_association=False).order_by("year", "name")
    general_by_year = defaultdict(list)
    for member in general_qs:
        general_by_year[member.year].append(member)

    women_qs = TeamMember.objects.filter(is_women_association=True).order_by("year", "name")
    women_by_year = defaultdict(list)
    for member in women_qs:
        women_by_year[member.year].append(member)

    return render(request, "our-team.html", {
        "general_by_year": dict(general_by_year),
        "women_by_year":   dict(women_by_year),
    })


def team_detail(request, slug):
    member = get_object_or_404(TeamMember, slug=slug)
    return render(request, "team-member-detail.html", {"member": member})


# ── Family Tree ───────────────────────────────────────────────────────────────

def family2(request):
    roots = Member.objects.filter(parent=None)
    return render(request, 'family2.html', {'roots': roots})


# ── Home ──────────────────────────────────────────────────────────────────────

def Home(request):
    advertisements = Advertisement.objects.all().order_by('-created_at')
    events         = Event.objects.prefetch_related('images').all().order_by('-date')[:4]
    memories       = Memory.objects.all().order_by('death_date')  # ← ordered by death date (oldest first)
    topic          = Topic.objects.first()
    comments       = Comment.objects.filter(topic=topic) if topic else []
    premium_events = PremiumEvent.objects.all()

    return render(request, 'index.html', {
        'advertisements': advertisements,
        'events':         events,
        'memories':       memories,
        'topic':          topic,
        'comments':       comments,
        'premium_events': premium_events,
    })


# ── Premium Events ────────────────────────────────────────────────────────────

def premium_event_view(request):
    events = PremiumEvent.objects.all()
    return render(request, 'premium_event_list.html', {'events': events})


def premium_event_detail(request, slug):
    event = get_object_or_404(PremiumEvent, slug=slug)
    return render(request, 'premium_event_detail.html', {'event': event})


# ── Memory ────────────────────────────────────────────────────────────────────

def memory_detail(request, id):
    memory = get_object_or_404(Memory, id=id)
    return render(request, 'memory_detail.html', {'memory': memory})


# ── Family Photos (single flat gallery page) ──────────────────────────────────

def family_photos(request):
    """
    Single-page family photo gallery.
    Supports optional ?year= filter via URL param.
    All filtering / lightbox is handled in the template with JS.
    """
    year_filter = request.GET.get('year', '').strip()

    photos = FamilyPhoto.objects.all()
    if year_filter:
        photos = photos.filter(year__icontains=year_filter)

    # Distinct year values for the filter tab bar
    all_years = (
        FamilyPhoto.objects
        .exclude(year='')
        .values_list('year', flat=True)
        .distinct()
        .order_by('-year')
    )

    return render(request, 'family_photos/family-photos.html', {
        'photos':      photos,
        'all_years':   all_years,
        'year_filter': year_filter,
        'total':       FamilyPhoto.objects.count(),
    })


# ── Registration ──────────────────────────────────────────────────────────────

def register(request):
    if request.method == "POST":
        email        = request.POST.get("email")
        first_name   = request.POST.get("first_name")
        password1    = request.POST.get("password1")
        password2    = request.POST.get("password2")
        phone_number = request.POST.get("phone")

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        if User.objects.filter(username=email).exists():
            messages.error(request, "User already exists.")
            return redirect("register")

        try:
            user = User.objects.create_user(
                username=email, email=email,
                password=password1, first_name=first_name,
            )
            Profile.objects.create(
                user=user, full_name=first_name,
                phone_number=phone_number, is_approved=False,
            )
            messages.success(request, f"Account created for {email}! Please wait for admin approval.")
            return redirect("login")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect("register")

    return render(request, "forms.html")


# ── Login / Logout ────────────────────────────────────────────────────────────

def custom_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(username=username, password=password)

        if user:
            try:
                profile = Profile.objects.get(user=user)
                if not profile.is_approved:
                    messages.error(request, "Your account is not approved yet.")
                    return redirect("login")
            except Profile.DoesNotExist:
                messages.error(request, "Profile not found. Contact admin.")
                return redirect("login")

            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name}!")
            return redirect("family_pillars")

        messages.error(request, "Invalid username or password.")
        return redirect("login")

    return render(request, "forms.html")


def custom_logout(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect("login")


# ── Discussion ────────────────────────────────────────────────────────────────

def discussion_view(request):
    topic    = Topic.objects.first()
    comments = Comment.objects.filter(topic=topic) if topic else []
    return render(request, 'discussion/discussion.html', {
        'topic': topic, 'comments': comments,
    })


@csrf_exempt
@login_required
def post_comment(request):
    if request.method == 'POST':
        content = request.POST.get('content')
        topic   = Topic.objects.first()
        if not topic:
            return JsonResponse({'success': False, 'error': 'No topic found.'})
        comment = Comment.objects.create(topic=topic, user=request.user, content=content)
        return JsonResponse({
            'success':   True,
            'username':  request.user.username,
            'timestamp': comment.posted_at.strftime('%Y-%m-%d %H:%M'),
            'content':   comment.content,
        })
    return JsonResponse({'success': False, 'error': 'Invalid request.'})


# ── Static Pages ─────────────────────────────────────────────────────────────

@login_required(login_url='login')
def FamilyPillars(request):
    return render(request, 'membership.html')


def gallery_list(request):
    galleries = Gallery.objects.all()
    return render(request, 'gallery.html', {'galleries': galleries})


def FamilyTree1(request):
    return render(request, 'tree.html')


# ── Events ────────────────────────────────────────────────────────────────────

def event_list(request):
    events = Event.objects.prefetch_related('images').all()

    query = request.GET.get('q', '').strip()
    if query:
        events = events.filter(title__icontains=query) | \
                 events.filter(description__icontains=query)

    category = request.GET.get('category', '').strip()
    if category:
        events = events.filter(category=category)

    all_categories = Event.objects.values_list('category', flat=True).distinct()
    paginator      = Paginator(events, 9)
    page_obj       = paginator.get_page(request.GET.get('page'))

    return render(request, 'events/event_list.html', {
        'page_obj':          page_obj,
        'all_categories':    all_categories,
        'current_query':     query,
        'current_category':  category,
    })