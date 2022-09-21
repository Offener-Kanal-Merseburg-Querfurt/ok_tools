from .disa_import import disa_import
from .models import Contribution
from .models import DisaImport
from admin_searchable_dropdown.filters import AutocompleteFilterFactory
from django import http
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.decorators import display
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext as _p
from import_export import resources
from import_export.admin import ExportMixin
from import_export.fields import Field
from rangefilter.filters import DateTimeRangeFilter
import datetime
import logging


logger = logging.getLogger('django')


class ContributionResource(resources.ModelResource):
    """Define the export for Contributions."""

    def _f(field, name=None):
        """Shortcut for field creation."""
        return Field(attribute=field, column_name=name)

    number = _f('license__number', _('License number'))
    title = _f('license__title', _('Title'))
    subtitle = _f('license__subtitle', _('Subtitle'))
    broadcast_date = _f('broadcast_date__date', _('Broadcast Date'))
    broadcast_time = _f('broadcast_date__time', _('Broadcast Time'))
    profile = _f('license__profile', _('Profile'))
    duration = _f('license__duration', _('Duration'))

    class Meta:
        """Define meta properties for Contribution export."""

        model = Contribution
        fields = ['live']


class YearFilter(admin.SimpleListFilter):
    """Filter after this or last years broadcast_date."""

    title = _('Broadcast year')
    parameter_name = 'broadcast_date'

    def lookups(self, request, model_admin):
        """Define labels to filter after this or last year."""
        return (
            ('this', _('This year')),
            ('last', _('Last year')),
        )

    def queryset(self, request, queryset):
        """Filter after broadcast date for this or last year."""
        match self.value():
            case None:
                return
            case 'this':
                return queryset.filter(
                    broadcast_date__year=datetime.datetime.now().year)
            case 'last':
                return queryset.filter(
                    broadcast_date__year=datetime.datetime.now().year-1)
            case _:
                msg = f'Invalid value {self.value()}.'
                logger.error(msg)
                raise ValueError(msg)


class ContributionAdmin(ExportMixin, admin.ModelAdmin):
    """How should the Contribution be shown on the admin site."""

    resource_class = ContributionResource

    list_display = (
        'get_title',
        'get_subtitle',
        'get_user',
        'broadcast_date',
        'get_number',
    )
    autocomplete_fields = ['license']

    ordering = ['-broadcast_date']
    search_fields = [
        'license__title',
        'license__subtitle',
        'license__number',
    ]
    search_help_text = _('Title, Subtitle, Number')

    list_filter = [
        AutocompleteFilterFactory(_('Profile'), 'license__profile'),
        ('broadcast_date', DateTimeRangeFilter),
        YearFilter,
    ]

    readonly_fields = ('_is_primary',)

    @display(boolean=True, description=(_('Is primary')))
    def _is_primary(self, obj):
        return obj.is_primary()

    @display(description=_('Title'))
    def get_title(self, obj):
        """Return the title of the corresponding license."""
        return obj.license.title

    @display(description=_('Subtitle'))
    def get_subtitle(self, obj):
        """Return the subtitle of the corresponding license."""
        return obj.license.subtitle

    @display(description=_('User'))
    def get_user(self, obj):
        """Return the first an last name of the contributions user."""
        return (f'{obj.license.profile.first_name}'
                f' {obj.license.profile.last_name}')

    @display(description=_('Number'))
    def get_number(self, obj):
        """Return the number of the license request."""
        return obj.license.number


admin.site.register(Contribution, ContributionAdmin)


class DisaImportAdmin(admin.ModelAdmin):
    """How should the DISA export data and import options be shown."""

    change_form_template = 'admin/disa_import_change_form.html'

    list_display = (
        '__str__',
        'imported',
    )

    ordering = ['-file']
    actions = ['import_files']

    @admin.action(description=_('Import selected DISA exports.'))
    def import_files(self, request, queryset):
        """Import selected files."""
        imported = 0
        for i in queryset:
            disa_import(request, i.file)
            i.imported = True
            i.save()
            imported += 1

        self.message_user(request, _p(
            '%d file successfully imported.',
            '%d files successfully imported.',
            imported
        ) % imported, messages.SUCCESS)

    def response_change(self, request, obj: DisaImport):
        """Add 'Import' button to change view."""
        if '_import_disa' in request.POST:
            disa_import(request, obj.file)
            obj.imported = True
            obj.save()
            self.message_user(request, _('"%(obj)s" successfully imported.') %
                              {'obj': obj}, level=messages.ERROR)

            return http.HttpResponseRedirect(request.path_info)
        return super().response_change(request, obj)


admin.site.register(DisaImport, DisaImportAdmin)
