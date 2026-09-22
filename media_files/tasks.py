"""Celery tasks for the media_files app."""

from celery import shared_task
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from licenses.models import License
from media_files.models import FileOperation
from media_files.models import VideoFile
from pathlib import Path
import logging
import os


logger = logging.getLogger(__name__)


@shared_task(name="media_files.tasks.run_auto_scan")
def run_auto_scan_task(**kwargs):
    """Run the auto_scan management command and refresh storage read speeds."""
    logger.info("Starting auto_scan task...")
    
    args = []
    if kwargs.get("delete_missing"):
        args.append("--delete-missing")
    if kwargs.get("force"):
        args.append("--force")
    if kwargs.get("skip_metadata"):
        args.append("--skip-metadata")
    if kwargs.get("strict_check"):
        args.append("--strict-check")
    if kwargs.get("calculate_checksums"):
        args.append("--calculate-checksums")
    if kwargs.get("storage_type"):
        args.extend(["--storage-type", kwargs["storage_type"]])
    
    call_command("auto_scan", *args)

    # Measure how fast each location actually reads, so the export source
    # picker does not have to measure on the hot path — and so a storage
    # degrading quietly shows up here instead of during an incident.
    if kwargs.get("skip_health_check"):
        logger.info("Finished auto_scan task (health check skipped).")
        return

    from media_files.storage_health import refresh_all_storage_health

    try:
        refresh_all_storage_health()
    except Exception:
        logger.exception("Storage health refresh failed after auto_scan.")
    logger.info("Finished auto_scan task.")


@shared_task(name="media_files.tasks.run_scan_video_storage")
def run_scan_video_storage_task(**kwargs):
    """Run the scan_video_storage management command."""
    logger.info("Starting scan_video_storage task...")
    
    from media_files.models import StorageLocation
    
    options = {}
    storage_ids = []
    if kwargs.get("storage_id"):
        options['storage_id'] = kwargs['storage_id']
        storage_ids = [kwargs['storage_id']]
    elif kwargs.get("all"):
        options['all'] = True
        # Get all active storage IDs that will be scanned
        storage_ids = list(StorageLocation.objects.filter(is_active=True).values_list('id', flat=True))
    if kwargs.get("force"):
        options['force'] = True
    if kwargs.get("strict_check"):
        options['strict_check'] = True
    if kwargs.get("calculate_checksum"):
        options['calculate_checksum'] = True
    if kwargs.get("skip_metadata"):
        options['skip_metadata'] = True
    if kwargs.get("delete_missing"):
        options['delete_missing'] = True
    
    call_command("scan_video_storage", **options)
    
    # Update updated_at for scanned storage locations
    if storage_ids:
        StorageLocation.objects.filter(id__in=storage_ids).update(updated_at=timezone.now())
        logger.info(f"Updated updated_at for {len(storage_ids)} storage location(s)")
    
    logger.info("Finished scan_video_storage task.")


@shared_task(name="media_files.tasks.run_link_orphan_licenses")
def run_link_orphan_licenses_task(**kwargs):
    """Run the link_orphan_licenses management command."""
    logger.info("Starting link_orphan_licenses task...")
    
    options = {}
    if kwargs.get("dry_run"):
        options['dry_run'] = True
    if kwargs.get("scan_first"):
        options['scan_first'] = True
        if kwargs.get("force_scan"):
            options['force_scan'] = True
        if kwargs.get("strict_check_scan"):
            options['strict_check_scan'] = True
        if kwargs.get("skip_metadata_scan"):
            options['skip_metadata_scan'] = True
    if kwargs.get("number"):
        options['number'] = kwargs['number']
    
    call_command("link_orphan_licenses", **options)
    logger.info("Finished link_orphan_licenses task.")


@shared_task(name="media_files.tasks.run_sync_licenses_videos")
def run_sync_licenses_videos_task(**kwargs):
    """Run the sync_licenses_videos management command."""
    logger.info("Starting sync_licenses_videos task...")
    
    options = {}
    if kwargs.get("dry_run"):
        options['dry_run'] = True
    if kwargs.get("force_sync_duration"):
        options['force_sync_duration'] = True
    if kwargs.get("number"):
        options['number'] = kwargs['number']
    
    call_command("sync_licenses_videos", **options)
    logger.info("Finished sync_licenses_videos task.")


@shared_task(name="media_files.tasks.run_cleanup_playout")
def run_cleanup_playout_task(**kwargs):
    """Run the cleanup_playout management command."""
    logger.info("Starting cleanup_playout task...")
    
    options = {}
    if kwargs.get("dry_run"):
        options['dry_run'] = True
    if kwargs.get("check_attributes"):
        options['check_attributes'] = True
    if kwargs.get("check_locks"):
        options['check_locks'] = True
    if kwargs.get("older_than"):
        options['older_than'] = kwargs['older_than']
    if kwargs.get("storage_id"):
        options['storage_id'] = kwargs['storage_id']
    
    call_command("cleanup_playout", **options)
    logger.info("Finished cleanup_playout task.")


@shared_task(name="media_files.tasks.run_find_duplicates")
def run_find_duplicates_task(**kwargs):
    """Run the find_duplicates management command."""
    logger.info("Starting find_duplicates task...")
    
    options = {}
    if kwargs.get("json"):
        options['json'] = True
    if kwargs.get("storage_type"):
        options['storage_type'] = kwargs['storage_type']
    
    call_command("find_duplicates", **options)
    logger.info("Finished find_duplicates task.")


@shared_task(name="media_files.tasks.run_cleanup_duplicates")
def run_cleanup_duplicates_task(**kwargs):
    """Run the cleanup_duplicates management command."""
    logger.info("Starting cleanup_duplicates task...")
    
    options = {}
    if kwargs.get("dry_run"):
        options['dry_run'] = True
    if kwargs.get("storage_type"):
        options['storage_type'] = kwargs['storage_type']
    if kwargs.get("number"):
        options['number'] = kwargs['number']
    
    call_command("cleanup_duplicates", **options)
    logger.info("Finished cleanup_duplicates task.")


@shared_task(name="media_files.tasks.run_update_video_metadata")
def run_update_video_metadata_task(**kwargs):
    """Run the update_video_metadata management command."""
    logger.info(f"Starting update_video_metadata task with args: {kwargs}")
    args = ["--all"]
    if kwargs.get("missing_only"):
        args.append("--missing-only")
    call_command("update_video_metadata", *args)
    logger.info("Finished update_video_metadata task.")


@shared_task(name="media_files.tasks.run_cleanup_old_file_operations")
def run_cleanup_old_file_operations_task(**kwargs):
    """Run the cleanup_old_file_operations management command."""
    logger.info("Starting cleanup_old_file_operations task...")
    older_than_days = kwargs.get("older_than_days", 30)
    keep_failed = kwargs.get("keep_failed", True)
    all_types = kwargs.get("all_types", False)
    operation_type = kwargs.get("operation_type")
    
    args = []
    if older_than_days:
        args.extend(["--older-than-days", str(older_than_days)])
    if keep_failed:
        args.append("--keep-failed")
    if all_types:
        args.append("--all-types")
    elif operation_type:
        args.extend(["--operation-type", str(operation_type)])
    
    call_command("cleanup_old_file_operations", *args)
    logger.info("Finished cleanup_old_file_operations task.")


@shared_task(name="media_files.tasks.run_cleanup_missing_files")
def run_cleanup_missing_files_task(**kwargs):
    """Run the cleanup_missing_files management command."""
    logger.info("Starting cleanup_missing_files task...")
    
    args = []
    if kwargs.get("all_storages"):
        args.append("--all-storages")
    elif kwargs.get("storage_id"):
        args.extend(["--storage-id", str(kwargs["storage_id"])])
    else:
        # Default: check all storages
        args.append("--all-storages")
    
    if kwargs.get("mark_unavailable"):
        args.append("--mark-unavailable")
    
    call_command("cleanup_missing_files", *args)
    logger.info("Finished cleanup_missing_files task.")


