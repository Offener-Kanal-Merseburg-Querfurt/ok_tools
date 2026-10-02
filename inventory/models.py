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
from django_prometheus.models import ExportModelOperationsMixin
from pathlib import Path
from tempfile import gettempdir
import logging
import os


logger = logging.getLogger('django')


def tmp_import_storage():
    """Return storage for temporary import file uploads.

    Defined as a callable so migrations serialize a reference to this function
    instead of baking in the absolute ``gettempdir()`` path, which varies per
    environment and would otherwise cause perpetual no-op migrations.
    """
    return FileSystemStorage(
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

class Category(models.Model):
    """Model representing a category of inventory items."""

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))

    class Meta:
        """Meta options for Category."""

        verbose_name = _("Category")
        verbose_name_plural = _("Categories")

    def __str__(self):
        """Return category name as string."""
        return self.name

class LocationManager(models.Manager):
    """Manager for hierarchical Location with helpers to work with paths."""

    def _split_parts(self, path_str: str) -> list:
        raw = str(path_str or "").replace("/", "->")
        return [p.strip() for p in raw.split("->") if p and p.strip()]

    def get_by_path(self, path_str: str):
        """Return existing Location by hierarchical path without creating it.

        Path segments can be separated by '->' or '/'. Returns None if any
        segment is missing.
        """
        parts = self._split_parts(path_str)
        if not parts:
            return None
        parent = None
        for name in parts:
            try:
                node = self.get(parent=parent, name=name)
            except self.model.DoesNotExist:
                return None
            parent = node
        return parent

    def get_or_create_by_path(self, path_str: str):
        """Get or create Location chain for the given hierarchical path.

        Ensures every segment exists and returns the deepest Location node.
        """
        parts = self._split_parts(path_str)
        if not parts:
            raise ValueError("Empty location path")
        parent = None
        for name in parts:
            node, _ = self.get_or_create(parent=parent, name=name)
            parent = node
        return parent

    def create_by_path(self, path_str: str):
        """Create (or fetch) Location chain for the given hierarchical path.

        Ensures every segment exists and returns the deepest Location node.
        """
        parts = self._split_parts(path_str)
        if not parts:
            raise ValueError("Empty location path")
        parent = None
        for name in parts:
            node, _ = self.get_or_create(parent=parent, name=name)
            parent = node
        return parent


class Location(models.Model):
    """Hierarchical location (e.g., Room -> Cabinet)."""

    name = models.CharField(max_length=255, verbose_name=_("Name"))
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.PROTECT,
        verbose_name=_("Parent"),
    )

    objects = LocationManager()

    class Meta:
        """Meta options for Location."""

        verbose_name = _("Location")
        verbose_name_plural = _("Locations")
        unique_together = (("parent", "name"),)
        ordering = ["parent__id", "name"]

    def __str__(self) -> str:
        """Return human readable full path of the location."""
        return self.full_path

    @property
    def full_path(self) -> str:
        """Compute full path from root to this node as 'A -> B -> C'."""
        parts = []
        node = self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return " -> ".join(reversed(parts))


class InventorySeries(models.Model):
    """A configured inventory number series and what it stands for.

    An inventory number is a series prefix followed by a zero-padded running
    number (``OK-000001``, ``INV-0042``). Series are configured here rather
    than hard-coded, so every installation can define its own and document
    what each one means. Import validation and the "copy" admin action both
    read this table.
    """

    prefix = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("Prefix"),
        help_text=_(
            'Leading part of the inventory number, including the separator '
            '(e.g. "OK-").'
        )
    )
    description = models.CharField(
        max_length=255,
        verbose_name=_("Meaning"),
        help_text=_(
            'What this series stands for, e.g. "Equipment owned by the OK".'
        )
    )
    padding = models.PositiveSmallIntegerField(
        default=6,
        verbose_name=_("Number width"),
        help_text=_(
            'Digits the running number is padded to (6 gives OK-000001).'
        )
    )
    active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_(
            'Inactive series are rejected on import and are not used to '
            'generate new numbers.'
        )
    )

    class Meta:
        """Meta options for InventorySeries."""

        verbose_name = _("Inventory Number Series")
        verbose_name_plural = _("Inventory Number Series")
        ordering = ['prefix']

    def __str__(self):
        """Return the prefix together with its meaning."""
        return f"{self.prefix} — {self.description}"


