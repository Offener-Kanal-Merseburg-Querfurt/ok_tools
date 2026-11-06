"""
Attach DVD / tape numbers from the old OK Merseburg Sendearchiv to licenses.

The contributions themselves are already in ok_tools. This command only
finds, for every Sendearchiv row that has a "DVD-Nr." or "SB-Nr.", the
matching License (Freistellung) and adds

* the carriers as ArchiveMedium (DVD, Sendeband, RAID, ...),
* the old "Beitrag-Nr." as ``legacy_number`` (if the license has none yet).

Nothing else is created or changed. Matching, strongest rule first:

1. ``legacy_number`` already equals the Beitrag-Nr. (re-run);
2. same number and same title;
3. same title + broadcast/creation date (+-1 day) + same user;
4. same title + date, only one candidate;
5. same title + same user, and that title exists only once.

Rows with several equally good candidates or no candidate are not touched
and are listed in the --report CSV for manual work.

Usage::

    python manage.py import_sendearchiv Sendearchiv.html --dry-run \\
        --report sendearchiv_report.csv
    python manage.py import_sendearchiv Sendearchiv.html --report r.csv
"""
from collections import defaultdict
from contributions.models import Contribution
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from licenses import legacy_import as li
from licenses.models import ArchiveMedium
from licenses.models import ArchiveMediumType
from licenses.models import License
from ok_tools.datetime import TZ
import csv
import json
import re


# column positions in the DATA array of Sendearchiv.html
(NR, DAY, TIME, MINUTES, TITLE, SUBTITLE, DESCRIPTION, LAST, FIRST, CITY,
 DVD, TAPE, RUBRIC, EXTERNAL_PERSON, CAMERA, EDIT, LIVE) = range(17)

OK_FIRST_NAME = 'Offener Kanal'


class _DryRun(Exception):
    """Raised to roll back the transaction after a dry run."""


def read_sendearchiv(path):
    """Return the DATA rows embedded in Sendearchiv.html (or a JSON list)."""
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    if text.lstrip().startswith('['):
        return json.loads(text)
    marker = 'const DATA = '
    start = text.find(marker)
    if start < 0:
        raise CommandError('No "const DATA = [...]" found in the file.')
    start += len(marker)
    end = text.index('];\n', start) + 1
    return json.loads(text[start:end])


def norm(value) -> str:
    """Compare titles/names ignoring case, punctuation and spacing."""
    text = li.clean_text(value).lower().replace('ß', 'ss')
    return ' '.join(re.findall(r'[^\W_]+', text))


def row_media(row):
    """ArchiveMedium kwargs for a Sendearchiv row."""
    media = []
    if row[DVD]:
        media.append((ArchiveMediumType.DVD, str(row[DVD])))
    tape = li.classify_tape_label(row[TAPE])
    if tape:
        media.append((tape[0], tape[1][:50]))
    return media


def person_names(row) -> set[str]:
    """Normalized names under which the row's user may exist."""
    first, last = norm(row[FIRST]), norm(row[LAST])
    names = {last, f'{first} {last}'.strip()}
    if li.clean_text(row[FIRST]) == OK_FIRST_NAME:
        names.add(norm(f'OK {row[LAST]}'))
    return {n for n in names if n}