@shared_task(name="media_files.tasks.render_video_task", queue="render")
def render_video_task(operation_id):
    """
    Render video with overlays asynchronously via Celery.
    
    Args:
        operation_id: FileOperation ID that contains all rendering parameters in details field
    """
    logger.info(f"Starting render_video_task for operation_id={operation_id}")
    
    try:
        # Load operation
        operation = FileOperation.objects.get(id=operation_id)
        
        if operation.status != "IN_PROGRESS":
            logger.warning(f"Operation {operation_id} is not IN_PROGRESS, skipping")
            return
        
        # Extract parameters from operation details
        details = operation.details or {}
        source_video_id = details.get("source_video_id")
        license_number = details.get("license_number")
        encode_name = details.get("encode", "1080p25_9000k")
        is_preview = details.get("preview", False)
        use_intro_outro = details.get("use_intro_outro", False)
        invert_text_color = bool(details.get("invert_text_color", False))
        overlay_text_color_intro = str(
            details.get("overlay_text_color_intro") or ("black" if invert_text_color else "preset")
        ).lower()
        overlay_text_color_outro = str(
            details.get("overlay_text_color_outro") or ("black" if invert_text_color else "preset")
        ).lower()
        if overlay_text_color_intro not in {"preset", "white", "black"}:
            overlay_text_color_intro = "preset"
        if overlay_text_color_outro not in {"preset", "white", "black"}:
            overlay_text_color_outro = "preset"
        overlay_type = details.get("overlay_type")
        elements = details.get("elements", {})
        styles = details.get("styles", {})
        overlay_texts = details.get("overlay_texts", {})
        plain_encode = details.get("plain_encode", False)

        # Get source video
        source_video = VideoFile.objects.get(id=source_video_id)
        new_video = operation.video_file

        if plain_encode:
            from media_files.rendering.ffmpeg import render_plain_encode
            from media_files.utils import extract_video_metadata_fast
            from tools.rendering.presets import load_encode_preset

            encode = load_encode_preset(encode_name)
            source_path = Path(source_video.full_path)
            abs_out = Path(new_video.storage_location.path) / new_video.file_path

            if not source_path.exists() or not source_path.is_file():
                raise FileNotFoundError(f"Source video file not found: {source_video.full_path}")

            abs_out.parent.mkdir(parents=True, exist_ok=True)

            logger.info("Plain encode: %s -> %s (encode=%s)", source_path, abs_out, encode.name)
            render_plain_encode(
                main_video=str(source_path),
                output_mp4=str(abs_out),
                encode=encode,
            )

            with transaction.atomic():
                metadata = extract_video_metadata_fast(str(abs_out))
                new_video.format = metadata.get('format', '')
                new_video.duration = metadata.get('duration')
                new_video.file_size = os.path.getsize(str(abs_out))
                new_video.has_video = metadata.get('has_video', False)
                new_video.video_codec = metadata.get('video_codec', '')
                new_video.fps = metadata.get('fps')
                new_video.width = metadata.get('width')
                new_video.height = metadata.get('height')
                new_video.has_audio = metadata.get('has_audio', False)
                new_video.audio_codec = metadata.get('audio_codec', '')
                new_video.audio_channels = metadata.get('audio_channels')
                new_video.total_bitrate = metadata.get('total_bitrate')
                new_video.is_available = True
                new_video.save()

                if not is_preview and new_video.has_version_suffix():
                    new_video.set_as_primary()

                operation.status = "SUCCESS"
                operation.save(update_fields=["status"])

            logger.info("Successfully rendered plain encode for operation_id=%s, video_id=%s", operation_id, new_video.id)
            return

        # Get license
        if license_number:
            license_obj = License.objects.get(number=int(license_number))
        else:
            license_obj = License.objects.get(number=source_video.number)

        # Build overlays - import here to avoid circular imports
        from django.apps import apps
        from django.conf import settings as django_settings
        from media_files.rendering.ffmpeg import FfmpegError
        from media_files.rendering.ffmpeg import \
            render_preview_overlays_on_main_edges
        from media_files.rendering.ffmpeg import render_with_intro_outro
        from media_files.rendering.ffmpeg import \
            render_with_overlays_on_main_edges
        from media_files.rendering.templates import build_template_context
        from media_files.utils import extract_video_metadata_fast
        from tools.rendering.presets import load_encode_preset
        from tools.rendering.presets import load_style_preset
        from tools.rendering.presets import load_style_preset_from_db

        VideoPresetModel = None
        try:
            VideoPresetModel = apps.get_model("tools", "VideoPreset")
        except Exception:
            VideoPresetModel = None
        
        # Check if this is full intro/outro overlay type (from admin action)
        if overlay_type == "full_intro_outro":
            # Use predefined full overlays (title, subtitle, broadcast_resp, media_authority)
            from tools.rendering.presets import OverlayLayer
            
            default_font = "fonts/Roboto-Bold.ttf"
            regular_font = "fonts/Roboto-Regular.ttf"
            
            # Intro overlays with full text elements
            intro_overlays = [
                # Title - centered horizontally, positioned below center for combined 4-line block
                OverlayLayer(
                    type="text",
                    template="{license.title_wrapped_short}",
                    x="(W-text_w)/2",  # Proper horizontal centering
                    y="(H/2)+70",  # Slightly above center, accounting for title + subtitle block (max 4 lines total)
                    start=0.0,
                    end=5.0,
                    animation="fade",
                    fade_in=0.6,
                    fade_out=0.6,
                    fontsize=64,
                    fontcolor="white",
                    fontfile=default_font,
                    box=False,
                ),
                # Subtitle - centered horizontally, close below title (max 4 lines total: title + subtitle)
                OverlayLayer(
                    type="text",
                    template="{license.subtitle_wrapped}",
                    x="(W-text_w)/2",  # Proper horizontal centering
                    y="(H/2)+220",  # Close below title, forming a combined centered block
                    start=0.2,
                    end=5.0,
                    animation="fade",
                    fade_in=0.5,
                    fade_out=0.4,
                    fontsize=48,
                    fontcolor="white",
                    fontfile=regular_font,
                    box=False,
                ),
                # Broadcast responsibility - right-aligned, bottom
                OverlayLayer(
                    type="text",
                    template="{labels.broadcast_responsibility}: {profile.display}",
                    x="w-text_w-120",  # More padding from right edge
                    y="882",
                    start=0.2,
                    end=5.0,
                    animation="slide_up",
                    fade_in=0.5,
                    fade_out=0.4,
                    fontsize=50,
                    fontcolor="white",
                    fontfile=regular_font,
                ),
                # Media authority - right-aligned, bottom
                OverlayLayer(
                    type="text",
                    template="{profile.media_authority_full_name}, {license.created_year}",
                    x="w-text_w-120",  # More padding from right edge
                    y="947",
                    start=0.2,
                    end=5.0,
                    animation="slide_left",
                    fade_in=0.6,
                    fade_out=0.4,
                    fontsize=38,
                    fontcolor="white",
                    fontfile=regular_font,
                ),
            ]
            
            # Outro overlays (same structure)
            outro_overlays = [
                # Title - centered horizontally, positioned below center for combined 4-line block
                OverlayLayer(
                    type="text",
                    template="{license.title_wrapped_short}",
                    x="(W-text_w)/2",  # Proper horizontal centering
                    y="(H/2)-20",  # Slightly above center, accounting for title + subtitle block (max 4 lines total)
                    start=0.0,
                    end=5.0,
                    animation="fade",
                    fade_in=0.6,
                    fade_out=0.6,
                    fontsize=64,
                    fontcolor="white",
                    fontfile=default_font,
                    box=False,
                ),
                # Subtitle - centered horizontally, close below title (max 4 lines total: title + subtitle)
                OverlayLayer(
                    type="text",
                    template="{license.subtitle_wrapped}",
                    x="(W-text_w)/2",  # Proper horizontal centering
                    y="(H/2)+140",  # Close below title, forming a combined centered block
                    start=0.2,
                    end=5.0,
                    animation="fade",
                    fade_in=0.5,
                    fade_out=0.4,
                    fontsize=48,
                    fontcolor="white",
                    fontfile=regular_font,
                    box=False,
                ),
                # Broadcast responsibility
                OverlayLayer(
                    type="text",
                    template="{labels.broadcast_responsibility}: {profile.display}",
                    x="w-text_w-120",  # More padding from right edge
                    y="882",
                    start=0.2,
                    end=5.0,
                    animation="slide_up",
                    fade_in=0.5,
                    fade_out=0.4,
                    fontsize=50,
                    fontcolor="white",
                    fontfile=regular_font,
                ),
                # Media authority
                OverlayLayer(
                    type="text",
                    template="{profile.media_authority_full_name}, {license.created_year}",
                    x="w-text_w-120",  # More padding from right edge
                    y="947",
                    start=0.2,
                    end=5.0,
                    animation="slide_left",
                    fade_in=0.6,
                    fade_out=0.4,
                    fontsize=38,
                    fontcolor="white",
                    fontfile=regular_font,
                ),
            ]
            segment_duration = 5.0
            # Get intro/outro paths from details (will search for files if not provided)
            intro_path = details.get("intro_clip")
            outro_path = details.get("outro_clip")
            # use_intro_outro will be set after file search if needed
        else:
            # Build overlays based on selected elements and their styles
            intro_overlays = []
            outro_overlays = []
            segment_duration = 5.0
            intro_path = details.get("intro_clip")
            outro_path = details.get("outro_clip")

        def _force_box_color_white_spec(color: str) -> str:
            """
            Keep alpha component (e.g. black@0.45) but force base color to white.
            If parsing fails, return original.
            """
            raw = (color or "").strip()
            if not raw:
                return raw
            base, alpha = (raw.split("@", 1) + [""])[:2]
            # Preserve existing alpha if present; otherwise keep it fully opaque.
            return f"white@{alpha}" if alpha else "white"

        def _force_layers_text_black(layers):
            """
            Force ALL text overlays to pure black (no alpha suffix).
            If a layer uses a text box background, flip it to white (keeping alpha),
            otherwise black text on black box becomes unreadable.
            """
            if not layers:
                return layers
            from dataclasses import replace

            out = []
            for layer in layers:
                try:
                    if getattr(layer, "type", None) != "text":
                        out.append(layer)
                        continue
                    updates = {"fontcolor": "black"}
                    if bool(getattr(layer, "box", False)):
                        updates["boxcolor"] = _force_box_color_white_spec(getattr(layer, "boxcolor", "") or "")
                    out.append(replace(layer, **updates))
                except Exception:
                    out.append(layer)
            return out

        def _force_layers_text_white(layers):
            """Force ALL text overlays to pure white (no alpha suffix)."""
            if not layers:
                return layers
            from dataclasses import replace

            out = []
            for layer in layers:
                try:
                    if getattr(layer, "type", None) != "text":
                        out.append(layer)
                        continue
                    out.append(replace(layer, fontcolor="white"))
                except Exception:
                    out.append(layer)
            return out

        def _apply_layers_text_color(layers, color_choice):
            if color_choice == "black":
                return _force_layers_text_black(layers)
            if color_choice == "white":
                return _force_layers_text_white(layers)
            return layers
        
        def filter_overlays_by_element(overlays, element_type):
            """Filter overlays to only include text overlays relevant to the specified element type."""
            filtered = []
            excluded_templates = []
            
            # Define templates that should be excluded for each element type
            if element_type == "title":
                excluded_templates = [
                    "{license.subtitle",
                    "{labels.broadcast_responsibility",
                    "{profile.media_authority_full_name",
                    "{license.created_year}",
                ]
            elif element_type == "subtitle":
                excluded_templates = [
                    "{license.title",
                    "{labels.broadcast_responsibility",
                    "{profile.media_authority_full_name",
                    "{license.created_year}",
                ]
            elif element_type == "broadcast_resp":
                excluded_templates = [
                    "{license.title",
                    "{license.title_line_wrapped",
                    "{license.subtitle",
                    "{profile.media_authority_full_name",
                    "{license.created_year}",
                ]
            elif element_type == "media_authority":
                excluded_templates = [
                    "{license.title",
                    "{license.title_line_wrapped",
                    "{license.subtitle",
                    "{labels.broadcast_responsibility",
                    "{profile.display}",
                ]
            
            for overlay in overlays:
                # Skip image overlays (logos) - only include text overlays
                if overlay.type == "image":
                    continue
                elif overlay.type == "text" and overlay.template:
                    template = overlay.template.lower()
                    # Exclude overlays that clearly belong to other elements
                    should_exclude = any(excluded in template for excluded in excluded_templates)
                    if not should_exclude:
                        filtered.append(overlay)
            return filtered
        
        # Process each selected element with its style
        show_title = elements.get("title", False)
        show_subtitle = elements.get("subtitle", False)
        show_broadcast_resp = elements.get("broadcast_resp", False)
        show_media_authority = elements.get("media_authority", False)
        
        style_title = styles.get("title")
        style_subtitle = styles.get("subtitle")
        style_broadcast = styles.get("broadcast")
        style_authority = styles.get("authority")
        
        if show_title and style_title:
            try:
                if VideoPresetModel is not None:
                    try:
                        db_preset = VideoPresetModel.objects.get(name=style_title)
                        style_preset = load_style_preset_from_db(db_preset)
                    except VideoPresetModel.DoesNotExist:
                        style_preset = load_style_preset(style_title)
                else:
                    style_preset = load_style_preset(style_title)
                
                title_intro = filter_overlays_by_element(style_preset.intro_overlays, "title")
                title_outro = filter_overlays_by_element(style_preset.outro_overlays, "title")
                intro_overlays.extend(title_intro)
                outro_overlays.extend(title_outro)
                segment_duration = max(segment_duration, style_preset.segment_duration)
            except Exception as e:
                logger.warning(f"Failed to load title style {style_title}: {e}")
        
        if show_subtitle and style_subtitle:
            try:
                if VideoPresetModel is not None:
                    try:
                        db_preset = VideoPresetModel.objects.get(name=style_subtitle)
                        style_preset = load_style_preset_from_db(db_preset)
                    except VideoPresetModel.DoesNotExist:
                        style_preset = load_style_preset(style_subtitle)
                else:
                    style_preset = load_style_preset(style_subtitle)
                
                subtitle_intro = filter_overlays_by_element(style_preset.intro_overlays, "subtitle")
                subtitle_outro = filter_overlays_by_element(style_preset.outro_overlays, "subtitle")
                intro_overlays.extend(subtitle_intro)
                outro_overlays.extend(subtitle_outro)
                segment_duration = max(segment_duration, style_preset.segment_duration)
            except Exception as e:
                logger.warning(f"Failed to load subtitle style {style_subtitle}: {e}")
        
        if show_broadcast_resp and style_broadcast:
            try:
                if VideoPresetModel is not None:
                    try:
                        db_preset = VideoPresetModel.objects.get(name=style_broadcast)
                        style_preset = load_style_preset_from_db(db_preset)
                    except VideoPresetModel.DoesNotExist:
                        style_preset = load_style_preset(style_broadcast)
                else:
                    style_preset = load_style_preset(style_broadcast)
                
                broadcast_intro = filter_overlays_by_element(style_preset.intro_overlays, "broadcast_resp")
                broadcast_outro = filter_overlays_by_element(style_preset.outro_overlays, "broadcast_resp")
                intro_overlays.extend(broadcast_intro)
                outro_overlays.extend(broadcast_outro)
                segment_duration = max(segment_duration, style_preset.segment_duration)
            except Exception as e:
                logger.warning(f"Failed to load broadcast style {style_broadcast}: {e}")
        
        if show_media_authority and style_authority:
            try:
                if VideoPresetModel is not None:
                    try:
                        db_preset = VideoPresetModel.objects.get(name=style_authority)
                        style_preset = load_style_preset_from_db(db_preset)
                    except VideoPresetModel.DoesNotExist:
                        style_preset = load_style_preset(style_authority)
                else:
                    style_preset = load_style_preset(style_authority)
                
                authority_intro = filter_overlays_by_element(style_preset.intro_overlays, "media_authority")
                authority_outro = filter_overlays_by_element(style_preset.outro_overlays, "media_authority")
                intro_overlays.extend(authority_intro)
                outro_overlays.extend(authority_outro)
                segment_duration = max(segment_duration, style_preset.segment_duration)
            except Exception as e:
                logger.warning(f"Failed to load authority style {style_authority}: {e}")
        
        if overlay_type != "full_intro_outro" and not intro_overlays:
            raise ValueError("No valid presets found for selected elements")

        # Optional: force overlay text colors per segment.
        intro_overlays = _apply_layers_text_color(intro_overlays, overlay_text_color_intro)
        outro_overlays = _apply_layers_text_color(outro_overlays, overlay_text_color_outro)
        
        # Load encoding preset
        encode = load_encode_preset(encode_name)
        
        # Get absolute paths
        source_path = Path(source_video.full_path)
        abs_out = Path(new_video.storage_location.path) / new_video.file_path
        
        # Verify source video exists
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Source video file not found: {source_video.full_path}")
        
        # Ensure output directory exists
        abs_out.parent.mkdir(parents=True, exist_ok=True)
        
        # Determine paths to intro and outro files
        # In production: ./data/media is mounted to /app/media
        # In local dev: docker-local/data/media is mounted to /app/media
        # Files should be placed in: <media_root>/intro_outro/intro.mp4 and outro.mp4
        
        from django.conf import settings as django_settings
        media_root = Path(django_settings.MEDIA_ROOT)
        base_dir = Path(django_settings.BASE_DIR)
        
        # Build list of candidate paths in order of preference
        # 1. MEDIA_ROOT/intro_outro/ (works for both production and local)
        # 2. /app/media/intro_outro/ (Docker path - production and local)
        # 3. BASE_DIR relative paths (for local development)
        
        # Only search for intro/outro files if not already provided in details
        if overlay_type != "full_intro_outro" or not intro_path or not outro_path:
            intro_candidates = [
                # Primary: MEDIA_ROOT (works everywhere)
                media_root / "intro_outro" / "intro.mp4",
                # Docker paths (production: ./data/media -> /app/media, local: docker-local/data/media -> /app/media)
                Path("/app/media/intro_outro/intro.mp4"),
                # Local development paths (relative to BASE_DIR)
                base_dir / "docker-local" / "data" / "media" / "intro_outro" / "intro.mp4",
                base_dir / "media" / "intro_outro" / "intro.mp4",
            ]
            outro_candidates = [
                # Primary: MEDIA_ROOT (works everywhere)
                media_root / "intro_outro" / "outro.mp4",
                # Docker paths (production: ./data/media -> /app/media, local: docker-local/data/media -> /app/media)
                Path("/app/media/intro_outro/outro.mp4"),
                # Local development paths (relative to BASE_DIR)
                base_dir / "docker-local" / "data" / "media" / "intro_outro" / "outro.mp4",
                base_dir / "media" / "intro_outro" / "outro.mp4",
            ]
            
            if not intro_path:
                for candidate in intro_candidates:
                    try:
                        if candidate.exists() and candidate.is_file():
                            intro_path = str(candidate.resolve())
                            logger.info(f"Found intro file at: {intro_path}")
                            break
                    except (OSError, ValueError):
                        continue
            
            if not outro_path:
                for candidate in outro_candidates:
                    try:
                        if candidate.exists() and candidate.is_file():
                            outro_path = str(candidate.resolve())
                            logger.info(f"Found outro file at: {outro_path}")
                            break
                    except (OSError, ValueError):
                        continue
        
        # For full_intro_outro type, ensure use_intro_outro is set correctly
        if overlay_type == "full_intro_outro":
            use_intro_outro = bool(intro_path and outro_path)
            if not use_intro_outro:
                error_msg = "Intro/outro files not found for full_intro_outro overlay type"
                if not intro_path:
                    error_msg += " (intro file missing)"
                if not outro_path:
                    error_msg += " (outro file missing)"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
        
        # Render video
        # Extract custom overlay texts if provided
        custom_title = overlay_texts.get("title")
        custom_subtitle = overlay_texts.get("subtitle")
        custom_broadcast = overlay_texts.get("broadcast")
        custom_authority = overlay_texts.get("authority")
        ctx = build_template_context(
            license_obj,
            custom_title=custom_title,
            custom_subtitle=custom_subtitle,
            custom_broadcast=custom_broadcast,
            custom_authority=custom_authority,
        )
        
        if is_preview:
            # Preview mode: always use overlay-only mode (no intro/outro clips)
            render_preview_overlays_on_main_edges(
                main_video=str(source_path),
                output_mp4=str(abs_out),
                encode=encode,
                intro_layers=intro_overlays,
                outro_layers=outro_overlays,
                ctx=ctx,
                segment_duration=segment_duration,
            )
        elif use_intro_outro:
            # User explicitly requested intro/outro mode
            if intro_path and outro_path:
                # Use intro/outro clips with overlays
                logger.info(f"Rendering with intro/outro clips: intro={intro_path}, outro={outro_path}")
                render_with_intro_outro(
                    intro_video=intro_path,
                    main_video=str(source_path),
                    outro_video=outro_path,
                    output_mp4=str(abs_out),
                    encode=encode,
                    intro_layers=intro_overlays,
                    outro_layers=outro_overlays,
                    ctx=ctx,
                )
            else:
                # Files not found but user requested intro/outro mode
                error_msg = "Intro/outro mode requested but files not found"
                if not intro_path:
                    error_msg += f" (intro file missing)"
                if not outro_path:
                    error_msg += f" (outro file missing)"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
        else:
            # Overlay-only mode (overlays on main video edges) - default behavior
            logger.info("Rendering with overlays on main video edges (no intro/outro clips)")
            render_with_overlays_on_main_edges(
                main_video=str(source_path),
                output_mp4=str(abs_out),
                encode=encode,
                intro_layers=intro_overlays,
                outro_layers=outro_overlays,
                ctx=ctx,
                segment_duration=segment_duration,
            )
        
        # Update metadata
        with transaction.atomic():
            # Preview clips are not linked to license; only full renders may replace license link
            if is_preview:
                new_video.is_preview = True
            else:
                # Before saving, handle OneToOne license constraint:
                # If license already has a linked VideoFile, unlink it first
                # The signal will then link the new VideoFile automatically
                if license_obj.video_file and license_obj.video_file.id != new_video.id:
                    old_video = license_obj.video_file
                    VideoFile.objects.filter(pk=old_video.pk).update(license=None)
                    logger.info(f"Unlinked old VideoFile {old_video.id} from License {license_obj.number} before saving new VideoFile {new_video.id}")
            
            metadata = extract_video_metadata_fast(str(abs_out))
            new_video.format = metadata.get('format', '')
            new_video.duration = metadata.get('duration')
            new_video.file_size = os.path.getsize(str(abs_out))
            new_video.has_video = metadata.get('has_video', False)
            new_video.video_codec = metadata.get('video_codec', '')
            new_video.fps = metadata.get('fps')
            new_video.width = metadata.get('width')
            new_video.height = metadata.get('height')
            new_video.has_audio = metadata.get('has_audio', False)
            new_video.audio_codec = metadata.get('audio_codec', '')
            new_video.audio_channels = metadata.get('audio_channels')
            new_video.total_bitrate = metadata.get('total_bitrate')
            new_video.is_available = True
            new_video.save()

            if not is_preview and new_video.has_version_suffix():
                new_video.set_as_primary()

            operation.status = "SUCCESS"
            operation.save(update_fields=["status"])
        
        logger.info(f"Successfully rendered video for operation_id={operation_id}, video_id={new_video.id}")
        
    except FileOperation.DoesNotExist:
        logger.error(f"FileOperation {operation_id} not found")
        raise
    except VideoFile.DoesNotExist:
        logger.error(f"VideoFile not found for operation_id={operation_id}")
        with transaction.atomic():
            operation = FileOperation.objects.get(id=operation_id)
            operation.status = "FAILED"
            operation.error_message = "Source video file not found"
            operation.save(update_fields=["status", "error_message"])
        raise
    except License.DoesNotExist:
        logger.error(f"License not found for operation_id={operation_id}")
        with transaction.atomic():
            operation = FileOperation.objects.get(id=operation_id)
            operation.status = "FAILED"
            operation.error_message = "License not found"
            operation.save(update_fields=["status", "error_message"])
        raise
    except FfmpegError as e:
        logger.error(f"FFmpeg error during rendering for operation_id={operation_id}: {e}")
        with transaction.atomic():
            operation = FileOperation.objects.get(id=operation_id)
            new_video = operation.video_file
            new_video.is_available = False
            new_video.save(update_fields=["is_available"])
            operation.status = "FAILED"
            operation.error_message = str(e)
            operation.save(update_fields=["status", "error_message"])
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during rendering for operation_id={operation_id}")
        with transaction.atomic():
            operation = FileOperation.objects.get(id=operation_id)
            new_video = operation.video_file
            new_video.is_available = False
            new_video.save(update_fields=["is_available"])
            operation.status = "FAILED"
            operation.error_message = str(e)
            operation.save(update_fields=["status", "error_message"])
        raise


