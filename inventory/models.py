from .middleware import get_current_user
from datetime import datetime
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from pathlib import Path
from tempfile import gettempdir
import logging
import os


logger = logging.getLogger('django')

tmp_import_storage = FileSystemStorage(
    location=os.path.join(gettempdir(), "inventory_import")
)


class Manufacturer(models.Model):
    """Model representing a manufacturer."""

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))

    class Meta:
        """Meta options for Manufacturer."""

        verbose_name = _("Manufacturer")
        verbose_name_plural = _("Manufacturers")

    def __str__(self):
        """Return manufacturer name as string."""
        return self.name


class Organization(models.Model):
    """Model representing an organization."""

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))

    class Meta:
        """Meta options for Organization."""

        verbose_name = _("Organization")
        verbose_name_plural = _("Organizations")

    def __str__(self):
        """Return organization name as string."""
        return self.name


class InventoryItem(models.Model):
    """Model representing an inventory item."""

    STATUS_IN_STOCK = "in_stock"
    STATUS_RENTED = "rented"
    STATUS_WRITTEN_OFF = "written_off"
    STATUS_DEFECT = "defect"

    STATUS_CHOICES = [
        (STATUS_IN_STOCK, _("In stock")),
        (STATUS_RENTED, _("Rented")),
        (STATUS_WRITTEN_OFF, _("Written off")),
        (STATUS_DEFECT, _("Defect")),
    ]

    inventory_number = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Inventory Number")
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Description")
    )
    serial_number = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Serial Number")
    )
    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Manufacturer")
    )
    location = models.CharField(
        max_length=255,
        verbose_name=_("Location")
    )
    quantity = models.PositiveIntegerField(
        verbose_name=_("Quantity")
    )
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_IN_STOCK,
        verbose_name=_("Status")
    )
    object_type = models.CharField(
        max_length=255,
        verbose_name=_("Object Type")
    )
    owner = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Owner")
    )
    inventory_number_owner = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Inventory Number Owner"),
        help_text=_("Enter the inventory number of the owner of the item.")
    )
    purchase_date = models.DateField(
        blank=True,
        null=True,
        verbose_name=_("Purchase Date")
    )
    purchase_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name=_("Purchase Cost")
    )
    date_added = models.DateField(
        auto_now_add=True,
        verbose_name=_("Date Added")
    )
    available_for_rent = models.BooleanField(
        default=False,
        verbose_name=_("Available for Rental"),
        help_text=_("Check if this item is available for rental.")
    )
    reserved_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Reserved Quantity")
    )
    rented_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Rented Quantity")
    )

    def __init__(self, *args, **kwargs):
        """Initialize InventoryItem and store original state."""
        super().__init__(*args, **kwargs)
        self._original_state = type('OriginalState', (), {
            field.name: getattr(self, field.name)
            for field in self._meta.fields
        })

    class Meta:
        """Meta options for InventoryItem."""

        verbose_name = _("Inventory Item")
        verbose_name_plural = _("Inventory Items")
        ordering = ['inventory_number']

    def __str__(self):
        """Return inventory number as string."""
        return self.inventory_number

    def is_in_stock(self) -> bool:
        """Check if the item is in stock."""
        return self.status == self.STATUS_IN_STOCK

    def object_type_display(self):
        """Return object type for display."""
        return self.object_type
    object_type_display.short_description = _('Object Type')

    @property
    def formatted_purchase_date(self) -> str:
        """Return purchase date in a readable format."""
        return self.purchase_date.strftime("%Y-%m-%d") if self.purchase_date else _("Not specified")


