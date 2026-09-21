from .models import InventoryItem
from .models import Location
from .models import Manufacturer
from .models import Organization
from .services import InventoryService
from datetime import datetime
from django.contrib import messages
from django.core.files import File
from django.core.files.temp import NamedTemporaryFile
from django.forms import ValidationError
from django.utils.translation import gettext as _
from openpyxl import Workbook
from openpyxl import load_workbook
import logging
import re


logger = logging.getLogger('django')
WS_NAME = _('Inventory')
IGNORED_PREFIXES = [_('Test'), _('Sample')]


def _check_inventory_number(inventory_number: str) -> bool:
    """Check if the inventory number is valid."""
    return InventoryService.is_valid_inventory_number(inventory_number)


def _create_or_skip(model, field_name, value, row_number, request):
    """Create an object or skip the row if value is missing."""
    if value:
        obj, was_created = model.objects.get_or_create(**{field_name: value}, defaults={'description': ''})
        if was_created:
            logger.info(
                _('%(model)s "%(value)s" created automatically.') %
                {'model': model._meta.verbose_name, 'value': value}
            )
        return obj
    else:
        log_msg = _('%(model)s name is missing in row %(row)s. Skipping...') % {
            'model': model._meta.verbose_name, 'row': row_number
        }
        logger.warning(log_msg)
        messages.warning(request, log_msg)
        return None


def validate(file):
    """Validate the inventory file and check column naming."""
    wb = load_workbook(file)
    errors = []

    ws = wb.worksheets[0]
    rows = ws.rows
    header = next(rows)
    required_columns = {
        0: 'inventory_number',
        1: 'description',
        2: 'serial_number',
        3: 'manufacturer',
        4: 'location',
        5: 'quantity',
        6: 'status',
         # 7: 'object_type',  # removed
        8: 'owner',
        9: 'inventory_number_owner',
        10: 'purchase_date',
        11: 'purchase_cost',
    }

    # Check for all required columns
    for col_idx, expected_name in required_columns.items():
        actual_name = header[col_idx].value if col_idx < len(header) else None
        if actual_name != expected_name:
            errors.append(ValidationError(
                _('Column %(col)s should be named "%(expected)s", but got "%(actual)s"') % {
                    'col': col_idx + 1,
                    'expected': expected_name,
                    'actual': actual_name or 'missing'
                }
            ))

    if errors:
        raise ValidationError(errors)


