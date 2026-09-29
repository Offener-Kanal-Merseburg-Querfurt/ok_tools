from . import label_formats
from . import label_layout
from .config import get_rental_working_hours
from .config import get_rental_working_hours_summary_text
from .formatting import format_booked_period
from .models import EquipmentSet
from .models import EquipmentSetItem
from .models import RentalConfig
from .models import RentalIssue
from .models import RentalItem
from .models import RentalRequest
from .models import RentalSigningSession
from .models import RentalSigningSessionStatus
from .models import RentalTransaction
from .models import Room
from .models import RoomImage
from .models import RoomRental
from .permissions import CanCreateRentalRequest
from .permissions import IsAuthenticatedAndMemberOrReadOnly
from .permissions import StaffCanIssuePermission
from .serializers import EquipmentSetItemSerializer
from .serializers import EquipmentSetSerializer
from .serializers import InventoryItemSerializer
from .serializers import RentalIssueSerializer
from .serializers import RentalItemSerializer
from .serializers import RentalRequestSerializer
from .serializers import RentalTransactionSerializer
from .services import RentalService
from .services.barcode_service import BarcodeService
from .services.label_printer_service import LabelPrinterError
from .services.label_printer_service import LabelPrinterService
from .services.label_printer_service import PrinterSettings
from .services.rental_email import send_issued_confirmation_email
from .services.rental_email import send_reminder_email
from .services.rental_email import send_return_receipt_email
from .working_hours import get_day_working_window
from .working_hours import validate_working_hours_period
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
from defusedxml.ElementTree import fromstring as defused_fromstring
from defusedxml.common import DefusedXmlException
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.cache import cache
from django.db import transaction
from django.db.models import Case
from django.db.models import CharField
from django.db.models import Count
from django.db.models import F
from django.db.models import Max
from django.db.models import Q
from django.db.models import Value
from django.db.models import When
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotFound
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import NoReverseMatch
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView
from django.views.generic import TemplateView
from django.views.generic import View
from django_filters.rest_framework import DjangoFilterBackend
from inventory.models import Category
from inventory.models import InventoryItem
from inventory.models import Organization
from registration.models import OKUser
from registration.models import Profile
from rental.services.inventory_service_interface import inventory_service
from rest_framework import filters
from rest_framework import permissions
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from types import SimpleNamespace
from typing import Any
import base64
import io
import json
import logging
import mimetypes
import qrcode
import uuid
import xml.etree.ElementTree as ET


logger = logging.getLogger('django')

RENTAL_PROCESS_INITIAL_USER_LIMIT = 20
RENTAL_PROCESS_ACTIVE_STATUSES = ('reserved', 'issued')
RENTAL_PROCESS_COUNTED_STATUSES = ('reserved', 'issued', 'returned', 'closed')



def _iter_time_slots(target_date, step_minutes):
    start_at, end_at = get_day_working_window(target_date)
    if not start_at or not end_at:
        return []

    slots = []
    current = start_at
    while current < end_at:
        slot_end = current + timedelta(minutes=step_minutes)
        if slot_end > end_at:
            break
        slots.append((current, slot_end))
        current = slot_end

    return slots
class DefaultPagination(PageNumberPagination):
    """
    Default pagination configuration for rental API views.

    Provides consistent pagination across all rental-related endpoints
    with configurable page size and reasonable limits.
    """

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200


def _add_sidebar_counts(context):
    now = timezone.now()
    base = RentalRequest.objects.all()
    context['sidebar'] = {
        'all_count': base.count(),
        'issued_count': base.filter(status='issued').count(),
        'overdue_count': base.filter(status='issued', requested_end_date__lt=now).count(),
        'due_today_count': base.filter(status='issued', requested_end_date__date=now.date()).count(),
        'pending_approval_count': base.filter(status='draft').count(),
    }


def _user_display_name(user):
    profile = getattr(user, 'profile', None)
    if profile and profile.first_name and profile.last_name:
        return f'{profile.first_name} {profile.last_name}'
    if profile and profile.first_name:
        return profile.first_name

    full_name = user.get_full_name().strip() if user else ''
    if full_name:
        return full_name

    return user.email if user and user.email else ''


def serialize_user(user):
    profile = getattr(user, 'profile', None)
    name = _user_display_name(user)
    name_parts = [part for part in name.split() if part]
    initials = ''.join(part[0] for part in name_parts[:2]).upper() if name_parts else '?'
    org = '—'
    if profile and profile.media_authority:
        org = profile.media_authority.full_name or profile.media_authority.name or '—'

    # Same order as RentalConfig.get_organizations_for: staff win, then the
    # mutually exclusive profile flags, then plain user. `role_key` is the
    # stable value the frontend styles on; `role` is only the label.
    if user and user.is_staff:
        role_key, role = 'employee', _('Staff')
    elif profile and profile.member:
        role_key, role = 'member', _('Member')
    elif profile and profile.rental_only:
        role_key, role = 'rental_only', _('Rental only')
    else:
        role_key, role = 'user', _('User')

    rental_count = getattr(user, 'rental_count', None)
    if rental_count is not None:
        past_count = rental_count
    else:
        rental_count = RentalRequest.objects.filter(
            user=user,
            status__in=RENTAL_PROCESS_COUNTED_STATUSES,
        ).count()
        past_count = max(0, rental_count - 1)

    return {
        'id': user.pk,
        'initials': initials,
        'name': name,
        'org': org,
        'role': str(role),
        'role_key': role_key,
        'past': past_count,
        'past_count': past_count,
        'phone': ((profile.phone_number or profile.mobile_number) if profile else ''),
        'email': user.email or '',
        'warn': None,
    }


def get_initial_rental_process_users(limit=RENTAL_PROCESS_INITIAL_USER_LIMIT):
    users = OKUser.objects.select_related('profile', 'profile__media_authority').filter(
        is_active=True,
    ).annotate(
        active_rental_count=Count(
            'rentalrequest',
            filter=Q(rentalrequest__status__in=RENTAL_PROCESS_ACTIVE_STATUSES),
            distinct=True,
        ),
        latest_rental_at=Max(
            'rentalrequest__created_at',
            filter=Q(rentalrequest__status__in=RENTAL_PROCESS_COUNTED_STATUSES),
        ),
        rental_count=Count(
            'rentalrequest',
            filter=Q(rentalrequest__status__in=RENTAL_PROCESS_COUNTED_STATUSES),
            distinct=True,
        ),
    )
    borrowers = list(users.filter(rental_count__gt=0).order_by(
        '-active_rental_count',
        F('latest_rental_at').desc(nulls_last=True),
        '-rental_count',
        '-date_joined',
    )[:limit])
    remaining = limit - len(borrowers)
    if remaining <= 0:
        return borrowers

    borrower_ids = [user.pk for user in borrowers]
    staff_fallback = list(users.filter(is_staff=True).exclude(pk__in=borrower_ids).order_by(
        '-is_staff',
        '-date_joined',
    )[:remaining])
    return borrowers + staff_fallback


def serialize_rental(rental):
    overdue_days = 0
    effective_status = rental.status
    now = timezone.now()
    if rental.status == 'issued' and rental.requested_end_date and rental.requested_end_date < now:
        effective_status = 'overdue'
        overdue_days = (now - rental.requested_end_date).days

    return {
        'pk': rental.pk,
        'id': f'R-{rental.created_at.strftime("%y%m")}-{rental.pk:04d}',
        'project': rental.project_name or '',
        'purpose': rental.purpose or '',
        'status': effective_status,
        'from_at': rental.requested_start_date.isoformat() if rental.requested_start_date else None,
        'to_at': rental.requested_end_date.isoformat() if rental.requested_end_date else None,
        'to_iso': rental.requested_end_date.strftime('%Y-%m-%dT%H:%M') if rental.requested_end_date else '',
        'overdue_days': overdue_days,
        'user': serialize_user(rental.user),
        'issued_by': _user_display_name(rental.created_by) if rental.created_by else None,
        'created_at': rental.created_at.isoformat() if rental.created_at else None,
        'internal_note': rental.notes or '',
        'has_signature': rental.has_any_signature(),
        'item_count': rental.items.count(),
        'room_count': rental.room_rentals.count(),
    }


def serialize_item(rental_item):
    inventory_item = rental_item.inventory_item
    category = inventory_item.category
    return {
        'id': rental_item.pk,
        'name': inventory_item.description or '',
        'num': inventory_item.inventory_number or '',
        'cat': category.name if category else '',
        'loc': inventory_item.location.full_path if inventory_item.location else '',
        'owner': inventory_item.owner.name if inventory_item.owner else '',
        'notes': rental_item.notes or '',
        'qty_requested': rental_item.quantity_requested,
        'qty_issued': rental_item.quantity_issued,
        'qty_returned': rental_item.quantity_returned,
        'issued_at': rental_item.rental_request.actual_start_date.isoformat() if rental_item.rental_request.actual_start_date else None,
    }


def _frontend_flags():
    """Return the switches the React islands read from ``rr-flags``."""
    from .config import get_rental_scan_sound_enabled

    return {'scan_sound': bool(get_rental_scan_sound_enabled())}


def _i18n_bundle():
    return {
        # Status pills
        'status.draft': str(_('Draft')),
        'status.reserved': str(_('Reserved')),
        'status.issued': str(_('Issued')),
        'status.returned': str(_('Returned')),
        'status.overdue': str(_('Overdue')),
        'status.cancelled': str(_('Cancelled')),
        # Wizard - step titles and hints
        'wiz.title': _('Create rental'),
        'wiz.sub': _('Reserve items and rooms for a user'),
        'wiz.guided': _('Guided'),
        'wiz.quick': _('Quick'),
        'wiz.step': _('Step'),
        'wiz.step1': _('User'),
        'wiz.step2': _('Time & conflicts'),
        'wiz.step3': _('Items & rooms'),
        'wiz.step4': _('Review & confirm'),
        'wiz.no_user': _('Not selected'),
        'wiz.skipped_rooms': _('Skipped (rooms only)'),
        'wiz.items': _('items'),
        'wiz.rooms': _('rooms'),
        'wiz.enlarge_photo': _('Click to enlarge'),
        'wiz.send_confirm': _('Send confirmation'),
        # Wizard - step 1 user
        'wiz.who': _('Who is this rental for?'),
        'wiz.who_sub': _('Pick an existing user or create a new account.'),
        'wiz.search_user': _('Search by name, email, student ID…'),
        'wiz.new_user': _('New user'),
        'wiz.user': _('User'),
        'wiz.need_user': _('Please select a user first'),
        'wiz.past_rentals': _('past rentals'),
        # Wizard - step 2 time
        'wiz.when': _('When do you need it?'),
        'wiz.when_sub': _('Select a date range. Working hours are shown below.'),
        'wiz.period': _('Period'),
        'wiz.hours': _('Working hours'),
        'wiz.availability': _('availability'),
        'wiz.need_dates': _('Please select start and end dates'),
        'wiz.warn.closed': _('The selected day is closed.'),
        'wiz.warn.hours': _('Outside configured working hours.'),
        'wiz.warn.reversed': _('End date must be after start date.'),
        'wiz.rooms_skip_title': _('Room-only rental'),
        'wiz.rooms_skip_hint': _('Each room has its own time slot. You can skip this step.'),
        # Wizard - step 3 items
        'wiz.equipment': _('Equipment'),
        'wiz.rooms_tab': _('Rooms'),
        'wiz.equipment_only_hint': _('Select equipment to rent.'),
        'wiz.rooms_only_hint': _('Select rooms to reserve.'),
        'wiz.search_items': _('Search items…'),
        'wiz.in_cat': _('in'),
        'wiz.available': _('Available'),
        'wiz.no_items': _('No items match your search.'),
        'wiz.tap_to_add': _('Tap + to add items.'),
        'wiz.clear': _('Clear'),
        'wiz.no_users': _('No users match your search.'),
        'wiz.need_period': _('Please set the pickup and return time.'),
        'sig.qr_title': _('Sign with phone'),
        'sig.print': _('Sign on paper'),
        'sig.print_desc': _('Print the issue slip and sign it by hand'),
        'sig.print_multi': _('Items of different owners are printed on '
                             'different forms. Print each slip the rental '
                             'needs.'),
        'btn.print': _('Print'),
        'btn.done': _('Done'),
        'btn.close': _('Close'),
        'wiz.of': _('of'),
        'wiz.free': _('free'),
        'wiz.per_room': _('per room'),
        'wiz.reserved': _('Reserved'),
        'wiz.issued_count': _('issued'),
        'wiz.scan': _('Scan item'),
        'wiz.scan_hint': _('Scan barcode to add item'),
        'wiz.confirm': _('Confirm'),
        'wiz.no_items_selected': _('No items or rooms selected'),
        'wiz.need_items': _('Please select at least one item or room'),
        # Wizard - step 4 review
        'wiz.review': _('Review & confirm'),
        'wiz.review_sub': _('Check your selection and submit.'),
        'wiz.project': _('Project'),
        'wiz.project_ph': _('Project name'),
        'wiz.project_req': _('Required — please enter a project name'),
        'wiz.no_items_rooms': _('Please select at least one item or room.'),
        'wiz.purpose': _('Purpose'),
        'wiz.purpose_ph': _('What is this rental for?'),
        'wiz.notifications': _('Notifications'),
        'wiz.notify_email': _('Send email notification to user'),
        'wiz.reserved_until': _('Reserved until'),
        'wiz.return_by': _('Return by'),
        'wiz.pickup': _('Pickup'),
        'wiz.returns': _('Returns'),
        'wiz.items_label': _('Items'),
        'wiz.rooms_label': _('Rooms'),
        'wiz.what_need': _('What do you need?'),
        'wiz.total': _('Total'),
        'wiz.your_booking': _('Your booking'),
        'wiz.add_items': _('Add items'),
        'wiz.add_rooms': _('Add rooms'),
        # Quick rental
        'quick.title': _('Quick rental'),
        'quick.today_tomorrow': _('Today / Tomorrow'),
        'quick.7days': _('Next 7 days'),
        'quick.afternoon': _('Afternoon'),
        'quick.weekend': _('Weekend'),
        # Buttons
        'btn.back': _('Back'),
        'btn.next': _('Next'),
        'btn.cancel': _('Cancel'),
        'btn.confirm_send': _('Create rental'),
        'btn.issue_now': _('Issue now'),
        'btn.sending': _('Creating…'),
        # Cart / items
        'cart.title': _('Selected items'),
        # Errors
        'err.create': _('Could not create rental: '),
        'err.extend': _('Could not extend rental: '),
        'err.change_user': _('Could not change user: '),
        'err.change_period': _('Could not change period: '),
        'err.sign_session': _('Could not create signing session: '),
        'err.save_sig': _('Failed to save signature.'),
        'err.swap': _('Could not swap item: '),
        'err.add_items': _('Could not add items: '),
        'err.scan_not_found': _('Item not found'),
        # Room
        'room.available': _('Available'),
        'room.booked_at': _('Already booked:'),
        'room.busy': _('booked'),
        'room.check': _('Check availability'),
        'room.check_error': _('Error checking availability'),
        'room.day_closed': _('Day is closed'),
        'room.day_overview': _('Day overview'),
        'room.free': _('free'),
        'room.end_date': _('End date'),
        'room.end_time': _('End time'),
        'room.not_available': _('Not available'),
        'room.no_future_slots': _('No reservable time remains on this day.'),
        'room.open': _('Open'),
        'room.past': _('past'),
        'room.remove': _('Remove'),
        'room.reserve': _('Reserve room'),
        'room.restricted': _('Restricted'),
        'room.day_closed': _('The day is closed'),
        'room.need_period': _('Please set dates and times in step 2 first.'),
        'room.checking': _('Checking availability…'),
        'room.available': _('Available'),
        'room.check_failed': _('Could not check availability'),
        'room.check_error': _('Could not check availability'),
        'room.restricted': _('Restricted'),
        'room.start_date': _('Start date'),
        'room.start_time': _('Start time'),
        'room.booked': _('Booked'),
        'rooms.none': _('No rooms booked in this rental.'),
        # Tags
        'tag.booked': _('Booked'),
        'tag.in_stock': _('In stock'),
        'tag.issued': _('Issued'),
        'tag.out': _('Out'),
        'tag.reserved': _('Reserved'),
        'tag.returned': _('Returned'),
        # Misc
        'from': _('From'),
        'to': _('To'),
        'loading': _('Loading…'),
        'err.return': _('Could not submit return: '),
        'ret.returning': _('returning'),
        'ret.items': _('items'),
        'ret.scan_barcode': _('Scan Barcode'),
        'ret.scan_ph': _('Scan or type inventory number…'),
        'ret.scan_failed': _('Scan failed.'),
        'ret.returned': _('returned'),
        'ret.progress': _('Progress'),
        'ret.checked': _('checked'),
        'ret.issues': _('Issues'),
        'ret.due_by': _('Due by'),
        'btn.complete_return': _('Complete return'),
        'ret.heading': _('Equipment returning'),
        'ret.sub': _("Tick off items as the user hands them back. Mark condition if something's not right."),
        'btn.reset': _('Reset'),
        'btn.all_ok': _('All returned, all OK'),
        'ret.col.item': _('Item'),
        'ret.col.returned': _('Returned'),
        'ret.col.condition': _('Condition'),
        'ret.col.note': _('Issue note'),
        'ret.issued': _('issued'),
        'ret.back': _('back'),
        'ret.ok': _('OK'),
        'ret.minor': _('Minor'),
        'ret.damage': _('Damage'),
        'ret.logged': _('Logged'),
        'ret.add_note': _('Add note'),
        'ret.log_for': _('Log issue for'),
        'ret.desc_ph': _("Describe what's wrong…"),
        'ret.charge': _('Charge user (recoverable damage)'),
        'ret.hold_out': _('Hold item out of pool until reviewed'),
        'ret.int_note': _('Return note (internal)'),
        'ret.int_note_ph': _('Anything to remember for next time?'),
        'ret.email_receipt': _('Email return receipt to user'),
        'ret.close': _('Close rental after return'),
        'ret.audit': _('Flag for inventory audit'),
        'ret.email_help_on': _('Checked: the user receives a return receipt by email.'),
        'ret.email_help_off': _('Unchecked: the return is saved without sending a receipt email.'),
        'ret.close_help_on': _('Checked: after all issued items are back, the rental is closed immediately and no separate Close rental step is needed.'),
        'ret.close_help_off': _('Unchecked: the rental stays returned, so staff can review it and close it later.'),
        'ret.audit_help_on': _('Checked: an inventory audit issue is created for each returned item.'),
        'ret.audit_help_off': _('Unchecked: no audit issue is created unless an item condition note is entered.'),
        'ret.options_explain': _('What these options do'),
        'add_items.title': _('Add items to rental'),
        'add_items.search': _('Search inventory…'),
        'add_items.none': _('No available items found'),
        'add_items.selected': _('selected'),
        'add_items.confirm': _('Add selected items'),
        'err.add_items': _('Could not add items: '),
        'tab.equipment': _('Equipment'),
        'tab.rooms': _('Rooms'),
        'tab.issues': _('Issues'),
        'tab.history': _('History'),
        'tab.equipment_sets': _('Sets'),
        'tab.sets': _('Sets'),
        'sets.none': _('No equipment sets available.'),
        'sets.items': _('items'),
        'btn.add_set': _('Add'),
        'confirm.add_set': _('Add all items from set to rental?'),
        'err.load_sets': _('Could not load equipment sets.'),
        'err.set_empty': _('This set has no items.'),
        'err.add_set': _('Could not add set'),
        'sig.title': _('Digital Signature'),
        'sig.choose': _('Choose a signing method. Drawing directly is recommended for tablets.'),
        'sig.draw_here': _('Draw here'),
        'sig.draw_desc': _('Draw directly on this device'),
        'sig.qr_phone': _('Sign with phone'),
        'sig.qr_desc': _('Scan QR code with your phone'),
        'sig.draw_title': _('Draw your signature'),
        'sig.draw_hint': _('Sign below using your finger or stylus.'),
        'sig.clear': _('Clear'),
        'sig.submit': _('Submit signature'),
        'sig.saving': _('Saving…'),
        'sig.scan_qr': _('Scan the QR code with your phone to sign'),
        'sig.expired': _('Signing session expired. Please try again.'),
        'sig.retry': _('Retry'),
        'sig.auto_check': _('Status will update automatically'),
        'sig.waiting': _('Waiting for signature…'),
        'sig.received_title': _('Signature received'),
        'sig.received_desc': _('The phone signature was transferred to this rental. The page will update automatically.'),
        'sig.signed': _('Signed'),
        'sig.draw_empty': _('Please draw a signature first.'),
        'confirm.mark_issued': _('Mark this rental as issued?'),
        'confirm.cancel': _('Cancel this rental?'),
        'confirm.close': _('Close this rental?'),
        'confirm.remove': _('Remove this item from the rental?'),
        'confirm.draft': _('Confirm this rental? It will become reserved.'),
        'extend.title': _('Extend return deadline'),
        'extend.from': _('from'),
        'extend.to': _('to'),
        'extend.reason': _('Reason (shown to user)…'),
        'item.location': _('Location'),
        'item.owner': _('Owner dept.'),
        'item.issued_at': _('Issued at'),
        'item.notes': _('Asset notes'),
        'item.swap': _('Swap unit'),
        'item.remove': _('Remove from rental'),
        'item.report': _('Report issue'),
        'btn.mark_issued': _('Mark issued'),
        'btn.request_signature': _('Request signature'),
        'btn.extend': _('Extend'),
        'btn.start_return': _('Start return'),
        'btn.edit_items': _('Edit items'),
        'btn.change_user': _('Change user'),
        'btn.edit_period': _('Edit period'),
        'btn.resend': _('Resend confirmation'),
        'btn.export_pdf': _('Export as PDF'),
        'btn.cancel_rental': _('Cancel rental'),
        'btn.close_rental': _('Close rental'),
        'btn.confirm': _('Confirm'),
        'btn.send_reminder': _('Send reminder'),
        'btn.add_item': _('Add item'),
        'btn.remove': _('Remove from rental'),
        'btn.report_issue': _('Report issue'),
        'btn.log_issue': _('Log issue'),
        'btn.swap': _('Swap unit'),
        'btn.swap_confirm': _('Confirm swap'),
        'btn.save_period': _('Save period'),
        'btn.issue_now': _('Issue now'),
        'btn.complete_return': _('Complete return'),
        'btn.all_ok': _('All returned, all OK'),
        'btn.reset': _('Reset'),
        'btn.submit': _('Submit'),
        'btn.change_user': _('Change user'),
        'btn.cancel': _('Cancel'),
        'sev.minor': _('Minor'),
        'sev.major': _('Major'),
        'sev.critical': _('Critical'),
        'issues.note': _("Issues are logged during return — they don't affect item availability until closed."),
        'issues.none': _('No issues logged.'),
        'report.title': _('Log issue'),
        'report.title_item': _('Report issue'),
        'report.severity': _('Severity'),
        'report.description': _('Description'),
        'report.placeholder': _('Describe the issue…'),
        'swap.title': _('Swap'),
        'swap.search': _('Search inventory…'),
        'swap.no_results': _('No items found'),
        'swap.unavailable': _('Unavailable'),
        'change_user.title': _('Change user'),
        'change_user.search': _('Search by name, email…'),
        'change_user.no_results': _('No users found'),
        'change_user.type_hint': _('Type at least 2 characters to search'),
        'change_period.title': _('Edit rental period'),
        'change_period.from': _('Pickup date'),
        'change_period.to': _('Return date'),
        'change_period.required': _('Both dates are required.'),
        'btn.save_room': _('Save'),
        'btn.add_room': _('Add room'),
        'add_room.title': _('Add room to rental'),
        'add_room.no_rooms': _('No rooms available.'),
        'add_room.free': _('Free'),
        'add_room.occupied': _('Occupied'),
        'confirm.remove_room': _('Remove this room from the rental?'),
        'room.start_date': _('Start date'),
        'room.start_time': _('Start time'),
        'room.end_date': _('End date'),
        'room.end_time': _('End time'),
        'room.booked': _('Booked'),
        'tab.equipment': _('Equipment'),
        'tab.rooms': _('Rooms'),
        'tab.issues': _('Issues'),
        'tab.history': _('History'),
        'tab.equipment_sets': _('Sets'),
        'tab.sets': _('Sets'),
        'sets.none': _('No equipment sets available.'),
        'sets.items': _('items'),
        'btn.add_set': _('Add'),
        'confirm.add_set': _('Add all items from set to rental?'),
        'err.load_sets': _('Could not load equipment sets.'),
        'err.set_empty': _('This set has no items.'),
        'err.add_set': _('Could not add set'),
        'rooms.none': _('No rooms booked in this rental.'),
        'common.loading': _('Loading…'),
        'err.update_room': _('Could not update room'),
        'err.remove_room': _('Could not remove room'),
        'err.add_room': _('Could not add room'),
        'user.past_rentals': _('past rentals'),
        'wiz.items_rooms': _('Items & rooms'),
        'wiz.return': _('Return'),
        'wiz.conflicts': _('Conflicts'),
        'btn.back': _('Back'),
        'btn.next': _('Next'),
        'btn.confirm_send': _('Confirm & send'),
        'btn.sending': _('Sending…'),
        'btn.reminder_sent': _('Reminder sent.'),
        'menu.edit_items': _('Edit items'),
        'menu.change_user': _('Change user'),
        'menu.edit_period': _('Edit period'),
        'menu.resend_email': _('Resend confirmation'),
        'menu.export_pdf': _('Export as PDF'),
        'menu.cancel': _('Cancel rental'),
        'due.return_due': _('Return due'),
        'due.closed': _('Closed'),
        'due.pickup_at': _('Pickup'),
        'due.reserved_until': _('Reserved'),
        'due.days_overdue': _('days overdue'),
        'ok.reminder_sent': _('Reminder sent.'),
        'items.total': _('Total:'),
        'items.units_issued': _('units issued'),
        'qty.req': _('req'),
        'qty.issued': _('issued'),
        'qty.back': _('back'),
        'status.draft': _('Draft'),
        'status.reserved': _('Reserved'),
        'status.issued': _('Issued'),
        'status.returned': _('Returned'),
        'status.overdue': _('Overdue'),
        'status.cancelled': _('Cancelled'),
        'status.closed': _('Closed'),
        'wiz.sets': str(_('Sets')),
        'wiz.sets_error': str(_('Could not load equipment sets.')),
        'wiz.sets_count': str(_('sets')),
        'wiz.add_set': str(_('Add set')),
        'wiz.adding': str(_('Adding…')),
        'wiz.set_add_error': str(_('Could not add equipment set.')),
        'wiz.no_sets': str(_('No equipment sets available.')),
        'sets.load_error': str(_('Could not load equipment sets.')),
        'sets.total': str(_('sets')),
        'sets.hide_form': str(_('Hide form')),
        'sets.new_set': str(_('New set')),
        'sets.confirm_delete': str(_('Delete set "{name}"?')),
        'sets.delete_error': str(_('Could not delete set: ')),
        'sets.need_name': str(_('Please enter a set name.')),
        'sets.need_items': str(_('Please add at least one item.')),
        'sets.create_error': str(_('Could not create set.')),
        'sets.create_title': str(_('Create Equipment Set')),
        'sets.name': str(_('Name')),
        'sets.name_ph': str(_('e.g. Podcast Kit')),
        'sets.description': str(_('Description')),
        'sets.desc_ph': str(_('Optional description…')),
        'sets.search_items': str(_('Search inventory items')),
        'sets.search_ph': str(_('Type to search by name, number, or manufacturer…')),
        'sets.add': str(_('Add')),
        'sets.no_results': str(_('No items found.')),
        'sets.selected_items': str(_('Selected items')),
        'sets.creating': str(_('Creating…')),
        'sets.create': str(_('Create set')),
        'sets.cancel': str(_('Cancel')),
        'sets.empty_title': str(_('No equipment sets yet.')),
        'sets.empty_desc': str(_('Create your first set using the button above.')),
        # Room calendar (day timeline)
        'auth_required': str(_('Please log in to view the schedule')),
        'available': str(_('Available')),
        'closed_day': str(_('Closed')),
        'enlarge_photo': str(_('Click to enlarge')),
        'error_loading': str(_('Failed to load room schedule')),
        'no_rooms': str(_('No rooms found. Add rooms in admin.')),
    }


class InventoryItemViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset for inventory items available for rental.

    Provides filtered access to inventory items based on user permissions.
    Members can see MSA and OKMQ items, non-members only see MSA items.
    """

    serializer_class = InventoryItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'owner', 'available_for_rent']
    search_fields = ['inventory_number', 'description', 'manufacturer__name']
    ordering_fields = ['inventory_number', 'description']

    def get_queryset(self):
        """
        Filter queryset based on user permissions and availability.

        Returns:
            Filtered queryset of available inventory items
        """
        # Use the inventory service to get available items
        user_id = self.request.user.id if self.request.user.is_authenticated else None
        available_items = inventory_service.get_available_items(user_id=user_id)
        
        # Extract IDs from the service response
        item_ids = [item['id'] for item in available_items]
        
        # Get the actual model instances
        # This viewset is now backed by the inventory service, but the serializer
        # still expects model instances. This is a temporary state until the
        # serializer is also updated.
        from inventory.models import InventoryItem
        return InventoryItem.objects.filter(id__in=item_ids)


class RentalRequestViewSet(viewsets.ModelViewSet):
    """
    Viewset for managing rental requests.

    Provides full CRUD operations for rental requests with filtering,
    search, and ordering capabilities.
    """

    queryset = RentalRequest.objects.select_related('user', 'created_by').all()
    serializer_class = RentalRequestSerializer
    permission_classes = [CanCreateRentalRequest]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'user', 'created_by']
    search_fields = ['project_name', 'purpose']
    ordering_fields = ['created_at', 'requested_start_date']

    def get_queryset(self):
        """Restrict non-staff users to their own rental requests.

        The permission class only checks that somebody is logged in, so without
        this filter every authenticated user could read, edit and delete any
        rental request by guessing its id.
        """
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_staff:
            return queryset
        return queryset.filter(Q(user=user) | Q(created_by=user))

    def perform_create(self, serializer):
        """Pin ownership to the caller so a request cannot be filed for others."""
        user = self.request.user
        if user.is_staff:
            serializer.save(created_by=user)
        else:
            serializer.save(user=user, created_by=user)

    def perform_update(self, serializer):
        """Stop a borrower from handing their rental over to someone else."""
        user = self.request.user
        if user.is_staff:
            serializer.save()
        else:
            serializer.save(user=serializer.instance.user)


class RentalItemViewSet(viewsets.ModelViewSet):
    """
    Viewset for managing rental items within rental requests.

    Handles individual items that are part of rental requests
    with search and filtering capabilities.
    """

    queryset = RentalItem.objects.select_related('rental_request', 'inventory_item').all()
    serializer_class = RentalItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['rental_request', 'inventory_item']
    search_fields = ['rental_request__project_name', 'inventory_item__inventory_number']

    def get_queryset(self):
        """Limit non-staff users to items belonging to their own rentals."""
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_staff:
            return queryset
        return queryset.filter(
            Q(rental_request__user=user) | Q(rental_request__created_by=user)
        )


class RentalTransactionViewSet(viewsets.ModelViewSet):
    """
    Viewset for managing rental transactions.

    Handles all rental-related transactions (reserve, issue, return, cancel)
    with staff-only access for security.
    """

    queryset = RentalTransaction.objects.select_related('rental_item', 'performed_by').all()
    serializer_class = RentalTransactionSerializer
    permission_classes = [StaffCanIssuePermission]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['transaction_type', 'performed_by']


class RentalIssueViewSet(viewsets.ModelViewSet):
    """
    Viewset for managing rental issues and problems.

    Handles reporting and tracking of issues with rental items
    including severity levels and resolution status.
    """

    queryset = RentalIssue.objects.select_related('rental_item', 'reported_by').all()
    serializer_class = RentalIssueSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['issue_type', 'severity', 'resolved']

    def get_queryset(self):
        """Limit non-staff users to issues on their own rentals."""
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_staff:
            return queryset
        return queryset.filter(
            Q(rental_item__rental_request__user=user)
            | Q(rental_item__rental_request__created_by=user)
            | Q(reported_by=user)
        )


class EquipmentSetViewSet(viewsets.ModelViewSet):
    """
    Viewset for managing equipment sets.

    Handles predefined sets of equipment that can be rented together
    with member-only access for creation and editing.
    """

    queryset = EquipmentSet.objects.prefetch_related('items').all()
    serializer_class = EquipmentSetSerializer
    permission_classes = [IsAuthenticatedAndMemberOrReadOnly]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_template', 'is_active']
    search_fields = ['name', 'description']


class EquipmentSetItemViewSet(viewsets.ModelViewSet):
    """
    Viewset for managing items within equipment sets.

    Handles individual items that make up equipment sets
    with member-only access for management.
    """

    queryset = EquipmentSetItem.objects.select_related('equipment_set', 'inventory_item').all()
    serializer_class = EquipmentSetItemSerializer
    permission_classes = [IsAuthenticatedAndMemberOrReadOnly]
    pagination_class = DefaultPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['equipment_set', 'inventory_item']


class AccessDeniedView(TemplateView):
    """
    View for access denied page.

    Displays a user-friendly message when access is denied
    due to insufficient permissions.
    """

    template_name = 'rental/access_denied.html'


class StaffRequiredMixin(UserPassesTestMixin):
    """
    Mixin to require staff access with better error handling.

    Provides custom error messages and redirects for unauthorized access,
    distinguishing between unauthenticated users and insufficient permissions.
    """

    def test_func(self):
        """
        Check if user has staff permissions.

        Returns:
            bool: True if user is authenticated and staff, False otherwise
        """
        return self.request.user.is_authenticated and self.request.user.is_staff

    def handle_no_permission(self):
        """
        Handle unauthorized access with appropriate messages and redirects.

        Returns:
            HttpResponse: Redirect to login or access denied page
        """
        if not self.request.user.is_authenticated:
            messages.warning(
                self.request,
                _('You must log in to access this page.')
            )
            return redirect('login')
        else:
            messages.error(
                self.request,
                _('You do not have permission to access this page. Only staff have access.')
            )
            return redirect('rental:access_denied')


class RentalListView(StaffRequiredMixin, ListView):
    template_name = 'rental/list.html'
    context_object_name = 'rentals'
    paginate_by = 40

    SORT_DEFAULT_DIRECTIONS = {
        'id': 'desc',
        'project': 'asc',
        'time': 'asc',
        'status': 'asc',
        'items': 'desc',
    }

    def _sorting(self):
        """Return a validated sort key and direction from the query string."""
        sort = self.request.GET.get('sort', 'id')
        if sort not in self.SORT_DEFAULT_DIRECTIONS:
            sort = 'id'
        direction = self.request.GET.get(
            'direction', self.SORT_DEFAULT_DIRECTIONS[sort])
        if direction not in ('asc', 'desc'):
            direction = self.SORT_DEFAULT_DIRECTIONS[sort]
        return sort, direction

    def _apply_sorting(self, queryset, now):
        """Apply one of the explicitly supported list-header orderings."""
        sort, direction = self._sorting()
        prefix = '-' if direction == 'desc' else ''

        if sort == 'project':
            fields = (
                'project_name',
                'user__profile__last_name',
                'user__profile__first_name',
                'user__email',
                'pk',
            )
        elif sort == 'time':
            fields = ('requested_start_date', 'requested_end_date', 'pk')
        elif sort == 'status':
            queryset = queryset.annotate(
                list_status=Case(
                    When(
                        status='issued',
                        requested_end_date__lt=now,
                        then=Value('overdue'),
                    ),
                    default=F('status'),
                    output_field=CharField(),
                ),
            )
            fields = ('list_status', 'requested_start_date', 'pk')
        elif sort == 'items':
            queryset = queryset.annotate(
                list_item_count=Count('items', distinct=True),
                list_room_count=Count('room_rentals', distinct=True),
            ).annotate(
                list_content_count=(
                    F('list_item_count') + F('list_room_count')),
            )
            fields = (
                'list_content_count',
                'list_item_count',
                'list_room_count',
                'pk',
            )
        else:
            fields = ('created_at', 'pk')

        return queryset.order_by(*(f'{prefix}{field}' for field in fields))

    def _query_url(self, **updates):
        """Build a list URL while preserving the other active controls."""
        params = self.request.GET.copy()
        params.pop('page', None)
        for key, value in updates.items():
            if value in (None, ''):
                params.pop(key, None)
            else:
                params[key] = value
        query = params.urlencode()
        return f'?{query}' if query else '?'

    def get_queryset(self):
        queryset = RentalRequest.objects.select_related(
            'user',
            'user__profile',
        ).prefetch_related(
            'items',
            'room_rentals',
            'room_rentals__room',
        )
        status = self.request.GET.get('status')
        query = self.request.GET.get('q')
        now = timezone.now()

        if status == 'overdue':
            queryset = queryset.filter(
                status='issued',
                requested_end_date__lt=now,
            )
        elif status == 'issued':
            queryset = queryset.filter(status='issued').exclude(requested_end_date__lt=now)
        elif status:
            queryset = queryset.filter(status=status)

        if query:
            queryset = queryset.filter(
                Q(project_name__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
                | Q(user__email__icontains=query)
            )

        # User category, mirroring RentalConfig.get_organizations_for: staff are
        # employees; otherwise the profile flags decide, defaulting to "user".
        user_kind = self.request.GET.get('user_kind')
        if user_kind == 'employee':
            queryset = queryset.filter(user__is_staff=True)
        elif user_kind == 'member':
            queryset = queryset.filter(
                user__is_staff=False, user__profile__member=True)
        elif user_kind == 'rental_only':
            queryset = queryset.filter(
                user__is_staff=False,
                user__profile__member=False,
                user__profile__rental_only=True,
            )
        elif user_kind == 'user':
            queryset = queryset.filter(user__is_staff=False).exclude(
                user__profile__member=True).exclude(
                user__profile__rental_only=True)

        # Content type: rentals that include rooms or inventory items.
        kind = self.request.GET.get('kind')
        if kind == 'rooms':
            queryset = queryset.filter(room_rentals__isnull=False).distinct()
        elif kind == 'inventory':
            queryset = queryset.filter(items__isnull=False).distinct()

        return self._apply_sorting(queryset, now)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        rentals = []

        for rental in context['object_list']:
            derived_status = 'overdue' if (
                rental.status == 'issued' and rental.requested_end_date < now
            ) else rental.status
            overdue_days = 0
            if derived_status == 'overdue':
                overdue_days = max((now.date() - rental.requested_end_date.date()).days, 0)

            return_url = None
            if derived_status in ['issued', 'overdue']:
                try:
                    return_url = reverse('rental:rental_return', args=[rental.pk])
                except NoReverseMatch:
                    return_url = ''

            issue_url = None
            if derived_status == 'reserved':
                try:
                    issue_url = reverse('rental:mark_issued', args=[rental.pk])
                except NoReverseMatch:
                    issue_url = ''

            rentals.append({
                'id': f"R-{rental.created_at.strftime('%y%m')}-{rental.pk:04d}",
                'project': rental.project_name,
                'user': serialize_user(rental.user),
                'status': derived_status,
                'from_at': rental.requested_start_date,
                'to_at': rental.requested_end_date,
                'item_count': rental.items.count(),
                'room_count': rental.room_rentals.count(),
                'first_room': rental.room_rentals.first().room.name if rental.room_rentals.exists() else '',
                'overdue_days': overdue_days,
                'detail_url': reverse('rental:rental_detail', args=[rental.pk]),
                'return_url': return_url,
                'issue_url': issue_url,
            })

        base_queryset = RentalRequest.objects.all()
        context['rentals'] = rentals
        context['current_path'] = self.request.get_full_path()
        context['counts'] = {
            'all': base_queryset.count(),
            'reserved': base_queryset.filter(status='reserved').count(),
            'issued': base_queryset.filter(status='issued', requested_end_date__gte=now).count(),
            'overdue': base_queryset.filter(status='issued', requested_end_date__lt=now).count(),
            'returned': base_queryset.filter(status='returned').count(),
        }
        context['current_status'] = self.request.GET.get('status', '')
        context['current_q'] = self.request.GET.get('q', '')
        context['current_user_kind'] = self.request.GET.get('user_kind', '')
        context['current_kind'] = self.request.GET.get('kind', '')
        current_sort, current_direction = self._sorting()
        header_labels = {
            'id': _('Rental ID'),
            'project': _('Project / User'),
            'time': _('Time'),
            'status': _('Status'),
            'items': _('Items'),
        }
        context['sort_headers'] = []
        for key, label in header_labels.items():
            active = key == current_sort
            if active:
                next_direction = (
                    'desc' if current_direction == 'asc' else 'asc')
            else:
                next_direction = self.SORT_DEFAULT_DIRECTIONS[key]
            context['sort_headers'].append({
                'key': key,
                'label': label,
                'active': active,
                'direction': current_direction if active else '',
                'aria_sort': (
                    'ascending' if active and current_direction == 'asc'
                    else 'descending' if active
                    else 'none'
                ),
                'url': self._query_url(
                    sort=key, direction=next_direction),
            })
        context['current_sort'] = current_sort
        context['current_direction'] = current_direction
        context['status_urls'] = {
            'all': self._query_url(status=None),
            'reserved': self._query_url(status='reserved'),
            'issued': self._query_url(status='issued'),
            'overdue': self._query_url(status='overdue'),
            'returned': self._query_url(status='returned'),
        }
        page_params = self.request.GET.copy()
        page_params.pop('page', None)
        context['pagination_query'] = page_params.urlencode()
        context['i18n_bundle'] = _i18n_bundle()
        context['is_paginated'] = True
        context['sidebar'] = {
            'all_count': base_queryset.count(),
            'issued_count': base_queryset.filter(status='issued').count(),
            'overdue_count': base_queryset.filter(status='issued', requested_end_date__lt=now).count(),
            'due_today_count': base_queryset.filter(
                status='issued',
                requested_end_date__date=now.date(),
            ).count(),
            'pending_approval_count': base_queryset.filter(status='draft').count(),
        }
        return context


class RentalProcessView(StaffRequiredMixin, TemplateView):
    """
    Custom admin page for rental process management.

    Provides staff interface for creating and managing rental requests,
    including user selection, inventory browsing, and equipment set management.
    """

    template_name = 'rental/admin_rental_process.html'

    def get_context_data(self, **kwargs):
        """
        Prepare context data for rental process page.

        Args:
            **kwargs: Additional context data

        Returns:
            dict: Context with users, inventory, organizations, and equipment sets
        """
        context = super().get_context_data(**kwargs)
        users = get_initial_rental_process_users()
        from .config import get_rental_show_room_photos
        show_room_photos = get_rental_show_room_photos()
        active_rooms = Room.objects.filter(is_active=True).order_by('name')
        if show_room_photos:
            active_rooms = active_rooms.prefetch_related('images')
        categories = Category.objects.all().order_by('name')
        
        # Use the inventory service to get available items
        inventory_data = inventory_service.get_available_items()
        inventory_ids = [item['id'] for item in inventory_data]
        inventory = inventory_service.get_items_by_ids(inventory_ids)
        
        organizations = inventory_service.get_item_organizations()
        equipment_sets = EquipmentSet.objects.filter(is_active=True)
        context.update({
            'users': users,
            'inventory_items': inventory,
            'organizations': organizations,
            'equipment_sets': equipment_sets,
            'rental_working_hours_json': json.dumps(get_rental_working_hours()),
            'rental_working_hours_summary': get_rental_working_hours_summary_text(),
            'initial_json': {
                'from_email': getattr(settings, 'EMAIL_HOST_USER', 'noreply@localhost'),
                'categories': [{
                    'id': '',
                    'label': str(_('All')),
                    'icon': 'fa-th',
                    'count': InventoryItem.objects.filter(available_for_rent=True, status='in_stock').count(),
                }] + [{
                    'id': str(category.pk),
                    'label': category.name,
                    'icon': 'fa-box',
                    'count': category.inventoryitem_set.filter(status='in_stock').count(),
                } for category in categories],
                'users': [serialize_user(user) for user in users],
                'rooms': [{
                    'id': room.pk,
                    'name': room.name,
                    'sub': room.description or '',
                    'free': room.is_active,
                    'image_url': (
                        _room_thumb_url(room)
                        if show_room_photos and room.primary_image
                        else None
                    ),
                    'image_full_url': (
                        _room_full_url(room)
                        if show_room_photos and room.primary_image
                        else None
                    ),
                    'image_urls': (
                        _room_photo_urls(room)
                        if show_room_photos and room.primary_image
                        else []
                    ),
                } for room in active_rooms],
                'defaults': {
                    'from': '',
                    'to': '',
                    'project': '',
                    'purpose': '',
                },
                'working_hours': get_rental_working_hours(),
                'urls': {
                    'create': reverse('rental:create_submit'),
                    'quick_issue': reverse('rental:quick_issue'),
                    'inventory_search': reverse('rental:api_inventory_search'),
                    'users_search': reverse('rental:api_users_search'),
                    'availability_check': reverse('rental:api_availability_check'),
                    'room_availability_check': reverse('rental:api_check_room_availability'),
                    'room_schedule': reverse('rental:api_room_schedule'),
                    'new_user': reverse('admin:registration_okuser_add'),
                    'equipment_sets': reverse('rental:api_equipment_sets_available'),
                    'equipment_set_details': reverse('rental:api_equipment_set_details', kwargs={'set_id': 0}),
                },
            },
            'sidebar': {
                'all_count': RentalRequest.objects.count(),
                'issued_count': RentalRequest.objects.filter(status='issued').count(),
                'overdue_count': RentalRequest.objects.filter(status='issued', requested_end_date__lt=timezone.now()).count(),
                'due_today_count': RentalRequest.objects.filter(
                    status='issued',
                    requested_end_date__date=timezone.now().date(),
                ).count(),
                'pending_approval_count': RentalRequest.objects.filter(status='draft').count(),
            },
            'i18n_strings': _i18n_bundle(),
            'flags_json': _frontend_flags(),
        })
        return context


@login_required
@staff_member_required
def api_search_users(request):
    """
    Search users by name or email.

    Searches for users based on profile information and returns
    user details including member status and permissions.
    Also handles users without profiles (staff members).

    Args:
        request: HTTP request object with query parameter 'q'

    Returns:
        JsonResponse: List of matching users with their details
    """
    query = request.GET.get('q', '')
    if not query:
        return JsonResponse({'users': []})
    
    # Search by email first (works for all users, including those without profile)
    # Then search by profile fields using LEFT JOIN to include users without profile
    users = OKUser.objects.select_related('profile', 'profile__media_authority').filter(
        Q(email__icontains=query) |
        Q(profile__first_name__icontains=query) |
        Q(profile__last_name__icontains=query)
    ).distinct().annotate(
        rental_count=Count(
            'rentalrequest',
            filter=Q(rentalrequest__status__in=RENTAL_PROCESS_COUNTED_STATUSES),
            distinct=True,
        ),
    ).order_by('email')[:30]
    
    result = []
    from registration import organization_config
    state_institution = organization_config.get_state_media_institution()
    organization_owner = organization_config.get_organization_owner()
    
    for user in users:
        profile = getattr(user, 'profile', None)
        
        # Determine role: Staff has highest priority, then Member, then User
        if user.is_staff:
            member_status = _('Staff')
            # Staff have access to all items
            permissions_text = _('All items')
        elif profile and profile.member:
            member_status = _('Member')
            permissions_text = f"{state_institution}, {organization_owner}"
        else:
            member_status = _('User')
            permissions_text = state_institution
        
        user_data = serialize_user(user)
        user_data.update({
            'member_status': member_status,
            'permissions': permissions_text,
            'is_member': profile.member if profile else False,
            'is_staff': user.is_staff,
        })
        result.append(user_data)
    
    return JsonResponse({'users': result})


@login_required
@staff_member_required
def api_get_user_inventory(request, user_id):
    """
    Get available inventory for a specific user.

    Returns filtered inventory items based on user permissions and
    availability during specified time period.

    Args:
        request: HTTP request object with filter parameters
        user_id: ID of the user to get inventory for

    Returns:
        JsonResponse: List of available inventory items
    """
    user = get_object_or_404(OKUser, id=user_id)
    # For staff users, don't require profile
    profile = getattr(user, 'profile', None)
    if not profile and not getattr(user, 'is_staff', False):
        return JsonResponse({'error': _('User profile not found')}, status=400)

    # Get filter parameters
    owner_filter = request.GET.get('owner', '')
    location_filter = request.GET.get('location', '')
    category_filter = request.GET.get('category', '')
    search_query = request.GET.get('search', '')

    # Get date parameters for availability calculation
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    # Parse dates
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    start_date = None
    end_date = None

    if start_date_str:
        try:
            start_date = parse_datetime(start_date_str)
            if start_date:
                # Make sure date is timezone-aware
                if timezone.is_naive(start_date):
                    start_date = timezone.make_aware(start_date)
            else:
                # Try parsing as date only
                from django.utils.dateparse import parse_date
                date_only = parse_date(start_date_str)
                if date_only:
                    start_date = timezone.make_aware(timezone.datetime.combine(date_only, timezone.datetime.min.time()))
        except:
            pass

    if end_date_str:
        try:
            end_date = parse_datetime(end_date_str)
            if end_date:
                # Make sure date is timezone-aware
                if timezone.is_naive(end_date):
                    end_date = timezone.make_aware(end_date)
            else:
                # Try parsing as date only
                from django.utils.dateparse import parse_date
                date_only = parse_date(end_date_str)
                if date_only:
                    end_date = timezone.make_aware(timezone.datetime.combine(date_only, timezone.datetime.max.time()))
        except:
            pass

    # Get available inventory through the service interface
    inventory_data = inventory_service.get_available_items(user_id=user.id)
    
    # Check if user is staff (Mitarbeiter) - staff can see all items even if quantity is 0
    is_staff = getattr(user, 'is_staff', False)
    
    # Apply additional filters
    filtered_inventory = []
    for item in inventory_data:
        if not item:
            continue
            
        # Apply owner filter
        owner_data = item.get('owner') or {}
        owner_name = owner_data.get('name') if isinstance(owner_data, dict) else (owner_data or '')
        if owner_filter and owner_filter != 'all':
            if owner_name != owner_filter:
                continue
        
        # Apply category filter
        category_data = item.get('category') or {}
        category_name = category_data.get('name') if isinstance(category_data, dict) else (category_data or '')
        if category_filter and category_filter != 'all':
            # Normalize both strings: strip whitespace and compare case-insensitively
            category_name_normalized = category_name.strip().lower() if category_name else ''
            category_filter_normalized = category_filter.strip().lower()
            if category_name_normalized != category_filter_normalized:
                continue
        
        # Apply location filter
        location_data = item.get('location') or {}
        if isinstance(location_data, dict):
            location_path = location_data.get('full_path', '')
            location_name = location_data.get('name', '')
        else:
            location_path = ''
            location_name = ''
        
        if location_filter and location_filter != 'all':
            # Compare with full_path (as stored in filter)
            if location_path != location_filter:
                continue
        
        # Apply search query
        manufacturer = item.get('manufacturer', '') or ''
        if isinstance(manufacturer, dict):
            manufacturer = manufacturer.get('name', '')
        if search_query:
            search_text = f"{item.get('description', '')} {item.get('inventory_number', '')} {manufacturer} {category_name}"
            if search_query.lower() not in search_text.lower():
                continue
        
        # Check availability for the period
        if start_date and end_date:
            # Use period-specific availability calculation
            try:
                available_qty = RentalService.get_available_quantity_for_period(
                    item.get('id'),
                    start_date,
                    end_date
                )
            except Exception:
                # Fallback to general availability if period calculation fails
                available_qty = inventory_service.get_available_quantity(item.get('id'))
        else:
            # No dates specified, use general availability
            available_qty = inventory_service.get_available_quantity(item.get('id'))
        
        # For staff users, show all items even if available_qty is 0
        # For regular users, only show items with available_qty > 0
        if available_qty > 0 or is_staff:
            
            filtered_inventory.append({
                'id': item.get('id'),
                'inventory_number': item.get('inventory_number', ''),
                'description': item.get('description', ''),
                'location_path': location_path,
                'location_name': location_name,
                'owner': owner_name,
                'manufacturer': manufacturer,
                'category': category_name,
                'available_quantity': available_qty,
                'total_quantity': item.get('quantity', 0),
            })
    
    return JsonResponse({'inventory': filtered_inventory})


@login_required
def api_create_rental_user(request):
    """
    Create a new rental request (user version).
    This version is accessible to regular users but only for their own rentals.

    Args:
        request: HTTP request object with rental data

    Returns:
        JsonResponse: Success status and rental ID or error message
    """
    # Security check: users can only create rentals for themselves
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        
        rental_service = RentalService()
        result = rental_service.create_rental_request(data, request.user, request.user, is_user_request=True)
        
        if result['success']:
            return JsonResponse(result)
        else:
            return JsonResponse({'error': result['error']}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@staff_member_required
def api_create_rental(request):
    """
    Create a new rental request.

    Creates rental requests for equipment and rooms with validation
    of dates, availability, and user permissions.

    Args:
        request: HTTP request object with rental data

    Returns:
        JsonResponse: Success status and rental ID or error message
    """
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    
    try:
        data = json.loads(request.body)
        
        rental_service = RentalService()
        user = get_object_or_404(OKUser, id=data['user_id'])
        result = rental_service.create_rental_request(data, user, request.user, is_user_request=False)
        
        if result['success']:
            return JsonResponse(result)
        else:
            return JsonResponse({'error': result['error']}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def get_available_quantity_for_period(item, start_date, end_date):
    """
    Calculate available quantity for a specific time period.

    Determines how many items are available for rental during a given
    time period by considering existing reservations and rentals.

    Args:
        item: InventoryItem instance to check availability for
        start_date: Start datetime of the requested period
        end_date: End datetime of the requested period

    Returns:
        int: Available quantity for the specified period
    """
    rental_service = RentalService()
    return rental_service.get_available_quantity_for_period(item, start_date, end_date)


@login_required
@staff_member_required
def api_get_user_stats(request, user_id):
    """
    Get rental statistics for a specific user.

    Returns counts of active, completed, and overdue rentals
    along with recent rental activities.

    Args:
        request: HTTP request object
        user_id: ID of the user to get stats for

    Returns:
        JsonResponse: User rental statistics and recent activities
    """
    from django.utils import timezone
    user = get_object_or_404(OKUser, id=user_id)
    active_rentals = RentalRequest.objects.filter(user=user, status__in=['draft', 'reserved', 'issued']).count()
    completed_rentals = RentalRequest.objects.filter(user=user, status='returned').count()
    overdue_rentals = RentalRequest.objects.filter(user=user, status='issued', requested_end_date__lt=timezone.now()).count()
    recent_activities = RentalRequest.objects.filter(user=user).order_by('-created_at')[:5]
    activities = [{
        'project_name': r.project_name,
        'date': r.created_at.strftime('%d.%m.%Y'),
        'status': r.get_status_display(),
    } for r in recent_activities]
    return JsonResponse({
        'active_rentals': active_rentals,
        'completed_rentals': completed_rentals,
        'overdue_rentals': overdue_rentals,
        'recent_activities': activities,
    })


@login_required
@staff_member_required
def api_user_active_items(request, user_id):
    """
    Get list of active issued items for a user to return.

    Returns items that are currently issued to the user and have
    outstanding quantities that need to be returned.

    Args:
        request: HTTP request object
        user_id: ID of the user to get active items for

    Returns:
        JsonResponse: List of active rental items with outstanding quantities
    """
    user = get_object_or_404(OKUser, id=user_id)
    items = RentalItem.objects.select_related('inventory_item', 'rental_request').filter(
        rental_request__user=user,
        rental_request__status='issued',
    )
    result = []
    for it in items:
        outstanding = max(0, (it.quantity_issued or 0) - (it.quantity_returned or 0))
        if outstanding > 0:
            inv = it.inventory_item
            result.append({
                'rental_item_id': it.id,
                'rental_request_id': it.rental_request.id,
                'inventory_number': inv.inventory_number,
                'description': inv.description,
                'outstanding': outstanding,
            })
    return JsonResponse({'items': result})


@login_required
@staff_member_required
def api_return_items(request):
    """
    Return selected items (creates RentalTransaction 'return').

    Processes item returns and updates rental status when all items
    in a rental request are fully returned.

    Args:
        request: HTTP request object with items to return

    Returns:
        JsonResponse: Success status or error message
    """
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    try:
        data = json.loads(request.body)
        items = data.get('items', [])
        
        rental_service = RentalService()
        result = rental_service.return_items(items, request.user)
        
        if result['success']:
            return JsonResponse(result)
        else:
            return JsonResponse({'error': result['error']}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@staff_member_required
def api_get_filter_options(request):
    """
    Get filter options for inventory.

    Returns available filter options for organizations (owners),
    locations, and categories to help with inventory filtering.
    If user_id is provided, filters owners based on user access rights.

    Args:
        request: HTTP request object with optional user_id parameter

    Returns:
        JsonResponse: Available filter options for inventory
    """
    from django.conf import settings

    # Get user_id if provided
    user_id = request.GET.get('user_id', None)
    
    # Get organizations (owners)
    all_organizations = inventory_service.get_item_organizations()
    
    # Filter owners based on user access if user_id provided
    if user_id:
        try:
            user = OKUser.objects.get(id=user_id)
            from registration import organization_config
            state_institution = organization_config.get_state_media_institution()
            organization_owner = organization_config.get_organization_owner()
            
            if user.is_staff:
                # Staff can see all owners
                organizations = all_organizations
            elif hasattr(user, 'profile') and user.profile and user.profile.member:
                # Members can see state institution + organization
                organizations = [
                    org for org in all_organizations 
                    if org.get('name') in [state_institution, organization_owner]
                ]
            else:
                # Regular users can only see state institution
                organizations = [
                    org for org in all_organizations 
                    if org.get('name') == state_institution
                ]
        except OKUser.DoesNotExist:
            organizations = all_organizations
    else:
        organizations = all_organizations

    # Get locations with hierarchical structure
    locations = inventory_service.get_item_locations()

    # Get categories
    categories = inventory_service.get_item_categories()

    return JsonResponse({
        'owners': organizations,
        'locations': locations,
        'categories': categories,
    })


@login_required
@staff_member_required
def api_get_equipment_sets(request):
    """
    Get available equipment sets.

    Returns equipment sets that are active and have all items
    available for rental.

    Args:
        request: HTTP request object

    Returns:
        JsonResponse: List of available equipment sets
    """

    try:
        from .models import EquipmentSet
        equipment_sets = EquipmentSet.objects.filter(is_active=True)

        result = []
        for equipment_set in equipment_sets:
            # Check availability of all items in the set
            all_items_available = True
            total_items = 0

            for set_item in equipment_set.items.all():
                inventory_item = set_item.inventory_item
                if inventory_item:
                    total_items += 1
                    # Simple availability check
                    if not inventory_item.available_for_rent or inventory_item.status != 'in_stock':
                        all_items_available = False
                        break

            if all_items_available and total_items > 0:
                result.append({
                    'id': equipment_set.id,
                    'name': equipment_set.name,
                    'description': equipment_set.description,
                    'items_count': total_items,
                })

        return JsonResponse({'success': True, 'equipment_sets': result})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
def api_get_equipment_set_details(request, set_id):
    """
    Get detailed information about a specific equipment set.

    Returns comprehensive details about an equipment set including
    all items, their availability, and metadata.

    Args:
        request: HTTP request object
        set_id: ID of the equipment set to get details for

    Returns:
        JsonResponse: Detailed equipment set information
    """
    try:
        from .models import EquipmentSet
        equipment_set = get_object_or_404(EquipmentSet, id=set_id, is_active=True)

        items_data = []
        for set_item in equipment_set.items.all():
            inventory_item = set_item.inventory_item
            if inventory_item:
                # Check item availability
                is_available = inventory_item.available_for_rent and inventory_item.status == 'in_stock'

                items_data.append({
                    'id': set_item.id,
                    'inventory_item_id': inventory_item.id,
                    'inventory_number': inventory_item.inventory_number,
                    'description': inventory_item.description,
                    'quantity_needed': set_item.quantity,
                    'quantity_available': inventory_item.quantity if is_available else 0,
                    'is_available': is_available,
                    'location': inventory_item.location.full_path if inventory_item.location else _('Location not specified'),
                    'category': inventory_item.category.name if inventory_item.category else _('No category')
                })

        result = {
            'id': equipment_set.id,
            'name': equipment_set.name,
            'description': equipment_set.description,
            'items': items_data,
            'total_items': len(items_data)
        }

        return JsonResponse({'success': True, 'equipment_set': result})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_get_rooms(request):
    """
    Get available rooms.

    Returns rooms with availability information for specified time periods,
    including conflict details for unavailable rooms.

    Args:
        request: HTTP request object with optional date parameters

    Returns:
        JsonResponse: List of rooms with availability status
    """

    try:
        from .models import Room
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        # Get time parameters for availability checking
        start_date_str = request.GET.get('start_date', '')
        end_date_str = request.GET.get('end_date', '')

        start_date = None
        end_date = None

        if start_date_str:
            try:
                start_date = parse_datetime(start_date_str)
                if not start_date:
                    from django.utils.dateparse import parse_date
                    date_only = parse_date(start_date_str)
                    if date_only:
                        start_date = timezone.make_aware(timezone.datetime.combine(date_only, timezone.datetime.min.time()))
            except:
                pass

        if end_date_str:
            try:
                end_date = parse_datetime(end_date_str)
                if not end_date:
                    from django.utils.dateparse import parse_date
                    date_only = parse_date(end_date_str)
                    if date_only:
                        end_date = timezone.make_aware(timezone.datetime.combine(date_only, timezone.datetime.max.time()))
            except:
                pass

        rooms = Room.objects.filter(is_active=True)

        result = []
        for room in rooms:
            # Check room availability
            is_available = True
            availability_info = _("Available")

            if start_date and end_date:
                if not room.is_available_for_time(start_date, end_date):
                    is_available = False
                    # Get conflict information
                    conflicts = room.get_conflicting_rentals(start_date, end_date)
                    if conflicts:
                        conflict_details = []
                        for conflict in conflicts[:3]:  # Show maximum 3 conflicts
                            user = conflict.rental_request.user
                            user_name = _("Unknown user")

                            # Try to get name from profile
                            try:
                                if hasattr(user, 'profile') and user.profile:
                                    profile = user.profile
                                    if hasattr(profile, 'first_name') and profile.first_name and hasattr(profile, 'last_name') and profile.last_name:
                                        user_name = f"{profile.first_name} {profile.last_name}"
                                    elif hasattr(profile, 'first_name') and profile.first_name:
                                        user_name = profile.first_name
                                    elif hasattr(profile, 'last_name') and profile.last_name:
                                        user_name = profile.last_name
                                elif hasattr(user, 'first_name') and user.first_name and hasattr(user, 'last_name') and user.last_name:
                                    user_name = f"{user.first_name} {user.last_name}"
                                elif hasattr(user, 'username') and user.username:
                                    user_name = user.username
                                elif hasattr(user, 'email') and user.email:
                                    user_name = user.email.split('@')[0]
                                else:
                                    user_name = _("User #{user_id}").format(user_id=user.id)
                            except:
                                user_name = _("User #{user_id}").format(user_id=user.id)

                            project = conflict.rental_request.project_name
                            status = conflict.rental_request.get_status_display()
                            conflict_details.append(f"{user_name} ({project})")

                        availability_info = _("Not available - Conflicts: {conflicts}").format(
                            conflicts=", ".join(conflict_details)
                        )
                        if len(conflicts) > 3:
                            availability_info += _(" and {count} more").format(count=len(conflicts) - 3)

            result.append({
                'id': room.id,
                'name': room.name,
                'description': room.description,
                'capacity': room.capacity,
                'location': room.location,
                'is_available': is_available,
                'availability_info': availability_info,
            })

        return JsonResponse({'success': True, 'rooms': result})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_get_user_rental_details_by_id(request, user_id=None):
    """
    Get detailed rental information for a user.

    Returns comprehensive rental details including items, rooms,
    and status information filtered by rental type.

    Args:
        request: HTTP request object with filter parameters
        user_id: ID of the user to get rental details for

    Returns:
        JsonResponse: Detailed rental information for the user
    """

    user = get_object_or_404(OKUser, id=user_id)
    rental_type = request.GET.get('type', 'active')  # active, returned, overdue
    rental_id = request.GET.get('rental_id')  # specific rental ID

    from .models import RentalRequest
    from django.utils import timezone

    base_query = RentalRequest.objects.select_related('user', 'created_by').prefetch_related(
        'items__inventory_item__category',
        'items__inventory_item__location',
        'items__transactions',
        'items__issues',
        'room_rentals__room'
    ).filter(user=user)

    # Filter by specific rental if provided
    if rental_id:
        rentals = base_query.filter(id=rental_id)
    elif rental_type == 'active':
        rentals = base_query.filter(status__in=['draft', 'reserved', 'issued'])
    elif rental_type == 'returned':
        rentals = base_query.filter(status='returned')
    elif rental_type == 'overdue':
        # Find rentals that are past their end date and not returned
        rentals = base_query.filter(
            status__in=['reserved', 'issued'],
            requested_end_date__lt=timezone.now()
        )
    else:
        rentals = base_query.none()

    result = []
    for rental in rentals:
        items_data = []
        for item in rental.items.all():
            items_data.append({
                'id': item.id,
                'inventory_item': {
                    'inventory_number': item.inventory_item.inventory_number,
                    'description': item.inventory_item.description,
                    'category': item.inventory_item.category.name if item.inventory_item.category else '',
                    'location': item.inventory_item.location.full_path if item.inventory_item.location else '',
                },
                'quantity_requested': item.quantity_requested,
                'quantity_issued': item.quantity_issued,
                'quantity_returned': item.quantity_returned,
                'actual_return_date': item.actual_return_date.isoformat() if item.actual_return_date else None,
                'is_overdue': item.is_overdue,
                'days_overdue': item.days_overdue,
                'outstanding': max(0, (item.quantity_issued or 0) - (item.quantity_returned or 0)),
            })

        # Calculate days overdue for overdue rentals
        days_overdue = 0
        if rental_type == 'overdue' and rental.requested_end_date:
            days_overdue = (timezone.now().date() - rental.requested_end_date.date()).days

        # Get rooms data
        rooms_data = []
        for room_rental in rental.room_rentals.all():
            rooms_data.append({
                'id': room_rental.id,
                'room': {
                    'id': room_rental.room.id,
                    'name': room_rental.room.name,
                    'description': room_rental.room.description,
                    'capacity': room_rental.room.capacity,
                    'location': room_rental.room.location,
                },
                'people_count': room_rental.people_count,
                'notes': room_rental.notes,
                'requested_start_date': room_rental.requested_start_date.isoformat() if room_rental.requested_start_date else None,
                'requested_end_date': room_rental.requested_end_date.isoformat() if room_rental.requested_end_date else None,
            })

        result.append({
            'id': rental.id,
            'project_name': rental.project_name,
            'purpose': rental.purpose,
            'status': rental.status,
            'status_display': rental.get_status_display(),
            'requested_start_date': rental.requested_start_date.isoformat() if rental.requested_start_date else None,
            'requested_end_date': rental.requested_end_date.isoformat() if rental.requested_end_date else None,
            'actual_start_date': rental.actual_start_date.isoformat() if rental.actual_start_date else None,
            'actual_end_date': rental.actual_end_date.isoformat() if rental.actual_end_date else None,
            'created_by': f"{rental.created_by.profile.first_name} {rental.created_by.profile.last_name} ({rental.created_by.email})" if rental.created_by and hasattr(rental.created_by, 'profile') and rental.created_by.profile else (rental.created_by.email if rental.created_by else ''),
            'created_at': rental.created_at.isoformat() if rental.created_at else None,
            'days_overdue': days_overdue,
            'items': items_data,
            'total_items': len(items_data),
            'room_rentals': rooms_data,
            'total_rooms': len(rooms_data),
        })

    return JsonResponse({
        'rentals': result,
        'type': rental_type,
        'user': {
            'id': user.id,
            'name': f"{user.profile.first_name} {user.profile.last_name}" if hasattr(user, 'profile') and user.profile else user.email,
            'email': user.email,
        }
    })


@login_required
@staff_member_required
def api_cancel_rental(request):
    """
    Cancel a rental request.

    Cancels active rentals by creating appropriate transactions
    and updating the rental status to cancelled.

    Args:
        request: HTTP request object with rental ID

    Returns:
        JsonResponse: Success status and confirmation message
    """

    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        rental_id = data.get('rental_id')

        if not rental_id:
            return JsonResponse({'error': _('Rental ID is required')}, status=400)

        rental_service = RentalService()
        result = rental_service.cancel_rental(rental_id, request.user)
        
        if result['success']:
            return JsonResponse(result)
        else:
            return JsonResponse({'error': result['error']}, status=400)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_confirm_rental(request):
    """
    Confirm a draft rental request (status -> reserved).

    Args:
        request: HTTP request object with rental ID

    Returns:
        JsonResponse: Success status and updated rental status
    """
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        rental_id = data.get('rental_id')

        if not rental_id:
            return JsonResponse({'error': _('Rental ID is required')}, status=400)

        rental = get_object_or_404(RentalRequest, id=rental_id)
        if rental.status != 'draft':
            return JsonResponse({'error': _('Only draft requests can be confirmed')}, status=400)

        rental.status = 'reserved'
        rental.save(update_fields=['status'])

        return JsonResponse({
            'success': True,
            'rental_id': rental.id,
            'status': rental.status,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_return_rental_items(request):
    """
    Return rental items with condition and issues tracking.

    Processes item returns with condition assessment and issue reporting,
    updating rental status when all items are returned.

    Args:
        request: HTTP request object with return data

    Returns:
        JsonResponse: Success status and completion information
    """

    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        rental_id = data.get('rental_id')
        items = data.get('items', [])
        general_note = (data.get('note') or '').strip()
        email_receipt = bool(data.get('email_receipt'))
        close_after_return = bool(data.get('close_rental'))
        flag_audit = bool(data.get('flag_audit'))

        if not rental_id and items:
            first_item_id = items[0].get('rental_item_id') or items[0].get('id')
            if first_item_id:
                rental_id = RentalItem.objects.filter(id=first_item_id).values_list('rental_request_id', flat=True).first()

        if not rental_id or not items:
            return JsonResponse({'error': _('Rental ID and items are required')}, status=400)

        from .models import RentalIssue
        from .models import RentalRequest
        from .models import RentalTransaction

        rental_request = get_object_or_404(RentalRequest, id=rental_id)

        # Check if rental can have returns
        if rental_request.status not in ['reserved', 'issued']:
            return JsonResponse({'error': _('Only active rentals can have returns')}, status=400)

        returned_items_for_email = []
        for item_data in items:
            rental_item_id = item_data.get('rental_item_id') or item_data.get('id')
            quantity = int(item_data.get('quantity') or item_data.get('qty_returned') or 0)

            condition_map = {
                'ok': 'good',
                'warn': 'fair',
                'bad': 'poor',
            }
            condition = condition_map.get(item_data.get('condition'), item_data.get('condition', 'good'))

            issue_text = (item_data.get('issue') or '').strip()
            charge_user = bool(item_data.get('charge'))
            hold_out = bool(item_data.get('hold_out'))
            notes = item_data.get('notes', '')
            if issue_text and not notes:
                notes = issue_text
            extra_notes = []
            if charge_user:
                extra_notes.append(str(_('Marked as recoverable damage charge.')))
            if hold_out:
                extra_notes.append(str(_('Hold item out of the rental pool until reviewed.')))
            if extra_notes:
                notes = f'{notes}\n' + '\n'.join(extra_notes) if notes else '\n'.join(extra_notes)
            if general_note:
                notes = f'{notes}\n\n{general_note}'.strip() if notes else general_note

            issues = item_data.get('issues')
            if issues is None:
                issues = []
                if issue_text:
                    issues.append({
                        'issue_type': 'damaged' if condition == 'poor' else 'other',
                        'description': issue_text,
                        'severity': 'major' if condition == 'poor' else 'minor',
                    })

            if quantity <= 0:
                continue

            rental_item = rental_request.items.get(id=rental_item_id)
            previous_returned_quantity = rental_item.quantity_returned or 0

            # Create return transaction
            from django.utils import timezone

            transaction = RentalTransaction.objects.create(
                rental_item=rental_item,
                transaction_type='return',
                quantity=quantity,
                performed_by=request.user,
                condition=condition,
                notes=notes
            )
            returned_items_for_email.append({
                'name': str(rental_item.inventory_item),
                'quantity': quantity,
                'condition': transaction.get_condition_display(),
            })

            # Update actual return date when item is fully returned
            rental_item.refresh_from_db()
            if (rental_item.quantity_returned or 0) <= previous_returned_quantity:
                rental_item.quantity_returned = previous_returned_quantity + quantity
                rental_item.save(update_fields=['quantity_returned'])
            if (rental_item.quantity_issued or 0) <= (rental_item.quantity_returned or 0):
                # Item is fully returned - set actual return date
                rental_item.actual_return_date = timezone.now()
                rental_item.save(update_fields=['actual_return_date'])

            # Create issues if any
            for issue_data in issues:
                if issue_data.get('issue_type') and issue_data.get('description'):
                    RentalIssue.objects.create(
                        rental_item=rental_item,
                        issue_type=issue_data['issue_type'],
                        description=issue_data['description'],
                        severity=issue_data.get('severity', 'minor'),
                        reported_by=request.user
                    )
            if flag_audit:
                RentalIssue.objects.create(
                    rental_item=rental_item,
                    issue_type='other',
                    description=_('Inventory audit requested during return processing.'),
                    severity='minor',
                    reported_by=request.user,
                )

        # Check if all equipment items are returned
        # Note: Rooms are handled separately via automatic expiration
        # For mixed rentals, we only check equipment items for 'returned' status
        rental_request.refresh_from_db()
        all_equipment_returned = True
        has_equipment = rental_request.items.exists()
        
        if has_equipment:
            for item in rental_request.items.all():
                if (item.quantity_issued or 0) > (item.quantity_returned or 0):
                    all_equipment_returned = False
                    break
        else:
            # No equipment items, so technically "returned" (rooms handled separately)
            all_equipment_returned = True

        # Update rental status if all equipment items returned
        # Rooms will be automatically returned by the expiration task
        if all_equipment_returned and has_equipment:
            from django.utils import timezone
            rental_request.status = 'closed' if close_after_return else 'returned'
            rental_request.actual_end_date = timezone.now()
            rental_request.save(update_fields=['status', 'actual_end_date', 'updated_at'])

        if email_receipt:
            send_return_receipt_email(
                rental_request=rental_request,
                returned_items=returned_items_for_email,
                note=general_note,
            )

        return JsonResponse({
            'success': True,
            'message': _('Items returned successfully'),
            'rental_completed': all_equipment_returned
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


class RentalDetailView(StaffRequiredMixin, TemplateView):
    """
    Detail view for a specific rental request with return/extend options.

    Displays comprehensive rental information including items,
    transactions, and available actions for staff members.
    """

    template_name = 'rental/rental_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rental_id = kwargs.get('rental_id')

        rental = get_object_or_404(
            RentalRequest.objects.select_related(
                'user',
                'user__profile',
                'user__profile__media_authority',
                'created_by',
                'created_by__profile',
            ).prefetch_related(
                'items__inventory_item__owner',
                'items__inventory_item__location',
                'items__inventory_item__category',
                'room_rentals__room',
            ),
            id=rental_id,
        )

        rental_json = serialize_rental(rental)
        context['rental'] = SimpleNamespace(
            **{
                **rental_json,
                'from_at': rental.requested_start_date,
                'to_at': rental.requested_end_date,
                'created_at': rental.created_at,
                'user': SimpleNamespace(**rental_json['user']),
            }
        )
        context['rental_json'] = rental_json
        context['current_status'] = rental_json['status']
        context['timeline'] = self._build_timeline(rental)
        context['items_json'] = [
            serialize_item(item)
            for item in rental.items.select_related(
                'rental_request',
                'inventory_item__category',
                'inventory_item__location',
                'inventory_item__owner',
            )
        ]
        context['rooms_json'] = [
            {
                'id': room_rental.pk,
                'name': room_rental.room.name,
                'room_id': room_rental.room.id,
                'period': (
                    f'{room_start:%d %b · %H:%M} – {room_end:%H:%M}'
                    if room_start and room_end else ''
                ),
                'start_date': room_start.strftime('%Y-%m-%d') if room_start else '',
                'start_time': room_start.strftime('%H:%M') if room_start else '',
                'end_date': room_end.strftime('%Y-%m-%d') if room_end else '',
                'end_time': room_end.strftime('%H:%M') if room_end else '',
                'seat': str(room_rental.people_count) if room_rental.people_count else '—',
            }
            for room_rental in rental.room_rentals.select_related('room')
            for _rs, _re in [(room_rental.get_start_date(), room_rental.get_end_date())]
            # Convert the UTC-aware stored datetimes to the local timezone so
            # the displayed/edited times match what was booked (input is
            # interpreted as local on save via make_aware).
            for room_start, room_end in [(
                timezone.localtime(_rs) if _rs else None,
                timezone.localtime(_re) if _re else None,
            )]
        ]
        context['issues_json'] = [
            {
                'id': issue.pk,
                'severity': issue.severity,
                'item': issue.rental_item.inventory_item.description if issue.rental_item else '',
                'num': issue.rental_item.inventory_item.inventory_number if issue.rental_item else '',
                'desc': issue.description,
                'by': _user_display_name(issue.reported_by),
                'at': issue.reported_at.isoformat() if issue.reported_at else None,
            }
            for issue in RentalIssue.objects.filter(
                rental_item__rental_request=rental,
            ).select_related(
                'rental_item__inventory_item',
                'reported_by',
                'reported_by__profile',
            )
        ]
        context['history_json'] = [
            {
                'at': transaction.performed_at.isoformat() if transaction.performed_at else None,
                'who': _user_display_name(transaction.performed_by),
                'what': (
                    f'{transaction.get_transaction_type_display()} {transaction.quantity}x '
                    f'{transaction.rental_item.inventory_item.description}'
                    if transaction.rental_item else transaction.get_transaction_type_display()
                ),
            }
            for transaction in RentalTransaction.objects.filter(
                rental_item__rental_request=rental,
            ).select_related(
                'performed_by',
                'performed_by__profile',
                'rental_item__inventory_item',
            )[:30]
        ]
        context['page_urls'] = {
            'list': self._safe_reverse('rental:list'),
            'print_slip': reverse('rental:print_slip', args=[rental.pk]),
            'print_pick_list': reverse('rental:print_pick_list', args=[rental.pk]),
            'duplicate': self._safe_reverse('rental:duplicate', args=[rental.pk]),
            'edit_note': self._safe_reverse('rental:edit_note', args=[rental.pk]),
            'detail': reverse('rental:rental_detail', args=[rental.pk]),
        }
        # Per-organization print form URLs for items in this rental
        context['print_slips'] = self._build_print_slip_urls(rental)
        context['show_pick_list'] = rental.status in ('reserved', 'issued')
        context['urls_json'] = {
            'extend': reverse('rental:extend', args=[rental.pk]),
            'mark_issued': reverse('rental:mark_issued', args=[rental.pk]),
            'cancel': reverse('rental:cancel', args=[rental.pk]),
            'close': reverse('rental:close', args=[rental.pk]),
            'send_reminder': reverse('rental:send_reminder', args=[rental.pk]),
            'report_issue': reverse('rental:report_issue', args=[rental.pk]),
            'return_page': reverse('rental:rental_return', args=[rental.pk]),
            'edit_items': f'{reverse("rental:rental_detail", args=[rental.pk])}#items',
            'edit_user': f'{reverse("rental:rental_detail", args=[rental.pk])}#user',
            'edit_period': f'{reverse("rental:rental_detail", args=[rental.pk])}#period',
            'resend_email': '#',
            'export_pdf': reverse('rental:print_slip', args=[rental.pk]),
            'inventory_search': reverse('rental:api_inventory_search'),
            'swap_item': reverse('rental:swap_item', args=[rental.pk]),
            'swap_unit': '#',
            'remove_item': reverse('rental:remove_item', args=[rental.pk]),
            'create_sign_session': reverse('rental:create_sign_session', args=[rental.pk]),
            'save_signature': reverse('rental:save_signature', args=[rental.pk]),
            'sign_session_status': '/rental/sign-session/',
            'sign_session_qr': '/rental/sign-session/',
            'change_user': reverse('rental:api_change_rental_user', args=[rental.pk]),
            'change_period': reverse('rental:api_change_rental_period', args=[rental.pk]),
            'add_items': reverse('rental:api_add_rental_items', args=[rental.pk]),
            'users_search': reverse('rental:api_users_search'),
            'confirm': reverse('rental:api_confirm_rental'),
            'add_room': reverse('rental:api_add_room_to_rental', args=[rental.pk]),
            'update_room': reverse('rental:api_update_room_rental', args=[rental.pk]),
            'remove_room': reverse('rental:api_remove_room_rental', args=[rental.pk]),
            'rooms_available': reverse('rental:api_rooms_available'),
            'equipment_sets': reverse('rental:admin_equipment_sets'),
            'equipment_sets_available': reverse('rental:api_equipment_sets_available'),
            'equipment_set_details': reverse('rental:api_equipment_set_details', args=[0]),
        }
        context['i18n_strings'] = _i18n_bundle()
        context['flags_json'] = _frontend_flags()
        context['sidebar_active'] = 'list'
        _add_sidebar_counts(context)

        return context

    def _build_print_slip_urls(self, rental):
        """Build print form URLs grouped by template (MSA vs non-MSA)."""
        return build_print_slip_urls(rental)

    def _build_timeline(self, rental):
        is_room_only = rental.items.count() == 0 and rental.room_rentals.count() > 0
        if is_room_only:
            steps = [
                ('created', _('Created'), rental.created_at),
                ('reserved', _('Reserved'), None),
            ]
        else:
            steps = [
                ('created', _('Created'), rental.created_at),
                ('reserved', _('Reserved'), None),
                ('issued', _('Issued'), rental.actual_start_date),
                ('returned', _('Returned'), rental.actual_end_date),
                ('closed', _('Closed'), None),
            ]
        status = serialize_rental(rental)['status']
        done_until = {
            'draft': 0,
            'reserved': 1,
            'issued': 2,
            'overdue': 2,
            'returned': 3,
            'cancelled': 1,
            'closed': 4 if not is_room_only else 2,
        }.get(status, 0)
        timeline = []
        for index, (step_id, label, at) in enumerate(steps):
            state = (
                'done' if index < done_until else
                'active' if index == done_until else
                'upcoming'
            )
            timeline.append({'id': step_id, 'label': label, 'at': at, 'state': state})
        return timeline

    def _safe_reverse(self, name, args=None, kwargs=None, fallback='#'):
        try:
            return reverse(name, args=args, kwargs=kwargs)
        except NoReverseMatch:
            return fallback


class RentalReturnView(StaffRequiredMixin, TemplateView):
    """Return processing view for staff React island."""

    template_name = 'rental/rental_return.html'

    def get_context_data(self, **kwargs):
        """Prepare context data for rental return page."""
        context = super().get_context_data(**kwargs)
        rental_id = kwargs.get('rental_id')
        now = timezone.now()
        base = RentalRequest.objects.all()
        context['sidebar'] = {
            'all_count': base.count(),
            'issued_count': base.filter(status='issued').count(),
            'overdue_count': base.filter(status='issued', requested_end_date__lt=now).count(),
            'due_today_count': base.filter(status='issued', requested_end_date__date=now.date()).count(),
            'pending_approval_count': base.filter(status='draft').count(),
        }

        try:
            rental = RentalRequest.objects.select_related(
                'user',
                'user__profile',
                'user__profile__media_authority',
                'created_by',
            ).prefetch_related(
                'items__inventory_item__category',
                'items__inventory_item__location',
                'items__transactions',
            ).get(id=rental_id)

            rental_json = serialize_rental(rental)
            context['rental'] = SimpleNamespace(
                **{
                    **rental_json,
                    'from_at': rental.requested_start_date,
                    'to_at': rental.requested_end_date,
                    'user': SimpleNamespace(**rental_json['user']),
                }
            )
            context['rental_json'] = rental_json
            context['items_json'] = [
                {
                    **serialize_item(item),
                    'outstanding': max(0, (item.quantity_issued or 0) - (item.quantity_returned or 0)),
                }
                for item in rental.items.select_related(
                    'rental_request',
                    'inventory_item__category',
                    'inventory_item__location',
                    'inventory_item__owner',
                ).prefetch_related('transactions')
            ]
            context['urls_json'] = {
                'submit_return': reverse('rental:api_return_rental_items'),
                'detail': reverse('rental:rental_detail', args=[rental.pk]),
                'scan_return': reverse('rental:api_scan_return_item'),
            }
            context['i18n_strings'] = _i18n_bundle()
            context['flags_json'] = _frontend_flags()
        except RentalRequest.DoesNotExist:
            context['error'] = _('Rental request not found')

        return context


def _json_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return {}


@login_required
@staff_member_required
def extend_rental(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    data = _json_body(request)
    new_end_date = data.get('to') or data.get('new_end_date')
    if not new_end_date:
        return JsonResponse({'error': _('New end date is required')}, status=400)

    from django.utils.dateparse import parse_datetime
    new_end_datetime = parse_datetime(new_end_date)
    if not new_end_datetime:
        return JsonResponse({'error': _('Invalid date format')}, status=400)
    if timezone.is_naive(new_end_datetime):
        new_end_datetime = timezone.make_aware(new_end_datetime)

    rental = get_object_or_404(RentalRequest, id=rental_id)
    if rental.status not in ['reserved', 'issued']:
        return JsonResponse({'error': _('Only active rentals can be extended')}, status=400)
    if new_end_datetime <= rental.requested_end_date:
        return JsonResponse({'error': _('New end date must be after current end date')}, status=400)
    if not RentalService.extend_rental(rental, new_end_datetime, request.user):
        return JsonResponse({'error': _('The rental cannot be extended to the selected end date.')}, status=400)
    return JsonResponse({'ok': True, 'success': True})


@login_required
@staff_member_required
def mark_issued(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    next_url = request.POST.get('next')
    redirect_after_post = next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
    )
    rental = get_object_or_404(RentalRequest, id=rental_id)
    if rental.status not in ['draft', 'reserved']:
        error_message = _('Only draft or reserved rentals can be issued')
        if redirect_after_post:
            messages.error(request, error_message)
            return redirect(next_url)
        return JsonResponse({'error': error_message}, status=400)
    if rental.items.count() == 0 and rental.room_rentals.count() > 0:
        error_message = _('Room-only rentals cannot be issued. Reservations expire automatically.')
        if redirect_after_post:
            messages.error(request, error_message)
            return redirect(next_url)
        return JsonResponse({'error': error_message}, status=400)
    with transaction.atomic():
        rental.status = 'issued'
        rental.actual_start_date = rental.actual_start_date or timezone.now()
        rental.save(update_fields=['status', 'actual_start_date', 'updated_at'])
        for rental_item in rental.items.select_related('inventory_item'):
            quantity_to_issue = rental_item.quantity_requested or 0
            if quantity_to_issue <= 0:
                continue
            RentalTransaction.objects.create(
                rental_item=rental_item,
                transaction_type='issue',
                quantity=quantity_to_issue,
                performed_by=request.user,
            )
    send_issued_confirmation_email(rental_request=rental)
    if redirect_after_post:
        messages.success(request, _('Rental marked as issued.'))
        return redirect(next_url)
    return JsonResponse({'ok': True, 'success': True})


@login_required
@staff_member_required
def cancel_rental(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    result = RentalService.cancel_rental(rental_id, request.user)
    if result.get('success'):
        return JsonResponse({'ok': True, **result})
    return JsonResponse({'error': result.get('error', _('Could not cancel rental'))}, status=400)


@login_required
@staff_member_required
def remove_item_from_rental(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        item_id = data.get('item_id')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': _('Invalid JSON body')}, status=400)

    if not item_id:
        return JsonResponse({'error': _('item_id is required')}, status=400)

    rental = get_object_or_404(RentalRequest, id=rental_id)

    if rental.status not in ('draft', 'reserved'):
        return JsonResponse({'error': _('Cannot remove items from issued, overdue, or returned rentals')}, status=400)

    if rental.has_any_signature():
        return JsonResponse({'error': _('Cannot modify items after rental is signed')}, status=400)

    try:
        rental_item = RentalItem.objects.get(id=item_id, rental_request=rental)
    except RentalItem.DoesNotExist:
        return JsonResponse({'error': _('Rental item not found')}, status=404)

    rental_item.delete()
    return JsonResponse({'ok': True})


@login_required
@staff_member_required
def swap_rental_item(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        current_item_id = data.get('current_item_id')
        new_inventory_item_id = data.get('new_inventory_item_id')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': _('Invalid JSON body')}, status=400)

    if not current_item_id or not new_inventory_item_id:
        return JsonResponse({'error': _('current_item_id and new_inventory_item_id are required')}, status=400)

    rental = get_object_or_404(RentalRequest, id=rental_id)

    if rental.status not in ('draft', 'reserved'):
        return JsonResponse({'error': _('Cannot swap items after issuance')}, status=400)

    if rental.has_any_signature():
        return JsonResponse({'error': _('Cannot modify items after rental is signed')}, status=400)

    try:
        rental_item = RentalItem.objects.get(id=current_item_id, rental_request=rental)
    except RentalItem.DoesNotExist:
        return JsonResponse({'error': _('Rental item not found')}, status=404)

    try:
        new_inventory_item = InventoryItem.objects.get(
            id=new_inventory_item_id,
            status='in_stock',
            available_for_rent=True,
        )
    except InventoryItem.DoesNotExist:
        return JsonResponse({'error': _('Inventory item not found or not available')}, status=404)

    rental_item.inventory_item = new_inventory_item
    rental_item.save(update_fields=['inventory_item'])
    return JsonResponse({'ok': True, 'item': serialize_item(rental_item)})


@login_required
@staff_member_required
def close_rental(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    rental = get_object_or_404(RentalRequest, id=rental_id)
    if rental.status == 'issued':
        return JsonResponse({'error': _('Issued rentals must be returned before closing')}, status=400)
    if rental.items.count() == 0 and rental.room_rentals.count() > 0:
        return JsonResponse({'error': _('Room-only rentals are closed automatically.')}, status=400)
    rental.status = 'closed'
    rental.save(update_fields=['status', 'updated_at'])
    return JsonResponse({'ok': True, 'success': True})


@login_required
@staff_member_required
def send_reminder(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    rental = get_object_or_404(RentalRequest, id=rental_id)
    send_reminder_email(rental_request=rental)
    return JsonResponse({'ok': True, 'success': True, 'message': _('Reminder queued')})


@login_required
@staff_member_required
def edit_note(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    rental = get_object_or_404(RentalRequest, id=rental_id)
    rental.notes = request.POST.get('note', rental.notes)
    rental.save(update_fields=['notes', 'updated_at'])
    return redirect('rental:rental_detail', rental_id=rental.pk)


@login_required
@staff_member_required
def report_issue(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    data = _json_body(request)
    rental_item = get_object_or_404(RentalItem, id=data.get('item_id'), rental_request_id=rental_id)
    issue = RentalIssue.objects.create(
        rental_item=rental_item,
        issue_type=data.get('issue_type', 'other'),
        description=data.get('description') or data.get('desc') or '',
        severity=data.get('severity', 'minor'),
        reported_by=request.user,
    )
    return JsonResponse({'ok': True, 'success': True, 'issue_id': issue.pk})


@login_required
@staff_member_required
def duplicate_rental(request, rental_id):
    source = get_object_or_404(RentalRequest, id=rental_id)
    with transaction.atomic():
        duplicate = RentalRequest.objects.create(
            user=source.user,
            created_by=request.user,
            project_name=source.project_name,
            purpose=source.purpose,
            requested_start_date=source.requested_start_date,
            requested_end_date=source.requested_end_date,
            status='draft',
            rental_type=source.rental_type,
            notes=source.notes,
        )
        for source_item in source.items.select_related('inventory_item'):
            RentalItem.objects.create(
                rental_request=duplicate,
                inventory_item=source_item.inventory_item,
                quantity_requested=source_item.quantity_requested,
                notes=source_item.notes,
            )
        for source_room in source.room_rentals.select_related('room'):
            RoomRental.objects.create(
                rental_request=duplicate,
                room=source_room.room,
                people_count=source_room.people_count,
                requested_start_date=source_room.requested_start_date,
                requested_end_date=source_room.requested_end_date,
                notes=source_room.notes,
            )
    return redirect('rental:rental_detail', rental_id=duplicate.pk)


def build_print_slip_urls(rental):
    """Build print form URLs grouped by template (MSA vs non-MSA).

    Items of different owners are printed on different forms, so a rental can
    need more than one slip; callers show one link per entry.
    """
    has_msa = False
    has_non_msa = False
    msa_org_id = None
    print_slips = []
    for item in rental.items.select_related('inventory_item__owner'):
        owner = item.inventory_item.owner
        if not owner:
            continue
        if owner.name == 'MSA':
            has_msa = True
            msa_org_id = owner.pk
        else:
            has_non_msa = True
    if has_msa and msa_org_id:
        print_slips.append({
            'org_id': msa_org_id,
            'org_name': 'MSA',
            'url': reverse('rental:print_form', args=[msa_org_id, rental.pk]),
        })
    if has_non_msa:
        print_slips.append({
            'org_id': 0,
            'org_name': str(_('Other')),
            'url': reverse('rental:print_form', args=[0, rental.pk]),
        })
    return print_slips


@login_required
@staff_member_required
def print_slip(request, rental_id):
    """Show print form selection or redirect if only one template group."""
    has_msa = False
    has_non_msa = False
    msa_org_id = None
    for item in RentalItem.objects.filter(
        rental_request_id=rental_id,
        inventory_item__owner__isnull=False,
    ).select_related('inventory_item__owner'):
        if item.inventory_item.owner.name == 'MSA':
            has_msa = True
            msa_org_id = item.inventory_item.owner_id
        else:
            has_non_msa = True

    msa_and_other = has_msa and has_non_msa

    if not msa_and_other:
        if has_msa and msa_org_id:
            return redirect('rental:print_form', org_id=msa_org_id, rental_id=rental_id)
        if has_non_msa:
            return redirect('rental:print_form', org_id=0, rental_id=rental_id)
        # Fallback
        try:
            msa_org = Organization.objects.only('id').get(name='MSA')
            return redirect('rental:print_form', org_id=msa_org.pk, rental_id=rental_id)
        except Organization.DoesNotExist:
            raise Http404(_('No print form available for this rental.'))

    print_slips = []
    if has_msa and msa_org_id:
        print_slips.append({
            'org_name': 'MSA',
            'url': reverse('rental:print_form', args=[msa_org_id, rental_id]),
        })
    if has_non_msa:
        print_slips.append({
            'org_name': str(_('Other')),
            'url': reverse('rental:print_form', args=[0, rental_id]),
        })

    return render(request, 'rental/print_slip_select.html', {
        'rental_id': rental_id,
        'print_slips': print_slips,
    })


@login_required
@staff_member_required
def print_form_msa_redirect(request, rental_id):
    """Redirect old MSA print form URL to new unified URL."""
    org = get_object_or_404(Organization, name='MSA')
    return redirect('rental:print_form', org_id=org.pk, rental_id=rental_id)


@login_required
@staff_member_required
def print_form_okmq_redirect(request, rental_id):
    """Redirect old OKMQ print form URL to new unified URL."""
    org = get_object_or_404(Organization, name='OKMQ')
    return redirect('rental:print_form', org_id=org.pk, rental_id=rental_id)


@login_required
@staff_member_required
def create_submit(request):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    data = _json_body(request)
    service_data = {
        'project_name': data.get('project') or data.get('project_name') or str(_('Untitled rental')),
        'purpose': data.get('purpose') or str(_('Rental request')),
        'start_date': data.get('from') or data.get('start_date'),
        'end_date': data.get('to') or data.get('end_date'),
        'action': 'reserved',
        'items': [
            {
                'inventory_item_id': item.get('id'),
                'quantity_requested': item.get('qty', 1),
                'notes': item.get('notes', ''),
            }
            for item in data.get('items', [])
        ],
        'rooms': [
            {
                'room_id': room.get('id'),
                'start_date': room.get('start_date', ''),
                'start_time': room.get('start_time', ''),
                'end_date': room.get('end_date', ''),
                'end_time': room.get('end_time', ''),
                'people_count': room.get('people_count', 1),
                'notes': room.get('notes', ''),
            }
            for room in data.get('rooms', [])
        ],
        'notes': data.get('note', ''),
    }
    user = get_object_or_404(OKUser, id=data.get('user_id'))
    result = RentalService.create_rental_request(service_data, user, request.user, is_user_request=False)
    if not result.get('success'):
        return JsonResponse({'error': result.get('error', _('Could not create rental'))}, status=400)
    rental_id = result['rental_id']
    return JsonResponse({
        'success': True,
        'rental_id': rental_id,
        'detail_url': reverse('rental:rental_detail', args=[rental_id]),
    })


@login_required
@staff_member_required
def quick_issue(request):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)
    data = _json_body(request)
    service_data = {
        'project_name': data.get('project') or str(_('Quick rental')),
        'purpose': data.get('purpose') or str(_('Quick issue')),
        'start_date': data.get('from'),
        'end_date': data.get('to'),
        'action': 'issued',
        'items': [
            {
                'inventory_item_id': item.get('id'),
                'quantity_requested': item.get('qty', 1),
                'notes': item.get('notes', ''),
            }
            for item in data.get('items', [])
        ],
        'rooms': [],
        'notes': data.get('note', ''),
    }
    user = get_object_or_404(OKUser, id=data.get('user_id'))
    result = RentalService.create_rental_request(service_data, user, request.user, is_user_request=False)
    if not result.get('success'):
        return JsonResponse({'error': result.get('error', _('Could not issue rental'))}, status=400)
    rental = get_object_or_404(RentalRequest, id=result['rental_id'])
    # Quick mode signs the rental right after issuing it, so hand back the
    # per-rental signature endpoints instead of making the client build them.
    return JsonResponse({
        'success': True,
        'rental_id': rental.pk,
        'detail_url': reverse('rental:rental_detail', args=[rental.pk]),
        'has_signature': rental.has_any_signature(),
        'signature_urls': {
            'save_signature': reverse('rental:save_signature', args=[rental.pk]),
            'create_sign_session': reverse(
                'rental:create_sign_session', args=[rental.pk]),
            # Signing on paper is a valid alternative, and a rental with items
            # of several owners needs one slip per owner.
            'print_slips': build_print_slip_urls(rental) or [{
                'org_name': str(_('Issue slip')),
                'url': reverse('rental:print_slip', args=[rental.pk]),
            }],
        },
    })


class RentalReturnWorkflowView(StaffRequiredMixin, TemplateView):
    template_name = 'rental/admin_return.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.get('q', '').strip()
        user_id = self.request.GET.get('user_id')
        now = timezone.now()

        base = RentalRequest.objects.all()
        context['sidebar'] = {
            'all_count': base.count(),
            'issued_count': base.filter(status='issued').count(),
            'overdue_count': base.filter(status='issued', requested_end_date__lt=now).count(),
            'due_today_count': base.filter(status='issued', requested_end_date__date=now.date()).count(),
            'pending_approval_count': base.filter(status='draft').count(),
        }

        if user_id:
            user = get_object_or_404(OKUser, id=user_id)
            context['selected_user'] = serialize_user(user)
            rentals = RentalRequest.objects.select_related(
                'user', 'user__profile',
            ).prefetch_related(
                'items', 'room_rentals',
            ).filter(user=user, status='issued').order_by('-created_at')

            user_rentals = []
            for r in rentals:
                derived_status = 'overdue' if r.requested_end_date < now else 'issued'
                overdue_days = 0
                if derived_status == 'overdue':
                    overdue_days = max((now.date() - r.requested_end_date.date()).days, 0)

                user_rentals.append({
                    'id': f"R-{r.created_at.strftime('%y%m')}-{r.pk:04d}",
                    'pk': r.pk,
                    'project': r.project_name,
                    'from_at': r.requested_start_date,
                    'to_at': r.requested_end_date,
                    'item_count': r.items.count(),
                    'room_count': r.room_rentals.count(),
                    'status': derived_status,
                    'overdue': derived_status == 'overdue',
                    'overdue_days': overdue_days,
                    'detail_url': reverse('rental:rental_detail', args=[r.pk]),
                    'return_url': reverse('rental:rental_return', args=[r.pk]),
                })

            context['user_rentals'] = user_rentals
        elif query:
            context['search_results'] = [
                serialize_user(u)
                for u in OKUser.objects.select_related('profile', 'profile__media_authority').filter(
                    is_active=True,
                ).filter(
                    Q(email__icontains=query)
                    | Q(profile__first_name__icontains=query)
                    | Q(profile__last_name__icontains=query)
                ).distinct().order_by('last_name', 'first_name', 'email')[:30]
            ]
            context['search_query'] = query
        else:
            # Show users with active rentals upfront
            active_user_ids = RentalRequest.objects.filter(
                status='issued'
            ).values_list('user_id', flat=True).distinct()
            context['active_users'] = [
                serialize_user(u)
                for u in OKUser.objects.select_related(
                    'profile', 'profile__media_authority'
                ).filter(
                    id__in=active_user_ids, is_active=True
                ).order_by('last_name', 'first_name', 'email')[:50]
            ]

        return context


class UserRentalDetailView(LoginRequiredMixin, TemplateView):
    """
    User-facing detail view for a specific rental request.

    Shows summary details for the owning user without staff actions.
    """

    template_name = 'rental/user_rental_detail.html'

    def get_context_data(self, **kwargs):
        """
        Prepare context data for user rental detail page.

        Args:
            **kwargs: Additional context data including rental_id

        Returns:
            dict: Context with rental details
        """
        context = super().get_context_data(**kwargs)
        rental_id = kwargs.get('rental_id')

        try:
            from .models import RentalRequest
            rental = RentalRequest.objects.select_related('user', 'created_by').prefetch_related(
                'items__inventory_item__owner',
                'items__inventory_item__location',
                'items__inventory_item__category',
                'items__issues',
                'room_rentals__room'
            ).get(id=rental_id, user=self.request.user)

            context['rental'] = rental
        except Exception as e:
            context['error'] = str(e)

        return context


@login_required
@staff_member_required
def api_extend_rental(request):
    """
    Extend a rental request.

    Extends the end date of an active rental request with
    validation of the new date format and business rules.

    Args:
        request: HTTP request object with new end date

    Returns:
        JsonResponse: Success status and confirmation message
    """

    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        rental_id = data.get('rental_id')
        new_end_date = data.get('new_end_date')

        if not rental_id or not new_end_date:
            return JsonResponse({'error': _('Rental ID and new end date are required')}, status=400)

        from .models import RentalRequest
        from django.utils.dateparse import parse_datetime

        rental_request = get_object_or_404(RentalRequest, id=rental_id)

        # Check if rental can be extended
        if rental_request.status not in ['reserved', 'issued']:
            return JsonResponse({'error': _('Only active rentals can be extended')}, status=400)

        # Parse and validate new end date
        from django.utils import timezone
        from django.utils.dateparse import parse_date
        import datetime

        try:
            new_end_datetime = parse_datetime(new_end_date)

            # If parse_datetime fails, try to parse as datetime-local format
            if not new_end_datetime:
                # Try parsing datetime-local format (YYYY-MM-DDTHH:MM)
                if 'T' in new_end_date and len(new_end_date) == 16:
                    try:
                        # Parse as naive datetime and make it timezone-aware
                        naive_datetime = datetime.datetime.fromisoformat(new_end_date)
                        new_end_datetime = timezone.make_aware(naive_datetime)
                    except:
                        pass

                # If still not parsed, try other formats
                if not new_end_datetime:
                    # Try parsing date only and add default time
                    date_part = new_end_date.split('T')[0] if 'T' in new_end_date else new_end_date
                    date_only = parse_date(date_part)
                    if date_only:
                        # Add default time (23:59) if only date is provided
                        default_time = datetime.time(hour=23, minute=59)
                        new_end_datetime = timezone.make_aware(datetime.datetime.combine(date_only, default_time))

            if not new_end_datetime:
                return JsonResponse({'error': _('Invalid date format. Please use YYYY-MM-DDTHH:MM or ISO format')}, status=400)

            # Ensure both dates are timezone-aware for comparison
            current_end_date = rental_request.requested_end_date
            if timezone.is_naive(current_end_date):
                current_end_date = timezone.make_aware(current_end_date)
            if timezone.is_naive(new_end_datetime):
                new_end_datetime = timezone.make_aware(new_end_datetime)

            if new_end_datetime <= current_end_date:
                return JsonResponse({'error': _('New end date must be after current end date')}, status=400)

            is_valid_period, error_message = validate_working_hours_period(
                rental_request.requested_start_date,
                new_end_datetime,
            )
            if not is_valid_period:
                return JsonResponse({'error': error_message}, status=400)

        except Exception as e:
            return JsonResponse({'error': _('Invalid date format: {error}').format(error=str(e))}, status=400)

        if not RentalService.extend_rental(rental_request, new_end_datetime, request.user):
            return JsonResponse({'error': _('The rental cannot be extended to the selected end date.')}, status=400)

        return JsonResponse({
            'success': True,
            'message': _('Rental request {rental_id} has been extended until {end_date}').format(
                rental_id=rental_id,
                end_date=new_end_datetime.strftime("%d.%m.%Y %H:%M")
            )
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)



class RentalStatsView(StaffRequiredMixin, TemplateView):
    """
    Statistics and administration page for rental system.

    Provides overview statistics and administrative functions
    for managing the rental system.
    """

    template_name = 'rental/rental_stats.html'

    def get_context_data(self, **kwargs):
        """
        Prepare context data for rental statistics page.

        Args:
            **kwargs: Additional context data

        Returns:
            dict: Context with rental system statistics
        """
        context = super().get_context_data(**kwargs)

        try:
            from .models import RentalItem
            from .models import RentalRequest
            from django.db.models import Count
            from django.db.models import Q
            from django.db.models import Sum

            # Overall statistics
            total_rentals = RentalRequest.objects.count()
            active_rentals = RentalRequest.objects.filter(status__in=['reserved', 'issued']).count()
            total_users = OKUser.objects.filter(rentalrequest__isnull=False).distinct().count()
            total_items = len(inventory_service.get_available_items())

            context.update({
                'total_rentals': total_rentals,
                'active_rentals': active_rentals,
                'total_users': total_users,
                'total_items': total_items,
            })

        except Exception as e:
            context['error'] = str(e)

        return context


class EquipmentSetsAdminView(StaffRequiredMixin, TemplateView):
    """
    Admin page for managing equipment sets.

    Provides staff interface for viewing, creating, and deleting
    reusable equipment sets.
    """

    template_name = 'rental/admin_equipment_sets.html'

    def get_context_data(self, **kwargs):
        """
        Prepare context data for equipment sets admin page.

        Args:
            **kwargs: Additional context data

        Returns:
            dict: Context with API URLs and sidebar counts
        """
        context = super().get_context_data(**kwargs)
        context.update({
            'initial_json': {
                'urls': {
                    'api_get_all_equipment_sets': reverse('rental:api_get_all_equipment_sets'),
                    'api_create_equipment_set': reverse('rental:api_create_equipment_set'),
                    'api_delete_equipment_set': reverse('rental:api_delete_equipment_set', kwargs={'pk': 0}),
                    'api_inventory_search': reverse('rental:api_inventory_search'),
                },
            },
            'sidebar': {
                'all_count': RentalRequest.objects.count(),
                'issued_count': RentalRequest.objects.filter(status='issued').count(),
                'overdue_count': RentalRequest.objects.filter(status='issued', requested_end_date__lt=timezone.now()).count(),
                'due_today_count': RentalRequest.objects.filter(
                    status='issued',
                    requested_end_date__date=timezone.now().date(),
                ).count(),
                'pending_approval_count': RentalRequest.objects.filter(status='draft').count(),
            },
            'i18n_strings': _i18n_bundle(),
        })
        return context


def _item_thumb_url(item):
    """Thumbnail URL of an item's first available photo, or ``None``.

    Iterates the prefetched ``images`` cache so callers pay no extra query.
    """
    for image in item.images.all():
        if image.is_available:
            return reverse('inventory:item_image_thumb', args=[image.id])
    return None


def _room_thumb_url(room):
    """Small-thumbnail URL for a room's primary image, or ``None``.

    Points at the ``room_image`` view with ``?size=thumb`` so calendars load a
    downscaled JPEG rather than the full-resolution original. Uses the same
    staff-only view as the room admin, so it works even though nginx runs on a
    separate VM.
    """
    image = room.primary_image
    if not image:
        return None
    return reverse('rental:room_image', args=[image.pk]) + '?size=thumb'


def _room_full_url(room):
    """Full-size URL for a room's primary image (for the zoom lightbox)."""
    image = room.primary_image
    return reverse('rental:room_image', args=[image.pk]) if image else None


