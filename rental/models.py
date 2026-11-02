from . import label_layout
from datetime import date
from datetime import datetime
from datetime import time
from decimal import Decimal
from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.query import QuerySet
from django.utils.translation import gettext_lazy as _
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union
import uuid


class RentalRequest(models.Model):
    """Equipment rental request."""

    user = models.ForeignKey(
        'registration.OKUser',
        on_delete=models.CASCADE,
        verbose_name=_('User'),
    )
    created_by = models.ForeignKey(
        'registration.OKUser',
        on_delete=models.CASCADE,
        related_name='created_rentals',
        verbose_name=_('Created by'),
    )
    project_name = models.CharField(
        max_length=255,
        verbose_name=_('Project name'),
    )
    purpose = models.TextField(
        verbose_name=_('Purpose'),
    )

    requested_start_date = models.DateTimeField(
        verbose_name=_('Requested start date'),
    )
    requested_end_date = models.DateTimeField(
        verbose_name=_('Requested end date'),
    )
    actual_start_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Actual start date'),
    )
    actual_end_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Actual end date'),
    )

    STATUS_CHOICES = [
        ('draft', _('Draft')),
        ('reserved', _('Reserved')),
        ('issued', _('Issued')),
        ('returned', _('Returned')),
        ('cancelled', _('Cancelled')),
        ('closed', _('Closed')),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        verbose_name=_('Status'),
    )

    RENTAL_TYPE_CHOICES = [
        ('equipment', _('Equipment')),
        ('room', _('Room')),
        ('mixed', _('Equipment and Room')),
    ]
    rental_type = models.CharField(
        max_length=20,
        choices=RENTAL_TYPE_CHOICES,
        default='equipment',
        verbose_name=_('Rental type'),
        help_text=_('Type of rental: equipment, room, or both'),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_('Notes'),
    )

    signature = models.TextField(
        _('Signature'),
        blank=True,
        null=True,
        help_text=_('Base64 encoded signature image'),
    )
    signature_svg = models.TextField(
        _('Signature SVG'),
        blank=True,
        null=True,
        help_text=_('Primary SVG signature data'),
    )
    signature_points = models.JSONField(
        _('Signature points'),
        blank=True,
        null=True,
        default=None,
        help_text=_('Biometric signature stroke points (x,y,time,pressure).'),
    )
    signature_metadata = models.JSONField(
        _('Signature metadata'),
        blank=True,
        null=True,
        default=None,
        help_text=_('Signature metadata such as device, user-agent, and capture details.'),
    )
    signature_method = models.CharField(
        _('Signature method'),
        max_length=32,
        blank=True,
        null=True,
        help_text=_('Signature input method (mouse, touch, stylus, qr_phone).'),
    )
    signature_signed_at = models.DateTimeField(
        _('Signature signed at'),
        blank=True,
        null=True,
        help_text=_('When the digital signature was captured.'),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    auto_return_reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Automatic return reminder sent at'),
        help_text=_('When the automatic return reminder email was sent.'),
    )

    class Meta:
        """Django model metadata for ``RentalRequest``."""

        verbose_name = _('Rental request')
        verbose_name_plural = _('Rental requests')
        ordering = ['-created_at']

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.project_name} ({self.user})"

    def has_any_signature(self):
        """Return True when any supported signature format is available."""
        if self.signature:
            return True
        if self.signature_svg:
            return True
        if self.signature_points:
            return True
        return False

    def __init__(self, *args, **kwargs):
        """Save original state for change auditing."""
        super().__init__(*args, **kwargs)
        # Safely read values without triggering relation descriptors on add view
        original = {}
        for field in self._meta.fields:
            attr_name = getattr(field, 'attname', field.name)
            original[field.name] = getattr(self, attr_name, None)
        self._original_state = type('OriginalState', (), original)

    def can_user_access_item(self, inventory_item) -> bool:
        """Check user access rights to inventory based on user status."""
        if not getattr(inventory_item, 'available_for_rent', False):
            return False

        # Staff users (Mitarbeiter) have access to all items
        if getattr(self.user, 'is_staff', False):
            return True

        # Profile can be null in rare cases — protect against it
        user_profile = getattr(self.user, 'profile', None)
        owner_name = inventory_item.owner.name if getattr(inventory_item, 'owner', None) else ""

        from registration import organization_config
        state_institution = organization_config.get_state_media_institution()
        organization_owner = organization_config.get_organization_owner()
        
        if user_profile and getattr(user_profile, 'member', False):
            # Member can take equipment from state institution AND organization
            return owner_name == state_institution or owner_name == organization_owner
        # Non-member can only take from state media institution
        return owner_name == state_institution

    def get_available_inventory(self) -> QuerySet:
        """Get available inventory for rental considering user rights."""
        from django.db.models import Q
        from rental.services.inventory_service_interface import \
            inventory_service

        # Get available items through the service interface
        available_items_data = inventory_service.get_available_items(user_id=self.user.id)

        # Extract IDs from the data
        available_item_ids = [item['id'] for item in available_items_data]

        # Get the actual InventoryItem objects
        return available_items_data

    @property
    def total_items_count(self) -> int:
        """Total number of items in the request (by quantity_requested)."""
        from django.db.models import Sum
        return self.items.aggregate(total=Sum('quantity_requested'))['total'] or 0

    @property
    def has_rooms(self) -> bool:
        """Check if there are rented rooms."""
        return self.room_rentals.exists()

    @property
    def total_rooms_count(self) -> int:
        """Total number of rented rooms."""
        return self.room_rentals.count()

    def get_room_summary(self) -> str:
        """Get brief information about rooms.
        
        PERFORMANCE: Requires prefetch_related('room_rentals__room') for efficiency.
        Without prefetch, this method will cause N+1 queries.
        """
        rooms = []
        for room_rental in self.room_rentals.all():
            rooms.append(f"{room_rental.room.name} ({room_rental.people_count} people)")
        return ", ".join(rooms) if rooms else _('No rooms')


