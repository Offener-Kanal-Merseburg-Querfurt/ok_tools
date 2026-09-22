"""
Celery tasks for the ok_tools project.
This file defines background tasks that can be scheduled or run asynchronously.
"""

from celery import shared_task
from django.core.management import call_command
from django.conf import settings
import logging

# Configure logger for this module
logger = logging.getLogger(__name__)

@shared_task(name='ok_tools.tasks.run_backup_db_task')
def run_backup_db_task():
    """
    Celery task to run the 'backup_db' Django management command.

    This task is designed to be scheduled via Celery Beat to perform
    periodic database backups. It calls the 'backup_db' command with
    specific arguments like output directory and compression.

    The command executed is roughly equivalent to:
    `python manage.py backup_db --output-dir /path/to/backups --compress`

    Make sure the output directory is accessible and persistent within the
    Docker environment where the Celery worker runs.
    """
    logger.info("Starting scheduled database backup task.")

    # Define arguments for the management command
    # IMPORTANT: Ensure the output directory is mapped correctly in your Docker setup
    # to persist backups outside the container.
    # The backup directory is now configurable via settings
    command_args = {
        'output_dir': getattr(settings, 'BACKUP_DIR', './backups'),  # Use configured backup directory
        'compress': True,           # Enable compression (creates .sql.gz)
    }

    try:
        # Call the Django management command
        call_command('backup_db', **command_args)
        logger.info("Database backup task completed successfully.")
    except Exception as e:
        # Log any errors that occur during the command execution
        logger.error(f"Error occurred during database backup task: {e}")
        # Re-raising the exception can be useful for Celery's error handling/reporting
        raise

@shared_task(name='ok_tools.tasks.run_expire_room_rentals_task')
def run_expire_room_rentals_task():
    """
    Celery task to run the 'expire_room_rentals' Django management command.

    This task is designed to be scheduled via Celery Beat to automatically
    expire room rentals and reservations that have passed their end date.
    It calls the 'expire_room_rentals' command without arguments (default behavior).

    The command executed is roughly equivalent to:
    `python manage.py expire_room_rentals`
    """
    logger.info("Starting scheduled room rental expiration task.")

    # Define arguments for the management command
    command_args = {
        # No specific arguments needed for default operation
        # Example with dry-run: 'dry_run': True
        # Example with verbose: 'verbose': True
    }

    try:
        # Call the Django management command
        call_command('expire_room_rentals', **command_args)
        logger.info("Room rental expiration task completed successfully.")
    except Exception as e:
        # Log any errors that occur during the command execution
        logger.error(f"Error occurred during room rental expiration task: {e}")
        # Re-raising the exception can be useful for Celery's error handling/reporting
        raise

@shared_task(name='ok_tools.tasks.cleanup_old_backups_task')
def cleanup_old_backups_task(backup_dir=None, keep_daily=7, keep_weekly=4, keep_monthly=1):
    """
    Celery task to clean up old backup files based on retention policy.

    Retention policy:
    - Keep the most recent N daily backups (keep_daily).
    - Keep the most recent N weekly backups (keep_weekly) from the remaining after daily cleanup.
    - Keep the most recent N monthly backups (keep_monthly) from the remaining after weekly cleanup.
    - Delete all other old backups.

    Args:
        backup_dir (str): Directory containing backup files (default: settings.BACKUP_DIR).
        keep_daily (int): Number of daily backups to keep (default: 7).
        keep_weekly (int): Number of weekly backups to keep (default: 4).
        keep_monthly (int): Number of monthly backups to keep (default: 1).
    """
    # Use the configured backup directory if none is provided
    if backup_dir is None:
        backup_dir = getattr(settings, 'BACKUP_DIR', './backups')
    logger.info(f"Starting cleanup for old backups in {backup_dir} with policy: "
                f"daily={keep_daily}, weekly={keep_weekly}, monthly={keep_monthly}")

    try:
        import os
        import re
        from datetime import datetime, timedelta

        # Regex to match backup filename format: backup-YYYY-MM-DD_HH-MM-SS.sql(.gz)
        backup_pattern = re.compile(r'backup-(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})\.sql(\.gz)?$')

        # Get all backup files and their parsed dates
        all_backups = []
        for filename in os.listdir(backup_dir):
            match = backup_pattern.match(filename)
            if match:
                filepath = os.path.join(backup_dir, filename)
                if os.path.isfile(filepath):
                    # Parse date from filename
                    year, month, day, hour, minute, second = map(int, match.groups()[:6])
                    file_datetime = datetime(year, month, day, hour, minute, second)
                    all_backups.append((file_datetime, filepath))

        # Sort backups by date, newest first
        all_backups.sort(key=lambda x: x[0], reverse=True)

        now = datetime.now()

        # --- Apply Retention Policy ---
        to_keep = set()
        kept_count = 0

        # 1. Keep most recent 'keep_daily' backups
        daily_cutoff_index = keep_daily
        for i in range(min(daily_cutoff_index, len(all_backups))):
            to_keep.add(all_backups[i][1]) # Add filepath to set
            kept_count += 1

        # 2. From the remaining, keep most recent 'keep_weekly' backups
        weekly_start_index = daily_cutoff_index
        weekly_end_index = weekly_start_index + keep_weekly
        for i in range(weekly_start_index, min(weekly_end_index, len(all_backups))):
            to_keep.add(all_backups[i][1])
            kept_count += 1

        # 3. From the remaining, keep most recent 'keep_monthly' backups
        monthly_start_index = weekly_end_index
        monthly_end_index = monthly_start_index + keep_monthly
        for i in range(monthly_start_index, min(monthly_end_index, len(all_backups))):
            to_keep.add(all_backups[i][1])
            kept_count += 1

        # --- Delete old backups ---
        files_deleted = 0
        for file_datetime, filepath in all_backups:
            if filepath not in to_keep:
                try:
                    os.remove(filepath)
                    logger.info(f"Deleted old backup: {filepath}")
                    files_deleted += 1
                except OSError as e:
                    logger.error(f"Failed to delete {filepath}: {e}")

        logger.info(f"Cleanup completed. {files_deleted} files deleted, {kept_count} files kept according to policy.")

    except Exception as e:
        logger.error(f"Error during backup cleanup: {e}")
        raise

