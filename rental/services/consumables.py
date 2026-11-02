"""
Consumables handed out with a rental that are not kept in inventory.

Staff list them as free text on the rental detail page (one per line, e.g.
"XLR cable 5 m - 3"), tick them off on the return screen, and resolve what is
still missing later. Missing consumables are reminded by email, see
``send_missing_consumable_reminders``.
"""

from __future__ import annotations
from ..models import RentalConsumable
from ..models import RentalRequest
from datetime import timedelta
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Tuple
import re


MAX_QUANTITY = 9999

# A trailing number is the quantity: "XLR cable 5 m - 3", "SD card 64GB 5",
# "Gaffer tape x2", "Batteries AA: 8 Stk". "XLR cable 5m" keeps quantity 1,
# because "5m" is not a bare number.
_QUANTITY_RE = re.compile(
    r'^(?P<name>.*?\S)\s*(?:[-–—:x×*]\s*)?(?P<qty>\d+)\s*(?:stk|st|pcs|pc|шт)?\.?$',
    re.IGNORECASE,
)


def parse_consumable_lines(text: str) -> List[Tuple[str, int]]:
    """Split free text into ``(name, quantity)`` pairs, one per non-empty line."""
    entries = []
    for raw_line in (text or '').splitlines():
        line = raw_line.strip().strip('-–—•*').strip()
        if not line:
            continue
        match = _QUANTITY_RE.match(line)
        name, quantity = line, 1
        candidate = match.group('name').strip().rstrip('-–—:x×*').strip() if match else ''
        # A line that is only a number ("12") has no name to split off.
        if candidate and not candidate.isdigit():
            name = candidate
            quantity = int(match.group('qty'))
        quantity = min(max(quantity, 1), MAX_QUANTITY)
        entries.append((name[:255], quantity))
    return entries


def add_consumables(rental_request: RentalRequest, text: str, user) -> List[RentalConsumable]:
    """Create one consumable per line of ``text``."""
    return [
        RentalConsumable.objects.create(
            rental_request=rental_request,
            name=name,
            quantity=quantity,
            created_by=user,
        )
        for name, quantity in parse_consumable_lines(text)
    ]


def apply_consumable_returns(
    rental_request: RentalRequest,
    returns: Iterable[Dict[str, Any]],
) -> Tuple[List[RentalConsumable], List[RentalConsumable]]:
    """
    Record the return check of the handed-out consumables.

    ``returns`` holds ``{'id', 'qty_returned', 'note'}`` per consumable. Every
    consumable still handed out is checked: one that is not in ``returns`` is
    treated as not returned at all, so nothing silently stays "out" after the
    rental was returned. Returns ``(returned, missing)``.
    """
    by_id = {}
    for entry in returns or []:
        try:
            by_id[int(entry.get('id'))] = entry
        except (TypeError, ValueError):
            continue

    now = timezone.now()
    returned, missing = [], []
    with transaction.atomic():
        pending = rental_request.consumables.select_for_update().filter(
            status=RentalConsumable.STATUS_OUT)
        for consumable in pending:
            entry = by_id.get(consumable.pk, {})
            try:
                quantity = int(entry.get('qty_returned') or 0)
            except (TypeError, ValueError):
                quantity = 0
            consumable.quantity_returned = min(max(quantity, 0), consumable.quantity)
            note = (entry.get('note') or '').strip()
            if note:
                consumable.notes = f'{consumable.notes}\n{note}'.strip()
            consumable.returned_at = now
            if consumable.quantity_returned >= consumable.quantity:
                consumable.status = RentalConsumable.STATUS_RETURNED
                returned.append(consumable)
            else:
                consumable.status = RentalConsumable.STATUS_MISSING
                missing.append(consumable)
            consumable.save(update_fields=[
                'quantity_returned', 'notes', 'returned_at', 'status'])
    return returned, missing


