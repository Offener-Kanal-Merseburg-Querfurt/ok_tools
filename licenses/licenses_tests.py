from .admin import DurationFilter
from .admin import LicenseAdmin
from .admin import YearFilter
from .models import License
from .models import default_category
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from ok_tools.datetime import TZ
from ok_tools.testing import DOMAIN
from ok_tools.testing import EMAIL
from ok_tools.testing import PWD
from ok_tools.testing import create_license
from ok_tools.testing import create_user
from ok_tools.testing import pdfToText
from registration.models import Profile
from unittest.mock import patch
from urllib.error import HTTPError
import datetime
import pytest


User = get_user_model()

HOME_URL = f'{DOMAIN}{reverse_lazy("home")}'
LIST_URL = f'{DOMAIN}{reverse_lazy("licenses:licenses")}'
CREATE_URL = f'{DOMAIN}{reverse_lazy("licenses:create")}'
LOGIN_URL = f'{DOMAIN}{reverse_lazy("login")}'
A_LICENSE_URL = (f'{DOMAIN}'
                 f'{reverse_lazy("admin:licenses_license_changelist")}')


def details_url(id):
    """Return details url."""
    return f'{DOMAIN}{reverse_lazy("licenses:details", args=[id])}'


def edit_url(id):
    """Return edit url."""
    return f'{DOMAIN}{reverse_lazy("licenses:update", args=[id])}'


def print_url(id):
    """Return print url."""
    return f'{DOMAIN}{reverse_lazy("licenses:print", args=[id])}'


def test__licenses__views__ListLicensesView__1(browser, user):
    """A logged in user can access his/her licenses overview."""
    browser.login()
    browser.open(HOME_URL)
    browser.follow('Licenses')
    browser.follow('Overview')

    assert LIST_URL == browser.url
    assert 'Your licenses' in browser.contents


def test__licenses__views__ListLicensesView__2(browser):
    """If no user is logged in the license overview returns a 404."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(LIST_URL)


def test__licenses__views__ListLicensesView__3(db, browser, license):
    """All licenses of the user are listed."""
    browser.login()
    browser.open(LIST_URL)

    assert str(license) in browser.contents
    assert 'No' in browser.contents  # the License is not confirmed


def test__licenses__views__ListLicensesView__4(browser, license):
    """If a LR is confirmed, it is shown in the overview."""
    license.confirmed = True
    license.save()
    browser.login()
    browser.open(LIST_URL)

    assert str(license) in browser.contents
    assert 'Yes' in browser.contents  # the License is confirmed


def test__licenses__views__ListLicensesView__5(browser, user, license):
    """It is possible to edit a license from the list view."""
    browser.login()
    browser.open(LIST_URL)
    browser.follow(id=f'id_edit_{license.id}')

    assert browser.url == edit_url(license.id)


def test__licenses__views__ListLicensesView__6(browser, user, license):
    """It is possible to print a license from the list view."""
    browser.login()
    browser.open(LIST_URL)
    browser.follow(id=f'id_print_{license.id}')

    assert browser.url == print_url(license.id)


def test__licenses__views__ListLicensesView__7(browser):
    """A user without a profile can not see any LRs."""
    User.objects.create_user(email=EMAIL, password=PWD)
    browser.login()
    browser.open(LIST_URL)

    assert 'No licenses yet.' in browser.contents


def test__licenses__views__DetailsLicensesView__1(browser, license):
    """If no user is logged in the details view returns a 404."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(details_url(license.id))


def test__licenses__views__DetailsLicensesView__2(browser, license):
    """The details view can be reached using the Overview."""
    browser.login()
    browser.open(LIST_URL)
    browser.follow(str(license))

    assert f'Details for {str(license)}' in browser.contents
    assert license.description in browser.contents


def test__licenses__views__DetailsLicensesView__3(browser, license):
    """It is possible to edit a LR over the details view."""
    browser.login()
    browser.open(details_url(license.id))
    browser.follow(id='id_edit_LR')

    assert f'Edit {license}:' in browser.contents


def test__licenses__views__UpdateLicensesView__1(browser, license):
    """The Description can be changed using the edit site."""
    browser.login()
    browser.open(edit_url(license.id))

    new_description = "This is the new description."
    browser.getControl('Description').value = new_description
    browser.getControl('Save').click()

    assert License.objects.get(description=new_description)
    assert browser.url == LIST_URL
    assert 'successfully edited.' in browser.contents


