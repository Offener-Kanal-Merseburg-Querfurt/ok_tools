"""Tests for the export hardening: chunked copy, locks and source failover."""

from austausch.models import ExchangeConfig
from austausch.services.export_locks import ExportItemLocks
from austausch.services.export_locks import acquire
from austausch.services.export_locks import lock_key
from austausch.services.export_locks import locked_item_ids
from austausch.services.export_locks import release
from austausch.services.export_locks import release_orphaned_locks
from austausch.services.export_to_server_service import ExportToServerService
from austausch.services.file_copy import CopyStalledError
from austausch.services.file_copy import copy_with_progress
from austausch.services.file_copy import sweep_stale_tmp_files
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from media_files.models import StorageLocation
from media_files.models import VideoFile
from unittest.mock import patch
import datetime
import os
import pytest
import tempfile
import time


class TestChunkedCopy:
    """copy_with_progress must move bytes, report them, and give up on a stall."""

    def test_copies_content_and_preserves_mtime(self, tmp_path):
        src = tmp_path / 'source.bin'
        src.write_bytes(b'0123456789' * 5000)
        old_mtime = time.time() - 86400
        os.utime(src, (old_mtime, old_mtime))
        dst = tmp_path / 'target.bin'

        copied = copy_with_progress(str(src), str(dst), chunk_size=4096)

        assert copied == src.stat().st_size
        assert dst.read_bytes() == src.read_bytes()
        # copy2 kept mtime; a read/write loop only does with copystat.
        assert int(dst.stat().st_mtime) == int(old_mtime)

    def test_reports_progress_in_chunks(self, tmp_path):
        src = tmp_path / 'source.bin'
        src.write_bytes(b'x' * (64 * 1024))
        dst = tmp_path / 'target.bin'
        calls = []

        copy_with_progress(
            str(src), str(dst), chunk_size=8 * 1024,
            progress_callback=lambda *args: calls.append(args),
            poll_interval=0.01,
        )

        assert calls, 'progress callback was never invoked'
        chunk_num, total_chunks, percent, speed_mbps = calls[-1]
        assert total_chunks == 8
        assert chunk_num == 8
        assert percent == pytest.approx(100.0)
        assert speed_mbps >= 0

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(OSError):
            copy_with_progress(str(tmp_path / 'nope.bin'), str(tmp_path / 'out.bin'))

    @pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='needs FIFOs')
    def test_stalled_copy_is_aborted(self, tmp_path):
        """A source that stops delivering must not hold the worker forever."""
        fifo = tmp_path / 'stalled.fifo'
        os.mkfifo(fifo)
        # O_RDWR keeps a writer attached so the child's open() returns; it then
        # reads the few bytes below and blocks forever — exactly the shape of a
        # CIFS share that stops answering mid-copy.
        writer = os.open(str(fifo), os.O_RDWR | os.O_NONBLOCK)
        try:
            os.write(writer, b'y' * 1024)
            started = time.monotonic()
            with pytest.raises(CopyStalledError):
                copy_with_progress(
                    str(fifo), str(tmp_path / 'out.bin'),
                    chunk_size=512, stall_timeout=2.0, poll_interval=0.1,
                )
            # It gave up on its own rather than waiting for the writer.
            assert time.monotonic() - started < 30
        finally:
            os.close(writer)

    def test_short_copy_is_reported(self, tmp_path):
        src = tmp_path / 'source.bin'
        src.write_bytes(b'z' * 2048)
        dst = tmp_path / 'target.bin'

        # The child writes nothing but exits cleanly: the byte count must not
        # be taken on faith.
        with patch('austausch.services.file_copy._copy_worker',
                   side_effect=lambda *a, **k: os._exit(0)):
            with pytest.raises(Exception) as excinfo:
                copy_with_progress(str(src), str(dst), poll_interval=0.05)
        assert 'Short copy' in str(excinfo.value)


