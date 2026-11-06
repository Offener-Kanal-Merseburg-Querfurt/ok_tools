"""Tests for the legacy archive importers (OK Stendal okdb, Sendearchiv)."""
from contributions.models import Contribution
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from django.core.management import call_command
from licenses import legacy_import as li
from licenses.models import ArchiveMedium
from licenses.models import License
from ok_tools.datetime import TZ
from registration.models import OKUser
from registration.models import Profile
import io
import json
import pytest


TODAY = date(2026, 11, 4)


# ------------------------------------------------------------- helpers
@pytest.mark.parametrize('raw, expected', [
    ('Bahnhofstr. 12a', ('Bahnhofstr.', '12a')),
    ('Hohenweidener Weg 86', ('Hohenweidener Weg', '86')),
    ('Schillerstraß 1B', ('Schillerstraß', '1B')),
    ('Am Markt 3 - 5', ('Am Markt', '3-5')),
    ('Postfach', ('Postfach', '')),
    ('', ('', '')),
])
def test_split_street(raw, expected):
    """Street and house number are separated without losing text."""
    assert li.split_street(raw) == expected


def test_normalize_zipcode_restores_leading_zero():
    """Zip codes stored as numbers lost their leading zero."""
    assert li.normalize_zipcode('6128') == '06128'
    assert li.normalize_zipcode('39576') == '39576'
    assert li.normalize_zipcode('') == ''


@pytest.mark.parametrize('raw, expected', [
    ('1983-02-22', date(1983, 2, 22)),
    ('2010-03-01', None),      # placeholder of the old software
    ('1899-12-30', None),      # Access/Excel zero date
    ('0000-00-00', None),
    ('2025-01-01', None),      # younger than 3 years
    (None, None),
])
def test_plausible_birthday(raw, expected):
    """Placeholder and impossible birthdays are dropped."""
    assert li.plausible_birthday(raw, today=TODAY) == expected


def test_plausible_date_rejects_junk():
    """Zero dates and far-future dates are not real broadcasts."""
    assert li.plausible_date('3000-11-11', max_date=TODAY) is None
    assert li.plausible_date('0000-00-00', max_date=TODAY) is None
    assert li.plausible_date('2012-02-13', max_date=TODAY) == date(2012, 2, 13)


def test_split_title():
    """Quoted series names become title, the rest the subtitle."""
    assert li.split_title(
        '"Stendaler Telegramm" 02.03.2012 Informationen') == (
        'Stendaler Telegramm', '02.03.2012 Informationen')
    assert li.split_title('"00 OK DUMMY 01 1 MINUTE"') == (
        '00 OK DUMMY 01 1 MINUTE', '')
    assert li.split_title('Monopoly Hindenburg') == ('Monopoly Hindenburg', '')


def test_parse_duration_and_time():
    """TIME columns are parsed; zero means unknown."""
    assert li.parse_duration('00:11:57') == timedelta(minutes=11, seconds=57)
    assert li.parse_duration('00:00:00') is None
    assert li.parse_duration(None) is None
    assert li.parse_time('20:15:00') == time(20, 15)
    assert li.parse_time('18:05') == time(18, 5)


def test_contact_normalization():
    """E-mails are validated, phones unified, salutations mapped."""
    assert li.normalize_email(' Max@Example.DE ') == 'max@example.de'
    assert li.normalize_email('kein@') == ''
    assert li.normalize_phone('03931 / 410884') == '03931/410884'
    assert li.normalize_phone('-') == ''
    assert li.gender_from_salutation('Frau') == 'f'
    assert li.gender_from_salutation('Firma') == 'none'


