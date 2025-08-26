from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError(_('The given email must be set'))
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        return self._create_user(email, password, **extra_fields)


class OKUser(AbstractUser):
    """
    Model for a User.

    A User don't has a username and gets identified by his/her email
    address. Nevertheless the email is optional due to administrative
    reasons of the OKs.
    """

    # If a User specifies an email address it needs to be unique
    username = None
    email = models.EmailField(
        _('email address'), unique=True, null=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self) -> str:
        """Represent OKUser by e-mail address."""
        return self.email

    class Meta:
        """Define the message IDs."""

        verbose_name = _('User')
        verbose_name_plural = _('Users')


class MediaAuthority(models.Model):
    """
    Model for a MediaAuthority.

    Every Profile belongs to a MediaAuthority. The default authority name of
    the default authority is defined in settings.py by OK_NAME_SHORT.
    """

    name = models.CharField(
        _('Media Authority'),
        default=settings.OK_NAME_SHORT,
        max_length=150,
        unique=True)

    def __str__(self) -> str:
        """Represent a MediaAuthority by its name."""
        return self.name

    class Meta:
        """Define the message IDs."""

        verbose_name = _('Media Authority')
        verbose_name_plural = _('Media Authorities')


def default_media_authority():
    """Provide the default MediaAuthority."""
    return MediaAuthority.objects.get_or_create(
        name=settings.OK_NAME_SHORT)[0]


class Gender(models.TextChoices):
    """The gender of the user."""

    NOT_GIVEN = 'none', _('not given')
    MALE = 'm', _('male')
    FEMALE = 'f', _('female')
    DIVERSE = 'd', _('diverse')

    @classmethod
    def verbose_name(cls, value: str) -> str:
        """Return the verbose name to the given value."""
        for choice in cls.choices:
            if value == choice[0]:
                return choice[1]  # verbose name

        return ''


class Profile(models.Model):
    """
    Model for a profil.

    A profil stores further informations about a user. Every profil
    belongs to a user.
    """

    okuser = models.OneToOneField(
        OKUser,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('User'),
    )

    first_name = models.CharField(
        _('first name'), blank=False, null=True, max_length=150)
    last_name = models.CharField(
        _('last name'), blank=False, null=True, max_length=150)

    gender = models.CharField(
        _('gender'),
        max_length=4,
        choices=Gender.choices,
        default=Gender.NOT_GIVEN,
    )

    # phone number as char field due to missing support from zope.testbrowser
    # phone (optional)
    phone_number = models.CharField(
        _('phone number'), blank=True, null=True, max_length=30)
    # mobile (optional)
    mobile_number = models.CharField(
        _('mobile number'), blank=True, null=True, max_length=30)

    # birthday
    birthday = models.DateField(
        _('birthday'), blank=False, null=True)

    # address (street, zipcode, location) mandatory
    street = models.CharField(_('street'), null=True, max_length=95)
    house_number = models.CharField(
        _('house number'), null=True, max_length=20)
    zipcode = models.CharField(
        _('zipcode'), null=True, max_length=5)
    city = models.CharField(
        _('city'), null=True, max_length=35)

    # was the profile validated by an employee
    verified = models.BooleanField(
        _('verified'),
        default=False,
        help_text=_('The profile data was verified by showing the ID to an'
                    ' employee.')
    )

    created_at = models.DateTimeField(
        _('created at'),
        default=timezone.now,
    )

    media_authority = models.ForeignKey(
        MediaAuthority,
        on_delete=models.CASCADE,
        default=default_media_authority,
        verbose_name=_('Media Authority'),
    )

    member = models.BooleanField(
        _('member'),
        default=False,
        blank=False,
        null=False,
    )

    comment = models.TextField(
        _('comment'),
        null=True,
        blank=True,
    )

    def __str__(self):
        """Represent Profile by first and last name."""
        return f'{self.first_name} {self.last_name}'

    class Meta:
        """Define the message IDs."""

        verbose_name = _('Profile')
        verbose_name_plural = _('Profiles')


class Notification(models.Model):
    """Model for system notifications that can be displayed to users."""

    NOTIFICATION_TYPES = [
        ('info', _('Information')),
        ('success', _('Success')),
        ('warning', _('Warning')),
        ('danger', _('Danger')),
    ]

    ICON_CHOICES = [
        ('info-circle', _('Info Circle')),
        ('check-circle', _('Check Circle')),
        ('exclamation-triangle', _('Exclamation Triangle')),
        ('exclamation-circle', _('Exclamation Circle')),
        ('clock', _('Clock')),
        ('bell', _('Bell')),
        ('broadcast', _('Broadcast')),
        ('star', _('Star')),
        ('gear', _('Gear')),
        ('shield-check', _('Shield Check')),
    ]

    title = models.CharField(
        _('Title'),
        max_length=200,
        help_text=_('Short title for the notification')
    )

    message = models.TextField(
        _('Message'),
        help_text=_('Main notification text')
    )

    notification_type = models.CharField(
        _('Type'),
        max_length=10,
        choices=NOTIFICATION_TYPES,
        default='info',
        help_text=_('Notification type determines color and style')
    )

    icon = models.CharField(
        _('Icon'),
        max_length=20,
        choices=ICON_CHOICES,
        default='info-circle',
        help_text=_('Bootstrap Icons icon name')
    )

    is_active = models.BooleanField(
        _('Active'),
        default=True,
        help_text=_('Only active notifications are displayed to users')
    )

    priority = models.IntegerField(
        _('Priority'),
        default=1,
        help_text=_('Higher priority notifications appear first (1-10)')
    )

    start_date = models.DateTimeField(
        _('Start Date'),
        default=timezone.now,
        help_text=_('When to start showing this notification')
    )

    end_date = models.DateTimeField(
        _('End Date'),
        null=True,
        blank=True,
        help_text=_('When to stop showing this notification (optional)')
    )

    created_at = models.DateTimeField(
        _('Created At'),
        auto_now_add=True
    )

    created_by = models.ForeignKey(
        OKUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('Created By'),
        help_text=_('Admin who created this notification (auto-filled)')
    )

    def __str__(self):
        """Represent Notification by title."""
        return f"{self.title} ({self.get_notification_type_display()})"

    class Meta:
        """Define the message IDs."""

        verbose_name = _('Notification')
        verbose_name_plural = _('Notifications')
        ordering = ['-priority', '-created_at']

    def is_currently_active(self):
        """Check if notification should be displayed now."""
        now = timezone.now()
        if not self.is_active:
            return False
        if now < self.start_date:
            return False
        if self.end_date and now > self.end_date:
            return False
        return True
