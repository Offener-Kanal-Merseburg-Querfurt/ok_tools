"""Celery tasks for Austausch module."""

from .models import ExchangeConfig
from .models import ExchangeImport
from .models import ExchangeItem
from .services.export_to_server_service import ExportToServerService
from .services.import_service import ImportService
from .services.nextcloud_exchange_service import NextcloudExchangeService
from celery import shared_task
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from licenses.models import License
from licenses.services.peertube_service import compute_lookup_eta
from licenses.services.peertube_service import compute_publish_time_for_license
import logging
import os


logger = logging.getLogger('django')


def enrich_with_oktools_metadata(contribution_id):
    """
    Enrich exchange item with metadata from OK-Tools License.
    
    Args:
        contribution_id: License number (contribution ID)
        
    Returns:
        Dictionary with metadata fields
    """
    metadata = {
        'title': '',
        'description': '',
        'duration': None,
        'sendeverantwortung': '',
    }
    
    if not contribution_id:
        return metadata
    
    try:
        license = License.objects.select_related('profile').get(number=contribution_id)
        
        metadata['title'] = license.title or ''
        metadata['description'] = license.description or ''
        metadata['duration'] = license.duration
        
        # Get sender responsible
        if license.profile:
            first_name = license.profile.first_name or ''
            last_name = license.profile.last_name or ''
            metadata['sendeverantwortung'] = f"{first_name} {last_name}".strip()
    except License.DoesNotExist:
        logger.warning(f"License not found for contribution_id {contribution_id}")
    except Exception as e:
        logger.error(f"Error enriching metadata for contribution_id {contribution_id}: {e}")
    
    return metadata


def get_channels_list(config):
    """
    Get list of channels to sync.
    
    Args:
        config: ExchangeConfig instance
        
    Returns:
        List of channel names
    """
    if config.channels_list:
        # Parse comma-separated list
        channels = [ch.strip() for ch in config.channels_list.split(',') if ch.strip()]
        if channels:
            return channels
    
    # TODO: Auto-discover channels from Nextcloud folder structure
    # For now, return empty list if not configured
    logger.warning("No channels configured in ExchangeConfig.channels_list")
    return []


