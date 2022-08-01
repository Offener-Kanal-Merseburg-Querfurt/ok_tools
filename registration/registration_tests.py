from .email import send_auth_mail
from .models import Profile
from conftest import PWD
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
USER_EDIT_URL = f'{DOMAIN}{reverse_lazy("user_data")}'
AUTH_URL = r'http://localhost:8000/profile/reset/.*/'
PWD_RESET_URL = f'{DOMAIN}{reverse_lazy("password_reset")}'


def test_registration__01(browser, user_dict):
    """It is possible to register with an unused email address."""
    _register_user(browser, user_dict)
    assert _success_string(user_dict['email']) in browser.contents
    assert browser.url == USER_CREATED_URL


def test_registration__02(browser, user_dict):
    """It is not possible to register with an used email address."""
    User(email=user_dict['email']).save()

    _register_user(browser, user_dict)
    assert f'address {user_dict["email"]} already exists' in browser.contents
    assert browser.url == REGISTER_URL


# TODO how to check that the register form is still there
def test_registration__03(browser, user_dict):
    """It is not possible to register with an invalid email address."""
    user_dict['email'] = "example.com"

    _register_user(browser, user_dict)
    assert 'Enter a valid email address' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__04(browser, user_dict):
    """It is possible to register with a valid phone number."""
    user_dict['phone_number'] = '+49346112345'
    user_dict['mobile_number'] = '015712345678'
    _register_user(browser, user_dict)
    assert _success_string(user_dict['email']) in browser.contents
    assert browser.url == USER_CREATED_URL


def test_registration__05(db, user_dict):
    # db is needed for data base access in send_auth_mail
    """It is not possible to send an authentication mail to an unknown user."""
    with pytest.raises(User.DoesNotExist):
        send_auth_mail(user_dict['email'])


def test_registration__06(browser, user_dict):
    """It is not possible to register without mandatory fields."""
    user_dict['first_name'] = None
    _register_user(browser, user_dict)
    assert 'This field is required' in browser.contents
    assert browser.url == REGISTER_URL


def test_registration__07(browser, mail_outbox, user_dict):
    """After the registration an email gets send."""
    _register_user(browser, user_dict)
    assert 1 == len(mail_outbox)
    assert _get_link_url_from_email(mail_outbox, AUTH_URL)


def test_registration__08():
    """It is not possible to register without an email on model base."""
    with pytest.raises(ValueError, match=r'.*email must be set.*'):
        User.objects.create_user(email=None)


def test_registration__09(user_dict):
    """A superuser needs to be a staff."""
    with pytest.raises(ValueError, match=r'.*must have is_staff=True.*'):
        User.objects.create_superuser(
            email=user_dict['email'], password=None, is_staff=False)


def test_registration__10(user_dict):
    """A superuser needs to have the right to be a superuser."""
    with pytest.raises(ValueError, match=r'.*must have is_superuser=True.*'):
        User.objects.create_superuser(
            email=user_dict['email'], password=None, is_superuser=False)


def test_registration__11(db, user_dict):
    """
    String representation.

    A User gets represented by his/her email address. A Profile by its first
    and last name.
    """
    testuser = User(email=user_dict['email'])
    assert user_dict['email'] in testuser.__str__()
    testprofil = Profile(
        okuser=testuser,
        first_name=user_dict['first_name'],
        last_name=user_dict['last_name']
    )
    assert user_dict['first_name'] in testprofil.__str__()
    assert user_dict['last_name'] in testprofil.__str__()


def test_registration__12(browser, user_dict):
    """It is not possible to log in with an unknown email address."""
    _log_in(browser, email=user_dict['email'], password=PWD)
    assert 'enter a correct email address and password' in browser.contents


def test_registration__13b(browser, user_dict):
    """It is possible to log in with a known user."""
    testuser = User.objects.create_user(email=user_dict['email'], password=PWD)
    testuser.save()

    _log_in(browser, user_dict['email'], password=PWD)
    assert f'Hi {user_dict["email"]}!' in browser.contents


def test_registration__14(browser, mail_outbox, user_dict):
    """A user can set a password after registration."""
    _register_user(browser, user_dict)
    assert 1 == len(mail_outbox)
    pw_url = _get_link_url_from_email(mail_outbox, AUTH_URL)

    browser.open(pw_url)
    browser.getControl('New password', index=0).value = PWD
    browser.getControl('confirmation').value = PWD
    browser.getControl('Change').click()

    assert '/profile/reset/done' in browser.url
    assert 'Password reset complete' in browser.contents