def _room_photo_urls(room):
    """Full-size URLs for all of a room's photos, in display order."""
    return [reverse('rental:room_image', args=[img.pk])
            for img in room.images.all()]


def _item_full_url(item):
    """Full-size URL of an item's first available photo, or ``None``."""
    for image in item.images.all():
        if image.is_available:
            return reverse('inventory:item_image', args=[image.id])
    return None


def _item_photo_urls(item):
    """Full-size URLs for all available photos of an item, in filename order."""
    return [reverse('inventory:item_image', args=[img.id])
            for img in item.images.all() if img.is_available]


def _room_thumbnail_path(room_image):
    """Return the cache path for a room photo's small thumbnail."""
    from pathlib import Path
    root = Path(settings.MEDIA_ROOT)
    if not root.is_absolute():
        root = Path(settings.BASE_DIR) / root
    return root / 'room_thumbnails' / f'{room_image.pk}.jpg'


def _ensure_room_thumbnail(room_image):
    """Return an up-to-date thumbnail path for ``room_image`` or ``None``.

    Reuses the inventory thumbnail generator (Pillow) and caches the result
    under ``MEDIA_ROOT/room_thumbnails/``. Fails softly to ``None`` so the view
    can fall back to the original.
    """
    from inventory.images import generate_thumbnail
    from pathlib import Path
    try:
        source = Path(room_image.image.path)
    except (ValueError, NotImplementedError):
        return None
    if not source.is_file():
        return None
    target = _room_thumbnail_path(room_image)
    try:
        fresh = (target.is_file()
                 and target.stat().st_mtime >= source.stat().st_mtime)
    except OSError:
        fresh = False
    if fresh:
        return target
    return target if generate_thumbnail(source, target) else None