@shared_task(name="media_files.tasks.transcode_hevc_to_h264")
def transcode_hevc_to_h264(video_id, user_id=None, encode_preset=None):
    """
    Transcode HEVC/H.265 video to H.264 for browser compatibility.
    
    Args:
        video_id: VideoFile ID to transcode
        user_id: Optional user ID for operation tracking
        encode_preset: Optional encoding preset name (defaults to config setting)
        
    Returns:
        Dictionary with operation result
    """
    from django.contrib.auth import get_user_model
    from media_files.rendering.ffmpeg import LOUDNORM_FILTER
    from pathlib import Path
    import subprocess
    
    User = get_user_model()
    user = User.objects.get(id=user_id) if user_id else None
    
    logger.info(f"Starting HEVC→H.264 transcode for video_id={video_id}")
    
    try:
        # Get source video
        source_video = VideoFile.objects.get(id=video_id)
        
        # Validate it's HEVC
        if source_video.is_browser_compatible:
            logger.info(f"Video {video_id} is already browser compatible, skipping transcode")
            return {
                'success': True,
                'message': 'Video is already browser compatible',
                'video_id': video_id,
                'skipped': True,
            }
        
        # Get encoding preset
        from media_files.config import get_transcode_encode_preset
        from tools.rendering.presets import EncodePreset, load_encode_preset

        preset_name = encode_preset or get_transcode_encode_preset()

        try:
            encode = load_encode_preset(preset_name)
        except Exception as e:
            logger.warning(f"Failed to load preset {preset_name}, using defaults: {e}")
            # Fallback to the EncodePreset dataclass defaults (single source of
            # truth for bitrate/audio), only overriding the source dimensions.
            encode = EncodePreset(
                name=f'{preset_name}-fallback',
                width=source_video.width or 1920,
                height=source_video.height or 1080,
                fps=int(source_video.fps or 25),
                x264_preset='medium',
            )
        
        # Build output path
        source_path = Path(source_video.full_path)
        
        if not source_path.exists():
            raise FileNotFoundError(f"Source video not found: {source_path}")
        
        # Create output filename with _h264 suffix
        stem = source_path.stem
        # Remove _hevc suffix if present
        if stem.endswith('_hevc'):
            stem = stem[:-5]
        
        output_filename = f"{stem}_h264.mp4"
        output_path = source_path.parent / output_filename
        
        # Check if output already exists
        version = 1
        while output_path.exists() and version < 100:
            output_filename = f"{stem}_h264_v{version}.mp4"
            output_path = source_path.parent / output_filename
            version += 1
        
        # Create operation record
        # First create placeholder VideoFile for the output
        rel_path = str(output_path.relative_to(source_video.storage_location.path)).replace("\\", "/")
        
        new_video = VideoFile.objects.create(
            number=source_video.number,
            filename=output_filename,
            file_path=rel_path,
            storage_location=source_video.storage_location,
            is_available=False,  # Will be set True after transcode completes
        )
        
        operation = FileOperation.objects.create(
            video_file=new_video,
            operation_type='RENDER',
            source_location=source_video.storage_location,
            destination_location=source_video.storage_location,
            performed_by=user,
            status='IN_PROGRESS',
            details={
                'source_video_id': source_video.id,
                'transcode_type': 'hevc_to_h264',
                'source_codec': source_video.video_codec,
                'target_codec': 'h264',
                'encode_preset': preset_name,
            }
        )
        
        # Build FFmpeg command
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-i', str(source_path),
            '-c:v', encode.vcodec,
            '-preset', encode.x264_preset,
            '-profile:v', encode.x264_profile,
            '-level:v', '4.1',
            '-b:v', f'{encode.video_bitrate_k}k',
            '-maxrate', f'{int(encode.video_bitrate_k * 1.5)}k',
            '-bufsize', f'{encode.video_bitrate_k * 2}k',
            '-pix_fmt', encode.pix_fmt,
            '-c:a', encode.acodec,
            '-b:a', f'{encode.audio_bitrate_k}k',
            '-ar', str(encode.audio_sample_rate),
            '-ac', str(encode.audio_channels),
            '-af', LOUDNORM_FILTER,
            '-movflags', '+faststart',  # Enable streaming
            str(output_path),
        ]
        
        logger.info(f"Running FFmpeg: {' '.join(cmd)}")
        
        # Run FFmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout for long videos
        )
        
        if result.returncode != 0:
            error_msg = result.stderr[-2000:] if result.stderr else "Unknown FFmpeg error"
            logger.error(f"FFmpeg failed: {error_msg}")
            
            # Update operation as failed
            operation.status = 'FAILED'
            operation.error_message = error_msg
            operation.save()
            
            # Delete placeholder video record
            new_video.delete()
            
            return {
                'success': False,
                'message': f'FFmpeg transcode failed: {error_msg}',
                'video_id': video_id,
            }
        
        # Transcode successful - update metadata
        from media_files.utils import extract_video_metadata_fast
        
        with transaction.atomic():
            metadata = extract_video_metadata_fast(str(output_path))
            
            new_video.format = metadata.get('format', 'mp4')
            new_video.duration = metadata.get('duration')
            new_video.file_size = output_path.stat().st_size
            new_video.has_video = metadata.get('has_video', True)
            new_video.video_codec = metadata.get('video_codec', 'h264')
            new_video.video_codec_long = metadata.get('video_codec_long', 'H.264 / AVC')
            new_video.video_bitrate = metadata.get('video_bitrate')
            new_video.fps = metadata.get('fps')
            new_video.width = metadata.get('width')
            new_video.height = metadata.get('height')
            new_video.aspect_ratio = metadata.get('aspect_ratio')
            new_video.pixel_format = metadata.get('pixel_format')
            new_video.has_audio = metadata.get('has_audio', True)
            new_video.audio_codec = metadata.get('audio_codec')
            new_video.audio_codec_long = metadata.get('audio_codec_long')
            new_video.audio_bitrate = metadata.get('audio_bitrate')
            new_video.audio_sample_rate = metadata.get('audio_sample_rate')
            new_video.audio_channels = metadata.get('audio_channels')
            new_video.total_bitrate = metadata.get('total_bitrate')
            new_video.is_available = True
            new_video.last_scanned = timezone.now()
            new_video.save()

            if new_video.has_version_suffix():
                new_video.set_as_primary()

            operation.status = 'SUCCESS'
            operation.save()
        
        logger.info(
            f"Successfully transcoded video {video_id} to H.264: "
            f"new_video_id={new_video.id}, output={output_path}"
        )
        
        return {
            'success': True,
            'message': 'Video transcoded successfully',
            'source_video_id': video_id,
            'new_video_id': new_video.id,
            'output_path': str(output_path),
        }
        
    except VideoFile.DoesNotExist:
        logger.error(f"VideoFile {video_id} not found")
        return {
            'success': False,
            'message': f'Video {video_id} not found',
            'video_id': video_id,
        }
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg transcode timed out for video {video_id}")
        if 'operation' in locals():
            operation.status = 'FAILED'
            operation.error_message = 'Transcode timed out (exceeded 2 hours)'
            operation.save()
        if 'new_video' in locals():
            new_video.delete()
        return {
            'success': False,
            'message': 'Transcode timed out',
            'video_id': video_id,
        }
    except Exception as e:
        logger.exception(f"Error transcoding video {video_id}")
        if 'operation' in locals():
            operation.status = 'FAILED'
            operation.error_message = str(e)
            operation.save()
        if 'new_video' in locals():
            new_video.delete()
        return {
            'success': False,
            'message': str(e),
            'video_id': video_id,
        }


