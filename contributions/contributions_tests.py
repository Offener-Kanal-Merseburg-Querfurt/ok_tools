from .admin import ContributionAdmin
from .admin import ContributionResource
from .admin import PrimaryFilter
from .admin import ProgramResource
from .admin import WeekFilter
from .admin import YearFilter
from .disa_import import _check_title
from .disa_import import disa_import
from .disa_import import validate
from .models import Contribution
from .models import ContributionManager
from .models import DisaImport
from datetime import datetime
from datetime import time
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files import File
from django.urls import reverse_lazy
from freezegun import freeze_time
from ok_tools.datetime import TZ
from ok_tools.testing import DOMAIN
from ok_tools.testing import EMAIL
from ok_tools.testing import PWD
from ok_tools.testing import _open
from ok_tools.testing import create_contribution
from ok_tools.testing import create_disaimport
from ok_tools.testing import create_license
from ok_tools.testing import create_user
from unittest.mock import patch
import pytest


User = get_user_model()

CONTRIBUTION_URL = f'{DOMAIN}{reverse_lazy("contributions:contributions")}'


def con_change_url(id: int) -> str:
    """Create the change url for the given id."""
    url = reverse_lazy("admin:contributions_contribution_change", args=[id])
    return (f'{DOMAIN}'f'{url}')


A_CON_URL = (f'{DOMAIN}'
             f'{reverse_lazy("admin:contributions_contribution_changelist")}')
DISA_CREATE_URL = (f'{DOMAIN}'
                   f'{reverse_lazy("admin:contributions_disaimport_add")}')
DISA_URL = (f'{DOMAIN}'
            f'{reverse_lazy("admin:contributions_disaimport_changelist")}')

XLSX_CT = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def disa_url_change(id: int) -> str:
    """Create the change url for the given id."""
    url = reverse_lazy("admin:contributions_disaimport_change", args=[id])
    return (f'{DOMAIN}'f'{url}')


def _raises(match):
    return pytest.raises(ValidationError, match=match)


def test__contributions__admin__ContributionsAdmin__1(browser, contribution):
    """Contributions get shown in the admin interface."""
    browser.login_admin()
    browser.open(A_CON_URL)

    assert str(contribution) in browser.contents
    assert contribution.license.profile.first_name in browser.contents
    assert contribution.license.profile.last_name in browser.contents


def test__contributions__view__ListContributionsView__1(
        browser, contribution_dict, license):
    """A user can see his/her contributions."""
    con1 = create_contribution(license, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022, month=9, day=12, hour=12, tzinfo=TZ)
    con2 = create_contribution(license, contribution_dict)

    browser.login()
    browser.open(CONTRIBUTION_URL)

    assert str(con1) in browser.contents
    assert str(con2) in browser.contents


def test__contributions__view__ListContributionsView__2(browser):
    """If the user doesn't have a profile, no contribution is shown."""
    User.objects.create_user(email=EMAIL, password=PWD)
    browser.login()
    browser.open(CONTRIBUTION_URL)

    assert 'No contributions yet' in browser.contents


def test__contributions__view__ListContributionsView__3(
        browser, contribution, user_dict):
    """Only the own contributions are shown to the user."""
    user_dict['email'] = f'new_{EMAIL}'
    user2 = create_user(user_dict)

    browser.login(email=user2.email)
    browser.open(CONTRIBUTION_URL)

    assert str(contribution) not in browser.contents
    assert 'No contributions yet' in browser.contents


def test__contributions__admin__ContributionsAdmin__4(
        db, license, contribution_dict, browser):
    """Show primary contributions as those."""
    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=8,
        tzinfo=TZ,
    )
    early_contr = create_contribution(license, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=18,
        tzinfo=TZ,
    )
    late_contr = create_contribution(license, contribution_dict)

    browser.login_admin()

    browser.open(con_change_url(early_contr.id))
    assert 'alt="True"' in browser.contents

    browser.open(con_change_url(late_contr.id))
    assert 'alt="False"' in browser.contents


def test__contributions__models__1(db, license, contribution_dict):
    """Mark the primary contribution."""
    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=8,
        tzinfo=TZ,
    )
    early_contr = create_contribution(license, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=18,
        tzinfo=TZ,
    )
    late_contr = create_contribution(license, contribution_dict)

    assert early_contr.is_primary()
    assert not late_contr.is_primary()