def test__licenses__views__UpdateLicensesView__2(browser, license):
    """It is not possible to edit a confirmed LR."""
    license.confirmed = True
    license.save()

    browser.login()
    browser.open(edit_url(license.id))

    assert 'Your License is already confirmed and no longer editable.'\
        in browser.contents


def test__licenses__views__UpdateLicensesView__3(browser, license):
    """Even if the form is still available, a confirmed LR is not editable."""
    browser.login()
    browser.open(edit_url(license.id))

    license.confirmed = True
    license.save()

    old_description = license.description
    browser.getControl('Description').value = "This is the new description."
    browser.getControl('Save').click()

    assert 'is already confirmed and therefor no longer editable.'\
        in browser.contents
    lr = License.objects.get(id=license.id)
    assert lr.description == old_description


def test__licenses__views__UpdateLicensesView__4(browser, license):
    """After a license was changed to a screen board, the duration is fixed."""
    browser.login()
    browser.open(edit_url(license.id))

    browser.getControl('Screen Board').click()
    browser.getControl('Save').click()

    assert (License.objects.get(id=license.id).duration ==
            datetime.timedelta(seconds=settings.SCREEN_BOARD_DURATION))


def test__licenses__views__CreateLicenseView__1(browser, user):
    """A logged in user can access the create site."""
    browser.login()
    browser.open(HOME_URL)
    open('response.html', 'w').write(browser.contents)
    browser.follow('Create license')

    assert CREATE_URL == browser.url
    assert 'Create a license' in browser.contents


def test__licenses__views__CreateLicenseView__2(browser):
    """If no user is logged in the create site returns a 404."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(CREATE_URL)


def test__licenses__views__CreateLicenseView__3(browser, user):
    """A user can create a license."""
    browser.login()
    title = 'Test License'

    browser.open(CREATE_URL)
    browser.getControl('Title').value = title
    browser.getControl('Description').value = 'This is a Test.'
    browser.getControl('Duration').value = '00:00:10'
    browser.getControl('Save').click()

    assert LIST_URL == browser.url
    assert 'Your licenses' in browser.contents
    assert 'successfully created' in browser.contents
    assert License.objects.get(title=title)


def test__licenses__views__CreateLicenseView__4(browser, user):
    """A license needs a Title."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Description').value = 'This is a Test.'
    browser.getControl('Duration').value = '00:00:10'
    browser.getControl('Save').click()

    assert CREATE_URL == browser.url
    assert 'This field is required' in browser.contents
    assert not License.objects.filter()


def test__licenses__views__CreateLicenseView__5(
        db, browser, user, license_dict):
    """A license representing a Screen Board has a fixed duration."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Title').value = license_dict['title']
    browser.getControl(
        'Description').value = license_dict['description']
    browser.getControl('Screen Board').click()
    browser.getControl('Save').click()

    assert (lr := License.objects.get(
        title=license_dict['title']))
    assert lr.duration == datetime.timedelta(
        seconds=settings.SCREEN_BOARD_DURATION)


def test__licenses__views__CreateLicenseView__6(browser):
    """It is not possible to create a LR without a Profile."""
    User.objects.create_user(email=EMAIL, password=PWD)
    browser.login()
    browser.open(CREATE_URL)
    assert 'There is no profile' in browser.contents


def test__licenses__forms__CreateLicenseForm__1(
        browser, user, license_dict):
    """A LR needs a duration or needs to be a Screen Board."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Title').value = license_dict['title']
    browser.getControl(
        'Description').value = license_dict['description']
    browser.getControl('Save').click()

    assert 'The duration field is required.' in browser.contents
    assert not License.objects.filter()


def test__licenses__forms__CreateLicenseForm__2(
        browser, user, license_dict):
    """The duration field gets validated."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Title').value = license_dict['title']
    browser.getControl(
        'Description').value = license_dict['description']
    browser.getControl('Duration').value = 'invalid00:01:20'
    browser.getControl('Save').click()

    assert ('Invalid format. Please use the format hh:mm:ss or mm:ss.'
            in browser.contents)


def test__licenses__forms__CreateLicenseForm__3(
        browser, user, license_dict):
    """The duration field can have the input format mm:ss."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Title').value = license_dict['title']
    browser.getControl(
        'Description').value = license_dict['description']
    browser.getControl('Duration').value = '30:20'
    browser.getControl('Save').click()

    assert (License.objects.get(
            title=license_dict['title']).duration ==
            datetime.timedelta(minutes=30, seconds=20))


