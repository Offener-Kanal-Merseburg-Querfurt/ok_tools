from .models import LicenseRequest
from .models import default_category
from django.urls import reverse_lazy
from ok_tools.testing import DOMAIN
from ok_tools.testing import create_license_request
from urllib.error import HTTPError
import pytest


HOME_URL = f'{DOMAIN}{reverse_lazy("home")}'
LIST_URL = f'{DOMAIN}{reverse_lazy("licenses:licenses")}'
CREATE_URL = f'{DOMAIN}{reverse_lazy("licenses:create")}'
LOGIN_URL = f'{DOMAIN}{reverse_lazy("login")}'


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
    browser.getControl(name='duration_0').value = 0
    browser.getControl(name='duration_1').value = 0
    browser.getControl(name='duration_2').value = 10
    browser.getControl('Create').click()

    assert LIST_URL == browser.url
    assert 'Your licenses' in browser.contents
    assert LicenseRequest.objects.get(title=title)


def test__licenses__views__CreateLicenseView__4(browser, user):
    """A license needs a Title."""
    browser.login()
    browser.open(CREATE_URL)
    browser.getControl('Description').value = 'This is a Test.'
    browser.getControl(name='duration_0').value = 0
    browser.getControl(name='duration_1').value = 0
    browser.getControl(name='duration_2').value = 10
    browser.getControl('Create').click()

    assert CREATE_URL == browser.url
    assert 'This field is required' in browser.contents
    assert not LicenseRequest.objects.filter()


def test__licenses__models__1(
        browser, user, license_request, license_template_dict):
    """
    String representation.

    A LicenseRequest gets represented by the first and last name of its user.
    A Category get represented by its name.
    """
    browser.login()
    subtitle = 'Test Subtitle'
    license_template_dict['subtitle'] = subtitle
    license_with_subtitle = create_license_request(
        user, default_category(), license_template_dict)

    assert license_request.__str__() == license_request.title
    assert license_with_subtitle.subtitle in license_with_subtitle.__str__()
    assert license_request.category.__str__() == default_category().name
