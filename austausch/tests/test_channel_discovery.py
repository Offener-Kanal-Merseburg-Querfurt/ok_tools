"""Tests for exchange channel discovery and date folder scanning."""

from austausch.models import ExchangeConfig
from austausch.models import ExchangeItem
from austausch.services.nextcloud_exchange_service import NextcloudExchangeService
from austausch.tasks import get_channels
from austausch.tasks import sync_exchange_folders_task
from datetime import timedelta
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from unittest.mock import Mock
from unittest.mock import patch
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlsplit


WEBDAV_PATH = '/remote.php/dav/files/test_user/'


def _propfind_xml(folder, children):
    """Depth-1 PROPFIND answer for folder with children [(name, is_dir)]."""
    def entry(path, is_dir):
        href = WEBDAV_PATH + quote(path)
        if is_dir:
            href += '/'
            props = '<d:resourcetype><d:collection/></d:resourcetype>'
        else:
            props = (
                '<d:resourcetype/>'
                '<d:getcontentlength>10</d:getcontentlength>'
                '<d:getlastmodified>Mon, 02 Nov 2026 10:00:00 GMT</d:getlastmodified>'
            )
        return (
            f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>'
            f'{props}</d:prop></d:propstat></d:response>'
        )

    body = entry(folder, True) + ''.join(
        entry(f'{folder}/{name}'.strip('/'), is_dir) for name, is_dir in children)
    return f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">{body}</d:multistatus>'


class FakeNextcloud:
    """Answers PROPFIND requests from a {folder path: children} tree."""

    def __init__(self, tree):
        self.tree = tree
        self.requested = []

    def __call__(self, method, url, **kwargs):
        path = unquote(urlsplit(url).path)
        assert path.startswith(WEBDAV_PATH.rstrip('/')), path
        folder = path[len(WEBDAV_PATH):].strip('/')
        self.requested.append(folder)
        if folder.startswith('GroupFolders') or folder not in self.tree:
            return Mock(status_code=404, text='')
        return Mock(status_code=207, text=_propfind_xml(folder, self.tree[folder]))


class ChannelDiscoveryTestBase(TestCase):

    def setUp(self):
        self.config = ExchangeConfig.get_config()
        self.config.nextcloud_base_url = 'https://cloud.example.com'
        self.config.nextcloud_username = 'test_user'
        self.config.nextcloud_password = 'test_pass'
        self.config.download_storage_path = '/tmp'
        self.config.upload_server_path = 'GroupFolders/Test-Upload'
        self.config.exchange_folder_pattern = '{channel} - Austausch'
        self.config.channel_search_roots = '/\nBVBM'
        self.config.channels_list = ''
        self.config.save()
        self.service = NextcloudExchangeService(self.config)

    def fake(self, tree):
        fake = FakeNextcloud(tree)
        patcher = patch(
            'austausch.services.nextcloud_exchange_service.requests.request', fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


class TestDiscoverChannels(ChannelDiscoveryTestBase):

    def test_discovers_channels_in_all_roots(self):
        self.fake({
            '': [('OK Dessau - Austausch', True), ('BVBM', True),
                 ('Privat', True), ('notes - Austausch', False)],
            'BVBM': [('h1 - Fernsehen aus Hannover - Austausch', True),
                     ('OK Dessau - Austausch', True)],
        })

        self.assertEqual(self.service.discover_channels(), {
            'OK Dessau': 'OK Dessau - Austausch',
            'h1 - Fernsehen aus Hannover':
                'BVBM/h1 - Fernsehen aus Hannover - Austausch',
        })

    def test_missing_root_is_ignored(self):
        self.fake({'': [('OK Dessau - Austausch', True)]})

        self.assertEqual(
            self.service.discover_channels(),
            {'OK Dessau': 'OK Dessau - Austausch'})

    def test_channels_list_filters_and_excluded_channels_skip(self):
        self.fake({
            '': [('OK Dessau - Austausch', True), ('OK Halle - Austausch', True),
                 ('ARCHIV - Austausch', True)],
        })
        self.config.excluded_channels = 'ARCHIV'
        self.assertEqual(get_channels(self.config, self.service), {
            'OK Dessau': 'OK Dessau - Austausch',
            'OK Halle': 'OK Halle - Austausch',
        })

        self.config.channels_list = 'OK Halle, OK Neu'
        self.assertEqual(get_channels(self.config, self.service), {
            'OK Halle': 'OK Halle - Austausch',
            # Listed but not found: folder from the pattern, as before.
            'OK Neu': 'OK Neu - Austausch',
        })


class TestDateFolders(ChannelDiscoveryTestBase):

    def test_select_date_folders_by_age(self):
        today = timezone.localdate()
        names = [
            today.strftime('%Y_%m_%d'),
            (today - timedelta(days=2)).strftime('%Y_%m_%d'),
            (today - timedelta(days=3)).strftime('%Y_%m_%d'),
            'Alt', '2026_13_40', '2026-11-01',
        ]

        self.assertEqual(
            NextcloudExchangeService.select_date_folders(names, 3), names[:2])
        self.assertEqual(
            NextcloudExchangeService.select_date_folders(names, None), names[:3])

    def test_list_exchange_folder_scans_existing_date_folders_only(self):
        self.config.sync_date_folders_days = 2
        today = timezone.localdate().strftime('%Y_%m_%d')
        old = (timezone.localdate() - timedelta(days=30)).strftime('%Y_%m_%d')
        folder = 'BVBM/h1 - Austausch'
        fake = self.fake({
            folder: [(today, True), (old, True), ('flat.mp4', False)],
            f'{folder}/{today}': [('new.mp4', False)],
            f'{folder}/{old}': [('old.mp4', False)],
        })

        files = self.service.list_exchange_folder('h1', folder_path=folder)
        self.assertEqual(
            sorted(f['path'] for f in files),
            [f'{folder}/{today}/new.mp4', f'{folder}/flat.mp4'])
        self.assertEqual(fake.requested, [folder, f'{folder}/{today}'])

        files = self.service.list_exchange_folder('h1', date_folders=[], folder_path=folder)
        self.assertEqual(len(files), 3)


@override_settings(AUSTAUSCH_ENABLED=True)
class TestSyncTask(ChannelDiscoveryTestBase):

    def test_channel_name_has_no_root_and_failure_does_not_stop_sync(self):
        today = timezone.localdate().strftime('%Y_%m_%d')
        self.fake({
            '': [('Broken - Austausch', True)],
            'BVBM': [('h1 - Austausch', True)],
            'BVBM/h1 - Austausch': [(today, True)],
            f'BVBM/h1 - Austausch/{today}': [('Sendung.mp4', False)],
        })
        original = NextcloudExchangeService.list_exchange_folder

        def list_folder(service, channel, **kwargs):
            if channel == 'Broken':
                raise RuntimeError('boom')
            return original(service, channel, **kwargs)

        with patch.object(NextcloudExchangeService, 'list_exchange_folder', list_folder):
            with self.assertRaisesRegex(RuntimeError, 'Broken'):
                sync_exchange_folders_task(full=True)

        item = ExchangeItem.objects.get()
        self.assertEqual(item.channel, 'h1')
        self.assertEqual(item.file_path, f'BVBM/h1 - Austausch/{today}/Sendung.mp4')
