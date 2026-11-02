"""Service for importing exchange items into OK-Tools."""

from ..models import ExchangeChannelAuth
from ..models import ExchangeConfig
from ..models import ExchangeImport
from ..models import ExchangeItem
from ..models import ImportedLicenseMapping
from .metadata_normalizer import normalize_exchange_metadata
from .nextcloud_exchange_service import NextcloudExchangeService
from datetime import timedelta
from difflib import SequenceMatcher
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from licenses.admin import create_profile_by_name
from licenses.admin import get_category_by_id
from licenses.admin import get_category_by_name
from licenses.admin import get_profile_by_name
from licenses.models import Category
from licenses.models import License
from media_files.models import StorageLocation
from media_files.models import VideoFile
from pathlib import Path
from registration.models import MediaAuthority
from registration.models import Profile
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import hashlib
import logging
import os
import re
import requests
import unicodedata


logger = logging.getLogger('django')


def similarity_ratio(str1, str2):
    """Calculate similarity ratio between two strings (0.0 to 1.0)."""
    if not str1 or not str2:
        return 0.0
    return SequenceMatcher(None, str1.lower().strip(), str2.lower().strip()).ratio()


def find_potential_duplicates(title, profile, threshold=0.8):
    """
    Find potential duplicate licenses by title and profile.
    
    Args:
        title: License title to check
        profile: Profile object to check
        threshold: Similarity threshold (default 0.8 = 80%)
    
    Returns:
        QuerySet of potential duplicate licenses
    """
    if not title or not profile:
        return License.objects.none()
    
    # Get all licenses for this profile
    profile_licenses = License.objects.filter(profile=profile)
    
    # Find licenses with similar titles
    potential_duplicates = []
    for license_obj in profile_licenses:
        similarity = similarity_ratio(title, license_obj.title)
        if similarity >= threshold:
            potential_duplicates.append(license_obj.id)
    
    return License.objects.filter(id__in=potential_duplicates)


def get_media_authority_by_channel(channel):
    """
    Get MediaAuthority by channel name from ExchangeItem.
    
    Tries to match channel (e.g., "ok_magdeburg", "OK Magdeburg") with MediaAuthority's 
    target_channel (e.g., "@ok_magdeburg@lokalmedial.de") or name.
    
    Args:
        channel: Channel name from ExchangeItem (e.g., "ok_magdeburg", "OK Magdeburg")
    
    Returns:
        MediaAuthority instance or None if not found
    """
    if not channel:
        return None
    
    # Normalize channel name: remove leading/trailing spaces, convert to lowercase,
    # replace spaces and hyphens with underscores for better matching
    channel_normalized = channel.strip().lower().replace(' ', '_').replace('-', '_')
    
    # Try to find MediaAuthority by target_channel containing the channel name
    # Example: channel="ok_magdeburg" should match target_channel="@ok_magdeburg@lokalmedial.de"
    # Also try with original channel (with spaces/hyphens) for flexibility
    channel_variants = [
        channel_normalized,  # "ok_magdeburg"
        channel.strip().lower(),  # "ok magdeburg" (original with spaces)
        channel.strip().lower().replace(' ', '').replace('-', ''),  # "okmagdeburg"
    ]
    
    for variant in channel_variants:
        media_authority = MediaAuthority.objects.filter(
            target_channel__icontains=variant
        ).first()
        
        if media_authority:
            logger.info(f"Found MediaAuthority '{media_authority.name}' by target_channel for channel '{channel}' (variant: '{variant}')")
            return media_authority
    
    # Try to find by name (case-insensitive, exact match)
    media_authority = MediaAuthority.objects.filter(
        name__iexact=channel.strip()
    ).first()
    
    if media_authority:
        logger.info(f"Found MediaAuthority '{media_authority.name}' by exact name match for channel '{channel}'")
        return media_authority
    
    # Try partial match on name (normalized)
    media_authority = MediaAuthority.objects.filter(
        name__icontains=channel_normalized
    ).first()
    
    if media_authority:
        logger.info(f"Found MediaAuthority '{media_authority.name}' by partial name match for channel '{channel}'")
        return media_authority
    
    logger.warning(f"Could not find MediaAuthority for channel '{channel}', will use default")
    return None


