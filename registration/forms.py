from .helper import toc_href
from .models import Profile
from bootstrap_datepicker_plus.widgets import DatePickerInput
from crispy_forms.helper import FormHelper
from crispy_forms.layout import ButtonHolder
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.conf import settings
from django.contrib.auth import forms as auth_forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import _unicode_ci_compare
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
import logging


logger = logging.getLogger('django')


class RegisterForm(forms.ModelForm, ):
    """Form to register a user."""

    class Meta:
        """At the moment, the user only needs to provide an email address."""

        model = get_user_model()
        fields = ('email',)


class ProfileForm(forms.ModelForm):
    """Form to register a profile."""

    email = forms.EmailField(label=_('Email address'))
    toc_agreement = forms.BooleanField(
        # TODO circular import:
        # toc-href -> urls -> RegisterView -> ProfileForm -> toc_href ...
        label='Please accept the ' + toc_href()
    )

    birthday = forms.DateField(
        label=_('Birthday'),
        input_formats=[settings.DATE_INPUT_FORMATS],
        widget=DatePickerInput(format=settings.DATE_INPUT_FORMATS)
    )

    class Meta:
        """General data about the user, stored in the profile."""

        model = Profile
        fields = ('first_name', 'last_name', 'gender', 'phone_number',
                  'mobile_number', 'street', 'house_number',
                  'zipcode', 'city')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'id-registerForm'
        self.helper.form_method = 'post'
        self.helper.form_action = 'register'

        self.helper.form_class = 'form-horizontal'

        self.helper.layout = Layout(
            'email',
            'first_name',
            'last_name',
            'gender',
            'phone_number',
            'mobile_number',
            'birthday',
            'street',
            'house_number',
            'zipcode',
            'city',
            'toc_agreement',
            ButtonHolder(
                Submit('submit', _('Register')),
            )
        )


class PasswordResetForm(auth_forms.PasswordResetForm):
    """Modified form to add first_name to sended mail."""

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        """Send the mail including the first name of the user."""
        UserModel = get_user_model()

        try:
            user = UserModel.objects.get(Q(email__iexact=to_email))
            profile = Profile.objects.get(okuser=user)
            first_name = profile.first_name
        except UserModel.DoesNotExist:
            logger.error(f'User with E-Mail {to_email} does not exist.')
            raise
        except Profile.DoesNotExist:
            logger.warning(f'Profile for user {to_email} does not exist.')
            first_name = None

        context['first_name'] = ' '+first_name if first_name else ''
        # TODO not hard coded
        context['domain'] = 'localhost:8000'

        super().send_mail(
            subject_template_name,
            email_template_name,
            context,
            from_email,
            to_email,
            html_email_template_name)

    # overwrite so also user that do not have password yet can reset password
    # copied from https://github.com/django/django/blob/d4c5d2b52c897ccc07f04482d3f42f976a79223c/django/contrib/auth/forms.py#L286  # noqa E501
    def get_users(self, email):
        """Given an email, return matching user(s) who should receive a reset.

        This allows subclasses to more easily customize the default policies
        that prevent inactive users and users with unusable passwords from
        resetting their password.
        """
        UserModel = get_user_model()
        email_field_name = UserModel.get_email_field_name()
        active_users = UserModel._default_manager.filter(
            **{
                "%s__iexact" % email_field_name: email,
                "is_active": True,
            }
        )
        return (
            u
            for u in active_users
            if _unicode_ci_compare(email, getattr(u, email_field_name))
        )
