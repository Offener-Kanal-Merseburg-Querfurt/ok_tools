from .email import send_auth_mail
from .models import Profile
from conftest import pdfToText
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from unittest.mock import patch
from urllib.error import HTTPError
import logging
import pytest
import re


logger = logging.getLogger('django')

User = get_user_model()

DOMAIN = 'http://localhost:8000'
USER_CREATED_URL = f'{DOMAIN}{reverse_lazy("user_created")}'
REGISTER_URL = f'{DOMAIN}{reverse_lazy("register")}'
LOGIN_URL = f'{DOMAIN}{reverse_lazy("login")}'
APPLY_URL = f'{DOMAIN}{reverse_lazy("print_registration")}'
AUTH_URL = r'http://localhost:8000/profile/reset/.*/'
PWD_RESET_URL = f'{DOMAIN}{reverse_lazy("password_reset")}'

PWD = 'testpassword'


def test_registration__01(browser, user):
    """It is possible to register with an unused email address."""
    _register_user(browser, user)
    assert _success_string(user['email']) in browser.contents
    assert browser.url == USER_CREATED_URL


def test_registration__02(browser, user):
    """It is not possible to register with an used email address."""
    User(email=user['email']).save()

    _register_user(browser, user)
    assert f'address {user["email"]} already exists' in browser.contents
    assert browser.url == REGISTER_URL


# TODO how to check that the register form is still there
def test_registration__03(browser, user):
    """It is not possible to register with an invalid email address."""
    user['email'] = "example.com"

    _register_user(browser, user)
    assert 'Enter a valid email address' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__04(browser, user):
    """It is possible to register with a valid phone number."""
    user['phone_number'] = '+49346112345'
    user['mobile_number'] = '015712345678'
    _register_user(browser, user)
    assert _success_string(user['email']) in browser.contents
    assert browser.url == USER_CREATED_URL


def test_registration__05(db, user):
    # db is needed for data base access in send_auth_mail
    """It is not possible to send an authentication mail to an unknown user."""
    with pytest.raises(User.DoesNotExist):
        send_auth_mail(user['email'])


def test_registration__06(browser, user):
    """It is not possible to register without mandatory fields."""
    user['first_name'] = None
    _register_user(browser, user)
    assert 'This field is required' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__07(browser, mail_outbox, user):
    """After the registration an email gets send."""
    _register_user(browser, user)
    assert 1 == len(mail_outbox)
    assert _get_link_url_from_email(mail_outbox, AUTH_URL)


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


def test_registration__11(user, db):
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
    _log_in(browser, email=user['email'], password=PWD)
    assert 'enter a correct email address and password' in browser.contents


def test_registration__13b(browser, user):
    """It is possible to log in with a known user."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()

    _log_in(browser, user['email'], password=PWD)
    assert f'Hi {user["email"]}!' in browser.contents


def test_registration__14(browser, mail_outbox, user):
    """A user can set a password after registration."""
    _register_user(browser, user)
    assert 1 == len(mail_outbox)
    pw_url = _get_link_url_from_email(mail_outbox, AUTH_URL)

    browser.open(pw_url)
    browser.getControl('New password', index=0).value = PWD
    browser.getControl('confirmation').value = PWD
    browser.getControl('Change').click()

    assert '/profile/reset/done' in browser.url
    assert 'Password reset complete' in browser.contents


def test_registration__15(browser, user, mail_outbox):
    """It is possible to change the password."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()

    _log_in(browser, user['email'], password=PWD)
    assert f'Hi {user["email"]}!' in browser.contents

    browser.getLink('Change Password').click()
    browser.getControl('Email').value = user['email']
    browser.getControl('Send').click()
    assert 1 == len(mail_outbox)
    assert _get_link_url_from_email(mail_outbox, AUTH_URL)


def test_registration__17(browser, user):
    """Log in with wrong password."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()

    _log_in(browser, user['email'], password='wrongpassword')
    assert '/profile/login' in browser.url
    assert 'enter a correct email address and password' in browser.contents


def test_registration__18(db, user):
    """It is not possible to send an email to someone without Profile."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()

    with pytest.raises(Profile.DoesNotExist):
        send_auth_mail(user['email'])


def test_registration__19(browser, user, mail_outbox):
    """It is possible to set a new password using email."""
    _register_user(browser, user)
    _request_pwd_reset(browser, user)

    assert 2 == len(mail_outbox)
    assert _get_link_url_from_email(mail_outbox, AUTH_URL)
    assert 'password change' in mail_outbox[-1].body
    assert user['first_name'] in mail_outbox[-1].body


