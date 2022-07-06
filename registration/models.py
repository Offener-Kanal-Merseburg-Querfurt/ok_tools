from datetime import date
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField


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


class Profile(models.Model):
    """
    Model for a profil.

    A profil stores further informations about a user. Every profil
    belongs to a user.
    """

    # TODO auch so, dass kein OKUser existiert
    okuser = models.OneToOneField(OKUser, on_delete=models.CASCADE)

    first_name = models.CharField(blank=False, null=True, max_length=150)
    last_name = models.CharField(blank=False, null=True, max_length=150)

    class Gender(models.TextChoices):
        """The gender of the user."""

        NOT_GIVEN = 'none', _('Not Given')
        MALE = 'm', _('Male')
        FEMALE = 'f', _('Female')
        DIVERSE = 'd', _('Diverse')

    gender = models.CharField(
        max_length=4,
        choices=Gender.choices,
        default=Gender.NOT_GIVEN,
    )

    # phone (optional)
    phone_number = PhoneNumberField(blank=True, null=True)
    # mobile (optional)
    mobile_number = PhoneNumberField(blank=True, null=True)

    # birthday
    birthday = models.DateField(default=date.fromisoformat('1990-09-01'))

    # address (street, zipcode, location) mandatory
    street = models.CharField(null=True, max_length=95)
    house_number = models.CharField(null=True, max_length=20)
    zipcode = models.CharField(
        null=True, default=settings.ZIPCODE, max_length=5)
    city = models.CharField(null=True, default=settings.CITY, max_length=35)

    # was the profile validated by an employee
    verified = models.BooleanField(
        default=False,
        help_text=_('The profile data was verified by showing the ID to an'
                    ' employee.')
    )

    def __str__(self):
        """Represent Profile by first and last name."""
        return f'{self.first_name} {self.last_name}'