def resolve_missing_consumable(consumable: RentalConsumable, action: str, user) -> None:
    """
    Close a missing consumable: ``returned`` later or ``written_off``.

    A consumable still marked as handed out (its rental was returned without
    the return screen) can also be resolved, or marked ``missing`` so that it
    is reminded about.
    """
    open_statuses = (RentalConsumable.STATUS_OUT, RentalConsumable.STATUS_MISSING)
    if consumable.status not in open_statuses:
        raise ValueError('Only open consumables can be resolved.')
    if action == 'missing':
        if consumable.status != RentalConsumable.STATUS_OUT:
            raise ValueError('Only handed-out consumables can be marked as missing.')
        consumable.status = RentalConsumable.STATUS_MISSING
        consumable.returned_at = timezone.now()
        consumable.save(update_fields=['status', 'returned_at'])
        return
    if action == 'returned':
        consumable.status = RentalConsumable.STATUS_RETURNED
        consumable.quantity_returned = consumable.quantity
    elif action == 'written_off':
        consumable.status = RentalConsumable.STATUS_WRITTEN_OFF
    else:
        raise ValueError(f'Unknown action: {action}')
    now = timezone.now()
    consumable.returned_at = consumable.returned_at or now
    consumable.resolved_at = now
    consumable.resolved_by = user
    consumable.save(update_fields=[
        'status', 'quantity_returned', 'returned_at', 'resolved_at', 'resolved_by'])


# Rentals in these states are past the return, so an unticked consumable is
# missing rather than still handed out.
RETURNED_RENTAL_STATUSES = ('returned', 'closed', 'cancelled', 'rejected')


def update_consumable_line(consumable: RentalConsumable, line: str) -> bool:
    """Rename a consumable from one checklist line ("XLR cable 3 m - 3")."""
    entries = parse_consumable_lines(line)
    if len(entries) != 1:
        return False
    consumable.name, consumable.quantity = entries[0]
    consumable.quantity_returned = min(consumable.quantity_returned, consumable.quantity)
    consumable.save(update_fields=['name', 'quantity', 'quantity_returned'])
    return True


def set_consumable_checked(consumable: RentalConsumable, checked: bool, user) -> None:
    """
    Tick a consumable off the checklist (returned) or untick it again.

    Unticking goes back to "handed out" while the rental is still active, and
    to "missing" once the rental is past its return, so it is reminded about.
    Written-off consumables are not changed here.
    """
    if consumable.status == RentalConsumable.STATUS_WRITTEN_OFF:
        raise ValueError('Written-off consumables cannot be ticked.')
    now = timezone.now()
    if checked:
        if consumable.status == RentalConsumable.STATUS_RETURNED:
            return
        if consumable.status == RentalConsumable.STATUS_MISSING:
            consumable.resolved_at = now
            consumable.resolved_by = user
        consumable.status = RentalConsumable.STATUS_RETURNED
        consumable.quantity_returned = consumable.quantity
        consumable.returned_at = consumable.returned_at or now
    else:
        if consumable.status != RentalConsumable.STATUS_RETURNED:
            return
        consumable.quantity_returned = 0
        consumable.resolved_at = None
        consumable.resolved_by = None
        if consumable.rental_request.status in RETURNED_RENTAL_STATUSES:
            consumable.status = RentalConsumable.STATUS_MISSING
            consumable.returned_at = now
        else:
            consumable.status = RentalConsumable.STATUS_OUT
            consumable.returned_at = None
    consumable.save(update_fields=[
        'status', 'quantity_returned', 'returned_at', 'resolved_at', 'resolved_by'])


def missing_consumables() -> QuerySet:
    """All consumables that did not come back and are not resolved yet."""
    return RentalConsumable.objects.filter(
        status=RentalConsumable.STATUS_MISSING,
    ).select_related('rental_request', 'rental_request__user', 'rental_request__user__profile')


def consumables_due_for_reminder(interval_days: int, now=None) -> QuerySet:
    """Missing consumables whose last reminder (or return) is ``interval_days`` old."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=interval_days)
    return missing_consumables().filter(
        returned_at__lte=cutoff,
    ).exclude(
        last_reminder_sent_at__gt=cutoff,
    )


def serialize_consumable(consumable: RentalConsumable) -> Dict[str, Any]:
    """JSON shape used by the return screen."""
    return {
        'id': consumable.pk,
        'name': consumable.name,
        'quantity': consumable.quantity,
        'quantity_returned': consumable.quantity_returned,
        'status': consumable.status,
        'status_label': str(consumable.get_status_display()),
        'quantity_missing': consumable.quantity_missing,
        'reminder_count': consumable.reminder_count,
        'notes': consumable.notes,
    }
