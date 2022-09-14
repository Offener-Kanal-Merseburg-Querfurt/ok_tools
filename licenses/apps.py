from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LicensesConfig(AppConfig):
    """Configure licenses app."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'licenses'
    verbose_name = _('Licenses')
