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
        self.login('admin@example.com')

    def login(self, email, password='password'):
        """Log-in a user at the login-page."""
        assert '/login/?next=' in self.url, \
            f'Not on login page, URL is {self.url}'
        self.getControl('Email address').value = email
        self.getControl('Password').value = password
        self.getControl('Log in').click()

    def register_user(self, user: dict):
        """
        Register a user defined by the given dictionary.

        The entries of the user dictionary correspond to the fields defined
        in models.py for user and profile.
        """
        assert '/register/' in self.url, \
            f'Not on register page, URL is {self.url}'

        self.getControl('Email').value = user['email']
        self.getControl('First name').value = user['first_name']
        self.getControl('Last name').value = user['last_name']
        self.getControl('Gender').value = user['gender']
        self.getControl('Phone number').value = user['phone_number']
        self.getControl('Mobile number').value = user['mobile_number']
        self.getControl('Birthday').value = user['birthday']
        self.getControl('Street').value = user['street']
        self.getControl('House number').value = user['house_number']
        self.getControl('Zipcode').value = user['zipcode']
        self.getControl('City').value = user['city']
        self.getControl('submit').click()
