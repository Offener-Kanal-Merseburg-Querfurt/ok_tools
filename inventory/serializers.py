"""
Serializers for the inventory API.

This module defines the serializers for the inventory models that will be used
by the API to provide data to the rental application.
"""

from rest_framework import serializers
from .models import InventoryItem, InventoryUnit, Category, Location, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer for Organization model."""
    
    class Meta:
        model = Organization
        fields = ['id', 'name', 'description']


class CategorySerializer(serializers.ModelSerializer):
    """Serializer for Category model."""
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']


class LocationSerializer(serializers.ModelSerializer):
    """Serializer for Location model."""
    
    class Meta:
        model = Location
        fields = ['id', 'name', 'full_path']


class InventoryUnitSerializer(serializers.ModelSerializer):
    """Serializer for one device of an inventory item."""

    class Meta:
        model = InventoryUnit
        fields = ['id', 'serial_number', 'status', 'purchase_date', 'purchase_cost', 'notes']


class InventoryItemSerializer(serializers.ModelSerializer):
    """Serializer for InventoryItem model."""
    
    owner = OrganizationSerializer(read_only=True)
    category = CategorySerializer(read_only=True)
    location = LocationSerializer(read_only=True)
    # Serial numbers of the devices in use, joined, as the field was before
    # items could hold several devices.
    serial_number = serializers.CharField(source='serial_numbers', read_only=True)
    units = InventoryUnitSerializer(many=True, read_only=True)
    
    class Meta:
        model = InventoryItem
        fields = [
            'id', 'inventory_number', 'description', 'serial_number',
            'manufacturer', 'category', 'location', 'quantity', 'status',
            'owner', 'inventory_number_owner', 'units',
            'date_added', 'available_for_rent', 'reserved_quantity', 'rented_quantity'
        ]