class TestSweepStaleTmpFiles:
    """Leftovers from killed copies must not accumulate on the share."""

    def test_removes_only_old_tmp_files(self, tmp_path):
        old_tmp = tmp_path / '.tmp_abandoned'
        old_tmp.write_bytes(b'partial')
        stale_time = time.time() - 48 * 3600
        os.utime(old_tmp, (stale_time, stale_time))

        fresh_tmp = tmp_path / '.tmp_in_progress'
        fresh_tmp.write_bytes(b'writing right now')

        real_file = tmp_path / 'video.mp4'
        real_file.write_bytes(b'exported')
        os.utime(real_file, (stale_time, stale_time))

        removed = sweep_stale_tmp_files(str(tmp_path), older_than_seconds=24 * 3600)

        assert removed == 1
        assert not old_tmp.exists()
        assert fresh_tmp.exists()
        assert real_file.exists()

    def test_missing_directory_is_not_an_error(self, tmp_path):
        assert sweep_stale_tmp_files(str(tmp_path / 'gone')) == 0


@pytest.mark.django_db
class TestExportLocks(TestCase):
    """The same item must not be exported by two tasks at once."""

    def setUp(self):
        cache.clear()

    def test_second_acquire_reports_the_holder(self):
        assert acquire('licenses', 18901, 'task-a') is None
        assert acquire('licenses', 18901, 'task-b') == 'task-a'

    def test_release_only_by_the_owner(self):
        acquire('licenses', 18901, 'task-a')
        assert release('licenses', 18901, 'task-b') is False
        assert release('licenses', 18901, 'task-a') is True
        assert acquire('licenses', 18901, 'task-b') is None

    def test_context_manager_splits_free_from_busy(self):
        acquire('licenses', 18901, 'other-task')

        with ExportItemLocks('licenses', [18901, 18902], 'my-task') as locks:
            assert locks.acquired_ids == [18902]
            assert locks.busy == [{'id': 18901, 'task_id': 'other-task'}]
            assert cache.get(lock_key('licenses', 18902)) == 'my-task'

        # Leaving the block frees what this task took, not what it did not.
        assert cache.get(lock_key('licenses', 18902)) is None
        assert cache.get(lock_key('licenses', 18901)) == 'other-task'

    def test_locks_are_released_even_when_the_export_raises(self):
        with pytest.raises(RuntimeError):
            with ExportItemLocks('licenses', [18901], 'my-task'):
                raise RuntimeError('export blew up')
        assert cache.get(lock_key('licenses', 18901)) is None

    def test_disabled_locking_takes_every_item(self):
        acquire('licenses', 18901, 'other-task')
        with ExportItemLocks('licenses', [18901], 'my-task', enabled=False) as locks:
            assert locks.acquired_ids == [18901]
            assert locks.busy == []

    def test_locked_item_ids_filters_by_mode(self):
        acquire('licenses', 18901, 'task-a')
        acquire('contributions', 55, 'task-b')

        with patch('austausch.services.export_locks.iter_locks', return_value={
            lock_key('licenses', 18901): 'task-a',
            lock_key('contributions', 55): 'task-b',
        }):
            assert locked_item_ids('licenses') == {'18901': 'task-a'}
            assert locked_item_ids('contributions') == {'55': 'task-b'}

    def test_orphaned_locks_are_released(self):
        acquire('licenses', 18901, 'dead-task')
        acquire('licenses', 18902, 'live-task')
        locks = {
            lock_key('licenses', 18901): 'dead-task',
            lock_key('licenses', 18902): 'live-task',
        }

        with patch('austausch.services.export_locks.iter_locks', return_value=locks):
            released = release_orphaned_locks({'live-task'})

        assert released == 1
        assert cache.get(lock_key('licenses', 18901)) is None
        assert cache.get(lock_key('licenses', 18902)) == 'live-task'

    def test_nothing_is_released_when_no_worker_answered(self):
        acquire('licenses', 18901, 'task-a')
        with patch('austausch.services.export_locks.iter_locks', return_value={
            lock_key('licenses', 18901): 'task-a',
        }):
            assert release_orphaned_locks(None) == 0
        assert cache.get(lock_key('licenses', 18901)) == 'task-a'


