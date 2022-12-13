from .ics_export import ics_export
from .models import MediaEducationSupervisor
from .models import Project
from .models import ProjectCategory
from .models import ProjectLeader
from .models import ProjectParticipant
from .models import TargetGroup
from admin_searchable_dropdown.filters import AutocompleteFilterFactory
from django.contrib import admin
from django.db import models
from django.forms import widgets
from django.urls import path
from django.utils.translation import gettext_lazy as _
from import_export import resources
from import_export.admin import ExportMixin
from import_export.fields import Field
from ok_tools.datetime import TZ
from rangefilter.filters import DateTimeRangeFilter
from registration.models import Gender
import datetime
import json
import logging
import tablib


logger = logging.getLogger('django')


class MediaEducationSupervisorAdmin(admin.ModelAdmin):
    """Define search_fields for ProjectAdmin autocomplete_fields."""

    search_fields = ['name']


admin.site.register(MediaEducationSupervisor, MediaEducationSupervisorAdmin)


class ProjectLeaderAdmin(admin.ModelAdmin):
    """Define search fields for ProjectAdmin autocomplete_fields."""

    search_fields = ['name']


admin.site.register(ProjectLeader, ProjectLeaderAdmin)


class ProjectCategoryAdmin(admin.ModelAdmin):
    """Add search_fields for the AutocompleteFilterFactory."""

    search_fields = ['name']


admin.site.register(ProjectCategory, ProjectCategoryAdmin)


class TargetGroupAdmin(admin.ModelAdmin):
    """Add search_fields for the AutocompleteFilterFactory."""

    search_fields = ['name']


admin.site.register(TargetGroup, TargetGroupAdmin)


class ProjectParticipantsResource(resources.ModelResource):
    """Define export for project participants of the selected projects."""

    def _create_data_item(
            self, project: Project, participant: ProjectParticipant):
        """Create a data item that represents a row in the export."""
        return [
            project.title,
            str(project.begin_date.date()),
            participant.name,
            participant.age,
            Gender.verbose_name(participant.gender),
        ]

    def export(self, queryset=None, *args, **kwargs):
        """
        Collect all participants from the selected projects.

        And create corresponding the actual export data.
        """
        self.before_export(queryset, *args, **kwargs)

        if queryset is None:
            queryset = super().get_queryset()

        HEADER = [
            str(_('Project title')),
            str(_('Project date')),
            str(_('Name')),
            str(_('Age')),
            str(_('Gender')),
        ]
        NEWLINE = [None, None, None, None, None]

        data = tablib.Dataset(headers=HEADER)

        for pr in queryset:
            participants = pr.participants.all()
            for part in participants:
                data.append(self._create_data_item(pr, part))
            if participants:
                data.append(NEWLINE)

        return data

    class Meta:
        """Define meta properties for the export."""

        model = Project
        fields = []
        name = _('Project Participants')


class ProjectParticipantAdmin(admin.ModelAdmin):
    """Define search fields for ProjectAdmin autocomplete_fields."""

    search_fields = ['name']


admin.site.register(ProjectParticipant, ProjectParticipantAdmin)


class ProjectResource(resources.ModelResource):
    """Define the export for Projects."""

    def _f(field, name=None):
        """Shortcut for field creation."""
        return Field(attribute=field, column_name=name)

    title = _f('title', _('Title'))
    topic = _f('topic', _('Topic'))
    duration = _f('duration', _('Duration'))
    begin_date = _f('begin_date', _('Start date'))
    end_date = _f('end_date', _('End date'))
    external_venue = _f('external_venue', _('External venue'))
    jugendmedienschutz = _f('jugendmedienschutz', _('Jugendmedienschutz'))
    target_group = _f('target_group__name', _('Target group'))
    project_category = _f('project_category__name', _('Project category'))
    project_leader = _f('project_leader__name', _('Project leader'))
    supervisors = Field()

    def dehydrate_begin_date(self, project: Project) -> str:
        """Return the begin datetime in the current time zone."""
        tz_datetime = project.begin_date.astimezone(
            tz=TZ)
        return f'{tz_datetime.date()} {tz_datetime.time()}'

    def dehydrate_end_date(self, project: Project) -> str:
        """Return the end datetime in the current time zone."""
        tz_datetime = project.end_date.astimezone(
            tz=TZ)
        return f'{tz_datetime.date()} {tz_datetime.time()}'

    def dehydrate_supervisors(self, project: Project) -> str:
        """Convert all supervisors to one string."""
        return ', '.join(
            [str(x) for x in project.media_education_supervisors.all()])

    class Meta:
        """Define meta properties for the Project export."""

        model = Project
        fields = []
        name = _('Projects')


