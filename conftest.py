from datetime import date
from django.contrib.auth import get_user_model
from django.core import mail
import PyPDF2
import io
from registration.models import Profile
import ok_tools.wsgi
import pytest
import zope.testbrowser.browser


User = get_user_model()
PWD = 'testpassword'


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
def user() -> User:
    """Return a registered user with profile and password."""
    user_data = {
        "email": "user@example.com",
        "first_name": "john",
        "last_name": "doe",
        "gender": "m",
        "phone_number": None,
        "mobile_number": None,
        "birthday": "1989-09-05",
        "street": "secondary street",
        "house_number": "1",
        "zipcode": "12345",
        "city": "example-city"
    }

    user = User.objects.create_user(user_data['email'], password=PWD)
    user.save()
    Profile(
        okuser=user,
        first_name=user_data['first_name'],
        last_name=user_data['last_name'],
        gender=user_data['gender'],
        phone_number=user_data['mobile_number'],
        mobile_number=user_data['phone_number'],
        birthday=date.fromisoformat(user_data['birthday']),
        street=user_data['street'],
        house_number=user_data['house_number'],
        zipcode=user_data['zipcode'],
        city=user_data['city'],
    ).save()

    return user

# Global helper functions.


def pdfToText(pdf) -> str:
    """Convert pdf bytes into text."""
    reader = PyPDF2.PdfReader(io.BytesIO(pdf))

    return "\n".join(page.extract_text() for page in reader.pages)
