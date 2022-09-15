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


def now():
    """Provide the current datetime for created_at."""
    return timezone.now()


def default_media_authority():
    """Provide the default MediaAuthority."""
    return MediaAuthority.objects.get_or_create(
        name=settings.OK_NAME_SHORT)[0]


class Profile(models.Model):
    """
    Model for a profil.

    A profil stores further informations about a user. Every profil
    belongs to a user.
    """

    okuser = models.OneToOneField(
        OKUser, on_delete=models.CASCADE, null=True, blank=True)

    first_name = models.CharField(
        _('first name'), blank=False, null=True, max_length=150)
    last_name = models.CharField(
        _('last name'), blank=False, null=True, max_length=150)

    class Gender(models.TextChoices):
        """The gender of the user."""

        NOT_GIVEN = 'none', _('Not Given')
        MALE = 'm', _('Male')
        FEMALE = 'f', _('Female')
        DIVERSE = 'd', _('Diverse')

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
        _('zipcode'), null=True, default=settings.ZIPCODE, max_length=5)
    city = models.CharField(
        _('city'), null=True, default=settings.CITY, max_length=35)

    # was the profile validated by an employee
    verified = models.BooleanField(
        _('verified'),
        default=False,
        help_text=_('The profile data was verified by showing the ID to an'
                    ' employee.')
    )

    created_at = models.DateTimeField(default=now)

    media_authority = models.ForeignKey(
        MediaAuthority,
        on_delete=models.CASCADE,
        default=default_media_authority,
    )

    member = models.BooleanField(
        _('member'),
        default=False,
        blank=False,
        null=False,
    )

    def __str__(self):
        """Represent Profile by first and last name."""
        return f'{self.first_name} {self.last_name}'

    class Meta:
        """Define permission to log in."""

        permissions = [
            (
                "verified",
                "Can access functionalities for verified users"
            )
        ]