class YearFilter(admin.SimpleListFilter):
    """Filter after this or last year."""

    title = _('start year')

    parameter_name = 'begin_date'

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
                    begin_date__year=datetime.datetime.now().year)
            case 'last':
                return queryset.filter(
                    begin_date__year=datetime.datetime.now().year-1)
            case _:
                msg = f'Invalid value {self.value()}.'
                logger.error(msg)
                raise ValueError(msg)


class StatisticWidget(widgets.Widget):
    """Represent statistic json value as text table."""

    def format_value(self, value):
        """Format json to html-table."""
        value: dict = json.loads(value)
        result = self._create_header() + self._create_rows(value)
        return '\n'.join(result)

    def render(self, name, value, attrs, renderer):
        """Render the result as read only paragraph."""
        return "<table>\n"+str(self.format_value(value))+"\n</table>"

    def _create_header(self) -> list[str]:
        """Create header row."""
        def _th(value) -> str:
            return f'<th> {value} </th>'

        header = []
        header.append('<tr>')
        header.append(_th(''))
        header.append(_th(_('Male')))
        header.append(_th(_('Female')))
        header.append(_th(_('Diverse')))
        header.append(_th(_('Ohne Angabe')))
        header.append('</tr>')

        return ['\n'.join(header)]

    def _create_rows(self, json_obj: dict) -> list[str]:
        """Create value row."""
        if not json_obj:
            return []
        item = json_obj.popitem()
        row = []

        row.append('<tr>')
        row.append(self._format_label(item[0]))
        for elem in item[1]:
            row.append(f'<td> {elem} </td>')
        row.append('</tr>')

        return self._create_rows(json_obj) + row

    def _format_label(self, label) -> str:
        """Format label to translatable string."""
        return f'<td><b> {Project.statistic_key_to_label(label)} </b></td>'


class ProjectAdmin(ExportMixin, admin.ModelAdmin):
    """Admin interface definitions for Projects."""

    resource_classes = [ProjectResource, ProjectParticipantsResource]
    change_list_template = 'admin/change_list_ics_export.html'
    change_form_template = 'admin/project_change_form.html'

    list_display = (
        'title',
        'topic',
        'begin_date',
        'project_leader',
        'jugendmedienschutz',
        'democracy_project',
    )

    autocomplete_fields = [
        'project_category',
        'target_group',
        'project_leader',
        'media_education_supervisors',
        'participants',
    ]

    ordering = ('-begin_date',)
    search_fields = ('title', 'topic')
    search_help_text = _('title, topic')

    list_filter = (
        AutocompleteFilterFactory(_('Target Group'), 'target_group'),
        AutocompleteFilterFactory(_('Project Category'), 'project_category'),
        'jugendmedienschutz',
        'democracy_project',
        ('begin_date', DateTimeRangeFilter),
        YearFilter,
    )

    readonly_fields = ('id',)

    fieldsets = (
        (_('Project data'), {
            'fields': (
                'title',
                'topic',
                'duration',
                'begin_date',
                'end_date',
                'external_venue',
                'jugendmedienschutz',
                'democracy_project',
                'project_category',
                'target_group',
                'project_leader',
                'media_education_supervisors',
                'participants',
            )
        }),
        (_('Participant Statistic'), {
            'fields': (
                'statistic',
            )
        }),
        (_('Project ID'), {
            'fields': (
                'id',
            )
        }),
    )

    formfield_overrides = {
        models.JSONField: {'widget': StatisticWidget}
    }

    def get_urls(self):
        """Add the ics_export_view to the admin urls."""
        return super().get_urls() + [
            path(
                'calender_export',
                self.ics_export_view,
                name='calender_export',
            )
        ]

    def ics_export_view(self, request):
        """Export project dates as ics."""
        # This method belongs to the ExportMixin and creates a queryset from
        # the urls query string.
        queryset = self.get_export_queryset(request)
        return ics_export(queryset)


admin.site.register(Project, ProjectAdmin)