def _copy_video_to_storage(source_video, destination_storage, user, destination_subfolder=None):
    """
    Helper function to copy video to storage location.
    
    Args:
        source_video: VideoFile instance to copy
        destination_storage: Destination StorageLocation
        user: User performing operation (optional)
        destination_subfolder: Optional subfolder (e.g., "2025_KW_41")
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    from media_files.models import FileOperation
    from media_files.models import VideoFile
    from media_files.utils import check_duplicate_before_copy
    from media_files.utils import copy_file_with_progress
    from pathlib import Path
    import os
    
    try:
        # Check for duplicates
        is_dup, existing, dup_msg = check_duplicate_before_copy(
            source_video, destination_storage
        )
        
        if is_dup and existing:
            # Check if it's the same file (same checksum) or different
            if source_video.checksum and existing.checksum:
                if source_video.checksum == existing.checksum:
                    # Identical file - just update file_path if needed
                    if destination_subfolder and not existing.file_path.startswith(destination_subfolder):
                        # Move to correct weekly folder
                        old_path = Path(destination_storage.path) / existing.file_path
                        new_path = Path(destination_storage.path) / destination_subfolder / source_video.filename
                        new_path.parent.mkdir(parents=True, exist_ok=True)
                        if old_path.exists():
                            os.rename(str(old_path), str(new_path))
                        existing.file_path = f"{destination_subfolder}/{source_video.filename}"
                        existing.save(update_fields=['file_path'])
                    return True, f"Video already exists (identical file)"
                else:
                    # Different file with same number - skip to avoid overwrite
                    return False, f"Different file with same number exists: {dup_msg}"
            else:
                # No checksum - compare by size
                if source_video.file_size == existing.file_size:
                    return True, f"Video already exists (same size)"
                else:
                    return False, f"Different file with same number exists: {dup_msg}"
        
        # Build destination path
        if destination_subfolder:
            dest_path = Path(destination_storage.path) / destination_subfolder / source_video.filename
            file_path = f"{destination_subfolder}/{source_video.filename}"
        else:
            dest_path = Path(destination_storage.path) / source_video.filename
            file_path = source_video.filename
        
        # Ensure destination directory exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create operation record
        operation = FileOperation.objects.create(
            video_file=source_video,
            operation_type='COPY',
            source_location=source_video.storage_location,
            destination_location=destination_storage,
            performed_by=user,
            status='IN_PROGRESS',
        )
        
        # Determine if checksum verification is needed.
        # Use module config (DB-backed) with env fallbacks to keep behavior consistent
        # with admin-configurable settings.
        from media_files.config import get_video_copy_use_md5_for_archive
        from media_files.config import get_video_copy_verify_checksum
        verify_checksum = get_video_copy_verify_checksum()
        use_md5_for_archive = get_video_copy_use_md5_for_archive()
        
        # Get source checksum from database (if available).
        # If we already have a checksum stored on the VideoFile, use it to avoid
        # reading the source file again for checksum calculation.
        source_checksum_from_db = source_video.checksum or None
        verify_by_size_only = False
        
        # For ARCHIVE sources: use size-only verification by default (fastest, no checksum calculation)
        if source_video.storage_location.storage_type == 'ARCHIVE':
            if verify_checksum:
                # Use size-only verification (fastest option for ARCHIVE)
                verify_checksum = True  # Keep True to enable size verification
                verify_by_size_only = True
                logger.info(f"Using size-only verification for ARCHIVE source (fastest, no checksum calculation)")
            else:
                # Skip all verification for ARCHIVE (fastest option)
                verify_by_size_only = False
                logger.info(f"Skipping verification for ARCHIVE source (fastest option)")
        elif verify_checksum:
            # For CUSTOM sources: calculate both source and destination
            logger.info(f"Using SHA256 checksum for {source_video.storage_location.storage_type} source")
        
        # Copy the file
        success, message = copy_file_with_progress(
            str(source_video.full_path), 
            str(dest_path),
            verify_checksum=verify_checksum,
            source_checksum_from_db=source_checksum_from_db,
            verify_by_size_only=verify_by_size_only
        )
        
        if not success:
            # Avoid leaving partially copied files behind. These can later be picked up by scans
            # and incorrectly treated as valid duplicates/primary versions.
            try:
                if dest_path.exists():
                    dest_path.unlink()
            except Exception:
                logger.exception(f"Failed to cleanup destination file after copy failure: {dest_path}")

            operation.status = 'FAILED'
            operation.error_message = message
            operation.save()
            return False, message
        
        # Primary status is meaningful only in ARCHIVE (the permanent source of
        # truth). PLAYOUT is a temporary playing slot, so copies there never
        # carry the manual-primary flag. CUSTOM is a staging area whose files
        # get auto-deleted after archiving.
        propagate_primary = (
            source_video.is_manual_primary
            and destination_storage.storage_type == 'ARCHIVE'
        )

        video_defaults = {
            'filename': source_video.filename,
            'is_available': True,
            'is_manual_primary': propagate_primary,
            'format': source_video.format,
            'file_size': source_video.file_size,
            'duration': source_video.duration,
            'checksum': source_video.checksum,
            'has_video': source_video.has_video,
            'has_audio': source_video.has_audio,
            'video_codec': source_video.video_codec,
            'video_codec_long': source_video.video_codec_long,
            'video_profile': source_video.video_profile,
            'video_bitrate': source_video.video_bitrate,
            'video_bitrate_mode': source_video.video_bitrate_mode,
            'audio_codec': source_video.audio_codec,
            'audio_codec_long': source_video.audio_codec_long,
            'audio_bitrate': source_video.audio_bitrate,
            'audio_sample_rate': source_video.audio_sample_rate,
            'audio_channels': source_video.audio_channels,
            'width': source_video.width,
            'height': source_video.height,
            'fps': source_video.fps,
            'aspect_ratio': source_video.aspect_ratio,
            'pixel_format': source_video.pixel_format,
            'color_space': source_video.color_space,
            'color_range': source_video.color_range,
            'chroma_subsampling': source_video.chroma_subsampling,
            'total_bitrate': source_video.total_bitrate,
            'last_scanned': timezone.now(),
        }
        new_video, created = VideoFile.objects.get_or_create(
            number=source_video.number,
            storage_location=destination_storage,
            file_path=file_path,
            defaults=video_defaults,
        )
        if not created:
            operation.video_file = new_video
            operation.status = 'SUCCESS'
            operation.save()
            logger.info(
                f"VideoFile record already exists for video {new_video.number} "
                f"in {destination_storage.name}: {new_video.file_path}"
            )
            return True, "Video already exists"

        # In ARCHIVE: the freshly copied primary must be the only primary there,
        # so clear the flag from other versions of the same number in this
        # storage. Scoped per-storage (not global) because the same primary may
        # be copied to several storages in one plan run.
        if propagate_primary:
            VideoFile.objects.filter(
                number=new_video.number,
                storage_location=new_video.storage_location,
            ).exclude(id=new_video.id).update(is_manual_primary=False)

        # Update operation with new video reference
        operation.video_file = new_video
        operation.status = 'SUCCESS'
        operation.save()
        
        logger.info(f"Created VideoFile record {new_video.id} for video {new_video.number} in {destination_storage.name}")
        return True, f"Video copied successfully"
        
    except Exception as e:
        error_msg = f'Error copying video: {str(e)}'
        logger.error(error_msg, exc_info=True)

        # Best-effort cleanup: if a partial destination file exists, remove it.
        # Keep fully copied files (same size) to allow future scans to register them.
        try:
            if 'dest_path' in locals() and dest_path.exists():
                src_size = source_video.file_size or 0
                dst_size = dest_path.stat().st_size
                if src_size and dst_size < src_size:
                    dest_path.unlink()
        except Exception:
            logger.exception(f"Failed to cleanup destination file after exception: {locals().get('dest_path')}")
        
        if 'operation' in locals():
            operation.status = 'FAILED'
            operation.error_message = error_msg
            operation.save()
        
        return False, error_msg


def _delete_source_from_custom(source_video, user):
    """
    Delete video file and VideoFile record from CUSTOM storage after successful copy.
    
    Args:
        source_video: VideoFile instance from CUSTOM storage
        user: User performing operation (optional)
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    from media_files.models import FileOperation
    from pathlib import Path
    import os
    
    try:
        # Only delete if source is CUSTOM storage
        if source_video.storage_location.storage_type != 'CUSTOM':
            return False, "Source is not CUSTOM storage"
        
        # Check if file exists
        full_path = Path(source_video.full_path)
        file_exists = full_path.exists()
        
        # Save video info before deletion (needed for logging and operation)
        video_id = source_video.id
        video_number = source_video.number
        storage_name = source_video.storage_location.name
        source_location = source_video.storage_location
        
        if not file_exists:
            logger.warning(f"Source file does not exist: {full_path}")
            # Create operation record before deletion
            operation = FileOperation.objects.create(
                video_file_id=video_id,  # Use ID to avoid issues after deletion
                operation_type='DELETE',
                source_location=source_location,
                destination_location=None,
                performed_by=user,
                status='SUCCESS',
            )
            # Delete record anyway if file is missing
            source_video.delete()
            logger.info(f"Deleted source video record {video_number} (ID: {video_id}) - file was already missing")
            return True, "Source file already missing, deleted record"
        
        # Create operation record BEFORE deleting video_file
        operation = FileOperation.objects.create(
            video_file=source_video,
            operation_type='DELETE',
            source_location=source_location,
            destination_location=None,
            performed_by=user,
            status='IN_PROGRESS',
        )
        # Save operation immediately to ensure it's persisted
        operation.save()
        
        # Delete physical file
        try:
            os.remove(str(full_path))
            logger.info(f"Deleted source file: {full_path}")
        except Exception as e:
            logger.error(f"Error deleting source file {full_path}: {e}")
            operation.status = 'FAILED'
            operation.error_message = f"Error deleting file: {str(e)}"
            operation.save()
            return False, f"Error deleting file: {str(e)}"
        
        # Update operation status BEFORE deleting video_file
        operation.status = 'SUCCESS'
        operation.save()
        
        # Now delete VideoFile record (operation is already saved with status)
        source_video.delete()
        
        logger.info(
            f"Deleted source video {video_number} (ID: {video_id}) from CUSTOM storage "
            f"({storage_name}) - file and database record removed"
        )
        return True, "Source deleted successfully"
        
    except Exception as e:
        error_msg = f'Error deleting source: {str(e)}'
        logger.error(error_msg, exc_info=True)
        
        if 'operation' in locals():
            operation.status = 'FAILED'
            operation.error_message = error_msg
            operation.save()
        
        return False, error_msg