def inventory_import(request, file, import_obj):
    """Import inventory items from an Excel file using batch processing."""
    created_counter = 0
    updated_counter = 0
    skipped_counter = 0
    error_logs = []
    error_details = []
    
    # Batch processing settings
    BATCH_SIZE = 500  # Reasonable batch size for memory efficiency
    
    # Lists to accumulate items for batch operations
    items_to_create = []
    items_to_update = []
    # Serial, purchase and status data per item, recorded on its devices once
    # the batches have saved the items.
    device_data = []
    
    try:
        wb = load_workbook(file)
        ws = wb.worksheets[0]
        rows = ws.rows
        headers = next(rows)
        
        # Preload all existing inventory items to avoid repeated queries
        existing_items = {
            item.inventory_number: item
            for item in InventoryItem.objects.all()
        }
        
        for row in rows:
            try:
                inventory_number = str(row[0].value or '').strip()
                row_data = [str(cell.value) if cell.value is not None else '' for cell in row]

                if not inventory_number or not _check_inventory_number(inventory_number):
                    error_msg = _(f'Invalid inventory number "{inventory_number}"')
                    error_logs.append(f'Row {row[0].row}: {error_msg}')
                    error_details.append([row[0].row, error_msg] + row_data)
                    skipped_counter += 1
                    continue

                # Get values from row
                description = str(row[1].value or '').strip() or None
                serial_number = str(row[2].value or '').strip() or None
                manufacturer_name = str(row[3].value or '').strip() or None
                location_str = str(row[4].value or '').strip()

                # Resolve location by path in dictionary; do not create new ones here
                def _resolve_location(path_str: str):
                    if not path_str:
                        return None
                    raw = str(path_str).replace('/', '->')
                    parts = [p.strip() for p in raw.split('->') if p and p.strip()]
                    if not parts:
                        return None
                    parent = None
                    for name in parts:
                        try:
                            node = Location.objects.get(parent=parent, name=name)
                        except Location.DoesNotExist:
                            return None
                        parent = node
                    return parent

                loc_obj = _resolve_location(location_str)
                if not loc_obj:
                    error_msg = _('Location "%(location)s" not found in dictionary') % {
                        'location': location_str
                    }
                    error_logs.append(f'Row {row[0].row}: {error_msg}')
                    error_details.append([row[0].row, error_msg] + row_data)
                    skipped_counter += 1
                    continue

                # Handle quantity with default value 1
                try:
                    quantity = int(float(str(row[5].value or '1').strip()))
                except (ValueError, TypeError):
                    quantity = 1

                # Convert German status to English
                status_map = {
                    _('in Betrieb'): 'in_stock',
                    _('defekt'): 'defect',
                    _('ausgemustert'): 'written_off',
                    _('ausgesondert'): 'retired',
                    _('verliehen'): 'rented',
                    _('Ausleihe'): 'rented'
                }
                raw_status = str(row[6].value or '').strip()
                status = status_map.get(raw_status, 'in_stock')

                # Determine object type
                # object_type removed

                owner_name = str(row[8].value or '').strip() or None
                inventory_number_owner = str(row[9].value or '').strip() or None

                # Handle purchase date
                purchase_date = None
                if row[10].value:
                    try:
                        if isinstance(row[10].value, datetime):
                            purchase_date = row[10].value.date()
                        else:
                            purchase_date = datetime.strptime(str(row[10].value).strip(), '%Y-%m-%d').date()
                    except ValueError:
                        pass

                # Handle cost
                purchase_cost = None
                if row[11].value:
                    try:
                        purchase_cost = float(str(row[11].value).strip().replace(',', '.'))
                    except ValueError:
                        pass

                # Create or get manufacturer
                manufacturer = None
                if manufacturer_name:
                    manufacturer = _create_or_skip(Manufacturer, 'name', manufacturer_name, row[0].row, request)
                    if not manufacturer:
                        skipped_counter += 1
                        continue

                # Create or get owner
                owner = None
                if owner_name:
                    owner = _create_or_skip(Organization, 'name', owner_name, row[0].row, request)
                    if not owner:
                        skipped_counter += 1
                        continue

                # Check if item already exists
                if inventory_number in existing_items:
                    # Update existing item
                    existing_item = existing_items[inventory_number]
                    
                    # Update fields that might have changed
                    existing_item.description = description
                    existing_item.manufacturer = manufacturer
                    existing_item.location = loc_obj
                    existing_item.quantity = quantity
                    existing_item.status = status
                    existing_item.owner = owner
                    existing_item.inventory_number_owner = inventory_number_owner
                    
                    items_to_update.append(existing_item)
                    device_data.append((existing_item, {
                        'serial_number': serial_number,
                        'purchase_date': purchase_date,
                        'purchase_cost': purchase_cost,
                        'status': status,
                    }))
                    updated_counter += 1
                    
                    # Process batch if it reaches the batch size
                    if len(items_to_update) >= BATCH_SIZE:
                        _process_update_batch(items_to_update)
                        items_to_update = []  # Clear the list for next batch
                else:
                    # Create new item
                    item = InventoryItem(
                        inventory_number=inventory_number,
                        description=description,
                        manufacturer=manufacturer,
                        location=loc_obj,
                        quantity=quantity,
                        status=status,
                        # object_type removed
                        owner=owner,
                        inventory_number_owner=inventory_number_owner,
                    )
                    
                    items_to_create.append(item)
                    device_data.append((item, {
                        'serial_number': serial_number,
                        'purchase_date': purchase_date,
                        'purchase_cost': purchase_cost,
                        'status': status,
                    }))
                    created_counter += 1
                    
                    # Process batch if it reaches the batch size
                    if len(items_to_create) >= BATCH_SIZE:
                        _process_create_batch(items_to_create)
                        items_to_create = []  # Clear the list for next batch

            except Exception as e:
                error_msg = str(e)
                error_logs.append(_('Row %(row)s: %(error)s') % {
                    'row': row[0].row,
                    'error': error_msg
                })
                error_details.append([row[0].row, error_msg] + row_data)
                skipped_counter += 1
        
        # Process any remaining items in the batches
        if items_to_create:
            _process_create_batch(items_to_create)
        
        if items_to_update:
            _process_update_batch(items_to_update)

        for item, data in device_data:
            if item.pk is None:
                continue  # Creating the item failed; the error is logged.
            try:
                InventoryService.apply_device_data(item, **data)
            except Exception as e:
                error_logs.append(_('%(number)s: %(error)s') % {
                    'number': item.inventory_number,
                    'error': str(e),
                })

        # If there are errors, create Excel file
        if error_details:
            error_wb = Workbook()
            ws = error_wb.active
            ws.title = _("Import Errors")

            # Headers
            ws.append([_('Row'), _('Error')] + [cell.value for cell in headers])

            # Error data
            for error_row in error_details:
                ws.append(error_row)

            # Save to temporary file
            with NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                error_wb.save(tmp.name)
                # Save to model
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = _('import_errors_%(timestamp)s.xlsx') % {
                    'timestamp': timestamp
                }
                import_obj.error_log_file.save(filename, File(open(tmp.name, 'rb')))

    except Exception as e:
        error_msg = str(e)
        error_logs.append(_('Row %(row)s: %(error)s') % {
            'row': row[0].row if 'row' in locals() else 'unknown',
            'error': error_msg
        })

    return {
        'created': created_counter,
        'updated': updated_counter,
        'skipped': skipped_counter,
        'error_log': '\n'.join(error_logs) if error_logs else _('No errors')
    }


