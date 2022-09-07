from .disa_import import validate
from datetime import datetime
from django.core.validators import FileExtensionValidator
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


class DisaImport(models.Model):
    """
    Model representing the DISA-Import.

    The Contributions get imported from a xlsx-file.
    """

    def timestamp_path(instance, filename):
        """Create a path based on the current timestamp."""
        now: datetime = datetime.now()
        return (f'{now.year}/{now.month}/{now.day}/{now.hour}-{now.minute}-'
                f'{now.second}-{now.microsecond}.xlsx')

    file = models.FileField(
        verbose_name=_('DISA export file'),
        upload_to=timestamp_path,
        validators=[
            FileExtensionValidator(allowed_extensions=['xlsx']),
        ],
        blank=False,
        null=False,
    )

    def clean(self) -> None:
        """Validate the uploaded file."""
        validate(self.file)
        return super().clean()

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('DISA-Import')
        verbose_name_plural = _('DISA-Imports')
