"""
Django signals for rental application.

This module contains signal handlers that automatically respond to model changes
in the rental system. It handles audit logging and inventory quantity updates.
"""

from .models import RentalItem
from .models import RentalRequest
from .models import RentalTransaction
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from inventory.models import AuditLog
from inventory.models import InventoryItem


@receiver(post_save, sender=RentalRequest)
def log_rental_request_changes(sender, instance: RentalRequest, created, **kwargs):
    """
    Log rental request changes to AuditLog.

    Writes to general AuditLog with model_name="RentalRequest".
    If created — action="created"; otherwise records changed fields.

    Args:
        sender: The model class that sent the signal
        instance: The RentalRequest instance being saved
        created: Boolean indicating if this is a new instance
        **kwargs: Additional keyword arguments
    """
    action = "created" if created else "updated"
    changes = None
    if not created and hasattr(instance, '_original_state'):
        changes = {}
        for field in instance._meta.fields:
            # Use attname to avoid RelatedObjectDoesNotExist on empty FK
            attr_name = getattr(field, 'attname', field.name)
            old_value = getattr(instance._original_state, field.name, None)
            new_value = getattr(instance, attr_name, None)
            if old_value != new_value:
                if hasattr(old_value, '__str__'):
                    old_value = str(old_value)
                if hasattr(new_value, '__str__'):
                    new_value = str(new_value)
                changes[field.name] = {'old': old_value, 'new': new_value}
        if not changes:
            changes = None

    AuditLog.objects.create(
        model_name="RentalRequest",
        object_id=str(instance.pk),
        action=action,
        changes=changes,
    )


@receiver(post_save, sender=RentalTransaction)
def update_inventory_quantities(sender, instance: RentalTransaction, created, **kwargs):
    """
    Update reserved_quantity and rented_quantity in InventoryItem.

    - reserve: increases reserved_quantity
    - issue: decreases reserved_quantity and increases rented_quantity
    - return: decreases rented_quantity
    - cancel: decreases reserved_quantity

    Args:
        sender: The model class that sent the signal
        instance: The RentalTransaction instance being saved
        created: Boolean indicating if this is a new instance
        **kwargs: Additional keyword arguments
    """
    if not created:
        return

    # Skip room transactions (they don't have rental_item)
    if not instance.rental_item:
        return

    rental_item = instance.rental_item
    item: InventoryItem = rental_item.inventory_item
    qty = int(instance.quantity or 0)

    if instance.transaction_type == 'reserve':
        item.reserved_quantity = (item.reserved_quantity or 0) + qty
    elif instance.transaction_type == 'issue':
        item.reserved_quantity = max(0, (item.reserved_quantity or 0) - qty)
        item.rented_quantity = (item.rented_quantity or 0) + qty
        rental_item.quantity_issued = (rental_item.quantity_issued or 0) + qty
        rental_item.save(update_fields=['quantity_issued'])
    elif instance.transaction_type == 'return':
        item.rented_quantity = max(0, (item.rented_quantity or 0) - qty)
        rental_item.quantity_returned = (rental_item.quantity_returned or 0) + qty
        rental_item.save(update_fields=['quantity_returned'])
    elif instance.transaction_type == 'cancel':
        item.reserved_quantity = max(0, (item.reserved_quantity or 0) - qty)

    item.save(update_fields=['reserved_quantity', 'rented_quantity'])
