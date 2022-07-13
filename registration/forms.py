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
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
import logging


logger = logging.getLogger('django')


class RegisterForm(forms.ModelForm, ):
    """Form to register a user."""

    class Meta:
        """At the moment, the user only needs to provide an email address."""

        model = get_user_model()
        # TODO further personal Data needed
        fields = ('email',)


class ProfileForm(forms.ModelForm):
    """Form to register a profile."""

    email = forms.EmailField(label=_('Email address'))

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
        # TODO schwer zu testen, aber vielleicht für Nebenläufigkeitsprobleme
        # rlevant
        except UserModel.DoesNotExist:
            # TODO logging messages should be delivered to front end
            logger.error(f'User with E-Mail {to_email} does not exist.')
            raise
        except Profile.DoesNotExist:
            logger.warning(f'Profile for user {to_email} does not exist.')
            first_name = None

        context['first_name'] = ' '+first_name if first_name else ''

        super().send_mail(
            subject_template_name,
            email_template_name,
            context,
            from_email,
            to_email,
            html_email_template_name)
