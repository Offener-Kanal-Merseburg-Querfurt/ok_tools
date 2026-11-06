from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_prometheus.models import ExportModelOperationsMixin
from registration.models import Profile
import datetime
import logging
import uuid


logger = logging.getLogger('django')

MAX_TITLE_LENGTH = 255



class YouthProtectionCategory(models.TextChoices):
    """Youth protection categories."""

    NONE = 'none', _('not necessary')
    FROM_12 = 'from_12', _('from 12')
    FROM_16 = 'from_16', _('from 16')
    FROM_18 = 'from_18', _('from 18')

    @classmethod
    def verbose_name(cls, value: str) -> str:
        """Return the verbose name to the given value."""
        for choice in cls.choices:
            if value == choice[0]:
                return choice[1]  # verbose name

        return ''


class YouthProtectionWindow(models.Model):
    """Broadcast window a youth protection category may be aired in.

    The category lives on the licence, but *when* that category may go on air
    is an editorial/legal decision that differs per station and changes over
    time, so it is configured here instead of being hard-coded. Windows
    normally wrap around midnight (e.g. 22:00-06:00); see ``allows``.
    """

    #: Times the station usually starts/ends restricted material with.
    DEFAULTS = {
        'from_12': (datetime.time(20, 0), datetime.time(6, 0)),
        'from_16': (datetime.time(22, 0), datetime.time(6, 0)),
        'from_18': (datetime.time(23, 0), datetime.time(6, 0)),
    }

    category = models.CharField(
        _('Youth protection category'),
        max_length=255,
        unique=True,
        choices=YouthProtectionCategory.choices,
    )
    enabled = models.BooleanField(
        _('Enforce this window'),
        default=True,
        help_text=_('When off, this category may be planned at any time.'),
    )
    start_time = models.TimeField(
        _('Broadcast allowed from'),
        default=datetime.time(22, 0),
    )
    end_time = models.TimeField(
        _('Broadcast allowed until'),
        default=datetime.time(6, 0),
        help_text=_('Earlier than the start time means the window crosses '
                    'midnight, e.g. 22:00-06:00.'),
    )

    class Meta:
        verbose_name = _('Youth protection broadcast window')
        verbose_name_plural = _('Youth protection broadcast windows')
        ordering = ['category']

    def __str__(self):
        """Return the category with its window."""
        return f'{self.get_category_display()}: {self.label()}'

    def label(self):
        """Return the window as ``HH:MM-HH:MM`` for messages and the UI."""
        return (f'{self.start_time.strftime("%H:%M")}'
                f'-{self.end_time.strftime("%H:%M")}')

    @staticmethod
    def _seconds(value):
        """Return seconds since midnight for a ``time``."""
        return value.hour * 3600 + value.minute * 60 + value.second

    def length_seconds(self):
        """Return the window length, counting a wrap around midnight."""
        start = self._seconds(self.start_time)
        end = self._seconds(self.end_time)
        length = (end - start) % 86400
        # start == end is read as "the whole day", not "no time at all":
        # an operator clearing both fields should not block everything.
        return 86400 if length == 0 else length

    def allows(self, start_seconds, duration_seconds):
        """Whether an item fits fully inside this window.

        Both the window and the item may cross midnight, so the check is done
        on a circular clock: measure the item's start as an offset from the
        window start and require the whole duration to fit before the end.
        """
        offset = (int(start_seconds) - self._seconds(self.start_time)) % 86400
        return offset + max(int(duration_seconds), 0) <= self.length_seconds()

    @classmethod
    def enforced_windows(cls):
        """Return ``{category: window}`` for every enforced category."""
        return {
            window.category: window
            for window in cls.objects.filter(enabled=True)
            if window.category != YouthProtectionCategory.NONE
        }


class Category(models.Model):
    """
    Model representing a category.

    Each License has a category.
    """

    name = models.CharField(
        _('Category'),
        blank=False,
        null=False,
        max_length=255,
        unique=True,
    )

    numeric_id = models.IntegerField(
        _('Numeric ID'),
        blank=True,
        null=True,
        unique=True,
        help_text=_('Numeric ID used for import from external systems (e.g., 101, 102, 103)'),
    )

    def __str__(self) -> str:
        """Represent category by its String."""
        return self.name

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Category')
        verbose_name_plural = _('Categories')


