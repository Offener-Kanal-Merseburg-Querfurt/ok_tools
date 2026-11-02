"""Service for WebDAV operations on Nextcloud exchange folders."""

import logging
import os
import re
import subprocess
import tempfile
import uuid
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote, urljoin
from xml.etree import ElementTree as ET

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

from ..models import ExchangeConfig
from .metadata_normalizer import _coerce_bool
from .metadata_normalizer import normalize_exchange_metadata

logger = logging.getLogger('django')


def _clean_str(value) -> str:
    """str() that maps None (JSON null) to '' instead of 'None'."""
    return '' if value is None else str(value).strip()


class NextcloudExchangeService:
    """Service for WebDAV operations on exchange folders."""
    
    # WebDAV namespaces
    DAV_NS = '{DAV:}'
    OC_NS = '{http://owncloud.org/ns}'
    
    def __init__(self, config: Optional[ExchangeConfig] = None):
        """
        Initialize Nextcloud exchange service.
        
        Args:
            config: ExchangeConfig instance. If None, will fetch singleton.
        """
        if config is None:
            config = ExchangeConfig.get_config()
        
        if not config.nextcloud_base_url:
            raise ImproperlyConfigured(
                _('Nextcloud base URL not configured in ExchangeConfig')
            )
        
        self.config = config
        self.base_url = config.nextcloud_base_url.rstrip('/')
        self.username = config.nextcloud_username
        self.password = config.nextcloud_password
        
        # Support both user files and GroupFolders
        # Try GroupFolders first (common for shared exchange folders)
        # Format: /remote.php/dav/files/{username}/GroupFolders/
        self.webdav_path = f"/remote.php/dav/files/{self.username}/"
        self.groupfolders_path = f"/remote.php/dav/files/{self.username}/GroupFolders/"
        
        # Construct WebDAV base URL
        self.webdav_url = urljoin(self.base_url, self.webdav_path)
        self.groupfolders_url = urljoin(self.base_url, self.groupfolders_path)
    
    def _get_auth(self):
        """Get authentication tuple for requests."""
        return (self.username, self.password)

    # --- Public share upload (same mechanism as UI upload) ---

    def _create_upload_share(self, folder_path: str, expire_hours: int = 2) -> Optional[Dict]:
        """
        Create temporary upload-only public share on a folder.
        Returns dict with share_id, token, upload_url or None on error.
        """
        from datetime import timedelta
        from django.utils import timezone
        local_today = timezone.localdate()
        expire_date_value = local_today + timedelta(days=max(1, int(expire_hours // 24) or 1))
        if expire_date_value <= local_today:
            expire_date_value = local_today + timedelta(days=1)
        expire_date = expire_date_value.strftime('%Y-%m-%d')
        share_path = f'/{folder_path.strip("/")}'
        try:
            r = requests.post(
                f"{self.base_url}/ocs/v2.php/apps/files_sharing/api/v1/shares",
                auth=self._get_auth(),
                headers={'OCS-APIRequest': 'true', 'Accept': 'application/json'},
                data={
                    'path': share_path,
                    'shareType': 3,      # Public link
                    'permissions': 4,    # Upload only (create)
                    'expireDate': expire_date,
                },
                timeout=30,
            )
            if r.status_code not in (200, 201):
                logger.error("Create upload share failed: %s - %s", r.status_code, r.text[:300])
                return None
            data = r.json()
            share_data = data.get('ocs', {}).get('data', {})
            token = share_data.get('token')
            share_id = share_data.get('id')
            if not token:
                logger.error("No token in share response")
                return None
            return {
                'share_id': share_id,
                'token': token,
                'upload_url': f"{self.base_url}/public.php/dav/files/{token}/",
            }
        except Exception as e:
            logger.error("Error creating upload share: %s", e, exc_info=True)
            return None

    def _delete_share(self, share_id) -> bool:
        """Delete a public share by ID."""
        try:
            r = requests.delete(
                f"{self.base_url}/ocs/v2.php/apps/files_sharing/api/v1/shares/{share_id}",
                auth=self._get_auth(),
                headers={'OCS-APIRequest': 'true'},
                timeout=30,
            )
            return r.status_code in (200, 204, 404)
        except Exception:
            return False

    def _upload_via_public_share(self, local_path: str, filename: str, share_token: str) -> bool:
        """
        Upload file via public share WebDAV endpoint using curl.
        
        Uses curl subprocess instead of Python requests because:
        - curl handles large file uploads more reliably
        - Avoids potential issues with Python requests' Expect: 100-continue handling
        - curl is battle-tested for WebDAV uploads
        """
        import subprocess

        # NC32+ format: token in URL path, not in basic auth
        upload_url = f"{self.base_url}/public.php/dav/files/{share_token}/{quote(filename, safe='')}"
        file_size = os.path.getsize(local_path)

        logger.info(
            "Starting curl upload: %s (%s bytes) -> %s",
            local_path, file_size, upload_url
        )

        try:
            # Use curl for reliable large file upload
            # -T: upload file
            # -H: disable Expect header
            # --connect-timeout: connection timeout
            # --max-time: maximum total time (1 hour per GB, minimum 10 min)
            max_time = max(600, int(file_size / (1024 * 1024) * 60))  # ~1 min per MB, min 10 min

            cmd = [
                'curl',
                '-X', 'PUT',
                '-T', local_path,
                '-u', f'{share_token}:',  # NC32+ still accepts auth (backward compatible)
                '-H', 'Expect:',  # Disable Expect: 100-continue
                '-H', 'Content-Type: application/octet-stream',
                '--connect-timeout', '30',
                '--max-time', str(max_time),
                '-s',  # Silent (no progress)
                '-w', '%{http_code}',  # Output status code
                '-o', '/dev/null',  # Discard response body
                upload_url,
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max_time + 60,  # subprocess timeout slightly longer
            )
            
            status_code = result.stdout.strip()
            
            if status_code in ('200', '201', '204'):
                logger.info("Curl upload success: %s (%s bytes)", filename, file_size)
                return True
            
            # If curl failed, get more details
            cmd_verbose = cmd.copy()
            cmd_verbose.remove('-s')
            cmd_verbose.remove('-o')
            cmd_verbose.remove('/dev/null')
            idx = cmd_verbose.index('-w')
            cmd_verbose.pop(idx)  # remove -w
            cmd_verbose.pop(idx)  # remove %{http_code}
            cmd_verbose.extend(['-v', '-o', '/dev/null'])
            
            result_verbose = subprocess.run(
                cmd_verbose,
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            logger.error(
                "Curl upload failed %s: status=%s stderr=%s",
                filename, status_code, result_verbose.stderr[:1000] if result_verbose.stderr else 'none',
            )
            return False
            
        except subprocess.TimeoutExpired:
            logger.error("Curl upload timeout for %s after %s seconds", filename, max_time)
            return False
        except FileNotFoundError:
            logger.error("curl not found, falling back to requests")
            return self._upload_via_requests(local_path, filename, share_token)
        except Exception as e:
            logger.error("Curl upload error %s: %s", filename, e, exc_info=True)
            return False
    
    def _upload_via_requests(self, local_path: str, filename: str, share_token: str) -> bool:
        """Fallback upload using Python requests (if curl not available)."""
        # NC32+ format: token in URL path, not in basic auth
        upload_url = f"{self.base_url}/public.php/dav/files/{share_token}/{quote(filename, safe='')}"
        file_size = os.path.getsize(local_path)
        headers = {
            'Content-Type': 'application/octet-stream',
            'Content-Length': str(file_size),
            'Expect': '',
        }
        try:
            with open(local_path, 'rb') as f:
                r = requests.put(
                    upload_url,
                    data=f,
                    headers=headers,
                    timeout=3600,
                )
            if r.status_code in (200, 201, 204):
                return True
            logger.error("Requests upload failed %s: %s", filename, r.status_code)
            return False
        except Exception as e:
            logger.error("Requests upload error: %s", e)
            return False

    def get_webdav_url_for_path(self, file_path: str) -> str:
        """
        Get the correct WebDAV base URL for a given file path.
        Checks if path is in GroupFolders and returns appropriate base URL.
        
        Args:
            file_path: Relative path in Nextcloud
            
        Returns:
            WebDAV base URL (with trailing slash removed)
        """
        # Check if path starts with GroupFolders
        if 'GroupFolders' in file_path or file_path.startswith('GroupFolders/'):
            return self.groupfolders_url.rstrip('/')
        else:
            return self.webdav_url.rstrip('/')
    
    def list_root_folders(self) -> List[str]:
        """
        List folders in the root of WebDAV to help debug folder structure.
        
        Returns:
            List of folder names
        """
        return self.list_subfolders('')

    def _propfind_children(self, folder_url: str, folder_path: str) -> Optional[List[Dict]]:
        """
        Depth-1 PROPFIND of a folder.

        Returns:
            Direct children (files and folders, see _parse_propfind_response),
            or None if the folder does not exist or cannot be read.
        """
        try:
            response = requests.request(
                'PROPFIND',
                folder_url,
                auth=self._get_auth(),
                headers={'Depth': '1'},
                timeout=30
            )
        except Exception as e:
            logger.debug(f"Error listing {folder_url}: {e}")
            return None
        if response.status_code != 207:
            if response.status_code != 404:
                logger.warning(
                    f"Unexpected response for {folder_path or '/'}: {response.status_code}"
                )
            return None
        return self._parse_propfind_response(response.text, folder_path, include_dirs=True)

    def list_subfolders(self, path: str = '') -> List[str]:
        """Names of direct subfolders of path (Depth 1), '' = root."""
        folder_path = path.strip('/')
        folder_url = self.webdav_url.rstrip('/')
        if folder_path:
            folder_url += '/' + '/'.join(quote(part, safe='') for part in folder_path.split('/'))
        children = self._propfind_children(folder_url, folder_path) or []
        return [child['filename'] for child in children if child['is_dir']]

    def discover_channels(self) -> Dict[str, str]:
        """
        Find exchange folders in the configured search roots.

        Returns:
            {channel name: folder path}, e.g.
            {'OK Dessau': 'OK Dessau - Austausch',
             'h1 - Fernsehen aus Hannover': 'BVBM/h1 - Fernsehen aus Hannover - Austausch'}
            The channel name never contains the search root, so ExchangeItem.channel
            stays the plain channel name. A name found in two roots is taken
            from the first one.
        """
        pattern = self.config.exchange_folder_pattern
        if '{channel}' not in pattern or '/' in pattern.strip('/'):
            logger.warning(f"Cannot discover channels with exchange folder pattern '{pattern}'")
            return {}
        prefix, suffix = pattern.strip('/').split('{channel}', 1)

        found: Dict[str, str] = {}
        for root in self.config.get_channel_search_roots():
            for name in self.list_subfolders(root):
                if not (name.startswith(prefix) and name.endswith(suffix)):
                    continue
                channel = name[len(prefix):len(name) - len(suffix)].strip()
                if channel:
                    found.setdefault(channel, f'{root}/{name}'.strip('/'))
        return found

    @staticmethod
    def select_date_folders(names: List[str], days: Optional[int]) -> List[str]:
        """
        Keep folder names of the form YYYY_MM_DD, newest first.

        Args:
            names: Folder names
            days: Keep only folders of the last `days` days (1 = today only);
                  None keeps all of them.
        """
        from django.utils import timezone
        oldest = None
        if days is not None:
            oldest = timezone.localdate() - timedelta(days=max(days, 1) - 1)
        selected = []
        for name in names:
            if not re.fullmatch(r'\d{4}_\d{2}_\d{2}', name):
                continue
            try:
                folder_date = datetime.strptime(name, '%Y_%m_%d').date()
            except ValueError:
                continue
            if oldest is None or folder_date >= oldest:
                selected.append(name)
        return sorted(selected, reverse=True)

    def list_exchange_folder(
        self,
        channel: str,
        date_folders: Optional[List[str]] = None,
        folder_path: Optional[str] = None,
    ) -> List[Dict]:
        """
        List files in exchange folder for a channel.
        
        Args:
            channel: Channel name
            date_folders: Optional list of date folder names (e.g., ['2025_12_05', '2025_12_06'])
                         If None, scans the existing date folders of the last
                         sync_date_folders_days days.
                         If empty list, scans all existing date folders.
            folder_path: Exchange folder path (e.g. from discover_channels).
                         If None, it is built from exchange_folder_pattern.
            
        Returns:
            List of file metadata dictionaries with keys:
            - path: Full file path in Nextcloud
            - filename: Filename
            - size: File size in bytes
            - modified: Last modified datetime
            - is_dir: Whether it's a directory
        Files lying directly in the exchange folder (no date folder) are
        always included.
        """
        if folder_path is None:
            folder_path = self.config.exchange_folder_pattern.format(channel=channel)
        folder_path = folder_path.strip('/')
        logger.debug(f"Looking for exchange folder: '{folder_path}' for channel: '{channel}'")

        encoded_base_path = '/'.join(quote(part, safe='') for part in folder_path.split('/'))

        # Try multiple locations: user files, GroupFolders
        locations_to_try = [
            (self.webdav_url, "user files"),
            (self.groupfolders_url, "GroupFolders"),
        ]

        all_files = []
        scanned_folders: List[str] = []

        for base_url, location_type in locations_to_try:
            base_full_url = f"{base_url.rstrip('/')}/{encoded_base_path}"
            logger.debug(f"Trying {location_type}: {base_full_url}")

            # One Depth-1 listing tells which date folders exist, instead of
            # probing every possible date.
            children = self._propfind_children(base_full_url, folder_path)
            if children is None:
                logger.debug(f"Base folder not found in {location_type}: {folder_path}")
                continue

            all_files.extend(child for child in children if not child['is_dir'])
            existing = [child['filename'] for child in children if child['is_dir']]
            if date_folders is None:
                scanned_folders = self.select_date_folders(
                    existing, getattr(self.config, 'sync_date_folders_days', 2))
            elif date_folders == []:
                scanned_folders = self.select_date_folders(existing, None)
            else:
                scanned_folders = [name for name in date_folders if name in existing]

            for date_folder in scanned_folders:
                date_folder_url = f"{base_full_url}/{quote(date_folder, safe='')}"
                files = self._propfind_children(date_folder_url, f"{folder_path}/{date_folder}")
                if files is None:
                    continue
                all_files.extend(f for f in files if not f['is_dir'])

            # Base folder found in this location, no need to try others
            logger.info(f"Found {len(all_files)} files in {location_type} for channel {channel}")
            break
        
        if not all_files:
            logger.warning(
                f"No files found in exchange folder: {folder_path}. "
                f"Scanned date folders: {scanned_folders}"
            )
        
        return all_files
    
    def _parse_propfind_response(
        self, xml_content: str, base_path: str, include_dirs: bool = False,
    ) -> List[Dict]:
        """
        Parse PROPFIND XML response.
        
        Args:
            xml_content: XML response body
            base_path: Base path of the folder ('' = root)
            include_dirs: Also return direct subfolders (is_dir=True)
            
        Returns:
            List of file metadata dictionaries
        """
        files = []
        
        try:
            root = ET.fromstring(xml_content)
            
            # Find all response elements
            for response in root.findall(f'.//{self.DAV_NS}response'):
                href_elem = response.find(f'{self.DAV_NS}href')
                if href_elem is None:
                    continue
                
                href = href_elem.text
                if not href:
                    continue
                
                # Extract relative path
                # href format: /remote.php/dav/files/username/path/to/file
                if self.webdav_path in href:
                    relative_path = href.split(self.webdav_path, 1)[1]
                else:
                    # Fallback: try to extract from href
                    parts = href.strip('/').split('/')
                    if len(parts) > 3:
                        relative_path = '/'.join(parts[3:])
                    else:
                        continue
                
                # Decode URL-encoded path
                from urllib.parse import unquote
                relative_path = unquote(relative_path)
                
                # Skip the folder itself
                base_path_clean = base_path.rstrip('/')
                relative_path_clean = relative_path.rstrip('/')
                if relative_path_clean == base_path_clean:
                    continue
                
                # For date folder scanning:
                # - base_path is like "OK Magdeburg - Austausch/2026_01_07"
                # - relative_path for files should be like "OK Magdeburg - Austausch/2026_01_07/filename.ext"
                # We want files that are direct children of the date folder
                if base_path_clean and not relative_path_clean.startswith(base_path_clean + '/'):
                    # Not a file in this date folder, skip
                    continue
                
                # Extract filename (should be direct child of date folder)
                # relative_path: "OK Magdeburg - Austausch/2026_01_07/filename.ext"
                # We want just "filename.ext" part
                path_after_base = relative_path_clean[len(base_path_clean):].lstrip('/')
                # If there are more slashes, it's in a subfolder, skip for now
                if '/' in path_after_base:
                    continue
                
                # Get file properties
                propstat = response.find(f'{self.DAV_NS}propstat')
                if propstat is None:
                    continue
                
                prop = propstat.find(f'{self.DAV_NS}prop')
                if prop is None:
                    continue
                
                # Extract file metadata
                getcontentlength = prop.find(f'{self.DAV_NS}getcontentlength')
                size = int(getcontentlength.text) if getcontentlength is not None and getcontentlength.text else 0
                
                getlastmodified = prop.find(f'{self.DAV_NS}getlastmodified')
                modified = None
                if getlastmodified is not None and getcontentlength is not None:
                    try:
                        # Parse RFC 1123 date format (e.g., "Mon, 01 Jan 2024 12:00:00 GMT")
                        modified_str = getlastmodified.text.strip()
                        # Parse as naive datetime first
                        modified = datetime.strptime(
                            modified_str,
                            '%a, %d %b %Y %H:%M:%S %Z'
                        )
                        # Make it timezone-aware (RFC 1123 dates are typically GMT/UTC)
                        from django.utils import timezone as tz
                        if tz.is_naive(modified):
                            # Use UTC for GMT/UTC timezone strings
                            from datetime import timezone as dt_tz
                            modified = modified.replace(tzinfo=dt_tz.utc)
                    except (ValueError, AttributeError) as e:
                        logger.debug(f"Could not parse date '{getlastmodified.text}': {e}")
                        pass
                
                resourcetype = prop.find(f'{self.DAV_NS}resourcetype')
                is_dir = resourcetype.find(f'{self.DAV_NS}collection') is not None
                
                # Skip directories
                if is_dir and not include_dirs:
                    continue
                
                filename = relative_path_clean.split('/')[-1]
                
                files.append({
                    'path': relative_path_clean if is_dir else relative_path,
                    'filename': filename,
                    'size': size,
                    'modified': modified,
                    'is_dir': is_dir,
                })
        except ET.ParseError as e:
            logger.error(f"Error parsing PROPFIND response: {e}")
        except Exception as e:
            logger.error(f"Unexpected error parsing PROPFIND response: {e}", exc_info=True)
        
        return files
    
    def download_file(self, file_path: str, local_path: str, resume: bool = False) -> bool:
        """
        Download file from Nextcloud to local storage.
        Supports resume download if file partially exists.
        
        Args:
            file_path: Relative path in Nextcloud
            local_path: Local file path to save to
            resume: If True, resume download from existing file position
            
        Returns:
            True if successful, False otherwise
        """
        import os
        
        try:
            # Construct full WebDAV URL with proper encoding
            from urllib.parse import quote
            webdav_base = self.webdav_url.rstrip('/')
            file_path_clean = file_path.lstrip('/')
            # URL encode each path segment
            encoded_path = '/'.join(quote(part, safe='') for part in file_path_clean.split('/'))
            full_url = f"{webdav_base}/{encoded_path}"
            
            # Check if file exists and get its size for resume
            headers = {}
            initial_pos = 0
            if resume and os.path.exists(local_path):
                initial_pos = os.path.getsize(local_path)
                if initial_pos > 0:
                    headers['Range'] = f'bytes={initial_pos}-'
                    logger.info(f"Resuming download of {file_path} from byte {initial_pos}")
            
            # Download file
            response = requests.get(
                full_url,
                auth=self._get_auth(),
                headers=headers,
                timeout=300,  # 5 minutes for large files
                stream=True
            )
            
            # Handle successful responses (200 for new download, 206 for partial content)
            if response.status_code in (200, 206):
                # Open file in append mode if resuming, otherwise write mode
                mode = 'ab' if resume and initial_pos > 0 else 'wb'
                with open(local_path, mode) as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                if initial_pos > 0:
                    logger.info(
                        f"Resumed and completed download: {file_path} -> {local_path} "
                        f"(resumed from {initial_pos} bytes)"
                    )
                else:
                    logger.info(f"Downloaded file: {file_path} -> {local_path}")
                return True
            elif response.status_code == 416:  # Range Not Satisfiable
                # File already fully downloaded
                logger.info(f"File already fully downloaded: {local_path}")
                return True
            else:
                logger.error(
                    f"Failed to download file {file_path}: "
                    f"{response.status_code} - {response.text[:200]}"
                )
                return False
        except Exception as e:
            logger.error(f"Error downloading file {file_path}: {e}", exc_info=True)
            return False
    
    def get_file_metadata(self, file_path: str) -> Optional[Dict]:
        """
        Get file metadata via PROPFIND.
        
        Args:
            file_path: Relative path in Nextcloud
            
        Returns:
            Dictionary with file metadata or None if not found
        """
        try:
            from urllib.parse import quote
            webdav_base = self.get_webdav_url_for_path(file_path).rstrip('/')
            file_path_clean = file_path.lstrip('/')
            # URL encode each path segment
            encoded_path = '/'.join(quote(part, safe='') for part in file_path_clean.split('/'))
            full_url = f"{webdav_base}/{encoded_path}"
            
            response = requests.request(
                'PROPFIND',
                full_url,
                auth=self._get_auth(),
                headers={
                    'Depth': '0',
                },
                timeout=30
            )
            
            if response.status_code == 207:
                # Parse single file response
                files = self._parse_propfind_response(response.text, '')
                if files:
                    return files[0]
            elif response.status_code == 404:
                return None
            else:
                logger.warning(
                    f"Unexpected response getting metadata for {file_path}: "
                    f"{response.status_code}"
                )
                return None
        except Exception as e:
            logger.error(f"Error getting file metadata for {file_path}: {e}")
            return None
    
    def check_file_exists(self, file_path: str) -> bool:
        """
        Check if file exists in Nextcloud.

        Args:
            file_path: Relative path in Nextcloud

        Returns:
            True if file exists, False otherwise
        """
        metadata = self.get_file_metadata(file_path)
        return metadata is not None

    def ensure_directory(self, remote_path: str) -> bool:
        """
        Create remote directory and all parent directories (MKCOL).
        Skips 409 Conflict if collection already exists.

        Args:
            remote_path: Relative path in Nextcloud (e.g. GroupFolders/Upload/2026_01_31)

        Returns:
            True if directory exists or was created, False on error
        """
        from urllib.parse import quote
        path_clean = remote_path.strip('/')
        if not path_clean:
            return True
        parts = [p for p in path_clean.split('/') if p]
        base_url = self.get_webdav_url_for_path(path_clean).rstrip('/')
        for i in range(1, len(parts) + 1):
            segment_path = '/'.join(parts[:i])
            encoded_path = '/'.join(quote(p, safe='') for p in parts[:i])
            full_url = f"{base_url}/{encoded_path}"
            try:
                response = requests.request(
                    'MKCOL',
                    full_url,
                    auth=self._get_auth(),
                    timeout=30
                )
                if response.status_code in (201, 405):
                    # 201 Created or 405 Method Not Allowed (already exists)
                    continue
                if response.status_code == 409:
                    # Conflict - parent may not exist; try creating parents
                    continue
                logger.warning(
                    f"MKCOL {segment_path} returned {response.status_code}: {response.text[:200]}"
                )
                return False
            except Exception as e:
                logger.error(f"Error creating directory {segment_path}: {e}", exc_info=True)
                return False
        return True

    # Use Nextcloud chunked upload for files larger than this (avoids proxy/PHP body limits).
    CHUNKED_UPLOAD_THRESHOLD = 50 * 1024 * 1024  # 50 MB
    CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB (Nextcloud minimum per chunk; smaller may pass proxy limits)

    def _upload_file_chunked(self, local_path: str, remote_path: str, file_size: int) -> bool:
        """
        Upload file via Nextcloud chunked upload v2 (MKCOL, PUT chunks, MOVE).
        Implements proper Nextcloud chunked upload API via requests.

        Args:
            local_path: Local file path
            remote_path: Relative path in Nextcloud (e.g., OK Magdeburg/INBOX/file.mp4)
            file_size: File size in bytes

        Returns:
            True if successful, False otherwise
        """
        import requests

        # Build URLs
        uploads_base = f"{self.base_url}/remote.php/dav/uploads/{self.username}"
        files_base = f"{self.base_url}/remote.php/dav/files/{self.username}"
        destination_url = f"{files_base}/{remote_path.lstrip('/')}"

        upload_id = f"oktools-{uuid.uuid4()}"
        upload_dir_url = f"{uploads_base}/{upload_id}"

        # Use session for connection reuse
        session = requests.Session()
        session.auth = (self.username, self.password)

        try:
            # 1. MKCOL - create upload directory
            resp = session.request(
                'MKCOL',
                upload_dir_url,
                headers={'Destination': destination_url},
                timeout=30,
            )
            if resp.status_code not in (201,):
                logger.error("Chunked upload MKCOL failed: %s %s", resp.status_code, resp.text[:200])
                return False

            # 2. PUT chunks
            chunk_num = 0
            with open(local_path, 'rb') as f:
                while True:
                    chunk = f.read(self.CHUNK_SIZE)
                    if not chunk:
                        break

                    chunk_num += 1
                    if chunk_num > 10000:
                        logger.error("Chunked upload: too many chunks (>10000)")
                        return False

                    chunk_name = str(chunk_num)
                    chunk_url = f"{upload_dir_url}/{chunk_name}"

                    headers = {
                        'Destination': destination_url,
                        'OC-Total-Length': str(file_size),
                    }

                    resp = session.put(
                        chunk_url,
                        headers=headers,
                        data=chunk,
                        timeout=600,
                    )
                    if resp.status_code not in (200, 201, 204):
                        logger.error(
                            "Chunked upload PUT %s failed: %s (chunk %s/%s, size %s) - %s",
                            chunk_name, resp.status_code, chunk_num,
                            (file_size + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE,
                            len(chunk), resp.text[:200],
                        )
                        return False

                    logger.debug("Uploaded chunk %s (%s bytes)", chunk_name, len(chunk))

            # 3. MOVE upload directory to assemble
            assemble_url = f"{upload_dir_url}/.file"
            move_headers = {
                'Destination': destination_url,
                'OC-Total-Length': str(file_size),
                'Overwrite': 'T',
            }

            resp = session.request(
                'MOVE',
                assemble_url,
                headers=move_headers,
                timeout=120,
            )
            if resp.status_code not in (201, 204):
                logger.error("Chunked upload MOVE failed: %s %s", resp.status_code, resp.text[:200])
                return False

            logger.info(
                "Uploaded file (chunked v2): %s -> %s (%s chunks, %s bytes)",
                local_path, remote_path, chunk_num, file_size,
            )
            return True

        except Exception as e:
            logger.error("Chunked upload failed %s -> %s: %s", local_path, remote_path, e, exc_info=True)
            return False

        finally:
            # Cleanup upload directory on failure (optional, server cleans after 24h)
            session.close()

    CHUNK_UPLOAD_MAX_RETRIES = 5
    CHUNK_UPLOAD_STATE_DIR = '/tmp/oktools-uploads'

    def _get_state_file_path(self, local_path: str) -> str:
        """Get path to state file for tracking upload progress."""
        import hashlib
        file_hash = hashlib.sha256(local_path.encode()).hexdigest()[:16]
        return os.path.join(self.CHUNK_UPLOAD_STATE_DIR, f'{file_hash}.json')

    def _load_upload_state(self, local_path: str) -> Optional[Dict]:
        """Load upload state from file if exists and is valid."""
        state_file = self._get_state_file_path(local_path)
        if not os.path.exists(state_file):
            return None
        try:
            import json
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if not isinstance(state, dict):
                return None
            return state
        except Exception:
            return None

    def _save_upload_state(self, local_path: str, state: Dict) -> None:
        """Save upload state to file."""
        import json
        os.makedirs(self.CHUNK_UPLOAD_STATE_DIR, exist_ok=True)
        state_file = self._get_state_file_path(local_path)
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def _delete_upload_state(self, local_path: str) -> None:
        """Delete upload state file."""
        state_file = self._get_state_file_path(local_path)
        if os.path.exists(state_file):
            try:
                os.unlink(state_file)
            except OSError:
                pass

    def _list_uploaded_chunks(self, session: requests.Session, upload_dir_url: str) -> set:
        """List already uploaded chunks in the upload directory via PROPFIND."""
        import xml.etree.ElementTree as ET
        from urllib.parse import urlparse

        body = b'''<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:resourcetype/>
  </d:prop>
</d:propfind>'''

        headers = {
            'Depth': '1',
            'Content-Type': 'application/xml; charset=utf-8',
        }

        try:
            resp = session.request(
                'PROPFIND',
                upload_dir_url,
                headers=headers,
                data=body,
                timeout=30,
            )
            if resp.status_code not in (207,):
                return set()

            root = ET.fromstring(resp.text)
            ns = {'d': 'DAV:'}
            uploaded = set()
            base_path = urlparse(upload_dir_url).path.rstrip('/')

            for response in root.findall('d:response', ns):
                href_el = response.find('d:href', ns)
                if href_el is None or not href_el.text:
                    continue

                href_path = urlparse(href_el.text).path.rstrip('/')
                if href_path == base_path:
                    continue

                name = href_path.split('/')[-1]
                if name == '.file':
                    continue

                if name.isdigit():
                    uploaded.add(name)

            return uploaded
        except Exception:
            return set()

    def _normalize_uploaded_chunks(self, uploaded_chunks) -> set:
        """Normalize chunk names to plain numeric strings."""
        normalized = set()
        for chunk_name in uploaded_chunks or []:
            if chunk_name is None:
                continue
            chunk_name = str(chunk_name).strip()
            if chunk_name.isdigit():
                normalized.add(str(int(chunk_name)))
        return normalized

    def _put_chunk_with_retry(
        self,
        session: requests.Session,
        chunk_url: str,
        chunk_data: bytes,
        headers: Dict,
        chunk_num: int,
        total_chunks: int,
    ) -> bool:
        """Upload a single chunk with retry logic and exponential backoff."""
        import time

        del session

        for attempt in range(1, self.CHUNK_UPLOAD_MAX_RETRIES + 1):
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.chunk', delete=False) as temp_file:
                    temp_file.write(chunk_data)
                    temp_file.flush()
                    temp_path = temp_file.name

                file_size = len(chunk_data)
                max_time = max(600, int(file_size / (1024 * 1024) * 60))
                cmd = [
                    'curl',
                    '-X', 'PUT',
                    '-T', temp_path,
                    '-u', f'{self.username}:{self.password}',
                    '-H', f'Destination: {headers["Destination"]}',
                    '-H', f'OC-Total-Length: {headers["OC-Total-Length"]}',
                    '-H', 'Content-Type: application/octet-stream',
                    '-H', 'Expect:',
                    '--connect-timeout', '30',
                    '--max-time', str(max_time),
                    '-s',
                    '-w', '%{http_code}',
                    '-o', '/dev/null',
                    chunk_url,
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=max_time + 60,
                )

                status_code = result.stdout.strip()
                if status_code in ('200', '201', '204'):
                    logger.debug(
                        "Chunk %05d/%s uploaded successfully via curl (%s bytes)",
                        chunk_num, total_chunks, file_size,
                    )
                    return True

                logger.warning(
                    "Chunk %05d PUT attempt %s/%s failed: HTTP %s, stderr=%s",
                    chunk_num, attempt, self.CHUNK_UPLOAD_MAX_RETRIES,
                    status_code or 'unknown',
                    result.stderr[:500] if result.stderr else 'none',
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Chunk %05d PUT attempt %s/%s timed out",
                    chunk_num, attempt, self.CHUNK_UPLOAD_MAX_RETRIES,
                )
            except Exception as e:
                logger.warning(
                    "Chunk %05d PUT attempt %s/%s exception: %s",
                    chunk_num, attempt, self.CHUNK_UPLOAD_MAX_RETRIES, e,
                )
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass

            if attempt < self.CHUNK_UPLOAD_MAX_RETRIES:
                sleep_time = min(2 ** attempt, 30)
                logger.info(
                    "Retrying chunk %05d in %s seconds (attempt %s/%s)",
                    chunk_num, sleep_time, attempt + 1, self.CHUNK_UPLOAD_MAX_RETRIES,
                )
                time.sleep(sleep_time)

        return False

    def _upload_file_chunked_resumable(
        self,
        local_path: str,
        remote_path: str,
        file_size: int,
        progress_callback=None,
    ) -> bool:
        """
        Upload file via Nextcloud chunked upload v2 with resume support.

        Features:
        - State file tracks upload progress
        - PROPFIND checks already uploaded chunks
        - Resume from interruption (skip existing chunks)
        - Retry logic with exponential backoff per chunk

        Args:
            local_path: Local file path
            remote_path: Relative path in Nextcloud
            file_size: File size in bytes
            progress_callback: Optional callback(chunk_num, total_chunks, percent)

        Returns:
            True if successful, False otherwise
        """
        uploads_base = f"{self.base_url}/remote.php/dav/uploads/{self.username}"
        files_base = f"{self.base_url}/remote.php/dav/files/{self.username}"
        # URL-encode the remote path to handle spaces and special characters
        encoded_path = quote(remote_path.lstrip('/'), safe='/')
        destination_url = f"{files_base}/{encoded_path}"

        state = self._load_upload_state(local_path)
        if (
            state
            and state.get('remote_path') == remote_path
            and state.get('file_size') == file_size
            and state.get('chunk_size') == self.CHUNK_SIZE
        ):
            upload_id = state['upload_id']
            uploaded_chunks = self._normalize_uploaded_chunks(state.get('uploaded_chunks', []))
            logger.info(
                "Resuming chunked upload: %s -> %s (already have %s chunks)",
                local_path, remote_path, len(uploaded_chunks),
            )
        else:
            upload_id = f"oktools-{uuid.uuid4()}"
            uploaded_chunks = set()
            state = {
                'upload_id': upload_id,
                'remote_path': remote_path,
                'file_size': file_size,
                'chunk_size': self.CHUNK_SIZE,
                'uploaded_chunks': [],
            }
            self._save_upload_state(local_path, state)

        upload_dir_url = f"{uploads_base}/{upload_id}"
        session = requests.Session()
        session.auth = (self.username, self.password)

        try:
            resp = session.request(
                'MKCOL',
                upload_dir_url,
                headers={'Destination': destination_url},
                timeout=30,
            )
            if resp.status_code not in (201, 405):
                logger.error("Chunked upload MKCOL failed: %s %s", resp.status_code, resp.text[:200])
                return False

            server_uploaded = self._list_uploaded_chunks(session, upload_dir_url)
            if server_uploaded:
                uploaded_chunks = uploaded_chunks.union(server_uploaded)
                logger.info(
                    "Found %s existing chunks on server, resuming upload",
                    len(server_uploaded),
                )

            total_chunks = (file_size + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
            chunks_uploaded = 0
            import time
            upload_start_time = time.time()
            bytes_uploaded = 0

            with open(local_path, 'rb') as f:
                chunk_num = 0
                while True:
                    chunk = f.read(self.CHUNK_SIZE)
                    if not chunk:
                        break

                    chunk_num += 1
                    if chunk_num > 10000:
                        logger.error("Chunked upload: too many chunks (>10000)")
                        return False

                    chunk_name = str(chunk_num)

                    if chunk_name in uploaded_chunks:
                        logger.debug("Skipping chunk %s (already uploaded)", chunk_name)
                        continue

                    chunk_url = f"{upload_dir_url}/{quote(chunk_name, safe='')}"
                    headers = {
                        'Destination': destination_url,
                        'OC-Total-Length': str(file_size),
                    }

                    if not self._put_chunk_with_retry(
                        session, chunk_url, chunk, headers,
                        chunk_num, total_chunks,
                    ):
                        logger.error(
                            "Failed to upload chunk %s after %s attempts",
                            chunk_name, self.CHUNK_UPLOAD_MAX_RETRIES,
                        )
                        return False

                    uploaded_chunks.add(chunk_name)
                    state['uploaded_chunks'] = sorted(uploaded_chunks)
                    self._save_upload_state(local_path, state)

                    chunks_uploaded += 1
                    bytes_uploaded += len(chunk)
                    progress = (chunk_num / total_chunks) * 100

                    # Calculate upload speed
                    elapsed = time.time() - upload_start_time
                    speed_mbps = (bytes_uploaded / elapsed) / (1024 * 1024) if elapsed > 0 else 0

                    logger.info(
                        "Uploaded chunk %s/%s (%.1f%%): %s - Speed: %.2f MB/s",
                        chunk_num, total_chunks, progress, chunk_name, speed_mbps,
                    )

                    # Call progress callback if provided
                    if progress_callback:
                        progress_callback(chunk_num, total_chunks, progress, speed_mbps)

            assemble_url = f"{upload_dir_url}/.file"
            move_headers = {
                'Destination': destination_url,
                'OC-Total-Length': str(file_size),
                'Overwrite': 'T',
            }

            logger.info(
                "Assembling file: MOVE %s -> %s (%s chunks, %s bytes)",
                assemble_url, destination_url, chunk_num, file_size,
            )

            # Ensure parent directory exists before MOVE
            parent_dir = '/'.join(remote_path.lstrip('/').split('/')[:-1])
            if parent_dir:
                self.ensure_directory(parent_dir)

            # Verify upload directory still exists
            check_resp = session.request('PROPFIND', upload_dir_url, timeout=30)
            if check_resp.status_code != 207:
                logger.error(
                    "Upload directory no longer exists: %s (status: %s)",
                    upload_dir_url, check_resp.status_code,
                )
                return False

            # Use curl for MOVE request to avoid issues with requests library
            import subprocess
            cmd = [
                'curl',
                '-X', 'MOVE',
                '-u', f'{self.username}:{self.password}',
                '-H', f'Destination: {destination_url}',
                '-H', f'OC-Total-Length: {file_size}',
                '-H', 'Overwrite: T',
                '-H', 'Content-Length: 0',
                '--connect-timeout', '30',
                '--max-time', '300',
                '-s',
                '-w', '%{http_code}',
                '-o', '/dev/null',
                assemble_url,
            ]

            move_retries = 3
            for attempt in range(1, move_retries + 1):
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=310,
                )

                status_code = result.stdout.strip()
                if status_code in ('201', '204'):
                    break

                logger.warning(
                    "Chunked upload MOVE attempt %s/%s failed: HTTP %s, stderr=%s",
                    attempt, move_retries, status_code or 'unknown',
                    result.stderr[:500] if result.stderr else 'none',
                )
                if status_code not in ('404', '423', '504') or attempt == move_retries:
                    debug_cmd = cmd.copy()
                    debug_cmd.remove('-s')
                    debug_cmd.remove('-o')
                    debug_cmd.remove('/dev/null')
                    debug_idx = debug_cmd.index('-w')
                    debug_cmd.pop(debug_idx)
                    debug_cmd.pop(debug_idx)
                    debug_cmd.extend(['-v', '--dump-header', '-'])

                    debug_result = subprocess.run(
                        debug_cmd,
                        capture_output=True,
                        text=True,
                        timeout=310,
                    )

                    logger.error(
                        "Chunked upload MOVE failed: HTTP %s, stderr=%s, stdout=%s, debug_stderr=%s, debug_stdout=%s, assemble_url=%s, destination=%s",
                        status_code,
                        result.stderr[:500] if result.stderr else 'none',
                        result.stdout[:500] if result.stdout else 'none',
                        debug_result.stderr[:4000] if debug_result.stderr else 'none',
                        debug_result.stdout[:4000] if debug_result.stdout else 'none',
                        assemble_url,
                        destination_url,
                    )
                    return False

                time.sleep(attempt)

            logger.info(
                "Uploaded file (chunked v2 resumable): %s -> %s "
                "(%s chunks, %s bytes)",
                local_path, remote_path, chunk_num, file_size,
            )

            self._delete_upload_state(local_path)

            try:
                session.delete(upload_dir_url, timeout=30)
            except Exception:
                pass

            return True

        except Exception as e:
            logger.error(
                "Chunked resumable upload failed %s -> %s: %s",
                local_path, remote_path, e, exc_info=True,
            )
            return False

        finally:
            session.close()

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """
        Upload a local file to Nextcloud via public share WebDAV.

        Uses the same mechanism as UI video upload (public.php/webdav with share token).
        This bypasses proxy/PHP body limits that block direct WebDAV PUT to remote.php/dav.

        Args:
            local_path: Local file path to read from
            remote_path: Relative path in Nextcloud (e.g. OKMQ/INBOX/file.mp4)

        Returns:
            True if successful, False otherwise
        """
        if not os.path.isfile(local_path):
            logger.error("Upload failed: local file not found: %s", local_path)
            return False
        path_clean = remote_path.strip('/')
        parts = [p for p in path_clean.split('/') if p]
        if not parts:
            logger.error("Upload failed: remote_path is empty")
            return False
        # Ensure parent directory exists
        parent_path = '/'.join(parts[:-1])
        if parent_path and not self.ensure_directory(parent_path):
            return False
        filename = parts[-1]
        # Create temporary upload share on parent folder
        share_data = self._create_upload_share(parent_path, expire_hours=2)
        if not share_data:
            logger.error("Upload failed: could not create upload share for %s", parent_path)
            return False
        share_id = share_data['share_id']
        token = share_data['token']
        try:
            success = self._upload_via_public_share(local_path, filename, token)
            return success
        finally:
            # Always clean up the share
            self._delete_share(share_id)

    def upload_file_direct(self, local_path: str, remote_path: str, progress_callback=None) -> bool:
        """
        Upload a local file to Nextcloud via direct WebDAV.

        For files > 50MB, uses chunked upload v2 with resume support.
        For smaller files, uses simple curl-based PUT.

        Args:
            local_path: Local file path to read from
            remote_path: Relative path in Nextcloud (e.g. OKMQ/INBOX/file.mp4)
            progress_callback: Optional callback(chunk_num, total_chunks, percent) for progress

        Returns:
            True if successful, False otherwise
        """
        if not os.path.isfile(local_path):
            logger.error("Upload failed: local file not found: %s", local_path)
            return False

        file_size = os.path.getsize(local_path)

        if file_size > self.CHUNKED_UPLOAD_THRESHOLD:
            return self._upload_file_chunked_resumable(local_path, remote_path, file_size, progress_callback)
        else:
            return self._upload_file_simple(local_path, remote_path)

    def _upload_file_simple(self, local_path: str, remote_path: str) -> bool:
        """
        Upload a small file via direct WebDAV PUT (no chunking).
        """
        path_clean = remote_path.strip('/')
        parts = [p for p in path_clean.split('/') if p]
        if not parts:
            logger.error("Upload failed: remote_path is empty")
            return False

        # Ensure parent directory exists
        parent_path = '/'.join(parts[:-1])
        if parent_path and not self.ensure_directory(parent_path):
            return False

        # Build direct WebDAV URL
        base_url = self.get_webdav_url_for_path(path_clean).rstrip('/')
        encoded_path = '/'.join(quote(p, safe='') for p in parts)
        url = f"{base_url}/{encoded_path}"

        filename = parts[-1]
        file_size = os.path.getsize(local_path)

        logger.info("Uploading file direct: %s (%s bytes) -> %s", local_path, file_size, url)

        try:
            # Use curl for reliable large file upload
            import subprocess
            max_time = max(600, int(file_size / (1024 * 1024) * 60))  # ~1 min per MB, min 10 min

            cmd = [
                'curl', '-X', 'PUT',
                '-T', local_path,
                '-u', f'{self.username}:{self.password}',
                '-H', 'Content-Type: application/octet-stream',
                '--connect-timeout', '30',
                '--max-time', str(max_time),
                '-s', '-w', '%{http_code}',
                '-o', '/dev/null',
                url,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max_time + 60,
            )

            status_code = result.stdout.strip()

            if status_code in ('200', '201', '204'):
                logger.info("Uploaded file (direct curl): %s -> %s", local_path, remote_path)
                return True
            else:
                logger.error("Upload failed: curl status %s, stderr: %s", status_code, result.stderr[:500])
                return False
        except subprocess.TimeoutExpired:
            logger.error("Upload timeout for %s after %s seconds", local_path, max_time)
            return False
        except Exception as e:
            logger.error("Upload failed: %s", e, exc_info=True)
            return False

    @staticmethod
    def parse_contribution_id(filename: str) -> Optional[int]:
        """
        Parse contribution ID from filename.
        
        Filenames from OK-Tools start with numeric ID: "{ID}_timestamp_filename.ext"
        
        Args:
            filename: Filename to parse
            
        Returns:
            Contribution ID as integer, or None if not found
        """
        # Pattern: number at the start of filename, followed by underscore
        match = re.match(r'^(\d+)_', filename)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        return None
    
    def parse_meta_json(self, file_path: str) -> Optional[Dict]:
        """
        Download and parse .meta.json file.
        
        Args:
            file_path: Path to .meta.json file in Nextcloud
            
        Returns:
            Dictionary with parsed metadata or None if file not found/invalid
            
        Expected JSON structure:
        {
            "name": "Title",
            "description": "Description text",
            "senderResponsible": "Author name",
            "category": 107,
            "targetChannel": "@ok_magdeburg@lokalmedial.de",
            "originallyPublishedAt": "2025-09-23T16:00:00Z",
            "thumbnail": "filename.jpg",
            "allowExchange": true,
            "saveToMediathek": true
        }
        """
        import json
        import tempfile
        import os
        from django.utils.dateparse import parse_duration
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
                temp_path = f.name
            
            if not self.download_file(file_path, temp_path):
                logger.warning(f"Failed to download meta.json: {file_path}")
                return None
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            os.unlink(temp_path)
            
            # Validate and extract relevant fields
            if not isinstance(data, dict):
                logger.error(f"Invalid meta.json format: expected dict, got {type(data)}")
                return None

            data = normalize_exchange_metadata(data)
            
            # Extract and clean fields
            # Handle both formats:
            # 1. category can be string or number
            # 2. videoNumber can be used instead of category as number
            category_value = data.get('category')
            video_number = data.get('videoNumber')
            
            # If category is a string, use videoNumber as category_id
            # If category is a number, use it as category_id
            category_id = None
            if isinstance(category_value, int):
                category_id = category_value
            elif video_number:
                category_id = video_number
            elif isinstance(category_value, str):
                # Category is a string (like "Kurzfilm"), keep it for reference
                pass
            
            duration_val = None
            duration_str = data.get('duration')
            if duration_str:
                duration_val = parse_duration(str(duration_str))
                
            result = {
                'title': _clean_str(data.get('name')),
                'description': _clean_str(data.get('description')),
                'sender_responsible': _clean_str(data.get('senderResponsible')),
                'category_id': category_id,
                'category_name': str(category_value) if isinstance(category_value, str) else None,
                'target_channel': _clean_str(data.get('targetChannel')),
                'originally_published_at': data.get('originallyPublishedAt'),
                'thumbnail': _clean_str(data.get('thumbnail')),
                'allow_exchange': _coerce_bool(data.get('allowExchange')),
                'allow_exchange_other_states': _coerce_bool(data.get('allowExchangeOtherStates')),
                'save_to_mediathek': _coerce_bool(data.get('saveToMediathek')),
                'tags': data.get('tags', []),  # Array of tags
                'youth_protection_necessary': _coerce_bool(data.get('youthProtectionNecessary')),
                'youth_protection_category': _clean_str(data.get('youthProtectionCategory')),
                'bundesland': _clean_str(data.get('bundesland')),
                'bundesland_code': _clean_str(data.get('bundesland_code')).upper()[:2],
                'video_number': video_number,  # Store videoNumber if present
                'duration': duration_val,
            }
            
            logger.debug(
                f"Parsed meta.json from {file_path}: "
                f"title='{result['title']}', "
                f"author='{result['sender_responsible']}', "
                f"category_id={category_id}, "
                f"video_number={video_number}"
            )
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in meta.json {file_path}: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error parsing meta.json {file_path}: {e}", exc_info=True)
            return None
    
    @staticmethod
    def detect_file_type(filename: str) -> str:
        """
        Detect file type from extension.
        
        Args:
            filename: Filename
            
        Returns:
            'video', 'pdf', 'json', 'image', or 'unknown'
        """
        filename_lower = filename.lower()
        video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.mxf', '.mpeg', '.mpg']
        pdf_extensions = ['.pdf']
        json_extensions = ['.json']
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif']
        
        for ext in video_extensions:
            if filename_lower.endswith(ext):
                return 'video'
        
        for ext in pdf_extensions:
            if filename_lower.endswith(ext):
                return 'pdf'
        
        for ext in json_extensions:
            if filename_lower.endswith(ext):
                return 'json'
        
        for ext in image_extensions:
            if filename_lower.endswith(ext):
                return 'image'
        
        return 'unknown'
