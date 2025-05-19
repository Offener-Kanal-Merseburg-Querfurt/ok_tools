from .models import Inspection
from django import forms
from django.utils.translation import gettext_lazy as _


class InspectionInlineForm(forms.ModelForm):
    """Form for inline Inspection model."""

    inspection_number = forms.CharField(
        label=_("Inspection Number"),
        max_length=255,
        help_text=_("Enter existing number or a new one")
    )

    class Meta:
        """Meta options for InspectionInlineForm."""

        model = Inspection
        fields = ("inspection_number", "target_part", "inspection_date", "result")

    def __init__(self, *args, **kwargs):
        """Initialize the form."""
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["inspection_number"].initial = self.instance.inspection_number

    def clean_inspection_number(self):
        """Validate inspection number uniqueness."""
        number = self.cleaned_data["inspection_number"].strip()
        qs = Inspection.objects.filter(inspection_number=number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.filter(inventory_item__isnull=False).exists():
            raise forms.ValidationError(
                _("Inspection number already attached to another item.")
            )
        return number

    def save(self, commit=True):
        """Save the form instance."""
        number = self.cleaned_data["inspection_number"].strip()
        if self.instance.pk:
            self.instance.inspection_number = number
            return super().save(commit)

        existing = Inspection.objects.filter(
            inspection_number=number,
            inventory_item__isnull=True
        ).first()

        if existing:
            self.instance = existing
        self.instance.inspection_number = number
        self.instance.target_part = self.cleaned_data["target_part"]
        self.instance.inspection_date = self.cleaned_data["inspection_date"]
        self.instance.result = self.cleaned_data["result"]
        return super().save(commit)
