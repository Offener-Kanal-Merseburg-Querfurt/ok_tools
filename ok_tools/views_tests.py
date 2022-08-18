def test_views__home__1(browser, user):
    """It welcomes the user and allows a password change."""
    browser.login()
    assert f'Hi {user.email}!' in browser.contents
    browser.follow('Change password')
    assert 'password_reset' in browser.url


def test_views__home__2(browser, user):
    """It shows a message if the account is not verified."""
    browser.handleErrors = False
    browser.login()
    assert (
        'This account is not verified. Please print the application form, sign'
        ' it and send it back to us. The account will then be verified.'
        in browser.contents
    )
    browser.follow('Application form')
    assert 'profile/application' in browser.url


def test_views__home__3(browser, user):
    """It shows no message if the account is verified."""
    user.profile.verified = True
    user.profile.save()
    browser.login()
    assert 'This account is not verified.' not in browser.contents
    assert 'This account is verified.' in browser.contents