def test__licenses__models__1(
        browser, user, license, license_dict):
    """
    String representation.

    A License gets represented by its title and subtitle.
    A Category get represented by its name.
    """
    browser.login()
    subtitle = 'Test Subtitle'
    license_dict['subtitle'] = subtitle
    license_with_subtitle = create_license(user.profile, license_dict)

    assert str(license) == license.title
    assert str(license_with_subtitle) in str(license_with_subtitle)
    assert license.category.__str__() == default_category().name


def test__licenses__models__2(
        db, license, license_dict, user):
    """Each new LR gets a unique, visible number."""
    lr1 = license
    lr2 = create_license(user.profile, license_dict)

    assert lr1.number == 1
    assert lr2.number == 2


def test__licenses__models__3(db, license):
    """The LR number always stays the same."""
    n1 = license.number
    license.subtitle = 'new_subtitle'
    license.save()
    n2 = license.number

    assert n1 == n2


def test__licenses__models__4(browser, license_dict, user):
    """A new LR must have a duration greater zero."""
    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow('Add License')

    browser.getControl('Title').value = license_dict['title']
    browser.getControl(
        'Description').value = license_dict['description']
    browser.getControl('Duration').value = '00:00'
    browser.getControl(str(user.profile)).click()  # select user

    browser.getControl(name='_save').click()

    assert 'Duration must not be null.' in browser.contents


def test__licenses__generate_file__1(browser, user, license):
    """The printed license contains the necessary data."""
    browser.login()
    browser.open(details_url(license.id))
    browser.follow(id='id_print_LR')

    assert browser.headers['Content-Type'] == 'application/pdf'
    pdftext = pdfToText(browser.contents)
    assert user.email in pdftext
    assert license.title in pdftext
    assert 'x' in pdftext


