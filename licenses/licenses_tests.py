from .admin import DurationFilter
from .admin import LicenseRequestAdmin
from .admin import YearFilter
from .models import LicenseRequest
from .models import default_category
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from ok_tools.testing import DOMAIN
from ok_tools.testing import EMAIL
from ok_tools.testing import PWD
from ok_tools.testing import TZ
from ok_tools.testing import create_license_request
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
                 f'{reverse_lazy("admin:licenses_licenserequest_changelist")}')


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


def test__licenses__views__ListLicensesView__3(db, browser, license_request):
    """All licenses of the user are listed."""
    browser.login()
    browser.open(LIST_URL)

    assert str(license_request) in browser.contents
    assert 'No' in browser.contents  # the License Request is not confirmed


def test__licenses__views__ListLicensesView__4(browser, license_request):
    """If a LR is confirmed, it is shown in the overview."""
    license_request.confirmed = True
    license_request.save()
    browser.login()
    browser.open(LIST_URL)

    assert str(license_request) in browser.contents
    assert 'Yes' in browser.contents  # the License Request is confirmed


def test__licenses__views__ListLicensesView__5(browser, user, license_request):
    """It is possible to edit a license from the list view."""
    browser.login()
    browser.open(LIST_URL)
    browser.follow(id=f'id_edit_{license_request.id}')

    assert browser.url == edit_url(license_request.id)


def test__licenses__views__ListLicensesView__6(browser, user, license_request):
    """It is possible to print a license from the list view."""
    browser.login()
    browser.open(LIST_URL)
    browser.follow(id=f'id_print_{license_request.id}')

    assert browser.url == print_url(license_request.id)


def test__licenses__views__ListLicensesView__7(browser):
    """A user without a profile can not see any LRs."""
    User.objects.create_user(email=EMAIL, password=PWD)
    browser.login()
    browser.open(LIST_URL)

    assert 'No licenses yet.' in browser.contents


def test__licenses__views__DetailsLicensesView__1(browser, license_request):
    """If no user is logged in the details view returns a 404."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(details_url(license_request.id))


def test__licenses__views__DetailsLicensesView__2(browser, license_request):
    """The details view can be reached using the Overview."""
    browser.login()
    browser.open(LIST_URL)
    browser.follow(str(license_request))

    assert f'Details for {str(license_request)}' in browser.contents
    assert license_request.description in browser.contents


def test__licenses__views__DetailsLicensesView__3(browser, license_request):
    """It is possible to edit a LR over the details view."""
    browser.login()
    browser.open(details_url(license_request.id))
    browser.follow(id='id_edit_LR')

    assert f'Edit {license_request}:' in browser.contents


def test__licenses__views__UpdateLicensesView__1(browser, license_request):
    """The Description can be changed using the edit site."""
    browser.login()
    browser.open(edit_url(license_request.id))

    new_description = "This is the new description."
    browser.getControl('Description').value = new_description
    browser.getControl('Save').click()

    assert LicenseRequest.objects.get(description=new_description)
    assert browser.url == LIST_URL
    assert 'successfully edited.' in browser.contents


def test__licenses__views__UpdateLicensesView__2(browser, license_request):
    """It is not possible to edit a confirmed LR."""
    license_request.confirmed = True
    license_request.save()

    browser.login()
    browser.open(edit_url(license_request.id))

    assert 'Your License is already confirmed and no longer editable.'\
        in browser.contents


def test__licenses__views__UpdateLicensesView__3(browser, license_request):
    """Even if the form is still available, a confirmed LR is not editable."""
    browser.login()
    browser.open(edit_url(license_request.id))

    license_request.confirmed = True
    license_request.save()

    old_description = license_request.description
    browser.getControl('Description').value = "This is the new description."
    browser.getControl('Save').click()

    assert 'is already confirmed and therefor no longer editable.'\
        in browser.contents
    lr = LicenseRequest.objects.get(id=license_request.id)
    assert lr.description == old_description


def test__licenses__views__UpdateLicensesView__4(browser, license_request):
    """After a license was changed to a screen board, the duration is fixed."""
    browser.login()
    browser.open(edit_url(license_request.id))

    browser.getControl('Screen Board').click()
    browser.getControl('Save').click()

    assert (LicenseRequest.objects.get(id=license_request.id).duration ==
            datetime.timedelta(seconds=settings.SCREEN_BOARD_DURATION))


def test__licenses__views__CreateLicenseView__1(browser, user):
    """A logged in user can access the create site."""
    browser.login()
    browser.open(HOME_URL)
    browser.follow('Licenses')
    browser.follow('Create')

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
    assert LicenseRequest.objects.get(title=title)


def test__licenses__views__CreateLicenseView__4(browser, user):
    """A license needs a Title."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Description').value = 'This is a Test.'
    browser.getControl('Duration').value = '00:00:10'
    browser.getControl('Save').click()

    assert CREATE_URL == browser.url
    assert 'This field is required' in browser.contents
    assert not LicenseRequest.objects.filter()


