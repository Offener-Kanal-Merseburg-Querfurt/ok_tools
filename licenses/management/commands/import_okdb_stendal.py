"""
Import the legacy OK Stendal database ("okdb") into a fresh ok_tools install.

Input is the JSON dump written by ``deployment/scripts/okdb_dump.py``.

What is imported:

* stammdaten (+ adressen, plz_ort, kontakt, nutzer, stammrubrik) -> Profile
  (+ OKUser for every unique valid e-mail address, unless --no-users)
* beitragsarchiv                      -> License (number = beitragsarchivnummer)
* beitragsrubrik                      -> Category
* archiv_dvd / archiv_vhs / archiv_mastervhs / archiv_masterdvd
                                      -> ArchiveMedium
* sendeplanung + beitragsarchiv_has_sendeplanung (exact times)
  and beitragsarchiv_has_sendeanzahl (dates only) -> Contribution
* optionally: future sendeplanung days -> planung.TagesPlan (as drafts)

Everything runs in one transaction; --dry-run rolls it back at the end, so
the numbers printed by a dry run are the real ones.

Usage::

    python manage.py import_okdb_stendal okdb_stendal.json --dry-run
    python manage.py import_okdb_stendal okdb_stendal.json \\
        --report /tmp/okdb_report.csv --with-tagesplan
"""
from collections import defaultdict
from contributions.models import Contribution
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from licenses import legacy_import as li
from licenses.models import ArchiveMedium
from licenses.models import ArchiveMediumType
from licenses.models import Category
from licenses.models import License
from licenses.models import default_category
from ok_tools.datetime import TZ
from registration.models import OKUser
from registration.models import Profile
from registration.models import default_media_authority
import csv
import json


MARKER = '[Alt-DB Stendal]'

MEDIA_TABLES = {
    'archiv_dvd': ('dvd', ArchiveMediumType.DVD),
    'archiv_masterdvd': ('masterdvd', ArchiveMediumType.MASTER_DVD),
    'archiv_vhs': ('vhs', ArchiveMediumType.VHS),
    'archiv_mastervhs': ('mastervhs', ArchiveMediumType.MASTER_VHS),
}


class _DryRun(Exception):
    """Raised to roll back the transaction after a dry run."""


