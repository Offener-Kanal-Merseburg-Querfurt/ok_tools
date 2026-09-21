"""
Tests for InventoryService in inventory application.
"""

from unittest.mock import Mock, patch, MagicMock, mock_open
from datetime import datetime, timedelta
from django.test import TestCase, RequestFactory
from django.utils import timezone
from registration.models import OKUser
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from inventory.models import (
    InventoryItem, InventoryUnit, Location, Manufacturer, Organization, Category,
    InventoryImport, Inspection, InspectionImport, AuditLog
)
from inventory.services.inventory_service import InventoryService


class InventoryServiceTestCase(TestCase):
    """Test cases for InventoryService class."""
    
    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.inventory_service = InventoryService()
        
        # Create test user
        self.user = OKUser.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test manufacturer
        self.manufacturer = Manufacturer.objects.create(
            name='Test Manufacturer',
            description='Test Description'
        )
        
        # Create test organization
        self.organization = Organization.objects.create(
            name='Test Organization',
            description='Test Description'
        )
        
        # Create test category
        self.category = Category.objects.create(
            name='Test Category',
            description='Test Description'
        )
        
        # Create test location
        self.location = Location.objects.create(
            name='Test Location'
        )
        
        # Create test inventory item
        self.inventory_item = InventoryItem.objects.create(
            inventory_number='OK-001',
            description='Test Item',
            manufacturer=self.manufacturer,
            category=self.category,
            location=self.location,
            quantity=5,
            status='in_stock',
            owner=self.organization,
            inventory_number_owner='OWNER-001',
            available_for_rent=True,
            reserved_quantity=1,
            rented_quantity=1
        )
        
        # Create test inventory import
        self.inventory_import = InventoryImport.objects.create(
            file='test.xlsx',
            completed_date=timezone.now(),
            items_updated=5,
            items_created=3,
            items_skipped=2
        )
        
        # Create test inspection
        self.inspection = Inspection.objects.create(
            inspection_number='INS-001',
            inventory_item=self.inventory_item,
            manufacturer='Test Manufacturer',
            device_type='Test Device',
            room='Test Room',
            target_part='device',
            inspection_date=timezone.now().date(),
            result='Passed'
        )
        
        # Create test inspection import
        self.inspection_import = InspectionImport.objects.create(
            file='test_inspection.xlsx',
            completed_date=timezone.now(),
            items_created=2,
            items_skipped=1
        )
        
        # Create test audit log
        self.audit_log = AuditLog.objects.create(
            model_name='InventoryItem',
            object_id=str(self.inventory_item.id),
            action='UPDATE',
            changes='{"quantity": "4 -> 5"}',
            user=self.user
        )
    
    def test_get_inventory_items_with_availability(self):
        """Test getting inventory items with availability information."""
        result = self.inventory_service.get_inventory_items_with_availability()
        
        # Assertions
        self.assertEqual(len(result), 1)
        item_data = result[0]
        self.assertEqual(item_data['id'], self.inventory_item.id)
        self.assertEqual(item_data['inventory_number'], 'OK-001')
        self.assertEqual(item_data['description'], 'Test Item')
        # Without devices the item has no serial numbers.
        self.assertEqual(item_data['serial_number'], '')
        self.assertEqual(item_data['manufacturer'], 'Test Manufacturer')
        self.assertEqual(item_data['category'], 'Test Category')
        self.assertEqual(item_data['location'], 'Test Location')
        self.assertEqual(item_data['quantity'], 5)
        self.assertEqual(item_data['status'], 'in_stock')
        self.assertEqual(item_data['owner'], 'Test Organization')
        self.assertTrue(item_data['available_for_rent'])
        self.assertEqual(item_data['reserved_quantity'], 1)
        self.assertEqual(item_data['rented_quantity'], 1)
        self.assertEqual(item_data['available_quantity'], 3)  # 5 - 1 - 1 = 3
    
    def test_get_inventory_item_by_number(self):
        """Test getting inventory item by inventory number."""
        # Test with existing item
        result = self.inventory_service.get_inventory_item_by_number('OK-001')
        self.assertEqual(result, self.inventory_item)
        
        # Test with non-existing item
        result = self.inventory_service.get_inventory_item_by_number('OK-999')
        self.assertIsNone(result)
    
    def test_create_inventory_item(self):
        """Test creating an inventory item with a single device."""
        purchase_date = timezone.now().date()
        result = self.inventory_service.create_inventory_item(
            inventory_number='OK-002',
            description='New Item',
            serial_number='SN002',
            manufacturer=self.manufacturer,
            category=self.category,
            location=self.location,
            quantity=1,
            status='in_stock',
            owner=self.organization,
            inventory_number_owner='OWNER-002',
            purchase_date=purchase_date,
            purchase_cost=200.0,
            available_for_rent=True
        )
        
        # Assertions
        self.assertIsInstance(result, InventoryItem)
        self.assertEqual(result.inventory_number, 'OK-002')
        self.assertEqual(result.description, 'New Item')
        self.assertEqual(result.manufacturer, self.manufacturer)
        self.assertEqual(result.category, self.category)
        self.assertEqual(result.location, self.location)
        self.assertEqual(result.quantity, 1)
        self.assertEqual(result.status, 'in_stock')
        self.assertEqual(result.owner, self.organization)
        self.assertEqual(result.inventory_number_owner, 'OWNER-002')
        self.assertTrue(result.available_for_rent)

        unit = result.units.get()
        self.assertEqual(unit.serial_number, 'SN002')
        self.assertEqual(unit.purchase_date, purchase_date)
        self.assertEqual(unit.purchase_cost, 200.0)
        self.assertEqual(result.serial_numbers, 'SN002')

    def test_create_inventory_item_with_one_device_per_serial_number(self):
        """A serial number column listing the whole quantity yields devices."""
        result = self.inventory_service.create_inventory_item(
            inventory_number='OK-003', location=self.location,
            quantity=2, serial_number='NX01088, NX01184')

        self.assertEqual(
            [u.serial_number for u in result.units.all()], ['NX01088', 'NX01184'])
        self.assertEqual(result.quantity, 2)

    def test_create_inventory_item_keeps_unassignable_data_in_notes(self):
        """One serial number for ten pieces is not guessed onto devices."""
        result = self.inventory_service.create_inventory_item(
            inventory_number='OK-004', location=self.location,
            quantity=10, serial_number='ULFS30KB60B')

        self.assertFalse(result.units.exists())
        self.assertEqual(result.quantity, 10)
        self.assertIn('ULFS30KB60B', result.notes)

    def test_update_inventory_item(self):
        """Test updating an inventory item."""
        # Test with existing item
        result = self.inventory_service.update_inventory_item(
            self.inventory_item.id,
            description='Updated Item',
            quantity=8,
            status='defect'
        )
        
        # Assertions
        self.assertIsInstance(result, InventoryItem)
        self.assertEqual(result.description, 'Updated Item')
        self.assertEqual(result.quantity, 8)
        self.assertEqual(result.status, 'defect')
        
        # Test with non-existing item
        result = self.inventory_service.update_inventory_item(
            99999,
            description='Should not exist'
        )
        self.assertIsNone(result)
    
    def test_delete_inventory_item(self):
        """Test deleting an inventory item."""
        # Test with existing item
        result = self.inventory_service.delete_inventory_item(self.inventory_item.id)
        self.assertTrue(result)
        
        # Verify item was deleted
        with self.assertRaises(InventoryItem.DoesNotExist):
            InventoryItem.objects.get(id=self.inventory_item.id)
        
        # Test with non-existing item
        result = self.inventory_service.delete_inventory_item(99999)
        self.assertFalse(result)
    
    def test_get_or_create_manufacturer(self):
        """Test getting or creating a manufacturer."""
        # Test getting existing manufacturer
        result = self.inventory_service.get_or_create_manufacturer('Test Manufacturer')
        self.assertEqual(result, self.manufacturer)
        self.assertEqual(result.description, 'Test Description')
        
        # Test creating new manufacturer
        result = self.inventory_service.get_or_create_manufacturer(
            'New Manufacturer', 
            'New Description'
        )
        self.assertIsInstance(result, Manufacturer)
        self.assertEqual(result.name, 'New Manufacturer')
        self.assertEqual(result.description, 'New Description')
    
    def test_get_or_create_organization(self):
        """Test getting or creating an organization."""
        # Test getting existing organization
        result = self.inventory_service.get_or_create_organization('Test Organization')
        self.assertEqual(result, self.organization)
        self.assertEqual(result.description, 'Test Description')
        
        # Test creating new organization
        result = self.inventory_service.get_or_create_organization(
            'New Organization', 
            'New Description'
        )
        self.assertIsInstance(result, Organization)
        self.assertEqual(result.name, 'New Organization')
        self.assertEqual(result.description, 'New Description')
    
    def test_get_or_create_category(self):
        """Test getting or creating a category."""
        # Test getting existing category
        result = self.inventory_service.get_or_create_category('Test Category')
        self.assertEqual(result, self.category)
        self.assertEqual(result.description, 'Test Description')
        
        # Test creating new category
        result = self.inventory_service.get_or_create_category(
            'New Category', 
            'New Description'
        )
        self.assertIsInstance(result, Category)
        self.assertEqual(result.name, 'New Category')
        self.assertEqual(result.description, 'New Description')
    
    def test_get_or_create_location_by_path(self):
        """Test getting or creating a location by path."""
        # Test with empty path
        result = self.inventory_service.get_or_create_location_by_path('')
        self.assertIsNone(result)
        
        # Test with existing location (mocked since we don't have path functionality fully set up)
        with patch('inventory.models.Location.objects.get_or_create_by_path') as mock_get_or_create:
            mock_get_or_create.return_value = self.location
            result = self.inventory_service.get_or_create_location_by_path('Test Location')
            self.assertEqual(result, self.location)
    
    def test_create_inspection(self):
        """Test creating an inspection record."""
        result = self.inventory_service.create_inspection(
            inspection_number='INS-002',
            inventory_item=self.inventory_item,
            manufacturer='New Manufacturer',
            device_type='New Device',
            room='New Room',
            target_part='accessory',
            inspection_date=timezone.now().date(),
            result='Failed'
        )
        
        # Assertions
        self.assertIsInstance(result, Inspection)
        self.assertEqual(result.inspection_number, 'INS-002')
        self.assertEqual(result.inventory_item, self.inventory_item)
        self.assertEqual(result.manufacturer, 'New Manufacturer')
        self.assertEqual(result.device_type, 'New Device')
        self.assertEqual(result.room, 'New Room')
        self.assertEqual(result.target_part, 'accessory')
        self.assertEqual(result.result, 'Failed')
    
    def test_get_inspections_for_inventory_item(self):
        """Test getting inspections for an inventory item."""
        result = self.inventory_service.get_inspections_for_inventory_item(self.inventory_item)
        
        # Assertions
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inspection)
    
    def test_get_latest_inspection_for_inventory_item(self):
        """Test getting the latest inspection for an inventory item."""
        # Create a newer inspection
        new_inspection = Inspection.objects.create(
            inspection_number='INS-003',
            inventory_item=self.inventory_item,
            manufacturer='Test Manufacturer',
            device_type='Test Device',
            room='Test Room',
            target_part='device',
            inspection_date=timezone.now().date() + timedelta(days=1),  # Future date
            result='Passed'
        )
        
        result = self.inventory_service.get_latest_inspection_for_inventory_item(self.inventory_item)
        
        # Assertions
        self.assertEqual(result, new_inspection)
    
    def test_get_audit_logs_for_inventory_item(self):
        """Test getting audit logs for an inventory item."""
        result = self.inventory_service.get_audit_logs_for_inventory_item(self.inventory_item)
        
        # Assertions - check that at least our audit log is in the results
        self.assertGreaterEqual(len(result), 1)
        self.assertIn(self.audit_log, result)
    
    def test_search_inventory_items(self):
        """Test searching inventory items."""
        # Test search by inventory number
        result = self.inventory_service.search_inventory_items(query='OK-001')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
        
        # Test search by description
        result = self.inventory_service.search_inventory_items(query='Test Item')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
        
        # Test search by a device's serial number
        InventoryUnit.objects.create(item=self.inventory_item, serial_number='SN01')
        InventoryUnit.objects.create(item=self.inventory_item, serial_number='SN01-B')
        result = self.inventory_service.search_inventory_items(query='SN01')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
        
        # Test filter by manufacturer
        result = self.inventory_service.search_inventory_items(manufacturer_id=self.manufacturer.id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
        
        # Test filter by category
        result = self.inventory_service.search_inventory_items(category_id=self.category.id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
        
        # Test filter by location
        result = self.inventory_service.search_inventory_items(location_id=self.location.id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
        
        # Test filter by owner
        result = self.inventory_service.search_inventory_items(owner_id=self.organization.id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
        
        # Test filter by status
        result = self.inventory_service.search_inventory_items(status='in_stock')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
        
        # Test filter by availability for rent
        result = self.inventory_service.search_inventory_items(available_for_rent=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], self.inventory_item)
    
    def test_get_inventory_statistics(self):
        """Test getting inventory statistics."""
        result = self.inventory_service.get_inventory_statistics()
        
        # Assertions
        self.assertIn('total_items', result)
        self.assertIn('in_stock_items', result)
        self.assertIn('rented_items', result)
        self.assertIn('defect_items', result)
        self.assertIn('written_off_items', result)
        self.assertIn('available_for_rent_items', result)
        self.assertIn('total_quantity', result)
        self.assertIn('total_reserved', result)
        self.assertIn('total_rented', result)
        self.assertIn('total_available', result)
        self.assertIn('items_by_status', result)
        
        # Check specific values
        self.assertEqual(result['total_items'], 1)
        self.assertEqual(result['in_stock_items'], 1)
        self.assertEqual(result['available_for_rent_items'], 1)
        self.assertEqual(result['total_quantity'], 5)
        self.assertEqual(result['total_reserved'], 1)
        self.assertEqual(result['total_rented'], 1)
        self.assertEqual(result['total_available'], 3)  # 5 - 1 - 1 = 3
    
    def test_update_inventory_quantities(self):
        """Test updating inventory quantities."""
        # Update both reserved and rented quantities
        result = self.inventory_service.update_inventory_quantities(
            self.inventory_item,
            reserved_quantity=2,
            rented_quantity=3
        )
        
        # Assertions
        self.assertEqual(result.reserved_quantity, 2)
        self.assertEqual(result.rented_quantity, 3)
        
        # Update only reserved quantity
        result = self.inventory_service.update_inventory_quantities(
            self.inventory_item,
            reserved_quantity=1
        )
        
        # Assertions
        self.assertEqual(result.reserved_quantity, 1)
        self.assertEqual(result.rented_quantity, 3)  # Should remain unchanged
        
        # Update only rented quantity
        result = self.inventory_service.update_inventory_quantities(
            self.inventory_item,
            rented_quantity=2
        )
        
        # Assertions
        self.assertEqual(result.reserved_quantity, 1)  # Should remain unchanged
        self.assertEqual(result.rented_quantity, 2)
    
    def test_reserve_inventory_item(self):
        """Test reserving an inventory item."""
        # Test successful reservation
        # Available quantity = 5 - 1 - 1 = 3
        result = self.inventory_service.reserve_inventory_item(self.inventory_item, 2)
        self.assertTrue(result)
        
        # Check that reserved quantity was updated
        updated_item = InventoryItem.objects.get(id=self.inventory_item.id)
        self.assertEqual(updated_item.reserved_quantity, 3)  # 1 + 2 = 3
        
        # Test reservation that exceeds available quantity
        result = self.inventory_service.reserve_inventory_item(self.inventory_item, 5)  # Only 3 available
        self.assertFalse(result)
        
        # Check that reserved quantity was not updated
        updated_item = InventoryItem.objects.get(id=self.inventory_item.id)
        self.assertEqual(updated_item.reserved_quantity, 3)  # Should remain unchanged
    
    def test_release_inventory_reservation(self):
        """Test releasing an inventory reservation."""
        # Test successful release
        # Currently reserved: 1
        result = self.inventory_service.release_inventory_reservation(self.inventory_item, 1)
        self.assertTrue(result)
        
        # Check that reserved quantity was updated
        updated_item = InventoryItem.objects.get(id=self.inventory_item.id)
        self.assertEqual(updated_item.reserved_quantity, 0)  # 1 - 1 = 0
        
        # Test release that exceeds reserved quantity
        result = self.inventory_service.release_inventory_reservation(self.inventory_item, 5)  # Only 0 reserved
        self.assertFalse(result)
    
    def test_rent_inventory_item(self):
        """Test renting an inventory item."""
        # First, reserve some items
        self.inventory_service.reserve_inventory_item(self.inventory_item, 2)
        updated_item = InventoryItem.objects.get(id=self.inventory_item.id)
        self.assertEqual(updated_item.reserved_quantity, 3)  # 1 + 2 = 3
        
        # Test successful rental
        # Currently reserved: 3
        result = self.inventory_service.rent_inventory_item(self.inventory_item, 2)
        self.assertTrue(result)
        
        # Check that quantities were updated
        updated_item = InventoryItem.objects.get(id=self.inventory_item.id)
        self.assertEqual(updated_item.reserved_quantity, 1)  # 3 - 2 = 1
        self.assertEqual(updated_item.rented_quantity, 3)  # 1 + 2 = 3
        
        # Test rental that exceeds reserved quantity
        result = self.inventory_service.rent_inventory_item(self.inventory_item, 5)  # Only 1 reserved
        self.assertFalse(result)
    
    def test_return_inventory_item(self):
        """Test returning an inventory item."""
        # First, rent some items
        # Set reserved quantity to 3 and rent 2
        self.inventory_item.reserved_quantity = 3
        self.inventory_item.rented_quantity = 3
        self.inventory_item.save()
        
        # Test successful return
        # Currently rented: 3
        result = self.inventory_service.return_inventory_item(self.inventory_item, 2)
        self.assertTrue(result)
        
        # Check that rented quantity was updated
        updated_item = InventoryItem.objects.get(id=self.inventory_item.id)
        self.assertEqual(updated_item.rented_quantity, 1)  # 3 - 2 = 1
        
        # Test return that exceeds rented quantity
        result = self.inventory_service.return_inventory_item(self.inventory_item, 5)  # Only 1 rented
        self.assertFalse(result)
    
    def test_import_inspection_data(self):
        """Test importing inspection data."""
        # Create mock request
        request = self.factory.get('/')
        
        # Create mock file
        file_content = b"inspection_number,inspection_date,inventory_number\nINS-004,2023-01-01,OK-001"
        mock_file = SimpleUploadedFile("test.csv", file_content, content_type="text/csv")
        
        # Mock get_object_or_404 to avoid database issues
        with patch('django.shortcuts.get_object_or_404') as mock_get:
            mock_get.return_value = self.inventory_item
            
            # Call the method
            result = self.inventory_service.import_inspection_data(
                request=request,
                file=mock_file,
                import_obj=self.inspection_import
            )
            
            # Assertions
            self.assertIn('created', result)
            self.assertIn('skipped', result)
            self.assertIn('error_log', result)
    
    def test_import_inspection_data_no_file(self):
        """Test importing inspection data with no file."""
        from django.test import Client
        
        # Create a proper request with session and messages middleware
        client = Client()
        client.login(email='test@example.com', password='testpass123')
        request = client.get('/').wsgi_request
        
        # Call the method with no file
        result = self.inventory_service.import_inspection_data(
            request=request,
            file=None,
            import_obj=self.inspection_import
        )
        
        # Assertions
        self.assertIn('created', result)
        self.assertIn('skipped', result)
        self.assertIn('error_log', result)
        # When no file is provided, the method should return 0 created items and an error in the log
        self.assertEqual(result['created'], 0)
        self.assertIn('No file provided for import', result['error_log'])
    
    def test_import_inspection_data_xlsx(self):
        """Test importing inspection data from XLSX file."""
        # Create a simple XLSX file in memory
        wb = Workbook()
        ws = wb.active
        ws.append(['inspection_number', 'inspection_date', 'inventory_number'])
        ws.append(['INS-005', '2023-01-01', 'OK-001'])
        
        # Save to bytes
        from io import BytesIO
        xlsx_buffer = BytesIO()
        wb.save(xlsx_buffer)
        xlsx_buffer.seek(0)
        
        # Create mock file
        mock_file = SimpleUploadedFile("test.xlsx", xlsx_buffer.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        mock_file.seek(0)
        
        # Create mock request
        request = self.factory.get('/')
        
        # Mock get_object_or_404 to avoid database issues
        with patch('django.shortcuts.get_object_or_404') as mock_get:
            mock_get.return_value = self.inventory_item
            
            # Call the method
            result = self.inventory_service.import_inspection_data(
                request=request,
                file=mock_file,
                import_obj=self.inspection_import
            )
            
            # Assertions
            self.assertIn('created', result)
            self.assertIn('skipped', result)
            self.assertIn('error_log', result)