class InventoryCalendarDayView(StaffRequiredMixin, TemplateView):
    template_name = 'rental/inventory_calendar_day.html'

    def get_context_data(self, **kwargs):
        from datetime import timedelta
        from django.utils import timezone
        context = super().get_context_data(**kwargs)
        date_str = self.request.GET.get('date')
        try:
            from django.utils.dateparse import parse_date
            day = parse_date(date_str) if date_str else timezone.now().date()
        except Exception:
            day = timezone.now().date()
        context['day'] = day
        context['today'] = timezone.now().date()
        context['prev_day'] = day - timedelta(days=1)
        context['next_day'] = day + timedelta(days=1)
        
        day_start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
        day_end = day_start + timedelta(days=1)
        
        search_query = self.request.GET.get('q', '').strip()
        status_filter = self.request.GET.get('status', '')
        sort_by = self.request.GET.get('sort', 'status')
        
        from inventory.models import InventoryItem
        items = InventoryItem.objects.filter(
            available_for_rent=True, status='in_stock'
        ).select_related('category', 'location').prefetch_related(
            'rentalitem_set__rental_request', 'images'
        )
        
        if search_query:
            items = items.filter(
                Q(description__icontains=search_query) | Q(inventory_number__icontains=search_query)
            )
        
        items_data = []
        for item in items:
            thumb_url = _item_thumb_url(item)
            photos_json = json.dumps(_item_photo_urls(item))
            active_rentals = item.rentalitem_set.filter(
                rental_request__status__in=['reserved', 'issued'],
                rental_request__requested_start_date__lt=day_end,
                rental_request__requested_end_date__gt=day_start,
            ).select_related('rental_request__user', 'rental_request__user__profile')

            if active_rentals.exists():
                for rental_item in active_rentals:
                    r = rental_item.rental_request
                    items_data.append({
                        'name': item.description,
                        'num': item.inventory_number,
                        'thumb_url': thumb_url,
                        'photos_json': photos_json,
                        'category': item.category.name if item.category else '—',
                        'status': r.status,
                        'rental_id': f"R-{r.created_at.strftime('%y%m')}-{r.pk:04d}",
                        'user': _user_display_name(r.user),
                        'from': r.requested_start_date,
                        'to': r.requested_end_date,
                    })
            else:
                items_data.append({
                    'name': item.description,
                    'num': item.inventory_number,
                    'thumb_url': thumb_url,
                    'photos_json': photos_json,
                    'category': item.category.name if item.category else '—',
                    'status': 'available',
                    'rental_id': None,
                    'user': None,
                    'from': None,
                    'to': None,
                })
        
        if status_filter:
            items_data = [i for i in items_data if i['status'] == status_filter]
        
        if sort_by == 'name':
            items_data.sort(key=lambda x: x['name'].lower())
        elif sort_by == 'category':
            items_data.sort(key=lambda x: x['category'].lower())
        else:
            items_data.sort(key=lambda x: (x['status'] != 'available', x['name'].lower()))
        
        context['items'] = items_data
        context['search_query'] = search_query
        context['status_filter'] = status_filter
        context['sort_by'] = sort_by
        context['sidebar_active'] = 'calendar'
        _add_sidebar_counts(context)
        return context


