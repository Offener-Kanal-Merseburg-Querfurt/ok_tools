from django.contrib.auth import get_user_model
from urllib.error import HTTPError
import pytest


User = get_user_model()
REGISTER_URL = 'http://localhost/register/'


def test_registration__1(browser):
    """It is possible to register with an unused email address."""
    email = 'test@example.com'

    browser.open(REGISTER_URL)
    browser.register_user(email)
    assert f'created user {email}' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__2(browser):
    """It is not possible to register with an used email address."""
    email = 'test@example.com'
    User(email=email).save()

    browser.open(REGISTER_URL)
    with pytest.raises(HTTPError, match=r'.* 400.*'):
        browser.register_user(email)
    assert 'address already exists' in browser.contents
    assert browser.url == REGISTER_URL


# TODO how to check that the register form is still there
def test_registration__3(browser):
    """It is not possible to register with an unvalid email address."""
    unvalid_email = "example.com"

    browser.open(REGISTER_URL)
    with pytest.raises(HTTPError, match=r'.* 400.*'):
        browser.register_user(unvalid_email)
    assert 'Enter a valid email address' in browser.contents
    assert browser.url == REGISTER_URL
