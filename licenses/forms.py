from .models import License
from .models import YouthProtectionCategory
from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML
from crispy_forms.layout import Field
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from datetime import timedelta
from django import forms
from django.utils.translation import gettext_lazy as _
import logging
import re


logger = logging.getLogger('django')


class CreateLicenseForm(forms.ModelForm):
    """Form to create a license."""

    class Meta:
        """The okuser field is not visible for the user."""

        model = License
        exclude = ('profile', 'confirmed', 'number')
        widgets = {
            'youth_protection_necessary': forms.Select(attrs={'id': 'id_youth_protection'}),
            'youth_protection_category': forms.Select(attrs={'id': 'id_youth_protection_category'}),
        }

        # TODO better widgets
        widgets = {
            'duration': forms.widgets.TimeInput,
            'suggested_date': forms.DateInput(attrs={"type": "date"}),
            'further_persons': forms.Textarea(
                attrs={'style': 'max-height: 4em'})
        }

    def is_valid(self) -> bool:
        """If the LR is a screen_board, duration is not required."""
        if self.data.get('is_screen_board'):
            # it's a screen board, we are fine
            return super().is_valid()

        # Convert youth_protection to boolean
        youth_protection = self.data.get('youth_protection_necessary') in ['true', 'True', 'Ja', True]
        if youth_protection:  # If youth protection is necessary
            youth_category = self.data.get('youth_protection_category')
            if youth_category == YouthProtectionCategory.NONE:
                self.add_error(
                    'youth_protection_category',
                    _('If youth protection is necessary, you have to choose a youth protection category.')
                )

        # Validate duration format
        duration = self.data.get('duration') or ""
        hh_mm_ss = r'\d{2}:\d{2}:\d{2}'
        mm_ss = r'\d{2}:\d{2}'
        if (not re.fullmatch(hh_mm_ss, duration) and
                not re.fullmatch(mm_ss, duration)):
            # duration format is not valid
            self.add_error(
                'duration',
                _('Invalid format. Please use the format hh:mm:ss or mm:ss.')
            )
            return super().is_valid() and False  # to collect further errors

        times = duration.split(':')
        if re.fullmatch(hh_mm_ss, duration):
            datetime = timedelta(
                hours=int(times[0]),
                minutes=int(times[1]),
                seconds=int(times[2])
            )
        else:
            assert re.fullmatch(mm_ss, duration)
            datetime = timedelta(
                minutes=int(times[0]),
                seconds=int(times[1]),
            )

        if not datetime:
            # the duration format is valid but duration is 0
            self.add_error('duration', _('The duration field is required.'))
            return super().is_valid and False  # to collect further errors

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
            'media_authority_exchange_allowed_other_states',
            'youth_protection_necessary',
            'youth_protection_category',
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
        <style>

            #div_id_youth_protection_category .asteriskField {
        display: none;
        }
        </style>

   '''


class RangeNumericForm(forms.Form):
    """A form for the numeric filter."""

    name = None

    def __init__(self, *args, **kwargs):
        """Initialize the form."""
        self.name = kwargs.pop('name')
        super().__init__(*args, **kwargs)

        self.fields[self.name + '_from'] = forms.FloatField(
            label='', required=False,
            widget=forms.NumberInput(attrs={'placeholder': _('From')})
        )
        self.fields[self.name + '_to'] = forms.FloatField(
            label='', required=False,
            widget=forms.NumberInput(attrs={'placeholder': _('To')})
        )
