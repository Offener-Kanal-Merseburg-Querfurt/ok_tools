
def test__contributions__admin__ContributionsAdmin__1(browser, contribution):
    """Contributions get shown in the admin interface."""
    browser.login_admin()
    browser.follow(url="/admin/contributions/contribution")

    assert str(contribution) in browser.contents
    assert contribution.license.profile.first_name in browser.contents
    assert contribution.license.profile.last_name in browser.contents
