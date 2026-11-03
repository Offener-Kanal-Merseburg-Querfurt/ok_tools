"""Utility functions for media files management."""

from datetime import datetime
from datetime import timedelta
from django.utils import timezone
from pathlib import Path
from typing import Dict
from typing import Optional
from typing import Tuple
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess


logger = logging.getLogger('django')


def extract_number_from_filename(filename: str) -> Optional[int]:
    """
    Extract license number from filename.
    
    Expected format: <number>_<rest_of_filename>.ext
    Example: 12345_my_video.mp4 -> 12345
    
    Args:
        filename: The filename to parse
        
    Returns:
        License number or None if not found
    """
    match = re.match(r'^(\d+)_', filename)
    if match:
        return int(match.group(1))
    return None


def is_reel_filename(filename: str) -> bool:
    """Return True for generated social reel files, which are not full versions."""
    stem = Path(filename or '').stem.lower()
    return bool(re.search(r'(^|_)reel($|_)', stem))


def storage_root_problem(storage_path: str) -> Optional[str]:
    """
    Return why a storage root cannot be trusted, or None if it looks mounted.

    An unmounted NAS share usually leaves an empty mount point behind, so an
    empty directory is treated as unavailable just like a missing one.
    """
    try:
        if not os.path.isdir(storage_path):
            return f"storage path is not a directory: {storage_path}"
        with os.scandir(storage_path) as entries:
            if next(entries, None) is None:
                return f"storage path is empty: {storage_path}"
    except OSError as e:
        return f"storage path is not readable: {storage_path} ({e})"
    return None


def scan_directory(storage_location, supported_formats=None) -> list:
    """
    Scan directory for video files.
    
    Args:
        storage_location: StorageLocation instance
        supported_formats: List of supported file extensions (e.g., ['mp4', 'mov'])
        
    Returns:
        List of tuples: (filename, relative_path, absolute_path)
    """
    if supported_formats is None:
        from media_files.config import get_video_supported_formats
        supported_formats = get_video_supported_formats()
    
    base_path = Path(storage_location.path)
    
    if not base_path.exists():
        logger.error(f"Storage path does not exist: {base_path}")
        return []
    
    found_files = []
    
    # Walk through all directories
    for root, dirs, files in os.walk(base_path):
        for file in files:
            # Check if file has supported extension
            ext = file.rsplit('.', 1)[-1].lower() if '.' in file else ''
            if ext in supported_formats:
                abs_path = Path(root) / file
                rel_path = abs_path.relative_to(base_path)
                found_files.append((file, str(rel_path), str(abs_path)))
    
    logger.info(f"Found {len(found_files)} video files in {storage_location.name}")
    return found_files