class RentalItem(models.Model):
    """Item in rental request."""

    rental_request = models.ForeignKey(
        RentalRequest,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('Rental request'),
    )
    inventory_item = models.ForeignKey(
        'inventory.InventoryItem',
        on_delete=models.CASCADE,
        verbose_name=_('Inventory item'),
        help_text=_('Search by number, description, manufacturer'),
    )

    quantity_requested = models.PositiveIntegerField(
        verbose_name=_('Quantity requested'),
    )
    quantity_issued = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Quantity issued'),
    )
    quantity_returned = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Quantity returned'),
    )

    actual_return_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Actual return date'),
        help_text=_('Date when the item was actually returned (auto-filled on return)'),
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_('Notes'),
    )
    pick_list_checked = models.BooleanField(
        default=False,
        verbose_name=_('Pick list checked'),
    )
    pick_list_note = models.TextField(
        blank=True,
        verbose_name=_('Pick list note'),
    )

    class Meta:
        """Django model metadata for ``RentalItem``."""

        verbose_name = _('Rental item')
        verbose_name_plural = _('Rental items')

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.inventory_item} x{self.quantity_requested}"

    @property
    def reserved_balance(self) -> int:
        """Return reserved balance for this rental item (reserved - issued - cancelled)."""
        from django.db.models import Sum
        totals = self.transactions.values('transaction_type').annotate(total=Sum('quantity'))
        by_type = {row['transaction_type']: row['total'] or 0 for row in totals}
        return max(0, (by_type.get('reserve', 0) - by_type.get('issue', 0) - by_type.get('cancel', 0)))

    @property
    def outstanding_to_issue(self) -> int:
        """Return remaining quantity allowed to issue for this item."""
        requested = self.quantity_requested or 0
        issued = self.quantity_issued or 0
        return max(0, requested - issued)

    @property
    def outstanding_to_return(self) -> int:
        """Return remaining quantity expected to be returned for this item."""
        issued = self.quantity_issued or 0
        returned = self.quantity_returned or 0
        return max(0, issued - returned)

    @property
    def is_overdue(self) -> bool:
        """Check if the item is overdue for return."""
        from django.utils import timezone
        if not self.actual_return_date:
            # If not yet returned, check if past due date
            return self.rental_request.requested_end_date < timezone.now()
        # If returned, check if returned after due date
        return self.actual_return_date > self.rental_request.requested_end_date

    @property
    def days_overdue(self) -> int:
        """Calculate how many days overdue the item is/was."""
        from django.utils import timezone
        if not self.actual_return_date:
            # Not yet returned
            if self.rental_request.requested_end_date < timezone.now():
                delta = timezone.now() - self.rental_request.requested_end_date
                return delta.days
        else:
            # Already returned
            if self.actual_return_date > self.rental_request.requested_end_date:
                delta = self.actual_return_date - self.rental_request.requested_end_date
                return delta.days
        return 0


class EquipmentSet(models.Model):
    """Equipment set."""

    name = models.CharField(
        max_length=255,
        verbose_name=_('Name'),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_('Description'),
    )
    is_template = models.BooleanField(
        default=False,
        verbose_name=_('Is template'),
    )
    created_by = models.ForeignKey(
        'registration.OKUser',
        on_delete=models.CASCADE,
        verbose_name=_('Created by'),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Is active'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        """Django model metadata for ``EquipmentSet``."""

        verbose_name = _('Equipment set')
        verbose_name_plural = _('Equipment sets')
        ordering = ['name']

    def __str__(self) -> str:
        """Return human-readable representation."""
        return self.name

    def apply_to_rental_request(self, rental_request: "RentalRequest") -> None:
        """Add set items to rental request.

        If an item with the same `inventory_item` already exists in the request,
        increase `quantity_requested`.
        """
        for set_item in self.items.select_related('inventory_item').all():
            rental_item, _ = RentalItem.objects.get_or_create(
                rental_request=rental_request,
                inventory_item=set_item.inventory_item,
                defaults={
                    'quantity_requested': 0,
                    'quantity_issued': 0,
                    'quantity_returned': 0,
                    'notes': '',
                },
            )
            rental_item.quantity_requested = (rental_item.quantity_requested or 0) + set_item.quantity
            rental_item.save(update_fields=[
                'quantity_requested',
            ])


class EquipmentSetItem(models.Model):
    """Equipment set item."""

    equipment_set = models.ForeignKey(
        EquipmentSet,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('Equipment set'),
    )
    inventory_item = models.ForeignKey(
        'inventory.InventoryItem',
        on_delete=models.CASCADE,
        verbose_name=_('Inventory item'),
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name=_('Quantity'),
    )
    is_required = models.BooleanField(
        default=True,
        verbose_name=_('Is required'),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_('Notes'),
    )

    class Meta:
        """Django model metadata for ``EquipmentSetItem``."""

        verbose_name = _('Equipment set item')
        verbose_name_plural = _('Equipment set items')

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.equipment_set}: {self.inventory_item} x{self.quantity}"


