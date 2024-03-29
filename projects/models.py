from django import forms
from django.db import models
from django.utils.translation import gettext_lazy as _


MAX_STRING_LENGTH = 255


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

    description = models.TextField(
        _('Description'),
        blank=False,
        null=True,
    )

    date = models.DateField(  # date
        _('Date'),
        blank=False,
        null=False,
    )

    duration = models.DurationField(  # timedelta
        _('Duration'),
        help_text=_('Format: hh:mm:ss or mm:ss'),
        blank=True,
        null=True,
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
        blank=True,
        verbose_name=_('Media education supervisors'),
    )

    tn_0_bis_6 = models.IntegerField(
        _('bis 6 Jahre'),
        blank=False,
        null=False,
        default=0
    )
    tn_7_bis_10 = models.IntegerField(
        _('7-10 Jahre'),
        blank=False,
        null=False,
        default=0
    )
    tn_11_bis_14 = models.IntegerField(
        _('11-14 Jahre'),
        blank=False,
        null=False,
        default=0
    )
    tn_15_bis_18 = models.IntegerField(
        _('15-18 Jahre'),
        blank=False,
        null=False,
        default=0
    )
    tn_19_bis_34 = models.IntegerField(
        _('19-34 Jahre'),
        blank=False,
        null=False,
        default=0
    )
    tn_35_bis_50 = models.IntegerField(
        _('35-50 Jahre'),
        blank=False,
        null=False,
        default=0
    )
    tn_51_bis_65 = models.IntegerField(
        _('51-65 Jahre'),
        blank=False,
        null=False,
        default=0
    )
    tn_ueber_65 = models.IntegerField(
        _('über 65 Jahre'),
        blank=False,
        null=False,
        default=0
    )
    tn_age_not_given = models.IntegerField(
        _('ohne Angabe'),
        blank=False,
        null=False,
        default=0
    )

    tn_female = models.IntegerField(
        _('weiblich'),
        blank=False,
        null=False,
        default=0
    )
    tn_male = models.IntegerField(
        _('männlich'),
        blank=False,
        null=False,
        default=0
    )
    tn_gender_not_given = models.IntegerField(
        _('ohne Angabe'),
        blank=False,
        null=False,
        default=0
    )
    tn_diverse = models.IntegerField(
        _('diverse'),
        blank=False,
        null=False,
        default=0,
    )

    def clean(self):
        """Validate participants by age agains participants by gender."""
        tn_age_sum = sum([
            self.tn_0_bis_6, self.tn_7_bis_10, self.tn_11_bis_14,
            self.tn_15_bis_18, self.tn_19_bis_34, self.tn_35_bis_50,
            self.tn_51_bis_65, self.tn_ueber_65])
        tn_gender_sum = sum([
            self.tn_female, self.tn_male,
            self.tn_gender_not_given, self.tn_diverse])
        if tn_age_sum != tn_gender_sum:
            raise forms.ValidationError(
                _('The sum of participants by age (%(age)s) does not '
                  'match the sum of participants by gender (%(gender)s).'
                  ' Please correct your data.') % {
                      'age': tn_age_sum,
                      'gender': tn_gender_sum,
                }
            )

    def __str__(self) -> str:
        """Represent a profile by its title."""
        return self.title

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Project')
        verbose_name_plural = _('Projects')
