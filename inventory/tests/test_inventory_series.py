"""Tests for the inventory number series registry and the copy admin action."""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.test import TestCase

from inventory.admin import InventoryItemAdmin
from inventory.models import InventoryItem
from inventory.models import InventorySeries
from inventory.models import Location
from inventory.services import InventoryService


class InventorySeriesSeedTest(TestCase):
    """The default series must exist so import validation keeps working."""

    def test_ok_series_is_seeded(self):
        """Test that the default OK- series is available with its settings."""
        series = InventorySeries.objects.get(prefix='OK-')
        self.assertTrue(series.active)
        self.assertEqual(series.padding, 6)


class IsValidInventoryNumberTest(TestCase):
    """Validation is driven by the registry, not by a hard-coded prefix."""

    def test_number_of_seeded_series_is_valid(self):
        """Test that numbers of a configured series are accepted."""
        self.assertTrue(InventoryService.is_valid_inventory_number('OK-123'))

    def test_number_of_unknown_series_is_rejected(self):
        """Test that numbers of an unconfigured series are rejected."""
        self.assertFalse(InventoryService.is_valid_inventory_number('ABC-123'))

    def test_number_of_added_series_becomes_valid(self):
        """Test that adding a series makes its numbers acceptable."""
        self.assertFalse(InventoryService.is_valid_inventory_number('INV-0001'))
        InventorySeries.objects.create(
            prefix='INV-', description='Borrowed', padding=4)
        self.assertTrue(InventoryService.is_valid_inventory_number('INV-0001'))

    def test_inactive_series_is_rejected(self):
        """Test that numbers of a deactivated series are rejected."""
        InventorySeries.objects.create(
            prefix='INV-', description='Borrowed', padding=4, active=False)
        self.assertFalse(InventoryService.is_valid_inventory_number('INV-0001'))

    def test_prefix_without_digits_is_rejected(self):
        """Test that a bare prefix without a running number is rejected."""
        self.assertFalse(InventoryService.is_valid_inventory_number('OK-'))
        self.assertFalse(InventoryService.is_valid_inventory_number(''))
        self.assertFalse(InventoryService.is_valid_inventory_number(None))


class GenerateNextInventoryNumberTest(TestCase):
    """The generator allocates the next free number within a series."""

    def setUp(self):
        """Create a location required by InventoryItem."""
        self.location = Location.objects.create(name='Room 1')

    def _item(self, number):
        """Create an inventory item with the given number."""
        return InventoryItem.objects.create(
            inventory_number=number, location=self.location, quantity=1)

    def test_uses_padding_from_series(self):
        """Test that the configured padding defines the number width."""
        InventorySeries.objects.create(
            prefix='INV-', description='Borrowed', padding=4)
        self.assertEqual(
            InventoryService.generate_next_inventory_number('INV-0001'),
            'INV-0001',
        )

    def test_continues_after_highest_number(self):
        """Test that the next number follows the highest one in the series."""
        self._item('OK-000001')
        self._item('OK-000007')
        self.assertEqual(
            InventoryService.generate_next_inventory_number('OK-000001'),
            'OK-000008',
        )

    def test_series_are_independent(self):
        """Test that one series does not shift another series' numbering."""
        InventorySeries.objects.create(
            prefix='INV-', description='Borrowed', padding=4)
        self._item('OK-000900')
        self.assertEqual(
            InventoryService.generate_next_inventory_number('INV-0001'),
            'INV-0001',
        )

    def test_suffixed_copies_do_not_shift_the_series(self):
        """Test that "OK-000456/1" style numbers stay out of the counter."""
        self._item('OK-000010')
        self._item('OK-000010/1')
        self.assertEqual(
            InventoryService.generate_next_inventory_number('OK-000010'),
            'OK-000011',
        )

    def test_unconfigured_series_falls_back_to_number_shape(self):
        """Test that an unknown series is derived from the number itself."""
        self._item('TEST-EMAIL-001')
        self.assertEqual(
            InventoryService.generate_next_inventory_number('TEST-EMAIL-001'),
            'TEST-EMAIL-002',
        )