class RentalTransaction(models.Model):
    """Rental operations (reserve, issue, return, cancel)."""

    rental_item = models.ForeignKey(
        RentalItem,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name=_('Rental item'),
        null=True,
        blank=True,
    )

    room = models.ForeignKey(
        'Room',
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name=_('Room'),
        null=True,
        blank=True,
    )

    TRANSACTION_TYPES = [
        ('reserve', _('Reserve')),
        ('issue', _('Issue')),
        ('return', _('Return')),
        ('cancel', _('Cancel')),
    ]
    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
        verbose_name=_('Transaction type'),
    )
    quantity = models.PositiveIntegerField(
        verbose_name=_('Quantity'),
    )

    performed_by = models.ForeignKey(
        'registration.OKUser',
        on_delete=models.CASCADE,
        verbose_name=_('Performed by'),
    )
    performed_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Performed at'),
    )

    CONDITION_CHOICES = [
        ('excellent', _('Excellent')),
        ('good', _('Good')),
        ('fair', _('Fair')),
        ('poor', _('Poor')),
    ]
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        blank=True,
        verbose_name=_('Condition'),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_('Notes'),
    )

    class Meta:
        """Django model metadata for ``RentalTransaction``."""

        verbose_name = _('Rental transaction')
        verbose_name_plural = _('Rental transactions')
        ordering = ['-performed_at']

    def __str__(self) -> str:
        """Return human-readable representation."""
        if self.rental_item:
            return f"{self.get_transaction_type_display()} {self.quantity} → {self.rental_item}"
        elif self.room:
            return f"{self.get_transaction_type_display()} {self.quantity} → {self.room}"
        else:
            return f"{self.get_transaction_type_display()} {self.quantity}"

    def clean(self) -> None:
        """Check that either ``rental_item`` or ``room`` is specified."""
        from django.core.exceptions import ValidationError
        if not self.rental_item and not self.room:
            raise ValidationError(_('Either item or room must be specified'))
        if self.rental_item and self.room:
            raise ValidationError(_('Cannot specify both item and room simultaneously'))


class RentalIssue(models.Model):
    """Issues during return."""

    rental_item = models.ForeignKey(
        RentalItem,
        on_delete=models.CASCADE,
        related_name='issues',
        verbose_name=_('Rental item'),
    )

    ISSUE_TYPES = [
        ('damaged', _('Damaged')),
        ('missing', _('Missing')),
        ('late_return', _('Late Return')),
        ('other', _('Other')),
    ]
    issue_type = models.CharField(
        max_length=20,
        choices=ISSUE_TYPES,
        verbose_name=_('Issue type'),
    )
    description = models.TextField(
        verbose_name=_('Description'),
    )

    SEVERITY_CHOICES = [
        ('minor', _('Minor')),
        ('major', _('Major')),
        ('critical', _('Critical')),
    ]
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        verbose_name=_('Severity'),
    )

    reported_by = models.ForeignKey(
        'registration.OKUser',
        on_delete=models.CASCADE,
        verbose_name=_('Reported by'),
    )
    reported_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Reported at'),
    )
    resolved = models.BooleanField(
        default=False,
        verbose_name=_('Resolved'),
    )
    resolution_notes = models.TextField(
        blank=True,
        verbose_name=_('Resolution notes'),
    )

    class Meta:
        """Django model metadata for ``RentalIssue``."""

        verbose_name = _('Rental issue')
        verbose_name_plural = _('Rental issues')
        ordering = ['-reported_at']

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.get_issue_type_display()} ({self.get_severity_display()}) → {self.rental_item}"


class RentalConsumable(models.Model):
    """
    Consumable or accessory handed out with a rental but not kept in inventory.

    Typical examples are cables or memory cards ("XLR cable 5 m", 3 pieces).
    The return screen records how many came back; what is still missing stays
    open until staff mark it as returned later or written off, and the user is
    reminded about it by email.
    """

    STATUS_OUT = 'out'
    STATUS_RETURNED = 'returned'
    STATUS_MISSING = 'missing'
    STATUS_WRITTEN_OFF = 'written_off'
    STATUS_CHOICES = [
        (STATUS_OUT, _('Handed out')),
        (STATUS_RETURNED, _('Returned')),
        (STATUS_MISSING, _('Missing')),
        (STATUS_WRITTEN_OFF, _('Written off')),
    ]

    rental_request = models.ForeignKey(
        RentalRequest,
        on_delete=models.CASCADE,
        related_name='consumables',
        verbose_name=_('Rental request'),
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_('Name'),
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name=_('Quantity'),
    )
    quantity_returned = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Quantity returned'),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OUT,
        db_index=True,
        verbose_name=_('Status'),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_('Notes'),
    )
    created_by = models.ForeignKey(
        'registration.OKUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('Created by'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created at'),
    )
    returned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Return checked at'),
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Resolved at'),
        help_text=_('When a missing consumable was returned later or written off.'),
    )
    resolved_by = models.ForeignKey(
        'registration.OKUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('Resolved by'),
    )
    last_reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Last reminder sent at'),
    )
    reminder_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Reminders sent'),
    )

    class Meta:
        """Django model metadata for ``RentalConsumable``."""

        verbose_name = _('Consumable')
        verbose_name_plural = _('Consumables')
        ordering = ['created_at', 'id']

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f'{self.name} × {self.quantity}'

    @property
    def quantity_missing(self) -> int:
        """Return how many pieces have not come back."""
        return max(self.quantity - self.quantity_returned, 0)