@pytest.mark.parametrize('raw, expected', [
    ('140', ('tape', '140')),
    ('140/84', ('tape', '140/84')),
    ('Raid 2', ('raid', 'Raid 2')),
    ('Raid3', ('raid', 'Raid 3')),
    ('READ 4', ('raid', 'Raid 4')),
    ('O-CDR', ('other', 'O-CDR')),
    ('Talking Food', ('tape', 'Talking Food')),
    ('gelöscht', None),
    ('', None),
])
def test_classify_tape_label(raw, expected):
    """Merseburg SB-Nr. values map to carrier types."""
    assert li.classify_tape_label(raw) == expected


def test_interpolate_dates():
    """Numbers without date inherit the date of the previous number."""
    known = {10: date(2010, 1, 1), 20: date(2011, 1, 1)}
    assert li.interpolate_dates(known, [5, 10, 15, 25]) == {
        5: date(2010, 1, 1), 15: date(2010, 1, 1), 25: date(2011, 1, 1)}


# ------------------------------------------------------ stendal import
def _okdb_dump(tmp_path):
    tables = {
        'anrede': [{'id_anrede': 1, 'anrede': 'Herr'},
                   {'id_anrede': 2, 'anrede': 'Frau'}],
        'titel': [{'id_titel': 1, 'titel': ''}],
        'plz_ort': [{'id_plz_ort': 1, 'plz': '6128', 'ort': 'Halle'},
                    {'id_plz_ort': 2, 'plz': '39576', 'ort': 'Stendal'}],
        'adressen': [
            {'id_adresse': 1, 'plz_ort_id_plz_ort': 1,
             'strasse_hausnummer': 'Hohenweidener Weg 86'},
            {'id_adresse': 2, 'plz_ort_id_plz_ort': 2,
             'strasse_hausnummer': 'Frommhagenstr. 32'}],
        'kontakt': [
            {'id_kontakt': 1, 'tel_privat': '03931 / 410884', 'tel_dienst': '',
             'tel_mobil': '', 'mail': 'Sophie@Example.de', 'fax': ''},
            {'id_kontakt': 2, 'tel_privat': '', 'tel_dienst': '',
             'tel_mobil': '', 'mail': 'sophie@example.de', 'fax': ''}],
        'nutzer': [{'id_nutzer': 1, 'nutzer_seit': '2004-02-05',
                    'nutzer_bis': None, 'ausweisnummer': '5009042393',
                    'nutzerantrag': ''}],
        'stammrubrik': [{'id_stammrubrik': 1, 'stammrubrik': 'OK'},
                        {'id_stammrubrik': 2, 'stammrubrik': 'Fremdnutzer'}],
        'stammdaten': [
            {'id_stammdaten': 1, 'anrede_id_anrede': 2, 'titel_id_titel': 1,
             'firmenname': '', 'vorname': 'Sophie', 'nachname': 'Hahes',
             'geb_datum': '1983-02-22', 'adressen_id_adresse': 2,
             'kontakt_id_kontakt': 1, 'nutzer_id_nutzer': 1,
             'bemerkung': None},
            # duplicate of 1 (same name, no birthday) -> merged
            {'id_stammdaten': 2, 'anrede_id_anrede': 2, 'titel_id_titel': 1,
             'firmenname': '', 'vorname': 'Sophie', 'nachname': 'Hahes',
             'geb_datum': '0000-00-00', 'adressen_id_adresse': None,
             'kontakt_id_kontakt': 2, 'nutzer_id_nutzer': None,
             'bemerkung': 'zweiter Eintrag'},
            {'id_stammdaten': 3, 'anrede_id_anrede': 1, 'titel_id_titel': 1,
             'firmenname': '', 'vorname': 'Matthias', 'nachname': 'May',
             'geb_datum': '2010-03-01', 'adressen_id_adresse': 1,
             'kontakt_id_kontakt': None, 'nutzer_id_nutzer': None,
             'bemerkung': ''}],
        'stammdaten_has_stammrubrik': [
            {'stammdaten_id_stammdaten': 1, 'stammrubrik_id_stammrubrik': 1},
            {'stammdaten_id_stammdaten': 3, 'stammrubrik_id_stammrubrik': 2}],
        'beitragsrubrik': [{'id_beitragsrubrik': 12,
                            'beitragarchivrubrik': 'Aktuell'}],
        'bewertung': [{'id_bewertung': 2, 'bewertung': '++'}],
        'beitragsarchiv': [
            {'beitragsarchivnummer': 100, 'stammdaten_id_stammdaten': 2,
             'beitragstitel': '"Stendaler Telegramm" 02.03.2012 Nachrichten',
             'beitragsdauer': '00:05:00',
             'beitragarchivsrubrik_id_beitragsrubrik': 12,
             'fremdbeitrag': 'nein', 'austausch': 'ja',
             'bewertung_id_bewertung': 2, 'registriert_am': '0000-00-00',
             'freistellungserklaerung': 'C:/.../ORDNER_BEITRAG/',
             'kommentar': 'WO 09 FR', 'rausgeben': 'nein'},
            {'beitragsarchivnummer': 101, 'stammdaten_id_stammdaten': 999,
             'beitragstitel': '"00 OK DUMMY 01 1 MINUTE"',
             'beitragsdauer': '00:01:00',
             'beitragarchivsrubrik_id_beitragsrubrik': 11,
             'fremdbeitrag': 'ja', 'austausch': 'nein',
             'bewertung_id_bewertung': None, 'registriert_am': '2012-01-01',
             'freistellungserklaerung': '', 'kommentar': '',
             'rausgeben': None},
            {'beitragsarchivnummer': 102, 'stammdaten_id_stammdaten': 3,
             'beitragstitel': 'Monopoly Hindenburg', 'beitragsdauer': None,
             'beitragarchivsrubrik_id_beitragsrubrik': 12,
             'fremdbeitrag': 'ja', 'austausch': 'nein',
             'bewertung_id_bewertung': 0, 'registriert_am': '2012-02-01',
             'freistellungserklaerung': '', 'kommentar': '',
             'rausgeben': ''}],
        'archiv_dvd': [
            {'id_archiv_dvd': 1, 'beitragsarchivnummer': 100, 'dvd': 15},
            {'id_archiv_dvd': 2, 'beitragsarchivnummer': 0, 'dvd': 0}],
        'archiv_vhs': [
            {'id_archiv_vhs': 1, 'beitragsarchivnummer': 100, 'vhs': 7}],
        'startzeit': [{'id_startzeit': 1, 'startzeit': '20:15:00'}],
        'blocklaenge': [{'id_blocklaenge': 1, 'blocklaenge': '03:00:00'}],
        'sendeplanung': [
            {'id_sendeplanung': 1, 'sendedatum': '2012-03-02',
             'id_startzeit': 1, 'id_blocklaenge': 1},
            {'id_sendeplanung': 2, 'sendedatum': '2026-12-01',
             'id_startzeit': 1, 'id_blocklaenge': 1}],
        'beitragsarchiv_has_sendeplanung': [
            {'id_sendeplanung': 1, 'beitragsarchivnummer': 101,
             'sendefolgenummer': 1, 'neu': 'nein', 'id_zusatz': None},
            {'id_sendeplanung': 1, 'beitragsarchivnummer': 100,
             'sendefolgenummer': 2, 'neu': 'ja', 'id_zusatz': None},
            {'id_sendeplanung': 2, 'beitragsarchivnummer': 100,
             'sendefolgenummer': 1, 'neu': 'nein', 'id_zusatz': None}],
        'beitragsarchiv_has_sendeanzahl': [
            # same day as the plan -> no duplicate
            {'sendeanzahl_id_sendeanzahl': 1, 'beitragsarchivnummer': 100,
             'sendedatum': '2012-03-02', 'einzelgenehmigung': None},
            {'sendeanzahl_id_sendeanzahl': 2, 'beitragsarchivnummer': 100,
             'sendedatum': '2012-03-05', 'einzelgenehmigung': None},
            {'sendeanzahl_id_sendeanzahl': 3, 'beitragsarchivnummer': 100,
             'sendedatum': '3000-11-11', 'einzelgenehmigung': None}],
    }
    path = tmp_path / 'okdb.json'
    path.write_text(json.dumps({'tables': tables}), encoding='utf-8')
    return path