def default_category():
    """Provide the default Category."""
    return Category.objects.get_or_create(name=_('Not Selected'))[0]


class License(ExportModelOperationsMixin('license'), models.Model):
    """Model representing a (Beitragsfreistellung)."""

    title = models.CharField(
        _('Title'),
        blank=False,
        null=True,
        max_length=MAX_TITLE_LENGTH,
    )

    subtitle = models.CharField(
        _('Subtitle'),
        blank=True,
        null=True,
        max_length=MAX_TITLE_LENGTH,
    )

    description = models.TextField(
        _('Description'),
        blank=False,
        null=True,
    )

    further_persons = models.TextField(
        _('Further involved persons'),
        blank=True,
        null=True,
    )
    duration = models.DurationField(  # timedelta
        _('Duration'),
        help_text=_('Format: hh:mm:ss or mm:ss'),
        blank=True,
        null=False,
        default=datetime.timedelta(seconds=0),
    )

    suggested_date = models.DateTimeField(  # datetime
        _('Suggested broadcast date'),
        blank=True,
        null=True,
    )

    repetitions_allowed = models.BooleanField(
        _('Repetitions allowed'),
        blank=False,
        null=True,
    )

    media_authority_exchange_allowed = models.BooleanField(
        _('Media Authority exchange allowed in Saxony-Anhalt'),
        blank=False,
        null=True,
    )

    media_authority_exchange_allowed_other_states = models.BooleanField(
        _('Media Authority exchange allowed in other states than Saxony-Anhalt.'),
        blank=False,
        null=True,
    )

    youth_protection_necessary = models.BooleanField(
        _('Youth protection necessary'),
        blank=False,
        null=True,
    )

    youth_protection_category = models.CharField(
        _('Youth protection category'),
        max_length=255,
        blank=False,
        null=True,
        choices=YouthProtectionCategory.choices,
        default=YouthProtectionCategory.NONE,
    )

    store_in_ok_media_library = models.BooleanField(
        _('Store in OK media library'),
        blank=False,
        null=True,
    )

    mediathek_url = models.URLField(
        _('Mediathek URL'),
        blank=True,
        null=True,
    )

    mediathek_url_updated_at = models.DateTimeField(
        _('Mediathek URL updated at'),
        blank=True,
        null=True,
    )

    is_live = models.BooleanField(
        _('Live broadcast'),
        default=False,
        help_text=_('Live broadcasts do not allow repetitions, exchange, or mediathek storage.')
    )

    tags = models.JSONField(
        _('Tags'),
        blank=True,
        null=True,
        default=None,
        help_text=_('Maximum 4 tags'),
    )

    signature = models.TextField(
        _('Signature'),
        blank=True,
        null=True,
        help_text=_('Base64 encoded signature image'),
    )

    signature_svg = models.TextField(
        _('Signature SVG'),
        blank=True,
        null=True,
        help_text=_('Primary SVG signature data'),
    )

    signature_points = models.JSONField(
        _('Signature points'),
        blank=True,
        null=True,
        default=None,
        help_text=_('Biometric signature stroke points (x,y,time,pressure).'),
    )

    signature_metadata = models.JSONField(
        _('Signature metadata'),
        blank=True,
        null=True,
        default=None,
        help_text=_('Signature metadata such as device, user-agent, and capture details.'),
    )

    signature_method = models.CharField(
        _('Signature method'),
        max_length=32,
        blank=True,
        null=True,
        help_text=_('Signature input method (mouse, touch, stylus, qr_phone).'),
    )

    signature_signed_at = models.DateTimeField(
        _('Signature signed at'),
        blank=True,
        null=True,
        help_text=_('When the digital signature was captured.'),
    )

    created_at = models.DateTimeField(
        _('Created at'),
        auto_now_add=True,
        db_index=True,
    )

    updated_at = models.DateTimeField(
        _('Updated at'),
        auto_now=True,
        db_index=True,
    )

    # a visible identification number (not djangos id)
    number = models.IntegerField(
        _('Number'),
        default=1,
        unique=True,
        blank=False,
        null=False,
    )

    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        verbose_name=_('Profile'),
        blank=False,
        null=False,
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        default=default_category,
        verbose_name=_('Category'),
    )

    confirmed = models.BooleanField(
        _('Confirmed'),
        blank=False,
        null=False,
        default=False,
    )

    confirmed_at = models.DateTimeField(
        _('Confirmed at'),
        blank=True,
        null=True,
        help_text=_('Timestamp when the license was confirmed (Genehmigt).'),
    )

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('Confirmed by'),
        help_text=_('Staff member who confirmed (Genehmigt) this license.'),
    )

    is_screen_board = models.BooleanField(
        _('Screen Board'),
        blank=False,
        null=False,
        default=False,
    )

    infoblock = models.BooleanField(
        _('Infoblock'),
        blank=False,
        null=False,
        default=False,
    )

    # --- Archive / legacy data -------------------------------------------
    external_production = models.BooleanField(
        _('External production'),
        default=False,
        help_text=_('Fremdbeitrag: produced outside the OK (e.g. by another '
                    'channel or an external producer).'),
    )

    internal_note = models.TextField(
        _('Internal note'),
        blank=True,
        default='',
        help_text=_('Staff-only note. Not shown to users, not exported to '
                    'the media library or the exchange.'),
    )

    legacy_number = models.PositiveIntegerField(
        _('Legacy number'),
        blank=True,
        null=True,
        db_index=True,
        help_text=_('Contribution number in the previous archive system '
                    '(as written on DVDs and tapes).'),
    )

    def __str__(self) -> str:
        """Licenses are represented by its titles."""
        if self.subtitle:
            return f'{self.title} - {self.subtitle}'
        else:
            return self.title or ""

    def clean(self) -> None:
        """Either the LR is a screen_board or the duration isn't null."""
        if self.is_screen_board:
            # it's a screen board, we are fine
            from licenses.config import get_screen_board_duration
            self.duration = timedelta(
                seconds=get_screen_board_duration())
            return super().clean()

        if not self.duration:
            raise ValidationError(
                {'duration': _('Duration must not be null.')})

        return super().clean()

    @transaction.atomic
    def save(self, update_fields=None, *args, **kwargs) -> None:
        """
        Make confirmed Licenses not editable.

        Nevertheless the confirmed status itself should stay editable.
        Live broadcasts automatically disable repetitions, exchange, and mediathek.
        """
        # Auto-set fields for Live broadcasts
        if self.is_live:
            self.repetitions_allowed = False
            self.media_authority_exchange_allowed = False
            self.media_authority_exchange_allowed_other_states = False
            self.store_in_ok_media_library = False

        # Emulate an Autofield for number.
        if self.id is None:  # license is new created

            if (License.objects.filter(number=self.number) and
                    # number already exists
                    (last := License.objects.order_by('number')
                     .last())):
                i = last.number
                i += 1
                self.number = i

            return super().save(*args, **kwargs)

        old = License.objects.get(id=self.id)

        # editing is allowed if only action was to unconfirm license,
        # update duration, or update mediathek URL metadata
        allowed_update_fields = {
            ('confirmed',),
            ('duration',),
            ('mediathek_url',),
            ('mediathek_url_updated_at',),
            ('mediathek_url', 'mediathek_url_updated_at'),
            ('mediathek_url_updated_at', 'mediathek_url'),
        }
        normalized_update_fields = None
        if update_fields is not None:
            normalized_update_fields = tuple(update_fields)

        if old.confirmed and normalized_update_fields not in allowed_update_fields:
            logger.warning(
                f'Not saved {self} because it is already confirmed.')
            return

        return super().save(*args, **kwargs)

    def get_video_file(self):
        """
        Get associated video file if exists.
        
        First checks OneToOne relation (video_file), then falls back to 
        searching by number (returns newest available version).
        """
        try:
            # First try to get via OneToOne relation (reverse lookup)
            if hasattr(self, 'video_file'):
                try:
                    video = self.video_file
                    if video:
                        return video
                except Exception:
                    pass
            
            # Fallback: search by number (newest available version)
            from media_files.models import VideoFile
            return VideoFile.objects.filter(
                number=self.number,
                is_available=True
            ).order_by('-created_at').first()
        except Exception:
            return None
    
    def get_tags_display(self):
        """Get formatted tags for display."""
        if not self.tags or self.tags is None:
            return ''
        if isinstance(self.tags, list) and len(self.tags) > 0:
            return ', '.join(str(tag).strip() for tag in self.tags if tag)
        return ''

    def has_any_signature(self):
        """Return True when any supported signature format is available."""
        if self.signature:
            return True
        if self.signature_svg:
            return True
        if self.signature_points:
            return True
        return False

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('License')
        verbose_name_plural = _('Licenses')


