from .ics_export import ics_export
from .models import MediaEducationSupervisor
from .models import Project
from .models import ProjectCategory
from .models import ProjectLeader
from .models import TargetGroup
from admin_searchable_dropdown.filters import AutocompleteFilterFactory
from django.contrib import admin
from django.urls import path
from django.utils.translation import gettext_lazy as _
from import_export import resources
from import_export.admin import ExportMixin
from ok_tools.admin import SanitizeGetParamsMixin
from import_export.fields import Field
from rangefilter.filters import DateRangeFilter
import datetime
import logging


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


class ProjectResource(resources.ModelResource):
    """Define the export for Projects."""

    def _f(field, name=None):
        """Shortcut for field creation."""
        return Field(attribute=field, column_name=name)

    title = _f('title', _('Title'))
    topic = _f('topic', _('Topic'))
    description = _f('description', _('Description'))
    date = _f('date', _('Date'))
    duration = _f('duration', _('Duration'))
    external_venue = _f('external_venue', _('External venue'))
    jugendmedienschutz = _f('jugendmedienschutz', _('Jugendmedienschutz'))
    target_group = _f('target_group__name', _('Target group'))
    project_category = _f('project_category__name', _('Project category'))
    project_leader = _f('project_leader__name', _('Project leader'))
    bis_6 = _f('tn_0_bis_6', _('bis 6 Jahre'))
    bis_10 = _f('tn_7_bis_10', _('7-10 Jahre'))
    bis_14 = _f('tn_11_bis_14', _('11-14 Jahre'))
    bis_18 = _f('tn_15_bis_18', _('15-18 Jahre'))
    bis_34 = _f('tn_19_bis_34', _('19-34 Jahre'))
    bis_50 = _f('tn_35_bis_50', _('35-50 Jahre'))
    bis_65 = _f('tn_51_bis_65', _('51-65 Jahre'))
    ueber_65 = _f('tn_ueber_65', _('über 65 Jahre'))
    no_age = _f('tni_age_not_given', _('ohne Angabe'))
    female = _f('tn_female', _('weiblich'))
    male = _f('tn_male', _('männlich'))
    diverse = _f('tn_diverse', _('diverse'))
    no_gender = _f('tn_gender_not_given', _('ohne Angabe'))
    supervisors = Field()

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

    parameter_name = 'date'

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
                    date__year=datetime.datetime.now().year)
            case 'last':
                return queryset.filter(
                    date__year=datetime.datetime.now().year-1)
            case _:
                msg = f'Invalid value {self.value()}.'
                logger.error(msg)
                raise ValueError(msg)


class ProjectAdmin(SanitizeGetParamsMixin, ExportMixin, admin.ModelAdmin):
    """Admin interface definitions for Projects."""

    resource_classes = [ProjectResource]
    change_list_template = 'admin/change_list_ics_export.html'

    list_display = (
        'title',
        'topic',
        'date',
        'project_leader',
        'jugendmedienschutz',
        'democracy_project',
    )

    autocomplete_fields = [
        'project_category',
        'target_group',
        'project_leader',
        'media_education_supervisors',
    ]

    ordering = ('-date',)
    search_fields = ('title', 'topic', 'description')
    search_help_text = _('title, topic, description')

    list_filter = (
        AutocompleteFilterFactory(_('Target Group'), 'target_group'),
        AutocompleteFilterFactory(_('Project Category'), 'project_category'),
        AutocompleteFilterFactory(_('Project leader'), 'project_leader'),
        'jugendmedienschutz',
        'democracy_project',
        ('date', DateRangeFilter),
        YearFilter,
    )

    fieldsets = (
        (_('Project data'), {
            'fields': (
                'title',
                'topic',
                'description',
                'date',
                'duration',
                'external_venue',
                'jugendmedienschutz',
                'democracy_project',
                'project_category',
                'target_group',
                'project_leader',
                'media_education_supervisors',
            )
        }),
        (_('Participant numbers - by age'), {
            'fields': (
                'tn_0_bis_6',
                'tn_7_bis_10',
                'tn_11_bis_14',
                'tn_15_bis_18',
                'tn_19_bis_34',
                'tn_35_bis_50',
                'tn_51_bis_65',
                'tn_ueber_65',
                'tn_age_not_given',
            )
        }),
        (_('Participant numbers - by gender'), {
            'fields': (
                'tn_female',
                'tn_male',
                'tn_diverse',
                'tn_gender_not_given',
            )
        }),
    )

    def get_urls(self):
        """Add the ics_export_view to the admin urls."""
        return super().get_urls() + [
            path(
                'calender_export',
                self.ics_export_view,
                name='calender_export',
            )
        ]

    # CAUTION: This view is reachable without any authentication
    def ics_export_view(self, request):
        """Export project dates as ics."""
        # This method belongs to the ExportMixin and creates a queryset from
        # the urls query string.
        queryset = self.get_export_queryset(request)
        return ics_export(queryset)


admin.site.register(Project, ProjectAdmin)
