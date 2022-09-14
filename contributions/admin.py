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
from rangefilter.filters import DateTimeRangeFilter


class ContributionAdmin(admin.ModelAdmin):
    """How should the Contribution be shown on the admin site."""

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