class Command(BaseCommand):
    """Link Sendearchiv DVD/tape numbers to existing licenses."""

    help = 'Add DVD/tape numbers from Sendearchiv.html to existing licenses.'

    def add_arguments(self, parser):
        """Define command line options."""
        parser.add_argument('file', help='Sendearchiv.html')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--report', default=None,
                            help='CSV with the result for every row.')

    def handle(self, *args, **options):
        """Run the matching."""
        rows = [r for r in read_sendearchiv(options['file']) if row_media(r)]
        self.stats = defaultdict(int)
        self.result = []
        try:
            with transaction.atomic():
                self._link(rows)
                if options['dry_run']:
                    raise _DryRun()
        except _DryRun:
            self.stdout.write(self.style.WARNING(
                'DRY RUN - all changes rolled back.'))
        self.stdout.write(f'Rows with DVD/tape: {len(rows)}')
        for key in sorted(self.stats):
            self.stdout.write(f'  {key}: {self.stats[key]}')
        if options['report']:
            with open(options['report'], 'w', newline='',
                      encoding='utf-8-sig') as fh:
                writer = csv.writer(fh, delimiter=';')
                writer.writerow([
                    'Status', 'Regel', 'Beitrag-Nr.', 'Datum', 'Titel',
                    'Untertitel', 'Nutzer', 'DVD', 'SB-Nr.',
                    'Lizenz-Nr.', 'Kandidaten'])
                writer.writerows(self.result)
            self.stdout.write(f'Report: {options["report"]}')

    # ------------------------------------------------------------------
    def _index(self):
        """Load every license once: title index, dates, user names."""
        self.licenses = {}
        self.by_title = defaultdict(set)
        for lic in (License.objects.select_related('profile')
                    .only('id', 'number', 'title', 'subtitle', 'created_at',
                          'legacy_number', 'profile__first_name',
                          'profile__last_name')):
            self.licenses[lic.id] = lic
            title = norm(lic.title)
            self.by_title[title].add(lic.id)
            if lic.subtitle:
                self.by_title[norm(f'{lic.title} {lic.subtitle}')].add(lic.id)
        self.dates = defaultdict(set)
        for lic_id, when in Contribution.objects.values_list(
                'license_id', 'broadcast_date'):
            self.dates[lic_id].add(when.astimezone(TZ).date())
        for lic in self.licenses.values():
            if lic.created_at:
                self.dates[lic.id].add(lic.created_at.astimezone(TZ).date())
        self.by_legacy = {lic.legacy_number: lic.id
                          for lic in self.licenses.values()
                          if lic.legacy_number}
        self.by_number = {lic.number: lic.id for lic in self.licenses.values()}

    def _user_matches(self, lic, row):
        p = lic.profile
        names = {norm(p.last_name), norm(f'{p.first_name} {p.last_name}'),
                 norm(f'{p.last_name} {p.first_name}')}
        return bool(names & person_names(row))

    def _date_matches(self, lic, row):
        day = li.parse_date(row[DAY])
        if day is None:
            return False
        window = {day - timedelta(days=1), day, day + timedelta(days=1)}
        return bool(self.dates[lic.id] & window)

    def _match(self, row):
        """Return (license id or None, rule, candidate numbers)."""
        if row[NR] in self.by_legacy:
            return self.by_legacy[row[NR]], 'Alt-Nr. bereits gesetzt', []

        title = norm(row[TITLE])
        cands = set(self.by_title.get(title, ()))
        if row[SUBTITLE]:
            cands |= self.by_title.get(norm(f'{row[TITLE]} {row[SUBTITLE]}'),
                                       set())
        if not cands:
            return None, 'Titel nicht gefunden', []

        same_number = self.by_number.get(row[NR])
        if same_number in cands:
            return same_number, 'Nummer + Titel', []

        lics = [self.licenses[i] for i in cands]
        numbers = sorted(lic.number for lic in lics)
        with_date = [lic for lic in lics if self._date_matches(lic, row)]
        with_both = [lic for lic in with_date if self._user_matches(lic, row)]
        if len(with_both) == 1:
            return with_both[0].id, 'Titel + Datum + Nutzer', []
        if len(with_both) > 1:
            return None, 'mehrdeutig (Titel + Datum + Nutzer)', numbers
        if len(with_date) == 1:
            return with_date[0].id, 'Titel + Datum', []
        if len(with_date) > 1:
            return None, 'mehrdeutig (Titel + Datum)', numbers
        with_user = [lic for lic in lics if self._user_matches(lic, row)]
        if len(lics) == 1 and len(with_user) == 1:
            return with_user[0].id, 'Titel + Nutzer (Datum abweichend)', []
        return None, 'kein eindeutiger Treffer', numbers

    def _link(self, rows):
        self._index()
        media, legacy = [], {}
        for row in rows:
            lic_id, rule, cands = self._match(row)
            status = 'zugeordnet' if lic_id else 'offen'
            self.stats[f'{status}: {rule}'] += 1
            lic = self.licenses.get(lic_id)
            self.result.append([
                status, rule, row[NR], row[DAY], row[TITLE], row[SUBTITLE],
                ' '.join(filter(None, [li.clean_text(row[FIRST]),
                                       li.clean_text(row[LAST])])),
                row[DVD] or '', li.clean_text(row[TAPE]),
                lic.number if lic else '',
                ', '.join(map(str, cands[:10])),
            ])
            if lic is None:
                continue
            for medium_type, number in row_media(row):
                media.append(ArchiveMedium(
                    license_id=lic.id, medium_type=medium_type,
                    number=number, note=f'Sendearchiv Nr. {row[NR]}'))
            if not lic.legacy_number and lic.id not in legacy \
                    and row[NR] not in self.by_legacy:
                legacy[lic.id] = row[NR]

        before = ArchiveMedium.objects.count()
        ArchiveMedium.objects.bulk_create(media, batch_size=2000,
                                          ignore_conflicts=True)
        self.stats['archive media added'] = ArchiveMedium.objects.count() - before
        # queryset.update(): confirmed licenses refuse a normal save()
        for lic_id, number in legacy.items():
            License.objects.filter(pk=lic_id).update(legacy_number=number)
        self.stats['legacy numbers set'] = len(legacy)