def test__licenses__views__FilledLicenseFile__1(browser, license):
    """If no user is logged in the site returns a 404."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(print_url(license.id))


def test__licenses__views__FilledLicenseFile__2(db, user, browser):
    """Try printing a not existing LR produces an error message."""
    browser.login()
    browser.open(print_url(1))

    assert browser.url == LIST_URL
    assert 'License not found.' in browser.contents


def test__licenses__views__FilledLicenseFile__3(
        browser, user, user_dict, license, license_dict):
    """A LR from another user can not be printed."""
    user_dict['email'] = f'new_{user_dict["email"]}'
    second_user = create_user(user_dict)
    second_lr = create_license(second_user.profile, license_dict)

    browser.login()  # login with user
    browser.open(print_url(second_lr.id))

    assert browser.url == LIST_URL
    assert 'License not found.' in browser.contents


def test__licenses__admin__LicenseAdmin__1(
        browser, user, license, license_dict):
    """Confirm multiple LRs."""
    license.confirmed = True
    license.save()
    for _ in range(3):
        create_license(user.profile, license_dict)

    browser.login_admin()
    browser.open(A_LICENSE_URL)
    for i in range(4):
        # select all LRs
        browser.getControl(name='_selected_action').controls[i].click()
    browser.getControl('Action').value = 'confirm'
    browser.getControl('Go').click()

    assert ('3 Licenses were successfully confirmed.'
            in browser.contents)
    for lr in License.objects.filter():
        assert lr.confirmed


def test__licenses__admin__LicenseAdmin__2(
        browser, user, license, license_dict):
    """Unconfirm multiple LRs."""
    license.save()
    for _ in range(3):
        lr = create_license(user.profile, license_dict)
        lr.confirmed = True
        lr.save()

    browser.login_admin()
    browser.open(A_LICENSE_URL)
    for i in range(4):
        # select all LRs
        browser.getControl(name='_selected_action').controls[i].click()
    browser.getControl('Action').value = 'unconfirm'
    browser.getControl('Go').click()

    assert ('3 Licenses were successfully unconfirmed.'
            in browser.contents)
    for lr in License.objects.filter():
        assert not lr.confirmed


def test__licenses__admin__LicenseAdmin__3(browser, license):
    """Try to edit an confirmed License."""
    license.confirmed = True
    license.save()

    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow(license.title)

    assert 'Confirmed licenses are not editable!' in browser.contents


def test__licenses__admin__LicenseAdmin__4(browser, license):
    """Change a license in the admin view."""
    new_title = f'new_{license.title}'

    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow(license.title)
    browser.getControl('Title').value = new_title
    browser.getControl(name='_save').click()

    lr = License.objects.get(id=license.id)
    assert 'was changed successfully' in browser.contents
    assert lr.title == new_title


def test__licenses__admin__LicenseAdmin__5(browser, license):
    """Change a LR without an actual change."""
    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow(license.title)
    browser.getControl(name='_save').click()

    lr = License.objects.get(id=license.id)
    assert 'was changed successfully' in browser.contents
    assert license == lr


def test__licenses__admin__LicenseAdmin__6(browser):
    """The number field is not visible when a LR gets add by an admin."""
    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow('Add License')

    assert 'Number:' not in browser.contents


def test__licenses__admin__LicenseAdmin__7(browser, license):
    """The number field is not visible when a LR gets add by an admin."""
    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow(license.title)

    assert 'Number:' in browser.contents


def test__licenses__admin__LicenseAdmin__8(
        browser, license_dict, user_dict):
    """Show LRs with a profile without user."""
    profile = Profile.objects.create(
        first_name=user_dict['first_name'],
        last_name=user_dict['last_name']
    )
    create_license(profile, license_dict)

    browser.login_admin()
    browser.follow('License')

    assert '-' in browser.contents


def test__licenses__admin__LicenseAdmin__9(
        browser, license_dict, user):
    """Filter LR by duration."""
    def _lr():
        return create_license(user.profile, license_dict, )

    def _a(str):
        assert str in browser.contents

    def _na(str):
        assert str not in browser.contents

    until_10 = _lr()
    until_10.title = 'title1'
    until_10.duration = datetime.timedelta(minutes=10)
    until_10.save()

    until_30 = _lr()
    until_30.title = 'title2'
    until_30.duration = datetime.timedelta(minutes=30)
    until_30.save()

    until_1h = _lr()
    until_1h.title = 'title3'
    until_1h.duration = datetime.timedelta(hours=1)
    until_1h.save()

    over_1h = _lr()
    over_1h.title = 'title4'
    over_1h.duration = datetime.timedelta(hours=1, minutes=1)
    over_1h.save()

    browser.login_admin()
    browser.open(A_LICENSE_URL)

    browser.follow('<= 10 minutes')
    _a(until_10.title)
    _na(until_30.title)
    _na(until_1h.title)
    _na(over_1h.title)

    browser.follow('<= 30 minutes')
    _na(until_10.title)
    _a(until_30.title)
    _na(until_1h.title)
    _na(over_1h.title)

    browser.follow('<= 1 hour')
    _na(until_10.title)
    _na(until_30.title)
    _a(until_1h.title)
    _na(over_1h.title)

    browser.follow('> 1 hour')
    _na(until_10.title)
    _na(until_30.title)
    _na(until_1h.title)
    _a(over_1h.title)


def test__licenses__admin__LicenseAdmin__10(browser, license):
    """Try to confirm a LR with unverified profile."""
    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow(license.title)

    profile = license.profile
    profile.verified = False
    profile.save()

    browser.getControl('Confirmed').click()
    browser.getControl(name='_save').click()

    assert 'corresponding profile is not verified' in browser.contents
    assert not license.confirmed


def test__licenses__admin__LicenseAdmin__11(browser, license):
    """Try to confirm LRs with unverified profiles."""
    profile = license.profile
    profile.verified = False
    profile.save()

    browser.login_admin()
    browser.open(A_LICENSE_URL)

    browser.getControl(name='_selected_action').controls[0].selected = True
    browser.getControl('Action').value = 'confirm'
    browser.getControl('Go').click()

    assert f'profile of {license} is not verified' in browser.contents
    assert '0 Licenses were successfully confirmed' in browser.contents


def test__licenses__admin__DurationFilter__1():
    """Handle invalid values."""
    with patch.object(DurationFilter, 'value', return_value='invalid'):
        with pytest.raises(ValueError, match=r'Invalid value .*'):
            filter = DurationFilter(
                {}, {}, License, LicenseAdmin)
            filter.queryset(None, None)


def test__licenses__admin__YearFilter__1(browser, user, license_dict):
    """Licenses can be filtered by the year of its creation date."""
    created_at = datetime.datetime(
        day=8, month=9, year=datetime.datetime.now().year, tzinfo=TZ)
    license_dict['title'] = 'new_title'
    lr1 = create_license(user.profile, license_dict)
    lr1.created_at = created_at
    lr1.save()

    created_at = datetime.datetime(
        day=8, month=9, year=(datetime.datetime.now().year-1), tzinfo=TZ)
    license_dict['title'] = 'old_title'
    lr2 = create_license(user.profile, license_dict)
    lr2.created_at = created_at
    lr2.save()

    browser.login_admin()
    browser.open(A_LICENSE_URL)

    browser.follow('This year')
    assert str(lr1) in browser.contents
    assert str(lr2) not in browser.contents

    browser.follow('Last year')
    assert str(lr1) not in browser.contents
    assert str(lr2) in browser.contents


def test__licenses__admin__YearFilter__2():
    """Handle invalid values."""
    with patch.object(YearFilter, 'value', return_value='invalid'):
        with pytest.raises(ValueError, match=r'Invalid value .*'):
            filter = YearFilter(
                {}, {}, License, LicenseAdmin)
            filter.queryset(None, None)


def test__licenses__admin__LicenseResource__1(browser, license):
    """Export the datetime properties using the current time zone."""
    license.suggested_date = datetime.datetime(
        year=2022,
        month=9,
        day=21,
        hour=0,
        tzinfo=TZ,
    )

    license.created_at = datetime.datetime(
        year=2022,
        month=9,
        day=20,
        hour=0,
        tzinfo=TZ,
    )

    license.save()

    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow('Export')
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    assert str(license.suggested_date.date()) in str(browser.contents)
    assert str(license.suggested_date.time()) in str(browser.contents)
    assert str(license.created_at.date()) in str(browser.contents)
    assert str(license.created_at.time()) in str(browser.contents)


def test__licenses__admin__LicenseResource__2(browser, license):
    """Export a license without a suggested broadcast date."""
    license.suggested_date = None
    license.save()

    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow('Export')
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    assert str(license.title) in str(browser.contents)


def test__licenses__admin__LicenseResource__3(browser, license: License):
    """Export a license with all necessary data."""
    license.subtitle = 'Subtitle'
    license.further_persons = 'cut: another person'
    license.suggested_date = datetime.datetime(
        year=2022,
        month=10,
        day=10,
        hour=9,
        tzinfo=TZ,
    )
    license.save()

    browser.login_admin()
    browser.open(A_LICENSE_URL)
    browser.follow('Export')
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    export = str(browser.contents)

    assert str(license.number) in export
    assert license.title in export
    assert license.subtitle in export
    assert license.description in export
    assert (f'{license.profile.first_name} {license.profile.last_name}' in
            export)
    assert license.further_persons in export
    assert str(license.duration) in export
    assert str(license.suggested_date.astimezone(TZ).date()) in export
    assert str(license.suggested_date.astimezone(TZ).time()) in export
    assert str(license.repetitions_allowed) in export
    assert str(license.media_authority_exchange_allowed) in export
    assert str(license.youth_protection_necessary) in export
    assert str(license.store_in_ok_media_library) in export


def test__licenses__admin__DurationRangeFilter__1(
        browser, license_dict, user):
    """Filter licenses after duration."""
    license_dict['duration'] = datetime.timedelta(minutes=5)
    license_dict['title'] = 'license1'
    license1 = create_license(user.profile, license_dict)

    license_dict['duration'] = datetime.timedelta(minutes=10)
    license_dict['title'] = 'license2'
    license2 = create_license(user.profile, license_dict)

    license_dict['title'] = 'license3'
    license_dict['duration'] = datetime.timedelta(minutes=15)
    license3 = create_license(user.profile, license_dict)

    browser.login_admin()
    browser.open(A_LICENSE_URL)

    browser.getControl(name='duration_from').value = 6
    browser.getControl(name='duration_to').value = 10
    browser.getControl('Search', index=2).click()

    assert license1.title not in browser.contents
    assert license2.title in browser.contents
    assert license3.title not in browser.contents
