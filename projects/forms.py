from .models import Project
from .models import ProjectParticipant
from crispy_forms.bootstrap import FormActions
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout
from crispy_forms.layout import Submit
from django import forms
from django.utils.translation import gettext_lazy as _


class FindProjectForm(forms.Form):
    """Form to enter an ID and find a project."""

    id = forms.UUIDField()

    def __init__(self, *args, **kwargs):
        """Show one field to enter the project id."""
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'id',
            FormActions(
                Submit('submit', _('Submit'))
            )
        )

    def is_valid(self) -> bool:
        """Make sure the id belongs to an existing project."""
        if not super().is_valid():
            return False

        try:
            Project.objects.get(id=self.data.get('id'))
        except Project.DoesNotExist:
            self.add_error(
                None,
                _('The Project with the given ID does not exist.')
            )
            return False

        return True


class AddParticipantForm(forms.ModelForm):
    """Add a Participant to a given project."""

    class Meta:
        """Include all fields."""

        model = ProjectParticipant
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        """Show fields as crispy form."""
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'name',
            'age',
            'gender',
            Submit('save', _('Add')),
        )