class RoomCalendarDayView(StaffRequiredMixin, TemplateView):
    template_name = 'rental/room_calendar_day.html'

    def get_context_data(self, **kwargs):
        from datetime import timedelta
        from django.utils import timezone
        context = super().get_context_data(**kwargs)
        date_str = self.request.GET.get('date')
        try:
            from django.utils.dateparse import parse_date
            day = parse_date(date_str) if date_str else timezone.now().date()
        except Exception:
            day = timezone.now().date()
        context['day'] = day
        context['today'] = timezone.now().date()
        context['prev_day'] = day - timedelta(days=1)
        context['next_day'] = day + timedelta(days=1)
        context['sidebar_active'] = 'room_calendar'
        context['i18n_strings'] = _i18n_bundle()
        context['flags_json'] = _frontend_flags()
        _add_sidebar_counts(context)
        return context


class RoomCalendarWeekView(StaffRequiredMixin, TemplateView):
    template_name = 'rental/room_calendar_week.html'

    def get_context_data(self, **kwargs):
        from .models import Room
        from .models import RoomRental
        from datetime import timedelta
        from django.utils import timezone
        context = super().get_context_data(**kwargs)
        date_str = self.request.GET.get('date')
        try:
            from django.utils.dateparse import parse_date
            ref_day = parse_date(date_str) if date_str else timezone.now().date()
        except Exception:
            ref_day = timezone.now().date()
        context['ref_day'] = ref_day
        context['today'] = timezone.now().date()
        context['prev_week'] = ref_day - timedelta(days=7)
        context['next_week'] = ref_day + timedelta(days=7)

        monday = ref_day - timedelta(days=ref_day.weekday())
        week_days = [monday + timedelta(days=i) for i in range(7)]

        rooms = Room.objects.filter(is_active=True).order_by('name').prefetch_related('images')

        week_start = timezone.make_aware(timezone.datetime.combine(week_days[0], timezone.datetime.min.time()))
        week_end = week_start + timedelta(days=7)

        all_bookings = RoomRental.objects.filter(
            room__in=rooms,
            rental_request__status__in=['reserved', 'issued'],
        ).select_related('rental_request__user__profile', 'room').order_by('requested_start_date')

        bookings_by_room_date = {}
        for b in all_bookings:
            start = b.get_start_date()
            end = b.get_end_date()
            if start and end and start < week_end and end > week_start:
                d = start.date()
                if b.room_id not in bookings_by_room_date:
                    bookings_by_room_date[b.room_id] = {}
                if d not in bookings_by_room_date[b.room_id]:
                    bookings_by_room_date[b.room_id][d] = []
                bookings_by_room_date[b.room_id][d].append({
                    'user': _user_display_name(b.rental_request.user) if b.rental_request and b.rental_request.user else '—',
                    'time': f"{start.strftime('%H:%M')} – {end.strftime('%H:%M')}",
                    'project': b.rental_request.project_name or '',
                })

        rooms_data = []
        for room in rooms:
            room_bookings = bookings_by_room_date.get(room.id, {})
            days_data = []
            for d in week_days:
                days_data.append({
                    'date': d,
                    'bookings': room_bookings.get(d, []),
                })
            rooms_data.append({
                'name': room.name,
                'image_url': _room_thumb_url(room),
                'image_urls_json': json.dumps(_room_photo_urls(room)),
                'days': days_data,
            })

        context['rooms_data'] = rooms_data
        context['week_days'] = week_days
        context['sidebar_active'] = 'room_calendar'
        _add_sidebar_counts(context)
        return context


class RoomCalendarMonthView(StaffRequiredMixin, TemplateView):
    template_name = 'rental/room_calendar_month.html'

    def get_context_data(self, **kwargs):
        from .models import Room
        from .models import RoomRental
        from datetime import timedelta
        from django.utils import timezone
        import calendar
        context = super().get_context_data(**kwargs)
        date_str = self.request.GET.get('date')
        try:
            from django.utils.dateparse import parse_date
            ref_day = parse_date(date_str) if date_str else timezone.now().date()
        except Exception:
            ref_day = timezone.now().date()
        context['ref_day'] = ref_day
        context['today'] = timezone.now().date()

        year, month = ref_day.year, ref_day.month
        cal = calendar.Calendar(firstweekday=0)
        month_days = cal.monthdatescalendar(year, month)
        context['month_name'] = f"{ref_day.strftime('%B %Y')}"

        prev_month = ref_day.replace(day=1) - timedelta(days=1)
        next_month = (ref_day.replace(day=28) + timedelta(days=4)).replace(day=1)
        context['prev_month'] = prev_month
        context['next_month'] = next_month

        rooms = list(
            Room.objects.filter(is_active=True).order_by('name')
            .prefetch_related('images')
        )
        for room in rooms:
            # Attributes consumed by the template for the thumbnail and zoom.
            room.image_url = _room_thumb_url(room)
            room.image_urls_json = json.dumps(_room_photo_urls(room))

        month_start = timezone.make_aware(timezone.datetime.combine(
            month_days[0][0], timezone.datetime.min.time()
        ))
        month_end = timezone.make_aware(timezone.datetime.combine(
            month_days[-1][-1] + timedelta(days=1), timezone.datetime.min.time()
        ))

        all_bookings = RoomRental.objects.filter(
            room__in=rooms,
            rental_request__status__in=['reserved', 'issued'],
        ).select_related('rental_request__user__profile', 'room').order_by('requested_start_date')

        bookings_by_room_date = {}
        for b in all_bookings:
            start = b.get_start_date()
            end = b.get_end_date()
            if not (start and end and start < month_end and end > month_start):
                continue
            r_id = b.room_id
            d = start.date()
            if r_id not in bookings_by_room_date:
                bookings_by_room_date[r_id] = {}
            if d not in bookings_by_room_date[r_id]:
                bookings_by_room_date[r_id][d] = []
            bookings_by_room_date[r_id][d].append({
                'user': _user_display_name(b.rental_request.user) if b.rental_request and b.rental_request.user else '—',
                'project': b.rental_request.project_name or '',
                'time': start.strftime('%H:%M'),
            })

        context['rooms'] = rooms
        context['month_days'] = month_days
        context['bookings_by_room_date'] = bookings_by_room_date
        context['sidebar_active'] = 'room_calendar'
        _add_sidebar_counts(context)
        return context


class InventoryCalendarWeekView(StaffRequiredMixin, TemplateView):
    template_name = 'rental/inventory_calendar_week.html'

    def get_context_data(self, **kwargs):
        from datetime import timedelta
        from django.utils import timezone
        context = super().get_context_data(**kwargs)
        date_str = self.request.GET.get('date')
        try:
            from django.utils.dateparse import parse_date
            ref = parse_date(date_str) if date_str else timezone.now().date()
        except Exception:
            ref = timezone.now().date()
        context['ref_day'] = ref
        context['prev_week'] = ref - timedelta(days=7)
        context['next_week'] = ref + timedelta(days=7)
        context['week_days'] = [ref + timedelta(days=i) for i in range(7)]
        context['sidebar_active'] = 'calendar'
        _add_sidebar_counts(context)
        return context


