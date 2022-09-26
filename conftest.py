from contributions.models import DisaImport
from datetime import datetime
from datetime import timedelta
from django.core import mail
from django.urls import reverse_lazy
from licenses.models import default_category
from ok_tools.datetime import TZ
from ok_tools.testing import DOMAIN
from ok_tools.testing import EMAIL
from ok_tools.testing import PWD
from ok_tools.testing import create_contribution
from ok_tools.testing import create_disaimport
from ok_tools.testing import create_license_request
from ok_tools.testing import create_project
from ok_tools.testing import create_user
from projects.models import Project
from projects.models import ProjectLeader
from projects.models import default_category as default_project_category
from projects.models import default_target_group
import ok_tools.wsgi
import pytest
import zope.testbrowser.browser


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
        self.open(f'{DOMAIN}{reverse_lazy("admin:login")}')
        self._login('admin@example.com', password='password')

    def login(self, email=EMAIL, password=PWD):
        """Log-in a user."""
        self.open(f'{DOMAIN}{reverse_lazy("login")}')
        self._login(email, password)

    def _login(self, email, password):
        """Log-in a user at the login-page."""
        assert '/login' in self.url, \
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
        "email": EMAIL,
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
def user(user_dict):
    """Return a registered user with profile and password."""
    return create_user(user_dict)


@pytest.fixture(scope='function')
def license_template_dict() -> dict:
    """Return a dictionary containing all the data of an LicenseTemplate."""
    return {
        "title": "Test Title",
        "subtitle": None,
        "description": "This is a Test.",
        "duration": timedelta(hours=1, minutes=1, seconds=1),
        "further_persons": None,
        "suggested_date": None,
        "repetitions_allowed": True,
        "media_authority_exchange_allowed": True,
        "youth_protection_necessary": False,
        "store_in_ok_media_library": True,
    }


@pytest.fixture(scope='function')
def license_request(user, license_template_dict):
    """Return a license request."""
    profile = user.profile
    profile.verified = True
    profile.save()

    return create_license_request(
        profile,
        default_category(),
        license_template_dict,
    )


@pytest.fixture(scope='function')
def contribution_dict() -> dict:
    """Return a dictionary with  all additional data for a contribution."""
    return {
        'broadcast_date': datetime(year=2022,
                                   month=8,
                                   day=25,
                                   hour=12,
                                   tzinfo=TZ,
                                   ),
        'live': False,
    }


@pytest.fixture(scope='function')
def contribution(license_request, contribution_dict):
    """Return a stored contribution."""
    return create_contribution(
        license_request,
        contribution_dict,
    )


@pytest.fixture(scope='function')
def disaimport() -> DisaImport:
    """Create a DISA import."""
    return create_disaimport()


@pytest.fixture(scope='function')
def project_dict() -> dict:
    """Create a dict with all necessary properties to create a project."""
    return {
        'title': 'title',
        'topic': 'topic',
        'duration': timedelta(hours=1, minutes=30),
        'begin_date': datetime(year=2022, month=9, day=20, hour=9, tzinfo=TZ),
        'end_date': datetime(year=2022, month=9, day=20, hour=10, tzinfo=TZ),
        'external_venue': False,
        'jugendmedienschutz': False,
        'target_group': default_target_group(),
        'project_category': default_project_category(),
        'project_leader': ProjectLeader.objects.create(name='leader'),
    }


@pytest.fixture(scope='function')
def project(project_dict) -> Project:
    """Create a project."""
    return create_project(project_dict)
