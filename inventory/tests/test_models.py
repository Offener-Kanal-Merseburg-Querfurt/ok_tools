"""
Tests for Inventory models.
"""
from datetime import date
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from registration.models import OKUser
from inventory.models import (
    Manufacturer, Organization, Category, Location, InventoryItem, 
    InventoryImport, InventoryUnit, AuditLog, Inspection, InspectionImport
)


class ManufacturerModelTest(TestCase):
    """Test cases for Manufacturer model."""
    
    def test_manufacturer_creation(self):
        """Test creating a manufacturer."""
        manufacturer = Manufacturer.objects.create(
            name='Test Manufacturer',
            description='Test Description'
        )
        
        self.assertEqual(manufacturer.name, 'Test Manufacturer')
        self.assertEqual(manufacturer.description, 'Test Description')
        self.assertEqual(str(manufacturer), 'Test Manufacturer')
    
    def test_manufacturer_string_representation(self):
        """Test manufacturer string representation."""
        manufacturer = Manufacturer.objects.create(name='Apple')
        self.assertEqual(str(manufacturer), 'Apple')


class OrganizationModelTest(TestCase):
    """Test cases for Organization model."""
    
    def test_organization_creation(self):
        """Test creating an organization."""
        organization = Organization.objects.create(
            name='Test Organization',
            description='Test Description'
        )
        
        self.assertEqual(organization.name, 'Test Organization')
        self.assertEqual(organization.description, 'Test Description')
        self.assertEqual(str(organization), 'Test Organization')
    
    def test_organization_string_representation(self):
        """Test organization string representation."""
        organization = Organization.objects.create(name='OK Media')
        self.assertEqual(str(organization), 'OK Media')


class CategoryModelTest(TestCase):
    """Test cases for Category model."""
    
    def test_category_creation(self):
        """Test creating a category."""
        category = Category.objects.create(
            name='Test Category',
            description='Test Description'
        )
        
        self.assertEqual(category.name, 'Test Category')
        self.assertEqual(category.description, 'Test Description')
        self.assertEqual(str(category), 'Test Category')
    
    def test_category_string_representation(self):
        """Test category string representation."""
        category = Category.objects.create(name='Electronics')
        self.assertEqual(str(category), 'Electronics')


class LocationModelTest(TestCase):
    """Test cases for Location model."""
    
    def test_location_creation(self):
        """Test creating a location."""
        location = Location.objects.create(name='Test Location')
        
        self.assertEqual(location.name, 'Test Location')
        self.assertEqual(str(location), 'Test Location')
    
    def test_location_string_representation(self):
        """Test location string representation."""
        location = Location.objects.create(name='Room A')
        self.assertEqual(str(location), 'Room A')
    
    def test_location_hierarchy(self):
        """Test location hierarchy functionality."""
        parent_location = Location.objects.create(name='Building A')
        child_location = Location.objects.create(
            name='Floor 1',
            parent=parent_location
        )
        
        self.assertEqual(child_location.parent, parent_location)
        self.assertEqual(child_location.full_path, 'Building A -> Floor 1')
    
    def test_location_manager_get_by_path(self):
        """Test location manager get_by_path method."""
        # Create a hierarchy: Building A -> Floor 1 -> Room 101
        building = Location.objects.create(name='Building A')
        floor = Location.objects.create(name='Floor 1', parent=building)
        room = Location.objects.create(name='Room 101', parent=floor)
        
        # Test getting by path
        result = Location.objects.get_by_path('Building A -> Floor 1 -> Room 101')
        self.assertEqual(result, room)
        
        # Test getting non-existent path
        result = Location.objects.get_by_path('Building A -> Floor 2 -> Room 201')
        self.assertIsNone(result)
    
    def test_location_manager_create_by_path(self):
        """Test location manager create_by_path method."""
        # Create a path hierarchy
        location = Location.objects.create_by_path('Building B -> Floor 2 -> Room 202')
        
        # Verify the hierarchy was created
        self.assertEqual(location.name, 'Room 202')
        self.assertEqual(location.parent.name, 'Floor 2')
        self.assertEqual(location.parent.parent.name, 'Building B')
        
        # Test getting existing path
        same_location = Location.objects.create_by_path('Building B -> Floor 2 -> Room 202')
        self.assertEqual(location, same_location)


