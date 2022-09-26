from .models import Category
from .models import LicenseRequest
from admin_searchable_dropdown.filters import AutocompleteFilterFactory
from django import forms
from django.contrib import admin
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext as _p
from import_export import resources
from import_export.admin import ExportMixin
from import_export.fields import Field
from ok_tools.datetime import TZ
from rangefilter.filters import DateTimeRangeFilter
import datetime
import logging


logger = logging.getLogger('django')


class LicenseRequestResource(resources.ModelResource):
    """Define the export for LicenseRequests."""

    def _f(field, name=None):
        """Shortcut for field creation."""
        return Field(attribute=field, column_name=name)

    number = _f('number', _('Number'))
    title = _f('title', _('Title'))
    subtitle = _f('subtitle', _('Subtitle'))
    description = _f('description', _('Description'))
    profile = _f('profile', _('Profile'))
    further_persons = _f('further_persons', _('Further involved persons'))
    duration = _f('duration', _('Duration'))
    category = _f('category__name', _('Category'))
    suggested_date = _f('suggested_date__date', _('Suggested broadcast date'))
    suggested_time = _f('suggested_date__time', _('Suggested broadcast time'))
    repetition_allowed = _f('repetitions_allowed', _('Repetitions allowed'))
    exchange = _f(
        'media_authority_exchange_allowed',
        _('Media Authority exchange allowed')
    )
    youth_protection = _f(
        'youth_protection_necessary', _('Youth protection necessary'))
    media_library = _f(
        'store_in_ok_media_library', _('Store in OK media library'))
    screen_board = _f('is_screen_board', _('Screen Board'))
    created_at = _f('created_at', _('created at'))

    def dehydrate_suggested_date(self, license: LicenseRequest):
        """Return the suggested date in the current time zone."""
        return str(license
                   .suggested_date
                   .astimezone(TZ)
                   .date())

    def dehydrate_suggested_time(self, license: LicenseRequest):
        """Return the suggested time in the current time zone."""
        return str(license
                   .suggested_date
                   .astimezone(TZ)
                   .time())

    def dehydrate_created_at(self, license: LicenseRequest):
        """Return the created_at datetime in the current time zone."""
        tz_datetime = license.created_at.astimezone(TZ)
        return f'{tz_datetime.date()} {tz_datetime.time()}'

    class Meta:
        """Define meta properties for the LicenseRequest export."""

        model = LicenseRequest
        fields = []


class YearFilter(admin.SimpleListFilter):
    """Filter after this or last year."""

    title = _('Creation year')

    parameter_name = 'created_at'

    def lookups(self, request, model_admin):
        """Define labels to filter after this or last year."""
        return (
            ('this', _('This year')),
            ('last', _('Last year')),
        )

    def queryset(self, request, queryset):
        """Filter after creation date for this or last year."""
        match self.value():
            case None:
                return
            case 'this':
                return queryset.filter(
                    created_at__year=datetime.datetime.now().year)
            case 'last':
                return queryset.filter(
                    created_at__year=datetime.datetime.now().year-1)
            case _:
                msg = f'Invalid value {self.value()}.'
                logger.error(msg)
                raise ValueError(msg)


class DurationFilter(admin.SimpleListFilter):
    """Filter licenses using duration ranges."""

    title = _('Duration')
    parameter_name = 'duration'

    def lookups(self, request, model_admin):
        """Labels to specify the duration range."""
        return (
            ('10m', _('<= 10 minutes')),
            ('30m', _('<= 30 minutes, > 10 minutes')),
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


class LicenseRequestAdminForm(forms.ModelForm):
    """Override the clean method for the forms used on the admin site."""

    def clean(self):
        """Raise an error if the LR of an unverified user gets confirmed."""
        if (self.cleaned_data['confirmed'] and
                not self.cleaned_data['profile'].verified):
            raise forms.ValidationError(
                {'confirmed': _('The corresponding profile is not verified.'
                                ' The License can not be confirmed until the'
                                ' profile is verified.')}
            )

        return super().clean()


class LicenseRequestAdmin(ExportMixin, admin.ModelAdmin):
    """How should the LicenseRequests be shown on the admin site."""

    form = LicenseRequestAdminForm
    resource_class = LicenseRequestResource

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
        YearFilter,
    ]

    @admin.action(description=_('Confirm selected License Requests'))
    def confirm(self, request, queryset):
        """Confirm all selected profiles."""
        updated = self._set_confirmed(request, queryset, True)
        self.message_user(request, _p(
            '%d License Request was successfully confirmed.',
            '%d License Requests were successfully confirmed.',
            updated
        ) % updated, messages.SUCCESS)

    @admin.action(description=_('Unconfirm selected License Requests'))
    def unconfirm(self, request, queryset):
        """Unconfirm all selected profiles."""
        updated = self._set_confirmed(request, queryset, False)
        self.message_user(request, _p(
            '%d License Request was successfully unconfirmed.',
            '%d License Requests were successfully unconfirmed.',
            updated
        ) % updated, messages.SUCCESS)

    def _set_confirmed(self, request, queryset, value: bool):
        """
        Set the 'confirmed' attribute.

        Return the amount of updated objects.
        """
        updated = 0
        for obj in queryset:
            if obj.confirmed == value:
                continue

            if value and not obj.profile.verified:
                # do not confirm LR of unverified users
                self.message_user(
                    request,
                    _('The corresponding profile of %(obj)s is not verified.'
                      ' The License can not be confirmed until the'
                      ' profile is verified.') % {'obj': obj},
                    messages.ERROR
                )
                continue

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
