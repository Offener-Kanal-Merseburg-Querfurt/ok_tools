from django.db import models
from django.utils.translation import gettext_lazy as _



MAX_TITLE_LENGTH = 255


class ProjectLeader(models.Model):
    """
    Model representing a project leader.

    Each Project has one or more project leaders.
    """

    name = models.CharField(
        _('Full name'),
        blank=False,
        null=True,
        max_length=255
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
        null=True,
        max_length=255
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
        null=True,
        max_length=255
    )

    def __str__(self) -> str:
        """Represent category by its String."""
        return self.name

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Project category')
        verbose_name_plural = _('Project categories')



class TargetGroup(models.Model):
    """
    Model representing a target group.

    Each Project has a target group.
    """

    name = models.CharField(
        _('Target group'),
        blank=False,
        null=True,
        max_length=255
    )

    def __str__(self) -> str:
        """Represent target group by its String."""
        return self.name

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Target group')
        verbose_name_plural = _('Target groups')




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
        max_length=MAX_TITLE_LENGTH,
    )

    topic = models.CharField(
        _('Topic'),
        blank=True,
        null=True,
        max_length=MAX_TITLE_LENGTH,
    )
    duration = models.DurationField(  # timedelta
        _('Duration'),
        blank=False,
        null=False,
    )

    begin_date = models.DateTimeField(  # datetime
        _('Start date'),
        blank=True,
        null=True,
    )
    end_date = models.DateTimeField(  # datetime
        _('End date'),
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

    target_group = models.ForeignKey(
        TargetGroup,
        on_delete=models.CASCADE,
        default=default_target_group
    )

    project_category = models.ForeignKey(
        ProjectCategory,
        on_delete=models.CASCADE,
        default=default_category
    )

    project_leader = models.ForeignKey(
        ProjectLeader,
        on_delete=models.CASCADE,
        blank=False,
        null=False,
    )

    media_education_supervisor = models.ForeignKey(
        MediaEducationSupervisor,
        on_delete=models.CASCADE,
        default=default_category
    )



    def __str__(self) -> str:
        """Licenses are represented by its titles."""
        if self.topic:
            return f'{self.title} - {self.topic}'
        else:
            return self.title

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Project')
        verbose_name_plural = _('Projects')

