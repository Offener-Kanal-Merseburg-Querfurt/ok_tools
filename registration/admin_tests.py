from .admin import BirthmonthFilter
from .admin import Profile
from .admin import ProfileAdmin
from .admin import YearFilter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from ok_tools.datetime import TZ
from ok_tools.testing import DOMAIN
from ok_tools.testing import create_user
from ok_tools.testing import pdfToText
from unittest.mock import patch
import datetime
import pytest


User = get_user_model()

PWD = 'testpassword'

LIST_URL = (f'{DOMAIN}'
            f'{reverse_lazy("admin:registration_profile_changelist")}')


def a_change_url(id):
    """Return admin change url."""
    return (
        f'{DOMAIN}'
        f'{reverse_lazy("admin:registration_profile_change", args=[id])}'
    )


def test__registration__admin__1(browser):
    """It is possible to log in as a valid admin user."""
    browser.login_admin()
    assert 'Site administration' in browser.contents
    assert browser.url == f'{DOMAIN}/admin/'


def test__registration__admin__2(browser, user_dict):
    """Create a user using the admin interface."""
    password = 'userpassword'

    browser.login_admin()
    browser.follow('Users')
    browser.follow('Add User')

    browser.getControl('Email').value = user_dict['email']
    browser.getControl('Password:').value = password
    browser.getControl(name='password2').value = password
    browser.getControl(name='_save').click()

    assert 'was added successfully' in browser.contents
    assert user_dict['email'] in browser.contents
    assert User.objects.get(email=user_dict['email'])


def test__registration__signals__send_verification_mail__1(
        db, user, browser, mail_outbox):
    """After verification a user gets send an email."""
    assert 0 == len(mail_outbox)
    browser.login_admin()
    browser.getLink('Profiles').click()
    browser.getLink(user.email).click()
    browser.getControl('Verified').selected = True
    browser.getControl(name='_save').click()

    assert 1 == len(mail_outbox)
    assert 'has been verified' in mail_outbox[-1].subject
    assert (
        'We have received your application and verified your data. Your'
        ' account is now fully activated.' in mail_outbox[-1].body
    )
    assert user.profile.first_name in mail_outbox[-1].body


def test__registration__admin__ProfileAdmin__3(db, user_dict, browser):
    """Create a profile using the admin interface."""
    user = User.objects.create_user(user_dict['email'], password=PWD)

    browser.login_admin()
    browser.follow('Profile')
    browser.follow('Add Profile')

    browser.getControl(name='okuser')._control.force_value(
        user.id)  # select user
    browser.getControl('First name').value = user_dict['first_name']
    browser.getControl('Last name').value = user_dict['last_name']
    browser.getControl('Birthday').value = datetime.datetime.strptime(
        user_dict['birthday'], settings.DATE_INPUT_FORMATS).date(),
    browser.getControl('Street').value = user_dict['street']
    browser.getControl('House number').value = user_dict['house_number']
    browser.getControl(name='_save').click()

    assert "was added successfully" in browser.contents
    assert Profile.objects.get(first_name=user_dict['first_name'])


def test__registration__admin__ProfileAdmin__4(db, user_dict):
    """Filter profiles by birth month."""
    user_dict['birthday'] = '05.01.1989'
    birthday = create_user(user_dict)

    user_dict['email'] = f'new_{user_dict["email"]}'
    user_dict['birthday'] = '05.02.1989'
    no_birthday = create_user(user_dict)

    with patch.object(BirthmonthFilter, 'value', return_value='1'):
        filter = BirthmonthFilter(
            {}, {}, Profile, ProfileAdmin)
        profiles = filter.queryset(None, Profile.objects.all())

    assert birthday.profile in profiles
    assert no_birthday.profile not in profiles


def test__registration__admin__ProfileAdmin__5():
    """Handle invalid int values."""
    with patch.object(BirthmonthFilter, 'value', return_value='13'):
        with pytest.raises(ValueError, match=r'Unsupported filter option .*'):
            filter = BirthmonthFilter(
                {}, {}, Profile, ProfileAdmin)
            filter.queryset(None, None)

    with patch.object(BirthmonthFilter, 'value', return_value='0'):
        with pytest.raises(ValueError, match=r'Unsupported filter option .*'):
            filter = BirthmonthFilter(
                {}, {}, Profile, ProfileAdmin)
            filter.queryset(None, None)


def test__registration__admin__ProfileAdmin__6():
    """Handle invalid values that are not of type int."""
    with patch.object(BirthmonthFilter, 'value', return_value='3.5'):
        with pytest.raises(ValueError, match=r'Unsupported filter option .*'):
            filter = BirthmonthFilter(
                {}, {}, Profile, ProfileAdmin)
            filter.queryset(None, None)


