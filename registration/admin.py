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
from django_admin_listfilter_dropdown.filters import DropdownFilter
from registration.signals import signal
import logging


logger = logging.getLogger('django')

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
        (_('Admin'), {
            'fields': ('is_superuser',)
        }),
        (_('permissions'), {
            'fields': ('user_permissions',)
        }),
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


admin.site.register(User, UserAdmin)


class BirthmonthFilter(admin.SimpleListFilter):
    """Filter profiles using a given birth month."""

    template = 'django_admin_listfilter_dropdown/dropdown_filter.html'
    title = _('birthmonth')
    parameter_name = 'birthday'

    def lookups(self, request, model_admin):
        """Labels for the possible months."""
        return (
            (1, _('January')),
            (2, _('February')),
            (3, _('March')),
            (4, _('April')),
            (5, _('May')),
            (6, _('June')),
            (7, _('July')),
            (8, _('August')),
            (9, _('September')),
            (10, _('October')),
            (11, _('November')),
            (12, _('December')),
        )

    def queryset(self, request, queryset):
        """Filter the profiles using the given month."""
        if self.value() is None:
            return

        try:
            value = int(self.value())
        except ValueError:
            raise ValueError(f'Unsupported filter option {self.value()}')

        if value < 1 or value > 12:
            raise ValueError(f'Unsupported filter option {self.value()}')

        return queryset.filter(birthday__month=int(value))


# register profile
class ProfileAdmin(admin.ModelAdmin):
    """How should the profile be shown on the admin site."""

    change_form_template = 'admin/registration_change_form_edit.html'

    list_display = [
        'okuser',
        'first_name',
        'last_name',
        'birthday',
        'verified',
        'member',
        'created_at',
    ]
    autocomplete_fields = ['okuser']
    ordering = ['-created_at']

    search_fields = ['okuser__email', 'first_name', 'last_name']
    search_help_text = _('e-mail, first name, last name')

    list_filter = [
        BirthmonthFilter,
        ('media_authority__name', DropdownFilter),
        'member',
    ]
    actions = ['verify', 'unverify']

    # inspired from https://stackoverflow.com/a/54579134
    def save_model(self, request, obj, form, change):
        """
        Set update_fields.

        Observed field is 'verified'.
        Set update_fields to use the post_save signal to set permissions.
        Necessary for registration/signals.py/verify_profile.
        """
        if form and form.changed_data:
            initial = form.initial.get('verified')
            new = form.cleaned_data.get('verified')
            if not (initial is None or new is None) and initial != new:
                signal.send(sender=self, obj=obj, request=request)

        return super().save_model(request, obj, form, change)

    @admin.action(description=_('Verify selected profiles'))
    def verify(self, request, queryset):
        """Verify all selected profiles."""
        updated = self._set_verified(queryset, True, request)
        self.message_user(request, _p(
            '%d profile was successfully verified.',
            '%d profiles were successfully verified.',
            updated,
        ) % updated, messages.SUCCESS)

    @admin.action(description=_('Unverify selected profiles'))
    def unverify(self, request, queryset):
        """Unverify all selected profiles."""
        updated = self._set_verified(queryset, False, request)
        self.message_user(request, _p(
            '%d profile was successfully unverified.',
            '%d profiles were successfully unverified.',
            updated,
        ) % updated, messages.SUCCESS)

    def _set_verified(self, queryset, value: bool, request) -> int:
        """Set the `verified` attribute.

        Return the amount of updated objects.
        """
        updated = 0
        for obj in queryset:
            if obj.verified == value:
                continue
            obj.verified = value
            obj.save()
            if obj.verified:
                signal.send(sender=self, obj=obj, request=request)
            updated += 1
        return updated

    def response_change(self, request, obj):
        """Add 'Print application' button to profile view."""
        if '_print_application' in request.POST:
            return generate_registration_form(obj.okuser, obj)
        return super().response_change(request, obj)


admin.site.register(Profile, ProfileAdmin)

admin.site.register(MediaAuthority)
