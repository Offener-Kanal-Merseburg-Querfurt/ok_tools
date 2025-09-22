from .disa_import import disa_import
from .models import Contribution
from .models import ContributionManager
from .models import DisaImport
from admin_searchable_dropdown.filters import AutocompleteFilterFactory
from datetime import datetime as dt
from django import http
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.decorators import display
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext as _p
from import_export import resources
from import_export.admin import ExportMixin
from import_export.fields import Field
from ok_tools.datetime import TZ
# from rangefilter.filters import DateTimeRangeFilter
import datetime
import logging
import tablib


logger = logging.getLogger('django')


class CustomDateTimeRangeFilter(admin.FieldListFilter):
    """Custom filter for date and time range, compatible with Django 5+."""

    template = 'admin/filter_datetime_range.html'
    title = 'Broadcast date'

    def __init__(self, field, request, params, model, model_admin, field_path):
        self.field_path = field_path
        self.parameter_name = field_path
        self.used_parameters = params
        super().__init__(field, request, params, model, model_admin, field_path)

    def choices(self, changelist):
        return ({
            'request': self.request,
            'parameter_name': self.parameter_name,
            'form': self._get_form(),
            'title': self.title,
        }, )

    def _get_form(self):
        """Create a form for the filter."""
        from django import forms

        class DateTimeRangeForm(forms.Form):
            gte_0 = forms.CharField(
                label=_('Date from'),
                required=False,
                widget=forms.TextInput(attrs={'placeholder': _('From'), 'type': 'date'})
            )
            gte_1 = forms.CharField(
                label=_('Time from'),
                required=False,
                widget=forms.TextInput(attrs={'placeholder': _('From'), 'type': 'time'})
            )
            lte_0 = forms.CharField(
                label=_('Date to'),
                required=False,
                widget=forms.TextInput(attrs={'placeholder': _('To'), 'type': 'date'})
            )
            lte_1 = forms.CharField(
                label=_('Time to'),
                required=False,
                widget=forms.TextInput(attrs={'placeholder': _('To'), 'type': 'time'})
            )

        # Create a dictionary with data for the form
        form_data = {}
        for param in self.expected_parameters():
            if param in self.used_parameters:
                form_data[param.replace(f'{self.parameter_name}__', '')] = self.used_parameters[param]

        return DateTimeRangeForm(data=form_data)

    def queryset(self, request, queryset):
        """Apply the filter to the queryset."""
        gte_date = self.used_parameters.get(f'{self.parameter_name}__gte_0')
        gte_time = self.used_parameters.get(f'{self.parameter_name}__gte_1')
        lte_date = self.used_parameters.get(f'{self.parameter_name}__lte_0')
        lte_time = self.used_parameters.get(f'{self.parameter_name}__lte_1')

        # Process the case when the parameter can be a list
        if isinstance(gte_date, list):
            gte_date = gte_date[0] if gte_date else None
        if isinstance(gte_time, list):
            gte_time = gte_time[0] if gte_time else None
        if isinstance(lte_date, list):
            lte_date = lte_date[0] if lte_date else None
        if isinstance(lte_time, list):
            lte_time = lte_time[0] if lte_time else None

        if gte_date:
            try:
                gte_datetime = datetime.datetime.strptime(gte_date, '%Y-%m-%d')
                if gte_time:
                    gte_time_obj = datetime.datetime.strptime(gte_time, '%H:%M').time()
                    gte_datetime = datetime.datetime.combine(gte_datetime.date(), gte_time_obj)
                queryset = queryset.filter(**{f'{self.field_path}__gte': gte_datetime})
            except ValueError:
                pass

        if lte_date:
            try:
                lte_datetime = datetime.datetime.strptime(lte_date, '%Y-%m-%d')
                if lte_time:
                    lte_time_obj = datetime.datetime.strptime(lte_time, '%H:%M').time()
                    lte_datetime = datetime.datetime.combine(lte_datetime.date(), lte_time_obj)
                else:
                    lte_datetime = datetime.datetime.combine(lte_datetime.date(), datetime.time.max)
                queryset = queryset.filter(**{f'{self.field_path}__lte': lte_datetime})
            except ValueError:
                pass

        return queryset

    def expected_parameters(self):
        """Return expected parameters."""
        return [
            f'{self.parameter_name}__gte_0',
            f'{self.parameter_name}__gte_1',
            f'{self.parameter_name}__lte_0',
            f'{self.parameter_name}__lte_1',
        ]


