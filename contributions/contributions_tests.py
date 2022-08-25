
def test__contributions__admin__ContributionsAdmin__1(browser, contribution):
    """Contributions get shown in the admin interface."""
    browser.login_admin()
    browser.follow(url="/admin/contributions/contribution")

    open('response.html', 'w').write(browser.contents)
    assert str(contribution) in browser.contents
    assert contribution.license.okuser.first_name in browser.contents
    assert contribution.license.okuser.last_name in browser.contents
