from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class RentalConfig(AppConfig):
    """Django app configuration for the rental app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "rental"
    verbose_name = _("Rental")

    def ready(self):
        """Register signal handlers on app ready."""
        from . import signals  # noqa: F401
