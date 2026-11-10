from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api"
    verbose_name = "Mobile app (API)"

    def ready(self):
        # Many families: every API request is locked to one family right after sign-in is
        # checked — for every view and every way of signing in (see tenancy.py).
        from rest_framework.exceptions import PermissionDenied
        from rest_framework.views import APIView

        from .tenancy import resolve_family_id, set_current_family

        original = APIView.perform_authentication

        def perform_authentication(view, request):
            original(view, request)
            user = request.user
            if user is not None and user.is_authenticated:
                fid = resolve_family_id(user, request.headers.get("X-Family"))
                if fid and not user.is_superuser:
                    from .models import Family
                    if not Family.objects.filter(pk=fid, is_active=True).exists():
                        raise PermissionDenied("Your family's Vamsham is paused. Please contact the Vamsham team.")
                set_current_family(fid)

        APIView.perform_authentication = perform_authentication
