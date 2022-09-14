from .models import Category
from .models import LicenseRequest
from admin_searchable_dropdown.filters import AutocompleteFilterFactory
from django.contrib import admin
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext as _p
from rangefilter.filters import DateTimeRangeFilter
import datetime
import logging


logger = logging.getLogger('django')


class DurationFilter(admin.SimpleListFilter):
    """Filter licenses using duration ranges."""

    title = _('Duration')
    parameter_name = 'duration'

    def lookups(self, request, model_admin):
        """Labels to specify the duration range."""
        return (
            ('10m', _('<= 10 minutes')),
            ('30m', _('<= 30 minutes, >10 minutes')),
            ('1h', _('<= 1 hour, > 30 minutes')),
            ('1h+', _('> 1 hour ')),
        )

    def queryset(self, request, queryset):
        """Filter profiles using the given duration range."""
        if self.value() is None:
            return
        match self.value():
            case '10m':
                return queryset.filter(
                    duration__lte=datetime.timedelta(minutes=10),
                )
            case '30m':
                return queryset.filter(
                    duration__lte=datetime.timedelta(minutes=30),
                    duration__gt=datetime.timedelta(minutes=10),
                )
            case '1h':
                return queryset.filter(
                    duration__lte=datetime.timedelta(hours=1),
                    duration__gt=datetime.timedelta(minutes=30),
                )
            case '1h+':
                return queryset.filter(
                    duration__gt=datetime.timedelta(hours=1),
                )
            case _:
                msg = f'Invalid value {self.value()}.'
                logger.error(msg)
                raise ValueError(msg)


class LicenseRequestAdmin(admin.ModelAdmin):
    """How should the LicenseRequests be shown on the admin site."""

    change_form_template = 'admin/licenses_change_form_edit.html'
    list_display = (
        'title',
        'subtitle',
        'profile',
        'number',
        'duration',
        'created_at',
        'confirmed',
    )

    ordering = ['-created_at']

    search_fields = [
        'title',
        'subtitle',
        'number',
        'description',
        'further_persons',
    ]
    search_help_text = _(
        'title, subtitle, number, description, further persons')

    actions = ['confirm', 'unconfirm']

    list_filter = [
        AutocompleteFilterFactory(_('Profile'), 'profile'),
        ('created_at', DateTimeRangeFilter),
        DurationFilter,
    ]

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
                # in case we need to do further actions when a license is
                # confirmed later
                obj.save(update_fields=['confirmed'])
                updated += 1

        return updated

    def change_view(
            self, request, object_id, form_url="", extra_context=None):
        """Don't show the save buttons if LR is confirmed."""
        license = get_object_or_404(LicenseRequest, pk=object_id)
        extra_context = extra_context or {}

        extra_context['object'] = license

        if license.confirmed:
            extra_context['show_save_and_continue'] = False
            extra_context['show_save'] = False
            extra_context['show_save_and_add_another'] = False

        return super().changeform_view(
            request, object_id, form_url, extra_context)

    def add_view(self, request, form_url="", extra_context=None):
        """Exclude the number field."""
        self.exclude = ['number']
        result = super().add_view(request, form_url, extra_context)
        # Because exclude is also used by change_view
        self.exclude = None

        return result


admin.site.register(LicenseRequest, LicenseRequestAdmin)

admin.site.register(Category)