class ArchiveMediumType(models.TextChoices):
    """Kind of physical (or legacy storage) carrier of a contribution."""

    DVD = 'dvd', _('DVD')
    MASTER_DVD = 'master_dvd', _('Master DVD')
    VHS = 'vhs', _('VHS cassette')
    MASTER_VHS = 'master_vhs', _('Master VHS cassette')
    TAPE = 'tape', _('Broadcast tape (Sendeband)')
    RAID = 'raid', _('Hard disk / RAID')
    OTHER = 'other', _('Other')


class ArchiveMedium(models.Model):
    """
    A carrier in the physical archive that holds a copy of a license.

    One license can be on several carriers (e.g. DVD + master tape) and one
    carrier (e.g. DVD no. 15) holds many licenses.
    """

    license = models.ForeignKey(
        License,
        on_delete=models.CASCADE,
        related_name='archive_media',
        verbose_name=_('License'),
    )

    medium_type = models.CharField(
        _('Medium type'),
        max_length=20,
        choices=ArchiveMediumType.choices,
        default=ArchiveMediumType.DVD,
    )

    # CharField: legacy labels are not always numeric ("140/84", "Raid 2").
    number = models.CharField(
        _('Medium number'),
        max_length=50,
        help_text=_('Number or label written on the carrier.'),
    )

    note = models.CharField(
        _('Note'),
        max_length=255,
        blank=True,
        default='',
    )

    def __str__(self) -> str:
        """Represent the carrier like it is labelled on the shelf."""
        return f'{self.get_medium_type_display()} {self.number}'

    class Meta:
        """Defines the message IDs."""

        verbose_name = _('Archive medium')
        verbose_name_plural = _('Archive media')
        ordering = ['medium_type', 'number']
        constraints = [
            models.UniqueConstraint(
                fields=['license', 'medium_type', 'number'],
                name='licenses_archive_medium_unique_per_license',
            ),
        ]
        indexes = [
            models.Index(fields=['medium_type', 'number']),
        ]