def test_registration__15(browser, user_dict, mail_outbox):
    """It is possible to change the password."""
    testuser = User.objects.create_user(email=user_dict['email'], password=PWD)
    testuser.save()

    _log_in(browser, user_dict['email'], password=PWD)
    assert f'Hi {user_dict["email"]}!' in browser.contents

    browser.getLink('Change Password').click()
    browser.getControl('Email').value = user_dict['email']
    browser.getControl('Send').click()
    assert 1 == len(mail_outbox)
    assert _get_link_url_from_email(mail_outbox, AUTH_URL)


def test_registration__17(browser, user_dict):
    """Log in with wrong password."""
    testuser = User.objects.create_user(email=user_dict['email'], password=PWD)
    testuser.save()

    _log_in(browser, user_dict['email'], password='wrongpassword')
    assert '/profile/login' in browser.url
    assert 'enter a correct email address and password' in browser.contents


def test_registration__18(db, user_dict):
    """It is not possible to send an email to someone without Profile."""
    testuser = User.objects.create_user(email=user_dict['email'], password=PWD)
    testuser.save()

    with pytest.raises(Profile.DoesNotExist):
        send_auth_mail(user_dict['email'])


def test_registration__19(browser, user_dict, mail_outbox):
    """It is possible to set a new password using email."""
    _register_user(browser, user_dict)
    _request_pwd_reset(browser, user_dict)

    assert 2 == len(mail_outbox)
    assert _get_link_url_from_email(mail_outbox, AUTH_URL)
    assert 'password change' in mail_outbox[-1].body
    assert user_dict['first_name'] in mail_outbox[-1].body


def test_registration__20(db, browser, user_dict):
    """It is not possible to send a password reset to an unknown user."""
    testuser = User.objects.create_user(email=user_dict['email'], password=PWD)
    testuser.save()

    with patch('registration.models.OKUser.objects.get') as mock:
        mock.side_effect = User.DoesNotExist()
        with pytest.raises(HTTPError, match=r'.*500.*'):
            _request_pwd_reset(browser, user_dict)


def test_registration__21(db, user_dict):
    """Users with unverified profile don't have the permission 'verified'."""
    testuser = User.objects.create_user(email=user_dict['email'], password=PWD)
    testuser.save()
    testprofile = Profile.objects.create(okuser=testuser)
    testprofile.save()

    assert not testuser.has_perm('registration.verified')


def test_registration__22(browser, user_dict, mail_outbox):
    """User can download a plain application form."""
    register_with_pwd(browser, user_dict, mail_outbox)
    _log_in(browser, user_dict['email'], PWD)
    browser.open(APPLY_URL)
    browser.getLink('Print template').click()

    assert browser.headers['Content-Type'] == 'application/pdf'
    assert user_dict['first_name'] not in pdfToText(browser.contents)
    assert user_dict['last_name'] not in pdfToText(browser.contents)


def test_registration__23(browser, user_dict, mail_outbox):
    """User can download an automatically created application form."""
    register_with_pwd(browser, user_dict, mail_outbox)
    _log_in(browser, user_dict['email'], PWD)
    browser.open(APPLY_URL)
    browser.getLink('Print registration').click()

    assert browser.headers['Content-Type'] == 'application/pdf'
    assert user_dict['first_name'] in pdfToText(browser.contents)
    assert user_dict['last_name'] in pdfToText(browser.contents)


def test_registration__24(browser, user_dict):
    """User without a profile can not create an application form."""
    testuser = User.objects.create_user(email=user_dict['email'], password=PWD)
    testuser.save()
    _log_in(browser, user_dict['email'], PWD)

    browser.open(APPLY_URL)
    assert browser.url == DOMAIN + reverse_lazy('home')
    assert f'There is no profile for {user_dict["email"]}' in browser.contents


def test_registration__25(browser, user_dict, mail_outbox):
    """Users that are verified can only change their phone number."""
    register_with_pwd(browser, user_dict, mail_outbox)
    _log_in(browser, user_dict['email'], PWD)
    testprofile = Profile.objects.get(first_name=user_dict['first_name'])
    testprofile.verified = True
    testprofile.save()
    browser.open(DOMAIN + reverse_lazy('user_data'))
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


def test__registration__views__EditProfileView__1(db, browser, user_dict):
    """It is not possible to change user data without a profile."""
    User.objects.create_user(user_dict['email'], password=PWD).save()
    _log_in(browser, user_dict['email'], PWD)
    browser.open(USER_EDIT_URL)
    assert browser.url == DOMAIN + reverse_lazy('home')
    assert 'There is no profile' in browser.contents


