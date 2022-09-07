from .models import Profile
from bootstrap_datepicker_plus.widgets import DatePickerInput
from crispy_forms.bootstrap import FormActions
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML
from crispy_forms.layout import ButtonHolder
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.conf import settings
from django.contrib.auth import forms as auth_forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import _unicode_ci_compare
from django.db.models import Q
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
import logging


logger = logging.getLogger('django')


class UserDataForm(forms.ModelForm):
    """Form to display user data which maybe can be changed by user."""

    email = forms.EmailField(label=_('Email address'))

    class Meta:
        """
        Excluded fields.

        The fields verified, okuser and media_authority are not shown to the
        user.
        """

        model = Profile
        exclude = ('verified', 'okuser', 'media_autority', 'created_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
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
            HTML('''
                 {{% if user.profile.verified %}}
                 <p>
                    {}
                 </p>
                 {{% endif %}}
                 '''.format(_('Your profile is already verified. To change '
                              'further data please contact an employee.'))
                 ),
            FormActions(
                Submit('submit', _('Submit changes')),
                HTML("""
                     {% load i18n %}
                     <a class="btn btn-outline-primary"
                     href="{% url 'registration:print_registration' %}">
                        {%translate 'Print registration form'%}
                     </a>
                     """
                     )
            )
        )


class ProfileForm(forms.ModelForm):
    """Form to register a profile."""

    email = forms.EmailField(label=_('Email address'))
    privacy_agreement = forms.BooleanField(
        label=_('I accept')
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
            HTML(_privacy_policy()),
            'privacy_agreement',
            ButtonHolder(
                Submit('submit', _('Register')),
            )
        )


def _privacy_policy() -> str:
    return '''
    <p> {}
        <a href="{}" target="_blank">{}</a>
    </p>
    '''.format(
        _('Please accept our '),
        reverse_lazy('privacy_policy'),
        _('privacy policy')
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
