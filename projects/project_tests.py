from .admin import ProjectAdmin
from .admin import YearFilter
from .models import MediaEducationSupervisor
from .models import Project
from .models import ProjectCategory
from .models import ProjectLeader
from .models import TargetGroup
from datetime import date
from datetime import datetime
from datetime import timedelta
from django import forms
from django.urls import reverse_lazy
from ok_tools.testing import DOMAIN
from ok_tools.testing import create_project
from unittest.mock import patch
import pytest


A_PROJ_URL = f'{DOMAIN}{reverse_lazy("admin:projects_project_changelist")}'


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
        target_group=tg,
        date=date(year=2022, month=9, day=27),
        duration=timedelta(days=1),
        external_venue=False,
        jugendmedienschutz=False
    )
    proj.media_education_supervisors.add(mes.id)
    proj.tn_0_bis_6 = 2
    proj.tn_7_bis_10 = 2
    proj.tn_female = 3
    with pytest.raises(forms.ValidationError):
        proj.clean()
    proj.tn_male = 1
    proj.clean()


def test__projects__admin__YearFilter__1(browser, project_dict):
    """Projects can be filtered by the year of the start date."""
    project_dict['title'] = 'new_title'
    project_dict['date'] = date(year=datetime.now().year, month=9, day=20)
    proj1 = create_project(project_dict)

    project_dict['title'] = 'old_title'
    project_dict['date'] = date(year=datetime.now().year-1, month=9, day=20)
    proj2 = create_project(project_dict)

    browser.login_admin()
    browser.open(A_PROJ_URL)

    browser.follow('This year')
    assert proj1.title in browser.contents
    assert proj2.title not in browser.contents

    browser.follow('Last year')
    assert proj1.title not in browser.contents
    assert proj2.title in browser.contents


def test__projects__admin__YearFilter__2():
    """Handle invalid values."""
    with patch.object(YearFilter, 'value', return_value='invalid'):
        with pytest.raises(ValueError, match=r'Invalid value .*'):
            filter = YearFilter(
                {}, {}, Project, ProjectAdmin)
            filter.queryset(None, None)


def test__projects__admin__ProjectResource__1(browser, project_dict):
    """Export projects."""
    s1 = MediaEducationSupervisor.objects.create(name='supervisor1')
    s2 = MediaEducationSupervisor.objects.create(name='supervisor2')
    supervisors = [s1, s2]

    create_project(project_dict, supervisors)

    browser.login_admin()
    browser.open(A_PROJ_URL)

    browser.follow('Export')
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    assert str(s1) in str(browser.contents)
    assert str(s2) in str(browser.contents)


def test__projects__admin__ProjectResource__2(browser, project_dict):
    """Export all necessary data."""
    project: Project = create_project(project_dict)
    browser.login_admin()
    browser.open(A_PROJ_URL)

    browser.follow('Export')
    browser.getControl('csv').click()
    browser.getControl('Submit').click()

    assert browser.headers['Content-Type'] == 'text/csv'
    export = str(browser.contents)
    assert project.title in export
    assert project.topic in export
    assert str(project.date) in export
    assert str(project.duration) in export
    assert str(project.external_venue) in export
    assert str(project.jugendmedienschutz) in export
    assert str(project.target_group) in export
    assert str(project.project_category) in export
    assert str(project.project_leader) in export


def test__projects__models__1(db, project):
    """Project gets represented by its title."""
    assert str(project) == project.title


def test__projects__admin__ProjectAdmin__1(browser, project):
    """Export the projects date to ics."""
    browser.login_admin()
    browser.open(A_PROJ_URL)
    browser.follow('Export dates')
    assert browser.headers['Content-Type'] == 'text/calendar'
    assert project.title in str(browser.contents)
    assert _f_ics_date(project.date) in str(browser.contents)
    assert project.topic in str(browser.contents)


def test__projects__admin__ProjectAdmin__2(browser, project_dict):
    """Export the projects date of this year to ics."""
    project_dict['date'] = date(
        year=datetime.now().year,
        month=9,
        day=26
    )
    project_dict['title'] = 'new_project'
    proj1 = create_project(project_dict)

    project_dict['date'] = date(
        year=datetime.now().year-1,
        month=9,
        day=26
    )
    project_dict['title'] = 'old_project'
    proj2 = create_project(project_dict)

    browser.login_admin()
    browser.open(A_PROJ_URL)
    browser.follow('This year')
    browser.follow('Export dates')

    assert browser.headers['Content-Type'] == 'text/calendar'
    assert proj1.title in str(browser.contents)
    assert proj2.title not in str(browser.contents)


def test__projects__admin__ProjectAdmin__3(browser, project):
    """Export the project date without accessing the admin site."""
    browser.login_admin()
    browser.open(f'{DOMAIN}{reverse_lazy("admin:calender_export")}')

    assert browser.headers['Content-Type'] == 'text/calendar'
    assert project.title in str(browser.contents)


def test__projects__admin__ProjectAdmin__4(browser, project):
    """The export dates button only appears on the project site."""
    browser.login_admin()
    browser.open(f'{DOMAIN}{reverse_lazy("contributions:contributions")}')

    assert 'Export dates' not in browser.contents


def test__projects__admin__ProjectAdmin__5(browser, project, user):
    """It is possible to download project dates without staff rights."""
    browser.login()
    browser.open(f'{DOMAIN}{reverse_lazy("admin:calender_export")}')
    assert browser.headers['Content-Type'] == 'text/calendar'


def test__projects__admin__ProjectAdmin__6(browser, project_dict):
    """The duration and end_date does not match."""
    project_dict['date'] = datetime(
        year=2022,
        month=9,
        day=3
    )
    project_dict['duration'] = timedelta(hours=1, minutes=30)

    project = create_project(project_dict)

    browser.login_admin()
    browser.open(A_PROJ_URL)
    browser.follow('Export dates')

    assert browser.headers['Content-Type'] == 'text/calendar'
    assert _f_ics_date(project.date) in str(browser.contents)


def _f_ics_date(dt: date):
    """Convert date objects to ics format."""
    return dt.strftime('DATE:%Y%m%d')