def extract_video_metadata(file_path: str, fast_mode: bool = False) -> Dict:
    """
    Extract comprehensive video metadata using ffprobe.
    
    Args:
        file_path: Absolute path to the video file
        
    Returns:
        Dictionary with extracted metadata
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    metadata = {
        'has_video': False,
        'has_audio': False,
    }
    
    try:
        # Run ffprobe to get JSON output
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
        ]
        
        # In fast mode, only get basic format info, skip streams
        if not fast_mode:
            cmd.append('-show_streams')
        
        cmd.append(file_path)
        
        # Increase timeout for large files (up to 5 minutes)
        timeout = 300 if os.path.getsize(file_path) > 500 * 1024 * 1024 else 30  # 500MB threshold
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        
        if result.returncode != 0:
            err = (result.stderr or '').strip()
            out = (result.stdout or '').strip()
            details = [f"returncode={result.returncode}"]
            if err:
                details.append(f"stderr={err[:1500]}")
            if out:
                details.append(f"stdout={out[:800]}")
            if not err and not out:
                details.append("no stderr/stdout (incomplete file or ffprobe -v quiet)")
            logger.error(f"ffprobe failed for {file_path}: {'; '.join(details)}")
            return metadata
        
        data = json.loads(result.stdout)
        metadata['raw_json'] = data
        
        # Extract format information
        if 'format' in data:
            fmt = data['format']
            # Get format from ffprobe
            ffprobe_format = fmt.get('format_name', '').split(',')[0]
            
            # Determine format based on file extension, not ffprobe
            file_extension = os.path.splitext(file_path)[1].lower()
            extension_formats = {
                '.mp4': 'mp4',
                '.mov': 'mov', 
                '.mpeg': 'mpeg',
                '.mpg': 'mpeg',
                '.avi': 'avi',
                '.mkv': 'mkv',
                '.webm': 'webm',
            }
            
            # Use file extension format if available, otherwise use ffprobe format
            metadata['format'] = extension_formats.get(file_extension, ffprobe_format)
            metadata['file_size'] = int(fmt.get('size', 0))
            metadata['total_bitrate'] = int(fmt.get('bit_rate', 0))
            
            # Duration
            duration_seconds = float(fmt.get('duration', 0))
            if duration_seconds > 0:
                metadata['duration'] = timedelta(seconds=duration_seconds)
        
        # Extract stream information
        if 'streams' in data:
            for stream in data['streams']:
                codec_type = stream.get('codec_type')
                
                if codec_type == 'video':
                    metadata['has_video'] = True
                    metadata['video_codec'] = stream.get('codec_name', '')
                    metadata['video_codec_long'] = stream.get('codec_long_name', '')
                    metadata['video_profile'] = stream.get('profile', '')
                    metadata['video_bitrate'] = int(stream.get('bit_rate', 0))
                    metadata['width'] = stream.get('width')
                    metadata['height'] = stream.get('height')
                    metadata['pixel_format'] = stream.get('pix_fmt', '')
                    metadata['color_space'] = stream.get('color_space', '')
                    metadata['color_range'] = stream.get('color_range', '')
                    
                    # FPS calculation
                    if 'r_frame_rate' in stream:
                        try:
                            num, den = map(int, stream['r_frame_rate'].split('/'))
                            if den != 0:
                                metadata['fps'] = round(num / den, 2)
                        except (ValueError, ZeroDivisionError):
                            pass
                    
                    # Aspect ratio
                    if 'display_aspect_ratio' in stream:
                        metadata['aspect_ratio'] = stream['display_aspect_ratio']
                    elif metadata['width'] and metadata['height']:
                        from math import gcd
                        g = gcd(metadata['width'], metadata['height'])
                        metadata['aspect_ratio'] = f"{metadata['width']//g}:{metadata['height']//g}"
                    
                    # Chroma subsampling from pixel format
                    pix_fmt = metadata['pixel_format']
                    if 'yuv420' in pix_fmt:
                        metadata['chroma_subsampling'] = '4:2:0'
                    elif 'yuv422' in pix_fmt:
                        metadata['chroma_subsampling'] = '4:2:2'
                    elif 'yuv444' in pix_fmt:
                        metadata['chroma_subsampling'] = '4:4:4'
                
                elif codec_type == 'audio':
                    metadata['has_audio'] = True
                    metadata['audio_codec'] = stream.get('codec_name', '')
                    metadata['audio_codec_long'] = stream.get('codec_long_name', '')
                    metadata['audio_bitrate'] = int(stream.get('bit_rate', 0))
                    metadata['audio_sample_rate'] = stream.get('sample_rate')
                    metadata['audio_channels'] = stream.get('channels')
                    metadata['audio_channel_layout'] = stream.get('channel_layout', '')
        
        logger.debug(f"Successfully extracted metadata for {file_path}")
        
    except subprocess.TimeoutExpired:
        logger.error(f"ffprobe timeout for {file_path}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ffprobe output for {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error extracting metadata for {file_path}: {e}")
    
    return metadata


def calculate_checksum(file_path: str, algorithm='sha256') -> str:
    """
    Calculate file checksum.
    
    Args:
        file_path: Absolute path to the file
        algorithm: Hash algorithm ('sha256' or 'md5')
        
    Returns:
        Hexadecimal checksum string
    """
    if algorithm == 'sha256':
        hasher = hashlib.sha256()
    elif algorithm == 'md5':
        hasher = hashlib.md5()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")
    
    try:
        with open(file_path, 'rb') as f:
            # Read in chunks to handle large files
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.error(f"Error calculating checksum for {file_path}: {e}")
        return ''


def _partial_copy_path(destination: Path) -> Path:
    """
    Return a hidden temporary path next to ``destination`` for an in-flight copy.

    The ``.part`` suffix is not a supported video format, so storage scans never
    register an interrupted copy as a video. Staying in the same directory keeps
    the final ``os.replace`` an atomic rename on the same filesystem.
    """
    return destination.with_name(f".{destination.name}.{os.getpid()}.part")


def _remove_partial_copy(path: Path) -> None:
    """Delete a leftover partial copy, logging (not raising) on failure."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception(f"Failed to remove partial copy: {path}")