def test__licenses__views__CreateLicenseView__5(
        db, browser, user, license_template_dict):
    """A license representing a Screen Board has a fixed duration."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Title').value = license_template_dict['title']
    browser.getControl(
        'Description').value = license_template_dict['description']
    browser.getControl('Screen Board').click()
    browser.getControl('Save').click()

    assert (lr := LicenseRequest.objects.get(
        title=license_template_dict['title']))
    assert lr.duration == datetime.timedelta(
        seconds=settings.SCREEN_BOARD_DURATION)


def test__licenses__views__CreateLicenseView__6(browser):
    """It is not possible to create a LR without a Profile."""
    User.objects.create_user(email=EMAIL, password=PWD)
    browser.login()
    browser.open(CREATE_URL)
    assert 'There is no profile' in browser.contents


def test__licenses__forms__CreateLicenseRequestForm__1(
        browser, user, license_template_dict):
    """A LR needs a duration or needs to be a Screen Board."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Title').value = license_template_dict['title']
    browser.getControl(
        'Description').value = license_template_dict['description']
    browser.getControl('Save').click()

    assert 'The duration field is required.' in browser.contents
    assert not LicenseRequest.objects.filter()


def test__licenses__forms__CreateLicenseRequestForm__2(
        browser, user, license_template_dict):
    """The duration field gets validated."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Title').value = license_template_dict['title']
    browser.getControl(
        'Description').value = license_template_dict['description']
    browser.getControl('Duration').value = 'invalid00:01:20'
    browser.getControl('Save').click()

    assert ('Invalid format. Please use the format hh:mm:ss or mm:ss.'
            in browser.contents)


def test__licenses__forms__CreateLicenseRequestForm__3(
        browser, user, license_template_dict):
    """The duration field can have the input format mm:ss."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Title').value = license_template_dict['title']
    browser.getControl(
        'Description').value = license_template_dict['description']
    browser.getControl('Duration').value = '30:20'
    browser.getControl('Save').click()

    assert (LicenseRequest.objects.get(
            title=license_template_dict['title']).duration ==
            datetime.timedelta(minutes=30, seconds=20))


def test__licenses__models__1(
        browser, user, license_request, license_template_dict):
    """
    String representation.

    A LicenseRequest gets represented by its title and subtitle.
    A Category get represented by its name.
    """
    browser.login()
    subtitle = 'Test Subtitle'
    license_template_dict['subtitle'] = subtitle
    license_with_subtitle = create_license_request(
        user.profile, default_category(), license_template_dict)

    assert str(license_request) == license_request.title
    assert str(license_with_subtitle) in str(license_with_subtitle)
    assert license_request.category.__str__() == default_category().name


def test__licenses__models__2(
        db, license_request, license_template_dict, user):
    """Each new LR gets a unique, visible number."""
    lr1 = license_request
    lr2 = create_license_request(
        user.profile, default_category(), license_template_dict)

    assert lr1.number == 1
    assert lr2.number == 2


