"""Tests for auto-copy on planning (media_files.tasks.copy_videos_for_plan).

Covers the primary-version selection and the lifecycle:
  CUSTOM (staging) -> ARCHIVE (permanent, all versions, primary flagged)
                   -> PLAYOUT (temporary, primary only, no primary flag)
  CUSTOM sources are auto-deleted once archived + played out.
"""

from datetime import date
from datetime import timedelta
from django.test import TestCase
from licenses.models import License
from licenses.models import default_category
from media_files.models import MediaFilesConfig
from media_files.models import StorageLocation
from media_files.models import VideoFile
from media_files.tasks import _copy_video_to_storage
from media_files.tasks import copy_videos_for_plan
from ok_tools.testing import create_license
from ok_tools.testing import create_user
from pathlib import Path
from unittest.mock import patch
import json
import shutil
import tempfile


def _make_video(storage, number, filename, *, is_manual_primary=False,
                total_bitrate=5_000_000, content=None):
    """Create a real file on disk in ``storage`` and a matching VideoFile row."""
    path = Path(storage.path) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content or f"fake video content {filename}".encode())
    return VideoFile.objects.create(
        number=number,
        filename=filename,
        storage_location=storage,
        file_path=filename,
        is_available=True,
        is_manual_primary=is_manual_primary,
        total_bitrate=total_bitrate,
        file_size=path.stat().st_size,
    )


def _enable_auto_copy(playout_storage_name="Test Sendungen"):
    """Turn on all auto-copy flags in the singleton MediaFilesConfig."""
    config = MediaFilesConfig.get_config()
    config.auto_copy_on_schedule = True
    config.auto_copy_to_archive = True
    config.auto_copy_to_playout = True
    config.auto_delete_from_custom = True
    config.copy_verify_checksum = False
    config.use_weekly_folders = True
    config.default_playout_storage_name = playout_storage_name
    config.save()
    return config


