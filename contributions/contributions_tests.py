from .admin import ContributionAdmin
from .admin import ContributionResource
from .admin import YearFilter
from .disa_import import disa_import
from .disa_import import validate
from .models import Contribution
from .models import DisaImport
from datetime import datetime
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files import File
from django.urls import reverse_lazy
from licenses.models import default_category
from ok_tools.testing import DOMAIN
from ok_tools.testing import EMAIL
from ok_tools.testing import PWD
from ok_tools.testing import TZ
from ok_tools.testing import _open
from ok_tools.testing import create_contribution
from ok_tools.testing import create_disaimport
from ok_tools.testing import create_license_request
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
        browser, contribution_dict, license_request):
    """A user can see his/her contributions."""
    con1 = create_contribution(license_request, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022, month=9, day=12, hour=12, tzinfo=TZ)
    con2 = create_contribution(license_request, contribution_dict)

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
        db, license_request, contribution_dict, browser):
    """Show primary contributions as those."""
    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=8,
        tzinfo=TZ,
    )
    early_contr = create_contribution(license_request, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=18,
        tzinfo=TZ,
    )
    late_contr = create_contribution(license_request, contribution_dict)

    browser.login_admin()

    browser.open(con_change_url(early_contr.id))
    assert 'alt="True"' in browser.contents

    browser.open(con_change_url(late_contr.id))
    assert 'alt="False"' in browser.contents


def test__contributions__models__1(db, license_request, contribution_dict):
    """Mark the primary contribution."""
    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=8,
        tzinfo=TZ,
    )
    early_contr = create_contribution(license_request, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=12,
        hour=18,
        tzinfo=TZ,
    )
    late_contr = create_contribution(license_request, contribution_dict)

    assert early_contr.is_primary()
    assert not late_contr.is_primary()


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


def test__contributions__disa_import__validate__4():
    """Files without a blank line after the header are not valid."""
    with _raises(r'.*is not empty.*'):
        with _open('no_blank.xlsx') as f:
            validate(f)


def test__contributions__disa_import__validate__5():
    """Files with an invalid title are not valid."""
    with _raises(r'.*Title needs the format <nr>_<title>.*'):
        with _open('invalid_number.xlsx') as f:
            validate(f)


def test__contributions__disa_import__1(db, license_request):
    """Import a contribution from DISA export."""
    with _open('valid.xlsx') as f:
        disa_import(None, f)

    assert Contribution.objects.filter()


def test__contributions__disa_import__2(db, license_request):
    """Do not create duplicated contributions."""
    with _open('double.xlsx') as f:
        disa_import(None, f)

    assert len(Contribution.objects.filter()) == 1


def test__contributions__disa_import__3(db, license_request):
    """Ignore everything after a blank line."""
    with _open('blank_line.xlsx') as f:
        disa_import(None, f)

    assert len(Contribution.objects.filter()) == 1


def test__contributions__disa_import__4(browser, disaimport):
    """Show an error message if no license exits."""
    browser.login_admin()
    browser.open(disa_url_change(disaimport.id))
    browser.getControl(name='_import_disa').click()

    assert not Contribution.objects.filter()
    assert 'No license with number 1 found.' in browser.contents


def test__contributions__disa_import__5(browser, db, license_request):
    """Don't import repetitions if no repetitions are allowed."""
    license_request.repetitions_allowed = False
    license_request.save()

    disaimport = DisaImport()
    with _open('repetitions.xlsx') as f:
        disaimport.file.save('test.xlsx', File(f), save=True)
    disaimport.save()

    browser.login_admin()
    browser.open(disa_url_change(disaimport.id))
    browser.getControl(name='_import_disa').click()

    assert len(Contribution.objects.filter(license=license_request)) == 1
    assert 'No repetitions for number 1 allowed' in browser.contents


def test__contributions__disa_import__6(db, license_request):
    """Update contributions with another import."""
    with _open('valid.xlsx') as f:
        disa_import(None, f)

    assert len(Contribution.objects.filter()) == 1

    with _open('valid_update.xlsx') as f:
        disa_import(None, f)

    assert len(Contribution.objects.filter()) == 2

    contributions = Contribution.objects.filter().order_by('broadcast_date')
    assert (contributions[0].broadcast_date ==
            datetime(2022, 9, 8, 9, 30, tzinfo=TZ))
    assert (contributions[1].broadcast_date ==
            datetime(2022, 9, 8, 10, 30, tzinfo=TZ))


def test__contributions__admin__1(browser, db, license_request):
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


def test__contributions__admin__YearFilter__1(
        browser, user, license_template_dict, contribution_dict):
    """Filter contributions after year."""
    license_template_dict['title'] = 'new_title'
    lr1 = create_license_request(
        user.profile, default_category(), license_template_dict)

    contribution_dict['broadcast_date'] = datetime(
        day=8, month=9, year=datetime.now().year, tzinfo=TZ)
    contr1 = create_contribution(lr1, contribution_dict)

    license_template_dict['title'] = 'old_title'
    lr2 = create_license_request(
        user.profile, default_category(), license_template_dict)

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
        browser, license_request, contribution_dict):
    """Export primary contributions only."""
    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=20,
        hour=9,
        tzinfo=TZ,
    )
    contr1 = create_contribution(license_request, contribution_dict)

    contribution_dict['broadcast_date'] = datetime(
        year=2022,
        month=9,
        day=21,
        hour=18,
        tzinfo=TZ,
    )
    contr2 = create_contribution(license_request, contribution_dict)

    assert contr1.is_primary()
    assert not contr2.is_primary()

    browser.login_admin()
    browser.open(A_CON_URL)

    browser.follow('Export')
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    assert str(contr1.broadcast_date.date()) in str(browser.contents)
    assert str(contr2.broadcast_date.date()) not in str(browser.contents)


def test__contributions__admin__ContributionResource__2(db):
    """Export with no given queryset."""
    ContributionResource().export(None, None)