class InventoryItem(ExportModelOperationsMixin('inventory_item'), models.Model):
    """Model representing an inventory item."""

    STATUS_IN_STOCK = "in_stock"
    STATUS_RENTED = "rented"
    STATUS_WRITTEN_OFF = "written_off"
    STATUS_DEFECT = "defect"
    STATUS_RETIRED = "retired"

    STATUS_CHOICES = [
        (STATUS_IN_STOCK, _("In stock")),
        (STATUS_RENTED, _("Rented")),
        (STATUS_WRITTEN_OFF, _("Written off")),
        (STATUS_DEFECT, _("Defect")),
        (STATUS_RETIRED, _("Retired")),
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
    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Manufacturer")
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Category")
    )

    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        verbose_name=_("Location")
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Quantity"),
        help_text=_(
            "Once devices are listed for this item, the quantity is the "
            "number of devices in stock and is updated automatically."
        ),
    )
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_IN_STOCK,
        verbose_name=_("Status")
    )
    # Removed: object_type field (was redundant with Location)
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
    date_added = models.DateField(
        auto_now_add=True,
        verbose_name=_("Date Added")
    )
    available_for_rent = models.BooleanField(
        default=False,
        verbose_name=_("Available for Rental"),
        help_text=_("Check if this item is available for rental.")
    )
    barcode_attached = models.BooleanField(
        default=False,
        verbose_name=_("Barcode label attached"),
        help_text=_("Check once the barcode label is stuck on the device.")
    )
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Notes"),
        help_text=_("Free text about this item, e.g. defects or accessories.")
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

        if self.pk:
            self._original_state = type('OriginalState', (), {
                field.name: getattr(self, field.name, None)
                for field in self._meta.fields
            })
        else:
            self._original_state = None

    class Meta:
        """Meta options for InventoryItem."""

        verbose_name = _("Inventory Item")
        verbose_name_plural = _("Inventory Items")
        ordering = ['inventory_number']

    def __str__(self):
        """Return human readable label: description and inventory number."""
        if self.description:
            return f"{self.description} [{self.inventory_number}]"
        return self.inventory_number

    def is_in_stock(self) -> bool:
        """Check if the item is in stock."""
        return self.status == self.STATUS_IN_STOCK

    # Removed: object_type_display helper

    @property
    def serial_numbers(self) -> str:
        """Return the serial numbers of the devices still in the stock."""
        return ', '.join(
            unit.serial_number for unit in self.units.all()
            if unit.serial_number and unit.status not in InventoryUnit.STATUS_GONE
        )

    def sync_from_units(self) -> bool:
        """Derive quantity and status from the devices listed for this item.

        The quantity is the number of devices in stock, so defective, written
        off and retired devices are not offered for rent. The status is "in
        stock" while any device is, otherwise "defect" if any device is
        defective, and the way the remaining devices left the stock ("written
        off" before "retired") once none is left. Items without devices keep
        their manually entered quantity and status. Returns whether anything
        changed.
        """
        statuses = list(self.units.values_list('status', flat=True))
        if not statuses:
            return False

        quantity = statuses.count(self.STATUS_IN_STOCK)
        if quantity:
            status = self.STATUS_IN_STOCK
        elif self.STATUS_DEFECT in statuses:
            status = self.STATUS_DEFECT
        else:
            status = next(
                (gone for gone in InventoryUnit.STATUS_GONE if gone in statuses),
                self.STATUS_WRITTEN_OFF,
            )

        changes = {
            field: {'old': str(getattr(self, field)), 'new': str(value)}
            for field, value in (('quantity', quantity), ('status', status))
            if getattr(self, field) != value
        }
        if not changes:
            return False

        # A queryset update keeps the item's post_save audit handler from
        # logging the admin form's edits a second time; this change is logged
        # on its own below.
        type(self).objects.filter(pk=self.pk).update(quantity=quantity, status=status)
        self.quantity = quantity
        self.status = status
        AuditLog.objects.create(
            model_name="InventoryItem",
            object_id=str(self.pk),
            action="updated",
            changes=changes,
            user=get_current_user(),
        )
        return True

    def save(self, *args, **kwargs):
        """Save the model and update original state for tracking changes."""
        # If the object already exists, save the current state
        if self.pk and not hasattr(self, '_original_state'):
            self._original_state = type('OriginalState', (), {
                field.name: getattr(self, field.name, None)
                for field in self._meta.fields
            })
        super().save(*args, **kwargs)


