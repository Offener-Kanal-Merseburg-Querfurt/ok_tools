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
