from .models import LicenseRequest
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.forms import widgets
from django.utils.translation import gettext_lazy as _
from durationwidget.widgets import TimeDurationWidget


class CreateLicenseRequestForm(forms.ModelForm):
    """Form to create a license."""

    class Meta:
        """The okuser field is not visible for the user."""

        model = LicenseRequest
        exclude = ('okuser',)

        # TODO better widgets
        widgets = {
            'duration': TimeDurationWidget(show_days=False),
            'suggested_date': widgets.DateTimeInput(
                attrs={'input_type': 'datetime'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'title',
            'subtitle',
            'description',
            'category',
            'duration',
            'suggested_date',
            'repetitions_allowed',
            'media_authority_exchange_allowed',
            'youth_protection_necessary',
            'store_in_ok_media_library',
            Submit('create', _('Create License'))
        )
