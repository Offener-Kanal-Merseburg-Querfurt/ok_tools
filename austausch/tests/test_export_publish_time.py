"""Publish time chosen per license on the export-to-server page."""
from austausch.models import ExchangeConfig
from austausch.services.export_to_server_service import ExportToServerService
from austausch.services.export_to_server_service import PUBLISH_NOW
from austausch.tasks import export_to_server_task
from contributions.models import Contribution
from datetime import date
from datetime import datetime
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from licenses.models import License
from licenses.services.peertube_service import compute_publish_time_for_license
from licenses.services.peertube_service import compute_publish_times_for_licenses
from planung.models import TagesPlan
from unittest.mock import Mock
from unittest.mock import patch
import pytest
import tempfile


def _aware(*args):
    return timezone.make_aware(datetime(*args))


def _plan(day, number, start, planned=True):
    return TagesPlan.objects.create(
        datum=day,
        json_plan={
            'items': [{'number': number, 'start': start}],
            'draft': not planned,
            'planned': planned,
        },
    )


# --- suggestion: compute_publish_times_for_licenses -------------------------

@pytest.mark.django_db
def test_suggestion_prefers_first_contribution(license):
    """The first broadcast wins over Planung, as in the JSON metadata."""
    Contribution.objects.create(
        license=license, broadcast_date=_aware(2026, 3, 2, 20, 0), live=False)
    Contribution.objects.create(
        license=license, broadcast_date=_aware(2026, 3, 1, 18, 30), live=False)
    _plan(date(2026, 2, 1), license.number, '10:00')

    found = compute_publish_times_for_licenses([license.number])

    assert found[license.number] == (_aware(2026, 3, 1, 18, 30), 'contribution')


@pytest.mark.django_db
def test_suggestion_falls_back_to_earliest_planned_plan(license):
    """Without a broadcast the earliest planned (not draft) plan is used."""
    _plan(date(2026, 4, 1), license.number, '09:00', planned=False)
    _plan(date(2026, 4, 3), license.number, '19:15')
    _plan(date(2026, 4, 5), license.number, '08:00')

    found = compute_publish_times_for_licenses([license.number])

    assert found[license.number] == (_aware(2026, 4, 3, 19, 15), 'planung')
    assert compute_publish_time_for_license(license) == _aware(2026, 4, 3, 19, 15)


@pytest.mark.django_db
def test_suggestion_leaves_out_licenses_without_time(license):
    """No broadcast, no plan: no suggestion, and the single helper gives None."""
    assert compute_publish_times_for_licenses([license.number, 999999]) == {}
    assert compute_publish_time_for_license(license) is None


# --- service: the chosen time ends up in originallyPublishedAt --------------

@pytest.fixture
def export_service():
    config = ExchangeConfig.get_config()
    config.nextcloud_base_url = 'https://cloud.example.com'
    config.nextcloud_username = 'test_user'
    config.nextcloud_password = 'test_pass'
    config.export_destination = 'network_share'
    config.network_share_base_path = tempfile.mkdtemp(prefix='austausch_publish_')
    config.download_storage_path = config.network_share_base_path
    config.network_share_subfolder = ''
    config.upload_thumbnail_enabled = False
    config.save()
    return ExportToServerService()


@pytest.mark.django_db
def test_run_resolves_now_and_passes_explicit_times(export_service):
    """'now' becomes the export moment; an explicit time is passed as is."""
    export_service._validate_destination = Mock(return_value=True)
    export_service._export_one = Mock(
        side_effect=lambda item_id, mode, publish_time=None: ('success', item_id, None))
    fixed_now = _aware(2026, 11, 6, 14, 5, 30)

    with patch('austausch.services.export_to_server_service.timezone.now',
               return_value=fixed_now):
        report = export_service.run(
            selected_ids=[1, 2, 3], mode='licenses',
            publish_at={'1': PUBLISH_NOW, '2': '2026-12-24T18:00:00+01:00'})

    calls = {c.args[0]: c.kwargs['publish_time']
             for c in export_service._export_one.call_args_list}
    assert calls[1] == timezone.localtime(fixed_now).isoformat()
    assert calls[2] == '2026-12-24T18:00:00+01:00'
    assert calls[3] is None
    assert report['publish_times'] == {'1': calls[1], '2': calls[2]}