class Room(models.Model):
    """Model for rooms/premises."""

    name = models.CharField(max_length=100, verbose_name=_('Room name'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    capacity = models.PositiveIntegerField(verbose_name=_('Capacity'))
    location = models.CharField(max_length=200, blank=True, verbose_name=_('Location'))
    is_active = models.BooleanField(default=True, verbose_name=_('Active'))

    class Meta:
        """Django model metadata for ``Room``."""

        verbose_name = _('Room')
        verbose_name_plural = _('Rooms')
        ordering = ['name']

    def __str__(self):
        """Return human-readable representation."""
        return self.name

    @property
    def primary_image(self):
        """Return the first room image, or ``None`` if there is none."""
        return self.images.first()

    def is_available_for_time(self, start_date: datetime, end_date: datetime, exclude_rental_request: Optional[int] = None) -> bool:
        """Check if the room is available for the specified time.

        Args:
            start_date: rental start datetime
            end_date: rental end datetime
            exclude_rental_request: request ID to exclude (when editing)

        Returns:
            bool: True if room is available, False if occupied
        """
        from django.db.models import Q
        from django.utils import timezone

        # Check that room is active
        if not self.is_active:
            return False

        # Check that time is not in the past
        now = timezone.now()
        if start_date < now or end_date < now:
            return False

        # Check that end_date is greater than start_date
        if end_date <= start_date:
            return False

        # Look for conflicts with existing rentals
        conflicting_rentals = RoomRental.objects.filter(
            room=self,
            rental_request__status__in=['reserved', 'issued']
        )

        # Exclude current request when editing
        if exclude_rental_request:
            conflicting_rentals = conflicting_rentals.exclude(
                rental_request_id=exclude_rental_request
            )

        # Check time conflicts
        for rental in conflicting_rentals:
            # Use room-specific dates if available, otherwise use rental request dates
            rental_start = rental.get_start_date()
            rental_end = rental.get_end_date()

            # Check time interval overlap
            if rental_start and rental_end:
                # There is overlap if:
                # 1. New time starts before existing ends AND ends after existing starts
                # 2. Or new time completely contains existing
                if (start_date < rental_end and end_date > rental_start):
                    return False

        return True

    def get_conflicting_rentals(self, start_date: datetime, end_date: datetime, exclude_rental_request: Optional[int] = None) -> List:
        """Return list of conflicting rentals for specified time.

        Args:
            start_date: rental start datetime
            end_date: rental end datetime
            exclude_rental_request: request ID to exclude

        Returns:
            QuerySet: List of conflicting rentals
        """
        from django.db.models import Q

        conflicting_rentals = RoomRental.objects.filter(
            room=self,
            rental_request__status__in=['reserved', 'issued']
        )

        if exclude_rental_request:
            conflicting_rentals = conflicting_rentals.exclude(
                rental_request_id=exclude_rental_request
            )

        # Filter by time overlap
        conflicts = []
        for rental in conflicting_rentals:
            # Use room-specific dates if available, otherwise use rental request dates
            rental_start = rental.get_start_date()
            rental_end = rental.get_end_date()

            if rental_start and rental_end:
                if (start_date < rental_end and end_date > rental_start):
                    conflicts.append(rental)

        return conflicts


class RoomImage(models.Model):
    """A photo of a room, uploaded via the admin."""

    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name=_('Room'),
    )
    image = models.ImageField(
        upload_to='room_photos/',
        verbose_name=_('Image'),
    )
    caption = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_('Caption'),
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        verbose_name=_('Sort order'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created at'),
    )

    class Meta:
        """Django model metadata for ``RoomImage``."""

        verbose_name = _('Room photo')
        verbose_name_plural = _('Room photos')
        ordering = ['sort_order', 'id']

    def __str__(self):
        """Return human-readable representation."""
        return f'{self.room.name} — {self.caption or self.image.name}'


class RoomRental(models.Model):
    """Model for room rentals."""

    rental_request = models.ForeignKey(
        RentalRequest,
        on_delete=models.CASCADE,
        related_name='room_rentals',
        verbose_name=_('Rental request'),
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.CASCADE,
        verbose_name=_('Room'),
    )
    people_count = models.PositiveIntegerField(
        verbose_name=_('Number of people'),
        help_text=_('Number of people using the room'),
    )
    requested_start_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Requested start date'),
        help_text=_('Room rental start date. If not specified, uses rental request start date.'),
    )
    requested_end_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Requested end date'),
        help_text=_('Room rental end date. If not specified, uses rental request end date.'),
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_('Notes'),
        help_text=_('Additional notes for room rental'),
    )
    nextcloud_event_href = models.URLField(
        blank=True,
        null=True,
        verbose_name=_('Nextcloud Event URL'),
        help_text=_('URL of the event in Nextcloud Calendar (for CalDAV sync)'),
    )

    class Meta:
        """Django model metadata for ``RoomRental``."""

        verbose_name = _('Room rental')
        verbose_name_plural = _('Room rentals')
        unique_together = ['rental_request', 'room']

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.room.name} - {self.rental_request.project_name}"

    def get_start_date(self):
        """Get start date for this room rental.
        
        Returns room-specific date if set, otherwise falls back to rental request date.
        """
        return self.requested_start_date or (self.rental_request.requested_start_date if self.rental_request else None)
    
    def get_end_date(self):
        """Get end date for this room rental.
        
        Returns room-specific date if set, otherwise falls back to rental request date.
        """
        return self.requested_end_date or (self.rental_request.requested_end_date if self.rental_request else None)

    @property
    def is_expired(self) -> bool:
        """Check if room rental time has expired."""
        from django.utils import timezone
        end_datetime = self.get_end_date()
        if not end_datetime:
            return False

        return timezone.now() > end_datetime

    @property
    def time_until_expiry(self) -> int:
        """Return number of minutes until rental expires."""
        from django.utils import timezone
        end_time = self.get_end_date()
        if not end_time:
            return 0

        now = timezone.now()
        if now >= end_time:
            return 0

        delta = end_time - now
        return int(delta.total_seconds() / 60)

    @property
    def status_display(self) -> str:
        """Return human-readable room rental status."""
        if self.is_expired:
            return _('Expired')
        elif self.time_until_expiry <= 30:  # Less than 30 minutes
            return _('Expiring soon')
        else:
            return _('Active')


