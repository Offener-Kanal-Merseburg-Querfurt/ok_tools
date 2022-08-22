from .models import MediaEducationSupervisor
from .models import Project
from .models import ProjectCategory
from .models import ProjectLeader
from .models import TargetGroup
from django.contrib import admin
from django.utils.translation import gettext_lazy as _


admin.site.register(MediaEducationSupervisor)
admin.site.register(ProjectCategory)
admin.site.register(ProjectLeader)
admin.site.register(TargetGroup)


class ProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'topic', 'begin_date', 'project_leader')
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
                'media_education_supervisor'
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
