from .models import Profile
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from ok_tools.testing import pdfToText
import pytest
import registration.signals


User = get_user_model()

PWD = 'testpassword'
VERIFIED_PERM = 'registration.verified'
LOGIN_URL = 'http://localhost/admin'


def test_admin__1(browser):
    """It is possible to log in as a valid admin user."""
    _login(browser)
    assert 'Site administration' in browser.contents
    assert browser.url == 'http://localhost/admin/'


def test_admin__2(db, user_dict):
    """A staff member has the permission 'verified'."""
    testuser = User(email=user_dict['email'], password=PWD, is_staff=True)
    testuser.save()

    assert testuser.has_perm(VERIFIED_PERM)


def test_admin__3(db, user_dict, browser):
    """After verification a user has the permission 'verified'."""
    _create_user(db, user_dict)
    _login(browser)
    browser.getLink('Profiles').click()
    browser.getLink(user_dict['email']).click()
    browser.getControl('Verified').selected = True
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user_dict['email'])
    assert testuser.has_perm(VERIFIED_PERM)


def test_admin__4(db, user_dict, browser):
    """A User created as verified has the permission 'verified'."""
    _create_user(db, user_dict, verified=True)
    testuser = User.objects.get(email=user_dict['email'])
    assert testuser.has_perm(VERIFIED_PERM)


def test_admin__5(db, user_dict, browser):
    """If a user is no longer verified the permission gets revoked."""
    _create_user(db, user_dict, verified=True)
    _login(browser)

    browser.getLink('Profiles').click()
    browser.getLink(user_dict['email']).click()
    browser.getControl('Verified').selected = False
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user_dict['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__6(db, user_dict, browser):
    """If a user gets staff status he/she has the permission 'verified'."""
    _create_user(db, user_dict, verified=True)
    _login(browser)

    browser.getLink('User').click()
    browser.getLink(user_dict['email']).click()
    browser.getControl('Staff status').click()
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user_dict['email'])
    assert testuser.has_perm(VERIFIED_PERM)


def test_admin__7(db, user_dict, browser):
    """If a user is no longer staff, the permission 'verified' gets revoked."""
    _create_user(db, user_dict, is_staff=True)
    _login(browser)

    browser.getLink('User').click()
    browser.getLink(user_dict['email']).click()
    browser.getControl('Staff status').click()
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user_dict['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__8(db):
    """
    Helper function '_get_permission'.

    The function raises an error if Permission does not exist.
    """
    with pytest.raises(Permission.DoesNotExist):
        registration.signals._get_permission(Profile, 'testpermission')


def test_admin__9(db, user_dict, browser):
    """Modify a user without a change."""
    _create_user(db, user_dict)
    _login(browser)

    browser.getLink('User').click()
    browser.getLink(user_dict['email']).click()
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user_dict['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__10(db, user_dict, browser):
    """Modify a user with a change which not changes staff status."""
    _create_user(db, user_dict)
    _login(browser)

    browser.getLink('User').click()
    browser.getLink(user_dict['email']).click()
    user_dict['email'] = 'new_'+user_dict['email']
    browser.getControl('Email').value = user_dict['email']
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user_dict['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__11(db, user_dict, browser):
    """Modify a profile without a change."""
    _create_user(db, user_dict)
    _login(browser)

    browser.getLink('Profile').click()
    browser.getLink(user_dict['email']).click()
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user_dict['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__12(db, user_dict, browser):
    """Modify a profile without changing 'verified'."""
    _create_user(db, user_dict)
    _login(browser)

    browser.getLink('Profile').click()
    browser.getLink(user_dict['email']).click()
    browser.getControl('First name').value = 'new_'+user_dict['first_name']
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user_dict['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__13(db, user_dict, browser):
    """Verify multiple users."""
    first_email = user_dict['email']
    _create_user(db, user_dict)
    second_email = 'second_' + user_dict['email']
    user_dict['email'] = second_email
    _create_user(db, user_dict)
    _login(browser)

    browser.getLink('Profile').click()

    # select both profiles
    browser.getControl(name='_selected_action').controls[0].selected = True
    browser.getControl(name='_selected_action').controls[1].selected = True

    browser.getControl('Action').value = 'verify'
    browser.getControl('Go').click()

    first_user = User.objects.get(email=first_email)
    second_user = User.objects.get(email=second_email)

    assert first_user.profile.verified
    assert second_user.profile.verified
    assert 'successfully verified' in browser.contents


def test_admin__14(db, user_dict, browser):
    """Unverify multiple users."""
    first_email = user_dict['email']
    _create_user(db, user_dict, verified=True)
    second_email = 'second_' + user_dict['email']
    user_dict['email'] = second_email
    _create_user(db, user_dict, verified=True)
    _login(browser)

    browser.getLink('Profile').click()

    # select both profiles
    browser.getControl(name='_selected_action').controls[0].selected = True
    browser.getControl(name='_selected_action').controls[1].selected = True

    browser.getControl('Action').value = 'unverify'
    browser.getControl('Go').click()

    first_user = User.objects.get(email=first_email)
    second_user = User.objects.get(email=second_email)

    assert not first_user.profile.verified
    assert not second_user.profile.verified
    assert 'successfully unverified' in browser.contents


def test__admin__15(db, user_dict, browser):
    """Print application form."""
    _create_user(db, user_dict)
    _login(browser)

    browser.getLink('Profile').click()
    browser.getLink(user_dict['email']).click()
    browser.getControl('Print').click()

    assert browser.headers['Content-Type'] == 'application/pdf'
    assert user_dict['first_name'] in pdfToText(browser.contents)
    assert user_dict['last_name'] in pdfToText(browser.contents)


def _create_user(db, user_dict, verified=False, is_staff=False):
    """Create a user with corresponding profile."""
    testuser = User(email=user_dict['email'], password=PWD, is_staff=is_staff)
    testuser.save()
    Profile(okuser=testuser,
            first_name=user_dict['first_name'],
            last_name=user_dict['last_name'],
            street=user_dict['street'],
            house_number=user_dict['house_number'],
            verified=verified
            ).save()


def _login(browser):
    """Log in to admin site with superuser."""
    browser.open(LOGIN_URL)
    browser.login_admin()
