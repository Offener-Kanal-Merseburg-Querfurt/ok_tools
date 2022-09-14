from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ContributionsConfig(AppConfig):
    """Configure contribution app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'contributions'
    verbose_name = _('Contributions')