@pytest.mark.django_db
def test_import_okdb_stendal(tmp_path):
    """Full Stendal import with data cleanup."""
    from planung.models import TagesPlan
    dump = _okdb_dump(tmp_path)
    call_command('import_okdb_stendal', str(dump), '--with-tagesplan',
                 '--tagesplan-from', '2026-11-01',
                 '--report', str(tmp_path / 'r.csv'), stdout=io.StringIO())

    sophie = Profile.objects.get(first_name='Sophie')   # merged: only one
    assert sophie.okuser.email == 'sophie@example.de'
    assert not sophie.okuser.has_usable_password()
    assert sophie.birthday == date(1983, 2, 22)
    assert (sophie.street, sophie.house_number) == ('Frommhagenstr.', '32')
    assert sophie.phone_number == '03931/410884'
    assert sophie.verified
    assert 'Alt-DB-ID: 1, 2' in sophie.comment
    assert 'Gruppe: OK' in sophie.comment

    matthias = Profile.objects.get(first_name='Matthias')
    assert matthias.zipcode == '06128'
    assert matthias.birthday is None
    assert 'Fremdnutzer' in matthias.comment

    telegramm = License.objects.get(number=100)
    assert telegramm.title == 'Stendaler Telegramm'
    assert telegramm.subtitle == '02.03.2012 Nachrichten'
    assert telegramm.profile == sophie
    assert telegramm.category.name == 'Aktuell'
    assert telegramm.media_authority_exchange_allowed is True
    assert telegramm.external_production is False
    assert telegramm.confirmed
    # registration date missing -> first broadcast
    assert telegramm.created_at.astimezone(TZ).date() == date(2012, 3, 2)
    assert 'Kommentar: WO 09 FR' in telegramm.internal_note
    assert 'Bewertung: ++' in telegramm.internal_note
    assert sorted(str(m) for m in telegramm.archive_media.all()) == [
        'DVD 15', 'VHS cassette 7']

    broadcasts = sorted(
        c.broadcast_date.astimezone(TZ).replace(tzinfo=None).isoformat()
        for c in Contribution.objects.filter(license=telegramm))
    # dummy (1 min) runs first -> telegramm at 20:16; 3000-11-11 dropped
    assert broadcasts == ['2012-03-02T20:16:00', '2012-03-05T20:15:00',
                          '2026-12-01T20:15:00']

    dummy = License.objects.get(number=101)
    assert dummy.external_production is True
    assert dummy.profile.first_name == 'Unbekannt'
    assert not Contribution.objects.filter(license=dummy).exists()

    assert 'Dauer fehlte' in License.objects.get(number=102).internal_note

    plan = TagesPlan.objects.get(datum=date(2026, 12, 1))
    assert plan.json_plan['draft'] is True
    assert plan.json_plan['items'][0]['number'] == 100
    assert plan.json_plan['items'][0]['duration'] == 300

    # a second run must not duplicate anything
    with pytest.raises(Exception, match='not empty'):
        call_command('import_okdb_stendal', str(dump), stdout=io.StringIO())