class InventoryImport(models.Model):
    """Model representing the inventory import."""

    IMPORT_STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('in_progress', _('In Progress')),
        ('completed', _('Completed')),
        ('completed_with_errors', _('Completed with Errors')),
        ('failed', _('Failed')),
    ]

    def timestamp_path(instance, filename):
        """Create a path based on the current timestamp."""
        now = datetime.now()
        ext = Path(filename).suffix
        return f"{now.year}/{now.month}/{now.day}/" \
            f"{now.hour}-{now.minute}-{now.second}-{now.microsecond}{ext}"

    file = models.FileField(
        verbose_name=_('Inventory file'),
        upload_to=timestamp_path,
        storage=tmp_import_storage,
        validators=[FileExtensionValidator(["xlsx", "csv"])],
        blank=False,
        null=False,
    )

    import_status = models.CharField(
        max_length=50,
        choices=IMPORT_STATUS_CHOICES,
        default='pending',
        verbose_name=_('Import Status')
    )

    imported = models.BooleanField(
        _('Imported'),
        default=False,
        help_text=_('Just marking the file as imported does not import the file!')
    )

    items_created = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Items Created')
    )

    items_skipped = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Items Skipped')
    )

    error_log = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Error Log')
    )

    import_date = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Import Date')
    )

    completed_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Completed Date')
    )

    error_log_file = models.FileField(
        upload_to='error_logs/%Y/%m/%d/',
        null=True,
        blank=True,
        verbose_name=_('Error Log File')
    )

    class Meta:
        """Meta options for InventoryImport."""

        verbose_name = _('Inventory Import')
        verbose_name_plural = _('Inventory Imports')

    def __str__(self):
        """Return inventory import file name as string."""
        return str(self.file.name)

    def clean(self) -> None:
        """Validate the uploaded file."""
        if not self.file:
            raise ValidationError(_("No file provided."))
        from .inventory_import import validate
        validate(self.file)

    def import_data(self, request=None):
        """Import data from the uploaded file."""
        from .inventory_import import inventory_import
        try:
            self.import_status = 'in_progress'
            self.save()

            result = inventory_import(request, self.file, self)

            self.items_created = result.get('created', 0)
            self.items_skipped = result.get('skipped', 0)
            self.error_log = result.get('error_log', '')

            if self.items_skipped > 0:
                self.import_status = 'completed_with_errors'
            else:
                self.import_status = 'completed'

            self.imported = True
            self.completed_date = datetime.now()
            self.save()

        except Exception as e:
            self.import_status = 'failed'
            self.error_log = str(e)
            self.save()
            raise


class AuditLog(models.Model):
    """Model representing the audit log for tracking changes in inventory items."""

    ACTION_CHOICES = [
        ("created", _("Created")),
        ("updated", _("Updated")),
        ("deleted", _("Deleted")),
    ]

    model_name = models.CharField(
        max_length=255,
        verbose_name=_("Model Name")
    )
    object_id = models.CharField(
        max_length=255,
        verbose_name=_("Object ID")
    )
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
        verbose_name=_("Action")
    )
    changes = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_("Changes"),
        encoder=DjangoJSONEncoder
    )
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("User")
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Timestamp")
    )

    class Meta:
        """Meta options for AuditLog."""

        verbose_name = _("Audit Log")
        verbose_name_plural = _("Audit Logs")
        ordering = ['-timestamp']

    def __str__(self):
        """Return audit log entry as string."""
        return _("%(number)s %(action)s by %(user)s at %(timestamp)s") % {
            'number': self.get_inventory_number(),
            'action': self.action,
            'user': self.user,
            'timestamp': self.timestamp
        }

    def get_inventory_number(self):
        """Get inventory_number of related object."""
        if self.model_name == "InventoryItem":
            try:
                item = InventoryItem.objects.get(id=self.object_id)
                return item.inventory_number
            except InventoryItem.DoesNotExist:
                return _("Deleted item (ID: %(id)s)") % {'id': self.object_id}
        return self.object_id

    def get_changes_display(self) -> str:
        """Return changes in a readable format."""
        if not self.changes:
            return _("No changes recorded.")
        readable_changes = []
        field_labels = {
            'owner': _('Owner'),
            'available_for_rent': _('Available for Rental'),
            'quantity': _('Quantity'),
            'status': _('Status'),
            'location': _('Location'),
            'object_type': _('Object Type'),
            # Add other fields if needed
        }
        for field, change in self.changes.items():
            field_name = field_labels.get(field, field)
            if field == 'available_for_rent':
                old = _('Yes') if change['old'] == 'True' else _('No')
                new = _('Yes') if change['new'] == 'True' else _('No')
            else:
                old = change['old']
                new = change['new']
            readable_changes.append(_("%(field)s: %(old)s → %(new)s") % {
                'field': field_name,
                'old': old,
                'new': new
            })
        return "\n".join(readable_changes)


@receiver(post_save, sender=InventoryItem)
def inventory_item_save_handler(sender, instance, created, **kwargs):
    """Signal handler for creating/updating AuditLog entry."""
    if created:
        action = "created"
        changes = None
    else:
        action = "updated"
        if hasattr(instance, '_original_state'):
            changes = {}
            for field in instance._meta.fields:
                old_value = getattr(instance._original_state, field.name, None)
                new_value = getattr(instance, field.name, None)
                if old_value != new_value:
                    if isinstance(old_value, bool):
                        old_value = str(old_value)
                    if isinstance(new_value, bool):
                        new_value = str(new_value)
                    if hasattr(old_value, '__str__'):
                        old_value = str(old_value)
                    if hasattr(new_value, '__str__'):
                        new_value = str(new_value)
                    changes[field.name] = {
                        'old': old_value,
                        'new': new_value
                    }
    AuditLog.objects.create(
        model_name="InventoryItem",
        object_id=str(instance.pk),
        action=action,
        changes=changes,
        user=get_current_user()
    )