@pytest.mark.django_db
class TestStorageHealth(TestCase):
    """Cached read speed, not stat(), decides whether a location is usable."""

    def setUp(self):
        self.storage = StorageLocation.objects.create(
            name='Archive', storage_type='ARCHIVE',
            path='/tmp/health_archive/', is_active=True,
        )

    def test_never_measured_is_unknown(self):
        from media_files.storage_health import health_state

        assert health_state(self.storage) is None

    def test_no_response_is_unhealthy(self):
        from media_files.storage_health import health_state
        from media_files.storage_health import record_read_speed

        record_read_speed(self.storage, None)
        assert health_state(self.storage) is False

    def test_slow_read_is_unhealthy(self):
        from media_files.storage_health import health_state
        from media_files.storage_health import record_read_speed

        record_read_speed(self.storage, 0.03)
        assert health_state(self.storage, min_mbps=1.0) is False

    def test_fast_read_is_healthy(self):
        from media_files.storage_health import health_state
        from media_files.storage_health import record_read_speed

        record_read_speed(self.storage, 136.0)
        assert health_state(self.storage, min_mbps=1.0) is True

    def test_old_measurement_is_unknown_again(self):
        from media_files.storage_health import health_state

        StorageLocation.objects.filter(pk=self.storage.pk).update(
            last_read_mbps=136.0,
            last_health_check=timezone.now() - datetime.timedelta(days=1),
        )
        self.storage.refresh_from_db()
        assert health_state(self.storage, max_age_seconds=3600) is None

    def test_probe_of_a_missing_file_returns_none(self):
        from media_files.storage_health import probe_read_speed

        assert probe_read_speed('/nonexistent/file.mp4', timeout=5) is None

    def test_probe_measures_a_real_file(self):
        from media_files.storage_health import probe_read_speed

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b'q' * (2 * 1024 * 1024))
            path = handle.name
        try:
            speed = probe_read_speed(path, sample_bytes=1024 * 1024, timeout=30)
        finally:
            os.unlink(path)
        assert speed is not None and speed > 0