class ProgramResource(resources.ModelResource):
    """Define the export for the TV program."""

    def _create_screen_board(self, date, start_time, end_time):
        """Create a screen board for the given time slot."""
        SCREEN_BOARD = 'Infoblock'
        return [
            str(date),
            str(start_time),
            str(end_time),
            SCREEN_BOARD,
            '',  # subtitle
            '',  # description
            '',  # credits
            False,
            '',  # category
            '',  # store_in_ok_media_library
        ]

    # Override for the original method defined in
    # https://github.com/django-import-export/django-import-export/blob/32279cec9ea0383d2fba69954f8c556d3b332617/import_export/resources.py#L920
    def export(self, queryset=None, *args, **kwargs):
        """Export a program resource and add screen boards if necessary."""
        self.before_export(queryset, *args, **kwargs)

        # only fill gaps with more than one minute waiting time
        TOLERANCE = datetime.timedelta(minutes=1)

        if queryset is None:
            queryset = self.get_queryset()

        queryset = queryset.order_by('broadcast_date')

        data = tablib.Dataset()

        prev_contr = None
        for obj in queryset.iterator(chunk_size=1000):
            # create a screen board if there is a gap in the program
            if ((end_time := self._get_end_time(prev_contr))
                    != (start_time := self._get_start_time(obj))):

                # we need a datetime object for subtraction
                today = dt.today()
                delta = (dt.combine(today, start_time) -
                         dt.combine(today, end_time))

                if delta > TOLERANCE:
                    data.append(
                        self._create_screen_board(
                            obj.broadcast_date.date(),
                            end_time,
                            start_time
                        )
                    )

            data.append(self.export_resource(obj))
            prev_contr = obj

        # create screen board if last contribution does not end at 0:00
        if ((end_date := self._get_end_time(prev_contr))
                != datetime.time(hour=0, minute=0)):
            screen_board_date = (prev_contr.broadcast_date + prev_contr.license.duration).date()
            data.append(
                self._create_screen_board(
                    screen_board_date,
                    end_date,
                    datetime.time(hour=0, minute=0)
                )
            )

        self.after_export(queryset, data, *args, **kwargs)

        return data

    def _f(field=None, name=None):
        """Shortcut for field creation."""
        return Field(attribute=field, column_name=name)

    broadcast_date = _f('broadcast_date__date', _('Broadcast Date'))
    broadcast_start_time = _f(name=_('Start Time'))
    broadcast_end_time = _f(name=_('End Time'))
    title = _f('license__title', _('Title'))
    subtitle = _f('license__subtitle', _('Subtitle'))
    description = _f('license__description', _('Description'))
    credits = _f(name=_('Credits'))
    contribution = _f()
    category = _f('license__category', name=_('Category'))
    store_in_ok_media_library = _f('license__store_in_ok_media_library', _('Store in OK media library'))

    def _get_start_time(self, contribution: Contribution):
        """Return the start time of a contribution in the current time zone."""
        return (contribution
                .broadcast_date
                .astimezone(tz=TZ)
                .time())

    def _get_end_time(self, contribution: Contribution):
        """Return the end time of a contribution in the current time zone."""
        if contribution is None:
            return datetime.time(hour=0, minute=0)

        end_datetime = (contribution.broadcast_date.astimezone(tz=TZ)
                        + contribution.license.duration)

        # It is possible that the time extends with the start date
        # e.g. 23:58 to 0:00. Nevertheless only one start date is given.
        return end_datetime.time()

    def dehydrate_broadcast_date(self, contribution: Contribution):
        """Show broadcast date in current time zone."""
        return str(contribution
                   .broadcast_date
                   .astimezone(tz=TZ)
                   .date())

    def dehydrate_broadcast_start_time(self, contribution: Contribution):
        """Show broadcast time in current time zone."""
        return str(self._get_start_time(contribution))

    def dehydrate_broadcast_end_time(self, contribution: Contribution):
        """Show broadcast time in current time zone."""
        return str(self._get_end_time(contribution))

    def dehydrate_credits(self, contribution: Contribution):
        """Show the author with introduction."""
        INTRODUCTION = 'Ein Beitrag von'
        return f'{INTRODUCTION} {contribution.license.profile}'

    def dehydrate_contribution(self, contribution: Contribution):
        """Show whether it is a contribution or a screen board or infoblock."""
        if getattr(contribution.license, 'infoblock', False):
            return False
        return True

    class Meta:
        """Define meta properties for Contribution export."""

        name = _('Program')
        model = Contribution
        fields = []


class ContributionResource(resources.ModelResource):
    """Define the export for Contributions."""

    def export(self, queryset=None, *args, **kwargs):
        """Only export primary contributions."""
        if queryset is None:
            queryset = self.get_queryset()
        data = tablib.Dataset()
        data.headers = [field.column_name for field in self.get_export_fields()]
        if hasattr(queryset, 'iterator'):
            iterator = queryset.iterator(chunk_size=1000)
        else:
            iterator = iter(queryset)
        for obj in iterator:
            if obj.is_primary():
                data.append(self.export_resource(obj))
        self.after_export(queryset, data, *args, **kwargs)
        return data

    def _f(field, name=None):
        """Shortcut for field creation."""
        return Field(attribute=field, column_name=name)

    number = _f('license__number', _('License number'))
    title = _f('license__title', _('Title'))
    subtitle = _f('license__subtitle', _('Subtitle'))
    broadcast_date = _f('broadcast_date__date', _('Broadcast Date'))
    broadcast_time = _f('broadcast_date__time', _('Broadcast Time'))
    profile = _f('license__profile', _('Profile'))
    profile_id = _f('license__profile__id', _('Profile ID'))
    duration = _f('license__duration', _('Duration'))
    live = _f('live', _('Live'))

    def dehydrate_broadcast_date(self, contribution: Contribution):
        """Show broadcast date in current time zone."""
        return str(contribution
                   .broadcast_date
                   .astimezone(tz=TZ)
                   .date())

    def dehydrate_broadcast_time(self, contribution: Contribution):
        """Show broadcast date in current time zone."""
        return str(contribution
                   .broadcast_date
                   .astimezone(tz=TZ)
                   .time())

    class Meta:
        """Define meta properties for Contribution export."""

        name = _('Data export')
        model = Contribution
        fields = []