class RentalProcessProxy(RentalRequest):
    """Proxy model for adding rental process link to admin menu."""

    class Meta:
        """Django model metadata for ``RentalProcessProxy``."""

        proxy = True
        verbose_name = _('Rental Process')
        verbose_name_plural = _('Rental Process')


class EquipmentTemplate(models.Model):
    """Template for equipment sets that can be reused for creating rentals."""

    name = models.CharField(
        max_length=255,
        verbose_name=_('Template Name'),
        help_text=_('Name of the equipment template (e.g., "Concert Setup", "Workshop Equipment")')
    )

    description = models.TextField(
        blank=True,
        verbose_name=_('Description'),
        help_text=_('Optional description of what this template is used for')
    )

    created_by = models.ForeignKey(
        'registration.OKUser',
        on_delete=models.CASCADE,
        verbose_name=_('Created by'),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created at')
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Updated at')
    )

    class Meta:
        verbose_name = _('Equipment Template')
        verbose_name_plural = _('Equipment Templates')
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class EquipmentTemplateItem(models.Model):
    """Individual equipment items in a template."""

    template = models.ForeignKey(
        EquipmentTemplate,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('Template')
    )

    inventory_item = models.ForeignKey(
        'inventory.InventoryItem',
        on_delete=models.CASCADE,
        verbose_name=_('Inventory Item')
    )

    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name=_('Quantity'),
        help_text=_('Default quantity for this item in the template')
    )

    class Meta:
        verbose_name = _('Template Item')
        verbose_name_plural = _('Template Items')
        unique_together = ['template', 'inventory_item']

    def __str__(self) -> str:
        return f"{self.template.name} - {self.inventory_item.description} ({self.quantity})"


