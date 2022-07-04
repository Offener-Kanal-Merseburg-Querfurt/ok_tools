from django import forms
from django.contrib.auth import get_user_model


class RegisterForm(forms.ModelForm):
    """Form to register a user."""

    class Meta:
        """At the moment, the user only needs to provide an email address."""

        model = get_user_model()
        # TODO further personal Data needed
        fields = ('email',)
