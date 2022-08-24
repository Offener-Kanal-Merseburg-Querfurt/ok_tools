from .models import MediaEducationSupervisor
from .models import Project
from .models import ProjectCategory
from .models import ProjectLeader
from .models import TargetGroup
from datetime import timedelta
from django import forms
import pytest


def test__admin__1(browser):
    """It is possible to add project and project deps."""
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
    browser.open(f'{base_url}projects/project/add')
    browser.getControl(name='_save').click()


def test__admin__2(db):
    """Participant number fields are validated."""
    pc = ProjectCategory.objects.create(name='Foo1')
    pl = ProjectLeader.objects.create(name='blah')
    tg = TargetGroup.objects.create(name='tg1')
    mes = MediaEducationSupervisor.objects.create(name='fupp')
    proj = Project.objects.create(
        project_category=pc,
        project_leader=pl,
        media_education_supervisor=mes,
        target_group=tg,
        duration=timedelta(days=1),
        external_venue=False,
        jugendmedienschutz=False
    )
    proj.tn_0_bis_6 = 2
    proj.tn_7_bis_10 = 2
    proj.tn_female = 3
    with pytest.raises(forms.ValidationError):
        proj.clean()
    proj.tn_male = 1
    proj.clean()