class RentalConfig(models.Model):
    """Configuration for rental module (singleton)."""

    WEEKDAY_FIELD_NAMES = [
        'monday',
        'tuesday',
        'wednesday',
        'thursday',
        'friday',
        'saturday',
        'sunday',
    ]
    
    # Enable email-based approval workflow for user-created rental requests
    # When enabled, user requests are created as 'draft' and require admin approval
    # Admins receive email with approve/deny links; users receive status notifications
    user_request_requires_approval = models.BooleanField(
        default=False,
        verbose_name=_('User Request Requires Approval'),
        help_text=_('Enable email-based approval workflow for user-created rental requests')
    )
    
    # Base URL for approval links in emails (must match your production domain)
    # Example: https://okmq.your-domain.com
    site_base_url = models.URLField(
        blank=True,
        verbose_name=_('Site Base URL'),
        help_text=_('Base URL for approval links in emails (must match your production domain)')
    )
    
    # User-facing rental request URL used in emails
    # Example: https://okmq-your-domain.com/rental/user/rental/{rental_id}/
    request_url_template = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_('Rental Request URL Template'),
        help_text=_('User-facing rental request URL template (use {rental_id} placeholder)')
    )
    
    # Optional: Explicit list of admin email addresses to notify
    # If not set, all active staff users with email addresses will be notified
    # Format: comma-separated email addresses
    approval_recipient_emails = models.TextField(
        blank=True,
        verbose_name=_('Approval Recipient Emails'),
        help_text=_('Comma-separated list of admin email addresses to notify (optional, if empty all staff users will be notified)')
    )
    
    # Optional: Token expiration time for approve/deny links (in seconds)
    # Default: 7 days (604800 seconds)
    approval_token_max_age_seconds = models.IntegerField(
        default=604800,
        verbose_name=_('Approval Token Max Age (seconds)'),
        help_text=_('Token expiration time for approve/deny links in seconds')
    )

    show_item_photos = models.BooleanField(
        default=False,
        verbose_name=_('Show item photos'),
        help_text=_('Show inventory item photos on the rental process and dashboard pages')
    )
    scan_sound_enabled = models.BooleanField(
        default=False,
        verbose_name=_('Scanner feedback sound'),
        help_text=_('Play a short tone when a barcode scan succeeds or fails. '
                    'Off by default, because a shared counter gets noisy.'),
    )
    show_room_photos = models.BooleanField(
        default=False,
        verbose_name=_('Show room photos'),
        help_text=_('Show room photos on the rental process page')
    )

    auto_reminder_enabled = models.BooleanField(
        default=False,
        verbose_name=_('Automatic Return Reminders'),
        help_text=_('Enable automatic return reminder emails for issued rentals')
    )
    auto_reminder_hours_before = models.IntegerField(
        default=24,
        verbose_name=_('Reminder Hours Before Return'),
        help_text=_('Send reminder this many hours before the requested return date')
    )
    missing_consumable_reminder_days = models.PositiveIntegerField(
        default=7,
        verbose_name=_('Missing consumables reminder interval (days)'),
        help_text=_('Remind the user by email about consumables that were not '
                    'returned, every this many days until staff resolve them. '
                    '0 disables the reminder.'),
    )

    monday_start_time = models.TimeField(
        default=time(hour=10, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Monday opening time'),
    )
    monday_end_time = models.TimeField(
        default=time(hour=18, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Monday closing time'),
    )
    tuesday_start_time = models.TimeField(
        default=time(hour=10, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Tuesday opening time'),
    )
    tuesday_end_time = models.TimeField(
        default=time(hour=18, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Tuesday closing time'),
    )
    wednesday_start_time = models.TimeField(
        default=time(hour=10, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Wednesday opening time'),
    )
    wednesday_end_time = models.TimeField(
        default=time(hour=18, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Wednesday closing time'),
    )
    thursday_start_time = models.TimeField(
        default=time(hour=10, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Thursday opening time'),
    )
    thursday_end_time = models.TimeField(
        default=time(hour=18, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Thursday closing time'),
    )
    friday_start_time = models.TimeField(
        default=time(hour=10, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Friday opening time'),
    )
    friday_end_time = models.TimeField(
        default=time(hour=18, minute=0),
        null=True,
        blank=True,
        verbose_name=_('Friday closing time'),
    )
    saturday_start_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_('Saturday opening time'),
    )
    saturday_end_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_('Saturday closing time'),
    )
    sunday_start_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_('Sunday opening time'),
    )
    sunday_end_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_('Sunday closing time'),
    )

    # Network label printer speaking TSPL (e.g. TSC TE210) reached over a raw
    # socket on port 9100. Printing through the browser needs the media size
    # configured on every workstation; the printer takes it in the job itself.
    label_printer_host = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_('Label printer host'),
        help_text=_('IP address or hostname of the TSPL label printer. '
                    'Leave empty to print labels through the browser only.'),
    )
    label_printer_port = models.PositiveIntegerField(
        default=9100,
        verbose_name=_('Label printer port'),
        help_text=_('Raw socket port of the label printer, usually 9100.'),
    )
    label_printer_dpi = models.PositiveIntegerField(
        default=203,
        choices=((203, '203 dpi'), (300, '300 dpi')),
        verbose_name=_('Label printer resolution'),
        help_text=_('Print head resolution, used to convert millimetres to dots.'),
    )
    label_gap_mm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal('2.0'),
        verbose_name=_('Label gap (mm)'),
        help_text=_('Distance between two labels on the roll. Measure it: a '
                    'wrong value makes the printer feed past the next label.'),
    )
    label_printer_density = models.PositiveSmallIntegerField(
        default=8,
        validators=[MinValueValidator(0), MaxValueValidator(15)],
        verbose_name=_('Print density'),
        help_text=_('Heat setting from 0 to 15. Raise it when the bars come '
                    'out grey, lower it when they bleed.'),
    )
    label_printer_speed = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        verbose_name=_('Print speed (inch/s)'),
        help_text=_('Printing speed in inches per second.'),
    )
    label_offset_x_mm = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        default=Decimal('0.0'),
        validators=[MinValueValidator(Decimal('-10')),
                    MaxValueValidator(Decimal('10'))],
        verbose_name=_('Horizontal offset (mm)'),
        help_text=_('Moves the printed content to the right. Use it when the '
                    'roll does not sit centred under the print head.'),
    )
    label_offset_y_mm = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        default=Decimal('0.0'),
        validators=[MinValueValidator(Decimal('-10')),
                    MaxValueValidator(Decimal('10'))],
        verbose_name=_('Top offset (mm)'),
        help_text=_('Moves the printed content down, away from the top edge. '
                    'The content is laid out in what is left of the label, so '
                    'nothing is pushed over the bottom edge.'),
    )

    user_organizations = models.ManyToManyField(
        'inventory.Organization',
        blank=True,
        related_name='rental_config_user',
        verbose_name=_("User organizations"),
    )
    member_organizations = models.ManyToManyField(
        'inventory.Organization',
        blank=True,
        related_name='rental_config_member',
        verbose_name=_("Member organizations"),
    )
    employee_organizations = models.ManyToManyField(
        'inventory.Organization',
        blank=True,
        related_name='rental_config_employee',
        verbose_name=_("Employee organizations"),
    )
    rental_only_organizations = models.ManyToManyField(
        'inventory.Organization',
        blank=True,
        related_name='rental_config_rental_only',
        verbose_name=_("Rental only organizations"),
    )

    @property
    def label_printer_configured(self) -> bool:
        """Return whether labels can be sent straight to a label printer."""
        return bool(self.label_printer_host.strip())

    @classmethod
    def get_organizations_for(cls, user):
        """
        Return the organizations whose items the given user may rent.

        Profile.member and Profile.rental_only are mutually exclusive, so the
        order of those two branches cannot matter in practice.

        Args:
            user: The user to resolve the organizations for

        Returns:
            QuerySet: Organizations gating this user, possibly empty
        """
        config = cls.get_config()
        if user.is_staff:
            return config.employee_organizations.all()
        profile = getattr(user, 'profile', None)
        if profile and profile.member:
            return config.member_organizations.all()
        if profile and profile.rental_only:
            return config.rental_only_organizations.all()
        return config.user_organizations.all()

    class Meta:
        verbose_name = _('Rental Configuration')
        verbose_name_plural = _('Rental Configuration')
    
    def __str__(self):
        """Return string representation."""
        return str(_("Rental Configuration"))
    
    def save(self, *args, **kwargs):
        """Ensure only one config instance exists."""
        self.pk = 1
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError

        errors = {}
        for day_name in self.WEEKDAY_FIELD_NAMES:
            start_time = getattr(self, f'{day_name}_start_time')
            end_time = getattr(self, f'{day_name}_end_time')
            if bool(start_time) != bool(end_time):
                errors[f'{day_name}_start_time'] = _('Please set both opening and closing time or leave both empty.')
            elif start_time and end_time and start_time >= end_time:
                errors[f'{day_name}_start_time'] = _('Opening time must be before closing time.')

        if errors:
            raise ValidationError(errors)
    
    @classmethod
    def get_config(cls):
        """Get the singleton config instance, create if doesn't exist."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
    
    def get_approval_recipient_emails_list(self):
        """Get approval recipient emails as a list."""
        if not self.approval_recipient_emails:
            return []
        return [email.strip() for email in self.approval_recipient_emails.split(',') if email.strip()]

    def get_weekday_hours(self, weekday: int) -> Dict[str, Any]:
        day_name = self.WEEKDAY_FIELD_NAMES[weekday]
        start_time = getattr(self, f'{day_name}_start_time')
        end_time = getattr(self, f'{day_name}_end_time')
        enabled = bool(start_time and end_time)
        return {
            'enabled': enabled,
            'start': start_time if enabled else None,
            'end': end_time if enabled else None,
        }


class LabelFormat(models.Model):
    """A physical label size barcode labels can be printed on.

    The two roll sizes the module started with were hand tuned; every other
    size derives its barcode geometry and type sizes from those two, so a new
    roll only needs its millimetres entered here.
    """

    slug = models.SlugField(
        max_length=50,
        unique=True,
        verbose_name=_('Key'),
        help_text=_('Identifies the format in the print URL. Changing it '
                    'breaks links that were already handed out.'),
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_('Name'),
        help_text=_('Shown in the format chooser, e.g. "Roll label".'),
    )
    width_mm = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(20), MaxValueValidator(200)],
        verbose_name=_('Width (mm)'),
    )
    height_mm = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(10), MaxValueValidator(200)],
        verbose_name=_('Height (mm)'),
    )
    gap_mm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        verbose_name=_('Gap (mm)'),
        help_text=_('Distance to the next label on this roll. Leave empty to '
                    'use the gap from the label printer settings.'),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Offered in the print dialog'),
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_('Sort order'),
    )

    class Meta:
        ordering = ('sort_order', 'width_mm', 'height_mm')
        verbose_name = _('Label format')
        verbose_name_plural = _('Label formats')

    def __str__(self):
        """Return the name together with the size it prints."""
        return f'{self.name} ({self.width_mm} × {self.height_mm} mm)'

    @property
    def size_label(self) -> str:
        """Return the size as it is shown next to the name."""
        return f'{self.width_mm} × {self.height_mm} mm'


class LabelLine(models.Model):
    """One line of a label format: what it shows and how large.

    A label is described rather than hard coded, because what belongs on it
    differs per installation: a house whose locations carry no shelf codes
    wants nothing highlighted, and a house that prints no owner wants that
    line gone.
    """

    class Content(models.TextChoices):
        """What a line puts on the label."""

        NUMBER_OWNER = label_layout.CONTENT_NUMBER_OWNER, \
            _('Inventory number and owner')
        NUMBER = label_layout.CONTENT_NUMBER, _('Inventory number')
        OWNER = label_layout.CONTENT_OWNER, _('Owner')
        BARCODE = label_layout.CONTENT_BARCODE, _('Barcode')
        DESCRIPTION = label_layout.CONTENT_DESCRIPTION, _('Description')
        LOCATION = label_layout.CONTENT_LOCATION, _('Location')

    class Size(models.TextChoices):
        """How large a line prints, relative to the label."""

        SMALL = label_layout.SIZE_SMALL, _('Small')
        NORMAL = label_layout.SIZE_NORMAL, _('Normal')
        LARGE = label_layout.SIZE_LARGE, _('Large')

    class Align(models.TextChoices):
        """Where a line sits across the label."""

        LEFT = label_layout.ALIGN_LEFT, _('Left')
        CENTER = label_layout.ALIGN_CENTER, _('Centred')
        RIGHT = label_layout.ALIGN_RIGHT, _('Right')

    label_format = models.ForeignKey(
        'LabelFormat',
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name=_('Label format'),
    )
    position = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_('Position'),
        help_text=_('Lines print in this order, top to bottom.'),
    )
    content = models.CharField(
        max_length=20,
        choices=Content.choices,
        verbose_name=_('Content'),
    )
    size = models.CharField(
        max_length=10,
        choices=Size.choices,
        default=Size.NORMAL,
        verbose_name=_('Size'),
    )
    align = models.CharField(
        max_length=10,
        choices=Align.choices,
        default=Align.CENTER,
        verbose_name=_('Alignment'),
    )
    shorten_words = models.BooleanField(
        default=True,
        verbose_name=_('Shorten words when needed'),
        help_text=_('Abbreviates the words of a location that would not fit '
                    '("Schrank" becomes "Schr."), keeping the codes intact. '
                    'Only applies to the location line.'),
    )
    highlight_codes = models.BooleanField(
        default=True,
        verbose_name=_('Enlarge the codes'),
        help_text=_('Prints the number or letter that ends a location level '
                    'larger than the words around it. Turn this off where '
                    'locations carry no such codes. Location line only.'),
    )
    drop_leading_segments = models.PositiveSmallIntegerField(
        default=0,
        verbose_name=_('Drop leading location levels'),
        help_text=_('Leaves out this many levels from the front of a '
                    'location, for a first level everybody knows anyway.'),
    )

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = _('Label line')
        verbose_name_plural = _('Label lines')

    def __str__(self):
        """Return the line's content and size."""
        return f'{self.get_content_display()} ({self.get_size_display()})'

    def to_spec(self) -> label_layout.LineSpec:
        """Return the line as the layout engine's own definition."""
        return label_layout.LineSpec(
            content=self.content,
            size=self.size,
            align=self.align,
            shorten_words=self.shorten_words,
            highlight_codes=self.highlight_codes,
            drop_leading_segments=self.drop_leading_segments,
        )


