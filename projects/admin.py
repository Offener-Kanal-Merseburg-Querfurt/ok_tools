from .models import MediaEducationSupervisor
from .models import Project
from .models import ProjectCategory
from .models import ProjectLeader
from .models import TargetGroup

from django.contrib import admin


admin.site.register(MediaEducationSupervisor)
admin.site.register(Project)
admin.site.register(ProjectCategory)
admin.site.register(ProjectLeader)
admin.site.register(TargetGroup)
