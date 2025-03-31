from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from registration.models import Profile
import datetime
import logging


logger = logging.getLogger('django')

MAX_TITLE_LENGTH = 255


class YouthProtectionCategory(models.TextChoices):
    """Youth protection categories."""

    NONE = 'none', _('not necessary')
    FROM_12 = 'from_12', _('from 12')
    FROM_16 = 'from_16', _('from 16')
    FROM_18 = 'from_18', _('from 18')

    @classmethod
    def verbose_name(cls, value: str) -> str:
        """Return the verbose name to the given value."""
        for choice in cls.choices:
            if value == choice[0]:
                return choice[1]  # verbose name

        return ''


class Category(models.Model):
    """
    Model representing a category.

    Each License has a category.
    """

    name = models.CharField(
        _('Category'),
        blank=False,
        null=False,
        max_length=255,
        unique=True,
    )

    def __str__(self) -> str:
        """Represent category by its String."""
        return self.name

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Category')
        verbose_name_plural = _('Categories')


def default_category():
    """Provide the default Category."""
    return Category.objects.get_or_create(name=_('Not Selected'))[0]


class License(models.Model):
    """Model representing a (Beitragsfreistellung)."""

    title = models.CharField(
        _('Title'),
        blank=False,
        null=True,
        max_length=MAX_TITLE_LENGTH,
    )

    subtitle = models.CharField(
        _('Subtitle'),
        blank=True,
        null=True,
        max_length=MAX_TITLE_LENGTH,
    )

    description = models.TextField(
        _('Description'),
        blank=False,
        null=True,
    )

    further_persons = models.TextField(
        _('Further involved persons'),
        blank=True,
        null=True,
    )
    duration = models.DurationField(  # timedelta
        _('Duration'),
        help_text=_('Format: hh:mm:ss or mm:ss'),
        blank=True,
        null=False,
        default=datetime.timedelta(seconds=0),
    )

    suggested_date = models.DateTimeField(  # datetime
        _('Suggested broadcast date'),
        blank=True,
        null=True,
    )

    repetitions_allowed = models.BooleanField(
        _('Repetitions allowed'),
        blank=False,
        null=True,
    )

    media_authority_exchange_allowed = models.BooleanField(
        _('Media Authority exchange allowed in Saxony-Anhalt'),
        blank=False,
        null=True,
    )

    media_authority_exchange_allowed_other_states = models.BooleanField(
        _('Media Authority exchange allowed in other states than Saxony-Anhalt.'),
        blank=False,
        null=True,
    )

    youth_protection_necessary = models.BooleanField(
        _('Youth protection necessary'),
        blank=False,
        null=True,
    )

    youth_protection_category = models.CharField(
        _('Youth protection category'),
        max_length=255,
        blank=False,
        null=True,
        choices=YouthProtectionCategory.choices,
        default=YouthProtectionCategory.NONE,
    )

    store_in_ok_media_library = models.BooleanField(
        _('Store in OK media library'),
        blank=False,
        null=True,
    )

    created_at = models.DateTimeField(
        _('Created at'),
        auto_now_add=True,
    )

    # a visible identification number (not djangos id)
    number = models.IntegerField(
        _('Number'),
        default=1,
        unique=True,
        blank=False,
        null=False,
    )

    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        verbose_name=_('Profile'),
        blank=False,
        null=False,
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        default=default_category,
        verbose_name=_('Category'),
    )

    confirmed = models.BooleanField(
        _('Confirmed'),
        blank=False,
        null=False,
        default=False,
    )

    is_screen_board = models.BooleanField(
        _('Screen Board'),
        blank=False,
        null=False,
        default=False,
    )

    def __str__(self) -> str:
        """Licenses are represented by its titles."""
        if self.subtitle:
            return f'{self.title} - {self.subtitle}'
        else:
            return self.title or ""

    def clean(self) -> None:
        """Either the LR is a screen_board or the duration isn't null."""
        if self.is_screen_board:
            # it's a screen board, we are fine
            self.duration = timedelta(
                seconds=settings.SCREEN_BOARD_DURATION)
            return super().clean()

        if not self.duration:
            raise ValidationError(
                {'duration': _('Duration must not be null.')})

        return super().clean()

    @transaction.atomic
    def save(self, update_fields=None, *args, **kwargs) -> None:
        """
        Make confirmed Licenses not editable.

        Nevertheless the confirmed status itself should stay editable.
        """
        # Emulate an Autofield for number.
        if self.id is None:  # license is new created

            if (License.objects.filter(number=self.number) and
                    # number already exists
                    (last := License.objects.order_by('number')
                     .last())):
                i = last.number
                i += 1
                self.number = i

            return super().save(*args, **kwargs)

        old = License.objects.get(id=self.id)

        # editing is allowed if only action was to unconfirm license
        if old.confirmed and update_fields != ['confirmed']:
            logger.warning(
                f'Not saved {self} because it is already confirmed.')
            return

        return super().save(*args, **kwargs)

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('License')
        verbose_name_plural = _('Licenses')
