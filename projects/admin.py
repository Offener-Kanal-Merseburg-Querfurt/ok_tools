from .models import Project
from .models import ProjectCategory
from .models import TargetGroup
from django.contrib import admin


admin.site.register(Project)
admin.site.register(ProjectCategory)
admin.site.register(TargetGroup)
