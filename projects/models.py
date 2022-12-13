from django.db import models
from django.utils.translation import gettext_lazy as _
from registration.models import Gender
import uuid


MAX_STRING_LENGTH = 255


class ProjectParticipant(models.Model):
    """
    Model representing participants of a project.

    They are described by name, age and gender.
    """

    name = models.CharField(
        _('Full name'),
        blank=False,
        null=False,
        max_length=MAX_STRING_LENGTH,
    )

    age = models.IntegerField(
        _('Age'),
        blank=True,
        null=True,
    )

    gender = models.CharField(
        _('Gender'),
        max_length=4,
        choices=Gender.choices,
        default=Gender.NOT_GIVEN,
    )

    def __str__(self) -> str:
        """Represent participant by name, age and gender."""
        return f'{self.name} ({self.age}, {Gender.verbose_name(self.gender)})'

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Project Participant')
        verbose_name_plural = _('Project Participants')


class ProjectLeader(models.Model):
    """
    Model representing a project leader.

    Each Project has one or more project leaders.
    """

    name = models.CharField(
        _('Full name'),
        blank=False,
        null=False,
        max_length=MAX_STRING_LENGTH
    )

    def __str__(self) -> str:
        """Represent category by its String."""
        return self.name

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Project leader')
        verbose_name_plural = _('Project leaders')


class MediaEducationSupervisor(models.Model):
    """
    Model representing a media education supervisor.

    Each Project has one or more media education supervisors.
    """

    name = models.CharField(
        _('Full name'),
        blank=False,
        null=False,
        max_length=MAX_STRING_LENGTH
    )

    def __str__(self) -> str:
        """Represent category by its String."""
        return self.name

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Media education supervisor')
        verbose_name_plural = _('Media education supervisors')


class ProjectCategory(models.Model):
    """
    Model representing a project category.

    Each Project has a category.
    """

    name = models.CharField(
        _('Project category'),
        blank=False,
        null=False,
        max_length=MAX_STRING_LENGTH
    )

    def __str__(self) -> str:
        """Represent category by its String."""
        return str(self.name)

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Project category')
        verbose_name_plural = _('Project categories')

        # used by the admin_searchable_dropdown filter in the admin view
        ordering = ['id']


class TargetGroup(models.Model):
    """
    Model representing a target group.

    Each Project has a target group.
    """

    name = models.CharField(
        _('Target group'),
        blank=False,
        null=False,
        max_length=MAX_STRING_LENGTH
    )

    def __str__(self) -> str:
        """Represent target group by its String."""
        return str(self.name)

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Target group')
        verbose_name_plural = _('Target groups')

        # used by the admin_searchable_dropdown filter in the admin view
        ordering = ['id']


def default_category():
    """Provide the default Category."""
    return ProjectCategory.objects.get_or_create(name=_('Not Selected'))[0]


def default_target_group():
    """Provide the default target group."""
    return TargetGroup.objects.get_or_create(name=_('Not Selected'))[0]


class Project(models.Model):
    """Model for the project."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    title = models.CharField(
        _('Project title'),
        blank=False,
        null=False,
        max_length=MAX_STRING_LENGTH,
    )

    topic = models.CharField(
        _('Topic'),
        blank=True,
        null=True,
        max_length=MAX_STRING_LENGTH,
    )
    duration = models.DurationField(  # timedelta
        _('Duration'),
        help_text=_('Total amount of time spend.'),
        blank=True,
        null=True,
    )

    begin_date = models.DateTimeField(  # datetime
        _('Start date'),
        blank=False,
        null=False,
    )
    end_date = models.DateTimeField(  # datetime
        _('End date'),
        blank=False,
        null=False,
    )

    external_venue = models.BooleanField(
        _('External venue'),
        blank=False,
        null=False,
    )

    jugendmedienschutz = models.BooleanField(
        _('Jugendmedienschutz'),
        blank=False,
        null=False,
    )

    democracy_project = models.BooleanField(
        _('Democracy project'),
        blank=False,
        null=False,
        default=False,
    )

    target_group = models.ForeignKey(
        TargetGroup,
        on_delete=models.CASCADE,
        default=default_target_group,
        verbose_name=_('Target group'),
    )

    project_category = models.ForeignKey(
        ProjectCategory,
        on_delete=models.CASCADE,
        default=default_category,
        verbose_name=_('Project category'),
    )

    project_leader = models.ForeignKey(
        ProjectLeader,
        on_delete=models.CASCADE,
        blank=False,
        null=False,
        verbose_name=_('Project leader'),
    )

    media_education_supervisors = models.ManyToManyField(
        MediaEducationSupervisor,
        blank=False,
        verbose_name=_('Media education supervisors'),
    )

    participants = models.ManyToManyField(
        ProjectParticipant,
        blank=False,
        verbose_name=('Project Participants'),
    )

    @classmethod
    def statistic_key_to_label(cls, key):
        """Map the keys of the statistic object to translatable labels."""
        match key:
            case '0_bis_6':
                return _('Bis 6 Jahre')
            case '7_bis_10':
                return _('7-10 Jahre')
            case '11_bis_14':
                return _('11-14 Jahre')
            case '15_bis_18':
                return _('15-18 Jahre')
            case '19_bis_34':
                return _('19-34 Jahre')
            case '35_bis_50':
                return _('35-50 Jahre')
            case '51_bis_65':
                return _('51-65 Jahre')
            case 'ueber_65':
                return _('Über 65 Jahre')
            case 'not_given':
                return _('Ohne Angabe')
            case _:
                raise ValueError(f'Unknown key {key}!')

    def statistic_default():
        """Provide default JSON-Structure."""
        return {
            # age, male, female, diverse, no gender given
            '0_bis_6': [0, 0, 0, 0],
            '7_bis_10': [0, 0, 0, 0],
            '11_bis_14': [0, 0, 0, 0],
            '15_bis_18': [0, 0, 0, 0],
            '19_bis_34': [0, 0, 0, 0],
            '35_bis_50': [0, 0, 0, 0],
            '51_bis_65': [0, 0, 0, 0],
            'ueber_65': [0, 0, 0, 0],
            'not_given': [0, 0, 0, 0],
        }

    statistic = models.JSONField(
        _('Gender and Age'),
        null=False,
        blank=True,
        default=statistic_default,
    )

    def __str__(self) -> str:
        """Represent a profile by its title."""
        return self.title

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Project')
        verbose_name_plural = _('Projects')
