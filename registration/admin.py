from .models import Profile
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _


# register user
User = get_user_model()

admin.site.unregister(Group)


class UserAdmin(BaseUserAdmin):
    """How should the user be shown on the admin site."""

    fieldsets = (
        (_('E-Mail address'), {
            'fields': ('email',)
        }),
        (_('Password'), {
            'fields': ('password',)
        })
    )
    add_fieldsets = (
        (_('E-Mail address'), {
            'fields': ('email',)
        }),
        (_('Password'), {
            'fields': ('password1', 'password2')
        })
    )
    list_display = ['email', 'last_login', 'is_superuser', 'is_staff']
    ordering = ['email']
    search_fields = ['email']


admin.site.register(User, UserAdmin)


# register profile
class ProfileAdmin(admin.ModelAdmin):
    """How should the profile be shown on the admin site."""

    list_display = ['okuser', 'first_name', 'last_name', 'verified']
    ordering = ['okuser']
    search_fields = ['okuser__email', 'first_name', 'last_name']


admin.site.register(Profile, ProfileAdmin)