class CopyItemsActionTest(TestCase):
    """The admin action duplicates items under fresh numbers."""

    def setUp(self):
        """Build an admin instance and a request carrying messages."""
        self.location = Location.objects.create(name='Room 1')
        self.admin = InventoryItemAdmin(InventoryItem, AdminSite())
        user = get_user_model().objects.create_superuser(
            'admin@example.org', 'password')
        self.request = RequestFactory().post('/')
        self.request.user = user
        setattr(self.request, 'session', 'session')
        setattr(self.request, '_messages', FallbackStorage(self.request))

    def _item(self, number, **kwargs):
        """Create an inventory item with the given number."""
        return InventoryItem.objects.create(
            inventory_number=number, location=self.location,
            quantity=kwargs.pop('quantity', 1), **kwargs)

    def test_copy_gets_next_free_number(self):
        """Test that the copy is created under the next free number."""
        item = self._item('OK-000001')
        self.admin.copy_items_action(
            self.request, InventoryItem.objects.filter(pk=item.pk))
        self.assertTrue(
            InventoryItem.objects.filter(inventory_number='OK-000002').exists())

    def test_copy_carries_over_descriptive_fields(self):
        """Test that descriptive fields are duplicated onto the copy."""
        item = self._item('OK-000001', description='Tripod',
                          available_for_rent=True)
        item.units.create(serial_number='SN-1')
        self.admin.copy_items_action(
            self.request, InventoryItem.objects.all())
        copy = InventoryItem.objects.get(inventory_number='OK-000002')
        self.assertEqual(copy.description, 'Tripod')
        # Devices are physical objects of the source item and stay there.
        self.assertFalse(copy.units.exists())
        self.assertTrue(copy.available_for_rent)
        self.assertEqual(copy.location, self.location)

    def test_copy_resets_status_and_booking_counters(self):
        """Test that a copy is in stock and free of bookings."""
        self._item('OK-000001', status=InventoryItem.STATUS_RENTED,
                   reserved_quantity=3, rented_quantity=2)
        self.admin.copy_items_action(
            self.request, InventoryItem.objects.all())
        copy = InventoryItem.objects.get(inventory_number='OK-000002')
        self.assertEqual(copy.status, InventoryItem.STATUS_IN_STOCK)
        self.assertEqual(copy.reserved_quantity, 0)
        self.assertEqual(copy.rented_quantity, 0)

    def test_copying_several_items_yields_unique_numbers(self):
        """Test that a bulk copy does not collide on inventory numbers."""
        self._item('OK-000001')
        self._item('OK-000002')
        self._item('OK-000003')
        self.admin.copy_items_action(
            self.request, InventoryItem.objects.all())
        self.assertEqual(InventoryItem.objects.count(), 6)
        numbers = InventoryItem.objects.values_list(
            'inventory_number', flat=True)
        self.assertEqual(len(set(numbers)), 6)

    def test_copy_still_needs_a_barcode_label(self):
        """Test that the copy is not marked as labelled like its source."""
        item = self._item('OK-000001', barcode_attached=True)
        self.admin.copy_items_action(
            self.request, InventoryItem.objects.filter(pk=item.pk))
        copy = InventoryItem.objects.get(inventory_number='OK-000002')
        self.assertFalse(copy.barcode_attached)


class SuggestNewInventoryNumberTest(TestCase):
    """New items are prefilled with the next number of the latest series."""

    def setUp(self):
        """Create a location and an admin instance."""
        self.location = Location.objects.create(name='Room 1')
        self.admin = InventoryItemAdmin(InventoryItem, AdminSite())

    def _item(self, number):
        """Create an inventory item with the given number."""
        return InventoryItem.objects.create(
            inventory_number=number, location=self.location, quantity=1)

    def test_continues_series_of_latest_item(self):
        """Test that the series of the most recently added item is used."""
        InventorySeries.objects.create(
            prefix='INV-', description='Borrowed', padding=4)
        self._item('OK-000007')
        self._item('INV-0003')
        self.assertEqual(
            InventoryService.suggest_new_inventory_number(), 'INV-0004')

    def test_without_items_uses_first_active_series(self):
        """Test that an empty inventory starts the first active series."""
        self.assertEqual(
            InventoryService.suggest_new_inventory_number(), 'OK-000001')

    def test_without_series_suggests_nothing(self):
        """Test that no number is suggested when no series is active."""
        InventorySeries.objects.update(active=False)
        self.assertIsNone(InventoryService.suggest_new_inventory_number())

    def test_add_form_is_prefilled(self):
        """Test that the admin add form gets the suggested number."""
        self._item('OK-000041')
        request = RequestFactory().get('/')
        initial = self.admin.get_changeform_initial_data(request)
        self.assertEqual(initial['inventory_number'], 'OK-000042')

    def test_number_from_url_is_kept(self):
        """Test that a number passed in the URL is not overwritten."""
        request = RequestFactory().get('/', {'inventory_number': 'OK-000500'})
        initial = self.admin.get_changeform_initial_data(request)
        self.assertEqual(initial['inventory_number'], 'OK-000500')


class BarcodeAttachedActionTest(TestCase):
    """The bulk actions set and clear the barcode label flag."""

    def setUp(self):
        """Build an admin instance and a request carrying messages."""
        location = Location.objects.create(name='Room 1')
        self.admin = InventoryItemAdmin(InventoryItem, AdminSite())
        self.request = RequestFactory().post('/')
        setattr(self.request, 'session', 'session')
        setattr(self.request, '_messages', FallbackStorage(self.request))
        for number in ('OK-000001', 'OK-000002'):
            InventoryItem.objects.create(
                inventory_number=number, location=location, quantity=1)

    def test_mark_and_unmark(self):
        """Test that the flag is set and cleared for the selected items."""
        self.admin.mark_barcode_attached_action(
            self.request, InventoryItem.objects.all())
        self.assertEqual(
            InventoryItem.objects.filter(barcode_attached=True).count(), 2)
        self.admin.mark_barcode_missing_action(
            self.request,
            InventoryItem.objects.filter(inventory_number='OK-000001'))
        self.assertEqual(
            list(InventoryItem.objects.filter(barcode_attached=True)
                 .values_list('inventory_number', flat=True)),
            ['OK-000002'])
