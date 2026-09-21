"""Move serial number, purchase information and status onto devices.

Several devices can now share one inventory number. Each item's serial number,
purchase date and purchase cost move onto ``InventoryUnit`` rows:

* An item with quantity 1 becomes one device carrying its data and status,
  and its inspections are linked to that device.
* An item with a larger quantity gets one device per serial number when its
  serial number field lists exactly that many (``"A, B"`` for quantity 2).
* Otherwise the data cannot be assigned to devices without guessing, so it is
  appended to the item's notes and the item keeps working without devices.

Items with devices derive quantity (devices in stock) and status from them.
"""

from django.db import migrations
from django.db import models
import django.db.models.deletion
import re


IN_STOCK = 'in_stock'
DEFECT = 'defect'
WRITTEN_OFF = 'written_off'

SERIAL_SEPARATORS = re.compile(r'\s*[,;\n]+\s*')


def _derived(statuses):
    """Return (quantity, status) for an item with devices in ``statuses``."""
    quantity = statuses.count(IN_STOCK)
    if quantity:
        return quantity, IN_STOCK
    if DEFECT in statuses:
        return 0, DEFECT
    return 0, WRITTEN_OFF


def _legacy_note(item):
    """Describe the item's serial and purchase data as a line of notes."""
    parts = []
    if item.serial_number and item.serial_number.strip():
        parts.append(f'Seriennummer: {item.serial_number.strip()}')
    if item.purchase_date:
        parts.append(f'Kaufdatum: {item.purchase_date.isoformat()}')
    if item.purchase_cost is not None:
        parts.append(f'Kaufpreis: {item.purchase_cost}')
    return '; '.join(parts)


def move_data_to_units(apps, schema_editor):
    InventoryItem = apps.get_model('inventory', 'InventoryItem')
    InventoryUnit = apps.get_model('inventory', 'InventoryUnit')
    Inspection = apps.get_model('inventory', 'Inspection')

    for item in InventoryItem.objects.all().iterator():
        raw_serial = (item.serial_number or '').strip()
        serials = [s for s in SERIAL_SEPARATORS.split(raw_serial) if s]
        unit_status = item.status if item.status in (DEFECT, WRITTEN_OFF) else IN_STOCK
        purchase = {
            'purchase_date': item.purchase_date,
            'purchase_cost': item.purchase_cost,
        }

        if item.quantity == 1:
            specs = [raw_serial]
        elif serials and len(serials) == item.quantity:
            specs = serials
        else:
            note = _legacy_note(item)
            notes = (item.notes or '').rstrip()
            if note and note not in notes:
                item.notes = f'{notes}\n{note}' if notes else note
                item.save(update_fields=['notes'])
            continue

        units = [
            InventoryUnit.objects.create(
                item=item, serial_number=serial, status=unit_status, **purchase)
            for serial in specs
        ]
        if len(units) == 1:
            Inspection.objects.filter(inventory_item=item).update(unit=units[0])

        quantity, status = _derived([unit.status for unit in units])
        InventoryItem.objects.filter(pk=item.pk).update(quantity=quantity, status=status)


def move_data_back_to_items(apps, schema_editor):
    InventoryItem = apps.get_model('inventory', 'InventoryItem')

    for item in InventoryItem.objects.prefetch_related('units').iterator(chunk_size=500):
        units = list(item.units.all())
        if not units:
            continue
        first = units[0]
        item.serial_number = ', '.join(u.serial_number for u in units if u.serial_number) or None
        item.purchase_date = first.purchase_date
        item.purchase_cost = first.purchase_cost
        # Devices that are defect or written off no longer count, but before
        # this migration the quantity included them.
        item.quantity = len(units)
        item.save(update_fields=['serial_number', 'purchase_date', 'purchase_cost', 'quantity'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0044_drop_leftover_inspection_device_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='InventoryUnit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('serial_number', models.CharField(blank=True, max_length=255, verbose_name='Serial Number')),
                ('status', models.CharField(choices=[('in_stock', 'In stock'), ('defect', 'Defect'), ('written_off', 'Written off')], default='in_stock', max_length=50, verbose_name='Status')),
                ('purchase_date', models.DateField(blank=True, null=True, verbose_name='Purchase Date')),
                ('purchase_cost', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='Purchase Cost')),
                ('notes', models.CharField(blank=True, max_length=255, verbose_name='Note')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='units', to='inventory.inventoryitem', verbose_name='Inventory Item')),
            ],
            options={
                'verbose_name': 'Device',
                'verbose_name_plural': 'Devices',
                'ordering': ['item', 'id'],
            },
        ),
        migrations.AddField(
            model_name='inspection',
            name='unit',
            field=models.ForeignKey(blank=True, help_text='The device of the item that was inspected.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inspections', to='inventory.inventoryunit', verbose_name='Device'),
        ),
        migrations.RunPython(move_data_to_units, move_data_back_to_items),
        migrations.RemoveField(
            model_name='inventoryitem',
            name='serial_number',
        ),
        migrations.RemoveField(
            model_name='inventoryitem',
            name='purchase_date',
        ),
        migrations.RemoveField(
            model_name='inventoryitem',
            name='purchase_cost',
        ),
        migrations.AlterField(
            model_name='inventoryitem',
            name='quantity',
            field=models.PositiveIntegerField(default=1, help_text='Once devices are listed for this item, the quantity is the number of devices in stock and is updated automatically.', verbose_name='Quantity'),
        ),
    ]
