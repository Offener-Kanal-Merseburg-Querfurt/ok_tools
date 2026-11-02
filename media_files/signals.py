"""Signal handlers for media files."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import VideoFile, FileOperation


logger = logging.getLogger('django')

# When set, auto_link_to_license leaves the License link untouched. Used by
# auto-copy while writing temporary PLAYOUT copies before the ARCHIVE copy
# exists, so the License never ends up pointing at a playout file.
_license_relink_suppressed = ContextVar('license_relink_suppressed', default=False)


@contextmanager
def suppress_license_relink():
    """Skip License auto-linking for VideoFile saves inside this block."""
    token = _license_relink_suppressed.set(True)
    try:
        yield
    finally:
        _license_relink_suppressed.reset(token)


@receiver(post_save, sender=VideoFile)
def auto_link_to_license(sender, instance, created, **kwargs):
    """
    Automatically link VideoFile to License based on number.
    Also sync duration from video to license.
    
    This runs after VideoFile is saved and attempts to find
    a matching License by number. Only the newest VideoFile
    (by created_at or updated_at) will be linked to the License.
    """
    if _license_relink_suppressed.get():
        logger.debug(
            f"License auto-link suppressed for VideoFile {instance.id} (number {instance.number})"
        )
        return
    try:
        from licenses.models import License
        from django.db import transaction
        
        # Find license by number
        try:
            license = License.objects.get(number=instance.number)
        except License.DoesNotExist:
            logger.debug(f"No License found for VideoFile number {instance.number}")
            return
        
        # Find best VideoFile to link (use is_primary_version for stability, not just "newest")
        # This avoids "ping-pong" when updated_at changes during scans
        all_videos = VideoFile.objects.filter(
            number=instance.number,
            is_available=True
        ).exclude(is_preview=True).select_related('storage_location')
        
        if not all_videos.exists():
            logger.debug(f"No VideoFile found for number {instance.number}")
            return
        
        # Use is_primary_version() to determine best video (stable criteria: quality + storage type)
        # This is more stable than just "newest by updated_at" which changes on every scan
        best_video = None
        for video in all_videos:
            if video.is_primary_version():
                best_video = video
                break
        
        # Fallback: if no primary found, use newest by created_at (stable, doesn't change)
        if not best_video:
            best_video = all_videos.order_by('-created_at', '-id').first()
        
        if not best_video:
            logger.debug(f"No suitable VideoFile found for number {instance.number}")
            return
        
        # Check if license is already linked to the best VideoFile
        # Use safe access to avoid RelatedObjectDoesNotExist exception
        try:
            current_video = license.video_file
            has_video_file = current_video is not None
        except License.video_file.RelatedObjectDoesNotExist:
            current_video = None
            has_video_file = False
        
        # Only re-link if current video is different AND not primary (avoid ping-pong)
        if has_video_file and current_video.id != best_video.id:
            # Check if current video is still primary - if yes, don't re-link (avoid ping-pong)
            if current_video.is_primary_version():
                logger.debug(
                    f"License #{license.number} already linked to primary VideoFile {current_video.id}, "
                    f"skipping re-link to {best_video.id} (avoid ping-pong)"
                )
                return
            
            # Re-link only if best_video is actually better (primary) or current is not primary
            with transaction.atomic():
                VideoFile.objects.filter(pk=current_video.pk).update(license=None)
                VideoFile.objects.filter(pk=best_video.pk).update(license=license)
            logger.info(f"Re-linked License #{license.number} from VideoFile {current_video.id} to primary VideoFile {best_video.id}")
        elif not has_video_file:
            # License is not linked, link to best video
            with transaction.atomic():
                VideoFile.objects.filter(pk=best_video.pk).update(license=license)
            logger.info(f"Auto-linked VideoFile {best_video.id} (number {instance.number}) to License #{license.number}")
        else:
            # License is already linked to the best video, nothing to do
            logger.debug(f"License #{license.number} already linked to primary VideoFile {best_video.id}")
        
        # Reload license from DB to get updated video_file relationship
        # (after update() the in-memory object may be stale)
        license.refresh_from_db()
        
        # Check if license has video_file before syncing duration
        # Use safe access to avoid RelatedObjectDoesNotExist exception
        try:
            has_video_file_after = license.video_file is not None
        except License.video_file.RelatedObjectDoesNotExist:
            has_video_file_after = False
        
        if not has_video_file_after:
            # This is normal for some licenses - they just don't have a file yet
            logger.warning(
                f"auto_link_to_license: License #{license.number} has no video_file yet, skipping duration sync."
            )
            return
        
        # Sync duration from best video to license if video has duration
        if best_video.duration:
            # Round to seconds (hh:mm:ss format)
            from datetime import timedelta
            video_duration = best_video.duration
            # Round to nearest second
            rounded_duration = timedelta(seconds=int(video_duration.total_seconds()))
            
            # Only sync if difference is 1 second or more
            if license.duration:
                video_seconds = int(video_duration.total_seconds())
                license_seconds = int(license.duration.total_seconds())
                duration_diff = abs(video_seconds - license_seconds)
                
                if duration_diff >= 1:
                    license.duration = rounded_duration
                    license.save(update_fields=['duration'])
                    logger.info(f"Synced duration from VideoFile to License #{license.number}: {video_duration} → {rounded_duration}")
                else:
                    logger.debug(f"Duration difference < 1 second, no sync needed for License #{license.number}")
            else:
                # License has no duration, sync anyway
                license.duration = rounded_duration
                license.save(update_fields=['duration'])
                logger.info(f"Synced duration from VideoFile to License #{license.number}: {video_duration} → {rounded_duration}")
                
    except Exception as e:
        logger.error(f"Error in auto_link_to_license signal: {e}")


@receiver(post_save, sender='licenses.License')
def auto_link_license_to_video(sender, instance, created, **kwargs):
    """
    Automatically link License to VideoFile based on number.
    Also sync duration from video to license if video exists.
    
    This runs after License is saved and attempts to find
    a matching VideoFile by number. Only the newest VideoFile
    (by created_at or updated_at) will be linked to the License.
    """
    try:
        from licenses.models import License
        from django.db import transaction
        
        # Only process if this is a License instance
        if not isinstance(instance, License):
            return
        
        # Skip video linking for Live broadcasts (they don't have video files)
        if instance.is_live:
            logger.debug(f"License {instance.number} is Live, skipping video link")
            return
            
        if instance.number:
            # Find best VideoFile to link (use is_primary_version for stability)
            all_videos = VideoFile.objects.filter(
                number=instance.number,
                is_available=True
            ).exclude(is_preview=True).select_related('storage_location')
            
            if not all_videos.exists():
                logger.debug(f"No VideoFile found for License number {instance.number}")
                return
            
            # Use is_primary_version() to determine best video (stable criteria)
            best_video = None
            for video in all_videos:
                if video.is_primary_version():
                    best_video = video
                    break
            
            # Fallback: if no primary found, use newest by created_at (stable)
            if not best_video:
                best_video = all_videos.order_by('-created_at', '-id').first()
            
            if not best_video:
                logger.debug(f"No suitable VideoFile found for License number {instance.number}")
                return
            
            # Check if license is already linked to the best VideoFile
            if instance.video_file and instance.video_file.id != best_video.id:
                # Check if current video is still primary - if yes, don't re-link (avoid ping-pong)
                if instance.video_file.is_primary_version():
                    logger.debug(
                        f"License #{instance.number} already linked to primary VideoFile {instance.video_file.id}, "
                        f"skipping re-link to {best_video.id} (avoid ping-pong)"
                    )
                    return
                
                # Re-link only if best_video is actually better (primary) or current is not primary
                current_video = instance.video_file
                with transaction.atomic():
                    VideoFile.objects.filter(pk=current_video.pk).update(license=None)
                    VideoFile.objects.filter(pk=best_video.pk).update(license=instance)
                logger.info(f"Re-linked License #{instance.number} from VideoFile {current_video.id} to primary VideoFile {best_video.id}")
            elif not instance.video_file:
                # License is not linked, link to best video
                with transaction.atomic():
                    VideoFile.objects.filter(pk=best_video.pk).update(license=instance)
                logger.info(f"Auto-linked License {instance.number} to VideoFile {best_video.id}")
            else:
                # License is already linked to the best video, nothing to do
                logger.debug(f"License #{instance.number} already linked to primary VideoFile {best_video.id}")
            
            # Sync duration from best video to license if license has no duration
            if best_video.duration and not instance.duration:
                from datetime import timedelta
                rounded_duration = timedelta(seconds=int(best_video.duration.total_seconds()))
                instance.duration = rounded_duration
                instance.save(update_fields=['duration'])
                logger.info(f"Synced duration from VideoFile to License #{instance.number}: {rounded_duration}")
                
    except Exception as e:
        logger.error(f"Error in auto_link_license_to_video signal: {e}")


@receiver(post_save, sender=VideoFile)
def auto_transcode_hevc_video(sender, instance, created, **kwargs):
    """
    Automatically queue HEVC videos for transcoding to H.264 when auto_transcode_hevc is enabled.
    
    This runs after VideoFile is saved (created or updated with codec info).
    Only triggers for HEVC/H.265 videos that don't already have an H.264 version.
    """
    try:
        from media_files.config import get_auto_transcode_hevc
        
        # Check if auto-transcode is enabled
        if not get_auto_transcode_hevc():
            return
        
        # Only process if this video is not browser compatible (HEVC)
        if instance.is_browser_compatible:
            return
        
        # Skip if this is a transcoded version (filename contains _h264)
        if instance.filename and '_h264' in instance.filename:
            return
        
        # Skip videos that are not available
        if not instance.is_available:
            return
        
        # Check if H.264 version already exists for this number
        h264_exists = VideoFile.objects.filter(
            number=instance.number,
            video_codec__in=['h264', 'avc1', 'avc'],
            is_available=True,
        ).exclude(id=instance.id).exists()
        
        if h264_exists:
            logger.debug(
                f"VideoFile {instance.id} (number {instance.number}) has HEVC codec but H.264 version already exists, skipping auto-transcode"
            )
            return
        
        # Check if transcode is already queued/in progress
        from media_files.models import FileOperation
        pending_transcode = FileOperation.objects.filter(
            video_file__number=instance.number,
            operation_type='RENDER',
            status='IN_PROGRESS',
            details__transcode_type='hevc_to_h264',
        ).exists()
        
        if pending_transcode:
            logger.debug(f"Transcode already in progress for number {instance.number}")
            return
        
        # Queue transcode task
        from media_files.tasks import transcode_hevc_to_h264
        transcode_hevc_to_h264.delay(video_id=instance.id)
        
        logger.info(
            f"Auto-queued HEVC→H.264 transcode for VideoFile {instance.id} "
            f"(number {instance.number}, codec {instance.video_codec})"
        )
        
    except Exception as e:
        # Don't fail save if auto-transcode fails to queue
        logger.error(f"Error in auto_transcode_hevc_video signal: {e}")


@receiver(pre_delete, sender=VideoFile)
def log_video_deletion(sender, instance, **kwargs):
    """
    Log VideoFile deletion to FileOperation.
    
    Note: This does NOT delete the physical file, only the database record.
    This signal runs before deletion, so we can still access the instance.
    
    Note: When deleting through admin, FileOperation records are deleted via raw SQL
    before this signal runs, so we skip logging in that case to avoid conflicts.
    """
    try:
        
        import os
        
        # Check if file exists on disk (handle read-only storage and missing paths gracefully)
        file_exists = False
        if instance.is_available:
            try:
                # Safely get full_path - may fail if storage_location is None or path is missing
                full_path = None
                try:
                    full_path = instance.full_path
                except (AttributeError, TypeError) as e:
                    logger.debug(f'Could not get full_path for video {instance.id} in signal: {e}')
                
                if full_path:
                    try:
                        file_exists = os.path.exists(full_path)
                    except (OSError, PermissionError, IOError):
                        # Storage might be read-only - that's OK
                        pass
            except Exception:
                # Any error - just skip file check
                pass
        
        # Create FileOperation record for deletion log
        # Note: This will be cascade deleted with VideoFile, but it's useful
        # for logging purposes before the actual deletion happens
        FileOperation.objects.create(
            video_file=instance,
            operation_type='DELETE',
            source_location=instance.storage_location,
            status='SUCCESS',
            details={
                'filename': instance.filename if instance.filename else '',
                'path': instance.file_path if instance.file_path else '',
                'file_existed_on_disk': file_exists,
                'note': 'Database record deleted' + (' (file was already removed from disk)' if not file_exists else '')
            }
        )
        logger.info(f"Logged deletion of VideoFile: {instance} (file existed: {file_exists})")
    except Exception as e:
        # Don't fail deletion if logging fails
        logger.error(f"Error logging VideoFile deletion: {e}")

