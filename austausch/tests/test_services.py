import json
import os
import tempfile
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from austausch.models import ExchangeItem, ExchangeConfig
from austausch.services.nextcloud_exchange_service import NextcloudExchangeService
from austausch.services.export_to_server_service import ExportToServerService
from austausch.services.metadata_normalizer import is_exchange_allowed_for_viewer


@pytest.mark.django_db
class TestNextcloudExchangeService(TestCase):
    """Tests for NextcloudExchangeService."""
    
    def setUp(self):
        """Set up test data."""
        self.config = ExchangeConfig.get_config()
        self.config.nextcloud_base_url = 'https://cloud.example.com'
        self.config.nextcloud_username = 'test_user'
        self.config.nextcloud_password = 'test_pass'
        self.config.download_storage_path = '/tmp'
        self.config.upload_server_path = 'GroupFolders/Test-Upload'
        self.config.save()
        self.service = NextcloudExchangeService(self.config)
    
    def test_parse_contribution_id(self):
        """Test parsing contribution ID from filename."""
        # OK-Tools managed filename
        self.assertEqual(
            NextcloudExchangeService.parse_contribution_id('12345_20240101_video.mp4'),
            12345
        )
        
        # Legacy filename
        self.assertIsNone(
            NextcloudExchangeService.parse_contribution_id('legacy_video.mp4')
        )
        
        # Edge cases
        self.assertIsNone(NextcloudExchangeService.parse_contribution_id(''))
        self.assertIsNone(NextcloudExchangeService.parse_contribution_id('no_number.mp4'))
    
    def test_detect_file_type(self):
        self.assertEqual(
            NextcloudExchangeService.detect_file_type('video.mp4'),
            'video'
        )
        self.assertEqual(
            NextcloudExchangeService.detect_file_type('document.pdf'),
            'pdf'
        )
        self.assertEqual(
            NextcloudExchangeService.detect_file_type('unknown.txt'),
            'unknown'
        )

    def test_parse_meta_json_supports_nested_canonical_fields(self):
        payload = {
            'name': 'Nested Title',
            'organization': {
                'bundesland': 'Sachsen-Anhalt',
                'bundesland_code': 'ST',
            },
            'license': {
                'allowExchange': True,
                'allowExchangeOtherStates': True,
            },
        }

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as src:
            json.dump(payload, src)
            source_path = src.name

        def _copy_download(_remote_path, local_path):
            with open(source_path, 'r', encoding='utf-8') as source_file:
                with open(local_path, 'w', encoding='utf-8') as target_file:
                    target_file.write(source_file.read())
            return True

        try:
            with patch.object(self.service, 'download_file', side_effect=_copy_download):
                metadata = self.service.parse_meta_json('/remote/test.meta.json')
        finally:
            os.unlink(source_path)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata['bundesland'], 'Sachsen-Anhalt')
        self.assertEqual(metadata['bundesland_code'], 'ST')
        self.assertTrue(metadata['allow_exchange'])
        self.assertTrue(metadata['allow_exchange_other_states'])

    def _parse(self, payload):
        """Run parse_meta_json on payload as if downloaded from Nextcloud."""
        def _write_download(_remote_path, local_path):
            with open(local_path, 'w', encoding='utf-8') as target_file:
                json.dump(payload, target_file)
            return True

        with patch.object(self.service, 'download_file', side_effect=_write_download):
            return self.service.parse_meta_json('/remote/test.meta.json')

    def test_parse_meta_json_missing_bundesland_gives_empty_strings(self):
        metadata = self._parse({'name': 'No state'})

        self.assertEqual(metadata['bundesland'], '')
        self.assertEqual(metadata['bundesland_code'], '')

    def test_parse_meta_json_null_values_give_empty_strings(self):
        metadata = self._parse({
            'name': None,
            'description': None,
            'bundesland': None,
            'bundesland_code': None,
            'youthProtectionCategory': None,
            'thumbnail': None,
        })

        for key in ('title', 'description', 'bundesland', 'bundesland_code',
                    'youth_protection_category', 'thumbnail'):
            self.assertEqual(metadata[key], '', key)

    def test_parse_meta_json_normalizes_bundesland_code(self):
        metadata = self._parse({'bundesland_code': ' st '})

        self.assertEqual(metadata['bundesland_code'], 'ST')


