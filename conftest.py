from datetime import datetime
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from licenses.models import default_category
from ok_tools.testing import PWD
from ok_tools.testing import create_license_request
from registration.models import Profile
import ok_tools.wsgi
import pytest
import zope.testbrowser.browser


User = get_user_model()


@pytest.fixture(scope="function")
def browser(db, admin_user):
    """Get a ``zope.testbrowser`` Browser instance.

    Usage:
    >>> browser.open(URL)
    >>> browser.login(USERNAME, PASSWORD)
    """
    return Browser(wsgi_app=ok_tools.wsgi.application)


class Browser(zope.testbrowser.browser.Browser):
    """Browser customized for cookie log-in to admin UI."""

    def login_admin(self):
        """Log-in the admin user."""
        self.login('admin@example.com')

    # TODO password=PWD
    def login(self, email, password='password'):
        """Log-in a user at the login-page."""
        assert '/login/?next=' in self.url, \
            f'Not on login page, URL is {self.url}'
        self.getControl('Email address').value = email
        self.getControl('Password').value = password
        self.getControl('Log in').click()


@pytest.fixture(scope='function')
def mail_outbox():
    """Return the mail outbox."""
    return mail.outbox


@pytest.fixture(scope='function')
def user_dict() -> dict:
    """Return a user as dict."""
    return {
        "email": "user@example.com",
        "first_name": "john",
        "last_name": "doe",
        "gender": "m",
        "phone_number": None,
        "mobile_number": None,
        "birthday": "05.09.1989",
        "street": "secondary street",
        "house_number": "1",
        "zipcode": "12345",
        "city": "example-city"
    }


@pytest.fixture(scope='function')
def user(user_dict) -> User:
    """Return a registered user with profile and password."""
    user = User.objects.create_user(user_dict['email'], password=PWD)
    Profile(
        okuser=user,
        first_name=user_dict['first_name'],
        last_name=user_dict['last_name'],
        gender=user_dict['gender'],
        phone_number=user_dict['mobile_number'],
        mobile_number=user_dict['phone_number'],
        birthday=datetime.strptime(
            user_dict['birthday'], settings.DATE_INPUT_FORMATS).date(),
        street=user_dict['street'],
        house_number=user_dict['house_number'],
        zipcode=user_dict['zipcode'],
        city=user_dict['city'],
    ).save()

    return user


@pytest.fixture(scope='function')
def license_template_dict() -> dict:
    """Return a dictionary containing all the data of an LicenseTemplate."""
    return {
        "title": "Test Title",
        "subtitle": None,
        "description": "This is a Test.",
        "duration": timedelta(hours=1, minutes=1, seconds=1),
        "suggested_date": None,
        "repetitions_allowed": True,
        "media_authority_exchange_allowed": True,
        "youth_protection_necessary": False,
        "store_in_ok_media_library": True,
    }


@pytest.fixture(scope='function')
def license_request(user, license_template_dict):
    """Return a license request."""
    return create_license_request(
        user,
        default_category(),
        license_template_dict,
    )
