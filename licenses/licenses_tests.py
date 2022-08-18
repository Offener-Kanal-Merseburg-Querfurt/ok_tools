from .models import LicenseRequest
from .models import default_category
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from ok_tools.testing import DOMAIN
from ok_tools.testing import create_license_request
from ok_tools.testing import create_user
from ok_tools.testing import pdfToText
from urllib.error import HTTPError
import ok_tools.testing as testing
import pytest


User = get_user_model()

HOME_URL = f'{DOMAIN}{reverse_lazy("home")}'
LIST_URL = f'{DOMAIN}{reverse_lazy("licenses:licenses")}'
CREATE_URL = f'{DOMAIN}{reverse_lazy("licenses:create")}'
LOGIN_URL = f'{DOMAIN}{reverse_lazy("login")}'


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
    browser.getControl('Save').click()

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
    browser.getControl('Save').click()

    assert CREATE_URL == browser.url
    assert 'This field is required' in browser.contents
    assert not LicenseRequest.objects.filter()


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
        user, default_category(), license_template_dict)

    assert str(license_request) == license_request.title
    assert str(license_with_subtitle) in str(license_with_subtitle)
    assert license_request.category.__str__() == default_category().name


def test__licenses__print__1(browser, user, license_request):
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
    user_dict['email'] = 'new_'+user_dict['email']
    second_user = create_user(user_dict)
    second_lr = create_license_request(
        second_user, default_category(), license_template_dict)

    browser.login()  # login with user
    browser.open(print_url(second_lr.id))

    assert browser.url == LIST_URL
    assert 'License not found.' in browser.contents


def test__licenses__views__Filled_licenseFile__4(
        browser, license_template_dict):
    """The user of a LR needs to have a profile."""
    user = User.objects.create_user(testing.EMAIL, password=testing.PWD)
    lr = create_license_request(
        user, default_category(), license_template_dict)

    browser.login()
    browser.open(print_url(lr.id))

    assert "There is no profile" in browser.contents