def copy_file_with_progress(source: str, destination: str, verify_checksum=True, source_checksum_from_db=None, verify_by_size_only=False) -> Tuple[bool, str]:
    """
    Copy file with progress logging and optional integrity verification.
    Calculates destination checksum during copy to avoid reading file twice.

    The data is written to a hidden ``.part`` file next to the destination and
    renamed into place only after verification succeeded. An interrupted copy
    (worker shutdown, time limit, crash) therefore never leaves a truncated file
    under the real name: the partial file is removed on any exception, and one
    left behind by a hard kill is ignored by scans.
    
    Args:
        source: Source file path
        destination: Destination file path
        verify_checksum: Whether to verify checksum after copy
                        - True: Use SHA256, calculate both source and destination
                        - False: Skip verification (fastest)
                        - 'md5': Use MD5, calculate both source and destination
                        - 'destination_only': Calculate only destination (SHA256), skip source
                        - 'md5_destination_only': Calculate only destination (MD5), skip source
        source_checksum_from_db: Pre-calculated checksum from database (for ARCHIVE sources)
                                 If provided, will be used for comparison instead of calculating
        verify_by_size_only: If True, only compare file sizes (fastest, for ARCHIVE sources)
                            No checksum calculation at all
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    import hashlib

    dest_path = Path(destination)
    partial_path = _partial_copy_path(dest_path)

    try:
        # Ensure destination directory exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Get file size for progress reporting and verification
        source_size = os.path.getsize(source)
        file_size_mb = source_size / (1024 * 1024)
        
        logger.info(f"Copying {source} to {destination} ({file_size_mb:.2f} MB)")
        
        # If verify_by_size_only, skip all checksum calculations
        if verify_by_size_only:
            logger.info(f"Using size-only verification (fastest, for ARCHIVE sources)")
            # Just copy the file
            logger.info(f"Starting file copy...")
            shutil.copy2(source, partial_path)
            logger.info(f"File copy completed, verifying by size...")
            
            # Verify by size
            dest_size = os.path.getsize(partial_path)
            if source_size != dest_size:
                _remove_partial_copy(partial_path)
                error_msg = f"Size mismatch - source: {source_size} bytes, destination: {dest_size} bytes"
                logger.error(error_msg)
                return False, error_msg
            os.replace(partial_path, dest_path)
            logger.info(f"Size verification passed ({file_size_mb:.2f} MB)")
            logger.info(f"Successfully copied file to {destination}")
            return True, "File copied successfully"
        
        # Determine checksum algorithm and mode
        checksum_algorithm = 'sha256'  # Default
        skip_source_checksum = False
        
        if verify_checksum == 'md5':
            checksum_algorithm = 'md5'
            verify_checksum = True
        elif verify_checksum == 'destination_only':
            checksum_algorithm = 'sha256'
            skip_source_checksum = True
            verify_checksum = True
        elif verify_checksum == 'md5_destination_only':
            checksum_algorithm = 'md5'
            skip_source_checksum = True
            verify_checksum = True
        
        # Calculate source checksum if needed (skip for ARCHIVE sources)
        source_checksum = source_checksum_from_db  # Use from DB if provided
        
        if verify_checksum and not skip_source_checksum and not source_checksum:
            # Calculate source checksum only if not provided from DB and not skipped
            if checksum_algorithm == 'md5':
                logger.info(f"Calculating source checksum (MD5, faster algorithm)...")
            else:
                logger.info(f"Calculating source checksum (SHA256)...")
            source_checksum = calculate_checksum(source, algorithm=checksum_algorithm)
            logger.info(f"Source checksum calculated ({checksum_algorithm})")
        elif source_checksum:
            logger.info(f"Using source checksum from database ({checksum_algorithm})")
        elif skip_source_checksum:
            logger.info(f"Skipping source checksum calculation (ARCHIVE source)")
        
        # Copy file AND calculate destination checksum simultaneously
        logger.info(f"Starting file copy with integrity verification...")
        
        # Initialize hasher for destination
        if verify_checksum:
            if checksum_algorithm == 'md5':
                dest_hasher = hashlib.md5()
            else:
                dest_hasher = hashlib.sha256()
        else:
            dest_hasher = None
        
        # Copy file in chunks and calculate checksum simultaneously
        with open(source, 'rb') as src_file:
            with open(partial_path, 'wb') as dst_file:
                if dest_hasher:
                    # Copy and calculate checksum in one pass (more efficient)
                    chunk_size = 8192 * 1024  # 8 MB chunks for better performance
                    while True:
                        chunk = src_file.read(chunk_size)
                        if not chunk:
                            break
                        dst_file.write(chunk)
                        dest_hasher.update(chunk)
                else:
                    # Just copy without checksum
                    shutil.copyfileobj(src_file, dst_file)
        
        # Copy metadata (timestamps, etc.)
        shutil.copystat(source, partial_path)
        
        logger.info(f"File copy completed")

        # Always verify by size as a baseline integrity check.
        # This protects against partial copies (e.g. timeouts, network hiccups) even when checksum
        # verification is enabled/disabled or run in destination-only mode.
        dest_size = os.path.getsize(partial_path)
        if source_size != dest_size:
            _remove_partial_copy(partial_path)
            error_msg = f"Size mismatch - source: {source_size} bytes, destination: {dest_size} bytes"
            logger.error(error_msg)
            return False, error_msg
        
        # Verify checksum
        if verify_checksum and source_checksum and dest_hasher:
            dest_checksum = dest_hasher.hexdigest()
            logger.info(f"Verifying integrity (checksum comparison)...")
            if source_checksum != dest_checksum:
                _remove_partial_copy(partial_path)
                error_msg = f"Checksum mismatch ({checksum_algorithm}) - file may be corrupted"
                logger.error(error_msg)
                return False, error_msg
            logger.info(f"Integrity verified ({checksum_algorithm})")
        elif verify_checksum and dest_hasher:
            # Only destination checksum calculated (no source to compare)
            dest_checksum = dest_hasher.hexdigest()
            logger.info(f"Destination checksum calculated ({checksum_algorithm}) - no source comparison")

        os.replace(partial_path, dest_path)
        logger.info(f"Successfully copied file to {destination}")
        return True, "File copied successfully"
        
    except Exception as e:
        _remove_partial_copy(partial_path)
        error_msg = f"Error copying file: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
    except BaseException:
        # Worker shutdown (SystemExit) or an interrupt: drop the partial file
        # and let the signal propagate.
        _remove_partial_copy(partial_path)
        raise


def verify_file_integrity(video_file) -> Tuple[bool, str]:
    """
    Verify file integrity by comparing stored checksum with current file.
    
    Args:
        video_file: VideoFile model instance
        
    Returns:
        Tuple of (is_valid: bool, message: str)
    """
    if not video_file.checksum:
        return False, "No checksum stored for comparison"
    
    full_path = video_file.full_path
    
    if not os.path.exists(full_path):
        return False, "File not found"
    
    try:
        current_checksum = calculate_checksum(full_path)
        
        if current_checksum == video_file.checksum:
            return True, "File integrity verified"
        else:
            return False, "Checksum mismatch - file may be corrupted"
            
    except Exception as e:
        return False, f"Error verifying integrity: {str(e)}"


def generate_thumbnail(file_path: str, output_path: str, timestamp='00:00:05') -> bool:
    """
    Generate thumbnail image from video.
    
    Args:
        file_path: Path to video file (local path or HTTP URL)
        output_path: Path for output thumbnail
        timestamp: Time position for thumbnail (format: HH:MM:SS)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-ss', timestamp,
            '-i', file_path,
            '-vframes', '1',
            '-q:v', '2',
            output_path
        ]
        
        # For HTTP URLs, increase timeout and allow seeking
        timeout = 60 if file_path.startswith(('http://', 'https://')) else 10
        
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        
        if result.returncode == 0 and os.path.exists(output_path):
            logger.info(f"Generated thumbnail: {output_path}")
            return True
        else:
            logger.error(f"Failed to generate thumbnail: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Error generating thumbnail: {e}")
        return False


