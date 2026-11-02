from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import time
from typing import Dict
from typing import Optional
from typing import Tuple

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _lazy


WEEKDAY_NAMES = [
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
    'sunday',
]

WEEKDAY_LABELS = [
    _lazy('Monday'),
    _lazy('Tuesday'),
    _lazy('Wednesday'),
    _lazy('Thursday'),
    _lazy('Friday'),
    _lazy('Saturday'),
    _lazy('Sunday'),
]

WEEKDAY_SHORT_LABELS = [
    _lazy('Mon'),
    _lazy('Tue'),
    _lazy('Wed'),
    _lazy('Thu'),
    _lazy('Fri'),
    _lazy('Sat'),
    _lazy('Sun'),
]


def format_time_value(value: Optional[time]) -> Optional[str]:
    if not value:
        return None
    return value.strftime('%H:%M')


def get_rental_working_hours_config():
    from .models import RentalConfig

    return RentalConfig.get_config()


def get_working_hours_by_weekday() -> Dict[str, Dict[str, Optional[str]]]:
    config = get_rental_working_hours_config()
    serialized: Dict[str, Dict[str, Optional[str]]] = {}

    for weekday, day_name in enumerate(WEEKDAY_NAMES):
        hours = config.get_weekday_hours(weekday)
        serialized[str(weekday)] = {
            'weekday': day_name,
            'label': str(WEEKDAY_LABELS[weekday]),
            'short_label': str(WEEKDAY_SHORT_LABELS[weekday]),
            'enabled': hours['enabled'],
            'start': format_time_value(hours['start']),
            'end': format_time_value(hours['end']),
        }

    return serialized


def get_working_hours_summary() -> str:
    config = get_rental_working_hours_config()
    parts = []

    for weekday in range(7):
        hours = config.get_weekday_hours(weekday)
        if hours['enabled']:
            parts.append(
                _('{day} {start}-{end}').format(
                    day=WEEKDAY_SHORT_LABELS[weekday],
                    start=format_time_value(hours['start']),
                    end=format_time_value(hours['end']),
                )
            )

    if not parts:
        return _('No working hours configured')

    return ', '.join(parts)


def get_day_working_hours(target_date: date) -> Dict[str, Optional[str]]:
    config = get_rental_working_hours_config()
    weekday = target_date.weekday()
    hours = config.get_weekday_hours(weekday)

    return {
        'weekday': WEEKDAY_NAMES[weekday],
        'label': str(WEEKDAY_LABELS[weekday]),
        'short_label': str(WEEKDAY_SHORT_LABELS[weekday]),
        'enabled': hours['enabled'],
        'start': format_time_value(hours['start']),
        'end': format_time_value(hours['end']),
    }


def get_day_working_window(target_date: date) -> Tuple[Optional[datetime], Optional[datetime]]:
    config = get_rental_working_hours_config()
    hours = config.get_weekday_hours(target_date.weekday())

    if not hours['enabled']:
        return None, None

    tz = timezone.get_current_timezone()
    start_at = timezone.make_aware(datetime.combine(target_date, hours['start']), tz)
    end_at = timezone.make_aware(datetime.combine(target_date, hours['end']), tz)
    return start_at, end_at


def can_bypass_working_hours(user) -> bool:
    """Staff may book equipment and rooms outside the configured working hours."""
    return bool(user is not None and getattr(user, 'is_staff', False))


def validate_working_hours_period(
    start_at: datetime,
    end_at: datetime,
    user=None,
) -> Tuple[bool, Optional[str]]:
    if end_at <= start_at:
        return False, _('End date must be after start date')

    if can_bypass_working_hours(user):
        return True, None

    start_window, start_close = get_day_working_window(start_at.date())
    end_window, end_close = get_day_working_window(end_at.date())

    if not start_window or not start_close:
        return False, _('The selected start day is closed.')

    if not end_window or not end_close:
        return False, _('The selected end day is closed.')

    if start_at < start_window or start_at >= start_close:
        return False, _('The selected start time is outside the configured working hours.')

    if end_at < end_window or end_at > end_close:
        return False, _('The selected end time is outside the configured working hours.')

    return True, None
