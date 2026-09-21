"""Tests for editing an item's devices on the inventory item admin page."""

from django.test import TestCase
from inventory.models import Inspection
from inventory.models import InventoryItem
from inventory.models import InventoryUnit
from inventory.models import Location
from inventory.models import Organization
from registration.models import OKUser


class InventoryItemDevicesAdminTest(TestCase):
    """Devices and their inspections are edited on the item's change page."""

    def setUp(self):
        self.client.force_login(OKUser.objects.create_superuser(
            email='admin-units@example.com', password='pw'))
        self.location = Location.objects.create(name='Stativschrank')
        self.owner = Organization.objects.create(name='OKMQ')
        self.item = InventoryItem.objects.create(
            inventory_number='OK-000774', description='Monitor Speaker',
            location=self.location, owner=self.owner, quantity=1)
        self.url = f'/admin/inventory/inventoryitem/{self.item.pk}/change/'

    def _post_data(self, units, inspections=(), existing_units=()):
        """Build the change form's POST data with both inline formsets."""
        data = {
            'inventory_number': self.item.inventory_number,
            'description': self.item.description,
            'location': self.location.pk,
            'owner': self.owner.pk,
            'quantity': self.item.quantity,
            'status': self.item.status,
            'inventory_number_owner': '',
            'notes': '',
            'units-TOTAL_FORMS': len(existing_units) + len(units),
            'units-INITIAL_FORMS': len(existing_units),
            'units-MIN_NUM_FORMS': 0,
            'units-MAX_NUM_FORMS': 1000,
            'inspections-TOTAL_FORMS': len(inspections),
            'inspections-INITIAL_FORMS': 0,
            'inspections-MIN_NUM_FORMS': 0,
            'inspections-MAX_NUM_FORMS': 1000,
            '_continue': 'Save',
        }
        rows = [dict(row, id=unit.pk) for unit, row in existing_units] + list(units)
        for index, row in enumerate(rows):
            data[f'units-{index}-item'] = self.item.pk
            for field in ('id', 'serial_number', 'status', 'purchase_date', 'purchase_cost', 'notes'):
                data[f'units-{index}-{field}'] = row.get(field, '')
        for index, row in enumerate(inspections):
            data[f'inspections-{index}-inventory_item'] = self.item.inventory_number
            for field in ('unit', 'inspection_number', 'target_part', 'inspection_date', 'result'):
                data[f'inspections-{index}-{field}'] = row.get(field, '')
        return data

    @staticmethod
    def _errors(response):
        """Return the form errors of a re-rendered change page."""
        context = response.context
        if context is None or 'adminform' not in context:
            return response.status_code
        return (context['adminform'].form.errors,
                [fs.formset.errors for fs in context['inline_admin_formsets']])

    def test_change_page_lists_devices_before_ownership_and_photos(self):
        unit = InventoryUnit.objects.create(item=self.item, serial_number='NX01088')
        Inspection.objects.create(
            inspection_number='113541', inventory_item=self.item, unit=unit,
            inspection_date='2025-02-01', result='bestanden')

        html = self.client.get(self.url).content.decode()

        self.assertIn('NX01088', html)
        self.assertIn('01.02.2025', html)  # last inspection column
        self.assertLess(html.index('id="units-group"'), html.index('id="inspections-group"'))
        self.assertLess(html.index('id="inspections-group"'), html.index('field-photo_gallery'))

    def test_saving_two_devices_sets_quantity_and_serial_numbers(self):
        response = self.client.post(self.url, self._post_data(units=[
            {'serial_number': 'NX01088', 'status': 'in_stock', 'purchase_date': '2024-01-15',
             'purchase_cost': '199.00'},
            {'serial_number': 'NX01184', 'status': 'defect'},
        ]))

        self.assertEqual(response.status_code, 302, self._errors(response))
        self.item.refresh_from_db()
        self.assertEqual(
            [(u.serial_number, u.status) for u in self.item.units.all()],
            [('NX01088', 'in_stock'), ('NX01184', 'defect')])
        self.assertEqual(self.item.quantity, 1)
        self.assertEqual(self.item.status, 'in_stock')

    def test_inspection_is_assigned_to_a_device(self):
        unit = InventoryUnit.objects.create(item=self.item, serial_number='NX01088')
        self.item.refresh_from_db()

        response = self.client.post(self.url, self._post_data(
            units=[],
            existing_units=[(unit, {'serial_number': 'NX01088', 'status': 'in_stock'})],
            inspections=[{'unit': unit.pk, 'inspection_number': '113541',
                          'target_part': 'device', 'inspection_date': '2025-02-01'}],
        ))

        self.assertEqual(response.status_code, 302, self._errors(response))
        inspection = Inspection.objects.get(inspection_number='113541')
        self.assertEqual(inspection.unit, unit)
        self.assertEqual(inspection.inventory_item, self.item)

    def test_devices_of_other_items_cannot_be_chosen_for_an_inspection(self):
        other = InventoryItem.objects.create(
            inventory_number='OK-000775', location=self.location, quantity=1)
        foreign = InventoryUnit.objects.create(item=other, serial_number='FOREIGN')

        response = self.client.post(self.url, self._post_data(
            units=[],
            inspections=[{'unit': foreign.pk, 'inspection_number': '113999',
                          'target_part': 'device', 'inspection_date': '2025-02-01'}],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Inspection.objects.filter(inspection_number='113999').exists())

    def test_quantity_and_status_are_read_only_once_devices_exist(self):
        InventoryUnit.objects.create(item=self.item, serial_number='NX01088')

        html = self.client.get(self.url).content.decode()

        self.assertNotIn('name="quantity"', html)
        self.assertNotIn('name="status"', html)
