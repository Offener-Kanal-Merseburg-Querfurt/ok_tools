from .models import Profile
from bootstrap_datepicker_plus.widgets import DatePickerInput
from crispy_forms.helper import FormHelper
from crispy_forms.layout import ButtonHolder
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model


class RegisterForm(forms.ModelForm, ):
    """Form to register a user."""

    class Meta:
        """At the moment, the user only needs to provide an email address."""

        model = get_user_model()
        # TODO further personal Data needed
        fields = ('email',)


class ProfileForm(forms.ModelForm):
    """Form to register a profile."""

    email = forms.EmailField()

    birthday = forms.DateField(
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

        self.helper.form_class = 'form-horizontal'  # form-control

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
                Submit('submit', 'Register'),
            )
        )
