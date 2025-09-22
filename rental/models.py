from django.db import models
from django.utils.translation import gettext_lazy as _


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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Django model metadata for ``RentalRequest``."""

        verbose_name = _('Rental request')
        verbose_name_plural = _('Rental requests')
        ordering = ['-created_at']

    def __str__(self) -> str:
        """Return human-readable representation."""
        return f"{self.project_name} ({self.user})"

    def __init__(self, *args, **kwargs):
        """Save original state for change auditing."""
        super().__init__(*args, **kwargs)
        # Safely read values without triggering relation descriptors on add view
        original = {}
        for field in self._meta.fields:
            attr_name = getattr(field, 'attname', field.name)
            original[field.name] = getattr(self, attr_name, None)
        self._original_state = type('OriginalState', (), original)

    def can_user_access_item(self, inventory_item):
        """Check user access rights to inventory based on user status."""
        if not getattr(inventory_item, 'available_for_rent', False):
            return False

        # Profile can be null in rare cases — protect against it
        user_profile = getattr(self.user, 'profile', None)
        owner_name = inventory_item.owner.name if getattr(inventory_item, 'owner', None) else ""

        if user_profile and getattr(user_profile, 'member', False):
            # Member can take MSA and OKMQ
            return owner_name in ['MSA', 'OKMQ']
        # User only MSA
        return owner_name == 'MSA'

    def get_available_inventory(self):
        """Get available inventory for rental considering user rights."""
        from django.db.models import Q
        from inventory.models import InventoryItem

        available_items = InventoryItem.objects.filter(
            available_for_rent=True,
            status='in_stock',
        )

        user_profile = getattr(self.user, 'profile', None)
        if user_profile and getattr(user_profile, 'member', False):
            available_items = available_items.filter(owner__name__in=['MSA', 'OKMQ'])
        else:
            available_items = available_items.filter(owner__name='MSA')

        return available_items

    @property
    def total_items_count(self):
        """Total number of items in the request (by quantity_requested)."""
        from django.db.models import Sum
        return self.items.aggregate(total=Sum('quantity_requested'))['total'] or 0

    @property
    def has_rooms(self):
        """Check if there are rented rooms."""
        return self.room_rentals.exists()

    @property
    def total_rooms_count(self):
        """Total number of rented rooms."""
        return self.room_rentals.count()

    def get_room_summary(self):
        """Get brief information about rooms."""
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

    def clean(self):
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

    def is_available_for_time(self, start_date, end_date, exclude_rental_request=None):
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
            rental_start = rental.rental_request.requested_start_date
            rental_end = rental.rental_request.requested_end_date

            # Check time interval overlap
            if rental_start and rental_end:
                # There is overlap if:
                # 1. New time starts before existing ends AND ends after existing starts
                # 2. Or new time completely contains existing
                if (start_date < rental_end and end_date > rental_start):
                    return False

        return True

    def get_conflicting_rentals(self, start_date, end_date, exclude_rental_request=None):
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
            rental_start = rental.rental_request.requested_start_date
            rental_end = rental.rental_request.requested_end_date

            if rental_start and rental_end:
                if (start_date < rental_end and end_date > rental_start):
                    conflicts.append(rental)

        return conflicts


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
    notes = models.TextField(
        blank=True,
        verbose_name=_('Notes'),
        help_text=_('Additional notes for room rental'),
    )

    class Meta:
        """Django model metadata for ``RoomRental``."""

        verbose_name = _('Room rental')
        verbose_name_plural = _('Room rentals')
        unique_together = ['rental_request', 'room']

    def __str__(self):
        """Return human-readable representation."""
        return f"{self.room.name} - {self.rental_request.project_name}"

    @property
    def is_expired(self) -> bool:
        """Check if room rental time has expired."""
        from django.utils import timezone
        if not self.rental_request:
            return False

        # Get end time from rental_request
        end_datetime = self.rental_request.requested_end_date
        if not end_datetime:
            return False

        return timezone.now() > end_datetime

    @property
    def time_until_expiry(self) -> int:
        """Return number of minutes until rental expires."""
        from django.utils import timezone
        if not self.rental_request or not self.rental_request.requested_end_date:
            return 0

        now = timezone.now()
        end_time = self.rental_request.requested_end_date

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

    def __str__(self):
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

    def __str__(self):
        return f"{self.template.name} - {self.inventory_item.description} ({self.quantity})"