@login_required
@staff_member_required
def api_reset_rental_system(request):
    """
    Reset rental system (DANGER: This will clear all rental data).

    Provides administrative functions to reset rental data, inventory quantities,
    or cancel active rentals. Requires special confirmation code for security.

    Args:
        request: HTTP request object with action and confirmation code

    Returns:
        JsonResponse: Success status and operation result
    """
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        action = data.get('action')
        confirm_code = data.get('confirm_code')

        # Security check
        if confirm_code != 'RESET_ALL_DATA':
            return JsonResponse({'error': _('Invalid confirmation code')}, status=400)

        from .models import RentalIssue
        from .models import RentalItem
        from .models import RentalRequest
        from .models import RentalTransaction

        if action == 'reset_all':
            # Delete all rental data
            RentalIssue.objects.all().delete()
            RentalTransaction.objects.all().delete()
            RentalItem.objects.all().delete()
            RentalRequest.objects.all().delete()

            # Reset inventory quantities through the service
            # This action is only possible through direct model access, which we're trying to avoid
            # So we'll skip this part or implement a special endpoint for it
            message = _('All rental data has been reset (inventory quantities reset not supported through API)')

        elif action == 'reset_inventory_quantities':
            # Only reset inventory quantities through the service
            # This action is only possible through direct model access, which we're trying to avoid
            message = _('Inventory quantities reset not supported through API')

        elif action == 'cancel_active_rentals':
            # Cancel all active rentals
            from django.utils import timezone

            active_rentals = RentalRequest.objects.filter(status__in=['reserved', 'issued'])
            count = active_rentals.count()

            active_rentals.update(
                status='cancelled',
                actual_end_date=timezone.now()
            )

            # Reset inventory quantities through the service
            # This action is only possible through direct model access, which we're trying to avoid
            message = _('{count} active rentals have been cancelled (inventory quantities reset not supported through API)').format(count=count)

        else:
            return JsonResponse({'error': _('Invalid action')}, status=400)

        return JsonResponse({
            'success': True,
            'message': message
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_get_all_rentals(request):
    """
    Get all rentals with filtering options.

    Returns paginated list of all rentals with optional filtering
    by status and user search, including summary information.

    Args:
        request: HTTP request object with filter and pagination parameters

    Returns:
        JsonResponse: Paginated list of rentals with metadata
    """
    try:
        from .models import RentalRequest
        from django.core.paginator import Paginator

        # Get filter parameters
        status = request.GET.get('status', 'all')
        type_filter = request.GET.get('type', 'all')
        user_query = request.GET.get('user', '')
        page = int(request.GET.get('page', 1))

        # Base queryset
        rentals = RentalRequest.objects.select_related(
            'user', 'created_by'
        ).prefetch_related(
            'items__inventory_item',
            'room_rentals__room'
        ).order_by('-created_at')

        # Apply filters
        if status != 'all':
            rentals = rentals.filter(status=status)

        if type_filter != 'all':
            if type_filter == 'equipment':
                # Only equipment rentals (have items, no rooms)
                rentals = rentals.filter(items__isnull=False).exclude(room_rentals__isnull=False)
            elif type_filter == 'room':
                # Only room rentals (have rooms, no items)
                rentals = rentals.filter(room_rentals__isnull=False).exclude(items__isnull=False)
            elif type_filter == 'mixed':
                # Mixed rentals (have both items and rooms)
                rentals = rentals.filter(items__isnull=False, room_rentals__isnull=False)

        if user_query:
            # Safe filtering - only include profile filters if profile exists
            q_filters = Q(user__email__icontains=user_query)
            try:
                q_filters |= Q(user__profile__first_name__icontains=user_query) | Q(user__profile__last_name__icontains=user_query)
            except:
                pass  # Skip profile filtering if it causes issues
            rentals = rentals.filter(q_filters)

        # Paginate
        paginator = Paginator(rentals.distinct(), 20)
        page_obj = paginator.get_page(page)

        # PERFORMANCE OPTIMIZATION: Re-fetch with prefetch after pagination
        # Paginator breaks prefetch_related, so we need to re-apply it
        rental_ids = [r.id for r in page_obj]
        optimized_rentals = RentalRequest.objects.filter(
            id__in=rental_ids
        ).select_related(
            'user', 'created_by', 'user__profile', 'created_by__profile'
        ).prefetch_related(
            'items__inventory_item', 
            'room_rentals__room'
        )
        
        # Create dict for quick lookup maintaining page order
        rentals_dict = {r.id: r for r in optimized_rentals}
        ordered_rentals = [rentals_dict[rid] for rid in rental_ids if rid in rentals_dict]

        # Serialize data
        result = []
        for rental in ordered_rentals:
            # Safely get user name
            try:
                user_name = f"{rental.user.profile.first_name} {rental.user.profile.last_name}" if hasattr(rental.user, 'profile') and rental.user.profile else rental.user.email
            except:
                user_name = rental.user.email

            # Safely get created_by name
            try:
                created_by_name = f"{rental.created_by.profile.first_name} {rental.created_by.profile.last_name}" if rental.created_by and hasattr(rental.created_by, 'profile') and rental.created_by.profile else (rental.created_by.email if rental.created_by else 'N/A')
            except:
                created_by_name = rental.created_by.email if rental.created_by else 'N/A'

            items_summary = []
            for item in rental.items.all()[:3]:  # Show first 3 items
                items_summary.append({
                    'description': item.inventory_item.description or item.inventory_item.inventory_number,
                    'quantity': item.quantity_requested
                })

            # Get rooms summary
            rooms_summary = []
            for room_rental in rental.room_rentals.all()[:3]:  # Show first 3 rooms
                rooms_summary.append({
                    'name': room_rental.room.name,
                    'people_count': room_rental.people_count
                })

            result.append({
                'id': rental.id if rental else 0,
                'project_name': rental.project_name or '',
                'user_name': user_name or '',
                'user_email': rental.user.email if rental.user else '',
                'created_by_name': created_by_name or '',
                'status': rental.status or '',
                'rental_type': rental.rental_type or '',
                'created_at': rental.created_at.strftime('%d.%m.%Y %H:%M') if rental.created_at else '',
                'requested_start_date': rental.requested_start_date.isoformat() if rental.requested_start_date else '',
                'requested_end_date': rental.requested_end_date.isoformat() if rental.requested_end_date else '',
                'actual_end_date': rental.actual_end_date.isoformat() if rental.actual_end_date else '',
                'items_count': rental.items.count() if hasattr(rental, 'items') else 0,
                'rooms_count': rental.room_rentals.count() if hasattr(rental, 'room_rentals') else 0,
                'items_summary': items_summary or [],
                'rooms_summary': rooms_summary or []
            })

        return JsonResponse({
            'rentals': result or [],
            'has_next': page_obj.has_next() if page_obj else False,
            'has_previous': page_obj.has_previous() if page_obj else False,
            'current_page': page or 1,
            'total_pages': paginator.num_pages if paginator else 1,
            'total_count': paginator.count if paginator else 0
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_get_all_inventory_status(request):
    """
    Get inventory status overview.

    Returns comprehensive inventory status information including
    quantities, locations, and categories with optional filtering.

    Args:
        request: HTTP request object with filter parameters

    Returns:
        JsonResponse: List of inventory items with status information
    """
    try:
        # Get filter parameters
        owner_filter = request.GET.get('owner', 'all')
        status_filter = request.GET.get('status', 'all')

        # Get all available items through the service
        items = inventory_service.get_available_items()

        # Apply filters
        filtered_items = []
        for item in items:
            if not item:
                continue
                
            # Safely get owner data
            owner_data = item.get('owner')
            if owner_data is None:
                owner_name = 'N/A'
            elif isinstance(owner_data, dict):
                owner_name = owner_data.get('name', 'N/A')
            else:
                owner_name = str(owner_data) if owner_data else 'N/A'
            
            # Apply owner filter
            if owner_filter != 'all':
                if owner_name != owner_filter:
                    continue

            # Apply status filter
            if status_filter == 'rented':
                if (item.get('rented_quantity') or 0) <= 0:
                    continue
            elif status_filter == 'reserved':
                if (item.get('reserved_quantity') or 0) <= 0:
                    continue
            elif status_filter == 'available':
                if (item.get('reserved_quantity') or 0) > 0 or (item.get('rented_quantity') or 0) > 0:
                    continue

            # Safely get location data
            location_data = item.get('location')
            if location_data is None:
                location_path = 'N/A'
            elif isinstance(location_data, dict):
                location_path = location_data.get('full_path') or location_data.get('name', 'N/A')
            else:
                location_path = str(location_data) if location_data else 'N/A'
            
            # Safely get category data
            category_data = item.get('category')
            if category_data is None:
                category_name = 'N/A'
            elif isinstance(category_data, dict):
                category_name = category_data.get('name', 'N/A')
            else:
                category_name = str(category_data) if category_data else 'N/A'

            filtered_items.append({
                'id': item.get('id'),
                'inventory_number': item.get('inventory_number', ''),
                'description': item.get('description') or item.get('inventory_number', ''),
                'owner': owner_name,
                'location': location_path,
                'category': category_name,
                'reserved_quantity': item.get('reserved_quantity') or 0,
                'rented_quantity': item.get('rented_quantity') or 0,
                'status': item.get('status') or ''
            })

        return JsonResponse({
            'items': filtered_items or [],
            'total_count': len(filtered_items) if filtered_items else 0
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_inventory_calendar(request):
    """
    Aggregate availability for inventory over a period.

    Query params:
      - mode: 'day' | 'week' (default: day)
      - date: ISO date (YYYY-MM-DD), default: today

    For day mode: returns hours 10..18 per item with occupied/available.
    For week mode: returns 7 days per item with occupied/available (any overlap in day).
    """
    try:
        from .models import RentalItem
        from datetime import datetime
        from datetime import timedelta
        from django.utils import timezone
        from django.utils.dateparse import parse_date

        mode = request.GET.get('mode', 'day')
        day = parse_date(request.GET.get('date') or '') or timezone.now().date()

        # Get inventory items through the service
        items_list = inventory_service.get_available_items()
        item_ids = [it['id'] for it in items_list]

        if mode == 'week':
            start_date = day
            end_date = day + timedelta(days=6)
        else:
            start_date = day
            end_date = day

        start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))

        rentals = (
            RentalItem.objects.select_related('rental_request')  # avoid selecting inventory_item to prevent model init side effects
            .filter(
                rental_request__status__in=['reserved', 'issued'],
                rental_request__requested_start_date__lte=end_dt,
                rental_request__requested_end_date__gte=start_dt,
                inventory_item_id__in=item_ids
            )
        )

        item_id_to_rentals = {}
        for ri in rentals:
            item_id_to_rentals.setdefault(ri.inventory_item_id, []).append(ri)

        result = []

        if mode == 'week':
            days = [start_date + timedelta(days=i) for i in range(7)]
            for it in items_list:
                day_statuses = []
                conflicts = item_id_to_rentals.get(it['id'], [])
                for d in days:
                    d_start, d_end = get_day_working_window(d)
                    status = 'available'
                    has_reserved = False
                    selected_user = None
                    selected_req = None
                    if not d_start or not d_end:
                        day_statuses.append({
                            'date': d.isoformat(),
                            'status': 'closed',
                            'user_name': None,
                            'info': None,
                        })
                        continue
                    for ri in conflicts:
                        rs = timezone.localtime(ri.rental_request.requested_start_date)
                        re = timezone.localtime(ri.rental_request.requested_end_date)
                        if rs <= d_end and re >= d_start:
                            # Prefer issued
                            if ri.rental_request.status == 'issued':
                                status = 'issued'
                                selected_req = ri
                                break
                            elif ri.rental_request.status == 'reserved':
                                has_reserved = True
                                if not selected_req:
                                    selected_req = ri
                    if status != 'issued' and has_reserved:
                        status = 'reserved'
                    info = None
                    if selected_req:
                        user = selected_req.rental_request.user
                        try:
                            profile = user.profile
                            full = f"{getattr(profile,'first_name','') or ''} {getattr(profile,'last_name','') or ''}".strip()
                            selected_user = full or (user.email.split('@')[0] if getattr(user,'email','') else str(user.id))
                        except Exception:
                            selected_user = user.email.split('@')[0] if getattr(user,'email','') else str(user.id)
                        
                        # Add info object for clickable slots
                        # Include start/end datetimes for display in modals
                        from django.utils import timezone as _tz
                        _rs = _tz.localtime(selected_req.rental_request.requested_start_date)
                        _re = _tz.localtime(selected_req.rental_request.requested_end_date)

                        info = {
                            'user_name': selected_user,
                            'status': selected_req.rental_request.status,
                            'rental_request_id': selected_req.rental_request_id,
                            'project': selected_req.rental_request.project_name or '',
                            'user_email': user.email if hasattr(user, 'email') and user.email else '',
                            'start': _rs.strftime('%d.%m.%Y %H:%M'),
                            'end': _re.strftime('%d.%m.%Y %H:%M'),
                        }
                    day_statuses.append({
                        'date': d.isoformat(),
                        'status': status,
                        'user_name': selected_user if selected_req else None,
                        'info': info
                    })

                result.append({
                    'id': it['id'],
                    'inventory_number': it['inventory_number'],
                    'description': it.get('description') or it['inventory_number'],
                    'week': day_statuses,
                })
        else:
            for it in items_list:
                hour_slots = []
                conflicts = item_id_to_rentals.get(it['id'], [])
                for slot_start, slot_end in _iter_time_slots(day, 60):
                    status = 'available'
                    info = None
                    for ri in conflicts:
                        rs = timezone.localtime(ri.rental_request.requested_start_date)
                        re = timezone.localtime(ri.rental_request.requested_end_date)
                        if slot_start < re and slot_end > rs:
                            status = ri.rental_request.status  # reserved or issued
                            user = ri.rental_request.user
                            try:
                                profile = user.profile
                                full = f"{getattr(profile,'first_name','') or ''} {getattr(profile,'last_name','') or ''}".strip()
                                user_name = full or (user.email.split('@')[0] if getattr(user,'email','') else str(user.id))
                            except Exception:
                                user_name = user.email.split('@')[0] if getattr(user,'email','') else str(user.id)
                            info = {
                                'user_name': user_name,
                                'status': ri.rental_request.status,
                                'start': rs.strftime('%d.%m.%Y %H:%M'),
                                'end': re.strftime('%d.%m.%Y %H:%M'),
                                'id': ri.rental_request_id,
                                'rental_request_id': ri.rental_request_id,
                                'project': ri.rental_request.project_name or '',
                                'user_email': user.email if hasattr(user, 'email') and user.email else '',
                                'start_time': rs.strftime('%H:%M'),
                                'end_time': re.strftime('%H:%M'),
                            }
                            break
                    hour_slots.append({'time': slot_start.strftime('%H:%M'), 'status': status, 'info': info})

                result.append({
                    'id': it['id'],
                    'inventory_number': it['inventory_number'],
                    'description': it.get('description') or it['inventory_number'],
                    'day': day.isoformat(),
                    'hours': hour_slots,
                })

        return JsonResponse({'success': True, 'mode': mode, 'date': day.isoformat(), 'items': result})
    except Exception:
        logger.exception('Error in api_inventory_calendar')
        return JsonResponse({'success': False, 'error': _('Internal server error')}, status=500)


@login_required
@staff_member_required
def api_get_all_equipment_sets(request):
    """
    Get all equipment sets for admin management.

    Returns all equipment sets with their items and metadata
    for administrative management purposes.

    Args:
        request: HTTP request object

    Returns:
        JsonResponse: List of all equipment sets with details
    """
    try:
        from .models import EquipmentSet

        sets = EquipmentSet.objects.prefetch_related('items__inventory_item').order_by('-created_at')

        result = []
        for equipment_set in sets:
            result.append({
                'id': equipment_set.id,
                'name': equipment_set.name,
                'description': equipment_set.description or '',
                'is_active': equipment_set.is_active,
                'items_count': equipment_set.items.count(),
                'created_at': equipment_set.created_at.strftime('%d.%m.%Y %H:%M'),
                'created_by': f"{equipment_set.created_by.profile.first_name} {equipment_set.created_by.profile.last_name}" if equipment_set.created_by and hasattr(equipment_set.created_by, 'profile') and equipment_set.created_by.profile else (equipment_set.created_by.email if equipment_set.created_by else 'N/A'),
                'items': [
                    {
                        'id': item.id,
                        'inventory_item': {
                            'id': item.inventory_item.id,
                            'inventory_number': item.inventory_item.inventory_number,
                            'description': item.inventory_item.description or item.inventory_item.inventory_number,
                        },
                        'quantity': item.quantity,
                    }
                    for item in equipment_set.items.all()
                ]
            })

        return JsonResponse({
            'sets': result or [],
            'total_count': len(result) if result else 0
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_create_equipment_set(request):
    """
    Create a new equipment set.

    Creates a new equipment set with specified items and quantities,
    allowing staff to define reusable equipment combinations.

    Args:
        request: HTTP request object with equipment set data

    Returns:
        JsonResponse: Success status and created set information
    """
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)

        from .models import EquipmentSet
        from .models import EquipmentSetItem

        # Create the set
        equipment_set = EquipmentSet.objects.create(
            name=data['name'],
            description=data.get('description', ''),
            is_active=data.get('is_active', True),
            created_by=request.user
        )

        # Add items to the set
        for item_data in data.get('items', []):
            inventory_item = InventoryItem.objects.get(id=item_data['inventory_item_id'])
            EquipmentSetItem.objects.create(
                equipment_set=equipment_set,
                inventory_item=inventory_item,
                quantity=item_data['quantity']
            )

        return JsonResponse({
            'success': True,
            'message': _('Equipment Set "{name}" was successfully created.').format(name=equipment_set.name),
            'set_id': equipment_set.id
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_delete_equipment_set(request, pk):
    """
    Delete an equipment set.

    Removes an equipment set and all its associated items
    from the system.

    Args:
        request: HTTP request object
        pk: Primary key of the equipment set to delete

    Returns:
        JsonResponse: Success status and confirmation message
    """
    if request.method != 'DELETE':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        from .models import EquipmentSet

        equipment_set = get_object_or_404(EquipmentSet, pk=pk)
        set_name = equipment_set.name
        equipment_set.delete()

        return JsonResponse({
            'success': True,
            'message': _('Equipment Set "{name}" was successfully deleted.').format(name=set_name)
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_search_inventory_items(request):
    """
    Search inventory items for set creation.

    Searches for available inventory items that can be added
    to equipment sets with filtering and search capabilities.

    Args:
        request: HTTP request object with search query

    Returns:
        JsonResponse: List of matching inventory items
    """
    try:
        query = request.GET.get('q', '').strip()
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        from .services import RentalService
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime
        from inventory.models import InventoryItem

        # Start with all items available for rent (don't filter by status for search)
        # This allows searching for all items, even if currently unavailable
        items = InventoryItem.objects.filter(
            available_for_rent=True
        ).select_related('category', 'location', 'owner', 'manufacturer')

        if query:
            # First, filter by database fields
            items = items.filter(
                Q(inventory_number__icontains=query) |
                Q(description__icontains=query) |
                Q(category__name__icontains=query) |
                Q(manufacturer__name__icontains=query) |
                Q(location__name__icontains=query) |
                Q(owner__name__icontains=query)
            )

        items = list(items[:150])  # Get more items to filter by full_path in Python
        
        # Additional filtering by full_path (computed property) in Python
        if query:
            query_lower = query.lower()
            filtered_items = []
            for item in items:
                # Check if already matched by database query
                matched = (
                    query_lower in (item.inventory_number or '').lower() or
                    query_lower in (item.description or '').lower() or
                    (item.category and query_lower in item.category.name.lower()) or
                    (item.manufacturer and query_lower in item.manufacturer.name.lower()) or
                    (item.location and query_lower in item.location.name.lower()) or
                    (item.owner and query_lower in item.owner.name.lower())
                )
                
                # Also check full_path (computed property)
                if not matched and item.location:
                    full_path_lower = item.location.full_path.lower()
                    if query_lower in full_path_lower:
                        matched = True
                
                if matched:
                    filtered_items.append(item)
            
            items = filtered_items[:100]  # Limit final results
        else:
            items = items[:100]

        result = []
        for item in items:
            # Check availability if dates are provided
            available_quantity = item.quantity or 0
            if start_date and end_date:
                try:
                    start_datetime = parse_datetime(start_date)
                    end_datetime = parse_datetime(end_date)

                    if start_datetime and end_datetime:
                        if timezone.is_naive(start_datetime):
                            start_datetime = timezone.make_aware(start_datetime)
                        if timezone.is_naive(end_datetime):
                            end_datetime = timezone.make_aware(end_datetime)

                        # Use RentalService method which takes item_id
                        available_quantity = RentalService.get_available_quantity_for_period(
                            item.id, start_datetime, end_datetime
                        )
                except Exception as e:
                    # If date parsing fails, use original quantity
                    pass

            # Include all items in search results (not just available ones)
            # This allows staff to see all items and their availability status
            manufacturer_name = item.manufacturer.name if item.manufacturer else ''
            
            result.append({
                'id': item.id,
                'inventory_number': item.inventory_number or '',
                'description': item.description or item.inventory_number or '',
                'category': item.category.name if item.category else 'Other',
                'location': item.location.full_path if item.location else 'N/A',
                'owner': item.owner.name if item.owner else 'N/A',
                'manufacturer': manufacturer_name,
                'available_quantity': available_quantity,
                'total_quantity': item.quantity or 0,
                'status': item.status or 'unknown'
            })

        return JsonResponse({
            'items': result or [],
            'total_count': len(result) if result else 0
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_barcode_lookup(request):
    num = request.GET.get('num', '').strip()
    if not num:
        return JsonResponse({'error': _('Missing required parameter: num')}, status=400)

    from inventory.models import InventoryItem

    item = InventoryItem.objects.filter(
        inventory_number__exact=num,
        available_for_rent=True,
    ).first()

    if not item:
        return JsonResponse({'error': _('Item not found')}, status=404)

    return JsonResponse({
        'id': item.id,
        'inventory_number': item.inventory_number or '',
        'description': item.description or '',
        'quantity': item.quantity or 0,
        'status': item.status or 'unknown',
    })


@login_required
@staff_member_required
def api_scan_return_item(request):
    """
    Scan a barcode to increment the return count for a rental item.

    POST /rental/api/scan-return/
    Body: {"rental_id": int, "inventory_number": str}
    Returns updated rental item details with completion status.
    """
    logger = logging.getLogger(__name__)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': _('Invalid JSON body')}, status=400)

    rental_id = data.get('rental_id')
    inventory_number = data.get('inventory_number')

    if not rental_id or not inventory_number:
        return JsonResponse(
            {'error': _('Missing required fields: rental_id and inventory_number')},
            status=400,
        )

    # Clients must send the numeric primary key, not the display code
    # (``R-2608-0284``); comparing that to an integer column raises ValueError.
    try:
        rental_id = int(rental_id)
    except (TypeError, ValueError):
        return JsonResponse(
            {'error': _('Invalid rental_id: a numeric rental id is required.')},
            status=400,
        )

    rental = RentalRequest.objects.filter(
        id=rental_id,
        status='issued',
    ).first()

    if not rental:
        return JsonResponse(
            {'error': _('Rental not found or not in issued status')},
            status=400,
        )

    rental_item = RentalItem.objects.filter(
        rental_request=rental,
        inventory_item__inventory_number=inventory_number,
    ).select_related('inventory_item').first()

    if not rental_item:
        return JsonResponse(
            {'error': _('Item not found in this rental')},
            status=404,
        )

    if rental_item.quantity_returned >= rental_item.quantity_issued:
        return JsonResponse(
            {'error': _('All issued quantities have already been returned')},
            status=400,
        )

    rental_item.quantity_returned += 1
    rental_item.save()

    return JsonResponse({
        'rental_item_id': rental_item.id,
        'inventory_number': rental_item.inventory_item.inventory_number,
        'description': rental_item.inventory_item.description or rental_item.inventory_item.inventory_number,
        'quantity_issued': rental_item.quantity_issued,
        'quantity_returned': rental_item.quantity_returned,
        'complete': rental_item.quantity_returned >= rental_item.quantity_issued,
    })


class PrintFormView(StaffRequiredMixin, TemplateView):
    """
    Unified print form view for any organization.

    Accepts rental_id and organization_id from URL kwargs.
    org_id=0 means all non-MSA items combined.
    Template selection: MSA → print_form_msa.html, all others → print_form_okmq.html.
    """

    MSA_TEMPLATE = 'rental/print_form_msa.html'
    DEFAULT_TEMPLATE = 'rental/print_form_okmq.html'

    def get_template_names(self):
        """Select template based on organization. org_id=0 defaults to non-MSA template."""
        org_id = self.kwargs.get('org_id')
        if org_id == 0:
            return [self.DEFAULT_TEMPLATE]
        try:
            organization = Organization.objects.only('name').get(pk=org_id)
            if organization.name == 'MSA':
                return [self.MSA_TEMPLATE]
        except Organization.DoesNotExist:
            pass
        return [self.DEFAULT_TEMPLATE]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rental_id = kwargs.get('rental_id')
        org_id = self.kwargs.get('org_id')

        try:
            rental_request = get_object_or_404(RentalRequest, id=rental_id)

            if org_id == 0:
                items = rental_request.items.exclude(
                    inventory_item__owner__name='MSA',
                ).select_related(
                    'inventory_item',
                    'inventory_item__owner',
                    'inventory_item__location',
                ).prefetch_related('issues')
            else:
                organization = get_object_or_404(Organization, pk=org_id)
                items = rental_request.items.filter(
                    inventory_item__owner_id=org_id,
                ).select_related(
                    'inventory_item',
                    'inventory_item__owner',
                    'inventory_item__location',
                ).prefetch_related('issues')

            context['msa_items'] = items
            context['okmq_items'] = items
            context['items'] = items
            context['rental_request'] = rental_request
            context['has_signature'] = rental_request.has_any_signature()
            context['signature_image'] = rental_request.signature
            context['signature_signed_at'] = rental_request.signature_signed_at
            context['signature_method'] = rental_request.signature_method

        except Exception as e:
            context['error'] = _('Error loading rental: {error}').format(error=str(e))

        return context


class PrintPickListView(StaffRequiredMixin, TemplateView):
    template_name = 'rental/print_pick_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rental_id = kwargs.get('rental_id')

        try:
            rental_request = get_object_or_404(RentalRequest, id=rental_id)
            rental_items = list(rental_request.items.select_related(
                'inventory_item',
                'inventory_item__location',
            ).prefetch_related('issues'))
            rental_items.sort(
                key=lambda item: (
                    item.inventory_item.location.full_path,
                    item.inventory_item.inventory_number,
                )
            )
            grouped_items = []
            current_location = None
            current_items = []

            for rental_item in rental_items:
                location_name = rental_item.inventory_item.location.full_path
                if location_name != current_location:
                    if current_items:
                        grouped_items.append({
                            'location': current_location,
                            'items': current_items,
                        })
                    current_location = location_name
                    current_items = []
                current_items.append(rental_item)

            if current_items:
                grouped_items.append({
                    'location': current_location,
                    'items': current_items,
                })

            context.update({
                'rental_request': rental_request,
                'rental_items': rental_items,
                'grouped_rental_items': grouped_items,
                'has_signature': rental_request.has_any_signature(),
                'signature_image': rental_request.signature,
                'signature_signed_at': rental_request.signature_signed_at,
                'signature_method': rental_request.signature_method,
            })
        except Exception as e:
            context['error'] = _('Error loading rental: {error}').format(error=str(e))

        return context


@login_required
def serve_room_image(request, image_id):
    """Stream a room photo through Django instead of a static ``/media/`` URL.

    In the split deployment nginx runs on a separate VM and cannot see the
    application's ``MEDIA_ROOT``, so ``/media/room_photos/...`` 404s there. This
    view is proxied to the app VM and reads the file locally, exactly like the
    inventory item photos (see ``inventory.views.serve_item_image``). Staff see
    every photo; other signed-in users only photos of active rooms, which the
    user rental dashboard offers them.
    """
    room_images = RoomImage.objects.all()
    if not request.user.is_staff:
        room_images = room_images.filter(room__is_active=True)
    room_image = get_object_or_404(room_images, pk=image_id)

    # Calendars and admin previews ask for a small cached thumbnail so the page
    # does not download full-resolution room photos for a 34px tile.
    if request.GET.get('size') == 'thumb':
        thumb = _ensure_room_thumbnail(room_image)
        if thumb is not None:
            return FileResponse(open(thumb, 'rb'), content_type='image/jpeg')

    try:
        fh = room_image.image.open('rb')
    except (FileNotFoundError, ValueError):
        raise Http404('Room image file not found.')

    content_type, _enc = mimetypes.guess_type(room_image.image.name)
    return FileResponse(fh, content_type=content_type or 'application/octet-stream')


class BarcodePrintView(StaffRequiredMixin, TemplateView):
    """
    Print barcode labels for selected inventory items.

    GET /rental/barcode/print/?ids=1,2,3&format=roll_51x25&rotate=90
    Renders a page with barcode SVGs for the given inventory item IDs.
    Returns 400 if the ids parameter is missing or empty.
    Supported formats are the two A4 sheet layouts plus every active
    ``LabelFormat`` row, addressed by its slug; an unknown value falls back
    to the A4 sheet layout.
    ``rotate=90`` turns the roll layout sideways for label printers whose
    media is defined portrait (25 x 51 instead of 51 x 25); without it the
    driver rotates the page itself and one label spills over two.
    """

    def get_label_format(self):
        """Return the requested label format definition, or the default one."""
        return label_formats.resolve_or_default(self.request.GET.get('format'))

    def get_template_names(self):
        return [self.get_label_format()['template']]

    def get_rotation(self):
        """Return 90 when the roll layout should be printed sideways, else 0."""
        return 90 if self.request.GET.get('rotate') == '90' else 0

    def dispatch(self, request, *args, **kwargs):
        ids_param = request.GET.get('ids', '')
        if not ids_param.strip():
            return HttpResponseBadRequest(_('Missing required parameter: ids'))
        try:
            [int(i.strip()) for i in ids_param.split(',') if i.strip()]
        except ValueError:
            return HttpResponseBadRequest(_('Invalid item id format'))
        response = super().dispatch(request, *args, **kwargs)
        response['X-Frame-Options'] = 'SAMEORIGIN'
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ids_param = self.request.GET.get('ids', '')
        item_ids = [int(i.strip()) for i in ids_param.split(',') if i.strip()]

        items = InventoryItem.objects.filter(
            id__in=item_ids,
        ).select_related('category', 'location', 'location__parent', 'owner')

        label_format = self.get_label_format()
        lines = label_layout.lines_for(label_format)
        # A roll label has one line per row and no room to spare, so a long
        # location is shortened to fit just as the label printer shortens it.
        # An A4 sheet label is roomier and lets a location wrap instead.
        fits = None
        if label_format.get('width'):
            fits = label_formats.html_row_fits(
                label_format['width'], label_format['typography'])
        items_data = []
        for item in items:
            try:
                barcode_svg = BarcodeService.generate_svg(
                    item.inventory_number, **label_format['writer'])
            except (ValueError, Exception):
                barcode_svg = ''
            fields = {
                'inventory_number': item.inventory_number,
                'description': item.description,
                'location': str(item.location) if item.location else '',
                'owner': item.owner.name if item.owner else '',
            }
            items_data.append({
                'id': item.id,
                'barcode_svg': barcode_svg,
                # The rows the label prints, shared with the TSPL renderer
                # so a format looks the same on paper and on the roll.
                'rows': label_layout.build_rows(fields, lines, fits=fits),
                **fields,
            })

        context['items'] = items_data
        context['label_width'] = label_format.get('width')
        context['label_height'] = label_format.get('height')
        context['rotate'] = self.get_rotation()
        context.update(label_format.get('typography') or {})
        return context


@login_required
@staff_member_required
@require_POST
def api_print_labels(request):
    """
    Send labels for the given inventory items straight to the label printer.

    POST /rental/barcode/print-direct/ with ``{"ids": [1, 2], "format": "roll_51x25"}``

    The printer is the one configured in the rental configuration, never one
    named by the request, and the job carries the label geometry itself, so
    no workstation needs a media size set up for it. Only the roll formats
    have a physical size and can be printed this way.
    """
    try:
        payload = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'error': _('Invalid request body')}, status=400)

    item_ids = payload.get('ids') or []
    if not isinstance(item_ids, list) or not item_ids:
        return JsonResponse(
            {'error': _('Missing required parameter: ids')}, status=400)
    try:
        item_ids = [int(item_id) for item_id in item_ids]
    except (TypeError, ValueError):
        return JsonResponse({'error': _('Invalid item id format')}, status=400)

    label_format = label_formats.resolve(payload.get('format'))
    if not label_format or not label_format.get('width'):
        return JsonResponse(
            {'error': _('This label format cannot be sent to the label '
                        'printer. Choose a roll format.')}, status=400)

    config = RentalConfig.get_config()
    if not config.label_printer_configured:
        return JsonResponse(
            {'error': _('No label printer is configured. Set its address in '
                        'the rental configuration.')}, status=409)

    items = InventoryItem.objects.filter(
        id__in=item_ids).select_related('location', 'location__parent', 'owner')
    labels = [
        {
            'inventory_number': item.inventory_number,
            'description': item.description,
            'location': str(item.location) if item.location else '',
            'owner': item.owner.name if item.owner else '',
        }
        for item in items
    ]
    if not labels:
        return JsonResponse({'error': _('No items found')}, status=404)

    try:
        printed = LabelPrinterService.print_items(
            labels,
            label_format['width'],
            label_format['height'],
            replace(
                PrinterSettings.from_config(config),
                gap_mm=label_formats.gap_for(label_format, config),
            ),
            label_layout.lines_for(label_format),
        )
    except LabelPrinterError as error:
        logger.warning('Label printing failed: %s', error)
        return JsonResponse(
            {'error': _('The label printer could not be reached: %(reason)s')
                % {'reason': str(error)}},
            status=502,
        )

    return JsonResponse({'printed': printed})


@login_required
@staff_member_required
def api_update_pick_list(request, rental_id):
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        rental_request = get_object_or_404(RentalRequest, id=rental_id)
        data = json.loads(request.body)
        items = data.get('items', [])

        rental_item_map = {
            item.id: item
            for item in rental_request.items.all()
        }

        updated_count = 0
        for item_data in items:
            item_id = item_data.get('id')
            rental_item = rental_item_map.get(item_id)
            if not rental_item:
                continue

            rental_item.pick_list_checked = bool(item_data.get('checked', False))
            rental_item.pick_list_note = str(item_data.get('note', '') or '').strip()
            rental_item.save(update_fields=['pick_list_checked', 'pick_list_note'])
            updated_count += 1

        return JsonResponse({'success': True, 'updated_count': updated_count})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@staff_member_required
def api_get_rental_print_info(request, rental_id):
    """
    Get rental print information.

    Returns information needed for printing rental forms,
    including item counts by owner organization.

    Args:
        request: HTTP request object
        rental_id: ID of the rental to get print info for

    Returns:
        JsonResponse: Rental print information and item counts
    """
    try:
        rental_request = get_object_or_404(RentalRequest, id=rental_id)

        # Count items by owner
        msa_count = rental_request.items.filter(inventory_item__owner__name='MSA').count()
        okmq_count = rental_request.items.filter(inventory_item__owner__name='OKMQ').count()

        try:
            user_name = f"{rental_request.user.profile.first_name} {rental_request.user.profile.last_name}" if hasattr(rental_request.user, 'profile') and rental_request.user.profile else rental_request.user.email
        except:
            user_name = rental_request.user.email

        return JsonResponse({
            'success': True,
            'rental_id': rental_request.id,
            'project_name': rental_request.project_name,
            'user_name': user_name,
            'msa_items_count': msa_count,
            'okmq_items_count': okmq_count,
            'has_msa_items': msa_count > 0,
            'has_okmq_items': okmq_count > 0,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_expire_room_rentals(request):
    """
    Manually trigger expiration of room rentals.

    Executes the management command to expire overdue room rentals
    and returns statistics about the operation.

    Args:
        request: HTTP request object

    Returns:
        JsonResponse: Operation results and statistics
    """
    if request.method != 'POST':
        return JsonResponse({'error': _('Only POST method allowed')}, status=405)

    try:
        from django.core.management import call_command
        from io import StringIO
        import json

        # Capture command output
        out = StringIO()

        # Run the command
        call_command('expire_room_rentals', stdout=out, verbosity=2)

        # Get the output
        output = out.getvalue()
        out.close()

        # Parse output to extract statistics
        lines = output.split('\n')
        expired_count = 0
        reserved_expired = 0
        issued_expired = 0

        for line in lines:
            if 'Found' in line and 'expired room rentals' in line:
                try:
                    expired_count = int(line.split()[1])
                except:
                    pass
            elif 'expired room reservations' in line:
                try:
                    reserved_expired = int(line.split()[0])
                except:
                    pass
            elif 'expired room issues' in line:
                try:
                    issued_expired = int(line.split()[0])
                except:
                    pass

        return JsonResponse({
            'success': True,
            'message': _('Automatic expiration of room rentals completed'),
            'output': output,
            'statistics': {
                'total_expired': expired_count,
                'reserved_expired': reserved_expired,
                'issued_expired': issued_expired
            }
        })

    except Exception as e:
        return JsonResponse({
            'error': _('Error executing command: {error}').format(error=str(e) if e else 'Unknown error')
        }, status=500)


@login_required
@staff_member_required
def api_get_room_schedule(request):
    """
    Get room schedule with detailed occupancy information.

    Returns comprehensive room scheduling information including
    time slots, availability status, and conflict details.

    Args:
        request: HTTP request object with date parameters

    Returns:
        JsonResponse: Room schedule with availability information
    """
    try:
        from .models import Room
        from .models import RoomRental
        from datetime import datetime
        from datetime import timedelta
        from django.utils import timezone
        from django.utils.dateparse import parse_date

        # Get parameters
        room_id = request.GET.get('room_id')
        start_date_str = request.GET.get('start_date', '')
        end_date_str = request.GET.get('end_date', '')

        # Parse dates
        start_date = None
        end_date = None

        if start_date_str:
            start_date = parse_date(start_date_str)
        if end_date_str:
            end_date = parse_date(end_date_str)

        # If dates are not specified, use current week
        if not start_date:
            start_date = timezone.now().date()
        if not end_date:
            end_date = start_date + timedelta(days=6)

        # Get rooms
        if room_id:
            rooms = Room.objects.filter(id=room_id, is_active=True)
        else:
            rooms = Room.objects.filter(is_active=True)
        rooms = rooms.prefetch_related('images')

        result = []
        for room in rooms:
            # Get all room rentals in the specified period
            # Use __date for date-only comparison, avoiding timezone issues
            room_rentals = RoomRental.objects.filter(
                room=room,
                rental_request__status__in=['reserved', 'issued'],
                rental_request__requested_start_date__date__lte=end_date,
                rental_request__requested_end_date__date__gte=start_date
            ).select_related('rental_request__user')

            # Build schedule by days
            schedule = []
            current_date = start_date
            while current_date <= end_date:
                # German day names mapping
                german_days = {
                    0: 'MO',  # Monday
                    1: 'DI',  # Tuesday
                    2: 'MI',  # Wednesday
                    3: 'DO',  # Thursday
                    4: 'FR',  # Friday
                    5: 'SA',  # Saturday
                    6: 'SO'   # Sunday
                }

                day_schedule = {
                    'date': current_date.isoformat(),
                    'day_name': current_date.strftime('%A'),  # Monday, Tuesday, etc.
                    'day_short': german_days[current_date.weekday()],  # German abbreviations
                    'day_number': current_date.day,
                    'is_today': current_date == timezone.now().date(),
                    'is_weekend': current_date.weekday() >= 5,  # Saturday and Sunday
                    'slots': []
                }

                for slot_start_aware, slot_end_aware in _iter_time_slots(current_date, 30):
                    slot_start = timezone.localtime(slot_start_aware)
                    slot_end = timezone.localtime(slot_end_aware)

                    slot_status = (
                        'past'
                        if slot_start_aware < timezone.now()
                        else 'available'
                    )
                    slot_info = None

                    for rental in room_rentals:
                        rental_start = rental.get_start_date()
                        rental_end = rental.get_end_date()

                        if rental_start and rental_end:
                            rental_start_local = timezone.localtime(rental_start)
                            rental_end_local = timezone.localtime(rental_end)
                            rental_start_time = datetime.combine(current_date, rental_start_local.time())
                            rental_end_time = datetime.combine(current_date, rental_end_local.time())

                            rental_covers_day = rental_start_local.date() <= current_date <= rental_end_local.date()
                            if not rental_covers_day:
                                continue

                            if slot_start.replace(tzinfo=None) < rental_end_time and slot_end.replace(tzinfo=None) > rental_start_time:
                                slot_status = 'occupied'
                                user = rental.rental_request.user
                                user_name = _("Unknown user")

                                try:
                                    if hasattr(user, 'profile') and user.profile:
                                        profile = user.profile
                                        if hasattr(profile, 'first_name') and profile.first_name and hasattr(profile, 'last_name') and profile.last_name:
                                            user_name = f"{profile.first_name} {profile.last_name}"
                                        elif hasattr(profile, 'first_name') and profile.first_name:
                                            user_name = profile.first_name
                                        elif hasattr(profile, 'last_name') and profile.last_name:
                                            user_name = profile.last_name
                                    elif hasattr(user, 'first_name') and user.first_name and hasattr(user, 'last_name') and user.last_name:
                                        user_name = f"{user.first_name} {user.last_name}"
                                    elif hasattr(user, 'username') and user.username:
                                        user_name = user.username
                                    elif hasattr(user, 'email') and user.email:
                                        user_name = user.email.split('@')[0]
                                    else:
                                        user_name = _("User #{user_id}").format(user_id=user.id)
                                except Exception:
                                    if hasattr(user, 'email') and user.email:
                                        user_name = user.email.split('@')[0]
                                    else:
                                        user_name = _("User #{user_id}").format(user_id=user.id)

                                slot_info = {
                                    'user_name': user_name,
                                    'project': rental.rental_request.project_name or _("No project"),
                                    'status': rental.rental_request.status,
                                    'people_count': rental.people_count or 1,
                                    'start_time': rental_start_local.strftime('%H:%M'),
                                    'end_time': rental_end_local.strftime('%H:%M'),
                                    'rental_request_id': rental.rental_request.id,
                                    'detail_url': reverse(
                                        'rental:rental_detail',
                                        args=[rental.rental_request.id],
                                    ),
                                    'user_email': user.email if hasattr(user, 'email') and user.email else ''
                                }
                                break

                    day_schedule['slots'].append({
                        'time': slot_start.strftime('%H:%M'),
                        'status': slot_status,
                        'info': slot_info
                    })

                schedule.append(day_schedule)
                current_date += timedelta(days=1)

            result.append({
                'id': room.id,
                'name': room.name,
                'description': room.description,
                'capacity': room.capacity,
                'location': room.location,
                'image_url': _room_thumb_url(room),
                'image_full_url': _room_full_url(room),
                'image_urls': _room_photo_urls(room),
                'schedule': schedule
            })

        return JsonResponse({
            'success': True,
            'rooms': result,
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            }
        })

    except Exception as e:
        import traceback
        print(f"Error in api_get_room_schedule: {e}")
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_get_inventory_schedule(request):
    """Return schedule for a specific inventory item for a date range."""
    print(f"🔍 api_get_inventory_schedule called with params: {request.GET}")
    try:
        from .models import RentalItem
        from datetime import datetime
        from datetime import timedelta
        from django.utils import timezone
        from django.utils.dateparse import parse_date

        inv = request.GET.get('inv')
        print(f"🔍 Looking for inventory item: {inv}")
        if not inv:
            return JsonResponse({'error': 'inv is required'}, status=400)

        # Get inventory item through the service
        item = inventory_service.get_item_by_inventory_number(inv)
        print(f"🔍 Found item: {item}")
        if not item:
            return JsonResponse({'error': 'Item not found'}, status=404)

        start_date = parse_date(request.GET.get('start_date') or '')
        end_date = parse_date(request.GET.get('end_date') or '')
        if not start_date:
            start_date = timezone.now().date()
        if not end_date:
            end_date = start_date + timedelta(days=6)

        print(f"🔍 Querying rental items for date range: {start_date} to {end_date}")
        # PERFORMANCE OPTIMIZATION: Add select_related for all FK accessed in loop
        rental_items = RentalItem.objects.filter(
            inventory_item_id=item['id'],
            rental_request__status__in=['reserved', 'issued'],
            rental_request__requested_start_date__date__lte=end_date,
            rental_request__requested_end_date__date__gte=start_date,
        ).select_related(
            'rental_request', 
            'rental_request__user', 
            'inventory_item'
        )

        print(f"🔍 Found {rental_items.count()} rental items")
        if rental_items.count() > 0:
            for ri in rental_items:
                print(f"🔍 Rental item {ri.id}: {ri.rental_request.requested_start_date} to {ri.rental_request.requested_end_date}, status: {ri.rental_request.status}")
        else:
            print("🔍 No rental items found!")

        print(f"🔍 Building schedule for {len(range((end_date - start_date).days + 1))} days")
        schedule = []
        current = start_date
        day_count = 0

        while current <= end_date:
            day_count += 1
            print(f"🔍 Processing day {day_count}: {current}")

            day = {
                'date': current.isoformat(),
                'day_name': current.strftime('%A'),
                'day_short': current.strftime('%a'),
                'day_number': current.day,
                'is_today': current == timezone.now().date(),
                'is_weekend': current.weekday() >= 5,
                'slots': []
            }

            slot_count = 0
            for slot_start, slot_end in _iter_time_slots(current, 60):
                slot_count += 1
                if slot_count % 6 == 0:
                    print(f"🔍 Processing slot {slot_count} for day {current}")

                status = 'available'
                info = None

                for ri in rental_items:
                    rs = timezone.localtime(ri.rental_request.requested_start_date)
                    re = timezone.localtime(ri.rental_request.requested_end_date)

                    # Debug: print rental item details for first slot of each day
                    if slot_count == 1:  # Only for first slot to avoid spam
                        print(f"🔍 Checking rental item: {ri.id}, start: {rs}, end: {re}, current date: {current}")

                    # Check if current day is within rental period
                    # Fix: Convert current to timezone-aware datetime for comparison
                    current_start_of_day = timezone.make_aware(datetime.combine(current, datetime.min.time().replace(hour=0, minute=0)))
                    current_end_of_day = timezone.make_aware(datetime.combine(current, datetime.min.time().replace(hour=23, minute=59)))

                    if rs <= current_end_of_day and re >= current_start_of_day:
                        working_start, working_end = get_day_working_window(current)
                        if not working_start or not working_end:
                            continue

                        # For the current day, adjust rental times to working hours
                        if current == rs.date():
                            # First day of rental
                            if rs >= working_end:
                                continue
                            elif rs <= working_start:
                                rental_start = working_start
                            else:
                                rental_start = rs
                        else:
                            rental_start = working_start

                        if current == re.date():
                            if re <= working_start:
                                continue
                            elif re >= working_end:
                                rental_end = working_end
                            else:
                                rental_end = re
                        else:
                            rental_end = working_end

                        print(f"🔍 Checking slot {slot_start.strftime('%H:%M')} ({slot_start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')}) vs rental ({rental_start.strftime('%H:%M')}-{rental_end.strftime('%H:%M')})")
                        
                        if slot_start < rental_end and slot_end > rental_start:
                            status = 'occupied'
                            user = ri.rental_request.user

                            # Get full name from Profile model (First Name + Last Name) instead of email
                            try:
                                profile = user.profile
                                if profile and profile.first_name and profile.last_name:
                                    user_name = f"{profile.first_name} {profile.last_name}"
                                elif profile and profile.first_name:
                                    user_name = profile.first_name
                                elif profile and profile.last_name:
                                    user_name = profile.last_name
                                else:
                                    user_name = user.email.split('@')[0] if getattr(user, 'email', '') else str(user.id)
                            except:
                                # Fallback to email if profile doesn't exist
                                user_name = user.email.split('@')[0] if getattr(user, 'email', '') else str(user.id)

                            info = {
                                'user_name': user_name,
                                'project': ri.rental_request.project_name or '',
                                'status': ri.rental_request.status,
                                'start_time': rs.strftime('%H:%M'),
                                'end_time': re.strftime('%H:%M')
                            }

                            print(f"🔍 Slot {slot_start.strftime('%H:%M')} occupied! Status: {status}, User: {user_name}")

                            break
                        else:
                            if slot_count == 1:  # Only for first slot to avoid spam
                                print(f"🔍 No overlap: Slot {slot_start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')} vs Rental {rental_start.strftime('%H:%M')}-{rental_end.strftime('%H:%M')}")

                day['slots'].append({'time': slot_start.strftime('%H:%M'), 'status': status, 'info': info})

            schedule.append(day)
            current += timedelta(days=1)
        print(f"🔍 Schedule built successfully with {len(schedule)} days")

        return JsonResponse({
            'success': True,
            'item': {
                'inventory_number': item['inventory_number'],
                'description': item.get('description'),
            },
            'schedule': schedule,
            'period': {'start_date': start_date.isoformat(), 'end_date': end_date.isoformat()}
        })
    except Exception as e:
        import traceback
        print('Error in api_get_inventory_schedule:', e)
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)


# User-accessible API endpoints (without staff_member_required)

@login_required
def api_get_filter_options_user(request):
    """
    Get filter options for inventory (user version).
    This version is accessible to regular users.
    """
    # Get organizations (owners)
    organizations = inventory_service.get_item_organizations()

    # Get locations with hierarchical structure
    locations = inventory_service.get_item_locations()

    # Get categories
    categories = inventory_service.get_item_categories()

    return JsonResponse({
        'owners': organizations,
        'locations': locations,
        'categories': categories,
    })


@login_required
def api_get_user_inventory_simple(request, user_id):
    """
    Get available inventory for a specific user (simplified version).
    This version is accessible to regular users but only for their own inventory.
    """
    # Security check: users can only access their own inventory
    if request.user.id != user_id and not request.user.is_staff:
        return JsonResponse({'error': 'Access denied'}, status=403)

    user = get_object_or_404(OKUser, id=user_id)
    profile = getattr(user, 'profile', None)
    if not profile:
        return JsonResponse({'error': _('User profile not found')}, status=400)

    # Get filter parameters
    owner_filter = request.GET.get('owner', '')
    location_filter = request.GET.get('location', '')
    category_filter = request.GET.get('category', '')
    search_query = request.GET.get('search', '')

    # Get date parameters for availability calculation
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    # Parse dates
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    start_date = None
    end_date = None

    if start_date_str:
        try:
            start_date = parse_datetime(start_date_str)
            if start_date:
                # Make sure date is timezone-aware
                if timezone.is_naive(start_date):
                    start_date = timezone.make_aware(start_date)
            else:
                # Try parsing as date only
                from django.utils.dateparse import parse_date
                date_only = parse_date(start_date_str)
                if date_only:
                    start_date = timezone.make_aware(timezone.datetime.combine(date_only, timezone.datetime.min.time()))
        except:
            pass

    if end_date_str:
        try:
            end_date = parse_datetime(end_date_str)
            if end_date:
                # Make sure date is timezone-aware
                if timezone.is_naive(end_date):
                    end_date = timezone.make_aware(end_date)
            else:
                # Try parsing as date only
                from django.utils.dateparse import parse_date
                date_only = parse_date(end_date_str)
                if date_only:
                    end_date = timezone.make_aware(timezone.datetime.combine(date_only, timezone.datetime.max.time()))
        except:
            pass

    # Get available inventory through the service interface
    inventory_data = inventory_service.get_available_items(user_id=user.id)
    
    # Apply additional filters
    filtered_inventory = []
    for item in inventory_data:
        # Apply owner filter
        owner_data = item.get('owner') or {}
        owner_name = owner_data.get('name') if isinstance(owner_data, dict) else (owner_data or '')
        if owner_filter and owner_filter != 'all':
            if owner_name != owner_filter:
                continue
        
        # Apply category filter
        category_data = item.get('category') or {}
        category_name = category_data.get('name') if isinstance(category_data, dict) else (category_data or '')
        if category_filter and category_filter != 'all':
            # Normalize both strings: strip whitespace and compare case-insensitively
            category_name_normalized = category_name.strip().lower() if category_name else ''
            category_filter_normalized = category_filter.strip().lower()
            if category_name_normalized != category_filter_normalized:
                continue
        
        # Apply search query
        manufacturer = item.get('manufacturer', '') or ''
        if isinstance(manufacturer, dict):
            manufacturer = manufacturer.get('name', '')
        if search_query:
            search_text = f"{item.get('description', '')} {item.get('inventory_number', '')} {manufacturer} {category_name}"
            if search_query.lower() not in search_text.lower():
                continue
        
        # Check availability for the period
        if start_date and end_date:
            # Use period-specific availability calculation
            try:
                available_qty = RentalService.get_available_quantity_for_period(
                    item['id'],
                    start_date,
                    end_date
                )
            except Exception:
                # Fallback to general availability if period calculation fails
                available_qty = inventory_service.get_available_quantity(item['id'])
        else:
            # No dates specified, use general availability
            available_qty = inventory_service.get_available_quantity(item['id'])
        
        if available_qty > 0:
            location_data = item.get('location') or {}
            owner_data = item.get('owner') or {}
            category_data = item.get('category') or {}
            
            # Handle location - can be dict or None
            if isinstance(location_data, dict):
                location_path = location_data.get('full_path', '')
                location_name = location_data.get('name', '')
            else:
                location_path = ''
                location_name = ''
            
            # Handle owner - can be dict or None
            if isinstance(owner_data, dict):
                owner_name = owner_data.get('name', '')
            else:
                owner_name = owner_data if owner_data else ''
            
            # Handle category - can be dict or None
            if isinstance(category_data, dict):
                category_name = category_data.get('name', '')
            else:
                category_name = category_data if category_data else ''
            
            # Handle manufacturer - can be string or None
            manufacturer = item.get('manufacturer', '') or ''
            if isinstance(manufacturer, dict):
                manufacturer = manufacturer.get('name', '')
            
            filtered_inventory.append({
                'id': item['id'],
                'inventory_number': item['inventory_number'],
                'description': item['description'],
                'location_path': location_path,
                'location_name': location_name,
                'owner': owner_name,
                'manufacturer': manufacturer,
                'category': category_name,
                'available_quantity': available_qty,
                'total_quantity': item.get('quantity', 0),
            })

    # Attach item photo thumbnails (first available image per item) when the
    # feature is enabled. Uses one batched query to avoid N+1.
    from .config import get_rental_show_item_photos
    if get_rental_show_item_photos() and filtered_inventory:
        from django.urls import reverse
        from inventory.models import InventoryItemImage
        item_ids = [row['id'] for row in filtered_inventory]
        thumb_map = {}
        for img in InventoryItemImage.objects.filter(
            item_id__in=item_ids, is_available=True
        ).order_by('item_id', 'filename'):
            thumb_map.setdefault(img.item_id, img.id)
        for row in filtered_inventory:
            image_id = thumb_map.get(row['id'])
            row['thumbnail_url'] = (
                reverse('inventory:item_image_thumb', args=[image_id])
                if image_id else None
            )
            row['image_url'] = (
                reverse('inventory:item_image', args=[image_id])
                if image_id else None
            )

    return JsonResponse({'inventory': filtered_inventory})


@login_required
def api_get_equipment_sets_user(request):
    """
    Get available equipment sets (user version).
    This version is accessible to regular users.
    """
    try:
        from .models import EquipmentSet
        equipment_sets = EquipmentSet.objects.filter(is_active=True)

        result = []
        for equipment_set in equipment_sets:
            # Check availability of all items in the set
            all_items_available = True
            total_items = 0

            for set_item in equipment_set.items.all():
                inventory_item = set_item.inventory_item
                if inventory_item:
                    total_items += 1
                    # Simple availability check
                    if not inventory_item.available_for_rent or inventory_item.status != 'in_stock':
                        all_items_available = False
                        break

            if all_items_available and total_items > 0:
                result.append({
                    'id': equipment_set.id,
                    'name': equipment_set.name,
                    'description': equipment_set.description,
                    'items_count': total_items,
                })

        return JsonResponse({'success': True, 'equipment_sets': result})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_get_equipment_set_details_user(request, set_id):
    """
    Get detailed information about a specific equipment set (user version).
    This version is accessible to regular users.

    Returns comprehensive details about an equipment set including
    all items, their availability, and metadata.

    Args:
        request: HTTP request object
        set_id: ID of the equipment set to get details for

    Returns:
        JsonResponse: Detailed equipment set information
    """
    try:
        from .models import EquipmentSet
        equipment_set = get_object_or_404(EquipmentSet, id=set_id, is_active=True)

        items_data = []
        for set_item in equipment_set.items.all():
            inventory_item = set_item.inventory_item
            if inventory_item:
                # Check item availability
                is_available = inventory_item.available_for_rent and inventory_item.status == 'in_stock'

                items_data.append({
                    'id': set_item.id,
                    'inventory_item_id': inventory_item.id,
                    'inventory_number': inventory_item.inventory_number,
                    'description': inventory_item.description,
                    'quantity_needed': set_item.quantity,
                    'quantity_available': inventory_item.quantity if is_available else 0,
                    'is_available': is_available,
                    'location': inventory_item.location.full_path if inventory_item.location else _('Location not specified'),
                    'category': inventory_item.category.name if inventory_item.category else _('No category')
                })

        result = {
            'id': equipment_set.id,
            'name': equipment_set.name,
            'description': equipment_set.description,
            'items': items_data,
            'total_items': len(items_data)
        }

        return JsonResponse({'success': True, 'equipment_set': result})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_get_rooms_user(request):
    """
    Get available rooms (user version).
    This version is accessible to regular users.
    """
    try:
        from .models import Room
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        # Get time parameters for availability checking
        start_date_str = request.GET.get('start_date', '')
        end_date_str = request.GET.get('end_date', '')

        start_date = None
        end_date = None

        if start_date_str:
            try:
                start_date = parse_datetime(start_date_str)
                if not start_date:
                    from django.utils.dateparse import parse_date
                    date_only = parse_date(start_date_str)
                    if date_only:
                        start_date = timezone.make_aware(timezone.datetime.combine(date_only, timezone.datetime.min.time()))
            except:
                pass

        if end_date_str:
            try:
                end_date = parse_datetime(end_date_str)
                if not end_date:
                    from django.utils.dateparse import parse_date
                    date_only = parse_date(end_date_str)
                    if date_only:
                        end_date = timezone.make_aware(timezone.datetime.combine(date_only, timezone.datetime.max.time()))
            except:
                pass

        rooms = Room.objects.filter(is_active=True)

        result = []
        for room in rooms:
            # Check room availability
            is_available = True
            availability_info = _("Available")

            if start_date and end_date:
                if not room.is_available_for_time(start_date, end_date):
                    is_available = False
                    availability_info = _("Not available for selected period")

            result.append({
                'id': room.id,
                'name': room.name,
                'description': room.description,
                'capacity': room.capacity,
                'location': room.location,
                'is_available': is_available,
                'availability_info': availability_info,
            })

        return JsonResponse({'success': True, 'rooms': result})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_get_room_schedule_user(request):
    """
    Get room schedule for regular users (without staff requirement).
    Returns room scheduling information for the specified period.
    """
    print(f"🔍 api_get_room_schedule_user ENTRY POINT")
    try:
        print(f"🔍 api_get_room_schedule_user called with params: {request.GET}")
        from datetime import datetime
        from datetime import timedelta
        from django.utils import timezone
        from django.utils.dateparse import parse_date

        # Get parameters
        room_id = request.GET.get('room_id')
        start_date_str = request.GET.get('start_date', '')
        end_date_str = request.GET.get('end_date', '')

        # Parse dates
        start_date = None
        end_date = None

        if start_date_str:
            start_date = parse_date(start_date_str)
        if end_date_str:
            end_date = parse_date(end_date_str)

        # If dates are not specified, use current week
        if not start_date:
            start_date = timezone.now().date()
        if not end_date:
            end_date = start_date + timedelta(days=6)

        # Get rooms
        if room_id:
            rooms = Room.objects.filter(id=room_id, is_active=True)
        else:
            rooms = Room.objects.filter(is_active=True)

        result = []
        for room in rooms:
            # Get all room rentals in the specified period
            room_rentals = RoomRental.objects.filter(
                room=room,
                rental_request__status__in=['reserved', 'issued'],
                rental_request__requested_start_date__date__lte=end_date,
                rental_request__requested_end_date__date__gte=start_date
            ).select_related('rental_request__user')

            # Build schedule by days
            schedule = []
            current_date = start_date
            while current_date <= end_date:
                # German day names mapping
                german_days = {
                    0: 'MO',  # Monday
                    1: 'DI',  # Tuesday
                    2: 'MI',  # Wednesday
                    3: 'DO',  # Thursday
                    4: 'FR',  # Friday
                    5: 'SA',  # Saturday
                    6: 'SO'   # Sunday
                }

                day_schedule = {
                    'date': current_date.isoformat(),
                    'day_name': current_date.strftime('%A'),
                    'day_short': german_days[current_date.weekday()],
                    'day_number': current_date.day,
                    'is_today': current_date == timezone.now().date(),
                    'is_weekend': current_date.weekday() >= 5,
                    'slots': []
                }

                for slot_start, slot_end in _iter_time_slots(current_date, 30):
                    slot_status = 'available'
                    slot_info = None

                    for rental in room_rentals:
                        rental_start = rental.rental_request.requested_start_date
                        rental_end = rental.rental_request.requested_end_date

                        if slot_start < rental_end and slot_end > rental_start:
                            slot_status = 'occupied'
                            slot_info = {
                                'user_name': rental.rental_request.user.get_full_name() or rental.rental_request.user.username,
                                'project': rental.rental_request.project_name or 'No project',
                                'status': rental.rental_request.status,
                                'people_count': rental.people_count or 1,
                                'start_time': rental.rental_request.requested_start_date.strftime('%H:%M'),
                                'end_time': rental.rental_request.requested_end_date.strftime('%H:%M')
                            }
                            break

                    day_schedule['slots'].append({
                        'time': slot_start.strftime('%H:%M'),
                        'status': slot_status,
                        'info': slot_info
                    })

                schedule.append(day_schedule)
                current_date += timedelta(days=1)

            result.append({
                'id': room.id,
                'name': room.name,
                'capacity': room.capacity,
                'location': room.location,
                'schedule': schedule
            })

        print(f"🔍 Returning {len(result)} rooms with schedules")
        return JsonResponse({
            'success': True,
            'rooms': result,
            'period': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            }
        })

    except Exception as e:
        import traceback
        print(f"Error in api_get_room_schedule_user: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def api_get_user_rental_details(request):
    """
    Get detailed rental information for the current user.
    Returns rental details filtered by type (active, returned, overdue).
    """
    from django.utils import timezone

    try:
        rental_type = request.GET.get('type', 'active')

        # Get user's rental requests based on type
        user_rentals = RentalRequest.objects.select_related('created_by').prefetch_related(
            'items__inventory_item',
            'room_rentals__room'
        ).filter(user=request.user)

        if rental_type == 'active':
            # Active rentals are those that are draft/reserved/issued and NOT expired
            rentals = user_rentals.filter(
                status__in=['draft', 'reserved', 'issued']
            ).filter(
                requested_end_date__isnull=False,
                requested_end_date__gte=timezone.now()
            )
        elif rental_type == 'returned':
            rentals = user_rentals.filter(status='returned')
        elif rental_type == 'overdue':
            # Overdue rentals are those that are active but past their end date
            rentals = user_rentals.filter(
                status__in=['reserved', 'issued']
            ).filter(
                requested_end_date__isnull=False,
                requested_end_date__lt=timezone.now()
            )
        else:
            return JsonResponse({
                'success': False,
                'error': 'Invalid type parameter'
            }, status=400)

        # Prepare rental data
        rental_data = []
        for rental in rentals:
            # Get rental items
            rental_items = []
            for item in rental.items.all():
                outstanding = (item.quantity_issued or 0) - (item.quantity_returned or 0)

                # Safely get inventory item info
                inventory_item = item.inventory_item
                if inventory_item:
                    description = inventory_item.description or 'No description'
                    inventory_number = inventory_item.inventory_number or 'N/A'
                else:
                    description = 'Unknown item'
                    inventory_number = 'N/A'

                rental_items.append({
                    'id': item.id if item else 0,
                    'inventory_item': {
                        'description': description,
                        'inventory_number': inventory_number
                    },
                    'quantity_requested': item.quantity_requested,
                    'quantity_issued': item.quantity_issued or 0,
                    'quantity_returned': item.quantity_returned or 0,
                    'outstanding': outstanding
                })

            # Get room rentals
            room_rentals = []
            for room_rental in rental.room_rentals.all():
                # Safely get room info
                room = room_rental.room
                if room:
                    room_name = room.name or 'Unknown room'
                    room_capacity = room.capacity or 0
                    room_location = room.location or 'Location not specified'
                else:
                    room_name = 'Unknown room'
                    room_capacity = 0
                    room_location = 'Location not specified'

                room_rentals.append({
                    'room': {
                        'name': room_name,
                        'capacity': room_capacity,
                        'location': room_location
                    },
                    'people_count': room_rental.people_count or 0,
                    'notes': room_rental.notes or '',
                    'requested_start_date': room_rental.requested_start_date.isoformat() if room_rental.requested_start_date else None,
                    'requested_end_date': room_rental.requested_end_date.isoformat() if room_rental.requested_end_date else None,
                })

            # Calculate days overdue if applicable
            days_overdue = 0
            if rental_type == 'overdue' and rental.requested_end_date:
                days_overdue = (timezone.now().date() - rental.requested_end_date.date()).days

            rental_data.append({
                'id': rental.id if rental else 0,
                'project_name': rental.project_name or '',
                'purpose': rental.purpose or '',
                'requested_start_date': rental.requested_start_date.isoformat() if rental.requested_start_date else None,
                'requested_end_date': rental.requested_end_date.isoformat() if rental.requested_end_date else None,
                'actual_end_date': rental.actual_end_date.isoformat() if rental.actual_end_date else None,
                'status': rental.status or '',
                'status_display': rental.get_status_display() if rental else '',
                'items': rental_items or [],
                'room_rentals': room_rentals or [],
                'days_overdue': days_overdue or 0
            })

        return JsonResponse({
            'success': True,
            'type': rental_type or '',
            'user': {
                'name': f"{request.user.profile.first_name} {request.user.profile.last_name}" if hasattr(request.user, 'profile') and request.user.profile and request.user.profile.first_name and request.user.profile.last_name else (request.user.email if request.user else ''),
                'email': request.user.email or ''
            },
            'rentals': rental_data or []
        })

    except Exception as e:
        import traceback
        print(f"Error in api_get_user_rental_details: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e) if e else 'Unknown error'
        }, status=500)


@login_required
def api_check_room_availability(request):
    """
    Check if a room is available for a specific time period.

    Args:
        request: HTTP request object with room_id, start_date, start_time, end_date, end_time

    Returns:
        JsonResponse: Availability status and any conflicts
    """
    if request.method != 'GET':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        room_id = request.GET.get('room_id')
        start_date = request.GET.get('start_date')
        start_time = request.GET.get('start_time')
        end_date = request.GET.get('end_date')
        end_time = request.GET.get('end_time')

        if not all([room_id, start_date, start_time, end_date, end_time]):
            return JsonResponse({'error': _('Missing required parameters')}, status=400)

        # Parse dates and times
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        start_datetime_str = f"{start_date}T{start_time}"
        end_datetime_str = f"{end_date}T{end_time}"

        start_datetime = parse_datetime(start_datetime_str)
        end_datetime = parse_datetime(end_datetime_str)

        if not start_datetime or not end_datetime:
            return JsonResponse({'error': _('Invalid date/time format')}, status=400)

        # Convert naive datetime to aware datetime if needed
        if timezone.is_naive(start_datetime):
            start_datetime = timezone.make_aware(start_datetime)
        if timezone.is_naive(end_datetime):
            end_datetime = timezone.make_aware(end_datetime)

        is_valid_period, error_message = validate_working_hours_period(start_datetime, end_datetime)
        if not is_valid_period:
            return JsonResponse({
                'success': True,
                'is_available': False,
                'message': error_message,
                'conflicts': [],
            })

        # Get room
        from .models import Room
        room = get_object_or_404(Room, id=room_id)

        # Check if room is available for the specified time
        is_available = room.is_available_for_time(start_datetime, end_datetime)

        if is_available:
            return JsonResponse({
                'success': True,
                'is_available': True,
                'message': _('Room is available for the selected period.')
            })
        else:
            # Get conflicting rentals for more detailed information
            conflicts = room.get_conflicting_rentals(start_datetime, end_datetime)
            conflict_info = []

            for conflict in conflicts:
                user = conflict.rental_request.user
                user_name = _("Unknown user")

                # Try to get name from profile
                try:
                    if hasattr(user, 'profile') and user.profile:
                        profile = user.profile
                        if hasattr(profile, 'first_name') and profile.first_name and hasattr(profile, 'last_name') and profile.last_name:
                            user_name = f"{profile.first_name} {profile.last_name}"
                        elif hasattr(profile, 'first_name') and profile.first_name:
                            user_name = profile.first_name
                        elif hasattr(profile, 'last_name') and profile.last_name:
                            user_name = profile.last_name
                    elif hasattr(user, 'first_name') and user.first_name and hasattr(user, 'last_name') and user.last_name:
                        user_name = f"{user.first_name} {user.last_name}"
                    elif hasattr(user, 'username') and user.username:
                        user_name = user.username
                    elif hasattr(user, 'email') and user.email:
                        user_name = user.email.split('@')[0]
                    else:
                        user_name = _("User #{user_id}").format(user_id=user.id)
                except:
                    user_name = _("User #{user_id}").format(user_id=user.id)

                project = conflict.rental_request.project_name
                status = conflict.rental_request.get_status_display()
                # Lead with the period: the point of this list is to tell the
                # user *when* the room is taken, so they can pick a free slot.
                period = format_booked_period(
                    conflict.get_start_date(), conflict.get_end_date())
                conflict_info.append(
                    f"{period} · {user_name} ({project}) - {status}")

            return JsonResponse({
                'success': True,
                'is_available': False,
                'message': _('Room is not available for the selected period.'),
                'conflicts': conflict_info
            })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@staff_member_required
def api_save_template(request):
    """
    Save selected equipment items as a reusable template.

    Args:
        request: HTTP request object with template data

    Returns:
        JsonResponse: Success status and template ID or error message
    """
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)

        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        items = data.get('items', [])

        if not name:
            return JsonResponse({'error': _('Template name is required')}, status=400)

        if not items:
            return JsonResponse({'error': _('At least one item is required')}, status=400)

        # Check if template with this name already exists
        from .models import EquipmentTemplate
        if EquipmentTemplate.objects.filter(name=name).exists():
            return JsonResponse({'error': _('Template with this name already exists')}, status=400)

        # Create template
        template = EquipmentTemplate.objects.create(
            name=name,
            description=description,
            created_by=request.user
        )

        # Create template items
        from .models import EquipmentTemplateItem
        for item_data in items:
            try:
                inventory_item = inventory_service.get_item(item_data['inventory_item_id'])
                quantity = item_data.get('quantity', 1)

                EquipmentTemplateItem.objects.create(
                    template=template,
                    inventory_item=inventory_item,
                    quantity=quantity
                )
            except InventoryItem.DoesNotExist:
                return JsonResponse({'error': _('Invalid inventory item ID')}, status=400)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=400)

        return JsonResponse({
            'success': True,
            'template_id': template.id,
            'message': _('Template saved successfully')
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': _('Invalid JSON data')}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_get_templates(request):
    """
    Get all available equipment templates.

    Returns:
        JsonResponse: List of templates with basic info
    """
    try:
        from .models import EquipmentTemplate

        templates = EquipmentTemplate.objects.select_related('created_by').prefetch_related('items').all()

        template_data = []
        for template in templates:
            template_data.append({
                'id': template.id,
                'name': template.name,
                'description': template.description,
                'created_by_name': template.created_by.get_full_name() or template.created_by.email if template.created_by else 'Unknown',
                'created_at': template.created_at.isoformat(),
                'items_count': template.items.count()
            })

        return JsonResponse({
            'success': True,
            'templates': template_data
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_load_template(request, template_id):
    """
    Load a specific template with its items.

    Args:
        request: HTTP request object
        template_id: ID of the template to load

    Returns:
        JsonResponse: Template data with items
    """
    try:
        from .models import EquipmentTemplate

        template = get_object_or_404(EquipmentTemplate, id=template_id)

        # Get template items with inventory details
        items_data = []
        for item in template.items.select_related('inventory_item__category', 'inventory_item__location').all():
            items_data.append({
                'quantity': item.quantity,
                'inventory_item': {
                    'id': item.inventory_item.id,
                    'description': item.inventory_item.description,
                    'inventory_number': item.inventory_item.inventory_number,
                    'category': {
                        'name': item.inventory_item.category.name if item.inventory_item.category else ''
                    } if item.inventory_item.category else None,
                    'location': {
                        'name': item.inventory_item.location.name if item.inventory_item.location else ''
                    } if item.inventory_item.location else None
                }
            })

        return JsonResponse({
            'success': True,
            'template': {
                'id': template.id,
                'name': template.name,
                'description': template.description,
                'items': items_data
            }
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_delete_template(request, template_id):
    """
    Delete an equipment template.

    Args:
        request: HTTP request object
        template_id: ID of the template to delete

    Returns:
        JsonResponse: Success status or error message
    """
    if request.method != 'DELETE':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        from .models import EquipmentTemplate

        template = get_object_or_404(EquipmentTemplate, id=template_id)
        template_name = template.name
        template.delete()

        return JsonResponse({
            'success': True,
            'message': _('Template deleted successfully')
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@staff_member_required
def api_issue_from_reservation(request):
    """
    Issue a rental from reservation status with ability to adjust positions and dates.

    Args:
        request: HTTP request object with rental_id, start_date, end_date, created_by, notes, item_quantities

    Returns:
        JsonResponse: Success status and message
    """
    if request.method != 'POST':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        data = json.loads(request.body)
        rental_id = data.get('rental_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        created_by = data.get('created_by')
        notes = data.get('notes', '')
        item_quantities = data.get('item_quantities', {})
        new_items = data.get('new_items', [])

        if not all([rental_id, start_date, end_date, created_by]):
            return JsonResponse({'error': _('Missing required parameters')}, status=400)

        # Parse dates
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        start_datetime = parse_datetime(start_date)
        end_datetime = parse_datetime(end_date)

        if not start_datetime or not end_datetime:
            return JsonResponse({'error': _('Invalid date format')}, status=400)

        # Convert naive datetime to aware datetime if needed
        if timezone.is_naive(start_datetime):
            start_datetime = timezone.make_aware(start_datetime)
        if timezone.is_naive(end_datetime):
            end_datetime = timezone.make_aware(end_datetime)

        # Get rental request
        rental = get_object_or_404(RentalRequest, id=rental_id)

        # Check if rental is in draft or reserved status
        if rental.status not in ['draft', 'reserved']:
            return JsonResponse({'error': _('Rental must be in draft or reserved status to issue')}, status=400)

        # Check if rental has any equipment items (rooms alone cannot be issued)
        # For mixed rentals, we issue only equipment, rooms remain reserved
        has_equipment = rental.items.exists()
        if not has_equipment:
            return JsonResponse({'error': _('Cannot issue rental with only rooms. Equipment is required to change status from reserved to issued.')}, status=400)
        
        # Note: For mixed rentals (rooms + equipment), we can issue equipment
        # Rooms will remain in reserved status and auto-return after scheduled time

        # Get the user by ID
        try:
            from registration.models import OKUser
            created_by_user = OKUser.objects.get(id=created_by)
        except OKUser.DoesNotExist:
            return JsonResponse({'error': _('Invalid user ID')}, status=400)

        # Update rental request - only equipment rentals can be issued
        rental.status = 'issued'
        rental.requested_start_date = start_datetime
        rental.requested_end_date = end_datetime
        rental.created_by = created_by_user
        if notes:
            rental.notes = notes
        rental.save()

        # Update item quantities if provided
        if item_quantities:
            for item_id, quantity in item_quantities.items():
                try:
                    rental_item = RentalItem.objects.get(id=item_id, rental_request=rental)
                    
                    # Validate that the requested quantity is available
                    available_qty = RentalService.get_available_quantity_for_period(
                        rental_item.inventory_item_id,
                        start_datetime,
                        end_datetime,
                        exclude_rental_request=rental.id
                    )
                    
                    # Add back the currently issued quantity (if any) since we're excluding this rental
                    # This allows increasing quantity_issued up to the available limit
                    current_issued = rental_item.quantity_issued or 0
                    available_qty += current_issued
                    
                    if available_qty < quantity:
                        return JsonResponse({
                            'error': _('Item "{item_description}" is not available in requested quantity. Available: {available}, requested: {requested}').format(
                                item_description=rental_item.inventory_item.description,
                                available=available_qty,
                                requested=quantity
                            )
                        }, status=400)
                    
                    # Calculate difference and create transaction instead of setting directly
                    # This ensures the signal handler updates quantity_issued correctly
                    old_issued = rental_item.quantity_issued or 0
                    quantity_to_issue = quantity - old_issued
                    
                    if quantity_to_issue > 0:
                        # Create transaction for the difference
                        RentalService.create_transaction(
                            rental_item=rental_item,
                            transaction_type='issue',
                            quantity=quantity_to_issue,
                            performed_by=created_by_user
                        )
                    # Note: quantity_issued will be updated by the signal handler
                    # Don't set it directly to avoid double increment
                except RentalItem.DoesNotExist:
                    continue

        # Add new items to the rental
        if new_items:
            for new_item_data in new_items:
                try:
                    inventory_id = new_item_data.get('inventory_id')
                    quantity = new_item_data.get('quantity', 1)

                    # Get the inventory item
                    inventory_item = inventory_service.get_item(inventory_id)
                    if not inventory_item:
                        return JsonResponse({'error': _('Inventory item not found')}, status=400)

                    # Check availability - pass item_id (int) not dict
                    available_qty = RentalService.get_available_quantity_for_period(
                        inventory_id,
                        start_datetime,
                        end_datetime,
                        exclude_rental_request=rental.id
                    )

                    if available_qty < quantity:
                        return JsonResponse({
                            'error': _('Item "{item_description}" is not available for the selected period. Available: {available}, requested: {requested}').format(
                                item_description=inventory_item['description'],
                                available=available_qty,
                                requested=quantity
                            )
                        }, status=400)

                    # Create new rental item
                    new_rental_item = RentalItem.objects.create(
                        rental_request=rental,
                        inventory_item_id=inventory_item['id'],
                        quantity_requested=quantity,
                        quantity_issued=0  # Will be set by transaction
                    )
                    
                    # Create transaction to issue the item
                    RentalService.create_transaction(
                        rental_item=new_rental_item,
                        transaction_type='issue',
                        quantity=quantity,
                        performed_by=created_by_user
                    )

                except Exception as e:
                    return JsonResponse({'error': str(e)}, status=400)

        # Update room rentals if any - only update dates, keep status as reserved
        room_rentals = RoomRental.objects.filter(rental_request=rental)
        for room_rental in room_rentals:
            room_rental.start_date = start_datetime
            room_rental.end_date = end_datetime
            # Rooms remain in reserved status - they are not physically issued
            room_rental.save()

        return JsonResponse({
            'success': True,
            'message': _('Rental successfully issued from reservation')
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@staff_member_required
def api_get_staff_users(request):
    """
    Get list of staff users for dropdown selection.

    Returns:
        JsonResponse: List of staff users with id, name, and email
    """
    if request.method != 'GET':
        return JsonResponse({'error': _('Method not allowed')}, status=405)

    try:
        from registration.models import OKUser

        # Get all staff users
        staff_users = OKUser.objects.filter(is_staff=True).select_related('profile')

        users_data = []
        for user in staff_users:
            name = user.email
            if hasattr(user, 'profile') and user.profile:
                if user.profile.first_name and user.profile.last_name:
                    name = f"{user.profile.first_name} {user.profile.last_name}"
                elif user.profile.first_name:
                    name = user.profile.first_name
                elif user.profile.last_name:
                    name = user.profile.last_name

            users_data.append({
                'id': user.id,
                'name': name,
                'email': user.email
            })

        return JsonResponse({
            'success': True,
            'users': users_data
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=400)

SIGNATURE_SVG_MAX_LENGTH = 50000
SIGNATURE_METADATA_MAX_LENGTH = 10000
SIGNATURE_POINTS_MAX_GROUPS = 200
SIGNATURE_POINTS_MAX_TOTAL_POINTS = 50000
SIGN_SESSION_RATE_LIMIT_ATTEMPTS = 20
SIGN_SESSION_RATE_LIMIT_WINDOW_SECONDS = 600


def _get_client_ip(request):
    """Get client IP from request headers."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _extract_signature_payload(data):
    """Extract signature payload from JSON/body dict."""
    signature_svg = data.get('signature_svg')
    signature_points = data.get('signature_points')
    signature_metadata = data.get('signature_metadata')
    signature_method = data.get('signature_method') or 'mouse'
    legacy_signature = data.get('legacy_signature')

    if isinstance(signature_points, str):
        signature_points = signature_points.strip()
        if signature_points:
            signature_points = json.loads(signature_points)
        else:
            signature_points = None

    if isinstance(signature_metadata, str):
        signature_metadata = signature_metadata.strip()
        if signature_metadata:
            signature_metadata = json.loads(signature_metadata)
        else:
            signature_metadata = None

    signature_svg = _sanitize_signature_svg(signature_svg)
    signature_points = _sanitize_signature_points(signature_points)
    signature_metadata = _sanitize_signature_metadata(signature_metadata)

    if signature_svg is not None and not isinstance(signature_svg, str):
        raise ValueError('signature_svg must be a string')
    if signature_points is not None and not isinstance(signature_points, list):
        raise ValueError('signature_points must be a list')
    if signature_metadata is not None and not isinstance(signature_metadata, dict):
        raise ValueError('signature_metadata must be an object')

    has_payload = bool(signature_svg) or bool(signature_points) or bool(legacy_signature)
    if not has_payload:
        raise ValueError('No signature payload provided')

    return {
        'signature_svg': signature_svg,
        'signature_points': signature_points,
        'signature_metadata': signature_metadata,
        'signature_method': signature_method,
        'legacy_signature': legacy_signature,
    }


def _is_sign_session_rate_limited(request, token):
    """Check and increment simple submit rate limit for signing sessions."""
    ip = _get_client_ip(request) or 'unknown'
    cache_key = f'sign-session-submit:{token}:{ip}'
    attempts = cache.get(cache_key, 0)
    if attempts >= SIGN_SESSION_RATE_LIMIT_ATTEMPTS:
        return True
    cache.set(cache_key, attempts + 1, timeout=SIGN_SESSION_RATE_LIMIT_WINDOW_SECONDS)
    return False


SVG_NAMESPACE = 'http://www.w3.org/2000/svg'

# Everything signature_pad's toSVG() emits, and nothing else. A blocklist does
# not work here: the payload is rendered raw (``|safe``) on the admin change
# form, and a list of forbidden strings always misses an event attribute
# (onbegin, onmouseover, onclick, ...) or an encoded javascript: URL.
SIGNATURE_SVG_ALLOWED_ELEMENTS = {
    'svg': {'viewbox', 'width', 'height'},
    'g': {'fill', 'stroke', 'stroke-width', 'transform'},
    'path': {
        'd', 'fill', 'stroke', 'stroke-width',
        'stroke-linecap', 'stroke-linejoin', 'stroke-opacity',
    },
    'polyline': {
        'points', 'fill', 'stroke', 'stroke-width',
        'stroke-linecap', 'stroke-linejoin',
    },
    'line': {'x1', 'y1', 'x2', 'y2', 'stroke', 'stroke-width', 'stroke-linecap'},
    'circle': {'cx', 'cy', 'r', 'fill', 'stroke', 'stroke-width'},
    'rect': {'x', 'y', 'width', 'height', 'fill', 'stroke', 'stroke-width'},
}


def _local_tag_name(tag):
    """Return the tag name without its ``{namespace}`` prefix, lowercased."""
    if not isinstance(tag, str):
        # Comments and processing instructions carry a callable as their tag.
        return None
    return tag.rsplit('}', 1)[-1].lower()


def _sanitize_signature_element(element):
    """Rebuild one element with only whitelisted children and attributes."""
    name = _local_tag_name(element.tag)
    allowed_attributes = SIGNATURE_SVG_ALLOWED_ELEMENTS.get(name)
    if allowed_attributes is None:
        return None

    clean = ET.Element(f'{{{SVG_NAMESPACE}}}{name}')
    for attribute, value in element.attrib.items():
        # Namespaced attributes (xlink:href and friends) never survive: they
        # are the classic carrier for javascript: URLs inside SVG.
        if '}' in attribute or ':' in attribute:
            continue
        if attribute.lower() in allowed_attributes:
            clean.set(attribute, value)

    for child in element:
        clean_child = _sanitize_signature_element(child)
        if clean_child is not None:
            clean.append(clean_child)

    return clean


def _sanitize_signature_svg(signature_svg):
    """Validate an SVG signature and return a rebuilt, whitelisted copy."""
    if signature_svg is None:
        return None
    if not isinstance(signature_svg, str):
        raise ValueError('signature_svg must be a string')

    signature_svg = signature_svg.strip()
    if not signature_svg:
        return None
    if len(signature_svg) > SIGNATURE_SVG_MAX_LENGTH:
        raise ValueError('signature_svg is too large')

    try:
        # defusedxml refuses entity expansion, so a signature cannot smuggle in
        # an XXE payload or a billion-laughs bomb.
        root = defused_fromstring(signature_svg)
    except DefusedXmlException as e:
        raise ValueError('signature_svg contains unsafe XML') from e
    except ET.ParseError as e:
        raise ValueError('signature_svg is not valid XML') from e

    if _local_tag_name(root.tag) != 'svg':
        raise ValueError('signature_svg root element must be <svg>')

    clean_root = _sanitize_signature_element(root)
    if clean_root is None:
        raise ValueError('signature_svg root element must be <svg>')

    ET.register_namespace('', SVG_NAMESPACE)
    return ET.tostring(clean_root, encoding='unicode')


def _sanitize_signature_points(signature_points):
    """Validate biometric points payload shape and limits."""
    if signature_points is None:
        return None
    if not isinstance(signature_points, list):
        raise ValueError('signature_points must be a list')
    if len(signature_points) > SIGNATURE_POINTS_MAX_GROUPS:
        raise ValueError('Too many signature point groups')

    total_points = 0
    sanitized_groups: list[dict[str, Any]] = []

    for group in signature_points:
        if not isinstance(group, dict):
            raise ValueError('signature_points group must be an object')
        points = group.get('points', [])
        if not isinstance(points, list):
            raise ValueError('signature_points group points must be a list')

        clean_points = []
        for point in points:
            if not isinstance(point, dict):
                raise ValueError('signature point must be an object')
            try:
                x = float(point.get('x', 0))
                y = float(point.get('y', 0))
                t = float(point.get('time', 0))
                p = float(point.get('pressure', 0.5))
            except (TypeError, ValueError) as e:
                raise ValueError('signature point contains invalid numeric values') from e

            clean_points.append({
                'x': x,
                'y': y,
                'time': t,
                'pressure': p,
            })

        total_points += len(clean_points)
        if total_points > SIGNATURE_POINTS_MAX_TOTAL_POINTS:
            raise ValueError('Too many signature points')

        clean_group: dict[str, Any] = {}
        clean_group['points'] = clean_points
        if 'color' in group:
            clean_group['color'] = str(group['color'])[:32]
        if 'minWidth' in group:
            clean_group['minWidth'] = group['minWidth']
        if 'maxWidth' in group:
            clean_group['maxWidth'] = group['maxWidth']
        sanitized_groups.append(clean_group)

    return sanitized_groups


def _sanitize_signature_metadata(signature_metadata):
    """Validate metadata payload and apply size limits."""
    if signature_metadata is None:
        return None
    if not isinstance(signature_metadata, dict):
        raise ValueError('signature_metadata must be an object')

    serialized = json.dumps(signature_metadata)
    if len(serialized) > SIGNATURE_METADATA_MAX_LENGTH:
        raise ValueError('signature_metadata is too large')

    return signature_metadata


def _render_svg_to_png_data_url(signature_svg):
    """Render SVG string to PNG data URL for legacy compatibility."""
    try:
        from cairosvg import svg2png
    except Exception:
        return None

    try:
        png_bytes = svg2png(bytestring=signature_svg.encode('utf-8'))
    except Exception:
        return None
    encoded = base64.b64encode(png_bytes).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def _apply_signature_to_rental_request(rental_request, payload):
    """Apply new signature payload to rental request with legacy dual-write."""
    _populate_signature_fields(rental_request, payload)

    rental_request.save(update_fields=[
        'signature',
        'signature_svg',
        'signature_points',
        'signature_metadata',
        'signature_method',
        'signature_signed_at',
    ])


def _populate_signature_fields(rental_request, payload):
    """Populate signature fields on model instance without saving."""
    rental_request.signature_svg = payload.get('signature_svg') or None
    rental_request.signature_points = payload.get('signature_points') or None
    rental_request.signature_metadata = payload.get('signature_metadata') or None
    rental_request.signature_method = payload.get('signature_method') or 'mouse'
    rental_request.signature_signed_at = timezone.now()

    legacy_signature = payload.get('legacy_signature')
    if legacy_signature:
        rental_request.signature = legacy_signature
    elif rental_request.signature_svg:
        rendered = _render_svg_to_png_data_url(rental_request.signature_svg)
        if rendered:
            rental_request.signature = rendered


def _may_sign_rental_request(user, rental_request):
    """Return True when ``user`` is allowed to sign this rental request.

    A signature is the legal record that the borrower received the equipment,
    so only staff (who hand it over) and the borrower themselves may write one.
    Without this check any logged-in user could enumerate ``pk`` and forge or
    wipe the signature on somebody else's rental.
    """
    if user.is_staff:
        return True
    return rental_request.user_id == user.id


@method_decorator(login_required, name='dispatch')
class SaveSignatureView(View):
    """Persist SVG/biometric signature payload for an existing rental request."""

    def post(self, request, *args, **kwargs):
        rental_pk = kwargs.get('pk')
        try:
            rental_request = RentalRequest.objects.get(pk=rental_pk)
        except RentalRequest.DoesNotExist:
            return JsonResponse({'success': False, 'error': _('Rental request not found.')}, status=404)

        if not _may_sign_rental_request(request.user, rental_request):
            return JsonResponse({'success': False, 'error': _('Not allowed.')}, status=403)

        if rental_request.status in ('returned', 'cancelled', 'closed'):
            return JsonResponse({'success': False, 'error': _('Cannot update a closed rental request.')}, status=400)

        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST
            payload = _extract_signature_payload(data)
            _apply_signature_to_rental_request(rental_request, payload)
        except (json.JSONDecodeError, ValueError) as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        except Exception as e:
            logger.error('Failed to save signature for rental request %s: %s', rental_pk, e, exc_info=True)
            return JsonResponse({'success': False, 'error': _('Failed to save signature.')}, status=500)

        return JsonResponse({'success': True, 'has_signature': rental_request.has_any_signature()})


@method_decorator(login_required, name='dispatch')
class CreateSigningSessionView(View):
    """Create QR signing session for cross-device signature capture."""

    def post(self, request, *args, **kwargs):
        rental_pk = kwargs.get('pk')
        try:
            rental_request = RentalRequest.objects.get(pk=rental_pk)
        except RentalRequest.DoesNotExist:
            return JsonResponse({'success': False, 'error': _('Rental request not found.')}, status=404)

        if not _may_sign_rental_request(request.user, rental_request):
            return JsonResponse({'success': False, 'error': _('Not allowed.')}, status=403)

        if rental_request.status in ('returned', 'cancelled', 'closed'):
            return JsonResponse({'success': False, 'error': _('Cannot sign a closed rental request.')}, status=400)

        try:
            expires_at = timezone.now() + timedelta(minutes=10)
            session = RentalSigningSession.objects.create(
                rental_request=rental_request,
                owner=request.user,
                token=uuid.uuid4().hex,
                status=RentalSigningSessionStatus.PENDING,
                expires_at=expires_at,
            )
            sign_url = request.build_absolute_uri(reverse('rental:sign_session_page', kwargs={'token': session.token}))
            qr_url = reverse('rental:sign_session_qr', kwargs={'token': session.token})
        except Exception:
            logger.exception('Failed to create signing session for rental %s', rental_pk)
            return JsonResponse({'success': False, 'error': _('Could not create signing session. Please try again.')}, status=500)

        return JsonResponse({
            'success': True,
            'token': session.token,
            'status': session.status,
            'expires_at': expires_at.isoformat(),
            'sign_url': sign_url,
            'qr_url': qr_url,
        })


@method_decorator(login_required, name='dispatch')
class SigningSessionStatusView(View):
    """Poll status for QR signing session."""

    def get(self, request, *args, **kwargs):
        token = kwargs.get('token')
        session = RentalSigningSession.objects.select_related('rental_request').filter(token=token).first()
        if not session:
            return JsonResponse({'success': False, 'error': _('Signing session not found.')}, status=404)

        owner = session.owner
        if owner is None and session.rental_request_id:
            owner = session.rental_request.user
        if owner != request.user:
            return JsonResponse({'success': False, 'error': _('Not allowed.')}, status=403)

        if session.status == RentalSigningSessionStatus.PENDING and session.is_expired():
            session.status = RentalSigningSessionStatus.EXPIRED
            session.save(update_fields=['status'])

        response_payload = {
            'success': True,
            'status': session.status,
            'expires_at': session.expires_at.isoformat(),
            'signed_at': session.signed_at.isoformat() if session.signed_at else None,
            'signature_svg': session.signature_svg,
            'signature_points': session.signature_points,
            'signature_metadata': session.signature_metadata,
            'signature_method': session.signature_method,
        }

        consume_flag = str(request.GET.get('consume', '')).lower() in {'1', 'true', 'yes'}
        if consume_flag and session.status == RentalSigningSessionStatus.SIGNED:
            session.delete()

        return JsonResponse(response_payload)


@method_decorator(login_required, name='dispatch')
class SigningSessionQRCodeView(View):
    """Render QR PNG for signing session URL."""

    def get(self, request, *args, **kwargs):
        token = kwargs.get('token')
        session = RentalSigningSession.objects.select_related('rental_request').filter(token=token).first()
        if not session:
            return HttpResponseNotFound()
        owner = session.owner
        if owner is None and session.rental_request_id:
            owner = session.rental_request.user
        if owner != request.user:
            return HttpResponseForbidden()

        sign_url = request.build_absolute_uri(reverse('rental:sign_session_page', kwargs={'token': token}))
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(sign_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buffer = io.BytesIO()
        img.save(buffer, 'PNG')
        return HttpResponse(buffer.getvalue(), content_type='image/png')


class SigningSessionPageView(TemplateView):
    """Public page used on phone to capture and submit a signature."""

    template_name = 'rental/sign_session.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        token = kwargs.get('token')
        session = RentalSigningSession.objects.select_related('rental_request').filter(token=token).first()
        context['session'] = session
        context['is_valid_session'] = bool(
            session and session.status == RentalSigningSessionStatus.PENDING and not session.is_expired()
        )
        if session and session.rental_request_id:
            context['rental_detail_url'] = reverse('rental:user_rental_detail', args=[session.rental_request_id])
        return context


class SubmitSigningSessionView(View):
    """Submit signed payload from phone and finalize session."""

    def post(self, request, *args, **kwargs):
        token = kwargs.get('token')

        if _is_sign_session_rate_limited(request, token):
            return JsonResponse(
                {'success': False, 'error': _('Too many requests. Please try again later.')}, status=429
            )

        session = RentalSigningSession.objects.select_related('rental_request').filter(token=token).first()
        if not session:
            return JsonResponse({'success': False, 'error': _('Signing session not found.')}, status=404)

        if session.status != RentalSigningSessionStatus.PENDING:
            return JsonResponse({'success': False, 'error': _('Signing session is not active.')}, status=400)
        if session.is_expired():
            session.status = RentalSigningSessionStatus.EXPIRED
            session.save(update_fields=['status'])
            return JsonResponse({'success': False, 'error': _('Signing session expired.')}, status=400)

        try:
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST
            payload = _extract_signature_payload(data)
        except (json.JSONDecodeError, ValueError) as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

        if not payload.get('signature_method'):
            payload['signature_method'] = 'qr_phone'

        session.signature_svg = payload.get('signature_svg')
        session.signature_points = payload.get('signature_points')
        session.signature_metadata = payload.get('signature_metadata')
        session.signature_method = payload.get('signature_method') or 'qr_phone'
        session.signer_ip = _get_client_ip(request)
        session.signer_user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:512]
        session.signed_at = timezone.now()
        session.status = RentalSigningSessionStatus.SIGNED
        session.save(update_fields=[
            'signature_svg',
            'signature_points',
            'signature_metadata',
            'signature_method',
            'signer_ip',
            'signer_user_agent',
            'signed_at',
            'status',
        ])

        if session.rental_request_id:
            _apply_signature_to_rental_request(session.rental_request, payload)
        return JsonResponse({'success': True, 'status': session.status})
