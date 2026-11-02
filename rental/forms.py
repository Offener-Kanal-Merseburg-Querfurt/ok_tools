from .models import RentalIssue
from .models import RentalItem
from .models import RentalRequest
from .models import RentalTransaction
from .working_hours import validate_working_hours_period
from django import forms
from django.utils.translation import gettext_lazy as _
from inventory.models import InventoryItem
from registration.models import OKUser
from .services.inventory_service_interface import inventory_service


class RentalRequestAdminForm(forms.ModelForm):
    """Admin form with validation for rental request dates."""

    class Meta:
        """Model/field options."""

        model = RentalRequest
        fields = '__all__'
        widgets = {
            'signature': forms.HiddenInput(),
            'signature_svg': forms.HiddenInput(),
            'signature_points': forms.HiddenInput(),
            'signature_metadata': forms.HiddenInput(),
            'signature_method': forms.HiddenInput(),
            'signature_signed_at': forms.HiddenInput(),
        }

    def clean(self):
        """
        Validate date consistency (end after start).

        Working hours are not enforced: only staff can open the Django admin,
        and staff may book outside the configured working hours.
        """
        cleaned = super().clean()
        start = cleaned.get('requested_start_date')
        end = cleaned.get('requested_end_date')
        if start and end and end < start:
            raise forms.ValidationError(_('Requested end date must be after start date.'))
        return cleaned


class RentalTransactionForm(forms.ModelForm):
    """Admin form for validating rental transactions consistency."""

    class Meta:
        """Model/field options."""

        model = RentalTransaction
        fields = '__all__'

    def clean(self):
        """Validate transaction rules against inventory and request state."""
        cleaned = super().clean()
        rental_item = cleaned.get('rental_item')
        tx_type = cleaned.get('transaction_type')
        qty = cleaned.get('quantity') or 0
        if not rental_item:
            return cleaned
        if qty <= 0:
            raise forms.ValidationError(_('Quantity must be positive.'))

        # Get item data from inventory service
        item_data = inventory_service.get_item_by_id(rental_item.inventory_item_id)
        if not item_data:
            raise forms.ValidationError(_('Inventory item not found.'))
        
        # Remaining global availability on the inventory item
        remaining_global = (item_data['quantity'] or 0) - (item_data['reserved_quantity'] or 0) - (item_data['rented_quantity'] or 0)

        # Compute reserved balance for this rental item
        reserve_sum = rental_item.transactions.filter(transaction_type='reserve').aggregate(total=forms.models.Sum('quantity'))['total'] or 0
        issue_sum = rental_item.transactions.filter(transaction_type='issue').aggregate(total=forms.models.Sum('quantity'))['total'] or 0
        cancel_sum = rental_item.transactions.filter(transaction_type='cancel').aggregate(total=forms.models.Sum('quantity'))['total'] or 0
        reserved_balance = reserve_sum - issue_sum - cancel_sum

        if tx_type == 'reserve':
            # cannot reserve more than missing requested and available globally
            missing_for_request = max(0, (rental_item.quantity_requested or 0) - max(0, reserved_balance))
            if qty > missing_for_request:
                raise forms.ValidationError(_('Cannot reserve more than requested amount.'))
            if qty > remaining_global:
                raise forms.ValidationError(_('Not enough items available to reserve.'))
        elif tx_type == 'issue':
            # cannot issue more than requested and more than reserved balance
            missing_issue = max(0, (rental_item.quantity_requested or 0) - (rental_item.quantity_issued or 0))
            if qty > missing_issue:
                raise forms.ValidationError(_('Cannot issue more than requested.'))
            if qty > max(0, reserved_balance):
                raise forms.ValidationError(_('Cannot issue more than reserved.'))
        elif tx_type == 'return':
            # cannot return more than issued minus already returned
            outstanding = max(0, (rental_item.quantity_issued or 0) - (rental_item.quantity_returned or 0))
            if qty > outstanding:
                raise forms.ValidationError(_('Cannot return more than outstanding issued quantity.'))
        elif tx_type == 'cancel':
            if qty > max(0, reserved_balance):
                raise forms.ValidationError(_('Cannot cancel more than reserved.'))

        return cleaned


class RentalIssueForm(forms.ModelForm):
    """Admin form for validating rental issue details."""

    class Meta:
        """Model/field options."""

        model = RentalIssue
        fields = '__all__'

    def clean(self):
        """Validate that description is provided for selected issue types."""
        cleaned = super().clean()
        issue_type = cleaned.get('issue_type')
        description = cleaned.get('description')
        if issue_type in {'damaged', 'missing', 'other'} and not description:
            raise forms.ValidationError(_('Description is required for the selected issue type.'))
        return cleaned


# Public forms for custom rental process page
class RentalRequestForm(forms.ModelForm):
    """Public form used on the custom rental process page."""

    class Meta:
        """Model/field options and widgets."""

        model = RentalRequest
        fields = ['user', 'project_name', 'purpose', 'requested_start_date', 'requested_end_date']
        widgets = {
            'requested_start_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'requested_end_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'purpose': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = OKUser.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('requested_start_date')
        end = cleaned.get('requested_end_date')
        if start and end:
            is_valid, error_message = validate_working_hours_period(start, end)
            if not is_valid and error_message:
                raise forms.ValidationError(error_message)
        return cleaned


class RentalItemForm(forms.ModelForm):
    """Public form for adding an item into a rental request."""

    class Meta:
        """Model/field options."""

        model = RentalItem
        fields = ['inventory_item', 'quantity_requested']

    def __init__(self, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if user and hasattr(user, 'profile'):
            # Get available items from inventory service
            available_items = inventory_service.get_available_items(user.id)
            # Extract item IDs from available items
            item_ids = [item['id'] for item in available_items]
            # Create a mock queryset with available item IDs
            from django.db.models import Q
            self.fields['inventory_item'].queryset = InventoryItem.objects.filter(id__in=item_ids)