@shared_task(name='austausch.tasks.sync_exchange_folders', bind=True)
def sync_exchange_folders_task(self):
    """
    Periodic task to scan Nextcloud exchange folders.
    
    Schedule is managed via django-celery-beat admin interface:
    /admin/django_celery_beat/periodictask/ (task name: "sync_exchange_folders")
    
    Discovers new files and updates ExchangeItem records.
    
    Returns:
        dict: Summary of sync operation (items processed, new, updated)
    """
    if not getattr(settings, 'AUSTAUSCH_ENABLED', False):
        logger.warning("Austausch module is disabled, skipping sync task")
        return {'status': 'skipped', 'reason': 'module_disabled'}
    
    logger.info("Starting exchange folders sync task")
    
    try:
        config = ExchangeConfig.get_config()
        if not config.nextcloud_base_url:
            logger.warning("ExchangeConfig not properly configured (missing nextcloud_base_url)")
            return {'status': 'skipped', 'reason': 'config_missing'}
        
        service = NextcloudExchangeService(config)
    except Exception as e:
        logger.error(f"Failed to initialize NextcloudExchangeService: {e}", exc_info=True)
        raise  # Re-raise to ensure task result is marked as FAILURE
    
    # Get list of channels
    channels = get_channels_list(config)
    if not channels:
        logger.warning("No channels to sync")
        # Try to list available folders for debugging
        try:
            available_folders = service.list_root_folders()
            if available_folders:
                logger.info(f"Available folders in Nextcloud root: {', '.join(available_folders[:10])}")
        except Exception as e:
            logger.debug(f"Could not list root folders: {e}")
        return {'status': 'skipped', 'reason': 'no_channels'}
    
    # Calculate lookback date
    lookback_date = timezone.now() - timedelta(days=config.sync_lookback_days)
    
    total_items = 0
    new_items = 0
    updated_items = 0
    
    for channel in channels:
        try:
            logger.info(f"Syncing exchange folder for channel: {channel}")
            items = service.list_exchange_folder(channel)
            
            # Group files by base name to find related .meta.json files
            files_by_base = {}
            for item_data in items:
                total_items += 1
                
                # We do not skip individual files by modified_date here because 
                # a video file might have an old modified_date from when it was created,
                # but its .meta.json was created recently when added to exchange.
                # We will check the package's latest modified date after grouping.
                
                # Detect file type
                file_type = NextcloudExchangeService.detect_file_type(
                    item_data['filename']
                )
                
                # Process video, PDF, .meta.json, and image files (for thumbnails)
                # Skip other file types
                if file_type not in ['video', 'pdf', 'json', 'image']:
                    continue
                
                # Skip .meta.json files themselves (we'll parse them separately)
                if file_type == 'json' and item_data['filename'].endswith('.meta.json'):
                    # Determine package key for .meta.json
                    meta_base_name = item_data['filename'].replace('.meta.json', '')
                    contribution_id_from_meta = NextcloudExchangeService.parse_contribution_id(
                        meta_base_name
                    )
                    
                    if contribution_id_from_meta:
                        package_key = str(contribution_id_from_meta)
                    else:
                        package_key = meta_base_name
                    
                    if package_key not in files_by_base:
                        files_by_base[package_key] = {}
                    files_by_base[package_key]['meta_json'] = item_data
                    continue
                
                # Skip non-.meta.json JSON files
                if file_type == 'json':
                    continue
                
                # Group files by package:
                # 1. If filename starts with number (e.g., "17987_..."), group by number
                # 2. Otherwise, group by base filename (without extension)
                package_key = None
                contribution_id_from_filename = NextcloudExchangeService.parse_contribution_id(
                    item_data['filename']
                )
                
                if contribution_id_from_filename:
                    # Group by contribution ID (number prefix)
                    package_key = str(contribution_id_from_filename)
                else:
                    # Group by base filename (without extension)
                    package_key = '.'.join(item_data['filename'].split('.')[:-1])
                
                if package_key not in files_by_base:
                    files_by_base[package_key] = {}
                
                if file_type == 'video':
                    files_by_base[package_key]['video'] = item_data
                elif file_type == 'pdf':
                    files_by_base[package_key]['pdf'] = item_data
                elif file_type == 'image':
                    # Store first image found as thumbnail
                    if 'thumbnail' not in files_by_base[package_key]:
                        files_by_base[package_key]['thumbnail'] = item_data
            
            # Process grouped files (one ExchangeItem per package)
            for package_key, file_group in files_by_base.items():
                # Check if package is new enough
                latest_modified = None
                for file_key, file_data in file_group.items():
                    modified_date = file_data.get('modified')
                    if modified_date:
                        if timezone.is_naive(modified_date):
                            modified_date = timezone.make_aware(modified_date)
                        if latest_modified is None or modified_date > latest_modified:
                            latest_modified = modified_date
                            
                if latest_modified and latest_modified < lookback_date:
                    logger.debug(f"Skipping old package: {package_key} (latest modified: {latest_modified})")
                    continue
                
                # Get main file (prefer video, then PDF)
                # PDF is part of package, not a separate item
                main_file = file_group.get('video') or file_group.get('pdf')
                if not main_file:
                    # Skip if no video or PDF (only .meta.json)
                    continue
                
                # Get PDF file if available (part of package)
                pdf_file = file_group.get('pdf')
                pdf_path = pdf_file['path'] if pdf_file else ''
                
                # Get thumbnail image if available (part of package)
                thumbnail_file = file_group.get('thumbnail')
                thumbnail_path = thumbnail_file['path'] if thumbnail_file else ''
                
                # Parse .meta.json if available
                meta_data = {}
                if 'meta_json' in file_group:
                    meta_json_path = file_group['meta_json']['path']
                    meta_data = service.parse_meta_json(meta_json_path) or {}
                
                # Parse contribution_id from main filename or package key
                contribution_id = None
                if package_key.isdigit():
                    contribution_id = int(package_key)
                else:
                    contribution_id = NextcloudExchangeService.parse_contribution_id(
                        main_file['filename']
                    )
                
                # Enrich with OK-Tools metadata if contribution_id exists
                oktools_metadata = enrich_with_oktools_metadata(contribution_id) if contribution_id else {}
                
                # Merge metadata: .meta.json takes precedence, then OK-Tools
                final_title = meta_data.get('title') or oktools_metadata.get('title', '')
                final_description = meta_data.get('description') or oktools_metadata.get('description', '')
                final_sender = meta_data.get('sender_responsible') or oktools_metadata.get('sendeverantwortung', '')
                final_duration = meta_data.get('duration') or oktools_metadata.get('duration')
                
                # Create or update ExchangeItem (one per package)
                # Use video file path as unique identifier, or PDF if no video
                exchange_item, created = ExchangeItem.objects.update_or_create(
                    file_path=main_file['path'],
                    channel=channel,
                    defaults={
                        'contribution_id': contribution_id,
                        'filename': main_file['filename'],
                        'file_size': main_file['size'],
                        'file_type': NextcloudExchangeService.detect_file_type(main_file['filename']),
                        'pdf_path': pdf_path,  # Store PDF path as part of package
                        'thumbnail_path': thumbnail_path,  # Store thumbnail path if available
                        'is_oktools_managed': contribution_id is not None,
                        'is_legacy': contribution_id is None,
                        'title': final_title,
                        'description': final_description,
                        'duration': final_duration,
                        'sendeverantwortung': final_sender,
                        'allow_exchange': meta_data.get('allow_exchange', False),
                        'allow_exchange_other_states': meta_data.get('allow_exchange_other_states', False),
                        'bundesland': meta_data.get('bundesland', ''),
                        'bundesland_code': meta_data.get('bundesland_code', ''),
                    }
                )
                
                if created:
                    new_items += 1
                    logger.debug(f"Created new exchange item: {exchange_item}")
                else:
                    updated_items += 1
                    logger.debug(f"Updated exchange item: {exchange_item}")
        
        except Exception as e:
            logger.error(f"Error syncing channel {channel}: {e}", exc_info=True)
            raise  # Re-raise to ensure task result is marked as FAILURE
    
    result = {
        'status': 'completed',
        'total_items': total_items,
        'new_items': new_items,
        'updated_items': updated_items,
        'channels_processed': len(channels)
    }
    
    logger.info(
        f"Exchange sync completed: {total_items} items processed, "
        f"{new_items} new, {updated_items} updated"
    )
    
    return result