class NextcloudVideoFile(models.Model):
    """Model representing a video file uploaded to Nextcloud."""

    license = models.ForeignKey(
        License,
        on_delete=models.CASCADE,
        related_name='nextcloud_videos',
        verbose_name=_('License'),
    )
    nextcloud_file_id = models.CharField(
        max_length=500,
        verbose_name=_('Nextcloud File ID'),
        help_text=_('File ID or path in Nextcloud'),
    )
    nextcloud_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name=_('Nextcloud URL'),
        help_text=_('Direct link to file in Nextcloud'),
    )
    filename = models.CharField(
        max_length=500,
        verbose_name=_('Filename'),
        help_text=_('Original filename'),
    )
    file_size = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_('File Size (bytes)'),
    )
    uploaded_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Uploaded at'),
        db_index=True,
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name=_('Is Deleted'),
        help_text=_('Flag if file was deleted from Nextcloud'),
    )
    user_uploaded = models.BooleanField(
        default=False,
        verbose_name=_('User uploaded'),
        help_text=_('True if the file was uploaded by the rightsholder via the portal; '
                    'False if created by staff (e.g. in Admin). Used to decide whether to '
                    'send draft_scheduled, planned_scheduled, contributions_available emails.'),
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Deleted at'),
        help_text=_('When file was deleted from Nextcloud'),
    )
    downloaded_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Downloaded at'),
        help_text=_('When the file was downloaded from Nextcloud to local storage'),
    )
    local_path = models.CharField(
        max_length=1000,
        blank=True,
        default='',
        verbose_name=_('Local path'),
        help_text=_('Path of the downloaded copy in local storage'),
    )

    @property
    def is_image(self) -> bool:
        """Whether the uploaded file is a photo (screen board) and not a video."""
        from licenses.media_types import is_image_filename
        return is_image_filename(self.filename)

    def __str__(self) -> str:
        """Return string representation."""
        return f"{self.license.number} - {self.filename}"

    class Meta:
        """Meta options for NextcloudVideoFile."""

        verbose_name = _('Nextcloud Video File')
        verbose_name_plural = _('Nextcloud Video Files')
        ordering = ['-uploaded_at']


