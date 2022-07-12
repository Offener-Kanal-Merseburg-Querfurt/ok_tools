from .email import send_auth_mail
from .models import Profile
from django.contrib.auth import get_user_model
from urllib.error import HTTPError
import pytest
import re


User = get_user_model()

REGISTER_URL = 'http://localhost/register/'
LOGIN_URL = 'http://localhost:8000/profile/login/'
PW_SET_URL = r'http://localhost:8000/profile/reset/.*/'
PWD = 'testpassword'


def test_registration__01(browser, user):
    """It is possible to register with an unused email address."""
    register_user(browser, user)
    assert success_string(user['email']) in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__02(browser, user):
    """It is not possible to register with an used email address."""
    User(email=user['email']).save()

    with pytest.raises(HTTPError, match=r'.* 400.*'):
        register_user(browser, user)
    assert f'address {user["email"]} already exists' in browser.contents
    assert browser.url == REGISTER_URL


# TODO how to check that the register form is still there
def test_registration__03(browser, user):
    """It is not possible to register with an invalid email address."""
    user['email'] = "example.com"

    with pytest.raises(HTTPError, match=r'.* 400.*'):
        register_user(browser, user)
    assert 'Enter a valid email address' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__04(browser, user):
    """It is possible to register with a valid phone number."""
    user['phone_number'] = '+49346112345'
    user['mobile_number'] = '015712345678'
    register_user(browser, user)
    assert success_string(user['email']) in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__05(db, user):
    # db is needed for data base access in send_auth_mail
    """It is not possible to send an authentication mail to an unknown user."""
    with pytest.raises(User.DoesNotExist):
        send_auth_mail(user['email'])


def test_registration__06(browser, user):
    """It is not possible to register without mandatory fields."""
    user['first_name'] = None
    with pytest.raises(HTTPError, match=r'.* 400.*'):
        register_user(browser, user)
    assert 'This field is required' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__07(browser, mail_outbox, user):
    """After the registration an email gets send."""
    register_user(browser, user)
    assert 1 == len(mail_outbox)
    assert get_link_url_from_email(mail_outbox, PW_SET_URL)


def test_registration__08():
    """It is not possible to register without an email on model base."""
    with pytest.raises(ValueError, match=r'.*email must be set.*'):
        User.objects.create_user(email=None)


def test_registration__09(user):
    """A superuser needs to be a staff."""
    with pytest.raises(ValueError, match=r'.*must have is_staff=True.*'):
        User.objects.create_superuser(
            email=user['email'], password=None, is_staff=False)


def test_registration__10(user):
    """A superuser needs to have the right to be a superuser."""
    with pytest.raises(ValueError, match=r'.*must have is_superuser=True.*'):
        User.objects.create_superuser(
            email=user['email'], password=None, is_superuser=False)


def test_registration__11(user):
    """
    String representation.

    A User gets represented by his/her email address. A Profile by its first
    and last name.
    """
    testuser = User(email=user['email'])
    assert user['email'] in testuser.__str__()
    testprofil = Profile(
        okuser=testuser,
        first_name=user['first_name'],
        last_name=user['last_name']
    )
    assert user['first_name'] in testprofil.__str__()
    assert user['last_name'] in testprofil.__str__()


def test_registration__12(browser, user):
    """It is not possible to log in with an unknown email address."""
    with pytest.raises(HTTPError, match=r'.*500.*'):
        log_in(browser, email=user['email'], password=PWD)


def test_registration__13(browser, user):
    """It is possible to log in with an known user."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()

    log_in(browser, user['email'], password=PWD)
    assert f'Hi {user["email"]}!' in browser.contents


def test_registration__14(browser, mail_outbox, user):
    """A user can set a password after registration."""
    register_user(browser, user)
    assert 1 == len(mail_outbox)
    pw_url = get_link_url_from_email(mail_outbox, PW_SET_URL)

    browser.open(pw_url)
    browser.getControl('New password:').value = PWD
    browser.getControl('confirmation').value = PWD
    browser.getControl('Change').click()

    assert '/profile/reset/done' in browser.url
    assert 'Password reset complete' in browser.contents


def test_registration__15(browser, user, mail_outbox):
    """It is possible to reset the password."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()

    log_in(browser, user['email'], password=PWD)
    assert f'Hi {user["email"]}!' in browser.contents

    browser.getLink('Change Password').click()
    browser.getControl('Email').value = user['email']
    browser.getControl('Send').click()
    assert 1 == len(mail_outbox)
    assert get_link_url_from_email(mail_outbox, PW_SET_URL)


def test_registration__17(browser, user):
    """Log in with wrong password."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()

    log_in(browser, user['email'], password='wrongpassword')
    assert '/profile/login' in browser.url
    assert 'enter a correct email address and password' in browser.contents


"""Helper functions"""


def register_user(browser, user: dict):
    """
    Register a user defined by the given dictionary.

    The entries of the user dictionary correspond to the fields defined
    in models.py for user and profile.
    """
    browser.open(REGISTER_URL)
    assert '/register/' in browser.url, \
        f'Not on register page, URL is {browser.url}'

    browser.getControl('Email').value = user['email']
    browser.getControl('First name').value = user['first_name']
    browser.getControl('Last name').value = user['last_name']
    browser.getControl('Gender').value = user['gender']
    browser.getControl('Phone number').value = user['phone_number']
    browser.getControl('Mobile number').value = user['mobile_number']
    browser.getControl('Birthday').value = user['birthday']
    browser.getControl('Street').value = user['street']
    browser.getControl('House number').value = user['house_number']
    browser.getControl('Zipcode').value = user['zipcode']
    browser.getControl('City').value = user['city']
    browser.getControl('Register').click()


def log_in(browser, email, password):
    """Log in a user with the given email and password."""
    browser.open(LOGIN_URL)
    assert 'profile/login/' in browser.url, \
        f'Not on login page, URL is {browser.url}'

    browser.getControl('Email').value = email
    browser.getControl('Password').value = password
    browser.getControl('Log In').click()


def get_link_url_from_email(mail_outbox, pattern: str) -> str:
    """Get a link URL from the last email sent."""
    mail_body = mail_outbox[-1].body
    res = re.search(pattern, mail_body, re.M)
    if not res:  # pragma: no cover
        raise AssertionError
    return res.group(0)  # entire match


def success_string(email: str) -> str:
    """Return the string which shows a successfull registration."""
    return f'created user {email}'
