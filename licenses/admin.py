from .models import Category
from .models import LicenseRequest
from django.contrib import admin
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext as _p


class LicenseRequestAdmin(admin.ModelAdmin):
    """How should the LicenseRequests be shown on the admin site."""

    list_display = (
        '__str__',
        'okuser',
        'created_at',
        'confirmed',
    )

    ordering = ['-created_at']

    # TODO it is not possible to search in string representation
    search_fields = ['okuser__email', 'title', 'subtitle']
    actions = ['confirm', 'unconfirm']

    @admin.action(description=_('Confirm selected License Requests'))
    def confirm(self, request, queryset):
        """Confirm all selected profiles."""
        updated = self._set_confirmed(queryset, True)
        self.message_user(request, _p(
            '%d License Request was successfully confirmed.',
            '%d License Requests were successfully confirmed.',
            updated
        ) % updated, messages.SUCCESS)

    @admin.action(description=_('Unconfirm selected License Requests'))
    def unconfirm(self, request, queryset):
        """Unconfirm all selected profiles."""
        updated = self._set_confirmed(queryset, False)
        self.message_user(request, _p(
            '%d License Request was successfully unconfirmed.',
            '%d License Requests were successfully unconfirmed.',
            updated
        ) % updated, messages.SUCCESS)

    def _set_confirmed(self, queryset, value: bool):
        """
        Set the 'confirmed' attribute.

        Return the amount of updated objects.
        """
        updated = 0
        for obj in queryset:
            if obj.confirmed != value:
                obj.confirmed = value
                # in case we need to to further actions when a license is
                # confirmed later
                obj.save(update_fields=['confirmed'])
                updated += 1

        return updated


admin.site.register(LicenseRequest, LicenseRequestAdmin)

admin.site.register(Category)