@receiver(post_delete, sender=InventoryItem)
def inventory_item_delete_handler(sender, instance, **kwargs):
    """Signal handler for deleting AuditLog entry."""
    AuditLog.objects.create(
        model_name="InventoryItem",
        object_id=str(instance.pk),
        action="deleted"
    )


class Inspection(models.Model):
    """Model representing an electrical safety inspection linked to an inventory item."""

    class TargetPart(models.TextChoices):
        """Enumeration for the inspected part of the device."""

        DEVICE = "device", _("Whole device")
        CABLE  = "cable",  _("Power cable")
        PSU    = "psu",    _("Power supply unit")

    inspection_number = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Inspection Number"),
        help_text=_("Number assigned by the inspection company")
    )

    inventory_item = models.ForeignKey(
        "InventoryItem",
        to_field="inventory_number",
        db_column="inventory_number",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspections",
        verbose_name=_("Inventory Item")
    )

    device_name  = models.CharField(max_length=255, blank=True, verbose_name=_("Device"))
    manufacturer = models.CharField(max_length=255, blank=True, verbose_name=_("Manufacturer"))
    device_type  = models.CharField(max_length=255, blank=True, verbose_name=_("Device Type"))
    room         = models.CharField(max_length=255, blank=True, verbose_name=_("Room"))

    target_part = models.CharField(
        max_length=50,
        choices=TargetPart.choices,
        default=TargetPart.DEVICE,
        verbose_name=_("Target Part")
    )
    inspection_date = models.DateField(verbose_name=_("Inspection Date"))
    result = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Result / Comment")
    )

    class Meta:
        """Meta options for Inspection."""

        verbose_name = _("Inspection")
        verbose_name_plural = _("Inspections")
        ordering = ["-inspection_date"]

    def __str__(self) -> str:
        """Return string representation of the inspection."""
        return f"{self.inspection_number} → {self.inventory_item or 'UNLINKED'}"


class InspectionImport(models.Model):
    """Model representing the inspection import."""

    IMPORT_STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('in_progress', _('In Progress')),
        ('completed', _('Completed')),
        ('completed_with_errors', _('Completed with Errors')),
        ('failed', _('Failed')),
    ]

    def timestamp_path(instance, filename) -> str:
        """Create a path based on the current timestamp."""
        now = datetime.now()
        ext = Path(filename).suffix
        return f"{now.year}/{now.month}/{now.day}/" \
            f"{now.hour}-{now.minute}-{now.second}-{now.microsecond}{ext}"

    file = models.FileField(
        verbose_name=_('Inspection file'),
        upload_to=timestamp_path,
        storage=tmp_import_storage,
        validators=[FileExtensionValidator(["xlsx", "csv"])],
        blank=False,
        null=False,
    )

    import_status = models.CharField(
        max_length=50,
        choices=IMPORT_STATUS_CHOICES,
        default='pending',
        verbose_name=_('Import Status')
    )

    imported = models.BooleanField(
        _('Imported'),
        default=False,
        help_text=_('Just marking the file as imported does not import the file!')
    )

    items_created = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Items Created')
    )

    items_skipped = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Items Skipped')
    )

    error_log = models.TextField(
        blank=True,
        null=True,
        verbose_name=_('Error Log')
    )

    import_date = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Import Date')
    )

    completed_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Completed Date')
    )

    error_log_file = models.FileField(
        upload_to='error_logs/%Y/%m/%d/',
        null=True,
        blank=True,
        verbose_name=_('Error Log File')
    )

    class Meta:
        """Meta options for InspectionImport."""

        verbose_name = _('Inspection Import')
        verbose_name_plural = _('Inspection Imports')

    def __str__(self) -> str:
        """Return string representation of the inspection import file."""
        return str(self.file.name)

    def clean(self) -> None:
        """Validate the uploaded file."""
        if not self.file:
            raise ValidationError(_("No file provided."))
        from .inspection_import import validate
        validate(self.file)

    def import_data(self, request=None) -> None:
        """Import data from the uploaded file."""
        from .inspection_import import inspection_import
        try:
            self.import_status = 'in_progress'
            self.save()

            result = inspection_import(request, self.file, self)

            self.items_created = result.get('created', 0)
            self.items_skipped = result.get('skipped', 0)
            self.error_log = result.get('error_log', '')

            if self.items_skipped > 0:
                self.import_status = 'completed_with_errors'
            else:
                self.import_status = 'completed'

            self.imported = True
            self.completed_date = datetime.now()
            self.save()

        except Exception as e:
            self.import_status = 'failed'
            self.error_log = str(e)
            self.save()
            raise