def test__registration__views__EditProfileView__2(browser, user):
    """A not verified user with a profile can change his/her data."""
    _log_in(browser, user.email, PWD)
    browser.open(USER_EDIT_URL)
    new_name = 'new_name'
    browser.getControl(name='first_name').value = new_name
    browser.getControl('Submit').click()
    assert 'successfully updated' in browser.contents
    assert User.objects.get(email=user.email).profile.first_name == new_name


def test__registration__views__EditProfileView__3(browser, user):
    """The edit form gets validated."""
    _log_in(browser, user.email, PWD)
    browser.open(USER_EDIT_URL)
    browser.getControl(name='email').value = 'invalid_email'
    browser.getControl('Submit').click()
    assert browser.url == USER_EDIT_URL
    assert 'Enter a valid email address' in browser.contents


def test__registration__views__EditProfileView__4(browser, user):
    """The email address needs to be unique."""
    used_email = 'used@example.com'
    User.objects.create_user(used_email, password=PWD)
    _log_in(browser, user.email, PWD)

    browser.open(USER_EDIT_URL)
    browser.getControl(name='email').value = used_email
    browser.getControl('Submit').click()

    assert browser.url == USER_EDIT_URL
    assert 'already exists.' in browser.contents


def test__registration__views__EditProfileView__5(browser):
    """The edit profile site is for logged in users only."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(USER_EDIT_URL)


def test__registration__views__EditProfileView__6(browser, user):
    """It is possible to edit the email address."""
    _log_in(browser, user.email, PWD)
    new_email = 'new_'+user.email

    browser.open(USER_EDIT_URL)
    browser.getControl(name='email').value = new_email
    browser.getControl('Submit').click()

    assert 'successfully updated' in browser.contents
    assert User.objects.get(email=new_email)


def test__registration__views__PrintRegistrationView__1(browser):
    """It raises a 404 in case the user is not logged in."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(APPLY_URL)


def test__registration__views__RegistrationFilledFormFile__1(
        browser, user_dict):
    """It redirects to the previous page if the user don't has a profile."""
    User.objects.create_user(user_dict['email'], password=PWD)
    _log_in(browser, user_dict['email'], password=PWD)
    browser.open(DOMAIN + reverse_lazy('registration_filled_file'))
    assert DOMAIN + reverse_lazy('home') == browser.url
    assert 'There is no profile' in browser.contents


def test__registration__views_RegistrationFilledFormFile__2(browser):
    """It raises a 404 in case the user is not logged in."""
    with pytest.raises(HTTPError, match=r'.*404.*'):
        browser.open(DOMAIN + reverse_lazy('registration_filled_file'))


def test__registration__views_RegistrationPlainFormFile__1(browser):
    """It is always possible to access the plain registration form."""
    browser.open(DOMAIN + reverse_lazy('registration_plain_file'))
    assert browser.headers['Content-Type'] == 'application/pdf'


# Helper functions


def register_with_pwd(browser, user_dict: dict, mail_outbox, password=PWD):
    """Register the given user and set a password."""
    _register_user(browser, user_dict)
    assert 1 == len(mail_outbox)
    pw_url = _get_link_url_from_email(mail_outbox, AUTH_URL)

    browser.open(pw_url)
    browser.getControl('New password', index=0).value = password
    browser.getControl('confirmation').value = password
    browser.getControl('Change').click()

    assert '/profile/reset/done' in browser.url
    assert 'Password reset complete' in browser.contents


def _register_user(browser, user_dict: dict):
    """
    Register a user defined by the given dictionary.

    The entries of the user dictionary correspond to the fields defined
    in models.py for user and profile.
    """
    browser.open(REGISTER_URL)
    assert '/register/' in browser.url, \
        f'Not on register page, URL is {browser.url}'

    browser.getControl('Email').value = user_dict['email']
    browser.getControl('First name').value = user_dict['first_name']
    browser.getControl('Last name').value = user_dict['last_name']
    browser.getControl('Gender').value = user_dict['gender']
    browser.getControl('Phone number').value = user_dict['phone_number']
    browser.getControl('Mobile number').value = user_dict['mobile_number']
    browser.getControl('Birthday').value = user_dict['birthday']
    browser.getControl('Street').value = user_dict['street']
    browser.getControl('House number').value = user_dict['house_number']
    browser.getControl('Zipcode').value = user_dict['zipcode']
    browser.getControl('City').value = user_dict['city']
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


def _request_pwd_reset(browser, user_dict):
    """Request an email to reset the password."""
    browser.open(PWD_RESET_URL)
    assert PWD_RESET_URL in browser.url
    assert 'Change Password' in browser.contents

    browser.getControl('Email').value = user_dict['email']
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