def generate_thumbnail_from_http_url(
    http_url: str,
    output_path: str,
    timestamp: str = '00:00:05',
    auth: Optional[Tuple[str, str]] = None
) -> bool:
    """
    Generate thumbnail image from video via HTTP URL without downloading entire file.
    Uses ffmpeg with HTTP input, which supports range requests for efficient seeking.
    
    Args:
        http_url: HTTP/HTTPS URL to video file (supports WebDAV)
        output_path: Path for output thumbnail
        timestamp: Time position for thumbnail (format: HH:MM:SS)
        auth: Optional tuple of (username, password) for HTTP authentication
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Build ffmpeg command
        # -ss before -i enables input seeking (more efficient for HTTP)
        # -seekable 1 allows seeking in HTTP streams
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-seekable', '1',  # Allow seeking in HTTP streams
            '-ss', timestamp,  # Seek to position before input
            '-i', http_url,
            '-vframes', '1',  # Extract only one frame
            '-q:v', '2',  # High quality JPEG
            output_path
        ]
        
        # If authentication is required, add it to URL
        # ffmpeg supports http://user:pass@host/path format
        # Need to URL-encode username and password to handle special characters
        if auth:
            from urllib.parse import quote
            from urllib.parse import urlparse
            from urllib.parse import urlunparse
            parsed = urlparse(http_url)
            # URL-encode username and password to handle special characters like @, :, etc.
            encoded_username = quote(auth[0], safe='')
            encoded_password = quote(auth[1], safe='')
            netloc = f"{encoded_username}:{encoded_password}@{parsed.netloc}"
            http_url_with_auth = urlunparse((
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
            cmd[cmd.index(http_url)] = http_url_with_auth
        
        # Run ffmpeg with longer timeout for HTTP (may need to download some data)
        # Log URL without password for debugging
        debug_url = http_url
        if auth:
            from urllib.parse import urlparse
            parsed = urlparse(http_url)
            debug_url = f"{parsed.scheme}://{auth[0]}:***@{parsed.netloc}{parsed.path}"
        logger.info(f"Generating thumbnail from HTTP URL: {debug_url} (timestamp: {timestamp})")
        
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        
        if result.returncode == 0 and os.path.exists(output_path):
            logger.info(f"Generated thumbnail from HTTP URL: {output_path}")
            return True
        else:
            error_msg = result.stderr.decode('utf-8', errors='ignore') if result.stderr else 'Unknown error'
            stdout_msg = result.stdout.decode('utf-8', errors='ignore') if result.stdout else ''
            logger.error(
                f"Failed to generate thumbnail from HTTP URL: {debug_url}\n"
                f"Return code: {result.returncode}\n"
                f"Stderr: {error_msg[:500]}\n"
                f"Stdout: {stdout_msg[:500]}"
            )
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout generating thumbnail from HTTP URL: {http_url}")
        return False
    except Exception as e:
        logger.error(f"Error generating thumbnail from HTTP URL: {e}", exc_info=True)
        return False


def generate_thumbnail_from_http_range(
    http_url: str,
    output_path: str,
    timestamp: str = '00:00:05',
    auth: Optional[Tuple[str, str]] = None,
    range_size: int = 15 * 1024 * 1024  # 15 MB should be enough for first few seconds
) -> bool:
    """
    Generate thumbnail by downloading a small range of video via HTTP Range request.
    This is more reliable than direct HTTP input for ffmpeg with WebDAV auth.
    
    Args:
        http_url: HTTP/HTTPS URL to video file
        output_path: Path for output thumbnail
        timestamp: Time position for thumbnail (format: HH:MM:SS)
        auth: Optional tuple of (username, password) for HTTP authentication
        range_size: Size of range to download in bytes (default 15MB)
        
    Returns:
        True if successful, False otherwise
    """
    import requests
    import tempfile
    
    try:
        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Download first N bytes of video (should contain the frame we need)
        headers = {'Range': f'bytes=0-{range_size-1}'}
        
        response = requests.get(
            http_url,
            auth=auth,
            headers=headers,
            timeout=60,
            stream=True
        )
        
        if response.status_code not in (200, 206):  # 206 = Partial Content
            logger.error(f"Failed to download video range: HTTP {response.status_code}")
            return False
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
            temp_path = temp_file.name
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    temp_file.write(chunk)
        
        try:
            # Generate thumbnail from temporary file
            if generate_thumbnail(temp_path, output_path, timestamp):
                logger.info(f"Generated thumbnail from HTTP range: {output_path}")
                return True
            else:
                logger.error(f"Failed to generate thumbnail from downloaded range")
                return False
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"Error generating thumbnail from HTTP range: {e}", exc_info=True)
        return False


def get_file_modified_time(file_path: str) -> Optional[datetime]:
    """
    Get file modification time as timezone-aware datetime.
    
    Args:
        file_path: Path to file
        
    Returns:
        Datetime object or None
    """
    try:
        mtime = os.path.getmtime(file_path)
        return timezone.make_aware(datetime.fromtimestamp(mtime))
    except Exception as e:
        logger.error(f"Error getting file mtime: {e}")
        return None


def check_duplicate_before_copy(source_video, destination_storage):
    """
    Check if copying would create a duplicate.
    
    Args:
        source_video: VideoFile instance to copy
        destination_storage: StorageLocation where to copy
        
    Returns:
        Tuple of (is_duplicate: bool, existing_video: VideoFile or None, message: str)
    """
    from .models import VideoFile

    # Match by number AND filename so that different versions of the same
    # number (e.g. a rendered "_v1" primary and the original 50fps master) can
    # coexist in one storage location. A true duplicate is the same file
    # (same number + same filename) copied into the same storage again.
    existing = VideoFile.objects.filter(
        number=source_video.number,
        filename=source_video.filename,
        storage_location=destination_storage,
        is_available=True
    ).first()

    if not existing:
        return False, None, "No duplicate"
    
    # Check if files are identical by checksum
    if source_video.checksum and existing.checksum:
        if source_video.checksum == existing.checksum:
            return True, existing, "Identical file already exists (same checksum)"
        else:
            return True, existing, "Different file with same number exists (different checksum)"
    
    # Compare by size if no checksum
    if source_video.file_size == existing.file_size:
        return True, existing, "File with same size already exists"
    
    return True, existing, "File with same number but different characteristics exists"


def select_best_source_video(number, recent_days=None):
    """
    Select best source video with smart priority:
    - Prefer CUSTOM if file is recent (freshly processed)
    - Otherwise prefer ARCHIVE (more stable, higher quality)
    
    Args:
        number: Video number (license number)
        recent_days: Number of days to consider CUSTOM as "recent" 
                    (if None, uses VIDEO_SOURCE_PREFERENCE_CUSTOM_DAYS setting)
        
    Returns:
        Tuple of (VideoFile or None, reason: str)
    """
    from .models import VideoFile
    from datetime import timedelta
    from django.conf import settings

    # Get recent_days from config if not provided
    if recent_days is None:
        from media_files.config import get_video_source_preference_custom_days
        recent_days = get_video_source_preference_custom_days()
    
    # Find all available full versions (exclude PLAYOUT and preview clips)
    all_versions = VideoFile.objects.filter(
        number=number,
        is_available=True
    ).exclude(
        storage_location__storage_type='PLAYOUT'
    ).exclude(
        is_preview=True
    ).select_related('storage_location')
    
    if not all_versions.exists():
        return None, "No source found (not in CUSTOM or ARCHIVE)"
    
    # Check if CUSTOM version is recent (within last N days)
    recent_threshold = timezone.now() - timedelta(days=recent_days)
    
    custom_versions = [v for v in all_versions if v.storage_location.storage_type == 'CUSTOM']
    archive_versions = [v for v in all_versions if v.storage_location.storage_type == 'ARCHIVE']
    
    # If CUSTOM version is recent, prefer it (might be freshly processed)
    recent_custom = [
        v for v in custom_versions 
        if v.updated_at and v.updated_at > recent_threshold
    ]
    
    if recent_custom:
        # Prefer recent CUSTOM version (best bitrate among recent)
        source_video = max(recent_custom, key=lambda v: (v.total_bitrate or 0, v.updated_at))
        days_ago = (timezone.now() - source_video.updated_at).days
        return source_video, f"Recent CUSTOM version (updated {days_ago} days ago, freshly processed)"
    
    # Otherwise use standard priority: ARCHIVE > CUSTOM
    # Priority: storage type > bitrate > date
    storage_priority = {'ARCHIVE': 3, 'CUSTOM': 1}
    
    source_video = max(
        all_versions,
        key=lambda v: (
            storage_priority.get(v.storage_location.storage_type, 0),
            v.total_bitrate or 0,
            v.created_at or timezone.now()
        )
    )
    
    storage_type = source_video.storage_location.storage_type
    bitrate_info = f"{source_video.total_bitrate or 'N/A'} bps" if source_video.total_bitrate else "unknown bitrate"
    
    return source_video, f"Best quality from {storage_type} ({bitrate_info})"


def has_system_attributes(file_path):
    """
    Check if file has hidden/system attributes (Windows) or special permissions (Linux).
    
    Args:
        file_path: Path to file
        
    Returns:
        bool: True if file has system attributes, False otherwise
    """
    import stat
    
    try:
        if os.name == 'nt':  # Windows
            # On Windows, check for hidden/system attributes
            attrs = os.stat(file_path).st_file_attributes
            return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))
        else:  # Linux/Unix
            # On Linux, check for special permissions or attributes
            file_stat = os.stat(file_path)
            # Check if file has special permissions (e.g., +x, setuid, setgid)
            mode = file_stat.st_mode
            # Check for system files (owned by root, etc.)
            return bool(mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX))
    except (OSError, AttributeError):
        # If we can't determine attributes, assume no special attributes
        return False


def is_file_in_use(file_path):
    """
    Check if file is currently in use (locked by another process).
    
    Args:
        file_path: Path to file
        
    Returns:
        bool: True if file is in use, False otherwise
    """
    try:
        if os.name == 'nt':  # Windows
            # Try to open file in exclusive mode
            with open(file_path, 'r+b') as f:
                pass
            return False
        else:  # Linux/Unix
            # Use lsof to check if file is open
            import subprocess
            result = subprocess.run(
                ['lsof', file_path], 
                capture_output=True, 
                text=True,
                timeout=5
            )
            return result.returncode == 0 and result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        # If we can't determine, assume file is not in use
        return False


def copy_video_to_playout(video_file, destination_storage, user=None):
    """
    Copy video to playout storage.
    
    Args:
        video_file: VideoFile instance to copy
        destination_storage: Destination StorageLocation
        user: User performing the operation (optional)
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    from .models import FileOperation
    from .models import VideoFile
    
    try:
        # Check if file already exists at destination
        existing = VideoFile.objects.filter(
            number=video_file.number,
            storage_location=destination_storage,
            is_available=True
        ).first()
        
        if existing:
            return False, f'Video {video_file.number} already exists in {destination_storage.name}'
        
        source_path = video_file.full_path
        dest_path = f"{destination_storage.path.rstrip('/')}/{video_file.filename}"
        
        # Create operation record
        operation = FileOperation.objects.create(
            video_file=video_file,
            operation_type='COPY',
            source_location=video_file.storage_location,
            destination_location=destination_storage,
            performed_by=user,
            status='IN_PROGRESS',
        )
        
        # Copy the file
        success, message = copy_file_with_progress(source_path, dest_path, verify_checksum=True)
        
        if not success:
            operation.status = 'FAILED'
            operation.error_message = message
            operation.save()
            return False, message
        
        # Create new VideoFile record for destination
        new_video = VideoFile.objects.create(
            number=video_file.number,
            filename=video_file.filename,
            file_path=video_file.filename,
            storage_location=destination_storage,
            is_available=True,
            format=video_file.format,
            file_size=video_file.file_size,
            duration=video_file.duration,
            checksum=video_file.checksum,
            has_video=video_file.has_video,
            has_audio=video_file.has_audio,
            video_codec=video_file.video_codec,
            audio_codec=video_file.audio_codec,
            width=video_file.width,
            height=video_file.height,
            fps=video_file.fps,
            total_bitrate=video_file.total_bitrate,
            last_scanned=timezone.now(),
        )
        
        operation.status = 'SUCCESS'
        operation.save()
        
        logger.info(f'Copied video {video_file.number} to {destination_storage.name}')
        return True, f'Video copied to {destination_storage.name} successfully'
        
    except Exception as e:
        error_msg = f'Error copying video: {str(e)}'
        logger.error(error_msg, exc_info=True)
        
        if 'operation' in locals():
            operation.status = 'FAILED'
            operation.error_message = error_msg
            operation.save()
        
        return False, error_msg