class InventoryUnit(models.Model):
    """One physical device filed under an inventory number.

    Several identical devices can share an inventory number. Each keeps its own
    serial number, purchase information, status and inspections, while the
    item holds what they have in common (description, category, location).
    """

    STATUS_IN_STOCK = InventoryItem.STATUS_IN_STOCK
    STATUS_DEFECT = InventoryItem.STATUS_DEFECT
    STATUS_WRITTEN_OFF = InventoryItem.STATUS_WRITTEN_OFF
    STATUS_RETIRED = InventoryItem.STATUS_RETIRED

    # Devices that left the stock for good, in the order the item falls back
    # on them once no device is in stock or defective.
    STATUS_GONE = (STATUS_WRITTEN_OFF, STATUS_RETIRED)

    # Renting is counted per item, not per device, so "rented" is not a
    # device status.
    STATUS_CHOICES = [
        (STATUS_IN_STOCK, _("In stock")),
        (STATUS_DEFECT, _("Defect")),
        (STATUS_WRITTEN_OFF, _("Written off")),
        (STATUS_RETIRED, _("Retired")),
    ]

    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='units',
        verbose_name=_("Inventory Item"),
    )
    serial_number = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Serial Number"),
    )
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default=STATUS_IN_STOCK,
        verbose_name=_("Status"),
    )
    purchase_date = models.DateField(
        blank=True,
        null=True,
        verbose_name=_("Purchase Date"),
    )
    purchase_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name=_("Purchase Cost"),
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Note"),
    )

    class Meta:
        """Meta options for InventoryUnit."""

        verbose_name = _("Device")
        verbose_name_plural = _("Devices")
        ordering = ['item', 'id']

    def __str__(self):
        """Return the serial number, or a numbered placeholder without one."""
        label = self.serial_number or _("Device %(id)s") % {'id': self.pk or '–'}
        return f"{label} [{self.item.inventory_number}]"


@receiver(post_save, sender=InventoryUnit)
@receiver(post_delete, sender=InventoryUnit)
def inventory_unit_changed_handler(sender, instance, **kwargs):
    """Keep the item's quantity and status in line with its devices."""
    item = InventoryItem.objects.filter(pk=instance.item_id).first()
    if item is not None:
        item.sync_from_units()


class InventoryImageConfig(models.Model):
    """Singleton configuration for inventory item photos.

    Photos live in a mounted folder (like ``media_files`` videos). The base
    folder can either reference an existing ``media_files.StorageLocation``
    (soft reference by id, since that app is optional) or be a manually
    entered absolute path. Each item's photos live in a sub-folder named after
    its ``inventory_number`` (e.g. ``OK-000001``).
    """

    enabled = models.BooleanField(
        default=True,
        verbose_name=_('Enabled'),
        help_text=_('Enable scanning and display of inventory item photos.')
    )
    media_storage_location_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_('Media Files storage location'),
        help_text=_(
            'Use an existing storage location from the Media Files module. '
            'Takes precedence over the manual path below.'
        )
    )
    base_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_('Photos folder'),
        help_text=_(
            'Absolute path to the mounted folder that holds one sub-folder '
            'per inventory number (e.g. /mnt/inventory_photos/).'
        )
    )
    supported_formats = models.CharField(
        max_length=200,
        default='jpg,jpeg,png,gif,webp,bmp',
        verbose_name=_('Supported image formats'),
        help_text=_('Comma-separated list of image file extensions to scan.')
    )
    thumbnails_beside_originals = models.BooleanField(
        default=False,
        verbose_name=_('Store thumbnails next to originals'),
        help_text=_(
            'Store generated thumbnails in a ".thumbnails" sub-folder next to '
            'the photos (requires a writable folder). When disabled, they are '
            'cached under MEDIA_ROOT. Falls back to MEDIA_ROOT if the folder '
            'is not writable.'
        )
    )

    class Meta:
        """Meta options for InventoryImageConfig."""

        verbose_name = _('Inventory Photo Settings')
        verbose_name_plural = _('Inventory Photo Settings')

    def __str__(self):
        """Return human readable label."""
        return str(_('Inventory Photo Settings'))

    @classmethod
    def get_config(cls):
        """Return the singleton config, creating a default row if missing."""
        config = cls.objects.first()
        if config is None:
            config = cls.objects.create()
        return config

    def _storage_location_path(self):
        """Return the path of the linked media_files StorageLocation, if any."""
        if not self.media_storage_location_id:
            return None
        from django.apps import apps
        if not apps.is_installed('media_files'):
            return None
        try:
            StorageLocation = apps.get_model('media_files', 'StorageLocation')
            storage = StorageLocation.objects.filter(
                pk=self.media_storage_location_id
            ).first()
        except Exception:
            return None
        return storage.path if storage else None

    def get_base_dir(self):
        """Return the resolved base directory as a ``Path`` or ``None``.

        Prefers the linked media_files storage location, then the manual
        ``base_path``. Returns ``None`` when nothing is configured or the
        resolved directory does not exist.
        """
        raw = self._storage_location_path() or self.base_path
        if not raw:
            return None
        path = Path(raw)
        if not path.is_dir():
            return None
        return path

    def get_extensions(self):
        """Return the set of lowercase image extensions (without dot)."""
        return {
            ext.strip().lstrip('.').lower()
            for ext in (self.supported_formats or '').split(',')
            if ext.strip()
        }