class CopyVideosForPlanTests(TestCase):
    """End-to-end tests for copy_videos_for_plan."""

    def setUp(self):
        self.custom_dir = tempfile.mkdtemp(prefix="custom_")
        self.archive_dir = tempfile.mkdtemp(prefix="archive_")
        self.playout_dir = tempfile.mkdtemp(prefix="playout_")

        self.custom = StorageLocation.objects.create(
            name="Custom Staging", storage_type="CUSTOM",
            path=self.custom_dir, is_active=True,
        )
        self.archive = StorageLocation.objects.create(
            name="Test Archive", storage_type="ARCHIVE",
            path=self.archive_dir, is_active=True,
        )
        self.playout = StorageLocation.objects.create(
            name="Test Sendungen", storage_type="PLAYOUT",
            path=self.playout_dir, is_active=True,
        )
        _enable_auto_copy()
        # Monday in ISO week 02 of 2025 -> week_folder "2025_KW_02"
        self.plan_date = date(2025, 1, 6)
        self.week_folder = "2025_KW_02"

    def tearDown(self):
        shutil.rmtree(self.custom_dir, ignore_errors=True)
        shutil.rmtree(self.archive_dir, ignore_errors=True)
        shutil.rmtree(self.playout_dir, ignore_errors=True)

    def _run(self, numbers):
        return copy_videos_for_plan(numbers, self.plan_date, user_id=None)

    def _run_expecting_errors(self, numbers):
        """Run the task and return the result carried by its RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            self._run(numbers)
        return json.loads(str(ctx.exception))

    def _fail_storage(self, storage_type, message):
        """Return a _copy_video_to_storage side effect failing one storage type."""
        def side_effect(source_video, destination_storage, user, destination_subfolder=None):
            if destination_storage.storage_type == storage_type:
                return False, message
            return _copy_video_to_storage(
                source_video, destination_storage, user,
                destination_subfolder=destination_subfolder,
            )
        return side_effect

    # --- order: playout pass before archive pass ---------------------------

    def test_all_playout_copies_before_archive_copies(self):
        """Every number reaches playout before any archive copy starts."""
        _make_video(self.custom, 18628, "18628.mp4", is_manual_primary=True)
        _make_video(self.custom, 17431, "17431.mp4", is_manual_primary=True)
        _make_video(self.custom, 19041, "19041.mp4", is_manual_primary=True)
        calls = []

        def record(source_video, destination_storage, user, destination_subfolder=None):
            calls.append((destination_storage.storage_type, source_video.number))
            return True, "Video copied successfully"

        with patch("media_files.tasks._copy_video_to_storage", side_effect=record):
            result = self._run([18628, 17431, 19041])

        self.assertEqual(calls, [
            ("PLAYOUT", 18628), ("PLAYOUT", 17431), ("PLAYOUT", 19041),
            ("ARCHIVE", 18628), ("ARCHIVE", 17431), ("ARCHIVE", 19041),
        ])
        self.assertEqual(result["copied_to_playout"], 3)
        self.assertEqual(result["copied_to_archive"], 3)
        self.assertEqual(result["errors"], 0)

    def test_archive_unreachable_still_fills_playout(self):
        """Archive failure keeps playout copies and the CUSTOM source."""
        _make_video(self.custom, 18628, "18628.mp4", is_manual_primary=True)
        _make_video(self.custom, 17431, "17431.mp4", is_manual_primary=True)

        with patch(
            "media_files.tasks._copy_video_to_storage",
            side_effect=self._fail_storage("ARCHIVE", "Archive not reachable"),
        ):
            result = self._run_expecting_errors([18628, 17431])

        self.assertEqual(result["copied_to_playout"], 2)
        self.assertEqual(result["copied_to_archive"], 0)
        self.assertEqual(result["errors"], 2)
        self.assertEqual(
            [e["message"] for e in result["details"]["errors"]],
            [
                "Archive copy failed for 18628.mp4: Archive not reachable",
                "Archive copy failed for 17431.mp4: Archive not reachable",
            ],
        )
        for number in (18628, 17431):
            self.assertTrue(VideoFile.objects.filter(
                number=number, storage_location=self.playout,
                file_path__startswith=self.week_folder, is_available=True,
            ).exists())
            self.assertTrue(VideoFile.objects.filter(
                number=number, storage_location=self.custom, is_available=True,
            ).exists())

    def test_playout_unreachable_still_fills_archive(self):
        """Playout failure still archives, but keeps the CUSTOM source."""
        _make_video(self.custom, 18628, "18628.mp4", is_manual_primary=True)

        with patch(
            "media_files.tasks._copy_video_to_storage",
            side_effect=self._fail_storage("PLAYOUT", "Playout not reachable"),
        ):
            result = self._run_expecting_errors([18628])

        self.assertEqual(result["copied_to_playout"], 0)
        self.assertEqual(result["copied_to_archive"], 1)
        self.assertEqual(
            result["details"]["errors"],
            [{"number": 18628, "message": "Playout copy failed: Playout not reachable"}],
        )
        self.assertTrue(VideoFile.objects.filter(
            number=18628, storage_location=self.archive, is_available=True,
        ).exists())
        self.assertTrue(VideoFile.objects.filter(
            number=18628, storage_location=self.custom, is_available=True,
        ).exists())

    def test_license_ends_on_archive_copy_not_playout(self):
        """The playout copy never takes the License link; the archive copy does."""
        user = create_user({
            "email": "autocopy@example.com", "first_name": "a",
            "last_name": "b", "gender": "m", "phone_number": None,
            "mobile_number": None, "birthday": "05.09.1989",
            "street": "s", "house_number": "1", "zipcode": "12345",
            "city": "c",
        })
        license = create_license(user.profile, {
            "title": "Auto copy", "subtitle": None, "description": "d",
            "duration": timedelta(minutes=1), "further_persons": None,
            "category": default_category(), "suggested_date": None,
            "repetitions_allowed": True,
            "media_authority_exchange_allowed": True,
            "youth_protection_necessary": False,
            "store_in_ok_media_library": True,
        })
        License.objects.filter(pk=license.pk).update(number=18628)
        custom_video = _make_video(self.custom, 18628, "18628.mp4")
        license.refresh_from_db()
        self.assertEqual(license.video_file.id, custom_video.id)

        with self.assertLogs("django", level="INFO") as logs:
            self._run([18628])

        playout_video = VideoFile.objects.get(
            number=18628, storage_location=self.playout,
        )
        archive_video = VideoFile.objects.get(
            number=18628, storage_location=self.archive,
        )
        license.refresh_from_db()
        self.assertEqual(license.video_file.id, archive_video.id)
        self.assertFalse(any(
            f"to primary VideoFile {playout_video.id}" in line
            or f"Auto-linked VideoFile {playout_video.id} " in line
            for line in logs.output
        ))

    # --- playout: only PRIMARY ---------------------------------------------

    def test_only_primary_copied_to_playout(self):
        """Playout receives the primary version, not the non-primary one."""
        primary = _make_video(
            self.custom, 18676, "18676_Teil_1_v1.mp4",
            is_manual_primary=True, total_bitrate=4_000_000,
        )
        _make_video(
            self.custom, 18676, "18676_Teil_1.mp4",
            is_manual_primary=False, total_bitrate=10_000_000,
        )

        self._run([18676])

        playout_files = list(
            VideoFile.objects.filter(
                number=18676, storage_location=self.playout, is_available=True,
            )
        )
        self.assertEqual(len(playout_files), 1)
        self.assertEqual(playout_files[0].filename, primary.filename)

    # --- archive: ALL versions ---------------------------------------------

    def test_all_versions_copied_to_archive(self):
        """Archive receives every source version, not just the primary."""
        _make_video(
            self.custom, 18676, "18676_Teil_1_v1.mp4",
            is_manual_primary=True, total_bitrate=4_000_000,
        )
        _make_video(
            self.custom, 18676, "18676_Teil_1.mp4",
            is_manual_primary=False, total_bitrate=10_000_000,
        )

        self._run([18676])

        archive_filenames = sorted(
            VideoFile.objects.filter(
                number=18676, storage_location=self.archive, is_available=True,
            ).values_list("filename", flat=True)
        )
        self.assertEqual(
            archive_filenames, ["18676_Teil_1.mp4", "18676_Teil_1_v1.mp4"],
        )

    # --- primary flag: archive only, not playout ---------------------------

    def test_primary_flag_propagates_to_archive_not_playout(self):
        """Archive copy of primary keeps the flag; playout copy does not."""
        _make_video(
            self.custom, 18676, "18676_Teil_1_v1.mp4",
            is_manual_primary=True, total_bitrate=4_000_000,
        )
        _make_video(
            self.custom, 18676, "18676_Teil_1.mp4",
            is_manual_primary=False, total_bitrate=10_000_000,
        )

        self._run([18676])

        archive_v1 = VideoFile.objects.get(
            number=18676, storage_location=self.archive,
            filename="18676_Teil_1_v1.mp4",
        )
        archive_master = VideoFile.objects.get(
            number=18676, storage_location=self.archive,
            filename="18676_Teil_1.mp4",
        )
        playout_v1 = VideoFile.objects.get(
            number=18676, storage_location=self.playout,
            filename="18676_Teil_1_v1.mp4",
        )
        self.assertTrue(archive_v1.is_manual_primary)
        self.assertFalse(archive_master.is_manual_primary)
        self.assertFalse(playout_v1.is_manual_primary)

    # --- filename-aware duplicate: existing non-primary does not block ------

    def test_existing_non_primary_in_archive_does_not_block_primary(self):
        """A 50fps master already in archive must not block the primary copy."""
        _make_video(
            self.archive, 18676, "18676_Teil_1.mp4",
            is_manual_primary=False, total_bitrate=10_000_000,
        )
        _make_video(
            self.custom, 18676, "18676_Teil_1_v1.mp4",
            is_manual_primary=True, total_bitrate=4_000_000,
        )

        self._run([18676])

        archive_filenames = sorted(
            VideoFile.objects.filter(
                number=18676, storage_location=self.archive, is_available=True,
            ).values_list("filename", flat=True)
        )
        self.assertEqual(
            archive_filenames, ["18676_Teil_1.mp4", "18676_Teil_1_v1.mp4"],
        )
        # The pre-existing master keeps its non-primary status; the freshly
        # copied primary becomes the archive's primary.
        self.assertFalse(
            VideoFile.objects.get(
                number=18676, storage_location=self.archive,
                filename="18676_Teil_1.mp4",
            ).is_manual_primary
        )
        self.assertTrue(
            VideoFile.objects.get(
                number=18676, storage_location=self.archive,
                filename="18676_Teil_1_v1.mp4",
            ).is_manual_primary
        )

    # --- auto-delete from CUSTOM -------------------------------------------

    def test_custom_auto_deleted_after_archive_and_playout(self):
        """CUSTOM sources are removed once archived and played out."""
        _make_video(
            self.custom, 18676, "18676_Teil_1_v1.mp4",
            is_manual_primary=True, total_bitrate=4_000_000,
        )
        _make_video(
            self.custom, 18676, "18676_Teil_1.mp4",
            is_manual_primary=False, total_bitrate=10_000_000,
        )

        self._run([18676])

        self.assertFalse(
            VideoFile.objects.filter(
                number=18676, storage_location=self.custom, is_available=True,
            ).exists()
        )

    # --- primary selection fallback (no manual primary) --------------------

    def test_primary_selection_falls_back_to_algorithm(self):
        """Without a manual flag, is_primary_version() picks the source."""
        from datetime import timedelta
        from django.utils import timezone

        # Two CUSTOM versions, neither manually marked. The newer acceptable
        # one (>= 80% of max bitrate) wins per is_primary_version() rules.
        # created_at (auto_now_add) determines recency, so create older first.
        older = _make_video(
            self.custom, 55555, "55555_old_high.mp4",
            is_manual_primary=False, total_bitrate=10_000_000,
        )
        older.last_scanned = timezone.now() - timedelta(days=2)
        older.save(update_fields=["last_scanned"])
        newer = _make_video(
            self.custom, 55555, "55555_new_ok.mp4",
            is_manual_primary=False, total_bitrate=8_100_000,
        )
        newer.last_scanned = timezone.now()
        newer.save(update_fields=["last_scanned"])

        self._run([55555])

        playout_files = list(
            VideoFile.objects.filter(
                number=55555, storage_location=self.playout, is_available=True,
            )
        )
        self.assertEqual(len(playout_files), 1)
        self.assertEqual(playout_files[0].filename, newer.filename)

    # --- missing video is a non-critical warning ---------------------------

    def test_missing_video_is_warning_not_error(self):
        """A number with no source versions is skipped, not raised."""
        result = self._run([99999])
        self.assertEqual(result["warnings"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["copied_to_archive"], 0)
        self.assertEqual(result["copied_to_playout"], 0)

    def test_repeated_run_treats_existing_copies_as_skipped(self):
        """Running the same plan twice should not fail on existing targets."""
        _make_video(
            self.custom, 18676, "18676_Teil_1_v1.mp4",
            is_manual_primary=True, total_bitrate=4_000_000,
        )

        first_result = self._run([18676])
        second_result = self._run([18676])

        self.assertEqual(first_result["errors"], 0)
        self.assertEqual(second_result["errors"], 0)
        self.assertEqual(second_result["copied_to_archive"], 0)
        self.assertEqual(second_result["copied_to_playout"], 0)
        self.assertGreaterEqual(second_result["skipped"], 1)

    def test_duplicate_running_task_returns_skip_result(self):
        """A matching active lock should skip the duplicate task."""
        with patch("django.core.cache.cache.add", return_value=False):
            result = self._run([18676])

        self.assertTrue(result["task_skipped"])
        self.assertEqual(result["reason"], "same task already running")
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["errors"], 0)

    def test_copy_helper_treats_existing_exact_record_as_success(self):
        """The final VideoFile insert is idempotent for the unique target key."""
        source = _make_video(
            self.custom, 18676, "18676_Teil_1_v1.mp4",
            is_manual_primary=True, total_bitrate=4_000_000,
        )
        _make_video(
            self.archive, 18676, "18676_Teil_1_v1.mp4",
            is_manual_primary=True, total_bitrate=4_000_000,
            content=b"different already copied content",
        )

        with patch(
            "media_files.utils.check_duplicate_before_copy",
            return_value=(False, None, "No duplicate"),
        ):
            success, message = _copy_video_to_storage(source, self.archive, user=None)

        self.assertTrue(success)
        self.assertEqual(message, "Video already exists")
        self.assertEqual(
            VideoFile.objects.filter(
                number=18676,
                storage_location=self.archive,
                file_path="18676_Teil_1_v1.mp4",
            ).count(),
            1,
        )