@shared_task(name='ok_tools.tasks.run_cleanup_deleted_nextcloud_videos_task')
def run_cleanup_deleted_nextcloud_videos_task():
    """
    Celery task to run the 'cleanup_deleted_nextcloud_videos' Django management command.
    
    This task checks Nextcloud for deleted videos and marks them as deleted in the database.
    It should be scheduled via Celery Beat to run periodically (e.g., daily).
    
    The command executed is roughly equivalent to:
    `python manage.py cleanup_deleted_nextcloud_videos`
    """
    # Check if Nextcloud is enabled
    if not getattr(settings, 'NEXTCLOUD_ENABLED', False):
        logger.info("Nextcloud integration is disabled. Skipping cleanup task.")
        return
    
    logger.info("Starting cleanup of deleted Nextcloud videos task.")
    
    try:
        # Call the Django management command
        call_command('cleanup_deleted_nextcloud_videos')
        logger.info("Cleanup of deleted Nextcloud videos task completed successfully.")
    except Exception as e:
        logger.error(f"Error occurred during cleanup of deleted Nextcloud videos task: {e}")
        raise


@shared_task(name='ok_tools.tasks.run_cleanup_signing_sessions_task')
def run_cleanup_signing_sessions_task():
    """Celery task to clean up old signing sessions for privacy retention."""
    logger.info("Starting cleanup of old signing sessions task.")

    try:
        call_command('cleanup_signing_sessions')
        logger.info("Cleanup of old signing sessions task completed successfully.")
    except Exception as e:
        logger.error(f"Error occurred during cleanup of old signing sessions task: {e}")
        raise


@shared_task(name='ok_tools.tasks.send_return_reminders_task')
def send_return_reminders_task():
    """Celery task to send automatic return reminders for issued rentals."""
    logger.info("Starting send return reminders task.")

    try:
        call_command('send_return_reminders')
        logger.info("Send return reminders task completed successfully.")
    except Exception as e:
        logger.error(f"Error occurred during send return reminders task: {e}")
        raise


@shared_task(name='ok_tools.tasks.cleanup_stale_task_results_task')
def cleanup_stale_task_results_task(older_than_minutes=60):
    """Close out Celery tasks whose worker vanished (restart, deploy, OOM).

    Such tasks never write a terminal state, so without this they stay in
    PROGRESS forever and have to be deleted by hand in the admin.
    """
    from ok_tools.celery_health import cleanup_orphaned_task_results

    logger.info("Starting cleanup of stale Celery task results.")
    summary = cleanup_orphaned_task_results(older_than_minutes=older_than_minutes)
    if summary['skipped']:
        logger.warning("No Celery worker answered; stale task cleanup skipped.")
    else:
        logger.info(
            "Stale task cleanup finished: %s orphaned, %s closed.",
            summary['orphaned'], summary['closed'],
        )
    summary['export_locks_released'] = _release_orphaned_export_locks(summary)
    return summary


def _release_orphaned_export_locks(summary):
    """Free austausch export locks whose owning task no longer exists.

    The locks outlive a hard-killed worker, so without this a license stays
    un-exportable until its TTL runs out. Nothing is released when no worker
    answered the inspect ping — every task would look dead.
    """
    if summary.get('skipped'):
        return 0
    try:
        from austausch.services.export_locks import release_orphaned_locks
        from ok_tools.celery_health import get_live_task_ids
    except ImportError:
        # austausch is only installed with MEDIA_FILES_ENABLED.
        return 0

    try:
        released = release_orphaned_locks(get_live_task_ids())
    except Exception:
        logger.exception("Could not release orphaned export locks.")
        return 0
    if released:
        logger.info("Released %s orphaned export lock(s).", released)
    return released