@pytest.mark.django_db
class TestExportSourceSelection(TestCase):
    """A dead archive must not be read when an identical playout copy exists."""

    NUMBER = 18901
    SIZE = 12_686_006_200

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='export_source_')
        self.archive_dir = os.path.join(self.tmpdir, 'archive')
        self.playout_dir = os.path.join(self.tmpdir, 'playout')
        os.makedirs(self.archive_dir)
        os.makedirs(self.playout_dir)

        self.config = ExchangeConfig.get_config()
        self.config.nextcloud_base_url = 'https://cloud.example.com'
        self.config.nextcloud_username = 'test_user'
        self.config.nextcloud_password = 'test_pass'
        self.config.export_destination = 'network_share'
        self.config.network_share_base_path = self.tmpdir
        self.config.download_storage_path = self.tmpdir
        self.config.save()

        self.archive = StorageLocation.objects.create(
            name='NAS Film Archiv', storage_type='ARCHIVE',
            path=self.archive_dir, is_active=True,
        )
        self.playout = StorageLocation.objects.create(
            name='NAS Playout - Sendungen', storage_type='PLAYOUT',
            path=self.playout_dir, is_active=True,
        )
        name = f'{self.NUMBER}_Sendung.mp4'
        for directory in (self.archive_dir, self.playout_dir):
            with open(os.path.join(directory, name), 'wb') as handle:
                handle.write(b'v')

        self.archive_video = VideoFile.objects.create(
            number=self.NUMBER, filename=name, storage_location=self.archive,
            file_path=name, file_size=self.SIZE, is_available=True,
        )
        self.playout_video = VideoFile.objects.create(
            number=self.NUMBER, filename=name, storage_location=self.playout,
            file_path=name, file_size=self.SIZE, is_available=True,
        )
        self.service = ExportToServerService()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _speeds(self, archive_mbps, playout_mbps):
        """Patch the probe so each path answers with a fixed speed."""
        def fake_probe(path, **kwargs):
            return archive_mbps if path.startswith(self.archive_dir) else playout_mbps
        return patch('media_files.storage_health.probe_read_speed',
                     side_effect=fake_probe)

    def test_healthy_archive_stays_the_source(self):
        with self._speeds(120.0, 136.0):
            chosen, note = self.service._select_export_source(
                self.archive_video, self.NUMBER)
        assert chosen.pk == self.archive_video.pk
        assert note is None

    def test_dead_archive_falls_back_to_playout(self):
        with self._speeds(0.03, 136.0):
            chosen, note = self.service._select_export_source(
                self.archive_video, self.NUMBER)
        assert chosen.pk == self.playout_video.pk
        assert 'PLAYOUT' in note and 'ARCHIVE' in note
        assert self.service._source_note_by_item[self.NUMBER] == note

    def test_unresponsive_archive_falls_back_to_playout(self):
        with self._speeds(None, 136.0):
            chosen, _note = self.service._select_export_source(
                self.archive_video, self.NUMBER)
        assert chosen.pk == self.playout_video.pk

    def test_no_reachable_copy_reports_why(self):
        with self._speeds(None, None):
            chosen, reason = self.service._select_export_source(
                self.archive_video, self.NUMBER)
        assert chosen is None
        assert 'no response' in reason

    def test_a_different_render_is_never_substituted(self):
        """Only byte-identical copies count as the same content."""
        self.playout_video.file_size = self.SIZE - 1
        self.playout_video.save(update_fields=['file_size'])

        with self._speeds(0.03, 136.0):
            chosen, reason = self.service._select_export_source(
                self.archive_video, self.NUMBER)
        assert chosen is None
        assert 'below threshold' in reason

    def test_mismatched_checksum_is_never_substituted(self):
        self.archive_video.checksum = 'a' * 64
        self.archive_video.save(update_fields=['checksum'])
        self.playout_video.checksum = 'b' * 64
        self.playout_video.save(update_fields=['checksum'])

        with self._speeds(0.03, 136.0):
            chosen, _reason = self.service._select_export_source(
                self.archive_video, self.NUMBER)
        assert chosen is None

    def test_probe_result_is_cached_on_the_location(self):
        with self._speeds(0.03, 136.0):
            self.service._select_export_source(self.archive_video, self.NUMBER)
        self.archive.refresh_from_db()
        self.playout.refresh_from_db()
        assert self.archive.last_read_mbps == pytest.approx(0.03)
        assert self.playout.last_read_mbps == pytest.approx(136.0)
        assert self.archive.last_health_check is not None

    def test_failover_off_still_detects_an_unreachable_primary(self):
        self.config.export_source_failover_enabled = False
        self.config.save()
        service = ExportToServerService()

        with self._speeds(None, 136.0):
            chosen, reason = service._select_export_source(
                self.archive_video, self.NUMBER)
        assert chosen is None
        assert 'no response' in reason

    def test_missing_file_is_reported_as_missing_not_unreachable(self):
        os.unlink(os.path.join(self.archive_dir, self.archive_video.file_path))
        os.unlink(os.path.join(self.playout_dir, self.playout_video.file_path))

        chosen, reason = self.service._select_export_source(
            self.archive_video, self.NUMBER)
        assert chosen is None
        assert 'file missing' in reason