def _copy_videos_for_plan_lock_key(video_numbers, plan_date):
    """Return a stable cache key for the auto-copy task arguments."""
    sorted_numbers = ','.join(map(str, sorted(video_numbers)))
    return f"copy_videos_for_plan:{plan_date}:{sorted_numbers}"


def _copy_result_already_exists(message):
    """Return True when a copy helper result represents an idempotent skip."""
    return 'already exists' in message.lower()


@shared_task(name="media_files.tasks.copy_videos_for_plan", queue="copy")
def copy_videos_for_plan(video_numbers, plan_date, user_id=None):
    """Run auto-copy unless an identical plan copy task is already active."""
    from django.conf import settings
    from django.core.cache import cache
    import uuid

    lock_key = _copy_videos_for_plan_lock_key(video_numbers, plan_date)
    lock_token = uuid.uuid4().hex
    lock_timeout = getattr(settings, 'VIDEO_AUTO_COPY_TASK_LOCK_TIMEOUT', 60 * 60)
    lock_acquired = cache.add(lock_key, lock_token, timeout=lock_timeout)
    if not lock_acquired:
        logger.info("[AUTO-COPY] Skipping duplicate running task: %s", lock_key)
        return {
            'task_skipped': True,
            'reason': 'same task already running',
            'copied_to_archive': 0,
            'copied_to_playout': 0,
            'skipped': len(video_numbers),
            'warnings': 0,
            'errors': 0,
            'details': {'errors': [], 'warnings': []},
        }

    try:
        return _copy_videos_for_plan_unlocked(video_numbers, plan_date, user_id=user_id)
    finally:
        if cache.get(lock_key) == lock_token:
            cache.delete(lock_key)


