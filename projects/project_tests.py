from .models import Project
from ok_tools.testing import DOMAIN
import pytest


def test__admin__1(browser):
    """It is possible to add project data."""
    browser.login_admin()
    base_url = browser.url
    browser.open(f'{base_url}projects/projectleader/add')
    browser.getControl('name').value = 'Hans im Glück'
    browser.getControl(name='_save').click()
    browser.open(f'{base_url}projects/mediaeducationsupervisor/add')
    browser.getControl('name').value = 'Heinz im Glück'
    browser.getControl(name='_save').click()
    browser.open(f'{base_url}projects/projectcategory/add')
    browser.getControl('Project category').value = 'Hauptkategorie'
    browser.getControl(name='_save').click()
    browser.open(f'{base_url}projects/targetgroup/add')
    browser.getControl('Target group').value = 'Die wichtige Zielgruppe'
    browser.getControl(name='_save').click()


def test__admin__2(browser):
    """Participant number fields are validated."""
    browser.login_admin()
    base_url = browser.url
    browser.open(f'{base_url}projects/project/add')
    browser.getControl('bis 6 Jahre').value = "1"
    browser.getControl('7 bis 14 Jahre').value = "1"
    browser.getControl('weiblich').value = "3"
    browser.getControl(name='_save').click()
    assert 'The sum of participants by age (2) does not match the sum of participants by gender (3). Please correct your data.' in browser.contents
