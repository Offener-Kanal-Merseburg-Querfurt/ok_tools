from django.db import models
from django.utils.translation import gettext_lazy as _
from licenses.models import LicenseRequest


class Contribution(models.Model):
    """
    Model representing a contribution.

    Each Contribution belongs to a license
    """

    license = models.ForeignKey(
        LicenseRequest,
        on_delete=models.CASCADE,
        verbose_name=_('License'),
        blank=False,
        null=False,
    )

    broadcast_date = models.DateTimeField(  # datetime
        _('Broadcast Date'),
        blank=False,
        null=False,
    )

    live = models.BooleanField(
        _('Is live'),
        blank=False,
        null=False,
    )

    def __str__(self) -> str:
        """Represent a contribution by its title and subtitle."""
        return str(self.license)

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Contribution')
        verbose_name_plural = _('Contributions')
