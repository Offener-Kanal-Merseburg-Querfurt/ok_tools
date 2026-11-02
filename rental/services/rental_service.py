"""
Rental service module containing business logic for rental operations.

This module encapsulates the business logic for rental operations,
separating it from views and models.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from django.db import transaction
from django.db.models import Q, Sum, Count
from django.utils import timezone
from django.conf import settings
import logging

from ..models import (
    RentalRequest, RentalItem, RentalTransaction, EquipmentSet,
    EquipmentSetItem, Room, RoomRental, EquipmentTemplate, EquipmentTemplateItem
)
from ..working_hours import validate_working_hours_period
from .inventory_service_interface import inventory_service


class RentalService:
    """
    Service class for rental operations.
    
    Encapsulates business logic for creating, updating, and managing rentals,
    equipment availability checking, room scheduling, and equipment set management.
    """
    
    @staticmethod
    def check_user_inventory_access(user, inventory_item_id: int) -> bool:
        """
        Check if user has access to inventory item based on membership status.
        
        Args:
            user: The user object
            inventory_item_id: The ID of the inventory item to check access for
            
        Returns:
            bool: True if user has access, False otherwise
        """
        from inventory.models import InventoryItem
        from rental.models import RentalConfig

        try:
            item = InventoryItem.objects.select_related('owner').get(id=inventory_item_id)
        except InventoryItem.DoesNotExist:
            return False

        if not item.available_for_rent or item.status != 'in_stock':
            return False

        orgs = RentalConfig.get_organizations_for(user)

        if orgs.exists():
            return bool(item.owner_id and orgs.filter(id=item.owner_id).exists())

        return inventory_service.can_user_access_item(user.id, inventory_item_id)
    
    @staticmethod
    def get_user_available_inventory(user) -> List[Dict[str, Any]]:
        """
        Get available inventory items for a user based on their access rights.
        
        Args:
            user: The user object
            
        Returns:
            List[Dict]: Available inventory items for the user
        """
        return inventory_service.get_available_items(user.id)
    
    @staticmethod
    def get_available_quantity_for_period(
        inventory_item_id: int,
        start_date: datetime,
        end_date: datetime,
        exclude_rental_request: Optional[int] = None
    ) -> int:
        """
        Calculate available quantity of an inventory item for a specific time period.
        
        Args:
            inventory_item_id: The ID of the inventory item to check
            start_date: Start of the rental period
            end_date: End of the rental period
            exclude_rental_request: Optional rental request ID to exclude from calculation
            
        Returns:
            int: Available quantity for the period
        """
        # Get total quantity of the item
        item_data = inventory_service.get_item_by_id(inventory_item_id)
        if not item_data:
            return 0
        total_quantity = item_data['quantity'] or 0
        
        # Get all rental items for this inventory item that overlap with the requested period
        conflicting_rentals = RentalItem.objects.filter(
            inventory_item_id=inventory_item_id,
            rental_request__status__in=['reserved', 'issued']
        )
        
        # Exclude specific rental request if provided
        if exclude_rental_request:
            conflicting_rentals = conflicting_rentals.exclude(
                rental_request_id=exclude_rental_request
            )
        
        # Filter by time overlap
        available_quantity = total_quantity
        for rental_item in conflicting_rentals:
            rental_start = rental_item.rental_request.requested_start_date
            rental_end = rental_item.rental_request.requested_end_date
            
            # Check time interval overlap
            if rental_start and rental_end:
                if (start_date < rental_end and end_date > rental_start):
                    # There is overlap, subtract the quantity based on rental status
                    rental_status = rental_item.rental_request.status
                    if rental_status == 'issued':
                        # For issued rentals, use quantity_issued (what's actually taken)
                        # If quantity_issued is 0 (edge case), fall back to quantity_requested
                        quantity_to_subtract = rental_item.quantity_issued or rental_item.quantity_requested or 0
                    else:
                        # For reserved rentals, use quantity_requested (what's reserved)
                        quantity_to_subtract = rental_item.quantity_requested or 0
                    
                    available_quantity -= quantity_to_subtract
        
        return max(0, available_quantity)
    
    @staticmethod
    def check_room_availability(
        room: Room, 
        start_date: datetime, 
        end_date: datetime,
        exclude_rental_request: Optional[int] = None
    ) -> bool:
        """
        Check if a room is available for the specified time period.
        
        Args:
            room: The room to check
            start_date: Start of the rental period
            end_date: End of the rental period
            exclude_rental_request: Optional rental request ID to exclude
            
        Returns:
            bool: True if room is available, False otherwise
        """
        return room.is_available_for_time(start_date, end_date, exclude_rental_request)
    
    @staticmethod
    def get_available_rooms(start_date: datetime, end_date: datetime) -> List[Room]:
        """
        Get list of available rooms for the specified time period.
        
        Args:
            start_date: Start of the rental period
            end_date: End of the rental period
            
        Returns:
            QuerySet: Available rooms
        """
        all_rooms = Room.objects.filter(is_active=True)
        available_rooms = []
        
        for room in all_rooms:
            if RentalService.check_room_availability(room, start_date, end_date):
                available_rooms.append(room)
        
        return available_rooms
    
    @staticmethod
    @transaction.atomic
    def create_rental_request(
        data_or_user,
        created_by_or_user=None,
        project_name_or_created_by=None,
        purpose: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        rental_type: str = 'equipment',
        notes: str = '',
        **kwargs
    ):
        """
        Create a new rental request.
        
        Can be called in two ways:
        1. With data dictionary (new API):
           create_rental_request(data, user, created_by, is_user_request=False)
        2. With individual parameters (old API):
           create_rental_request(user, created_by, project_name, purpose, start_date, end_date, rental_type, notes)
        
        Args (new API):
            data_or_user: Dictionary containing rental data (new API) or user object (old API)
            created_by_or_user: User creating the rental (new API) or created_by (old API)
            project_name_or_created_by: Not used (new API) or project_name (old API)
            purpose: Not used (new API) or purpose (old API)
            start_date: Not used (new API) or start_date (old API)
            end_date: Not used (new API) or end_date (old API)
            rental_type: Not used (new API) or rental_type (old API)
            notes: Not used (new API) or notes (old API)
            **kwargs: Additional keyword arguments including is_user_request (new API only)
            
        Returns:
            RentalRequest: The created rental request (old API)
            dict: Result with success status, rental_id or error message (new API)
        """
        # Extract is_user_request from kwargs if present
        is_user_request = kwargs.get('is_user_request', False)
        
        # Detect which API is being used by checking if first parameter is a dict
        if isinstance(data_or_user, dict):
            # New API: create_rental_request(data, user, created_by, is_user_request)
            data = data_or_user
            user = created_by_or_user
            created_by = project_name_or_created_by
            
            return RentalService._create_rental_request_from_data(data, user, created_by, is_user_request)
        else:
            # Old API: create_rental_request(user, created_by, project_name, purpose, start_date, end_date, rental_type, notes)
            user = data_or_user
            created_by = created_by_or_user
            project_name = project_name_or_created_by
            
            rental_request = RentalRequest.objects.create(
                user=user,
                created_by=created_by,
                project_name=project_name,
                purpose=purpose,
                requested_start_date=start_date,
                requested_end_date=end_date,
                rental_type=rental_type,
                notes=notes,
                status='draft'
            )
            
            return rental_request
    
    @staticmethod
    @transaction.atomic
    def _create_rental_request_from_data(
        data: Dict[str, Any],
        user,
        created_by,
        is_user_request: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new rental request from data dictionary.
        
        Args:
            data: Dictionary containing rental data:
                - project_name: str
                - purpose: str
                - start_date: str (ISO format)
                - end_date: str (ISO format)
                - action: str ('draft', 'reserved', 'issued')
                - items: List[Dict] with inventory_item_id, quantity_requested, notes
                - rooms: List[Dict] with room_id, people_count, notes
                - rental_type: str (optional, auto-detected if not provided)
                - notes: str (optional)
            user: The user requesting the rental
            created_by: The user creating the rental request
            is_user_request: Whether this is a user-initiated request
            
        Returns:
            dict: Result with success status, rental_id or error message
        """
        from django.utils.dateparse import parse_datetime
        from django.utils.translation import gettext_lazy as _
        
        try:
            # Extract and validate required fields
            project_name = data.get('project_name', '').strip()
            purpose = data.get('purpose', '').strip()
            start_date_str = data.get('start_date')
            end_date_str = data.get('end_date')
            action = data.get('action', 'draft')  # draft, reserved, issued
            items = data.get('items', [])
            rooms = data.get('rooms', [])
            notes = data.get('notes', '').strip()
            
            if not project_name:
                return {'success': False, 'error': _('Project name is required')}
            if not purpose:
                return {'success': False, 'error': _('Purpose is required')}

            room_has_own_times = rooms and any(
                r.get('start_date') or r.get('start_time') or r.get('end_date') or r.get('end_time')
                for r in rooms
            )
            if not start_date_str or not end_date_str:
                if not room_has_own_times:
                    return {'success': False, 'error': _('Start date and end date are required')}
                for r in rooms:
                    r_start = r.get('start_date', '')
                    r_start_time = r.get('start_time', '00:00')
                    r_end = r.get('end_date', '')
                    r_end_time = r.get('end_time', '23:59')
                    if r_start and (not start_date_str or r_start < start_date_str):
                        start_date_str = f"{r_start}T{r_start_time}"
                    if r_end and (not end_date_str or r_end > end_date_str):
                        end_date_str = f"{r_end}T{r_end_time}"
            
            # Parse dates
            start_date = parse_datetime(start_date_str)
            end_date = parse_datetime(end_date_str)
            
            if not start_date:
                # Try parsing as date only and add default time
                from django.utils.dateparse import parse_date
                date_only = parse_date(start_date_str.split('T')[0] if 'T' in start_date_str else start_date_str)
                if date_only:
                    start_date = timezone.make_aware(datetime.combine(date_only, datetime.min.time()))
            
            if not end_date:
                from django.utils.dateparse import parse_date
                date_only = parse_date(end_date_str.split('T')[0] if 'T' in end_date_str else end_date_str)
                if date_only:
                    end_date = timezone.make_aware(datetime.combine(date_only, datetime.max.time()))
            
            if not start_date or not end_date:
                return {'success': False, 'error': _('Invalid date format')}
            
            # Ensure timezone-aware
            if timezone.is_naive(start_date):
                start_date = timezone.make_aware(start_date)
            if timezone.is_naive(end_date):
                end_date = timezone.make_aware(end_date)
            
            if end_date <= start_date:
                return {'success': False, 'error': _('End date must be after start date')}

            is_valid_period, error_message = validate_working_hours_period(
                start_date, end_date, created_by)
            if not is_valid_period and not rooms:
                return {'success': False, 'error': error_message}
            
            # Validate that at least items or rooms are provided
            if not items and not rooms:
                return {'success': False, 'error': _('Please select at least one item or room')}
            
            # Determine rental type
            rental_type = data.get('rental_type')
            if not rental_type:
                if items and rooms:
                    rental_type = 'mixed'
                elif rooms:
                    rental_type = 'room'
                else:
                    rental_type = 'equipment'
            
            # Validate action
            if action not in ['draft', 'reserved', 'issued']:
                action = 'draft'

            # If user requests require approval, force 'draft' regardless of what client sends.
            if is_user_request:
                from rental.config import get_rental_user_request_requires_approval
                if get_rental_user_request_requires_approval():
                    action = 'draft'
            
            # For mixed rentals (rooms + equipment), if action is 'issued', 
            # create as 'reserved' first - equipment can be issued separately
            # Rooms always remain reserved and auto-return
            if rooms and action == 'issued':
                # Only change to reserved if there are no items (only rooms)
                # If there are items, keep 'issued' - items will be issued, rooms remain reserved
                if not items:
                    action = 'reserved'
                else:
                    # Mixed rental: create as reserved, equipment can be issued later
                    action = 'reserved'
            
            # Create rental request
            rental_request = RentalRequest.objects.create(
                user=user,
                created_by=created_by,
                project_name=project_name,
                purpose=purpose,
                requested_start_date=start_date,
                requested_end_date=end_date,
                rental_type=rental_type,
                notes=notes,
                status=action
            )
            
            # Add items
            if items:
                for item_data in items:
                    inventory_item_id = item_data.get('inventory_item_id') or item_data.get('inventory_id') or item_data.get('id')
                    quantity_requested = item_data.get('quantity_requested') or item_data.get('quantity', 1)
                    
                    if not inventory_item_id:
                        continue
                    
                    # Check user access
                    if not RentalService.check_user_inventory_access(user, inventory_item_id):
                        rental_request.delete()
                        return {'success': False, 'error': _('User does not have access to one or more selected items')}
                    
                    # Check availability
                    available_quantity = RentalService.get_available_quantity_for_period(
                        inventory_item_id,
                        start_date,
                        end_date,
                        rental_request.id
                    )
                    
                    if available_quantity < quantity_requested:
                        rental_request.delete()
                        return {
                            'success': False,
                            'error': _('Item is not available for the selected period. Available: {available}, requested: {requested}').format(
                                available=available_quantity,
                                requested=quantity_requested
                            )
                        }
                    
                    # Create rental item
                    # Note: quantity_issued will be set by transaction signal, not directly
                    rental_item = RentalItem.objects.create(
                        rental_request=rental_request,
                        inventory_item_id=inventory_item_id,
                        quantity_requested=quantity_requested,
                        quantity_issued=0,  # Will be set by transaction signal
                        notes=item_data.get('notes', '')
                    )
                    
                    # Create transaction for issued items
                    if action == 'issued':
                        RentalService.create_transaction(
                            rental_item=rental_item,
                            transaction_type='issue',
                            quantity=quantity_requested,
                            performed_by=created_by
                        )
            
            # Add rooms
            if rooms:
                for room_data in rooms:
                    room_id = room_data.get('room_id') or room_data.get('id')
                    if not room_id:
                        continue
                    
                    try:
                        room = Room.objects.get(id=room_id)
                    except Room.DoesNotExist:
                        rental_request.delete()
                        return {'success': False, 'error': _('Room not found')}
                    
                    # Get room-specific dates if provided, otherwise use general dates
                    from django.utils.dateparse import parse_datetime
                    from django.utils import timezone as tz
                    
                    room_start_date = start_date
                    room_end_date = end_date
                    
                    # Check if room has specific dates
                    if room_data.get('start_date') or room_data.get('start_time'):
                        room_start_str = room_data.get('start_date', '')
                        room_start_time = room_data.get('start_time', '00:00')
                        if room_start_str:
                            room_start_datetime_str = f"{room_start_str}T{room_start_time}"
                            room_start_date_parsed = parse_datetime(room_start_datetime_str)
                            if room_start_date_parsed:
                                room_start_date = tz.make_aware(room_start_date_parsed) if tz.is_naive(room_start_date_parsed) else room_start_date_parsed
                    
                    if room_data.get('end_date') or room_data.get('end_time'):
                        room_end_str = room_data.get('end_date', '')
                        room_end_time = room_data.get('end_time', '23:59')
                        if room_end_str:
                            room_end_datetime_str = f"{room_end_str}T{room_end_time}"
                            room_end_date_parsed = parse_datetime(room_end_datetime_str)
                            if room_end_date_parsed:
                                room_end_date = tz.make_aware(room_end_date_parsed) if tz.is_naive(room_end_date_parsed) else room_end_date_parsed
                    
                    # Check availability with room-specific dates
                    is_valid_room_period, error_message = validate_working_hours_period(
                        room_start_date,
                        room_end_date,
                        created_by,
                    )
                    if not is_valid_room_period:
                        rental_request.delete()
                        return {'success': False, 'error': error_message}

                    if not RentalService.check_room_availability(
                        room,
                        room_start_date,
                        room_end_date,
                        rental_request.id
                    ):
                        rental_request.delete()
                        return {'success': False, 'error': _('Room "{room_name}" is not available for the selected period').format(room_name=room.name)}
                    
                    # Create room rental with room-specific dates if different from general dates
                    room_rental_data = {
                        'rental_request': rental_request,
                        'room': room,
                        'people_count': room_data.get('people_count', 1),
                        'notes': room_data.get('notes', '')
                    }
                    
                    # Only set room-specific dates if they differ from general dates
                    if room_start_date != start_date or room_end_date != end_date:
                        room_rental_data['requested_start_date'] = room_start_date
                        room_rental_data['requested_end_date'] = room_end_date
                    
                    RoomRental.objects.create(**room_rental_data)

            # Notify admins and user if this is a user request that requires approval.
            if is_user_request and action == 'draft':
                from rental.config import get_rental_user_request_requires_approval
                if get_rental_user_request_requires_approval():
                    try:
                        from rental.email_approval import send_admin_approval_email, send_user_pending_email
                        send_admin_approval_email(rental_request=rental_request)
                        send_user_pending_email(rental_request=rental_request)
                    except Exception:
                        # Do not fail rental creation on notification errors.
                        logging.getLogger('django').exception(
                            "Failed to send rental approval email (rental_request_id=%s)", rental_request.id
                        )
            
            return {
                'success': True,
                'rental_id': rental_request.id,
                'status': rental_request.status
            }
            
        except Exception as e:
            import traceback
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def add_items_to_rental_request(
        rental_request: RentalRequest,
        items_data: List[Dict[str, Any]]
    ) -> List[RentalItem]:
        """
        Add items to a rental request.
        
        Args:
            rental_request: The rental request to add items to
            items_data: List of dictionaries containing item data
                       (inventory_item_id, quantity_requested, notes)
                       
        Returns:
            List[RentalItem]: List of created rental items
        """
        rental_items = []
        
        for item_data in items_data:
            # Check if user has access to this item
            if not RentalService.check_user_inventory_access(rental_request.user, item_data['inventory_item_id']):
                continue
                
            # Check availability
            available_quantity = RentalService.get_available_quantity_for_period(
                item_data['inventory_item_id'],
                rental_request.requested_start_date,
                rental_request.requested_end_date,
                rental_request.id if rental_request.id else None
            )
            
            if available_quantity >= item_data['quantity_requested']:
                rental_item = RentalItem.objects.create(
                    rental_request=rental_request,
                    inventory_item_id=item_data['inventory_item_id'],
                    quantity_requested=item_data['quantity_requested'],
                    notes=item_data.get('notes', '')
                )
                rental_items.append(rental_item)
        
        return rental_items
    
    @staticmethod
    def add_rooms_to_rental_request(
        rental_request: RentalRequest,
        rooms_data: List[Dict[str, Any]]
    ) -> List[RoomRental]:
        """
        Add rooms to a rental request.
        
        Args:
            rental_request: The rental request to add rooms to
            rooms_data: List of dictionaries containing room data
                        (room_id, people_count, notes, start_date, end_date - optional)
                        
        Returns:
            List[RoomRental]: List of created room rentals
        """
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone as tz
        
        room_rentals = []
        
        for room_data in rooms_data:
            room = Room.objects.get(id=room_data['room_id'])
            
            # Get room-specific dates if provided, otherwise use rental request dates
            room_start_date = rental_request.requested_start_date
            room_end_date = rental_request.requested_end_date
            
            # Check if room has specific dates
            if room_data.get('start_date') or room_data.get('start_time'):
                room_start_str = room_data.get('start_date', '')
                room_start_time = room_data.get('start_time', '00:00')
                if room_start_str:
                    room_start_datetime_str = f"{room_start_str}T{room_start_time}"
                    room_start_date_parsed = parse_datetime(room_start_datetime_str)
                    if room_start_date_parsed:
                        room_start_date = tz.make_aware(room_start_date_parsed) if tz.is_naive(room_start_date_parsed) else room_start_date_parsed
            
            if room_data.get('end_date') or room_data.get('end_time'):
                room_end_str = room_data.get('end_date', '')
                room_end_time = room_data.get('end_time', '23:59')
                if room_end_str:
                    room_end_datetime_str = f"{room_end_str}T{room_end_time}"
                    room_end_date_parsed = parse_datetime(room_end_datetime_str)
                    if room_end_date_parsed:
                        room_end_date = tz.make_aware(room_end_date_parsed) if tz.is_naive(room_end_date_parsed) else room_end_date_parsed
            
            # Check availability with room-specific dates
            is_valid_room_period, error_message = validate_working_hours_period(
                room_start_date,
                room_end_date,
                rental_request.created_by,
            )
            if not is_valid_room_period:
                continue

            if RentalService.check_room_availability(
                room,
                room_start_date,
                room_end_date,
                rental_request.id if rental_request.id else None
            ):
                room_rental_data = {
                    'rental_request': rental_request,
                    'room': room,
                    'people_count': room_data.get('people_count', 1),
                    'notes': room_data.get('notes', '')
                }
                
                # Only set room-specific dates if they differ from rental request dates
                if room_start_date != rental_request.requested_start_date or room_end_date != rental_request.requested_end_date:
                    room_rental_data['requested_start_date'] = room_start_date
                    room_rental_data['requested_end_date'] = room_end_date
                
                room_rental = RoomRental.objects.create(**room_rental_data)
                room_rentals.append(room_rental)
        
        return room_rentals
    
    @staticmethod
    @transaction.atomic
    def create_transaction(
        rental_item: Optional[RentalItem] = None,
        room: Optional[Room] = None,
        transaction_type: str = 'reserve',
        quantity: int = 1,
        performed_by=None,
        condition: str = '',
        notes: str = ''
    ) -> RentalTransaction:
        """
        Create a rental transaction (reserve, issue, return, cancel).
        
        Args:
            rental_item: The rental item (optional)
            room: The room (optional)
            transaction_type: Type of transaction
            quantity: Quantity for the transaction
            performed_by: User performing the transaction
            condition: Condition of the item (for returns)
            notes: Additional notes
            
        Returns:
            RentalTransaction: The created transaction
        """
        if not rental_item and not room:
            raise ValueError("Either rental_item or room must be provided")
        
        transaction = RentalTransaction.objects.create(
            rental_item=rental_item,
            room=room,
            transaction_type=transaction_type,
            quantity=quantity,
            performed_by=performed_by,
            condition=condition,
            notes=notes
        )
        
        # Update rental item quantities if applicable
        # Note: quantity_issued and quantity_returned are updated by the signal handler
        # We only need to update actual_return_date here for returns
        if rental_item:
            if transaction_type == 'return':
                rental_item.actual_return_date = timezone.now()
                rental_item.save(update_fields=['actual_return_date'])
        
        return transaction
    
    @staticmethod
    def apply_equipment_set_to_rental_request(
        equipment_set: EquipmentSet,
        rental_request: RentalRequest
    ) -> List[RentalItem]:
        """
        Apply an equipment set to a rental request.
        
        Args:
            equipment_set: The equipment set to apply
            rental_request: The rental request to apply the set to
            
        Returns:
            List[RentalItem]: List of created/updated rental items
        """
        return equipment_set.apply_to_rental_request(rental_request)
    
    @staticmethod
    def create_equipment_set(
        name: str,
        description: str,
        created_by,
        is_template: bool = False,
        items_data: List[Dict[str, Any]] = None
    ) -> EquipmentSet:
        """
        Create a new equipment set.
        
        Args:
            name: Name of the equipment set
            description: Description of the set
            created_by: User creating the set
            is_template: Whether this is a template set
            items_data: List of items to include in the set
                        (inventory_item_id, quantity, is_required, notes)
                        
        Returns:
            EquipmentSet: The created equipment set
        """
        equipment_set = EquipmentSet.objects.create(
            name=name,
            description=description,
            created_by=created_by,
            is_template=is_template
        )
        
        if items_data:
            for item_data in items_data:
                EquipmentSetItem.objects.create(
                    equipment_set=equipment_set,
                    inventory_item_id=item_data['inventory_item_id'],
                    quantity=item_data['quantity'],
                    is_required=item_data.get('is_required', True),
                    notes=item_data.get('notes', '')
                )
        
        return equipment_set
    
    @staticmethod
    def create_equipment_template(
        name: str,
        description: str,
        created_by,
        items_data: List[Dict[str, Any]] = None
    ) -> EquipmentTemplate:
        """
        Create a new equipment template.
        
        Args:
            name: Name of the template
            description: Description of the template
            created_by: User creating the template
            items_data: List of items to include in the template
                        (inventory_item_id, quantity)
                        
        Returns:
            EquipmentTemplate: The created equipment template
        """
        template = EquipmentTemplate.objects.create(
            name=name,
            description=description,
            created_by=created_by
        )
        
        if items_data:
            for item_data in items_data:
                EquipmentTemplateItem.objects.create(
                    template=template,
                    inventory_item_id=item_data['inventory_item_id'],
                    quantity=item_data['quantity']
                )
        
        return template
    
    @staticmethod
    def get_room_schedule(room: Room, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Get the schedule for a room within a date range.
        
        Args:
            room: The room to get schedule for
            start_date: Start of the date range
            end_date: End of the date range
            
        Returns:
            List[Dict]: List of scheduled rentals with details
        """
        room_rentals = RoomRental.objects.filter(
            room=room,
            rental_request__status__in=['reserved', 'issued']
        ).filter(
            Q(rental_request__requested_start_date__lte=end_date) &
            Q(rental_request__requested_end_date__gte=start_date)
        ).select_related('rental_request', 'rental_request__user')
        
        schedule = []
        for room_rental in room_rentals:
            schedule.append({
                'id': room_rental.rental_request.id,
                'project_name': room_rental.rental_request.project_name,
                'user': room_rental.rental_request.user.email,
                'start_date': room_rental.rental_request.requested_start_date,
                'end_date': room_rental.rental_request.requested_end_date,
                'status': room_rental.rental_request.status,
                'people_count': room_rental.people_count,
                'notes': room_rental.notes
            })
        
        return schedule
    
    @staticmethod
    def get_inventory_schedule(
        inventory_item_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """
        Get the schedule for an inventory item within a date range.
        
        Args:
            inventory_item_id: The ID of the inventory item to get schedule for
            start_date: Start of the date range
            end_date: End of the date range
            
        Returns:
            List[Dict]: List of scheduled rentals with details
        """
        rental_items = RentalItem.objects.filter(
            inventory_item_id=inventory_item_id,
            rental_request__status__in=['reserved', 'issued']
        ).filter(
            Q(rental_request__requested_start_date__lte=end_date) &
            Q(rental_request__requested_end_date__gte=start_date)
        ).select_related('rental_request', 'rental_request__user')
        
        schedule = []
        for rental_item in rental_items:
            schedule.append({
                'id': rental_item.rental_request.id,
                'project_name': rental_item.rental_request.project_name,
                'user': rental_item.rental_request.user.email,
                'start_date': rental_item.rental_request.requested_start_date,
                'end_date': rental_item.rental_request.requested_end_date,
                'status': rental_item.rental_request.status,
                'quantity_requested': rental_item.quantity_requested,
                'quantity_issued': rental_item.quantity_issued,
                'quantity_returned': rental_item.quantity_returned,
                'notes': rental_item.notes
            })
        
        return schedule
    
    @staticmethod
    def cancel_rental_request(rental_request: RentalRequest, performed_by) -> None:
        """
        Cancel a rental request and handle related transactions.
        
        Args:
            rental_request: The rental request to cancel
            performed_by: User performing the cancellation
        """
        with transaction.atomic():
            # Update status
            rental_request.status = 'cancelled'
            rental_request.save(update_fields=['status'])
            
            # Cancel all reservations for items
            for rental_item in rental_request.items.all():
                reserved_balance = rental_item.reserved_balance
                if reserved_balance > 0:
                    RentalService.create_transaction(
                        rental_item=rental_item,
                        transaction_type='cancel',
                        quantity=reserved_balance,
                        performed_by=performed_by,
                        notes=f"Cancelled rental request: {rental_request.project_name}"
                    )
    
    @staticmethod
    def extend_rental(
        rental_request: RentalRequest,
        new_end_date: datetime,
        performed_by
    ) -> bool:
        """
        Extend the end date of a rental request if possible.
        
        Args:
            rental_request: The rental request to extend
            new_end_date: New end date for the rental
            performed_by: User performing the extension
            
        Returns:
            bool: True if extension was successful, False otherwise
        """
        if new_end_date <= rental_request.requested_end_date:
            return False

        is_valid_period, error_message = validate_working_hours_period(
            rental_request.requested_start_date,
            new_end_date,
            performed_by,
        )
        if not is_valid_period:
            return False
        
        # Check availability for all items and rooms
        for rental_item in rental_request.items.all():
            available_quantity = RentalService.get_available_quantity_for_period(
                rental_item.inventory_item_id,
                rental_request.requested_end_date,
                new_end_date,
                rental_request.id
            )
            
            if available_quantity < (rental_item.quantity_issued or rental_item.quantity_requested or 0):
                return False
        
        for room_rental in rental_request.room_rentals.all():
            if not RentalService.check_room_availability(
                room_rental.room,
                rental_request.requested_end_date,
                new_end_date,
                rental_request.id
            ):
                return False
        
        # All checks passed, update the rental request
        rental_request.requested_end_date = new_end_date
        rental_request.save(update_fields=['requested_end_date'])
        
        return True
    
    @staticmethod
    def cancel_rental(rental_id, user):
        """
        Cancel a rental request.
        
        Cancels active rentals by creating appropriate transactions
        and updating the rental status to cancelled.
        
        Args:
            rental_id: ID of the rental request to cancel
            user: User performing the cancellation
            
        Returns:
            dict: Result with success status and message
        """
        try:
            from django.shortcuts import get_object_or_404
            from django.utils.translation import gettext_lazy as _
            
            rental_request = get_object_or_404(RentalRequest, id=rental_id)
            
            # Check if rental can be cancelled
            if rental_request.status not in ['draft', 'reserved', 'issued']:
                return {
                    'success': False,
                    'error': _('Only draft, reserved or issued rentals can be cancelled')
                }
            
            # Create cancellation transactions for all items
            for rental_item in rental_request.items.all():
                # Cancel reserved quantity (if any)
                reserved_qty = (rental_item.quantity_requested or 0) - (rental_item.quantity_issued or 0)
                if reserved_qty > 0:
                    RentalTransaction.objects.create(
                        rental_item=rental_item,
                        transaction_type='cancel',
                        quantity=reserved_qty,
                        performed_by=user,
                        notes=_('Cancelled reserved quantity via admin interface')
                    )
                
                # Return issued quantity (if any)
                issued_qty = (rental_item.quantity_issued or 0) - (rental_item.quantity_returned or 0)
                if issued_qty > 0:
                    RentalTransaction.objects.create(
                        rental_item=rental_item,
                        transaction_type='return',
                        quantity=issued_qty,
                        performed_by=user,
                        notes=_('Returned issued quantity due to cancellation via admin interface')
                    )
            
            # Update rental request status
            rental_request.status = 'cancelled'
            rental_request.actual_end_date = timezone.now()
            rental_request.save(update_fields=['status', 'actual_end_date'])
            
            return {
                'success': True,
                'message': _('Rental request {rental_id} has been cancelled successfully').format(rental_id=rental_id or '')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def reopen_rental(rental_id):
        """
        Reopen a cancelled rental as a draft.

        Only rentals cancelled before anything was issued can be reopened;
        the draft can then be edited and confirmed again, which re-runs the
        normal reservation flow.

        Args:
            rental_id: ID of the rental request to reopen

        Returns:
            dict: Result with success status and message
        """
        from django.shortcuts import get_object_or_404
        from django.utils.translation import gettext as _

        rental_request = get_object_or_404(RentalRequest, id=rental_id)

        if rental_request.status != 'cancelled':
            return {
                'success': False,
                'error': _('Only cancelled rentals can be reopened'),
            }

        if rental_request.items.filter(quantity_issued__gt=0).exists():
            return {
                'success': False,
                'error': _('Rentals with issued items cannot be reopened'),
            }

        rental_request.status = 'draft'
        rental_request.actual_end_date = None
        rental_request.save(update_fields=['status', 'actual_end_date'])

        return {'success': True, 'status': rental_request.status}

    @staticmethod
    def return_items(items_data, user):
        """
        Return selected items (creates RentalTransaction 'return').
        
        Processes item returns and updates rental status when all items
        in a rental request are fully returned.
        
        Args:
            items_data: List of items to return with rental_item_id and quantity
            user: User performing the return
            
        Returns:
            dict: Result with success status
        """
        try:
            from django.shortcuts import get_object_or_404
            
            for entry in items_data:
                rental_item_id = entry['rental_item_id']
                qty = int(entry['quantity'])
                rental_item = get_object_or_404(RentalItem, id=rental_item_id)
                
                RentalService.create_transaction(
                    rental_item=rental_item,
                    transaction_type='return',
                    quantity=qty,
                    performed_by=user,
                )
                
                # Update actual return date when item is fully returned
                ri = RentalItem.objects.get(id=rental_item_id)
                if (ri.quantity_issued or 0) <= (ri.quantity_returned or 0):
                    # Item is fully returned - set actual return date
                    ri.actual_return_date = timezone.now()
                    ri.save(update_fields=['actual_return_date'])
                    
                    req = ri.rental_request
                    # Check if all equipment items in the rental request are returned
                    # Note: Rooms are handled separately via automatic expiration
                    # For mixed rentals, we only check equipment items for 'returned' status
                    has_equipment = req.items.exists()
                    if has_equipment:
                        open_left = any((x.quantity_issued or 0) > (x.quantity_returned or 0) for x in req.items.all())
                        if not open_left:
                            req.status = 'returned'
                            req.actual_end_date = timezone.now()
                            req.save(update_fields=['status', 'actual_end_date'])
            
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