@shared_task(name='austausch.tasks.download_exchange_files', queue='download', bind=True, max_retries=3)
def download_exchange_files_task(self, import_record_id):
    """
    Download files from Nextcloud after license creation.
    
    This task runs after license is created to download video and PDF files
    asynchronously via Celery.
    
    Args:
        import_record_id: ExchangeImport ID
        
    Returns:
        Import record ID
    """
    logger.info(f"Starting download task for import record {import_record_id}")
    
    try:
        import_record = ExchangeImport.objects.get(id=import_record_id)
    except ExchangeImport.DoesNotExist:
        logger.error(f"ExchangeImport {import_record_id} not found")
        raise
    
    if import_record.status != 'pending_download':
        logger.warning(
            f"Import record {import_record_id} status is {import_record.status}, "
            f"expected 'pending_download'. Skipping."
        )
        return import_record_id
    
    try:
        import_record.status = 'downloading'
        import_record.save()
        
        exchange_item = import_record.exchange_item
        license = import_record.license
        
        if not license:
            raise Exception("License not found in import record")
        
        # Initialize import service for file operations
        import_service = ImportService(exchange_item, import_record.imported_by)
        
        # Set license in import_service for filename formatting
        import_service.license = license
        
        # Download files
        video_path, pdf_path = import_service._download_files()
        
        # Verify files exist
        if not video_path or not os.path.exists(video_path):
            raise Exception("Video file not downloaded or not found")
        
        import_record.status = 'processing'
        import_record.save()
        
        # Verify checksums if available
        import_service._verify_files(video_path, pdf_path)
        
        # Get or create storage location for imports
        storage_location = import_service._get_import_storage_location()
        
        # Create VideoFile record
        video_file = import_service._create_video_file(license, video_path, storage_location)
        
        # Store PDF if available
        if pdf_path and os.path.exists(pdf_path):
            import_service._store_pdf(license, pdf_path)
        
        # Update import record
        import_record.status = 'completed'
        import_record.video_file = video_file
        import_record.completed_at = timezone.now()
        import_record.save()

        # Ensure exchange item status is consistent with completed import.
        # This covers cases where a previous retry attempt marked it as failed.
        exchange_item.import_status = 'imported'
        if not exchange_item.imported_at:
            exchange_item.imported_at = timezone.now()
        if not exchange_item.imported_license:
            exchange_item.imported_license = license
        exchange_item.save(update_fields=['import_status', 'imported_at', 'imported_license', 'last_seen_at'])
        
        # Optionally: enqueue PeerTube upload
        config = ExchangeConfig.get_config()
        if config.auto_import_enabled:
            import_service._enqueue_peertube_upload(video_file)
        
        logger.info(
            f"Download task completed successfully for import record {import_record_id}, "
            f"license_id={license.id}"
        )
        
        return import_record_id
    except Exception as e:
        import_record.status = 'failed'
        import_record.error_message = str(e)
        import_record.save()
        
        exchange_item = import_record.exchange_item
        exchange_item.import_status = 'failed'
        exchange_item.save()
        
        logger.error(
            f"Download failed for import record {import_record_id}: {e}",
            exc_info=True
        )
        
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task(name='austausch.tasks.import_exchange_item', bind=True, max_retries=3)
def import_exchange_item_task(self, item_id, user_id):
    """
    Async import task with retry logic.
    
    DEPRECATED: Use ImportService.import_item() directly from API,
    which now creates license first and enqueues download task.
    
    Args:
        item_id: ExchangeItem ID
        user_id: User ID performing the import
        
    Returns:
        Import record ID
    """
    logger.warning("import_exchange_item_task is deprecated, use ImportService.import_item() directly")
    
    try:
        exchange_item = ExchangeItem.objects.get(id=item_id)
        user = get_user_model().objects.get(id=user_id)
    except ExchangeItem.DoesNotExist:
        logger.error(f"ExchangeItem {item_id} not found")
        raise
    except get_user_model().DoesNotExist:
        logger.error(f"User {user_id} not found")
        raise
    
    try:
        import_service = ImportService(exchange_item, user)
        import_record, duplicates = import_service.import_item()
        
        logger.info(
            f"Import task completed successfully for item {item_id}, "
            f"import_id={import_record.id}"
        )
        
        return import_record.id
    except Exception as e:
        logger.error(
            f"Import failed for item {item_id}: {e}",
            exc_info=True
        )
        
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@shared_task(name='austausch.tasks.export_to_server', bind=True)
def export_to_server_task(self, selected_ids, mode, user_id=None):
    """
    Export selected contributions or licenses to Nextcloud (video, PDF, JSON, optional thumbnail).
    Saves result to ExportToServerRun for user-visible report.

    Items another export task is already uploading are locked out and reported
    separately rather than exported a second time in parallel; see
    :mod:`austausch.services.export_locks`.

    Args:
        selected_ids: List of contribution IDs (mode='contributions') or license numbers (mode='licenses').
        mode: 'contributions' or 'licenses'.
        user_id: Optional user ID for logging and report.

    Returns:
        dict: success_count, failure_count, skipped_no_pdf_count, details, run_id.
    """
    from .models import ExchangeConfig
    from .models import ExportToServerRun
    from .services.export_locks import ExportItemLocks
    from licenses.tasks import refresh_license_mediathek_url

    User = get_user_model()
    user = User.objects.filter(pk=user_id).first() if user_id else None
    run = ExportToServerRun.objects.create(
        user=user,
        mode=mode,
        total_count=len(selected_ids),
        details={'task_id': str(self.request.id)},
    )

    def progress_callback(current: int, total: int, status: str, item_id: int = None):
        """Report progress to Celery task state."""
        progress = int((current / total) * 100) if total > 0 else 0
        self.update_state(
            state='PROGRESS',
            meta={
                'current': current,
                'total': total,
                'progress': progress,
                'status': status,
                'current_item_id': item_id,
            }
        )

    def file_upload_callback(chunk_num: int, total_chunks: int, percent: float, speed_mbps: float = 0):
        """Report file upload progress to Celery task state."""
        self.update_state(
            state='PROGRESS',
            meta={
                'current': chunk_num,
                'total': total_chunks,
                'progress': int(percent),
                'status': 'uploading',
                'current_item_id': None,
                'speed_mbps': round(speed_mbps, 2),
            }
        )

    lock_enabled = getattr(ExchangeConfig.get_config(), 'export_lock_enabled', True)

    try:
        with ExportItemLocks(mode, selected_ids, self.request.id,
                             enabled=lock_enabled) as locks:
            if locks.busy:
                logger.warning(
                    'Export %s: %s item(s) skipped, already being exported',
                    self.request.id, len(locks.busy))
            service = ExportToServerService(user=user)
            service.set_progress_callback(file_upload_callback)
            report = service.run(
                selected_ids=locks.acquired_ids,
                mode=mode,
                progress_callback=progress_callback,
            )
        run.success_count = report['success_count']
        run.failure_count = report['failure_count']
        run.skipped_no_pdf_count = report['skipped_no_pdf_count']
        # Preserve task_id in details
        run.details = {
            'task_id': str(self.request.id),
            'success_ids': report['success_ids'],
            'success_license_numbers': report.get('success_license_numbers', []),
            'failed': report['failed'],
            'skipped_no_pdf': report['skipped_no_pdf'],
            'covers_generated': report.get('covers_generated', []),
            'source_fallbacks': report.get('source_fallbacks', {}),
            'already_running': locks.busy,
        }
        run.completed_at = timezone.now()
        run.save()

        for license_number in report.get('success_license_numbers', []):
            license_obj = License.objects.filter(number=int(license_number)).first()
            eta = timezone.now()
            if license_obj:
                publish_time = compute_publish_time_for_license(license_obj)
                eta = compute_lookup_eta(publish_time)
            refresh_license_mediathek_url.apply_async(
                args=[int(license_number)],
                kwargs={'force': False},
                eta=eta,
            )

        return {
            'success_count': report['success_count'],
            'failure_count': report['failure_count'],
            'skipped_no_pdf_count': report['skipped_no_pdf_count'],
            'details': run.details,
            'run_id': run.pk,
        }
    except Exception as e:
        run.completed_at = timezone.now()
        run.details = {'error': str(e)}
        run.save()
        raise
