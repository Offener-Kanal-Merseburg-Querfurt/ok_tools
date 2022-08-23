from .models import LicenseRequest
from bootstrap_datepicker_plus.widgets import DatePickerInput
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML
from crispy_forms.layout import Field
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.conf import settings
from django.forms.utils import ErrorDict
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
            'suggested_date': DatePickerInput(
                format=settings.DATE_INPUT_FORMATS),
            'further_persons': forms.Textarea(
                attrs={'style': 'max-height: 4em'})
        }

    def is_valid(self) -> bool:
        """If the LR is a screen_board, duration is not required."""
        if (self.errors == {'duration': ['This field is required.']} and
                self.instance.is_screen_board):
            self._errors = ErrorDict()
            return self.is_bound

        return super().is_valid()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'title',
            'subtitle',
            'description',
            'further_persons',
            'category',
            HTML(_screen_board_js()),
            Field('is_screen_board', onclick="showDuration()"),
            'duration',
            'suggested_date',
            'repetitions_allowed',
            'media_authority_exchange_allowed',
            'youth_protection_necessary',
            'store_in_ok_media_library',
            Submit('save', _('Save'))
        )


def _screen_board_js() -> str:
    return '''
        <script>
        function showDuration() {
            element = document.getElementById('div_id_duration')
            if (!document.getElementById("id_is_screen_board").checked){
                element.style.display = "initial"
            } else {
                element.style.display = "none"
            }
            // document.getElementById().remove()
        }
        window.onload = function(){ showDuration() }
        </script>
   '''
