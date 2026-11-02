from rest_framework.permissions import BasePermission


def is_approved(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.is_approved and user.is_active)


class IsApproved(BasePermission):
    """Signed in AND approved by the committee (staff always pass)."""
    message = "Your account is waiting for approval by the family committee."

    def has_permission(self, request, view):
        return is_approved(request.user)


class IsStaff(BasePermission):
    message = "Only committee members (admins) can do this."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)