class ImportService:
    """Handles import of exchange items into OK-Tools."""
    
    def __init__(self, exchange_item: ExchangeItem, user):
        """
        Initialize import service.
        
        Args:
            exchange_item: ExchangeItem to import
            user: User performing the import
        """
        self.exchange_item = exchange_item
        self.user = user
        self.config = ExchangeConfig.get_config()
        self.service = NextcloudExchangeService(self.config)

    @staticmethod
    def _parse_duration(value: Any):
        """Parse remote duration formats to datetime.timedelta."""
        if value in (None, ''):
            return None

        if isinstance(value, timedelta):
            return value

        if isinstance(value, (int, float)):
            return timedelta(seconds=float(value))

        if isinstance(value, str):
            try:
                # Accept HH:MM:SS[.ffffff]
                chunks = value.split(':')
                if len(chunks) == 3:
                    hours = int(chunks[0])
                    minutes = int(chunks[1])
                    seconds = float(chunks[2])
                    return timedelta(hours=hours, minutes=minutes, seconds=seconds)
            except (TypeError, ValueError):
                return None

        return None

    @staticmethod
    def _parse_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
        """Parse bool-like values from API payloads."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {'1', 'true', 'yes', 'y', 'on'}:
                return True
            if normalized in {'0', 'false', 'no', 'n', 'off'}:
                return False
        return default

    def _resolve_profile_from_remote_metadata(self, fallback_profile: Profile, remote_metadata: Dict[str, Any]) -> Profile:
        """Resolve profile from remote metadata, fallback to detected profile."""
        profile_name = (
            remote_metadata.get('profile')
            or remote_metadata.get('senderResponsible')
            or remote_metadata.get('sender_responsible')
        )
        if not profile_name:
            return fallback_profile

        profile_name = str(profile_name).strip()
        if not profile_name:
            return fallback_profile

        profile = get_profile_by_name(profile_name)
        if profile:
            return profile

        media_authority = get_media_authority_by_channel(self.exchange_item.channel)
        profile = create_profile_by_name(profile_name, media_authority=media_authority)
        return profile or fallback_profile

    def _fetch_remote_metadata(
        self,
        channel_auth: ExchangeChannelAuth,
        remote_license_number: int,
    ) -> Dict[str, Any]:
        """Fetch authoritative metadata from remote OK-Tools API."""
        endpoint = channel_auth.metadata_endpoint_for_license(remote_license_number)
        headers = {
            'Authorization': f'Token {channel_auth.metadata_api_token}',
            'Accept': 'application/json',
        }

        try:
            response = requests.get(
                endpoint,
                headers=headers,
                timeout=channel_auth.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            channel_auth.last_error = str(exc)
            channel_auth.save(update_fields=['last_error', 'updated_at'])
            raise Exception(
                f"Remote metadata API request failed for channel '{channel_auth.channel_name}', "
                f"license {remote_license_number}: {exc}"
            )

        if not isinstance(payload, dict):
            raise Exception(
                f"Remote metadata API returned non-object payload for channel "
                f"'{channel_auth.channel_name}', license {remote_license_number}."
            )

        channel_auth.last_error = ''
        channel_auth.last_success_at = timezone.now()
        channel_auth.save(update_fields=['last_error', 'last_success_at', 'updated_at'])
        return normalize_exchange_metadata(payload)

    def _resolve_license_for_remote_channel(
        self,
        profile: Profile,
        remote_metadata: Dict[str, Any],
    ) -> License:
        """Resolve local license by stable remote identity for API-capable channels."""
        contribution_id = self.exchange_item.contribution_id
        if contribution_id is None:
            raise Exception('Remote channel resolution requires contribution_id.')

        source_channel = ExchangeChannelAuth.normalize_channel_name(self.exchange_item.channel)
        mapping = ImportedLicenseMapping.objects.select_related('local_license').filter(
            source_channel=source_channel,
            remote_license_number=contribution_id,
        ).first()

        if mapping:
            logger.info(
                f"Using mapped local license {mapping.local_license.number} "
                f"for remote {source_channel}:{contribution_id}"
            )
            return mapping.local_license

        resolved_profile = self._resolve_profile_from_remote_metadata(profile, remote_metadata)
        license_obj = self._get_or_create_license(resolved_profile, remote_metadata=remote_metadata)
        ImportedLicenseMapping.objects.create(
            source_channel=source_channel,
            remote_license_number=contribution_id,
            local_license=license_obj,
        )
        return license_obj
    
    def import_item(self, check_duplicates: bool = True) -> Tuple[ExchangeImport, Optional[List[License]]]:
        """
        Main import method - idempotent.
        
        Process:
        1. Check for duplicates (optional)
        2. Create License (without files)
        3. Return import record and duplicate list (if any)
        4. Files will be downloaded via Celery task
        
        Args:
            check_duplicates: Whether to check for potential duplicates
            
        Returns:
            Tuple of (ExchangeImport record, list of potential duplicate licenses)
            
        Raises:
            Exception: If import fails
        """
        # Check if already imported or in progress
        existing_import = ExchangeImport.objects.filter(
            exchange_item=self.exchange_item,
            status__in=['completed', 'pending_download', 'downloading', 'processing']
        ).first()
        
        if existing_import:
            logger.info(f"Item {self.exchange_item.id} already imported or in progress (status: {existing_import.status})")
            return existing_import, None
        
        # Check if exchange item already has a linked license
        if self.exchange_item.imported_license:
            logger.info(f"Item {self.exchange_item.id} already has license {self.exchange_item.imported_license.number}")
            # Create import record pointing to existing license
            import_record = ExchangeImport.objects.create(
                exchange_item=self.exchange_item,
                imported_by=self.user,
                status='pending_download',
                license=self.exchange_item.imported_license
            )
            # Enqueue Celery task to download files (if not already downloaded)
            from ..tasks import download_exchange_files_task
            download_exchange_files_task.delay(import_record.id)
            return import_record, None
        
        # Create import record
        import_record = ExchangeImport.objects.create(
            exchange_item=self.exchange_item,
            imported_by=self.user,
            status='pending'
        )
        
        try:
            import_record.status = 'processing'
            import_record.save()
            
            # Get or create profile for duplicate checking
            profile = self._get_or_create_profile()

            channel_auth = ExchangeChannelAuth.get_for_channel(self.exchange_item.channel)
            uses_remote_api = bool(
                channel_auth
                and channel_auth.supports_oktools_api
                and self.exchange_item.contribution_id
            )
            remote_metadata = {}
            if uses_remote_api:
                try:
                    remote_metadata = self._fetch_remote_metadata(
                        channel_auth,
                        int(self.exchange_item.contribution_id),
                    )
                    remote_metadata = normalize_exchange_metadata(remote_metadata)
                except Exception:
                    logger.warning(
                        "Remote metadata is unavailable for exchange item %s; "
                        "falling back to the synchronized meta.json data.",
                        self.exchange_item.id,
                        exc_info=True,
                    )
            
            # Check for potential duplicates before creating license
            potential_duplicates = None
            exact_match_license = None
            
            if (
                check_duplicates
                and self.exchange_item.title
                and profile
                and not self.exchange_item.contribution_id
            ):
                potential_duplicates = find_potential_duplicates(
                    self.exchange_item.title,
                    profile,
                    threshold=0.8
                )
                if potential_duplicates.exists():
                    logger.warning(
                        f"Found {potential_duplicates.count()} potential duplicates "
                        f"for exchange item {self.exchange_item.id}"
                    )
                    
                    # Check for exact match (100% similarity)
                    for dup_license in potential_duplicates:
                        similarity = similarity_ratio(
                            self.exchange_item.title or '',
                            dup_license.title or ''
                        )
                        if similarity >= 0.99:  # 99% or more = exact match
                            exact_match_license = dup_license
                            logger.info(
                                f"Found exact match (similarity: {similarity*100:.1f}%) "
                                f"for license {dup_license.number}, using existing license"
                            )
                            break
            
            # Create or get License (without downloading files yet)
            if exact_match_license:
                # Use existing license if exact match found
                license = exact_match_license
                logger.info(
                    f"Using existing license {license.number} "
                    f"instead of creating new one for exchange item {self.exchange_item.id}"
                )
            elif self.exchange_item.contribution_id:
                if uses_remote_api:
                    license = self._resolve_license_for_remote_channel(profile, remote_metadata)
                else:
                    license = self._get_or_create_license(profile)
            else:
                license = self._create_legacy_license(profile)
            
            # Update import record with license
            import_record.license = license
            import_record.status = 'pending_download'  # Will be completed after Celery task
            import_record.save()
            
            # Update exchange item
            self.exchange_item.import_status = 'imported'
            self.exchange_item.imported_at = timezone.now()
            self.exchange_item.imported_license = license
            self.exchange_item.save()
            
            # Enqueue Celery task to download files
            from ..tasks import download_exchange_files_task
            download_exchange_files_task.delay(import_record.id)
            
            logger.info(
                f"License {license.id} created for exchange item {self.exchange_item.id}, "
                f"download task enqueued"
            )
            
            # Return duplicates as list for API response
            duplicates_list = list(potential_duplicates) if potential_duplicates and potential_duplicates.exists() else None
            
            return import_record, duplicates_list
            
        except Exception as e:
            import_record.status = 'failed'
            import_record.error_message = str(e)
            import_record.save()
            
            self.exchange_item.import_status = 'failed'
            self.exchange_item.save()
            
            logger.error(
                f"Import failed for exchange item {self.exchange_item.id}: {e}",
                exc_info=True
            )
            raise
    
    def _get_or_create_profile(self) -> Profile:
        """
        Get or create profile from sendeverantwortung.
        
        Determines MediaAuthority based on exchange item's channel to ensure
        correct affiliation with Offene Kanäle/Bürgermedien.
        
        Returns:
            Profile instance
        """
        # Determine MediaAuthority based on channel
        media_authority = get_media_authority_by_channel(self.exchange_item.channel)
        
        profile = None
        if self.exchange_item.sendeverantwortung:
            profile = get_profile_by_name(self.exchange_item.sendeverantwortung)
            if not profile:
                # Create new profile if not found, with determined MediaAuthority
                profile = create_profile_by_name(
                    self.exchange_item.sendeverantwortung,
                    media_authority=media_authority
                )
        
        # Fallback: use user's profile or first available profile
        if not profile:
            try:
                # Try to get profile from current user
                profile = Profile.objects.get(okuser=self.user)
            except Profile.DoesNotExist:
                # Use first available profile as last resort
                profile = Profile.objects.first()
                if not profile:
                    raise Exception("No profile found. Please create at least one profile.")
        
        return profile
    
    def _download_files(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Download video and PDF files from Nextcloud.
        
        Files are saved with license number prefix: {number}_{normalized_filename}
        Filename normalization:
        - Spaces are replaced with underscores
        - German umlauts are normalized: ü->ue, ä->ae, ö->oe, ß->ss
        - Other non-ASCII characters are normalized using Unicode decomposition
        - Invalid filesystem characters are removed or replaced
        Supports resume download if file partially exists.
        
        Returns:
            Tuple of (video_path, pdf_path) local file paths
        """
        download_dir = self._get_download_directory()
        download_dir.mkdir(parents=True, exist_ok=True)
        
        # Get license number for filename prefix
        license_number = None
        if hasattr(self, 'license') and self.license:
            license_number = self.license.number
        elif self.exchange_item.imported_license:
            license_number = self.exchange_item.imported_license.number
        elif self.exchange_item.contribution_id:
            license_number = self.exchange_item.contribution_id
        
        video_path = None
        pdf_path = None
        
        def format_filename(original_filename: str) -> str:
            """
            Format filename with license number prefix, normalize German characters,
            and sanitize for filesystem compatibility.
            
            Rules:
            - Replace spaces with underscores
            - Normalize German umlauts: ü->ue, ä->ae, ö->oe, ß->ss
            - Normalize other non-ASCII characters using Unicode decomposition
            - Remove or replace invalid filesystem characters
            """
            # Normalize German umlauts according to German rules
            german_replacements = {
                'ü': 'ue',
                'Ü': 'Ue',
                'ä': 'ae',
                'Ä': 'Ae',
                'ö': 'oe',
                'Ö': 'Oe',
                'ß': 'ss',
            }
            
            # Apply German character replacements
            safe_name = original_filename
            for char, replacement in german_replacements.items():
                safe_name = safe_name.replace(char, replacement)
            
            # Normalize Unicode characters (decompose and remove combining marks)
            # This handles accented characters from other languages
            safe_name = unicodedata.normalize('NFD', safe_name)
            # Remove combining diacritical marks (accents)
            safe_name = ''.join(
                char for char in safe_name
                if unicodedata.category(char) != 'Mn'
            )
            
            # Replace spaces with underscores
            safe_name = safe_name.replace(' ', '_')
            
            # Remove or replace invalid filesystem characters
            # Keep: letters, digits, underscore, dash, dot
            # Remove: other special characters that might cause issues
            safe_name = re.sub(r'[^\w\-.]', '_', safe_name)
            
            # Remove multiple consecutive underscores
            safe_name = re.sub(r'_+', '_', safe_name)
            
            # Remove leading/trailing underscores and dots
            safe_name = safe_name.strip('_.')
            
            # Add license number prefix if available
            if license_number:
                # Extract extension
                name_parts = safe_name.rsplit('.', 1)
                if len(name_parts) == 2:
                    base_name, extension = name_parts
                    return f"{license_number}_{base_name}.{extension}"
                else:
                    return f"{license_number}_{safe_name}"
            return safe_name
        
        # Download video file (main file)
        video_file_path = self.exchange_item.file_path
        original_video_filename = self.exchange_item.filename
        formatted_video_filename = format_filename(original_video_filename)
        local_video_path = download_dir / formatted_video_filename
        
        # Check if video already exists and has correct size
        if local_video_path.exists():
            local_size = local_video_path.stat().st_size
            remote_size = self.exchange_item.file_size
            if remote_size and local_size >= remote_size:
                video_path = str(local_video_path)
                logger.info(f"Video already exists: {video_path} (size: {local_size})")
            else:
                # File exists but incomplete, resume download
                if self.service.download_file(video_file_path, str(local_video_path), resume=True):
                    video_path = str(local_video_path)
                    logger.info(f"Resumed video download: {video_file_path} -> {video_path}")
                else:
                    raise Exception(f"Failed to resume video file: {video_file_path}")
        else:
            if self.service.download_file(video_file_path, str(local_video_path), resume=True):
                video_path = str(local_video_path)
                logger.info(f"Downloaded video: {video_file_path} -> {video_path}")
            else:
                raise Exception(f"Failed to download video file: {video_file_path}")
        
        # Download PDF file if it's part of the package
        if self.exchange_item.pdf_path:
            pdf_file_path = self.exchange_item.pdf_path
            # Extract PDF filename from path
            original_pdf_filename = pdf_file_path.rsplit('/', 1)[-1]
            formatted_pdf_filename = format_filename(original_pdf_filename)
            local_pdf_path = download_dir / formatted_pdf_filename
            
            # Check if PDF already exists
            if local_pdf_path.exists() and local_pdf_path.stat().st_size > 0:
                pdf_path = str(local_pdf_path)
                logger.info(f"PDF already exists: {pdf_path}")
            elif self.service.download_file(pdf_file_path, str(local_pdf_path), resume=True):
                pdf_path = str(local_pdf_path)
                logger.info(f"Downloaded PDF: {pdf_file_path} -> {pdf_path}")
            else:
                logger.warning(f"Failed to download PDF file: {pdf_file_path}")
        else:
            # Fallback: try to find PDF by base filename (for backward compatibility)
            base_filename = '.'.join(self.exchange_item.filename.split('.')[:-1])
            folder_path = self.exchange_item.file_path.rsplit('/', 1)[0]
            pdf_filename = base_filename + '.pdf'
            pdf_file_path = f"{folder_path}/{pdf_filename}"
            
            if self.service.check_file_exists(pdf_file_path):
                original_pdf_filename = pdf_filename
                formatted_pdf_filename = format_filename(original_pdf_filename)
                local_pdf_path = download_dir / formatted_pdf_filename
                
                # Check if PDF already exists
                if local_pdf_path.exists() and local_pdf_path.stat().st_size > 0:
                    pdf_path = str(local_pdf_path)
                    logger.info(f"PDF already exists (fallback): {pdf_path}")
                elif self.service.download_file(pdf_file_path, str(local_pdf_path), resume=True):
                    pdf_path = str(local_pdf_path)
                    logger.info(f"Downloaded PDF (fallback): {pdf_file_path} -> {pdf_path}")
        
        return video_path, pdf_path

    def _get_download_directory(self) -> Path:
        """Resolve the local directory used for exchange downloads."""
        download_storage_path = (self.config.download_storage_path or '').strip()
        if download_storage_path:
            return Path(download_storage_path)

        if self.config.storage_location and self.config.storage_location.path:
            return Path(self.config.storage_location.path)

        raise ValueError(
            "Either download_storage_path or storage_location.path must be configured."
        )
    
    def _verify_files(self, video_path: str, pdf_path: Optional[str]):
        """
        Verify downloaded files (checksums, size, etc.).
        
        Args:
            video_path: Path to video file
            pdf_path: Path to PDF file (optional)
        """
        # Verify video file exists and has content
        if not video_path or not os.path.exists(video_path):
            raise Exception("Video file not found after download")
        
        video_size = os.path.getsize(video_path)
        if video_size == 0:
            raise Exception("Video file is empty")
        
        # Verify PDF if provided
        if pdf_path and os.path.exists(pdf_path):
            pdf_size = os.path.getsize(pdf_path)
            if pdf_size == 0:
                logger.warning("PDF file is empty, but continuing import")
        
        # TODO: Verify checksums if available in ExchangeItem
        # For now, we rely on file size verification
    
    def _get_or_create_license(
        self,
        profile: Profile,
        remote_metadata: Optional[Dict[str, Any]] = None,
    ) -> License:
        """
        Create a new internal license for OK-Tools managed item.
        
        Args:
            profile: Profile instance (already obtained)
        
        Returns:
            License instance
        """
        contribution_id = self.exchange_item.contribution_id

        # Always create a new internal license number, even if the exchange item has a numeric ID.
        logger.info(f"Creating new internal license for contribution_id {contribution_id}")

        # Get category from meta.json or use default
        # Try to parse .meta.json if available
        meta_data = {}
        if self.exchange_item.file_path:
            # Try to find and parse .meta.json file
            try:
                base_name = '.'.join(self.exchange_item.filename.split('.')[:-1])
                folder_path = self.exchange_item.file_path.rsplit('/', 1)[0]
                meta_json_path = f"{folder_path}/{base_name}.meta.json"

                if self.service.check_file_exists(meta_json_path):
                    meta_data = self.service.parse_meta_json(meta_json_path) or {}
            except Exception as e:
                logger.warning(f"Could not parse meta.json for exchange item {self.exchange_item.id}: {e}")

        category = None
        if meta_data.get('category_id'):
            category = get_category_by_id(meta_data['category_id'])

        if not category:
            # Use default category
            try:
                category = Category.objects.first()
                if not category:
                    # Create default category if none exists
                    from django.utils.translation import gettext_lazy as _
                    category = Category.objects.get_or_create(name=_('Gastbeitrag'))[0]
            except Category.DoesNotExist:
                from django.utils.translation import gettext_lazy as _
                category = Category.objects.get_or_create(name=_('Gastbeitrag'))[0]

        new_number = self._generate_next_license_number()

        remote_metadata = remote_metadata or {}
        remote_title = remote_metadata.get('title') or remote_metadata.get('name')
        remote_subtitle = remote_metadata.get('subtitle')
        remote_description = remote_metadata.get('description')
        remote_further_persons = (
            remote_metadata.get('further_persons')
            or remote_metadata.get('furtherInvolvedPersons')
            or remote_metadata.get('furtherPersons')
        )
        remote_duration = self._parse_duration(remote_metadata.get('duration'))

        remote_tags = remote_metadata.get('tags')
        if not isinstance(remote_tags, list):
            remote_tags = None
        if isinstance(remote_tags, list):
            remote_tags = [str(tag).strip() for tag in remote_tags if str(tag).strip()][:4]

        remote_category = remote_metadata.get('category')
        if isinstance(remote_category, dict):
            remote_category = remote_category.get('name')
        if remote_category:
            remote_category_obj = get_category_by_name(str(remote_category).strip())
            if remote_category_obj:
                category = remote_category_obj

        repetitions_allowed = self._parse_bool(
            remote_metadata.get('repetitionsAllowed', remote_metadata.get('repetitions_allowed')),
            default=False,
        )
        allow_exchange = self._parse_bool(
            remote_metadata.get('allowExchange', remote_metadata.get('media_authority_exchange_allowed')),
            default=meta_data.get('allow_exchange', True),
        )
        allow_exchange_other_states = self._parse_bool(
            remote_metadata.get('allowExchangeOtherStates', remote_metadata.get('media_authority_exchange_allowed_other_states')),
            default=meta_data.get('allow_exchange_other_states', False),
        )
        youth_protection_necessary = self._parse_bool(
            remote_metadata.get('youthProtectionNecessary', remote_metadata.get('youth_protection_necessary')),
            default=meta_data.get('youth_protection_necessary', False),
        )
        youth_protection_category = (
            remote_metadata.get('youthProtectionCategory')
            or remote_metadata.get('youth_protection_category')
            or meta_data.get('youth_protection_category')
            or 'none'
        )
        save_to_mediathek = self._parse_bool(
            remote_metadata.get('saveToMediathek', remote_metadata.get('store_in_ok_media_library')),
            default=meta_data.get('save_to_mediathek', False),
        )

        # Create license with metadata from exchange item (similar to import_json_view)
        license = License.objects.create(
            number=new_number,
            title=remote_title or self.exchange_item.title or f"Imported from Exchange - {contribution_id}",
            subtitle=remote_subtitle,
            description=remote_description or self.exchange_item.description or "",
            further_persons=remote_further_persons,
            duration=remote_duration or self.exchange_item.duration or timezone.timedelta(seconds=0),
            profile=profile,
            category=category,
            tags=remote_tags,
            # Set exchange flags based on source
            media_authority_exchange_allowed=allow_exchange,
            store_in_ok_media_library=save_to_mediathek,
            repetitions_allowed=repetitions_allowed,
            media_authority_exchange_allowed_other_states=allow_exchange_other_states,
            youth_protection_necessary=youth_protection_necessary,
            youth_protection_category=youth_protection_category,
            is_screen_board=False,
            infoblock=False,
            confirmed=False,
        )

        logger.info(
            f"Created new internal license {license.id} with number {new_number} "
            f"for contribution_id {contribution_id}"
        )
        return license

    def _generate_next_license_number(self) -> int:
        """
        Generate the next sequential license number (internal numbering).

        This uses a database transaction + row lock to reduce race conditions during concurrent imports.
        """
        with transaction.atomic():
            last_license = License.objects.select_for_update().order_by('-number').first()
            if last_license and last_license.number:
                return last_license.number + 1
            return 1
    
    def _create_legacy_license(self, profile: Profile) -> License:
        """
        Create license for legacy (non-OK-Tools) item.
        
        Args:
            profile: Profile instance (already obtained)
        
        Returns:
            License instance
        """
        logger.info(f"Creating legacy license for exchange item {self.exchange_item.id}")
        
        # Try to parse .meta.json if available
        meta_data = {}
        if self.exchange_item.file_path:
            # Try to find and parse .meta.json file
            try:
                base_name = '.'.join(self.exchange_item.filename.split('.')[:-1])
                folder_path = self.exchange_item.file_path.rsplit('/', 1)[0]
                meta_json_path = f"{folder_path}/{base_name}.meta.json"
                
                if self.service.check_file_exists(meta_json_path):
                    meta_data = self.service.parse_meta_json(meta_json_path) or {}
            except Exception as e:
                logger.warning(f"Could not parse meta.json for exchange item {self.exchange_item.id}: {e}")
        
        # Get default category
        try:
            category = Category.objects.first()
            if not category:
                from django.utils.translation import gettext_lazy as _
                category = Category.objects.get_or_create(name=_('Gastbeitrag'))[0]
        except Category.DoesNotExist:
            from django.utils.translation import gettext_lazy as _
            category = Category.objects.get_or_create(name=_('Gastbeitrag'))[0]
        
        new_number = self._generate_next_license_number()
        
        license = License.objects.create(
            number=new_number,
            title=self.exchange_item.title or f"Legacy Import - {self.exchange_item.filename}",
            description=self.exchange_item.description or f"Imported from exchange folder: {self.exchange_item.channel}",
            duration=self.exchange_item.duration or timezone.timedelta(seconds=0),
            profile=profile,
            category=category,
            media_authority_exchange_allowed=meta_data.get('allow_exchange', True),
            store_in_ok_media_library=meta_data.get('save_to_mediathek', False),
            repetitions_allowed=False,
            media_authority_exchange_allowed_other_states=meta_data.get('allow_exchange_other_states', False),
            youth_protection_necessary=meta_data.get('youth_protection_necessary', False),
            youth_protection_category=meta_data.get('youth_protection_category') or 'none',
            is_screen_board=False,
            infoblock=False,
            confirmed=False,
        )
        
        logger.info(f"Created legacy license {license.id} with number {new_number}")
        return license
    
    def _get_import_storage_location(self) -> StorageLocation:
        """
        Get or create storage location for imported files.
        
        Priority:
        1. Use storage_location from config if set
        2. Find existing storage by path (to avoid duplicates)
        3. Fall back to searching by name
        4. Create new storage if none found
        
        Returns:
            StorageLocation instance
        """
        # First priority: use storage_location from config if explicitly set
        if self.config.storage_location:
            logger.debug(f"Using configured storage location: {self.config.storage_location.id} ({self.config.storage_location.name})")
            return self.config.storage_location
        
        # Second priority: find existing storage by path (if download_storage_path is set)
        storage_path = self.config.download_storage_path
        
        if storage_path:
            # Normalize path for comparison (remove trailing slashes)
            normalized_path = storage_path.rstrip('/')
            
            # Try to find existing storage by exact path match
            # This prevents creating duplicate storage locations for the same path
            storage = StorageLocation.objects.filter(
                path__in=[storage_path, normalized_path, f"{storage_path}/", f"{normalized_path}/"]
            ).first()
            
            if not storage:
                # Fallback: try to find by name (for backward compatibility)
                storage = StorageLocation.objects.filter(
                    storage_type='CUSTOM',
                    name__icontains='import'
                ).first()
            
            if not storage:
                # Create new storage location only if none exists for this path
                # Use full_clean() to ensure validation runs (including duplicate path check)
                storage = StorageLocation(
                    name='Exchange Imports',
                    storage_type='CUSTOM',
                    path=normalized_path,
                    is_active=True,
                    scan_enabled=False,
                )
                storage.full_clean()  # Validate before saving
                storage.save()
                logger.info(f"Created new storage location for imports: {storage.id} at {normalized_path}")
            else:
                logger.debug(f"Using existing storage location: {storage.id} ({storage.name}) at {storage.path}")
        else:
            # No storage_path and no storage_location - this is an error
            raise ValueError(
                "Either 'storage_location' must be set in ExchangeConfig, "
                "or 'download_storage_path' must be provided."
            )
        
        return storage
    
    def _create_video_file(
        self,
        license: License,
        video_path: str,
        storage_location: StorageLocation
    ) -> VideoFile:
        """
        Create VideoFile record for imported video with full metadata extraction.
        
        VideoFile is automatically linked to License via signals (auto_link_to_license)
        based on the number field.
        
        Args:
            license: License instance
            video_path: Local path to video file
            storage_location: StorageLocation instance
            
        Returns:
            VideoFile instance
        """
        from django.utils import timezone
        from media_files.utils import extract_video_metadata_fast
        
        video_file_path = Path(video_path)
        relative_path = video_file_path.name  # Just filename for now
        
        # Extract comprehensive video metadata
        try:
            metadata = extract_video_metadata_fast(video_path)
            logger.info(f"Extracted metadata for {video_path}")
        except Exception as e:
            logger.warning(f"Failed to extract metadata for {video_path}: {e}")
            metadata = {}
        
        # Calculate checksum
        checksum = self._calculate_checksum(video_path)
        
        # Get file size (use from metadata if available, otherwise from filesystem)
        file_size = metadata.get('file_size') or os.path.getsize(video_path)
        
        # Get format (use from metadata if available, otherwise from extension)
        file_format = metadata.get('format') or video_file_path.suffix.lstrip('.').lower()
        
        # Get duration (prefer metadata, then exchange_item, then None)
        duration = metadata.get('duration') or self.exchange_item.duration
        
        video_defaults = {
            'filename': video_file_path.name,
            'file_size': file_size,
            'format': file_format,
            'checksum': checksum,
            'license': license,
            'is_available': True,
            'duration': duration,
            'has_video': metadata.get('has_video', False),
            'video_codec': metadata.get('video_codec', ''),
            'video_codec_long': metadata.get('video_codec_long', ''),
            'video_profile': metadata.get('video_profile', ''),
            'video_bitrate': metadata.get('video_bitrate'),
            'video_bitrate_mode': metadata.get('video_bitrate_mode', ''),
            'fps': metadata.get('fps'),
            'width': metadata.get('width'),
            'height': metadata.get('height'),
            'aspect_ratio': metadata.get('aspect_ratio', ''),
            'pixel_format': metadata.get('pixel_format', ''),
            'color_space': metadata.get('color_space', ''),
            'color_range': metadata.get('color_range', ''),
            'chroma_subsampling': metadata.get('chroma_subsampling', ''),
            'has_audio': metadata.get('has_audio', False),
            'audio_codec': metadata.get('audio_codec', ''),
            'audio_codec_long': metadata.get('audio_codec_long', ''),
            'audio_bitrate': metadata.get('audio_bitrate'),
            'audio_sample_rate': metadata.get('audio_sample_rate'),
            'audio_channels': metadata.get('audio_channels'),
            'audio_channel_layout': metadata.get('audio_channel_layout', ''),
            'total_bitrate': metadata.get('total_bitrate'),
            'last_scanned': timezone.now(),
        }

        video_file = VideoFile.objects.filter(
            number=license.number,
            storage_location=storage_location,
            file_path=relative_path,
        ).first()

        existing = getattr(license, 'video_file', None)
        if existing and (not video_file or existing.pk != video_file.pk):
            VideoFile.objects.filter(pk=existing.pk).update(license=None)
            logger.info(
                f"Unlinked existing VideoFile {existing.id} from License {license.number} "
                "before assigning imported file"
            )

        if video_file:
            for field_name, field_value in video_defaults.items():
                setattr(video_file, field_name, field_value)
            video_file.save()
            logger.info(
                f"Updated existing VideoFile {video_file.id} for license {license.number} "
                "after concurrent scan discovery"
            )
        else:
            video_file = VideoFile.objects.create(
                number=license.number,
                storage_location=storage_location,
                file_path=relative_path,
                **video_defaults,
            )
            logger.info(
                f"Created VideoFile {video_file.id} for license {license.number} "
                f"with full metadata (codec: {video_file.video_codec}, "
                f"resolution: {video_file.width}x{video_file.height}, "
                f"fps: {video_file.fps})"
            )

        return video_file
    
    def _calculate_checksum(self, file_path: str) -> str:
        """
        Calculate SHA256 checksum of file.
        
        Args:
            file_path: Path to file
            
        Returns:
            Hex digest of SHA256 checksum
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _store_pdf(self, license: License, pdf_path: str):
        """
        Store PDF file (link to license).
        
        For now, we just log it. PDF storage can be implemented later
        if needed (similar to how videos are stored).
        
        Args:
            license: License instance
            pdf_path: Path to PDF file
        """
        # TODO: Implement PDF storage if needed
        # For now, PDFs are downloaded but not stored in a separate model
        logger.info(f"PDF file stored for license {license.id}: {pdf_path}")
    
    def _enqueue_peertube_upload(self, video_file: VideoFile):
        """
        Enqueue PeerTube upload task (optional).
        
        Args:
            video_file: VideoFile instance
        """
        # TODO: Integrate with existing PeerTube upload pipeline
        # This would typically call a Celery task from media_files.tasks
        logger.info(f"PeerTube upload enqueued for video_file {video_file.id} (not implemented yet)")