def _process_create_batch(items_to_create):
    """Process a batch of items for creation using bulk_create."""
    if not items_to_create:
        return
    
    try:
        # Use bulk_create for efficient batch creation
        InventoryItem.objects.bulk_create(items_to_create, batch_size=500)
        logger.info(_('Successfully created %(count)d inventory items in batch') % {
            'count': len(items_to_create)
        })
    except Exception as e:
        # If bulk_create fails, fall back to individual creation with error logging
        logger.error(_('Bulk create failed: %(error)s. Falling back to individual creation.') % {
            'error': str(e)
        })
        
        for item in items_to_create:
            try:
                item.save()
            except Exception as individual_error:
                logger.error(_('Failed to create item %(inventory_number)s: %(error)s') % {
                    'inventory_number': item.inventory_number,
                    'error': str(individual_error)
                })


def _process_update_batch(items_to_update):
    """Process a batch of items for update using bulk_update."""
    if not items_to_update:
        return
    
    try:
        # Define the fields to update - only include fields that might change
        update_fields = [
            'description', 'manufacturer', 'location',
            'quantity', 'status', 'owner', 'inventory_number_owner',
        ]
        
        # Use bulk_update for efficient batch updates
        InventoryItem.objects.bulk_update(items_to_update, update_fields, batch_size=500)
        logger.info(_('Successfully updated %(count)d inventory items in batch') % {
            'count': len(items_to_update)
        })
    except Exception as e:
        # If bulk_update fails, fall back to individual updates with error logging
        logger.error(_('Bulk update failed: %(error)s. Falling back to individual updates.') % {
            'error': str(e)
        })
        
        for item in items_to_update:
            try:
                item.save()
            except Exception as individual_error:
                logger.error(_('Failed to update item %(inventory_number)s: %(error)s') % {
                    'inventory_number': item.inventory_number,
                    'error': str(individual_error)
                })
