from .models import Profile
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.forms.widgets import DateInput


class RegisterForm(forms.ModelForm):
    """Form to register a user."""

    class Meta:
        """At the moment, the user only needs to provide an email address."""

        model = get_user_model()
        # TODO further personal Data needed
        fields = ('email',)


class ProfileForm(forms.ModelForm):
    """Form to register a profile."""

    email = forms.EmailField()

    class Meta:
        """General data about the user, stored in the profile."""

        model = Profile
        fields = ('first_name', 'last_name', 'gender', 'phone_number',
                  'mobile_number', 'birthday', 'street', 'house_number',
                  'zipcode', 'city')
        widgets = {
            # TODO nicer input
            'birthday': DateInput(format=settings.DATE_INPUT_FORMAT)
        }
