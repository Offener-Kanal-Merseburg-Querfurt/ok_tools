from copy import deepcopy
from django.contrib.auth import get_user_model
from urllib.error import HTTPError
import pytest


User = get_user_model()
REGISTER_URL = 'http://localhost/register/'
USER: dict = {
    "email": "user@example.com",
    "first_name": "john",
    "last_name": "doe",
    "gender": "m",
    "phone_number": None,
    "mobile_number": None,
    "birthday": "05/09/1989",
    "street": "secondary street",
    "house_number": "1",
    "zipcode": "12345",
    "city": "example-city"
}

SUCCESS_STRING = f'created user {USER["email"]}'


def test_registration__1(browser):
    """It is possible to register with an unused email address."""
    browser.open(REGISTER_URL)
    browser.register_user(USER)
    assert SUCCESS_STRING in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__2(browser):
    """It is not possible to register with an used email address."""
    user = deepcopy(USER)
    User(email=user['email']).save()

    browser.open(REGISTER_URL)
    with pytest.raises(HTTPError, match=r'.* 400.*'):
        browser.register_user(user)
    assert f'address {user["email"]} already exists' in browser.contents
    assert browser.url == REGISTER_URL


# TODO how to check that the register form is still there
def test_registration__3(browser):
    """It is not possible to register with an invalid email address."""
    user = deepcopy(USER)
    user['email'] = "example.com"

    browser.open(REGISTER_URL)
    with pytest.raises(HTTPError, match=r'.* 400.*'):
        browser.register_user(user)
    assert 'Enter a valid email address' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__4(browser):
    """It is possible to register with a valid phone number."""
    user = deepcopy(USER)
    user['phone_number'] = '+49346112345'
    user['mobile_number'] = '015712345678'
    browser.open(REGISTER_URL)
    browser.register_user(user)
    assert SUCCESS_STRING in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__5(browser):
    """It is not possible to register with an invalid phone number."""
    user = deepcopy(USER)
    user['phone_number'] = '12345678'
    browser.open(REGISTER_URL)
    with pytest.raises(HTTPError, match=r'.* 400.*'):
        browser.register_user(user)
    assert 'Enter a valid phone number' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration_6(browser):
    """It is not possible to register without mandatory fields."""
    user = deepcopy(USER)
    user['first_name'] = None
    browser.open(REGISTER_URL)
    with pytest.raises(HTTPError, match=r'.* 400.*'):
        browser.register_user(user)
    assert 'This field is required' in browser.contents
    assert browser.url == REGISTER_URL
