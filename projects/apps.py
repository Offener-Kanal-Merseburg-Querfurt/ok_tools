from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ProjectsConfig(AppConfig):
    """Configure projects app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'projects'
    verbose_name = _('Projects')