class LicensesConfig(models.Model):
    """Configuration for licenses module (singleton)."""
    
    # Fixed duration of a screen board (Bildschirmtafel) in seconds
    screen_board_duration = models.IntegerField(
        default=20,
        verbose_name=_('Screen Board Duration (seconds)'),
        help_text=_('Fixed duration for screen board display in seconds')
    )

    # Storage settings
    download_storage_path = models.CharField(
        max_length=500,
        default='/app/media/',
        verbose_name=_('Download Storage Path'),
        help_text=_('Local path for downloaded files')
    )

    auto_download_to_storage = models.BooleanField(
        default=True,
        verbose_name=_('Download Nextcloud files automatically'),
        help_text=_(
            'Download a file to local storage as soon as it was uploaded to Nextcloud, '
            'without pressing "Download" in the admin. Requires a configured download '
            'storage path and a running Celery worker on the "download" queue.'
        ),
    )

    create_videofile_on_nextcloud_download = models.BooleanField(
        default=False,
        verbose_name=_('Create VideoFile on Nextcloud download'),
        help_text=_(
            'After downloading a Nextcloud video to disk, create a VideoFile in media_files '
            'so it shows as Player in the license list immediately. Requires MEDIA_FILES_ENABLED '
            'and the download path to be under a StorageLocation. If off, only the file is saved; '
            'a storage scan can create the VideoFile later.'
        ),
    )

    send_status_emails = models.BooleanField(
        default=True,
        verbose_name=_('Send status emails'),
        help_text=_('Send email notifications about video status (upload, scheduling, broadcast dates).'),
    )

    notification_media_authority_names = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_('Send notifications to (Media Authorities)'),
        help_text=_(
            'Send status emails only to users whose profile belongs to one of these '
            'Media Authorities (Offene Kanäle/Bürgermedien). Empty = send to all. '
            'Use to restrict to "our" organisation(s) only.'
        ),
    )

    # Freistellung (exemption) print form configuration
    freistellung_enabled = models.BooleanField(
        default=False,
        verbose_name=_('Freistellung enabled'),
        help_text=_('Enable freistellung-specific text overlays and staff signature in the generated PDF.'),
    )

    freistellung_city = models.CharField(
        max_length=255,
        default='',
        blank=True,
        verbose_name=_('Freistellung city'),
        help_text=_('City name for "Ort, Datum" in the Freistellung print form.'),
    )

    freistellung_signature_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('Freistellung signature user'),
        help_text=_(
            'Staff member whose signature appears on the Freistellung print form. '
            'When this user confirms a license, their signature is added to the PDF.'
        ),
    )

    freistellung_signature_text = models.CharField(
        max_length=500,
        default='Im Auftrag des Vorstands der Medienanstalt Sachsen-Anhalt',
        blank=True,
        verbose_name=_('Freistellung signature text'),
        help_text=_('Text below the signature on the Freistellung print form.'),
    )

    freistellung_sendezeit_no_protection = models.CharField(
        max_length=500,
        default='Sendezeit gem. JMStV zu beachten: Nein',
        blank=True,
        verbose_name=_('Sendezeit text (no youth protection)'),
        help_text=_('Text for "Sendezeit gem. JMStV zu beachten" when no youth protection is needed.'),
    )

    freistellung_sendezeit_with_protection = models.CharField(
        max_length=500,
        default='Sendezeit gem. JMStV zu beachten: Ja\nSendezeit ab 22:00 Uhr',
        blank=True,
        verbose_name=_('Sendezeit text (with youth protection)'),
        help_text=_(
            'Text for "Sendezeit gem. JMStV zu beachten" and "Sendezeit ab" '
            'when youth protection is needed. Use \\n for line break.'
        ),
    )

    freistellung_sendezeit_time = models.CharField(
        max_length=20,
        default='22:00',
        blank=True,
        verbose_name=_('Sendezeit time'),
        help_text=_('Time for "Sendezeit ab ___ Uhr" in the Freistellung print form (e.g. 22:00).'),
    )

    class Meta:
        verbose_name = _('Licenses Configuration')
        verbose_name_plural = _('Licenses Configuration')
    
    def __str__(self):
        """Return string representation."""
        return str(_("Licenses Configuration"))
    
    def save(self, *args, **kwargs):
        """Ensure only one config instance exists."""
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def get_config(cls):
        """Get the singleton config instance, create if doesn't exist."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class LicenseNotificationEventType(models.TextChoices):
    """Notification event types for license-related user emails."""

    VIDEO_UPLOADED = "video_uploaded", _("Video uploaded")
    DRAFT_SCHEDULED = "draft_scheduled", _("Draft scheduled")
    PLANNED_SCHEDULED = "planned_scheduled", _("Planned scheduled")
    CONTRIBUTIONS_AVAILABLE = "contributions_available", _("Contributions available")
    MEDIATHEK_PUBLISHED = "mediathek_published", _("Mediathek published")


class LicenseNotificationEvent(models.Model):
    """
    Deduplication log for license-related user notification emails.

    We deduplicate by license number + event type. This keeps mail sending
    idempotent across retries and repeated saves/imports.
    """

    license_number = models.IntegerField(
        _("License number"),
        db_index=True,
        help_text=_("License number used for matching and deduplication."),
    )
    event_type = models.CharField(
        _("Event type"),
        max_length=64,
        choices=LicenseNotificationEventType.choices,
        db_index=True,
    )
    created_at = models.DateTimeField(
        _("Created at"),
        auto_now_add=True,
        db_index=True,
    )
    payload = models.JSONField(
        _("Payload"),
        blank=True,
        null=True,
        default=None,
        help_text=_("Optional structured data about the event (e.g., schedule time, filenames)."),
    )

    class Meta:
        verbose_name = _("License Notification Event")
        verbose_name_plural = _("License Notification Events")
        constraints = [
            models.UniqueConstraint(
                fields=["license_number", "event_type"],
                name="uniq_license_notification_event",
            ),
        ]


class SigningSessionStatus(models.TextChoices):
    """Status for cross-device signing sessions."""

    PENDING = 'pending', _('Pending')
    SIGNED = 'signed', _('Signed')
    EXPIRED = 'expired', _('Expired')
    CANCELLED = 'cancelled', _('Cancelled')


class SigningSession(models.Model):
    """Short-lived session used for QR-based phone signing."""

    license = models.ForeignKey(
        License,
        on_delete=models.CASCADE,
        related_name='signing_sessions',
        verbose_name=_('License'),
        blank=True,
        null=True,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='signing_sessions',
        verbose_name=_('Owner'),
        blank=True,
        null=True,
    )
    token = models.CharField(
        _('Token'),
        max_length=64,
        unique=True,
        db_index=True,
        default=uuid.uuid4,
    )
    status = models.CharField(
        _('Status'),
        max_length=16,
        choices=SigningSessionStatus.choices,
        default=SigningSessionStatus.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField(
        _('Expires at'),
        db_index=True,
    )
    signature_svg = models.TextField(
        _('Signature SVG'),
        blank=True,
        null=True,
    )
    signature_points = models.JSONField(
        _('Signature points'),
        blank=True,
        null=True,
        default=None,
    )
    signature_metadata = models.JSONField(
        _('Signature metadata'),
        blank=True,
        null=True,
        default=None,
    )
    signature_method = models.CharField(
        _('Signature method'),
        max_length=32,
        blank=True,
        null=True,
    )
    signer_ip = models.GenericIPAddressField(
        _('Signer IP'),
        blank=True,
        null=True,
    )
    signer_user_agent = models.TextField(
        _('Signer user agent'),
        blank=True,
        null=True,
    )
    signed_at = models.DateTimeField(
        _('Signed at'),
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(
        _('Created at'),
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        verbose_name = _('Signing Session')
        verbose_name_plural = _('Signing Sessions')
        ordering = ['-created_at']

    def __str__(self):
        if self.license_id:
            return f'{self.license.number} ({self.status})'
        return f'{self.token} ({self.status})'

    def is_expired(self):
        return timezone.now() >= self.expires_at