def test__contributions__models__ContributionManager__1(
        db, license, contribution_dict):
    """Get a list of all ids from primary contributions."""
    primary = set()
    repetitions = set()

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=8,
        tzinfo=TZ,
    )
    primary.add(create_contribution(license, contribution_dict))

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=18,
        tzinfo=TZ,
    )
    repetitions.add(create_contribution(license, contribution_dict))

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=18,
        tzinfo=TZ,
    )
    repetitions.add(create_contribution(license, contribution_dict))

    contributions = repetitions.union(primary)
    primary_ids = ContributionManager().primary_contributions(contributions)
    repetition_ids = ContributionManager().repetitions(contributions)
    assert primary == {Contribution.objects.get(id=id) for id in primary_ids}
    assert repetitions == {Contribution.objects.get(
        id=id) for id in repetition_ids}


def test__contributions__disa_import__validate__1(browser):
    """It is possible to upload a valid DISA export file."""
    browser.login_admin()
    browser.open(DISA_CREATE_URL)

    with _open('valid.xlsx') as file:
        browser.getControl(
            'DISA export file').add_file(file, XLSX_CT, 'test.xlsx')

    browser.getControl(name='_save').click()

    assert 'added successfully' in browser.contents
    assert DisaImport.objects.filter()


def test__contributions__disa_import__validate__2():
    """The file needs to have the right column names."""
    with _raises(r'.*Anfang.*Ende.*Länge.*Titel.*Typ'):
        with _open('invalid_header.xlsx') as f:
            validate(f)


def test__contributions__disa_import__validate__3():
    """The Worksheet needs the right name."""
    with _raises(r'.*Auftragsfenster.*'):
        with _open('wrong_ws.xlsx') as f:
            validate(f)


def test__contributions__disa_import__validate__5():
    """Files with an invalid title are not valid."""
    with _raises(r'.*Title needs the format <nr>_<title>.*'):
        with _open('invalid_number.xlsx') as f:
            validate(f)


def test__contributions__disa_import__1(db, mocked_request, license):
    """Import a contribution from DISA export."""
    with _open('valid.xlsx') as f:
        disa_import(mocked_request, f)

    assert Contribution.objects.filter()


def test__contributions__disa_import__2(db, mocked_request, license):
    """Do not create duplicated contributions."""
    with _open('double.xlsx') as f:
        disa_import(mocked_request, f)

    assert len(Contribution.objects.filter()) == 1


def test__contributions__disa_import__3(db, mocked_request, license):
    """Ignore everything after a blank line."""
    with _open('blank_line.xlsx') as f:
        disa_import(mocked_request, f)

    assert len(Contribution.objects.filter()) == 1


def test__contributions__disa_import__4(browser, disaimport):
    """Show an error message if no license exits."""
    browser.login_admin()
    browser.open(disa_url_change(disaimport.id))
    browser.getControl(name='_import_disa').click()

    assert not Contribution.objects.filter()
    assert 'No license with number 1 found.' in browser.contents


def test__contributions__disa_import__5(browser, db, license):
    """Don't import repetitions if no repetitions are allowed."""
    license.repetitions_allowed = False
    license.save()

    disaimport = DisaImport()
    with _open('repetitions.xlsx') as f:
        disaimport.file.save('test.xlsx', File(f), save=True)
    disaimport.save()

    browser.login_admin()
    browser.open(disa_url_change(disaimport.id))
    browser.getControl(name='_import_disa').click()

    assert len(Contribution.objects.filter(license=license)) == 1
    assert 'No repetitions for number 1 allowed' in browser.contents


def test__contributions__disa_import__6(db, mocked_request, license):
    """Update contributions with another import."""
    with _open('valid.xlsx') as f:
        disa_import(mocked_request, f)

    assert len(Contribution.objects.filter()) == 1

    with _open('valid_update.xlsx') as f:
        disa_import(mocked_request, f)

    assert len(Contribution.objects.filter()) == 2

    contributions = Contribution.objects.filter().order_by('broadcast_date')
    assert (contributions[0].broadcast_date ==
            datetime(2022, 9, 8, 9, 30, tzinfo=TZ))
    assert (contributions[1].broadcast_date ==
            datetime(2022, 9, 8, 10, 30, tzinfo=TZ))


def test__contributions__disa_import___check_title():
    """Check the title for a valid format."""
    assert _check_title('3_title', '')
    assert _check_title('test', 'Infoblock')
    assert _check_title('Trailertest', '')
    assert _check_title('Programmvorschau_test', '')

    assert not _check_title('3title', '')
    assert not _check_title('2022Trailer', '')


def test__contributions__admin__1(browser, db, license):
    """Import multiple DISA export files."""
    # create 3 DISA export files
    for _ in range(3):
        create_disaimport()

    browser.login_admin()
    browser.open(DISA_URL)
    for i in range(3):
        # select all disaimports
        browser.getControl(name='_selected_action').controls[i].click()
    browser.getControl('Action').value = 'import_files'
    browser.getControl('Go').click()

    assert '3 files successfully imported.' in browser.contents
    assert Contribution.objects.filter()