def test_registration__20(db, browser, user):
    """It is not possible to send a password reset to an unknown user."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()

    with patch('registration.models.OKUser.objects.get') as mock:
        mock.side_effect = User.DoesNotExist()
        with pytest.raises(HTTPError, match=r'.*500.*'):
            _request_pwd_reset(browser, user)


def test_registration__21(db, user):
    """Users with unverified profile don't have the permission 'verified'."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()
    testprofile = Profile.objects.create(okuser=testuser)
    testprofile.save()

    assert not testuser.has_perm('registration.verified')


def test_registration__22(browser, user, mail_outbox):
    """User can download a plain application form."""
    register_with_pwd(browser, user, mail_outbox)
    _log_in(browser, user['email'], PWD)
    browser.open(APPLY_URL)
    browser.getControl('Apply').click()

    assert browser.headers['Content-Type'] == 'application/pdf'
    assert user['first_name'] not in pdfToText(browser.contents)
    assert user['last_name'] not in pdfToText(browser.contents)


def test_registration__23(browser, user, mail_outbox):
    """User can download an automatically created application form."""
    register_with_pwd(browser, user, mail_outbox)
    _log_in(browser, user['email'], PWD)
    browser.open(APPLY_URL)
    browser.getControl('application form').click()

    assert browser.headers['Content-Type'] == 'application/pdf'
    assert user['first_name'] in pdfToText(browser.contents)
    assert user['last_name'] in pdfToText(browser.contents)


def test_registration__24(browser, user):
    """User without a profile can not create an application form."""
    testuser = User.objects.create_user(email=user['email'], password=PWD)
    testuser.save()
    _log_in(browser, user['email'], PWD)

    browser.open(APPLY_URL)
    assert browser.url == DOMAIN + reverse_lazy('home')
    assert f'There is no profile for {user["email"]}' in browser.contents


def test_registration__25(browser, user, mail_outbox):
    """Users that are verified can only change their phone number."""
    register_with_pwd(browser, user, mail_outbox)
    _log_in(browser, user['email'], PWD)
    testprofile = Profile.objects.get(first_name=user['first_name'])
    testprofile.verified = True
    testprofile.save()
    browser.open(APPLY_URL)
    with pytest.raises(AttributeError, match=r'.*readonly.*'):
        browser.getControl(name='first_name').value = 'new_name'
    browser.getControl(name='phone_number').value = '123456789012'
    # TODO submit changes


def test__registration__templates__privacy_policy__1(browser):
    """The Privacy Policy is accessible."""
    browser.open(REGISTER_URL)
    browser.getLink('privacy policy').click()
    assert 'Privacy Policy' in browser.contents


def test__registration__templates__navbar__1(browser):
    """It is possible to got to the register site and back using the navbar."""
    browser.open(DOMAIN)
    browser.getLink('register').click()
    assert 'first_name' in browser.contents
    assert 'privacy policy' in browser.contents

    browser.getLink(settings.OK_NAME_SHORT).click()
    assert 'You are not logged in' in browser.contents


"""Helper functions"""


def register_with_pwd(browser, user: dict, mail_outbox, password=PWD):
    """Register the given user and set a password."""
    _register_user(browser, user)
    assert 1 == len(mail_outbox)
    pw_url = _get_link_url_from_email(mail_outbox, AUTH_URL)

    browser.open(pw_url)
    browser.getControl('New password', index=0).value = password
    browser.getControl('confirmation').value = password
    browser.getControl('Change').click()

    assert '/profile/reset/done' in browser.url
    assert 'Password reset complete' in browser.contents


def _register_user(browser, user: dict):
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
    browser.getControl('accept').click()
    browser.getControl('Register').click()


def _log_in(browser, email, password):
    """Log in a user with the given email and password."""
    browser.open(LOGIN_URL)
    assert 'profile/login/' in browser.url, \
        f'Not on login page, URL is {browser.url}'

    browser.getControl('Email').value = email
    browser.getControl('Password').value = password
    browser.getControl('Log In').click()


def _request_pwd_reset(browser, user):
    """Request an email to reset the password."""
    browser.open(PWD_RESET_URL)
    assert PWD_RESET_URL in browser.url
    assert 'Change Password' in browser.contents

    browser.getControl('Email').value = user['email']
    browser.getControl('Send').click()


def _get_link_url_from_email(mail_outbox, pattern: str) -> str:
    """Get a link URL from the last email sent."""
    mail_body = mail_outbox[-1].body
    res = re.search(pattern, mail_body, re.M)
    if not res:  # pragma: no cover
        logger.error(f'No auth link in email:\n {mail_body}')
        raise AssertionError
    return res.group(0)  # entire match


def _success_string(email: str) -> str:
    """Return the string which shows a successfull registration."""
    return f'created user {email}'
