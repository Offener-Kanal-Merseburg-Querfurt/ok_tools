from .models import MediaEducationSupervisor
from .models import Project
from .models import ProjectCategory
from .models import ProjectLeader
from .models import TargetGroup
from admin_searchable_dropdown.filters import AutocompleteFilterFactory
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from import_export import resources
from import_export.admin import ExportMixin
from import_export.fields import Field
from rangefilter.filters import DateTimeRangeFilter
import datetime
import logging


logger = logging.getLogger('django')

admin.site.register(MediaEducationSupervisor)
admin.site.register(ProjectLeader)


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
    duration = _f('duration', _('Duration'))
    begin_date = _f('begin_date', _('Start date'))
    end_date = _f('end_date', _('End date'))
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
    diverse = _f('tn_divers', _('diverse'))
    no_gender = _f('tn_gender_not_given', _('ohne Angabe'))
    supervisors = Field()

    class Meta:
        """Define meta properties for the Project export."""

        model = Project
        fields = []

    def dehydrate_supervisors(self, project):
        """Convert all supervisors to one string."""
        return ', '.join(
            [str(x) for x in project.media_education_supervisors.all()])


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


class ProjectAdmin(ExportMixin, admin.ModelAdmin):
    """Admin interface definitions for Projects."""

    resource_class = ProjectResource

    list_display = (
        'title',
        'topic',
        'begin_date',
        'project_leader',
        'jugendmedienschutz',
    )

    ordering = ('-begin_date',)
    search_fields = ('title', 'topic')
    search_help_text = _('title, topic')

    list_filter = (
        AutocompleteFilterFactory(_('Target Group'), 'target_group'),
        AutocompleteFilterFactory(_('Project Category'), 'project_category'),
        'jugendmedienschutz',
        ('begin_date', DateTimeRangeFilter),
        YearFilter,
    )

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
                'project_category',
                'target_group',
                'project_leader',
                'media_education_supervisors'
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
                'tn_age_not_given')
        }),
        (_('Participant numbers - by gender'), {
            'fields': (
                'tn_female',
                'tn_male',
                'tn_gender_not_given',)
        }),
    )


admin.site.register(Project, ProjectAdmin)
