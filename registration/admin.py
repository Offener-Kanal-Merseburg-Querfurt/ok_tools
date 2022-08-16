from .models import MediaAuthority
from .models import Profile
from .print import generate_registration_form
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext as _p


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
        }),
        # https://github.com/gocept/ok_tools/issues/11
        # (_('permissions'), {
        #     'fields': ('user_permissions',)
        # }),
        (_('Staff'), {
            'fields': ('is_staff',)
        }),
    )
    add_fieldsets = (
        (_('E-Mail address'), {
            'fields': ('email',)
        }),
        (_('Password'), {
            'fields': ('password1', 'password2')
        }),
        (_('Staff'), {
            'fields': ('is_staff',)
        }),
    )
    list_display = ['email', 'last_login', 'is_superuser', 'is_staff']
    ordering = ['email']
    search_fields = ['email']

    # inspired by https://stackoverflow.com/a/54579134
    def save_model(self, request, obj, form, change):
        """
        Set update_fields.

        Observed field is 'is_staff'.
        Set update_fields to use the post_save signal to set permissions.
        Necessary for registration/signals.py/is_staff .
        """
        if form and form.changed_data:
            initial = form.initial.get('is_staff')
            new = form.cleaned_data.get('is_staff')
            if not (initial is None or new is None) and initial != new:
                obj.save(update_fields=['is_staff'])

        return super(UserAdmin, self).save_model(request, obj, form, change)


admin.site.register(User, UserAdmin)


# register profile
class ProfileAdmin(admin.ModelAdmin):
    """How should the profile be shown on the admin site."""

    change_form_template = 'admin/change_form_edit.html'

    list_display = [
        'okuser',
        'first_name',
        'last_name',
        'verified',
        'created_at',
    ]
    ordering = ['-created_at']

    search_fields = ['okuser__email', 'first_name', 'last_name']
    actions = ['verify', 'unverify']

    # inspired from https://stackoverflow.com/a/54579134
    def save_model(self, request, obj, form, change):
        """
        Set update_fields.

        Observed field is 'verified'.
        Set update_fields to use the post_save signal to set permissions.
        Necessary for registration/signals.py/is_validated .
        """
        if form and form.changed_data:
            initial = form.initial.get('verified')
            new = form.cleaned_data.get('verified')
            if not (initial is None or new is None) and initial != new:
                obj.save(update_fields=['verified'])

        return super().save_model(request, obj, form, change)

    @admin.action(description=_('Verify selected profiles'))
    def verify(self, request, queryset):
        """Verify all selected profiles."""
        updated = queryset.update(verified=True)
        self.message_user(request, _p(
            '%d profile was successfully verified.',
            '%d profiles were successfully verified.',
            updated,
        ) % updated, messages.SUCCESS)

    @admin.action(description=_('Unverify selected profiles'))
    def unverify(self, request, queryset):
        """Unverify all selected profiles."""
        updated = queryset.update(verified=False)
        self.message_user(request, _p(
            '%d profile was successfully unverified.',
            '%d profiles were successfully unverified.',
            updated,
        ) % updated, messages.SUCCESS)

    def response_change(self, request, obj):
        """Add 'Print application' button to profile view."""
        if '_print_application' in request.POST:
            return generate_registration_form(obj.okuser, obj)
        return super().response_change(request, obj)


admin.site.register(Profile, ProfileAdmin)

admin.site.register(MediaAuthority)