def test__registration__admin__ProfileAdmin__7(browser, user):
    """The verification of a user can be revoked."""
    profile: Profile = user.profile
    profile.verified = True
    profile.save()

    browser.login_admin()
    browser.open(a_change_url(profile.id))
    browser.getControl('Verified').click()
    browser.getControl(name='_save').click()

    assert not Profile.objects.get(id=profile.id).verified


def test__registration__admin__verify__1(
        db, user, user_dict, browser, mail_outbox):
    """Verify multiple users."""
    assert 0 == len(mail_outbox)
    first_email = user.email
    second_email = 'second_' + user_dict['email']
    user_dict['email'] = second_email
    create_user(user_dict)
    browser.login_admin()

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
    assert '2 profiles were successfully verified' in browser.contents
    assert 2 == len(mail_outbox)


def test__registration__admin__verify__2(
        db, user, user_dict, browser, mail_outbox):
    """It sets the attribute and sends email only if it was unverified."""
    assert 0 == len(mail_outbox)
    first_email = user.email
    second_email = 'second_' + user_dict['email']
    user_dict['email'] = second_email
    create_user(user_dict)
    user.profile.verified = True
    user.profile.save()

    browser.login_admin()

    browser.getLink('Profile').click()

    # select both profiles
    browser.getControl(name='_selected_action').controls[0].selected = True
    browser.getControl(name='_selected_action').controls[1].selected = True

    browser.getControl('Action').value = 'verify'
    browser.getControl('Go').click()

    first_user = User.objects.get(email=first_email)
    second_user = User.objects.get(email=second_email)

    # The first user is still verified but did not get an email.
    assert first_user.profile.verified
    assert second_user.profile.verified
    assert '1 profile was successfully verified' in browser.contents
    assert 1 == len(mail_outbox)


def test__registration__admin__unverify__1(db, user_dict, browser):
    """Unverify multiple users."""
    first_email = user_dict['email']
    create_user(user_dict, verified=True)
    second_email = 'second_' + user_dict['email']
    user_dict['email'] = second_email
    create_user(user_dict, verified=True)
    browser.login_admin()

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


def test__registration__admin__response_change__1(db, user, browser):
    """Print application form."""
    browser.login_admin()

    browser.getLink('Profile').click()
    browser.getLink(user.email).click()
    browser.getControl('Print').click()

    assert browser.headers['Content-Type'] == 'application/pdf'
    assert user.profile.first_name in pdfToText(browser.contents)
    assert user.profile.last_name in pdfToText(browser.contents)


def test__registration__admin__YearFilter__1(browser, user_dict):
    """Filter profiles after creation year."""
    year = datetime.datetime.now().year

    user_dict['email'] = 'user1@example.com'
    user1 = create_user(user_dict)
    user1.save()

    user_dict['email'] = 'user2@example.com'
    user2 = create_user(user_dict)
    user2.profile.created_at = datetime.datetime.now().replace(
        year=year-1, tzinfo=TZ)
    user2.profile.save()

    browser.login_admin()
    browser.open(LIST_URL)

    browser.follow('This year')
    assert user1.email in str(browser.contents)
    assert user2.email not in str(browser.contents)

    browser.follow('Last year')
    assert user1.email not in str(browser.contents)
    assert user2.email in str(browser.contents)


def test__registration__admin__YearFilter__2():
    """Handle invalid values."""
    with patch.object(YearFilter, 'value', return_value='invalid'):
        with pytest.raises(ValueError, match=r'Invalid value .*'):
            filter = YearFilter(
                {}, {}, Profile, ProfileAdmin)
            filter.queryset(None, None)


def test__registration__admin__ProfileResource__1(browser, user_dict):
    """Export profiles."""
    user_dict['phone_number'] = '0123456789'
    user_dict['mobile_number'] = '+49123456789'
    user: User = create_user(user_dict)
    profile: Profile = user.profile
    browser.login_admin()
    browser.open(LIST_URL)

    browser.follow('Export')
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    export = str(browser.contents)
    assert str(profile.first_name) in export
    assert str(profile.last_name) in export
    assert str(profile.gender) in export
    assert str(user.email) in export
    assert str(profile.phone_number) in export
    assert str(profile.mobile_number) in export
    assert str(profile.birthday) in export
    assert str(profile.street) in export
    assert str(profile.house_number) in export
    assert str(profile.zipcode) in export
    assert str(profile.city) in export
    created_at = profile.created_at.astimezone(TZ)
    assert str(created_at.date()) in export
    assert str(created_at.time()) in export
    assert str(profile.member) in export
    assert str(profile.media_authority) in export