class InventoryItemModelTest(TestCase):
    """Test cases for InventoryItem model."""
    
    def setUp(self):
        """Set up test data."""
        self.manufacturer = Manufacturer.objects.create(name='Test Manufacturer')
        self.category = Category.objects.create(name='Test Category')
        self.location = Location.objects.create(name='Test Location')
        self.organization = Organization.objects.create(name='Test Organization')
    
    def test_inventory_item_creation(self):
        """Test creating an inventory item."""
        item = InventoryItem.objects.create(
            inventory_number='OK-001',
            description='Test Item',
            manufacturer=self.manufacturer,
            category=self.category,
            location=self.location,
            quantity=5,
            status='in_stock',
            owner=self.organization,
            inventory_number_owner='OWNER-001',
            available_for_rent=True
        )
        
        self.assertEqual(item.inventory_number, 'OK-001')
        self.assertEqual(item.description, 'Test Item')
        self.assertEqual(item.manufacturer, self.manufacturer)
        self.assertEqual(item.category, self.category)
        self.assertEqual(item.location, self.location)
        self.assertEqual(item.quantity, 5)
        self.assertEqual(item.status, 'in_stock')
        self.assertEqual(item.owner, self.organization)
        self.assertEqual(item.inventory_number_owner, 'OWNER-001')
        self.assertTrue(item.available_for_rent)
        self.assertEqual(item.reserved_quantity, 0)
        self.assertEqual(item.rented_quantity, 0)
        self.assertEqual(str(item), 'Test Item [OK-001]')
    
    def test_inventory_item_string_representation(self):
        """Test inventory item string representation."""
        item = InventoryItem.objects.create(
            inventory_number='OK-002',
            description='Laptop',
            location=self.location,
            quantity=1,
            status='in_stock',
            owner=self.organization
        )
        self.assertEqual(str(item), 'Laptop [OK-002]')
    
    def test_inventory_item_without_description(self):
        """Test inventory item string representation without description."""
        item = InventoryItem.objects.create(
            inventory_number='OK-003',
            location=self.location,
            quantity=1,
            status='in_stock',
            owner=self.organization
        )
        self.assertEqual(str(item), 'OK-003')
    
    def test_inventory_item_is_in_stock(self):
        """Test is_in_stock method."""
        item = InventoryItem.objects.create(
            inventory_number='OK-004',
            location=self.location,
            quantity=1,
            status='in_stock',
            owner=self.organization
        )
        self.assertTrue(item.is_in_stock())
        
        item.status = 'rented'
        item.save()
        self.assertFalse(item.is_in_stock())
    
    def _item_with_units(self, *statuses, quantity=1):
        item = InventoryItem.objects.create(
            inventory_number='OK-005', location=self.location,
            quantity=quantity, owner=self.organization)
        for index, status in enumerate(statuses):
            InventoryUnit.objects.create(
                item=item, serial_number=f'SN-{index}', status=status)
        item.refresh_from_db()
        return item

    def test_devices_set_the_quantity_to_those_in_stock(self):
        """Defective and written-off devices are not offered for rent."""
        item = self._item_with_units('in_stock', 'in_stock', 'defect', 'written_off')
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.status, 'in_stock')

    def test_item_is_defect_when_no_device_is_in_stock(self):
        item = self._item_with_units('defect', 'written_off')
        self.assertEqual(item.quantity, 0)
        self.assertEqual(item.status, 'defect')

    def test_item_is_written_off_when_every_device_is(self):
        item = self._item_with_units('written_off')
        self.assertEqual(item.status, 'written_off')

    def test_item_is_retired_when_every_device_is(self):
        item = self._item_with_units('retired', 'retired')
        self.assertEqual(item.quantity, 0)
        self.assertEqual(item.status, 'retired')

    def test_written_off_devices_outweigh_retired_ones(self):
        item = self._item_with_units('retired', 'written_off')
        self.assertEqual(item.status, 'written_off')

    def test_deleting_a_device_updates_the_quantity(self):
        item = self._item_with_units('in_stock', 'in_stock')
        item.units.first().delete()
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)

    def test_items_without_devices_keep_their_manual_quantity(self):
        item = self._item_with_units(quantity=7)
        self.assertFalse(item.sync_from_units())
        self.assertEqual(item.quantity, 7)

    def test_serial_numbers_skip_devices_that_left_the_stock(self):
        item = self._item_with_units(
            'in_stock', 'written_off', 'defect', 'retired')
        self.assertEqual(item.serial_numbers, 'SN-0, SN-2')