def test__licenses__models__3(db, license_request):
    """The LR number always stays the same."""
    n1 = license_request.number
    license_request.subtitle = 'new_subtitle'
    license_request.save()
    n2 = license_request.number

    assert n1 == n2


def test__licenses__models__4(browser, license_template_dict, user):
    """A new LR must have a duration greater zero."""
    browser.login_admin()
    browser.follow('License Requests')
    browser.follow('Add License Request')

    browser.getControl('Title').value = license_template_dict['title']
    browser.getControl(
        'Description').value = license_template_dict['description']
    browser.getControl('Duration').value = '00:00'
    browser.getControl(str(user.profile)).click()  # select user

    browser.getControl(name='_save').click()

    assert 'Duration must not be null.' in browser.contents


def test__licenses__generate_file__1(browser, user, license_request):
    """The printed license contains the necessary data."""
    browser.login()
    browser.open(details_url(license_request.id))
    browser.follow(id='id_print_LR')

    assert browser.headers['Content-Type'] == 'application/pdf'
    pdftext = pdfToText(browser.contents)
    assert user.email in pdftext
    assert license_request.title in pdftext
    assert 'x' in pdftext


def test__licenses__views__FilledLicenseFile__1(browser, license_request):
    """If no user is logged in the site returns a 404."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(print_url(license_request.id))


def test__licenses__views__FilledLicenseFile__2(db, user, browser):
    """Try printing a not existing LR produces an error message."""
    browser.login()
    browser.open(print_url(1))

    assert browser.url == LIST_URL
    assert 'License not found.' in browser.contents


def test__licenses__views__FilledLicenseFile__3(
        browser, user, user_dict, license_request, license_template_dict):
    """A LR from another user can not be printed."""
    user_dict['email'] = f'new_{user_dict["email"]}'
    second_user = create_user(user_dict)
    second_lr = create_license_request(
        second_user.profile, default_category(), license_template_dict)

    browser.login()  # login with user
    browser.open(print_url(second_lr.id))

    assert browser.url == LIST_URL
    assert 'License not found.' in browser.contents


def test__licenses__admin__LicenseRequestAdmin__1(
        browser, user, license_request, license_template_dict):
    """Confirm multiple LRs."""
    license_request.confirmed = True
    license_request.save()
    for _ in range(3):
        create_license_request(
            user.profile, default_category(), license_template_dict)

    browser.login_admin()
    browser.follow('License Requests')
    for i in range(4):
        # select all LRs
        browser.getControl(name='_selected_action').controls[i].click()
    browser.getControl('Action').value = 'confirm'
    browser.getControl('Go').click()

    assert '3 License Requests were successfully confirmed.'\
        in browser.contents
    for lr in LicenseRequest.objects.filter():
        assert lr.confirmed


def test__licenses__admin__LicenseRequestAdmin__2(
        browser, user, license_request, license_template_dict):
    """Unconfirm multiple LRs."""
    license_request.save()
    for _ in range(3):
        lr = create_license_request(
            user.profile, default_category(), license_template_dict)
        lr.confirmed = True
        lr.save()

    browser.login_admin()
    browser.follow('License Requests')
    for i in range(4):
        # select all LRs
        browser.getControl(name='_selected_action').controls[i].click()
    browser.getControl('Action').value = 'unconfirm'
    browser.getControl('Go').click()

    assert '3 License Requests were successfully unconfirmed.'\
        in browser.contents
    for lr in LicenseRequest.objects.filter():
        assert not lr.confirmed


def test__licenses__admin__LicenseRequestAdmin__3(browser, license_request):
    """Try to edit an confirmed License Request."""
    license_request.confirmed = True
    license_request.save()

    browser.login_admin()
    browser.follow('License Request')
    browser.follow(license_request.title)

    assert 'Confirmed licenses are not editable!' in browser.contents


def test__licenses__admin__LicenseRequestAdmin__4(browser, license_request):
    """Change a license request in the admin view."""
    new_title = f'new_{license_request.title}'

    browser.login_admin()
    browser.follow('License Request')
    browser.follow(license_request.title)
    browser.getControl('Title').value = new_title
    browser.getControl(name='_save').click()

    lr = LicenseRequest.objects.get(id=license_request.id)
    assert 'was changed successfully' in browser.contents
    assert lr.title == new_title


def test__licenses__admin__LicenseRequestAdmin__5(browser, license_request):
    """Change a LR without an actual change."""
    browser.login_admin()
    browser.follow('License Request')
    browser.follow(license_request.title)
    browser.getControl(name='_save').click()

    lr = LicenseRequest.objects.get(id=license_request.id)
    assert 'was changed successfully' in browser.contents
    assert license_request == lr


def test__licenses__admin__LicenseRequestAdmin__6(browser):
    """The number field is not visible when a LR gets add by an admin."""
    browser.login_admin()
    browser.follow('License Request')
    browser.follow('Add License Request')

    assert 'Number:' not in browser.contents


def test__licenses__admin__LicenseRequestAdmin__7(browser, license_request):
    """The number field is not visible when a LR gets add by an admin."""
    browser.login_admin()
    browser.follow('License Request')
    browser.follow(license_request.title)

    assert 'Number:' in browser.contents


def test__licenses__admin__LicenseRequestAdmin__8(
        browser, license_template_dict, user_dict):
    """Show LRs with a profile without user."""
    profile = Profile.objects.create(
        first_name=user_dict['first_name'],
        last_name=user_dict['last_name']
    )
    create_license_request(profile, default_category(), license_template_dict)

    browser.login_admin()
    browser.follow('License Request')

    assert '-' in browser.contents


def test__licenses__admin__LicenseRequestAdmin__9(
        browser, license_template_dict, user):
    """Filter LR by duration."""
    def _lr():
        return create_license_request(
            user.profile, default_category(), license_template_dict, )

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
    browser.follow('License Request')

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


def test__licenses__admin__LicenseRequestAdmin__10(browser, license_request):
    """Try to confirm a LR with unverified profile."""
    browser.login_admin()
    browser.follow('License Request')
    browser.follow(license_request.title)

    profile = license_request.profile
    profile.verified = False
    profile.save()

    browser.getControl('Confirmed').click()
    browser.getControl(name='_save').click()

    assert 'corresponding profile is not verified' in browser.contents
    assert not license_request.confirmed


def test__licenses__admin__LicenseRequestAdmin__11(browser, license_request):
    """Try to confirm LRs with unverified profiles."""
    profile = license_request.profile
    profile.verified = False
    profile.save()

    browser.login_admin()
    browser.follow('License Request')

    browser.getControl(name='_selected_action').controls[0].selected = True
    browser.getControl('Action').value = 'confirm'
    browser.getControl('Go').click()

    assert f'profile of {license_request} is not verified' in browser.contents
    assert '0 License Requests were successfully confirmed' in browser.contents


def test__licenses__admin__DurationFilter__1():
    """Handle invalid values."""
    with patch.object(DurationFilter, 'value', return_value='invalid'):
        with pytest.raises(ValueError, match=r'Invalid value .*'):
            filter = DurationFilter(
                {}, {}, LicenseRequest, LicenseRequestAdmin)
            filter.queryset(None, None)


def test__licenses__admin__YearFilter__1(browser, user, license_template_dict):
    """Licenses can be filtered by the year of its creation date."""
    created_at = datetime.datetime(
        day=8, month=9, year=datetime.datetime.now().year, tzinfo=TZ)
    license_template_dict['title'] = 'new_title'
    lr1 = create_license_request(
        user.profile, default_category(), license_template_dict)
    lr1.created_at = created_at
    lr1.save()

    created_at = datetime.datetime(
        day=8, month=9, year=(datetime.datetime.now().year-1), tzinfo=TZ)
    license_template_dict['title'] = 'old_title'
    lr2 = create_license_request(
        user.profile, default_category(), license_template_dict)
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
                {}, {}, LicenseRequest, LicenseRequestAdmin)
            filter.queryset(None, None)