def test__contributions__admin__2(browser, disaimport):
    """Just mark a DISA export file as imported."""
    browser.login_admin()
    browser.open(disa_url_change(disaimport.id))

    browser.getControl('Imported').click()

    browser.getControl(name=('_save')).click()

    assert DisaImport.objects.get(id=disaimport.id).imported
    assert not Contribution.objects.filter()


def test__contributions__admin__PrimaryFilter__1(
        db, browser, license, contribution_dict):
    """Filter by primary contributions."""
    contribution_dict['broadcast_date'] = datetime(
        year=2020,
        month=9,
        day=12,
        hour=8,
        tzinfo=TZ,
    )
    primary = create_contribution(license, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2021,
        month=9,
        day=12,
        hour=20,
        tzinfo=TZ,
    )
    repetition1 = create_contribution(license, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=22,
        tzinfo=TZ,
    )
    repetition2 = create_contribution(license, contribution_dict)

    browser.login_admin()
    browser.open(A_CON_URL)
    browser.follow('Yes')
    result = browser.contents

    assert str(primary.broadcast_date.year) in result
    assert str(repetition1.broadcast_date.year) not in result
    assert str(repetition2.broadcast_date.year) not in result

    browser.follow('No')
    result = browser.contents
    assert str(primary.broadcast_date.year) not in result
    assert str(repetition1.broadcast_date.year) in result
    assert str(repetition2.broadcast_date.year) in result


def test__contributions__admin__PrimaryFileter__2():
    """Handle invalid values."""
    with patch.object(PrimaryFilter, 'value', return_value='invalid'):
        with pytest.raises(ValueError, match=r'Invalid value .*'):
            filter = PrimaryFilter(
                {}, {}, Contribution, ContributionAdmin)
            filter.queryset(None, None)


def test__contributions__admin__YearFilter__1(
        browser, user, license_dict, contribution_dict):
    """Filter contributions after year."""
    license_dict['title'] = 'new_title'
    lr1 = create_license(user.profile, license_dict)

    contribution_dict['broadcast_date'] = datetime(
        day=8, month=9, year=datetime.now().year, tzinfo=TZ)
    contr1 = create_contribution(lr1, contribution_dict)

    license_dict['title'] = 'old_title'
    lr2 = create_license(user.profile, license_dict)

    contribution_dict['broadcast_date'] = datetime(
        day=8, month=9, year=datetime.now().year-1, tzinfo=TZ)
    contr2 = create_contribution(lr2, contribution_dict)

    browser.login_admin()
    browser.open(A_CON_URL)

    browser.follow('This year')
    assert str(contr1) in browser.contents
    assert str(contr2) not in browser.contents

    browser.follow('Last year')
    assert str(contr1) not in browser.contents
    assert str(contr2) in browser.contents


def test__contributions__admin__YearFilter__2():
    """Handle invalid values."""
    with patch.object(YearFilter, 'value', return_value='invalid'):
        with pytest.raises(ValueError, match=r'Invalid value .*'):
            filter = YearFilter(
                {}, {}, Contribution, ContributionAdmin)
            filter.queryset(None, None)


def test__contributions__admin__ContributionResource__1(
        browser, license, contribution_dict):
    """Export primary contributions only."""
    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=20,
        hour=9,
        tzinfo=TZ,
    )
    contr1 = create_contribution(license, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=21,
        hour=18,
        tzinfo=TZ,
    )
    contr2 = create_contribution(license, contribution_dict)

    assert contr1.is_primary()
    assert not contr2.is_primary()

    browser.login_admin()
    browser.open(A_CON_URL)

    browser.follow('Export')
    browser.getControl('Data export').click()
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    assert str(contr1.broadcast_date.date()) in str(browser.contents)
    assert str(contr2.broadcast_date.date()) not in str(browser.contents)


def test__contributions__admin__ContributionResource__2(db):
    """Export with no given queryset."""
    ContributionResource().export(None, None)


def test__contributions__admin__ContributionResource__3(
        browser, license, contribution_dict):
    """Export the broadcast date with the right timezone."""
    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=20,
        hour=0,
        tzinfo=TZ,
    )
    contr1 = create_contribution(license, contribution_dict)
    browser.login_admin()
    browser.open(A_CON_URL)

    browser.follow('Export')
    browser.getControl('Data export').click()
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    assert str(contr1.broadcast_date.date()) in str(browser.contents)
    assert str(contr1.broadcast_date.time()) in str(browser.contents)


def test__contributions__admin__ContributionResource__4(
        browser, license, contribution_dict):
    """All necessary data are included in the export."""
    license.subtitle = 'subtitle'
    license.save()
    contr = create_contribution(license, contribution_dict)

    browser.login_admin()
    browser.open(A_CON_URL)

    browser.follow('Export')
    browser.getControl('Data export').click()
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    export = str(browser.contents)

    assert str(license.number) in export
    assert license.title in export
    assert license.subtitle in export
    assert str(license.duration) in export
    assert (f'{license.profile.first_name} {license.profile.last_name}'
            in export)
    assert str(contr.live) in export


