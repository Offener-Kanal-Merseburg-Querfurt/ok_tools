from django.apps import AppConfig


class RegistrationConfig(AppConfig):
    """Configuration class for the application 'registration'."""

    name = 'registration'

    def ready(self):
        """Import Signals to set permissions on profile change."""
        from . import signals  # noqa F401
