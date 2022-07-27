from .models import Profile
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
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


def test_admin__2(db, user):
    """A staff member has the permission 'verified'."""
    testuser = User(email=user['email'], password=PWD, is_staff=True)
    testuser.save()

    assert testuser.has_perm(VERIFIED_PERM)


def test_admin__3(db, user, browser):
    """After verification a user has the permission 'verified'."""
    _create_user(db, user)
    _login(browser)
    browser.getLink('Profiles').click()
    browser.getLink(user['email']).click()
    browser.getControl('Verified').selected = True
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user['email'])
    assert testuser.has_perm(VERIFIED_PERM)


def test_admin__4(db, user, browser):
    """A User created as verified has the permission 'verified'."""
    _create_user(db, user, verified=True)
    testuser = User.objects.get(email=user['email'])
    assert testuser.has_perm(VERIFIED_PERM)


def test_admin__5(db, user, browser):
    """If a user is no longer verified the permission gets revoked."""
    _create_user(db, user, verified=True)
    _login(browser)

    browser.getLink('Profiles').click()
    browser.getLink(user['email']).click()
    browser.getControl('Verified').selected = False
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__6(db, user, browser):
    """If a user gets staff status he/she has the permission 'verified'."""
    _create_user(db, user, verified=True)
    _login(browser)

    browser.getLink('User').click()
    browser.getLink(user['email']).click()
    browser.getControl('Staff status').click()
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user['email'])
    assert testuser.has_perm(VERIFIED_PERM)


def test_admin__7(db, user, browser):
    """If a user is no longer staff, the permission 'verified' gets revoked."""
    _create_user(db, user, is_staff=True)
    _login(browser)

    browser.getLink('User').click()
    browser.getLink(user['email']).click()
    browser.getControl('Staff status').click()
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__8(db):
    """
    Helper function '_get_permission'.

    The function raises an error if Permission does not exist.
    """
    with pytest.raises(Permission.DoesNotExist):
        registration.signals._get_permission(Profile, 'testpermission')


def test_admin__9(db, user, browser):
    """Modify a user without a change."""
    _create_user(db, user)
    _login(browser)

    browser.getLink('User').click()
    browser.getLink(user['email']).click()
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__10(db, user, browser):
    """Modify a user with a change which not changes staff status."""
    _create_user(db, user)
    _login(browser)

    browser.getLink('User').click()
    browser.getLink(user['email']).click()
    user['email'] = 'new_'+user['email']
    browser.getControl('Email').value = user['email']
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__11(db, user, browser):
    """Modify a profile without a change."""
    _create_user(db, user)
    _login(browser)

    browser.getLink('Profile').click()
    browser.getLink(user['email']).click()
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__12(db, user, browser):
    """Modify a profile without changing 'verified'."""
    _create_user(db, user)
    _login(browser)

    browser.getLink('Profile').click()
    browser.getLink(user['email']).click()
    browser.getControl('First name').value = 'new_'+user['first_name']
    browser.getControl(name='_save').click()

    testuser = User.objects.get(email=user['email'])
    assert not testuser.has_perm(VERIFIED_PERM)


def test_admin__13(db, user, browser):
    """Verify multiple users."""
    first_email = user['email']
    _create_user(db, user)
    second_email = 'second_' + user['email']
    user['email'] = second_email
    _create_user(db, user)
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


def test_admin__14(db, user, browser):
    """Unverify multiple users."""
    first_email = user['email']
    _create_user(db, user, verified=True)
    second_email = 'second_' + user['email']
    user['email'] = second_email
    _create_user(db, user, verified=True)
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


def _create_user(db, user, verified=False, is_staff=False):
    """Create a user with corresponding profile."""
    testuser = User(email=user['email'], password=PWD, is_staff=is_staff)
    testuser.save()
    Profile(okuser=testuser,
            first_name=user['first_name'],
            last_name=user['last_name'],
            street=user['street'],
            house_number=user['house_number'],
            verified=verified
            ).save()


def _login(browser):
    """Log in to admin site with superuser."""
    browser.open(LOGIN_URL)
    browser.login_admin()