def test__contributions__admin__ProgramResource__1(
        browser, license_dict, user, contribution_dict):
    """Export the programm."""
    license_dict['title'] = 'first_title'
    license_dict['duration'] = timedelta(hours=1, minutes=30)
    license1 = create_license(user.profile, license_dict)

    contribution_dict['broadcast_date'] = datetime(2022, 9, 28, 9, tzinfo=TZ)
    contr1 = create_contribution(license1, contribution_dict)

    license_dict['title'] = 'second_title'
    license2 = create_license(user.profile, license_dict)

    contribution_dict['broadcast_date'] = datetime(
        2022, 9, 28, 10, 30, tzinfo=TZ)
    contr2 = create_contribution(license2, contribution_dict)

    # gabs with one minute or less get ignored
    contribution_dict['broadcast_date'] = datetime(
        2022, 9, 28, 12, 1, tzinfo=TZ)
    contr3 = create_contribution(license1, contribution_dict)

    browser.login_admin()
    browser.open(A_CON_URL)

    browser.follow('Export')
    browser.getControl('Program').click()
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'

    assert str(contr1.broadcast_date.time()) in str(browser.contents)
    assert (str((contr1.broadcast_date + license1.duration).time())
            in str(browser.contents))
    assert license1.title in str(browser.contents)

    assert str(contr2.broadcast_date.time()) in str(browser.contents)
    assert (str((contr2.broadcast_date + license2.duration).time())
            in str(browser.contents))
    assert license2.title in str(browser.contents)

    assert str(contr3.broadcast_date.time()) in str(browser.contents)
    assert (str((contr3.broadcast_date + license2.duration).time())
            in str(browser.contents))

    assert str(time(hour=0, minute=0)) in str(browser.contents)
    assert 'Infoblock' in str(browser.contents)


def test__contributions__admin__ProgramResource__2(db):
    """Export with no given queryset."""
    ProgramResource().export(None, None)


@freeze_time("2022-06-15")
def test__contributions__admin__WeekFilter__1(
        browser, user, license_dict, contribution_dict):
    """Filter contributions are filterable after their broadcast week."""
    now = datetime.now()
    week = now.date().isocalendar().week
    year = now.year

    license_dict['title'] = 'This week'
    license1 = create_license(user.profile, license_dict)
    bc_date = datetime.fromisocalendar(year, week, 1)
    contribution_dict['broadcast_date'] = bc_date.replace(tzinfo=TZ)
    contr1 = create_contribution(license1, contribution_dict)

    license_dict['title'] = 'Next week'
    license2 = create_license(user.profile, license_dict)
    bc_date = datetime.fromisocalendar(year, week+1, 1)
    contribution_dict['broadcast_date'] = bc_date.replace(tzinfo=TZ)
    contr2 = create_contribution(license2, contribution_dict)

    license_dict['title'] = 'After next week'
    license3 = create_license(user.profile, license_dict)
    bc_date = datetime.fromisocalendar(year, week+2, 1)
    contribution_dict['broadcast_date'] = bc_date.replace(tzinfo=TZ)
    contr3 = create_contribution(license3, contribution_dict)

    license_dict['title'] = 'Far away'
    license4 = create_license(user.profile, license_dict)
    bc_date = datetime.fromisocalendar(year, week+3, 1)
    contribution_dict['broadcast_date'] = bc_date.replace(tzinfo=TZ)
    contr4 = create_contribution(license4, contribution_dict)

    browser.login_admin()
    browser.open(A_CON_URL)

    browser.follow('In this week')
    assert contr1.license.title in browser.contents
    assert contr2.license.title not in browser.contents
    assert contr3.license.title not in browser.contents
    assert contr4.license.title not in browser.contents

    browser.follow('Until next week')
    assert contr1.license.title in browser.contents
    assert contr2.license.title in browser.contents
    assert contr3.license.title not in browser.contents
    assert contr4.license.title not in browser.contents

    browser.follow('Until week after next')
    assert contr1.license.title in browser.contents
    assert contr2.license.title in browser.contents
    assert contr3.license.title in browser.contents
    assert contr4.license.title not in browser.contents


def test__contributions__admin__WeekFilter__2():
    """Handle invalid values."""
    with patch.object(WeekFilter, 'value', return_value='invalid'):
        with pytest.raises(ValueError, match=r'Invalid value .*'):
            filter = WeekFilter(
                {}, {}, Contribution, ContributionAdmin)
            filter.queryset(None, None)