class RentalSigningSessionStatus(models.TextChoices):
    """Status choices for rental signing sessions."""

    PENDING = 'pending', _('Pending')
    SIGNED = 'signed', _('Signed')
    EXPIRED = 'expired', _('Expired')


class RentalSigningSession(models.Model):
    """Short-lived session for QR-based phone signing of rental requests."""

    rental_request = models.ForeignKey(
        RentalRequest,
        on_delete=models.CASCADE,
        related_name='signing_sessions',
        verbose_name=_('Rental request'),
        blank=True,
        null=True,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rental_signing_sessions',
        verbose_name=_('Owner'),
        blank=True,
        null=True,
    )
    token = models.CharField(
        _('Token'),
        max_length=64,
        unique=True,
        db_index=True,
        default=uuid.uuid4,
    )
    status = models.CharField(
        _('Status'),
        max_length=16,
        choices=RentalSigningSessionStatus.choices,
        default=RentalSigningSessionStatus.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField(
        _('Expires at'),
        db_index=True,
    )
    signature_svg = models.TextField(
        _('Signature SVG'),
        blank=True,
        null=True,
    )
    signature_points = models.JSONField(
        _('Signature points'),
        blank=True,
        null=True,
        default=None,
    )
    signature_metadata = models.JSONField(
        _('Signature metadata'),
        blank=True,
        null=True,
        default=None,
    )
    signature_method = models.CharField(
        _('Signature method'),
        max_length=32,
        blank=True,
        null=True,
    )
    signer_ip = models.GenericIPAddressField(
        _('Signer IP'),
        blank=True,
        null=True,
    )
    signer_user_agent = models.TextField(
        _('Signer user agent'),
        blank=True,
        null=True,
    )
    signed_at = models.DateTimeField(
        _('Signed at'),
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(
        _('Created at'),
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        verbose_name = _('Rental Signing Session')
        verbose_name_plural = _('Rental Signing Sessions')
        ordering = ['-created_at']

    def __str__(self):
        if self.rental_request_id:
            return f'R-{self.rental_request_id} ({self.status})'
        return f'{self.token} ({self.status})'

    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at
