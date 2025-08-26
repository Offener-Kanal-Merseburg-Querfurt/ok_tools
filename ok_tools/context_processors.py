from registration.models import Profile


def user_display_name(request):
    """Add user_display_name to global context."""
    if request.user.is_authenticated:
        try:
            profile = Profile.objects.get(okuser=request.user)
            if profile.first_name and profile.last_name:
                return {'user_display_name': f"{profile.first_name} {profile.last_name}"}
            elif profile.first_name:
                return {'user_display_name': profile.first_name}
            elif profile.last_name:
                return {'user_display_name': profile.last_name}
            else:
                return {'user_display_name': request.user.email or request.user.username}
        except Profile.DoesNotExist:
            return {'user_display_name': request.user.email or request.user.username}
    return {'user_display_name': None}