class Command(BaseCommand):
    """Import the OK Stendal legacy database dump."""

    help = 'Import the legacy OK Stendal database (JSON dump of okdb).'

    def add_arguments(self, parser):
        """Define command line options."""
        parser.add_argument('dump', help='JSON file from deployment/scripts/okdb_dump.py')
        parser.add_argument('--dry-run', action='store_true',
                            help='Run everything, then roll back.')
        parser.add_argument('--no-users', action='store_true',
                            help='Do not create login accounts (OKUser).')
        parser.add_argument(
            '--default-time', default='20:15',
            help='Broadcast time for dates known without time (HH:MM).')
        parser.add_argument(
            '--with-tagesplan', action='store_true',
            help='Also create draft day plans (planung) from the old plan.')
        parser.add_argument(
            '--tagesplan-from', default=None,
            help='First day for --with-tagesplan (YYYY-MM-DD, default today).')
        parser.add_argument('--report', default=None,
                            help='Write a CSV with every data fix/problem.')

    # ------------------------------------------------------------------ io
    def handle(self, *args, **options):
        """Run the import."""
        with open(options['dump'], encoding='utf-8') as fh:
            dump = json.load(fh)
        self.t = dump.get('tables', dump)
        self.today = timezone.localdate()
        self.issues = []
        self.stats = defaultdict(int)
        self.default_time = li.parse_time(options['default_time']) or time(20, 15)

        try:
            with transaction.atomic():
                self._check_empty_target()
                self._import(options)
                if options['dry_run']:
                    raise _DryRun()
        except _DryRun:
            self.stdout.write(self.style.WARNING(
                'DRY RUN - all changes rolled back.'))

        for key in sorted(self.stats):
            self.stdout.write(f'  {key}: {self.stats[key]}')
        if options['report']:
            with open(options['report'], 'w', newline='',
                      encoding='utf-8-sig') as fh:
                writer = csv.writer(fh, delimiter=';')
                writer.writerow(['kind', 'old id', 'message'])
                writer.writerows(self.issues)
            self.stdout.write(f'Report: {options["report"]} '
                              f'({len(self.issues)} rows)')

    def issue(self, kind, old_id, message):
        """Remember a data fix or problem for the report."""
        self.issues.append([kind, old_id, message])
        self.stats[f'fix: {kind}'] += 1

    def rows(self, table):
        """Rows of a dumped table ([] if the table was empty)."""
        return self.t.get(table) or []

    def lookup(self, table, key, value):
        """Build {key: value} for a small lookup table."""
        return {r[key]: r[value] for r in self.rows(table)}

    def _check_empty_target(self):
        numbers = [r['beitragsarchivnummer'] for r in self.rows('beitragsarchiv')]
        clash = License.objects.filter(number__in=numbers).count()
        marked = Profile.objects.filter(comment__contains=MARKER).count()
        if clash or marked:
            raise CommandError(
                f'Target database is not empty: {clash} license numbers '
                f'already exist, {marked} profiles were imported before. '
                'This command is meant for a fresh installation.')

    # -------------------------------------------------------------- import
    def _import(self, options):
        beitraege = {r['beitragsarchivnummer']: r
                     for r in self.rows('beitragsarchiv')}
        broadcasts = self._collect_broadcasts(beitraege)
        profiles = self._import_profiles(options, beitraege, broadcasts)
        licenses = self._import_licenses(beitraege, profiles, broadcasts)
        self._import_media(licenses)
        self._import_contributions(licenses, broadcasts)
        if options['with_tagesplan']:
            start = (li.parse_date(options['tagesplan_from'])
                     if options['tagesplan_from'] else self.today)
            self._import_tagesplan(licenses, start)

    # ---------------------------------------------------------- broadcasts
    def _collect_broadcasts(self, beitraege):
        """
        Return {number: sorted list of aware datetimes}.

        Exact times come from the block plan (block start + durations of the
        clips before). Dates of the 'n. Sendedatum' list are added when the
        plan has no broadcast of that number on that day.
        """
        startzeit = {k: li.parse_time(v) for k, v in
                     self.lookup('startzeit', 'id_startzeit', 'startzeit').items()}
        items_by_block = defaultdict(list)
        for row in self.rows('beitragsarchiv_has_sendeplanung'):
            items_by_block[row['id_sendeplanung']].append(row)

        result = defaultdict(set)
        self.plan_days = defaultdict(list)   # date -> [(dt, number, dur)]
        max_date = self.today.replace(year=self.today.year + 2)
        for block in self.rows('sendeplanung'):
            day = li.plausible_date(block['sendedatum'], max_date=max_date)
            start = startzeit.get(block['id_startzeit'])
            if day is None or start is None:
                self.issue('plan block without date/time',
                           block['id_sendeplanung'], str(block))
                continue
            current = datetime.combine(day, start, tzinfo=TZ)
            items = sorted(items_by_block.get(block['id_sendeplanung'], []),
                           key=lambda r: r['sendefolgenummer'] or 0)
            for item in items:
                number = item['beitragsarchivnummer']
                beitrag = beitraege.get(number)
                if beitrag is None:
                    continue
                duration = li.parse_duration(beitrag['beitragsdauer']) \
                    or timedelta(0)
                self.plan_days[day].append((current, number, duration))
                if not li.is_filler_title(beitrag['beitragstitel']):
                    result[number].add(current)
                current += duration

        planned_days = {(n, dt.date()) for n, dts in result.items()
                        for dt in dts}
        for row in self.rows('beitragsarchiv_has_sendeanzahl'):
            number = row['beitragsarchivnummer']
            if number not in beitraege:
                continue
            day = li.plausible_date(row['sendedatum'], max_date=max_date)
            if day is None:
                if li.clean_text(row['sendedatum']):
                    self.issue('invalid broadcast date dropped', number,
                               row['sendedatum'])
                continue
            if (number, day) in planned_days:
                continue
            if li.is_filler_title(beitraege[number]['beitragstitel']):
                continue
            result[number].add(datetime.combine(day, self.default_time,
                                                tzinfo=TZ))
            self.stats['broadcasts without exact time'] += 1
        return {n: sorted(dts) for n, dts in result.items()}

    # ------------------------------------------------------------ profiles
    def _person_records(self):
        anrede = self.lookup('anrede', 'id_anrede', 'anrede')
        titel = self.lookup('titel', 'id_titel', 'titel')
        adressen = {r['id_adresse']: r for r in self.rows('adressen')}
        plz_ort = {r['id_plz_ort']: r for r in self.rows('plz_ort')}
        kontakt = {r['id_kontakt']: r for r in self.rows('kontakt')}
        nutzer = {r['id_nutzer']: r for r in self.rows('nutzer')}
        rubrik = self.lookup('stammrubrik', 'id_stammrubrik', 'stammrubrik')
        rubriken = defaultdict(list)
        for r in self.rows('stammdaten_has_stammrubrik'):
            name = rubrik.get(r['stammrubrik_id_stammrubrik'])
            if name:
                rubriken[r['stammdaten_id_stammdaten']].append(name)

        records = {}
        for s in self.rows('stammdaten'):
            pid = s['id_stammdaten']
            adr = adressen.get(s['adressen_id_adresse']) or {}
            ort = plz_ort.get(adr.get('plz_ort_id_plz_ort')) or {}
            kon = kontakt.get(s['kontakt_id_kontakt']) or {}
            nut = nutzer.get(s['nutzer_id_nutzer']) or {}

            street, house = li.split_street(adr.get('strasse_hausnummer'))
            raw_zip = li.clean_text(ort.get('plz'))
            zipcode = li.normalize_zipcode(raw_zip)
            if zipcode != raw_zip and raw_zip:
                self.issue('zipcode leading zero restored', pid,
                           f'{raw_zip} -> {zipcode}')
            birthday = li.plausible_birthday(s['geb_datum'], today=self.today)
            if birthday is None and li.parse_date(s['geb_datum']):
                self.issue('placeholder birthday removed', pid,
                           s['geb_datum'])
            email = li.normalize_email(kon.get('mail'))
            if li.clean_text(kon.get('mail')) and not email:
                self.issue('invalid email kept in comment', pid, kon.get('mail'))

            records[pid] = {
                'id': pid,
                'first_name': li.clean_text(s['vorname'])[:150],
                'last_name': li.clean_text(s['nachname'])[:150],
                'company': li.clean_text(s['firmenname']),
                'title': li.clean_text(titel.get(s['titel_id_titel'])),
                'gender': li.gender_from_salutation(
                    anrede.get(s['anrede_id_anrede'])),
                'salutation': li.clean_text(anrede.get(s['anrede_id_anrede'])),
                'birthday': birthday,
                'street': street[:95], 'house_number': house[:20],
                'zipcode': zipcode, 'city': li.clean_text(ort.get('ort'))[:35],
                'phone': li.normalize_phone(kon.get('tel_privat')),
                'mobile': li.normalize_phone(kon.get('tel_mobil')),
                'phone_work': li.normalize_phone(kon.get('tel_dienst')),
                'fax': li.normalize_phone(kon.get('fax')),
                'email': email,
                'raw_email': li.clean_text(kon.get('mail')),
                'id_number': li.clean_text(nut.get('ausweisnummer'))[:50],
                'user_since': li.parse_date(nut.get('nutzer_seit')),
                'user_until': li.parse_date(nut.get('nutzer_bis')),
                'application': li.clean_text(nut.get('nutzerantrag')),
                'groups': sorted(set(rubriken.get(pid, []))),
                'remark': li.clean_text(s['bemerkung']),
                'old_ids': [pid],
            }
        return records

    def _merge_duplicates(self, records, beitraege):
        """Merge records with same name and compatible birthday/zip."""
        count = defaultdict(int)
        for b in beitraege.values():
            count[b['stammdaten_id_stammdaten']] += 1
        by_name = defaultdict(list)
        for rec in records.values():
            if rec['last_name'] and rec['first_name']:
                by_name[(rec['first_name'].lower(),
                         rec['last_name'].lower())].append(rec)
        alias = {}
        for group in by_name.values():
            group.sort(key=lambda r: (-count[r['id']], r['id']))
            keep = group[0]
            for other in group[1:]:
                compatible = all(
                    not keep[f] or not other[f] or keep[f] == other[f]
                    for f in ('birthday', 'zipcode'))
                if not compatible:
                    self.issue('same name, kept separate', other['id'],
                               f'{other["first_name"]} {other["last_name"]} '
                               f'(vs. id {keep["id"]})')
                    continue
                for field, value in other.items():
                    if field == 'old_ids':
                        keep['old_ids'] += value
                    elif field == 'groups':
                        keep['groups'] = sorted(set(keep['groups'] + value))
                    elif not keep.get(field) and value:
                        keep[field] = value
                alias[other['id']] = keep['id']
                self.issue('duplicate person merged', other['id'],
                           f'merged into id {keep["id"]}')
        for old in alias:
            del records[old]
        return alias

    def _comment(self, rec):
        lines = [MARKER, f'Alt-DB-ID: {", ".join(map(str, sorted(rec["old_ids"])))}']
        if rec['groups']:
            lines.append(f'Gruppe: {", ".join(rec["groups"])}')
        if rec['company'] and (rec['first_name'] or rec['last_name']):
            lines.append(f'Firma/Organisation: {rec["company"]}')
        if rec['title']:
            lines.append(f'Titel: {rec["title"]}')
        if rec['salutation'] in ('Familie', 'Firma'):
            lines.append(f'Anrede: {rec["salutation"]}')
        if rec['user_since']:
            lines.append(f'Nutzer seit: {rec["user_since"]}')
        if rec['user_until']:
            lines.append(f'Nutzer bis: {rec["user_until"]}')
        if rec['application']:
            lines.append(f'Nutzerantrag: {rec["application"]}')
        if rec['phone_work']:
            lines.append(f'Tel. dienstlich: {rec["phone_work"]}')
        if rec['fax']:
            lines.append(f'Fax: {rec["fax"]}')
        if rec['raw_email'] and rec.get('email_note'):
            lines.append(f'E-Mail: {rec["raw_email"]} ({rec["email_note"]})')
        if rec['remark']:
            lines.append(f'Bemerkung: {rec["remark"]}')
        return '\n'.join(lines)

    def _import_profiles(self, options, beitraege, broadcasts):
        records = self._person_records()
        alias = self._merge_duplicates(records, beitraege)

        # first known activity of each person -> created_at
        first_seen = {}
        for number, b in beitraege.items():
            pid = alias.get(b['stammdaten_id_stammdaten'],
                            b['stammdaten_id_stammdaten'])
            dates = [d.date() for d in broadcasts.get(number, [])]
            reg = li.plausible_date(b['registriert_am'], max_date=self.today)
            if reg:
                dates.append(reg)
            if dates:
                first_seen[pid] = min([first_seen.get(pid, date.max), *dates])

        # e-mail is the login and must be unique
        users = {}
        if not options['no_users']:
            taken = set(OKUser.objects.values_list('email', flat=True))
            unusable = make_password(None)
            for rec in sorted(records.values(), key=lambda r: r['id']):
                if not rec['email']:
                    continue
                if rec['email'] in taken:
                    rec['email_note'] = 'doppelt, kein Login angelegt'
                    self.issue('duplicate email, no login', rec['id'],
                               rec['email'])
                    continue
                taken.add(rec['email'])
                users[rec['id']] = OKUser(
                    email=rec['email'], password=unusable, is_active=True)
            OKUser.objects.bulk_create(users.values())
            self.stats['users created'] = len(users)
        for rec in records.values():
            if rec['raw_email'] and not rec['email']:
                rec['email_note'] = 'ungültig'

        authority = default_media_authority()
        objs = {}
        for pid, rec in records.items():
            first, last = rec['first_name'], rec['last_name']
            if not first and not last:
                last = rec['company'] or f'Unbekannt (Alt-DB {pid})'
            since = rec['user_since'] or first_seen.get(pid)
            objs[pid] = Profile(
                okuser=users.get(pid),
                first_name=first, last_name=last, gender=rec['gender'],
                phone_number=rec['phone'] or rec['phone_work'] or None,
                mobile_number=rec['mobile'] or None,
                ausweisnummer=rec['id_number'] or None,
                birthday=rec['birthday'],
                street=rec['street'] or None,
                house_number=rec['house_number'] or None,
                zipcode=rec['zipcode'] or None, city=rec['city'] or None,
                verified=bool(rec['id_number']),
                created_at=(datetime.combine(since, time(12), tzinfo=TZ)
                            if since else timezone.now()),
                media_authority=authority,
                comment=self._comment(rec),
            )
        Profile.objects.bulk_create(objs.values())
        self.stats['profiles created'] = len(objs)

        mapping = {pid: obj for pid, obj in objs.items()}
        for old, new in alias.items():
            mapping[old] = objs[new]
        return mapping

    def _unknown_profile(self):
        if not hasattr(self, '_unknown'):
            self._unknown = Profile.objects.create(
                first_name='Unbekannt', last_name='(Alt-DB Stendal)',
                media_authority=default_media_authority(),
                comment=f'{MARKER}\nPlatzhalter für Beiträge ohne '
                        'zugeordneten Nutzer in der Alt-DB.',
            )
        return self._unknown

    # ------------------------------------------------------------ licenses
    def _import_licenses(self, beitraege, profiles, broadcasts):
        rubrik = self.lookup('beitragsrubrik', 'id_beitragsrubrik',
                             'beitragarchivrubrik')
        bewertung = self.lookup('bewertung', 'id_bewertung', 'bewertung')
        categories = {}
        for rid, name in rubrik.items():
            name = li.clean_text(name)
            if name:
                categories[rid] = Category.objects.get_or_create(name=name)[0]
        fallback_category = default_category()

        known = {}
        for number, b in beitraege.items():
            reg = li.plausible_date(b['registriert_am'], max_date=self.today)
            first = broadcasts.get(number)
            if reg and first and first[0].date() < reg:
                reg = first[0].date()   # registered after it aired: typo
            if reg is None and first:
                reg = first[0].date()
            if reg:
                known[number] = reg
        estimated = li.interpolate_dates(known, beitraege)

        objs = {}
        for number, b in sorted(beitraege.items()):
            title, subtitle = li.split_title(b['beitragstitel'])
            duration = li.parse_duration(b['beitragsdauer'])
            filler = li.is_filler_title(title)
            notes = [MARKER]
            if li.clean_text(b['kommentar']):
                notes.append(f'Kommentar: {li.clean_text(b["kommentar"])}')
            rating = bewertung.get(b['bewertung_id_bewertung'])
            if rating:
                notes.append(f'Bewertung: {rating}')
            if li.clean_text(b['rausgeben']):
                notes.append(f'Herausgabe erlaubt: {b["rausgeben"]}')
            if li.clean_text(b['freistellungserklaerung']):
                notes.append('Freistellungserklärung: Papier (Ordner Beitrag)')
            if filler:
                notes.append('Füller/Dummy - keine Sendungen gezählt.')
            if duration is None:
                notes.append('Dauer fehlte in der Alt-DB.')
                self.issue('missing duration', number, title)
            created = known.get(number) or estimated.get(number)
            if number not in known:
                notes.append('Erfassungsdatum geschätzt.')
            profile = profiles.get(b['stammdaten_id_stammdaten'])
            if profile is None:
                profile = self._unknown_profile()
                self.issue('license without person', number, title)
            created_dt = (datetime.combine(created, time(12), tzinfo=TZ)
                          if created else timezone.now())
            objs[number] = License(
                number=number, legacy_number=number,
                title=title or f'Beitrag {number}', subtitle=subtitle or None,
                duration=duration or timedelta(0),
                profile=profile,
                category=categories.get(
                    b['beitragarchivsrubrik_id_beitragsrubrik'],
                    fallback_category),
                external_production=b['fremdbeitrag'] == 'ja',
                media_authority_exchange_allowed=b['austausch'] == 'ja',
                repetitions_allowed=True,
                store_in_ok_media_library=False,
                youth_protection_necessary=False,
                confirmed=True, confirmed_at=created_dt,
                created_at=created_dt,
                internal_note='\n'.join(notes),
            )
        License.objects.bulk_create(objs.values(), batch_size=1000)
        # created_at is auto_now_add, so bulk_create stamped "now";
        # bulk_update writes the historical dates back (no pre_save there).
        for obj in objs.values():
            obj.created_at = obj.confirmed_at
        License.objects.bulk_update(objs.values(), ['created_at'],
                                    batch_size=1000)
        self.stats['licenses created'] = len(objs)
        self.stats['licenses with estimated date'] = len(estimated)
        return objs

    def _import_media(self, licenses):
        media = []
        for table, (column, medium_type) in MEDIA_TABLES.items():
            seen = set()
            for row in self.rows(table):
                number = row['beitragsarchivnummer']
                label = li.clean_text(row.get(column))
                if number not in licenses:
                    continue
                note = ''
                if not label or label == '0':
                    # the old DB only flagged "exists on this carrier type"
                    label, note = 'ohne Nr.', 'Nummer in der Alt-DB nicht erfasst'
                key = (number, label)
                if key in seen:
                    continue
                seen.add(key)
                media.append(ArchiveMedium(
                    license=licenses[number], medium_type=medium_type,
                    number=label, note=note))
            self.stats[f'archive media: {medium_type}'] = len(seen)
        ArchiveMedium.objects.bulk_create(media, batch_size=2000)

    def _import_contributions(self, licenses, broadcasts):
        objs = [
            Contribution(license=licenses[number], broadcast_date=dt,
                         live=False)
            for number, dts in broadcasts.items() if number in licenses
            for dt in dts
        ]
        Contribution.objects.bulk_create(objs, batch_size=2000)
        self.stats['contributions created'] = len(objs)

    def _import_tagesplan(self, licenses, start):
        from planung.models import TagesPlan
        existing = set(TagesPlan.objects.filter(datum__gte=start)
                       .values_list('datum', flat=True))
        plans = []
        for day, entries in sorted(self.plan_days.items()):
            if day < start or day in existing:
                continue
            items = []
            for dt, number, duration in sorted(entries, key=lambda e: e[0]):
                lic = licenses.get(number)
                if lic is None:
                    continue
                items.append({
                    'number': number,
                    'start': dt.strftime('%H:%M:%S'),
                    'duration': int(duration.total_seconds()),
                    'title': lic.title,
                    'subtitle': lic.subtitle or '',
                    'sender_responsible': str(lic.profile),
                    'license_id': lic.pk,
                    'is_live': False,
                })
            plans.append(TagesPlan(
                datum=day,
                json_plan={'items': items, 'draft': True, 'planned': False},
                kommentar=f'{MARKER} aus der alten Sendeplanung übernommen '
                          '- bitte prüfen.'))
        TagesPlan.objects.bulk_create(plans)
        self.stats['day plans created (draft)'] = len(plans)