def move_video_to_archive(video_file, archive_storage=None, user=None):
    """
    Move video from playout to archive storage.
    
    Args:
        video_file: VideoFile instance to move
        archive_storage: Archive StorageLocation (optional, auto-detect if None)
        user: User performing the operation (optional)
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    from .models import FileOperation
    from .models import StorageLocation
    
    if not archive_storage:
        archive_storage = StorageLocation.objects.filter(
            storage_type='ARCHIVE',
            is_active=True
        ).first()
        
        if not archive_storage:
            return False, 'No ARCHIVE storage configured'
    
    # Check if file has system attributes (still in use)
    if has_system_attributes(video_file.full_path):
        return False, 'File has system attributes - still in use by playout system'
    
    # Check if file is locked
    if is_file_in_use(video_file.full_path):
        return False, 'File is currently in use - cannot move'
    
    try:
        source_path = video_file.full_path
        dest_path = f"{archive_storage.path.rstrip('/')}/{video_file.filename}"
        
        # Create operation record
        operation = FileOperation.objects.create(
            video_file=video_file,
            operation_type='MOVE',
            source_location=video_file.storage_location,
            destination_location=archive_storage,
            performed_by=user,
            status='IN_PROGRESS',
        )
        
        # Ensure destination directory exists
        dest_dir = os.path.dirname(dest_path)
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        
        # Move the file
        shutil.move(source_path, dest_path)
        
        # Update VideoFile record
        video_file.storage_location = archive_storage
        video_file.file_path = video_file.filename
        video_file.save(update_fields=['storage_location', 'file_path'])
        
        operation.status = 'SUCCESS'
        operation.save()
        
        logger.info(f'Moved video {video_file.number} from playout to archive')
        return True, 'Video moved to archive successfully'
        
    except Exception as e:
        error_msg = f'Error moving video to archive: {str(e)}'
        logger.error(error_msg, exc_info=True)
        
        if 'operation' in locals():
            operation.status = 'FAILED'
            operation.error_message = error_msg
            operation.save()
        
        return False, error_msg


def extract_video_metadata_fast(file_path: str) -> Dict:
    """
    Extract video metadata using ffprobe for fastest processing (5.6x faster than pymediainfo).
    Falls back to pymediainfo if ffprobe fails.
    
    Args:
        file_path: Absolute path to the video file
        
    Returns:
        Dictionary with extracted metadata (same format as extract_video_metadata)
    """
    import os
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    # Try ffprobe first (fastest method)
    try:
        metadata = extract_video_metadata(file_path, fast_mode=False)
        if metadata and metadata.get('has_video'):
            return metadata
    except Exception as e:
        logger.warning(f"ffprobe failed for {file_path}: {str(e)}, falling back to pymediainfo")
    
    # Fallback to pymediainfo if ffprobe fails
    metadata = {
        'has_video': False,
        'has_audio': False,
    }
    
    try:
        from pymediainfo import MediaInfo
        
        media_info = MediaInfo.parse(file_path)
        
        if not media_info:
            logger.error(f"pymediainfo failed to parse {file_path}")
            return metadata
        
        # Get general information
        general = media_info.general_tracks[0] if media_info.general_tracks else None
        if general:
            metadata['format'] = general.format
            metadata['file_size'] = general.file_size
            metadata['total_bitrate'] = general.overall_bit_rate
            if general.duration:
                metadata['duration'] = timedelta(milliseconds=float(general.duration))
        
        # Process video tracks
        for track in media_info.video_tracks:
            metadata['has_video'] = True
            metadata['video_codec'] = track.format if track.format else (track.commercial_name if track.commercial_name else track.codec_id)
            metadata['video_codec_long'] = track.format_info if track.format_info else track.format
            metadata['video_profile'] = track.format_profile
            metadata['video_bitrate'] = track.bit_rate
            metadata['width'] = track.width
            metadata['height'] = track.height
            metadata['pixel_format'] = track.color_space or ''
            metadata['color_space'] = track.color_space or ''
            metadata['color_range'] = track.color_range or ''
            
            # FPS
            if track.frame_rate:
                metadata['fps'] = float(track.frame_rate)
            
            # Aspect ratio
            if track.display_aspect_ratio:
                metadata['aspect_ratio'] = track.display_aspect_ratio
            
            # Chroma subsampling
            if track.chroma_subsampling:
                metadata['chroma_subsampling'] = track.chroma_subsampling
                
            break  # Only process first video track
        
        # Process audio tracks
        for track in media_info.audio_tracks:
            metadata['has_audio'] = True
            metadata['audio_codec'] = track.format if track.format else (track.commercial_name if track.commercial_name else track.codec_id)
            metadata['audio_codec_long'] = track.format_info if track.format_info else track.format
            metadata['audio_bitrate'] = track.bit_rate
            metadata['audio_sample_rate'] = track.sampling_rate
            metadata['audio_channels'] = track.channel_s
            if track.channel_layout:
                metadata['audio_channel_layout'] = track.channel_layout
            break  # Only process first audio track
            
    except ImportError:
        logger.warning("pymediainfo not available, falling back to ffprobe")
        return extract_video_metadata(file_path, fast_mode=False)
    except OSError as e:
        if "libmediainfo.so.0" in str(e):
            logger.warning(f"libmediainfo library not available: {e}, falling back to ffprobe")
        else:
            logger.error(f"OS error with pymediainfo for {file_path}: {str(e)}")
        return extract_video_metadata(file_path, fast_mode=False)
    except Exception as e:
        logger.error(f"Error extracting metadata with pymediainfo for {file_path}: {str(e)}")
        return extract_video_metadata(file_path, fast_mode=False)
    
    return metadata


# ---------------------------------------------------------------------------
# Lookups shared by the notification checks, the reel reminder and the export
# ---------------------------------------------------------------------------

def numbers_with_video(numbers) -> set:
    """Return the license numbers that have an available full video file."""
    numbers = list(numbers or [])
    if not numbers:
        return set()
    from media_files.models import VideoFile

    return set(
        VideoFile.objects
        .filter(number__in=numbers, is_available=True, is_preview=False)
        .values_list('number', flat=True)
    )


def numbers_with_reel(numbers) -> set:
    """Return the license numbers that already have a rendered reel.

    Reels are registered as preview clips; the filename carries the marker.
    """
    numbers = list(numbers or [])
    if not numbers:
        return set()
    from media_files.models import VideoFile

    found = set()
    queryset = VideoFile.objects.filter(
        number__in=numbers, is_preview=True).values_list(
            'number', 'filename', 'file_path')
    for number, filename, file_path in queryset:
        if is_reel_filename(filename or '') or is_reel_filename(file_path or ''):
            found.add(number)
    return found


def get_cover_output_dir() -> str:
    """Return the directory holding the canonical covers, or an empty string."""
    try:
        from media_files.covers.config import get_cover_config

        config = get_cover_config()
        return config.output_dir if config.enabled else ''
    except Exception:
        logger.warning('Could not resolve the cover output directory',
                       exc_info=True)
        return ''


def has_cover(number, cover_output_dir: Optional[str] = None) -> bool:
    """Return whether a canonical cover file exists for a license number."""
    directory = (
        cover_output_dir if cover_output_dir is not None
        else get_cover_output_dir()
    )
    if not directory:
        return False
    return os.path.isfile(os.path.join(directory, f'{number}_cover.jpg'))


def numbers_with_cover(numbers) -> set:
    """Return the license numbers that already have a cover image."""
    numbers = list(numbers or [])
    directory = get_cover_output_dir()
    if not numbers or not directory:
        return set()
    return {number for number in numbers if has_cover(number, directory)}


def get_target_encode_preset():
    """Return the encoding preset that defines the expected video format.

    The norm is whatever this channel transcodes to, so it is read from the
    configured preset instead of being hard-coded.
    """
    from django.apps import apps

    if not apps.is_installed('tools'):
        return None
    from media_files.models import MediaFilesConfig

    VideoEncodePreset = apps.get_model('tools.VideoEncodePreset')
    name = (MediaFilesConfig.get_config().transcode_encode_preset or '').strip()
    if name:
        preset = VideoEncodePreset.objects.filter(name=name).first()
        if preset is not None:
            return preset
        logger.warning(
            'Configured transcode preset %r does not exist', name)

    # With a single preset there is nothing to guess; with several, the
    # configured name is the only thing that can decide.
    presets = list(VideoEncodePreset.objects.all()[:2])
    return presets[0] if len(presets) == 1 else None


def format_deviation(video, preset, fps_tolerance: float = 0.05) -> Dict:
    """Return how a video deviates from the preset, or an empty dict.

    ``fps`` is a float filled from ffprobe, which reports values like
    24.999 or 25.000001 for material that is perfectly fine; comparing it
    exactly would flag most of the archive.
    """
    if preset is None:
        return {}
    deviation = {}
    if video.width and video.height and (
            video.width != preset.width or video.height != preset.height):
        deviation['resolution'] = {
            'actual': f'{video.width}x{video.height}',
            'expected': f'{preset.width}x{preset.height}',
        }
    if video.fps and abs(float(video.fps) - float(preset.fps)) > fps_tolerance:
        deviation['fps'] = {
            'actual': round(float(video.fps), 3),
            'expected': preset.fps,
        }
    return deviation