def _copy_videos_for_plan_unlocked(video_numbers, plan_date, user_id=None):
    """
    Automatically copy videos to archive and playout storage when planning.
    
    Uses smart source selection: prefers CUSTOM if recent, otherwise ARCHIVE.
    
    Args:
        video_numbers: List of video numbers (license numbers)
        plan_date: Date object from planning
        user_id: Optional user ID for operation tracking
        
    Returns:
        Dictionary with operation results
    """
    from datetime import date
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from media_files.models import FileOperation
    from media_files.models import StorageLocation
    from media_files.models import VideoFile
    from media_files.utils import select_best_source_video
    from pathlib import Path
    
    User = get_user_model()
    user = User.objects.get(id=user_id) if user_id else None
    
    logger.info(f"[AUTO-COPY] Starting auto-copy for plan date {plan_date}, {len(video_numbers)} videos")
    
    # Get storage locations
    from media_files.config import get_video_auto_copy_to_archive
    from media_files.config import get_video_auto_copy_to_playout
    from media_files.config import get_video_default_playout_storage_name
    from media_files.config import get_video_default_playout_storage_path
    
    archive_storage = None
    if get_video_auto_copy_to_archive():
        archive_storage = StorageLocation.objects.filter(
            storage_type='ARCHIVE',
            is_active=True
        ).first()
        if not archive_storage:
            logger.warning("VIDEO_AUTO_COPY_TO_ARCHIVE enabled but no ARCHIVE storage found")
    
    playout_storage = None
    if get_video_auto_copy_to_playout():
        # Try to find default playout storage (000_Sendungen for main broadcasts)
        default_playout_name = get_video_default_playout_storage_name()
        default_playout_path = get_video_default_playout_storage_path()
        
        playout_query = StorageLocation.objects.filter(
            storage_type='PLAYOUT',
            is_active=True
        )
        
        # Priority 1: Use configured name
        if default_playout_name and default_playout_name.strip():
            playout_storage = playout_query.filter(name__icontains=default_playout_name).first()
            if playout_storage:
                logger.info(f"Using playout storage by name '{default_playout_name}': {playout_storage.name}")
        
        # Priority 2: Use configured path
        if not playout_storage and default_playout_path and default_playout_path.strip():
            playout_storage = playout_query.filter(path__icontains=default_playout_path).first()
            if playout_storage:
                logger.info(f"Using playout storage by path '{default_playout_path}': {playout_storage.name}")
        
        # Priority 3: Auto-detect by path (000_Sendungen)
        if not playout_storage:
            playout_storage = playout_query.filter(path__icontains='000_Sendungen').first()
            if playout_storage:
                logger.info(f"Auto-detected playout storage by path '000_Sendungen': {playout_storage.name}")
        
        # Priority 4: Auto-detect by name (Sendungen)
        if not playout_storage:
            playout_storage = playout_query.filter(name__icontains='Sendungen').first()
            if playout_storage:
                logger.info(f"Auto-detected playout storage by name 'Sendungen': {playout_storage.name}")
        
        # Priority 5: Fallback to first available
        if not playout_storage:
            playout_storage = playout_query.first()
            if playout_storage:
                logger.warning(f"Using first available playout storage (fallback): {playout_storage.name}")
        
        if not playout_storage:
            logger.warning("VIDEO_AUTO_COPY_TO_PLAYOUT enabled but no PLAYOUT storage found")
    
    if not archive_storage and not playout_storage:
        logger.warning("No target storages configured for auto-copy")
        return {
            'copied_to_archive': 0,
            'copied_to_playout': 0,
            'skipped': 0,
            'errors': len(video_numbers),
        }
    
    # Calculate calendar week folder name
    use_weekly_folders = getattr(settings, 'VIDEO_USE_WEEKLY_FOLDERS', True)
    if use_weekly_folders and playout_storage:
        year, week, _ = plan_date.isocalendar()
        week_folder = f"{year}_KW_{week:02d}"
    else:
        week_folder = None
    
    copied_to_archive = 0
    copied_to_playout = 0
    skipped = 0
    errors = 0
    warnings = 0  # Non-critical errors (e.g., video not found)
    operation_details = {'errors': [], 'warnings': []}
    
    for number in video_numbers:
        try:
            # All source versions for this number (CUSTOM + ARCHIVE); PLAYOUT is a
            # destination and preview clips are not full versions, both excluded.
            source_versions = list(VideoFile.objects.filter(
                number=number,
                is_available=True,
            ).exclude(
                storage_location__storage_type='PLAYOUT'
            ).exclude(
                is_preview=True
            ).select_related('storage_location'))

            if not source_versions:
                # Video not found is a NON-CRITICAL error - it may not be uploaded yet
                logger.warning(f"Video {number}: Not found in source storages (CUSTOM/ARCHIVE)")
                warnings += 1
                operation_details['warnings'].append({
                    'number': number,
                    'message': 'Not found in CUSTOM or ARCHIVE storage'
                })
                continue

            # Select the PRIMARY version for playout. Priority:
            #   1. Manually marked primary (is_manual_primary) - set after render
            #   2. is_primary_version() algorithm (bitrate/storage/recency)
            #   3. select_best_source_video() as last-resort fallback
            primary_video = next(
                (v for v in source_versions if v.is_manual_primary), None
            )
            if primary_video is None:
                for v in source_versions:
                    try:
                        if v.is_primary_version():
                            primary_video = v
                            break
                    except Exception:
                        logger.debug(
                            f"Video {number}: is_primary_version() failed for video {v.id}",
                            exc_info=True,
                        )
            if primary_video is None:
                primary_video, selection_reason = select_best_source_video(number)
                logger.info(
                    f"Video {number}: No primary marked, using best source "
                    f"{primary_video.filename if primary_video else 'N/A'} - {selection_reason}"
                )
            else:
                logger.info(
                    f"Video {number}: Selected PRIMARY {primary_video.filename} "
                    f"from {primary_video.storage_location.name} "
                    f"({primary_video.storage_location.storage_type})"
                )

            if primary_video is None:
                warnings += 1
                operation_details['warnings'].append({
                    'number': number,
                    'message': 'No primary version could be selected'
                })
                continue

            # Step 1: Copy ALL source versions to archive.
            # Each version is copied only if its filename is not already in the
            # archive, so a rendered "_v1" primary lands alongside an existing
            # 50fps master without overwriting or skipping it.
            archive_copy_success = True
            archived_custom_ids = []
            if archive_storage:
                for version in source_versions:
                    if version.storage_location == archive_storage:
                        continue
                    already_archived = VideoFile.objects.filter(
                        number=number,
                        storage_location=archive_storage,
                        filename=version.filename,
                        is_available=True,
                    ).exists()
                    if already_archived:
                        logger.debug(
                            f"Video {number}: {version.filename} already in archive, skipping"
                        )
                        continue
                    success, msg = _copy_video_to_storage(
                        version, archive_storage, user, destination_subfolder=None
                    )
                    if success:
                        already_exists = _copy_result_already_exists(msg)
                        if already_exists:
                            skipped += 1
                            warnings += 1
                            operation_details['warnings'].append({
                                'number': number,
                                'message': f'Archive copy skipped for {version.filename}: {msg}'
                            })
                            logger.info(
                                f"Video {number}: {version.filename} already in archive, skipping"
                            )
                        else:
                            copied_to_archive += 1
                            logger.info(
                                f"Video {number}: copied {version.filename} to archive"
                            )
                        if version.storage_location.storage_type == 'CUSTOM' and not already_exists:
                            archived_custom_ids.append(version.id)
                    else:
                        logger.error(
                            f"Video {number}: \u2717 Failed to copy {version.filename} to archive: {msg}"
                        )
                        errors += 1
                        operation_details['errors'].append({
                            'number': number,
                            'message': f'Archive copy failed for {version.filename}: {msg}'
                        })
                        archive_copy_success = False
            else:
                archive_copy_success = True  # Archive copy not required

            # Step 2: Copy PRIMARY to playout (weekly folder).
            # The existence check is filename-aware so a previously copied
            # non-primary version in the same week does not block the primary.
            playout_copy_success = False
            if playout_storage:
                if week_folder:
                    playout_exists = VideoFile.objects.filter(
                        number=number,
                        storage_location=playout_storage,
                        file_path__startswith=week_folder,
                        filename=primary_video.filename,
                        is_available=True,
                    ).exists()
                else:
                    playout_exists = VideoFile.objects.filter(
                        number=number,
                        storage_location=playout_storage,
                        filename=primary_video.filename,
                        is_available=True,
                    ).exists()

                if not playout_exists:
                    success, msg = _copy_video_to_storage(
                        primary_video, playout_storage, user,
                        destination_subfolder=week_folder
                    )
                    if success:
                        playout_copy_success = True
                        if _copy_result_already_exists(msg):
                            skipped += 1
                            warnings += 1
                            operation_details['warnings'].append({
                                'number': number,
                                'message': f'Playout copy skipped: {msg}'
                            })
                            logger.info(
                                f"Video {number}: PRIMARY already in "
                                f"playout/{week_folder or 'root'}, skipping"
                            )
                        else:
                            copied_to_playout += 1
                            logger.info(
                                f"Video {number}: copied PRIMARY {primary_video.filename} "
                                f"to playout/{week_folder or 'root'}"
                            )
                    else:
                        logger.error(f"Video {number}: \u2717 Failed to copy PRIMARY to playout: {msg}")
                        errors += 1
                        operation_details['errors'].append({
                            'number': number,
                            'message': f'Playout copy failed: {msg}'
                        })
                else:
                    playout_copy_success = True  # Already exists, consider as success
                    logger.debug(
                        f"Video {number}: PRIMARY already in playout/{week_folder or 'root'}, skipping"
                    )
                    skipped += 1
            else:
                playout_copy_success = True  # Playout copy not required
                skipped += 1

            # Step 3: Delete CUSTOM source versions that were archived and
            # (when playout is configured) the primary was played out.
            # CUSTOM is treated as a staging area: once a version is safely in
            # the archive it can be removed from CUSTOM.
            auto_delete_enabled = getattr(settings, 'VIDEO_AUTO_DELETE_FROM_CUSTOM', True)
            if (
                auto_delete_enabled
                and archive_copy_success
                and playout_copy_success
                and archived_custom_ids
            ):
                for custom_id in archived_custom_ids:
                    try:
                        custom_source = VideoFile.objects.filter(
                            id=custom_id,
                            storage_location__storage_type='CUSTOM',
                            is_available=True,
                        ).first()
                        if not custom_source:
                            logger.debug(
                                f"Video {number}: CUSTOM source {custom_id} already deleted or not found"
                            )
                            continue
                        delete_success, delete_msg = _delete_source_from_custom(custom_source, user)
                        if delete_success:
                            logger.info(
                                f"Video {number}: \u2713 Deleted {custom_source.filename} "
                                f"from CUSTOM (archived+played)"
                            )
                        else:
                            logger.warning(
                                f"Video {number}: \u26a0 Failed to delete {custom_source.filename} "
                                f"from CUSTOM: {delete_msg}"
                            )
                    except Exception as e:
                        logger.error(
                            f"Video {number}: Error deleting CUSTOM source {custom_id}: {str(e)}",
                            exc_info=True,
                        )

        except Exception as e:
            logger.error(f"Video {number}: ERROR - {str(e)}", exc_info=True)
            errors += 1
            operation_details['errors'].append({
                'number': number,
                'message': str(e)
            })
    
    logger.info(
        f"[AUTO-COPY] Completed: archive={copied_to_archive}, "
        f"playout={copied_to_playout}, skipped={skipped}, warnings={warnings}, errors={errors}"
    )
    
    result = {
        'copied_to_archive': copied_to_archive,
        'copied_to_playout': copied_to_playout,
        'skipped': skipped,
        'warnings': warnings,
        'errors': errors,
        'details': operation_details
    }
    
    # CRITICAL errors (storage access issues, copy failures) should fail the task.
    # NON-CRITICAL errors (video not found) are treated as warnings and don't fail the task.
    # This allows partial success to be visible while not failing when some videos
    # simply haven't been uploaded yet.
    if errors > 0:
        import json
        raise RuntimeError(json.dumps(result, ensure_ascii=False))

    return result


@shared_task(name="media_files.tasks.run_generate_covers")
def run_generate_covers_task(**kwargs):
    """Run the generate_covers management command.

    Accepts the same options as the command: number, all, missing_only,
    force, limit.
    """
    logger.info("Starting generate_covers task...")

    args = []
    if kwargs.get("number") is not None:
        args.extend(["--number", str(kwargs["number"])])
    if kwargs.get("all"):
        args.append("--all")
    if kwargs.get("missing_only"):
        args.append("--missing-only")
    if kwargs.get("force"):
        args.append("--force")
    if kwargs.get("limit"):
        args.extend(["--limit", str(kwargs["limit"])])

    call_command("generate_covers", *args)
    logger.info("Finished generate_covers task.")