@pytest.mark.django_db
def test_export_one_writes_the_chosen_time_into_the_json(export_service, license):
    """The page's time replaces the broadcast time in the exported JSON."""
    Contribution.objects.create(
        license=license, broadcast_date=_aware(2026, 3, 1, 18, 30), live=False)
    video = Mock(filename='video.mp4', storage_location=Mock(), full_path='/x/video.mp4')
    written = {}

    def capture_json(meta, base, name):
        written.update(meta)
        return True

    export_service._select_export_source = Mock(return_value=(video, None))
    export_service._upload_or_copy_file = Mock(return_value=True)
    export_service._write_pdf_to_destination = Mock(return_value=True)
    export_service._write_json_to_destination = Mock(side_effect=capture_json)

    with patch.object(License, 'get_video_file', return_value=video), \
            patch.object(License, 'has_any_signature', return_value=True), \
            patch('licenses.generate_file.generate_license_pdf_bytes', return_value=b'%PDF'):
        status, _, reason = export_service._export_one(
            license.number, 'licenses', publish_time='2026-12-24T18:00:00+01:00')
        assert (status, reason) == ('success', None)
        assert written['originallyPublishedAt'] == '2026-12-24T18:00:00+01:00'

        written.clear()
        export_service._export_one(license.number, 'licenses')
        # Unchanged behaviour without a chosen time (the serializer gives UTC).
        assert (datetime.fromisoformat(written['originallyPublishedAt'])
                == _aware(2026, 3, 1, 18, 30))


# --- page: step 2 in the license-number mode --------------------------------

@pytest.fixture
def step2(admin_client, license):
    """Step 2 of the license-number mode with one exportable license."""
    session = admin_client.session
    session['export_to_server'] = {
        'mode': 'licenses', 'ids': [license.number], 'source': 'license'}
    session.save()
    video = Mock(id=1)
    with override_settings(AUSTAUSCH_ENABLED=True), \
            patch.object(License, 'get_video_file', return_value=video), \
            patch('austausch.views._license_has_pdf', return_value=True), \
            patch('austausch.views._cover_settings', return_value=(False, None)), \
            patch.object(export_to_server_task, 'delay') as delay:
        delay.return_value = Mock(id='task-1')
        yield admin_client, license, delay


@pytest.mark.django_db
def test_step2_suggests_the_known_time(step2):
    client, license, _ = step2
    _plan(date(2026, 4, 3), license.number, '19:15')

    response = client.get(reverse('austausch:export_to_server_step2'))

    item = response.context['items'][0]
    assert response.context['manual_publish'] is True
    assert item['publish_now'] is False
    assert item['publish_value'] == '2026-04-03T19:15'
    assert item['publish_suggestion_display'] == '03.04.2026 19:15'


@pytest.mark.django_db
def test_step2_defaults_to_now_without_a_known_time(step2):
    client, _, _ = step2

    response = client.get(reverse('austausch:export_to_server_step2'))

    item = response.context['items'][0]
    assert item['publish_now'] is True
    assert item['publish_value'] == ''


@pytest.mark.django_db
def test_step2_sends_the_edited_time_to_the_task(step2):
    client, license, delay = step2
    _plan(date(2026, 4, 3), license.number, '19:15')

    response = client.post(reverse('austausch:export_to_server_step2'), {
        'selected_ids': [str(license.number)],
        f'publish_at_{license.number}': '2026-05-01T20:30',
    })

    assert response.status_code == 302
    publish_at = delay.call_args.kwargs['publish_at']
    assert publish_at == {str(license.number): _aware(2026, 5, 1, 20, 30).isoformat()}


@pytest.mark.django_db
def test_step2_sends_now(step2):
    client, license, delay = step2

    client.post(reverse('austausch:export_to_server_step2'), {
        'selected_ids': [str(license.number)],
        f'publish_now_{license.number}': '1',
    })

    assert delay.call_args.kwargs['publish_at'] == {str(license.number): PUBLISH_NOW}


@pytest.mark.django_db
def test_step2_rejects_an_unreadable_time_and_keeps_the_input(step2):
    client, license, delay = step2

    response = client.post(reverse('austausch:export_to_server_step2'), {
        'selected_ids': [str(license.number)],
        f'publish_at_{license.number}': 'tomorrow evening',
    })

    assert response.status_code == 200
    assert not delay.called
    item = response.context['items'][0]
    assert item['publish_value'] == 'tomorrow evening'
    assert item['publish_error']


@pytest.mark.django_db
def test_planung_mode_has_no_publish_field(step2):
    """Only the manual license-number mode offers the publish time."""
    client, license, delay = step2
    session = client.session
    session['export_to_server'] = {'mode': 'licenses', 'ids': [license.number]}
    session.save()

    response = client.get(reverse('austausch:export_to_server_step2'))
    assert response.context['manual_publish'] is False
    assert 'publish_value' not in response.context['items'][0]

    client.post(reverse('austausch:export_to_server_step2'), {
        'selected_ids': [str(license.number)],
        f'publish_now_{license.number}': '1',
    })
    assert delay.call_args.kwargs['publish_at'] is None