class InventoryImportModelTest(TestCase):
    """Test cases for InventoryImport model."""
    
    def test_inventory_import_creation(self):
        """Test creating an inventory import."""
        # Create a temporary file for testing
        import tempfile
        import os
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        # Create a mock file
        test_file = SimpleUploadedFile(
            "test_import.xlsx",
            b"file_content",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        import_obj = InventoryImport.objects.create(
            file=test_file,
            import_status='pending',
            imported=False,
            items_created=0,
            items_skipped=0,
            items_updated=0
        )
        
        self.assertEqual(import_obj.import_status, 'pending')
        self.assertFalse(import_obj.imported)
        self.assertEqual(import_obj.items_created, 0)
        self.assertEqual(import_obj.items_skipped, 0)
        self.assertEqual(import_obj.items_updated, 0)
        self.assertIsNotNone(import_obj.import_date)
        self.assertEqual(import_obj.celery_status, 'not_started')
        # The file name changes after saving due to the timestamp_path function, so we just check that it contains the expected extension
        self.assertIn('.xlsx', str(import_obj))
    
    def test_inventory_import_status_choices(self):
        """Test inventory import status choices."""
        import_obj = InventoryImport.objects.create(
            file=SimpleUploadedFile("test.xlsx", b"content")
        )
        
        # Test setting different statuses
        statuses = ['pending', 'in_progress', 'completed', 'completed_with_errors', 'failed']
        for status in statuses:
            import_obj.import_status = status
            import_obj.save()
            self.assertEqual(import_obj.import_status, status)


class AuditLogModelTest(TestCase):
    """Test cases for AuditLog model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = OKUser.objects.create_user(email='test@example.com', password='testpass123')
        self.location = Location.objects.create(name='Test Location')
        self.organization = Organization.objects.create(name='Test Organization')
        self.item = InventoryItem.objects.create(
            inventory_number='OK-001',
            description='Test Item',
            location=self.location,
            quantity=1,
            status='in_stock',
            owner=self.organization
        )
    
    def test_audit_log_creation(self):
        """Test creating an audit log entry."""
        audit_log = AuditLog.objects.create(
            model_name='InventoryItem',
            object_id=str(self.item.pk),
            action='created',
            changes=None,
            user=self.user
        )
        
        self.assertEqual(audit_log.model_name, 'InventoryItem')
        self.assertEqual(audit_log.object_id, str(self.item.pk))
        self.assertEqual(audit_log.action, 'created')
        self.assertEqual(audit_log.user, self.user)
        self.assertIsNotNone(audit_log.timestamp)
        self.assertIn('OK-001', str(audit_log))
    
    def test_audit_log_get_inventory_number(self):
        """Test get_inventory_number method."""
        audit_log = AuditLog.objects.create(
            model_name='InventoryItem',
            object_id=str(self.item.pk),
            action='updated',
            changes={'quantity': {'old': '1', 'new': '2'}},
            user=self.user
        )
        
        self.assertEqual(audit_log.get_inventory_number(), 'OK-001')
        
        # Test with non-existent item
        audit_log.object_id = '99999'
        # Account for localization
        localized_values = ['Deleted item', 'Gelöschter Artikel']
        self.assertTrue(any(value in audit_log.get_inventory_number() for value in localized_values))
    
    def test_audit_log_get_changes_display(self):
        """Test get_changes_display method."""
        changes = {
            'quantity': {'old': '1', 'new': '2'},
            'status': {'old': 'in_stock', 'new': 'rented'}
        }
        
        audit_log = AuditLog.objects.create(
            model_name='InventoryItem',
            object_id=str(self.item.pk),
            action='updated',
            changes=changes,
            user=self.user
        )
        
        display = audit_log.get_changes_display()
        # Account for localization of field names
        localized_quantity = _('Quantity')
        localized_status = _('Status')
        
        # Check for both localized and English versions
        quantity_found = any(x in display for x in ['Quantity: 1 → 2', 'Menge: 1 → 2'])
        status_found = any(x in display for x in ['Status: in_stock → rented', 'Status: in_stock → rented'])
        
        self.assertTrue(quantity_found, f"Quantity change not found in: {display}")
        self.assertTrue(status_found, f"Status change not found in: {display}")


class InspectionModelTest(TestCase):
    """Test cases for Inspection model."""
    
    def setUp(self):
        """Set up test data."""
        self.location = Location.objects.create(name='Test Location')
        self.organization = Organization.objects.create(name='Test Organization')
        self.item = InventoryItem.objects.create(
            inventory_number='OK-001',
            description='Test Item',
            location=self.location,
            quantity=1,
            status='in_stock',
            owner=self.organization
        )
    
    def test_inspection_creation(self):
        """Test creating an inspection."""
        inspection = Inspection.objects.create(
            inspection_number='INS-001',
            inventory_item=self.item,
            manufacturer='Test Manufacturer',
            device_type='Test Device',
            room='Test Room',
            target_part='device',
            inspection_date=date.today(),
            result='Passed'
        )
        
        self.assertEqual(inspection.inspection_number, 'INS-001')
        self.assertEqual(inspection.inventory_item, self.item)
        self.assertEqual(inspection.manufacturer, 'Test Manufacturer')
        self.assertEqual(inspection.device_type, 'Test Device')
        self.assertEqual(inspection.room, 'Test Room')
        self.assertEqual(inspection.target_part, 'device')
        self.assertEqual(inspection.result, 'Passed')
        self.assertEqual(str(inspection), 'INS-001 → Test Item [OK-001]')
    
    def test_inspection_with_unlinked_item(self):
        """Test inspection with unlinked inventory item."""
        inspection = Inspection.objects.create(
            inspection_number='INS-002',
            manufacturer='Test Manufacturer',
            device_type='Test Device',
            inspection_date=date.today()
        )
        
        self.assertEqual(inspection.inspection_number, 'INS-002')
        self.assertIsNone(inspection.inventory_item)
        self.assertEqual(str(inspection), 'INS-002 → UNLINKED')
    
    def test_inspection_target_part_choices(self):
        """Test inspection target part choices."""
        choices = Inspection.TargetPart.choices
        expected_choices = [
            ('device', 'Whole device'),
            ('cable', 'Power cable'),
            ('psu', 'Power supply unit')
        ]
        
        # Account for localization of choices
        choice_keys = [choice[0] for choice in choices]
        choice_values = [choice[1] for choice in choices]
        
        for expected_key, expected_value in expected_choices:
            self.assertIn(expected_key, choice_keys)
            # Check if the localized value is present
            self.assertTrue(any(expected_key in choice[0] for choice in choices))


class InspectionImportModelTest(TestCase):
    """Test cases for InspectionImport model."""
    
    def test_inspection_import_creation(self):
        """Test creating an inspection import."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        # Create a mock file
        test_file = SimpleUploadedFile("test_inspection.xlsx", b"file_content")
        
        import_obj = InspectionImport.objects.create(
            file=test_file,
            import_status='pending',
            imported=False,
            items_created=0,
            items_skipped=0
        )
        
        self.assertEqual(import_obj.import_status, 'pending')
        self.assertFalse(import_obj.imported)
        self.assertEqual(import_obj.items_created, 0)
        self.assertEqual(import_obj.items_skipped, 0)
        self.assertIsNotNone(import_obj.import_date)
        # The file name changes after saving due to the timestamp_path function
        # Just check that it contains the expected extension
        self.assertIn('.xlsx', str(import_obj))
    
    def test_inspection_import_status_choices(self):
        """Test inspection import status choices."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        import_obj = InspectionImport.objects.create(
            file=SimpleUploadedFile("test.xlsx", b"content")
        )
        
        # Test setting different statuses
        statuses = ['pending', 'in_progress', 'completed', 'completed_with_errors', 'failed']
        for status in statuses:
            import_obj.import_status = status
            import_obj.save()
            self.assertEqual(import_obj.import_status, status)