@pytest.mark.django_db
class TestCopyIntegration(TestCase):
    """The service-level copy must fail loudly and leave no debris."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='austausch_copy_')
        self.config = ExchangeConfig.get_config()
        self.config.nextcloud_base_url = 'https://cloud.example.com'
        self.config.nextcloud_username = 'test_user'
        self.config.nextcloud_password = 'test_pass'
        self.config.export_destination = 'network_share'
        self.config.network_share_base_path = self.tmpdir
        self.config.network_share_subfolder = ''
        self.config.download_storage_path = self.tmpdir
        self.config.copy_stall_timeout_seconds = 2
        self.config.save()
        self.service = ExportToServerService()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_copy_reports_progress_through_the_service(self):
        source = os.path.join(self.tmpdir, 'source.bin')
        with open(source, 'wb') as handle:
            handle.write(b'p' * (256 * 1024))
        calls = []
        self.service.set_progress_callback(lambda *args: calls.append(args))
        self.config.copy_chunk_size_mb = 1
        self.service.config = self.config

        target = os.path.join(self.tmpdir, 'out', 'copied.bin')
        assert self.service._copy_file_atomic(source, target) is True
        assert os.path.getsize(target) == 256 * 1024
        assert calls, 'the network-share branch reported no progress'

    @pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='needs FIFOs')
    def test_stalled_copy_fails_with_a_reason_and_no_leftovers(self):
        fifo = os.path.join(self.tmpdir, 'stalled.fifo')
        os.mkfifo(fifo)
        writer = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        target_dir = os.path.join(self.tmpdir, 'out')
        try:
            os.write(writer, b'y' * 1024)
            ok = self.service._copy_file_atomic(
                fifo, os.path.join(target_dir, 'copied.bin'))
        finally:
            os.close(writer)

        assert ok is False
        assert 'Copy stalled' in self.service._last_copy_error
        # The .tmp_ file must be gone, not left on a share that is 96% full.
        assert [n for n in os.listdir(target_dir) if n.startswith('.tmp_')] == []

    def test_run_sweeps_leftover_tmp_files(self):
        leftover = os.path.join(self.tmpdir, '.tmp_from_a_killed_worker')
        with open(leftover, 'wb') as handle:
            handle.write(b'partial')
        stale = time.time() - 48 * 3600
        os.utime(leftover, (stale, stale))

        self.service.run(selected_ids=[], mode='licenses')

        assert not os.path.exists(leftover)


@pytest.mark.django_db
class TestExportTaskLocking(TestCase):
    """The task must skip, not duplicate, an item another task is uploading."""

    def setUp(self):
        cache.clear()
        config = ExchangeConfig.get_config()
        config.nextcloud_base_url = 'https://cloud.example.com'
        config.nextcloud_username = 'test_user'
        config.nextcloud_password = 'test_pass'
        config.export_destination = 'nextcloud'
        config.upload_server_path = 'GroupFolders/Test-Upload'
        config.download_storage_path = tempfile.mkdtemp(prefix='austausch_task_')
        config.save()

    def test_busy_items_are_reported_and_not_re_exported(self):
        from austausch.models import ExportToServerRun
        from austausch.tasks import export_to_server_task

        acquire('licenses', 18901, 'first-task')
        seen = {}

        def fake_run(selected_ids, mode, progress_callback=None):
            seen['ids'] = list(selected_ids)
            return {
                'success_count': len(selected_ids),
                'failure_count': 0,
                'skipped_no_pdf_count': 0,
                'success_ids': list(selected_ids),
                'success_license_numbers': [],
                'failed': [],
                'skipped_no_pdf': [],
                'covers_generated': [],
                'source_fallbacks': {},
            }

        with patch.object(ExportToServerService, 'run', side_effect=fake_run):
            result = export_to_server_task.apply(
                args=[[18901, 18902], 'licenses'], kwargs={'user_id': None}).get()

        assert seen['ids'] == [18902]
        already = result['details']['already_running']
        assert already == [{'id': 18901, 'task_id': 'first-task'}]
        # The run still counts both items as selected.
        run = ExportToServerRun.objects.get(pk=result['run_id'])
        assert run.total_count == 2

    def test_locks_are_freed_when_the_task_finishes(self):
        from austausch.tasks import export_to_server_task

        def fake_run(selected_ids, mode, progress_callback=None):
            assert cache.get(lock_key('licenses', 18901)) is not None
            return {
                'success_count': 0, 'failure_count': 0, 'skipped_no_pdf_count': 0,
                'success_ids': [], 'success_license_numbers': [],
                'failed': [], 'skipped_no_pdf': [], 'covers_generated': [],
                'source_fallbacks': {},
            }

        with patch.object(ExportToServerService, 'run', side_effect=fake_run):
            export_to_server_task.apply(
                args=[[18901], 'licenses'], kwargs={'user_id': None}).get()

        assert cache.get(lock_key('licenses', 18901)) is None