def test_is_exchange_allowed_for_viewer_uses_bundesland_code_rules():
    payload = {
        'organization': {
            'bundesland': 'Sachsen-Anhalt',
            'bundesland_code': 'ST',
        },
        'license': {
            'allowExchange': True,
            'allowExchangeOtherStates': False,
        },
    }

    assert is_exchange_allowed_for_viewer(payload, 'ST') is True
    assert is_exchange_allowed_for_viewer(payload, 'SN') is False


def test_is_exchange_allowed_for_viewer_parses_string_booleans():
    payload = {
        'organization': {
            'bundesland_code': 'ST',
        },
        'license': {
            'allowExchange': 'false',
            'allowExchangeOtherStates': 'true',
        },
    }

    assert is_exchange_allowed_for_viewer(payload, 'ST') is False
    assert is_exchange_allowed_for_viewer(payload, 'SN') is True


@pytest.mark.django_db
class TestExportToServerServiceNetworkShare(TestCase):
    """Tests for network share export helpers."""

    def setUp(self):
        self.config = ExchangeConfig.get_config()
        self.config.nextcloud_base_url = 'https://cloud.example.com'
        self.config.nextcloud_username = 'test_user'
        self.config.nextcloud_password = 'test_pass'
        self.config.export_destination = 'network_share'
        self.config.network_share_windows_root = r'Z:\Vorschau\2025'
        self.config.network_share_subfolder = 'austausch'
        self.tmpdir = tempfile.mkdtemp(prefix='austausch_test_')
        self.config.network_share_base_path = self.tmpdir
        self.config.download_storage_path = self.tmpdir
        self.config.save()
        self.service = ExportToServerService()

    def test_build_windows_files_txt_entry(self):
        entry = self.service._build_windows_files_txt_entry('Lassa_Sendung.mp4')
        self.assertEqual(entry, r'"Z:\Vorschau\2025\Lassa_Sendung.mp4"')

    def test_append_to_files_txt(self):
        export_dir = self.service._network_share_export_dir()
        os.makedirs(export_dir, exist_ok=True)
        ok1 = self.service._append_to_files_txt(export_dir, 'video.mp4')
        ok2 = self.service._append_to_files_txt(export_dir, 'video.meta.json')
        self.assertTrue(ok1)
        self.assertTrue(ok2)

        files_txt = os.path.join(export_dir, 'files.txt')
        self.assertTrue(os.path.isfile(files_txt))
        with open(files_txt, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], r'"Z:\Vorschau\2025\video.mp4"')
        self.assertEqual(lines[1], r'"Z:\Vorschau\2025\video.meta.json"')

    def test_copy_file_atomic(self):
        export_dir = self.service._network_share_export_dir()
        os.makedirs(export_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False) as src:
            src.write(b'test_payload')
            src_path = src.name

        target_path = os.path.join(export_dir, 'copied.bin')
        try:
            ok = self.service._copy_file_atomic(src_path, target_path)
            self.assertTrue(ok)
            with open(target_path, 'rb') as f:
                self.assertEqual(f.read(), b'test_payload')
        finally:
            if os.path.exists(src_path):
                os.unlink(src_path)

    def test_run_includes_success_license_numbers_for_license_mode(self):
        self.service._validate_destination = Mock(return_value=True)
        self.service._export_one = Mock(return_value=('success', 12345, None))

        report = self.service.run(selected_ids=[12345], mode='licenses')

        self.assertEqual(report['success_count'], 1)
        self.assertEqual(report['success_ids'], [12345])
        self.assertEqual(report['success_license_numbers'], [12345])
