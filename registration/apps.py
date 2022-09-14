from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RegistrationConfig(AppConfig):
    """Configuration class for the application 'registration'."""

    name = 'registration'
    verbose_name = _('Registration')

    def ready(self):
        """Import Signals to set permissions on profile change."""
        from . import signals  # noqa F401