class WeekFilter(admin.SimpleListFilter):
    """Filter the contributions for the next 3 weeks."""

    title = _('Broadcast week')
    parameter_name = 'broadcast_week'

    def lookups(self, request, model_admin):
        """Define labels to filter after the broadcast week."""
        return (
            ('this_week', _('In this week')),
            ('next_week', _('Until next week')),
            ('after_next_week', _('Until week after next')),
        )

    def queryset(self, request, queryset):
        """Filter after broadcast date for the chosen weeks."""
        week = datetime.datetime.now().date().isocalendar().week
        year = datetime.datetime.now().year

        match self.value():
            case None:
                return
            case 'this_week':
                return queryset.filter(broadcast_date__week=week,
                                       broadcast_date__year=year)
            case 'next_week':
                return (queryset
                        .filter(broadcast_date__week__gte=week,
                                broadcast_date__year=year)
                        .filter(broadcast_date__week__lte=week+1,
                                broadcast_date__year=year))
            case 'after_next_week':
                return (queryset
                        .filter(broadcast_date__week__gte=week,
                                broadcast_date__year=year)
                        .filter(broadcast_date__week__lte=week+2,
                                broadcast_date__year=year))
            case _:
                msg = f'Invalid value {self.value()}.'
                logger.error(msg)
                raise ValueError(msg)


class PrimaryFilter(admin.SimpleListFilter):
    """Filter after primary contributions."""

    title = _('Primary Contribution')
    parameter_name = 'primary_contribution'

    def lookups(self, request, model_admin):
        """Define labels for filtering."""
        return (
            ('y', _('Yes')),
            ('n', _('No')),
        )

    def queryset(self, request, queryset):
        """Filter after primary contributions."""
        match self.value():
            case None:
                return
            case 'y':
                ids = ContributionManager().primary_contributions(queryset)
                return queryset.filter(id__in=ids)
            case 'n':
                ids = ContributionManager().repetitions(queryset)
                return queryset.filter(id__in=ids)

            case _:
                msg = f'Invalid value {self.value()}.'
                logger.error(msg)
                raise ValueError(msg)


class YearFilter(admin.SimpleListFilter):
    """Filter after this or last years broadcast_date."""

    title = _('Broadcast year')
    parameter_name = 'broadcast_year'

    def lookups(self, request, model_admin):
        """Define labels to filter after this or last year."""
        return (
            ('this_year', _('This year')),
            ('last_year', _('Last year')),
        )

    def queryset(self, request, queryset):
        """Filter after broadcast date for this or last year."""
        match self.value():
            case None:
                return
            case 'this_year':
                return queryset.filter(
                    broadcast_date__year=datetime.datetime.now().year)
            case 'last_year':
                return queryset.filter(
                    broadcast_date__year=datetime.datetime.now().year-1)
            case _:
                msg = f'Invalid value {self.value()}.'
                logger.error(msg)
                raise ValueError(msg)


class ContributionAdmin(ExportMixin, admin.ModelAdmin):
    """How should the Contribution be shown on the admin site."""

    resource_classes = [ProgramResource, ContributionResource]
    export_template_name = 'admin/export.html'

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
        ('broadcast_date', CustomDateTimeRangeFilter),
        PrimaryFilter,
        YearFilter,
        WeekFilter,
        AutocompleteFilterFactory(
            _('Media Authority'), 'license__profile__media_authority'),
    ]

    readonly_fields = ('_is_primary',)

    @display(boolean=True, description=(_('Is primary')))
    def _is_primary(self, obj):
        return obj.is_primary()

    @display(ordering='license__title', description=_('Title'))
    def get_title(self, obj):
        """Return the title of the corresponding license."""
        return obj.license.title

    @display(ordering='license__subtitle', description=_('Subtitle'))
    def get_subtitle(self, obj):
        """Return the subtitle of the corresponding license."""
        return obj.license.subtitle

    @display(ordering='license__profile__last_name', description=_('User'))
    def get_user(self, obj):
        """Return the first an last name of the contributions user."""
        return (f'{obj.license.profile.first_name}'
                f' {obj.license.profile.last_name}')

    @display(ordering='license__number', description=_('Number'))
    def get_number(self, obj):
        """Return the number of the license."""
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
                              {'obj': obj}, level=messages.SUCCESS)

            return http.HttpResponseRedirect(request.path_info)
        return super().response_change(request, obj)


admin.site.register(DisaImport, DisaImportAdmin)
