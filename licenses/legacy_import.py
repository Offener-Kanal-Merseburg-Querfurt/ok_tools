"""
Helpers for importing legacy archive data (old OK databases) into ok_tools.

Pure functions only (no DB access) so they can be unit tested and shared by
the management commands ``import_okdb_stendal`` and ``import_sendearchiv``.
"""
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import bisect
import re


# Earliest plausible date for anything in an OK archive (first German OKs
# started in the 1980s). Used to reject 0000-00-00 / 1899-12-30 style junk.
MIN_ARCHIVE_DATE = date(1984, 1, 1)

# Birthdays the old Stendal software filled in when the real one was unknown.
PLACEHOLDER_BIRTHDAYS = {
    date(2010, 3, 1),
    date(2010, 1, 1),
    date(1899, 12, 30),
    date(1900, 1, 1),
    date(1970, 1, 1),
}

_WS = re.compile(r'\s+')


def clean_text(value) -> str:
    """Strip and collapse whitespace; ``None`` becomes ''."""
    if value is None:
        return ''
    return _WS.sub(' ', str(value)).strip()


def parse_date(value) -> date | None:
    """Parse ISO dates, returning ``None`` for zero/invalid dates."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value)
    if not text or text.startswith('0000'):
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def plausible_date(value, *, max_date: date, min_date: date = MIN_ARCHIVE_DATE
                   ) -> date | None:
    """Return the date only if it lies in [min_date, max_date]."""
    parsed = parse_date(value)
    if parsed is None or not (min_date <= parsed <= max_date):
        return None
    return parsed


def plausible_birthday(value, *, today: date) -> date | None:
    """Drop placeholder and impossible birthdays (younger than 3 years)."""
    parsed = parse_date(value)
    if parsed is None or parsed in PLACEHOLDER_BIRTHDAYS:
        return None
    if parsed.year < 1900 or parsed > today.replace(year=today.year - 3):
        return None
    return parsed


def parse_duration(value) -> timedelta | None:
    """Parse 'HH:MM:SS' (or seconds) into a timedelta; 0/empty -> None."""
    if value is None or value == '':
        return None
    if isinstance(value, timedelta):
        return value or None
    if isinstance(value, (int, float)):
        return timedelta(seconds=int(value)) or None
    text = clean_text(value)
    match = re.fullmatch(r'(-?\d+):(\d{1,2})(?::(\d{1,2}))?', text)
    if not match:
        return None
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    result = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return result if result > timedelta(0) else None


def parse_time(value) -> time | None:
    """Parse 'HH:MM[:SS]' into a time."""
    if isinstance(value, time):
        return value
    duration = parse_duration(value)
    if duration is None:
        return time(0, 0) if clean_text(value) in ('00:00', '00:00:00') else None
    seconds = int(duration.total_seconds()) % 86400
    return time(seconds // 3600, seconds % 3600 // 60, seconds % 60)


def normalize_zipcode(value) -> str:
    """
    Restore German 5-digit zip codes.

    The old DB stored them as numbers, so '06128' became '6128'.
    """
    text = clean_text(value).replace(' ', '')
    if re.fullmatch(r'\d{4}', text):
        return '0' + text
    return text[:5]


_STREET_RE = re.compile(
    r'^(?P<street>.*?\D)\s*'
    r'(?P<number>\d+\s*[a-zA-Z]?(?:\s*[-/+]\s*\d*\s*[a-zA-Z]?)?)\s*$'
)


def split_street(value) -> tuple[str, str]:
    """Split 'Bahnhofstr. 12a' into ('Bahnhofstr.', '12a')."""
    text = clean_text(value)
    match = _STREET_RE.match(text)
    if not match:
        return text, ''
    street = match.group('street').strip().rstrip(',')
    number = _WS.sub('', match.group('number'))
    return street, number


def normalize_phone(value) -> str:
    """Unify phone notation: keep digits, '+', and one '/' as separator."""
    text = clean_text(value)
    if not re.search(r'\d{3,}', text):
        return ''
    text = re.sub(r'[^\d+/ ]', ' ', text)
    text = re.sub(r'\s*/\s*', '/', text)
    return _WS.sub(' ', text).strip()[:30]


def normalize_email(value) -> str:
    """Return a lowercased valid email address or ''."""
    text = clean_text(value).lower().replace(' ', '')
    text = text.removeprefix('mailto:')
    if not text:
        return ''
    try:
        validate_email(text)
    except ValidationError:
        return ''
    return text


def gender_from_salutation(value) -> str:
    """Map Herr/Frau to the Gender choices of registration.Profile."""
    text = clean_text(value).lower()
    if text == 'herr':
        return 'm'
    if text == 'frau':
        return 'f'
    return 'none'


_QUOTED_TITLE = re.compile(r'^[\"„“”\']\s*(?P<title>[^\"„“”]+?)\s*[\"“”\']\s*(?P<rest>.*)$')


def split_title(value, max_length: int = 255) -> tuple[str, str]:
    """
    Split Stendal style titles into (title, subtitle).

    '"Stendaler Telegramm" 02.03.2012 Nachrichten' ->
    ('Stendaler Telegramm', '02.03.2012 Nachrichten')
    """
    text = clean_text(value)
    match = _QUOTED_TITLE.match(text)
    if match:
        title = match.group('title').strip()
        rest = match.group('rest').strip(' -–:,')
        return title[:max_length], rest[:max_length]
    return text.strip('"')[:max_length], ''


def is_filler_title(title: str) -> bool:
    """Dummy / filler clips used to pad broadcast blocks."""
    return bool(re.search(r'\bOK\s+DUMMY\b', title or '', re.IGNORECASE))


def classify_tape_label(label) -> tuple[str, str] | None:
    """
    Map a Merseburg 'SB-Nr.' value to (medium_type, number).

    Returns ``None`` when the label says the tape no longer exists.
    """
    text = clean_text(label)
    if not text:
        return None
    lower = text.lower()
    if lower.startswith('gelöscht') or lower.startswith('geloescht'):
        return None
    raid = re.fullmatch(r'(?:raid|read)\s*(\d+)', lower)
    if raid:
        return 'raid', f'Raid {raid.group(1)}'
    if 'cd' in lower and re.fullmatch(r'[a-z]*-?cd-?r?', lower):
        return 'other', text
    return 'tape', text


def interpolate_dates(known: dict[int, date], numbers) -> dict[int, date]:
    """
    Estimate missing dates from neighbouring numbers.

    Contribution numbers were handed out chronologically, so a number
    without a registration date gets the date of the closest lower number
    that has one (or the closest higher one at the very beginning).
    """
    ordered = sorted(known)
    result = {}
    if not ordered:
        return result
    for number in numbers:
        if number in known:
            continue
        pos = bisect.bisect_left(ordered, number)
        neighbour = ordered[pos - 1] if pos > 0 else ordered[0]
        result[number] = known[neighbour]
    return result