class InventoryItemImage(models.Model):
    """A single photo of an inventory item discovered by the folder scan."""

    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name=_('Inventory Item')
    )
    filename = models.CharField(
        max_length=500,
        verbose_name=_('Filename')
    )
    relative_path = models.CharField(
        max_length=1000,
        verbose_name=_('Relative Path'),
        help_text=_('Path relative to the configured photos folder.')
    )
    file_size = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_('File Size (bytes)')
    )
    is_available = models.BooleanField(
        default=True,
        verbose_name=_('Available'),
        help_text=_('Whether the file is physically present on disk.')
    )
    last_scanned = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Last Scanned')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created at')
    )

    class Meta:
        """Meta options for InventoryItemImage."""

        verbose_name = _('Inventory Item Photo')
        verbose_name_plural = _('Inventory Item Photos')
        unique_together = (('item', 'relative_path'),)
        ordering = ['filename']

    def __str__(self):
        """Return the relative path as string representation."""
        return self.relative_path

    def abs_path(self):
        """Return the absolute filesystem path or ``None`` if unresolved."""
        base_dir = InventoryImageConfig.get_config().get_base_dir()
        if base_dir is None:
            return None
        return base_dir / self.relative_path


@receiver(post_save, sender=InventoryImageConfig)
def sync_scan_inventory_images_task(sender, instance, **kwargs):
    """Enable/disable the periodic photo scan to match the config toggle.

    The Celery beat entry ``scan_inventory_images`` is toggled in step with
    ``InventoryImageConfig.enabled`` so beat stops dispatching the task
    entirely when photo scanning is switched off.
    """
    try:
        from django_celery_beat.models import PeriodicTask
    except Exception:
        return
    try:
        for task in PeriodicTask.objects.filter(name='scan_inventory_images'):
            if task.enabled != instance.enabled:
                task.enabled = instance.enabled
                # save() (not update()) so beat's change tracker is bumped.
                task.save(update_fields=['enabled'])
    except Exception:
        # Beat table may be missing (e.g. during migrations); ignore.
        logger.debug(
            'Could not sync scan_inventory_images periodic task',
            exc_info=True,
        )


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

    items_updated = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Items Updated')
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

    task_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_('Task ID'),
        help_text=_('Celery task ID for asynchronous processing')
    )

    celery_status = models.CharField(
        max_length=50,
        choices=[
            ('not_started', _('Not Started')),
            ('pending', _('Pending')),
            ('in_progress', _('In Progress')),
            ('completed', _('Completed')),
            ('completed_with_errors', _('Completed with Errors')),
            ('failed', _('Failed')),
            ('retry', _('Retry')),
            ('revoked', _('Revoked')),
        ],
        default='not_started',
        verbose_name=_('Celery Status')
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
        from .tasks import process_inventory_import_task
        
        # Import and process synchronously for backwards compatibility
        try:
            self.import_status = 'in_progress'
            self.celery_status = 'in_progress'
            self.save()

            from .inventory_import import inventory_import
            result = inventory_import(request, self.file, self)

            self.items_created = result.get('created', 0)
            self.items_updated = result.get('updated', 0)
            self.items_skipped = result.get('skipped', 0)
            self.error_log = result.get('error_log', '')

            if self.items_skipped > 0:
                self.import_status = 'completed_with_errors'
                self.celery_status = 'completed_with_errors'
            else:
                self.import_status = 'completed'
                self.celery_status = 'completed'

            self.imported = True
            self.completed_date = datetime.now()
            self.save()

        except Exception as e:
            self.import_status = 'failed'
            self.celery_status = 'failed'
            self.error_log = str(e)
            self.save()
            raise
    
    def import_data_async(self):
        """Start asynchronous import using Celery."""
        from .tasks import process_inventory_import_task
        
        # Update status to indicate processing is starting
        self.import_status = 'pending'
        self.celery_status = 'pending'
        self.save()
        
        # Start the asynchronous task
        task = process_inventory_import_task.delay(self.id)
        
        # Save the task ID
        self.task_id = task.id
        self.save()
        
        return task.id


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
        """Get inventory_number of related object.
        
        PERFORMANCE ISSUE: This method causes N+1 queries when called in admin list_display.
        Consider caching inventory items in admin's get_queryset or using annotate.
        """
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
            # 'object_type': _('Object Type'),
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
        changes = {}
        if hasattr(instance, '_original_state') and instance._original_state:
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
        if not changes:
            changes = None

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
    unit = models.ForeignKey(
        InventoryUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspections",
        verbose_name=_("Device"),
        help_text=_("The device of the item that was inspected."),
    )

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