@pytest.mark.django_db
def test_import_okdb_stendal_dry_run(tmp_path):
    """A dry run reports but leaves the database untouched."""
    out = io.StringIO()
    call_command('import_okdb_stendal', str(_okdb_dump(tmp_path)),
                 '--dry-run', stdout=out)
    assert 'licenses created: 3' in out.getvalue()
    assert not License.objects.exists()
    assert not OKUser.objects.filter(email='sophie@example.de').exists()


# --------------------------------------------------- sendearchiv import
def _sendearchiv(tmp_path):
    rows = [
        # matches by title + date + user
        [5, '2004-05-01', '18:05', 30, 'Gast aus Magdeburg', 'Teil 1', '',
         'Magdeburg', 'Offener Kanal', 'Magdeburg', 357, 'Raid 2',
         'Gastbeitrag', '', '', '', False],
        # same series title twice on other days -> only the right episode
        [6, '2010-01-08', '18:00', 12, 'Wochenschau', '', '', 'Treuter',
         'Klaus', 'Merseburg', 12, '140/84', 'Sonstiges', '', '', '', False],
        # title unknown -> reported, nothing changed
        [7, '2011-01-01', '18:00', 5, 'Gibt es nicht', '', '', 'Treuter',
         'Klaus', 'Merseburg', 13, '', 'Sonstiges', '', '', '', False],
        # no carrier -> ignored
        [8, '2011-01-01', '18:00', 5, 'Wochenschau', '', '', 'Treuter',
         'Klaus', 'Merseburg', 0, 'gelöscht', 'Sonstiges', '', '', '', False],
    ]
    html = ('<html><script>\nconst DATA = ' + json.dumps(rows)
            + ';\nconst X = 1;\n</script></html>')
    path = tmp_path / 'Sendearchiv.html'
    path.write_text(html, encoding='utf-8')
    return path


