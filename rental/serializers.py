from .models import EquipmentSet
from .models import EquipmentSetItem
from .models import RentalIssue
from .models import RentalItem
from .models import RentalRequest
from .models import RentalTransaction
from django.utils.translation import gettext_lazy as _
from inventory.models import InventoryItem
from rest_framework import serializers


class InventoryItemSerializer(serializers.ModelSerializer):
    """
    Serializer for InventoryItem model.

    Provides serialization and deserialization of inventory items for API operations.
    Includes all essential fields for inventory management and rental operations.
    """

    class Meta:
        """Metadata options for InventoryItemSerializer."""

        model = InventoryItem
        fields = (
            'id', 'inventory_number', 'description', 'manufacturer', 'location', 'quantity',
            'status', 'owner', 'available_for_rent', 'reserved_quantity', 'rented_quantity'
        )


class RentalItemSerializer(serializers.ModelSerializer):
    """
    Serializer for RentalItem model.

    Handles rental item data with nested inventory item information.
    Provides read-only access to computed fields like reserved balance and outstanding quantities.
    Uses separate fields for read/write operations on inventory_item.
    """

    inventory_item = InventoryItemSerializer(read_only=True)
    inventory_item_id = serializers.PrimaryKeyRelatedField(
        queryset=InventoryItem.objects.all(), source='inventory_item', write_only=True
    )

    class Meta:
        """Metadata options for RentalItemSerializer."""

        model = RentalItem
        fields = (
            'id', 'rental_request', 'inventory_item', 'inventory_item_id',
            'quantity_requested', 'quantity_issued', 'quantity_returned', 'notes',
            'reserved_balance', 'outstanding_to_issue', 'outstanding_to_return',
        )
        read_only_fields = ('quantity_issued', 'quantity_returned', 'reserved_balance', 'outstanding_to_issue', 'outstanding_to_return')


class RentalTransactionSerializer(serializers.ModelSerializer):
    """
    Serializer for RentalTransaction model.

    Manages rental transaction data including reserve, issue, return, and cancel operations.
    Implements comprehensive validation logic to ensure business rules are followed.
    Validates quantities against available inventory and rental item constraints.
    """

    class Meta:
        """Metadata options for RentalTransactionSerializer."""

        model = RentalTransaction
        fields = ('id', 'rental_item', 'transaction_type', 'quantity', 'performed_by', 'performed_at', 'condition', 'notes')
        read_only_fields = ('performed_at',)

    def validate(self, attrs):
        """
        Validate transaction data against business rules.

        Args:
            attrs: Dictionary of field values to validate

        Returns:
            dict: Validated attributes

        Raises:
            ValidationError: If validation fails
        """
        rental_item = attrs.get('rental_item')
        tx_type = attrs.get('transaction_type')
        qty = attrs.get('quantity') or 0
        if not rental_item:
            return attrs
        if qty <= 0:
            raise serializers.ValidationError(_('Quantity must be positive.'))
        item = rental_item.inventory_item
        remaining_global = (item.quantity or 0) - (item.reserved_quantity or 0) - (item.rented_quantity or 0)
        if tx_type == 'reserve':
            if qty > rental_item.outstanding_to_issue:
                raise serializers.ValidationError(_('Cannot reserve more than requested.'))
            if qty > remaining_global:
                raise serializers.ValidationError(_('Not enough items available to reserve.'))
        elif tx_type == 'issue':
            if qty > rental_item.outstanding_to_issue:
                raise serializers.ValidationError(_('Cannot issue more than requested.'))
            if qty > rental_item.reserved_balance:
                raise serializers.ValidationError(_('Cannot issue more than reserved.'))
        elif tx_type == 'return':
            if qty > rental_item.outstanding_to_return:
                raise serializers.ValidationError(_('Cannot return more than outstanding issued.'))
        elif tx_type == 'cancel':
            if qty > rental_item.reserved_balance:
                raise serializers.ValidationError(_('Cannot cancel more than reserved.'))
        return attrs


class RentalIssueSerializer(serializers.ModelSerializer):
    """
    Serializer for RentalIssue model.

    Handles rental issue reporting and resolution tracking.
    Provides fields for issue description, severity classification, and resolution notes.
    Automatically tracks reporting time and user.
    """

    class Meta:
        """Metadata options for RentalIssueSerializer."""

        model = RentalIssue
        fields = ('id', 'rental_item', 'issue_type', 'description', 'severity', 'reported_by', 'reported_at', 'resolved', 'resolution_notes')
        read_only_fields = ('reported_at',)


class EquipmentSetItemSerializer(serializers.ModelSerializer):
    """
    Serializer for EquipmentSetItem model.

    Manages individual items within equipment sets.
    Provides nested inventory item information for read operations.
    Uses separate fields for read/write operations on inventory_item.
    """

    inventory_item = InventoryItemSerializer(read_only=True)
    inventory_item_id = serializers.PrimaryKeyRelatedField(
        queryset=InventoryItem.objects.all(), source='inventory_item', write_only=True
    )

    class Meta:
        """Metadata options for EquipmentSetItemSerializer."""

        model = EquipmentSetItem
        fields = ('id', 'equipment_set', 'inventory_item', 'inventory_item_id', 'quantity', 'is_required', 'notes')


class EquipmentSetSerializer(serializers.ModelSerializer):
    """
    Serializer for EquipmentSet model.

    Handles equipment set data with nested item information.
    Provides comprehensive set details including template status and creation metadata.
    Includes read-only access to all set items through nested serialization.
    """

    items = EquipmentSetItemSerializer(many=True, read_only=True)

    class Meta:
        """Metadata options for EquipmentSetSerializer."""

        model = EquipmentSet
        fields = ('id', 'name', 'description', 'is_template', 'created_by', 'is_active', 'created_at', 'items')


class RentalRequestSerializer(serializers.ModelSerializer):
    """
    Serializer for RentalRequest model.

    Manages rental request data with comprehensive project and timing information.
    Provides nested rental items and computed totals for complete request overview.
    Includes read-only access to creation metadata and computed fields.
    """

    items = RentalItemSerializer(many=True, read_only=True)

    class Meta:
        """Metadata options for RentalRequestSerializer."""

        model = RentalRequest
        fields = (
            'id', 'user', 'created_by', 'project_name', 'purpose',
            'requested_start_date', 'requested_end_date', 'actual_start_date', 'actual_end_date',
            'status', 'notes', 'created_at', 'updated_at', 'total_items_count', 'items'
        )
        read_only_fields = ('created_at', 'updated_at', 'total_items_count')
