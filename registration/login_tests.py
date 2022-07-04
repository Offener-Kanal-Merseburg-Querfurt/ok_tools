def test_login__1(browser):
    """It is possible to log in as a valid admin user."""
    browser.open('http://localhost/admin')
    browser.login_admin()
    assert 'Authentication and Authorization' in browser.contents
    assert browser.url == 'http://localhost/admin/'