def _license(profile, title, number, day):
    lic = License.objects.create(
        profile=profile, title=title, number=number,
        duration=timedelta(minutes=10))
    Contribution.objects.create(
        license=lic, live=False,
        broadcast_date=datetime.combine(day, time(18), tzinfo=TZ))
    return lic


@pytest.mark.django_db
def test_import_sendearchiv_links_media(tmp_path):
    """DVD/tape numbers are attached to the matching existing licenses."""
    klaus = Profile.objects.create(first_name='Klaus', last_name='Treuter')
    ok_md = Profile.objects.create(first_name='OK', last_name='Magdeburg')
    gast = _license(ok_md, 'Gast aus Magdeburg', 9001, date(2004, 5, 1))
    week1 = _license(klaus, 'Wochenschau', 9002, date(2010, 1, 1))
    week2 = _license(klaus, 'Wochenschau', 9003, date(2010, 1, 8))
    licenses_before = License.objects.count()

    report = tmp_path / 'r.csv'
    out = io.StringIO()
    call_command('import_sendearchiv', str(_sendearchiv(tmp_path)),
                 '--report', str(report), stdout=out)

    assert License.objects.count() == licenses_before   # nothing created
    gast.refresh_from_db()
    assert gast.legacy_number == 5
    assert sorted(str(m) for m in gast.archive_media.all()) == [
        'DVD 357', 'Hard disk / RAID Raid 2']
    assert not week1.archive_media.exists()
    week2.refresh_from_db()
    assert week2.legacy_number == 6
    assert sorted(str(m) for m in week2.archive_media.all()) == [
        'Broadcast tape (Sendeband) 140/84', 'DVD 12']

    text = report.read_text(encoding='utf-8-sig')
    assert 'Titel nicht gefunden;7' in text
    assert 'Rows with DVD/tape: 3' in out.getvalue()

    # re-run: matched by legacy number, no duplicate media
    call_command('import_sendearchiv', str(_sendearchiv(tmp_path)),
                 stdout=io.StringIO())
    assert ArchiveMedium.objects.filter(license=week2).count() == 2


@pytest.mark.django_db
def test_import_sendearchiv_dry_run(tmp_path):
    """Dry run changes nothing."""
    klaus = Profile.objects.create(first_name='Klaus', last_name='Treuter')
    _license(klaus, 'Wochenschau', 9003, date(2010, 1, 8))
    call_command('import_sendearchiv', str(_sendearchiv(tmp_path)),
                 '--dry-run', stdout=io.StringIO())
    assert not ArchiveMedium.objects.exists()
    assert not License.objects.filter(legacy_number__isnull=False).exists()
