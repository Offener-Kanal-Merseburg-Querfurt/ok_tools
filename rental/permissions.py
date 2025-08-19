from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import SAFE_METHODS
from rest_framework.permissions import BasePermission


class IsAuthenticatedAndMemberOrReadOnly(BasePermission):
    """Reading for all authenticated users, modifications only for members (profile.member)."""

    def has_permission(self, request, view):
        """Return True for safe methods; require authenticated member for write operations."""
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        profile = getattr(user, 'profile', None)
        return bool(profile and getattr(profile, 'member', False))


class CanCreateRentalRequest(BasePermission):
    """Right to create rental requests — for all authenticated users."""

    def has_permission(self, request, view):
        """Allow action if user is authenticated."""
        return bool(request.user and request.user.is_authenticated)


class StaffCanIssuePermission(BasePermission):
    """Issue/return can only be done by staff (is_staff)."""

    def has_permission(self, request, view):
        """Allow safe methods to any authenticated user; write only for staff users."""
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(user.is_staff)
