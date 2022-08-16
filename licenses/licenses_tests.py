from django.urls import reverse_lazy
from ok_tools.testing import DOMAIN
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
