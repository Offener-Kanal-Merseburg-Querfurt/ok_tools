"""Django admin configuration for Austausch module."""

from .models import ExchangeChannelAuth
from .models import ExchangeConfig
from .models import ExchangeImport
from .models import ExchangeItem
from .models import ExportToServerRun
from .models import ImportedLicenseMapping
from .tasks import import_exchange_item_task
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _


class ExchangeChannelAuthInline(admin.TabularInline):
    model = ExchangeChannelAuth
    extra = 0
    fields = [
        'channel_name',
        'supports_oktools_api',
        'metadata_api_base_url',
        'metadata_api_token',
        'request_timeout_seconds',
        'is_active',
        'last_success_at',
        'last_error',
    ]
    readonly_fields = ['last_success_at', 'last_error']
    show_change_link = False


@admin.register(ExchangeConfig)
class ExchangeConfigAdmin(admin.ModelAdmin):
    """Admin for ExchangeConfig (singleton)."""
    
    autocomplete_fields = ['storage_location', 'default_media_authority']
    inlines = [ExchangeChannelAuthInline]
    
    def has_add_permission(self, request):
        """Only allow one config instance."""
        return not ExchangeConfig.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of config."""
        return False
    
    def exchange_feed_link(self, obj):
        """Link to Exchange Feed UI."""
        url = reverse('austausch:feed')
        return format_html(
            '<a href="{}" class="button" target="_blank">{}</a>',
            url,
            _('Open Exchange Feed')
        )
    exchange_feed_link.short_description = _('Exchange Feed UI')
    
    list_display = ['nextcloud_base_url', 'sync_lookback_days', 'sync_date_folders_days', 'exchange_feed_link']
    fieldsets = (
        (_('Quick Links'), {
            'fields': ('exchange_feed_link',),
            'classes': ('wide',),
        }),
        (_('Nextcloud Settings'), {
            'fields': ('nextcloud_base_url', 'nextcloud_username', 'nextcloud_password')
        }),
        (_('Folder Patterns'), {
            'fields': ('channel_folder_pattern', 'exchange_folder_pattern')
        }),
        (_('Sync Settings'), {
            'fields': (
                'sync_lookback_days',
                'sync_date_folders_days',
                'channels_list',
                'same_state_channel_exceptions',
            ),
            'description': _(
                'Note: Periodic sync schedule is managed via '
                '<a href="/admin/django_celery_beat/periodictask/" target="_blank">Periodic Tasks</a> '
                '(task name: "sync_exchange_folders"). '
                'You can enable/disable and change schedule there.'
            ),
        }),
        (_('Storage Settings'), {
            'fields': ('storage_location', 'download_storage_path'),
            'description': _(
                'Select an existing storage location to use for imports, or leave empty to create a new one automatically. '
                'If storage location is set, download storage path is only used as fallback.'
            ),
        }),
        (_('Auto-Import Settings'), {
            'fields': ('auto_import_enabled',)
        }),
        (_('Export to server'), {
            'fields': (
                'export_destination',
                'upload_server_path',
                'network_share_base_path',
                'network_share_subfolder',
                'network_share_windows_root',
                'default_media_authority',
                'local_pdf_fallback_path',
                'local_pdf_fallback_path_2',
                'upload_thumbnail_enabled',
                'thumbnail_storage_path',
            ),
            'description': _(
                'Settings for exporting video, PDF, JSON and optional thumbnails. '
                'Choose export destination (Nextcloud or Network Share). '
                'Thumbnail storage path is used only when "Upload Thumbnail Enabled" is checked.'
            ),
        }),
        (_('Export robustness'), {
            'fields': (
                'copy_chunk_size_mb',
                'copy_stall_timeout_seconds',
                'export_tmp_cleanup_hours',
                'export_source_failover_enabled',
                'export_source_min_read_mbps',
                'export_lock_enabled',
            ),
            'classes': ('collapse',),
            'description': _(
                'Safeguards against an unresponsive storage: copies run in chunks '
                'with a stall watchdog, leftover .tmp_ files are swept, an '
                'unreachable source is replaced by a byte-identical copy on '
                'another location, and the same item cannot be exported twice at '
                'the same time. The defaults are sensible; change them only if an '
                'export is being aborted or kept waiting too often.'
            ),
        }),
    )
    
    readonly_fields = ['exchange_feed_link']


@admin.register(ExportToServerRun)
class ExportToServerRunAdmin(admin.ModelAdmin):
    """Admin for export-to-server run results (read-only list)."""
    list_display = ['started_at', 'completed_at', 'user', 'mode', 'total_count', 'success_count', 'failure_count', 'skipped_no_pdf_count']
    list_filter = ['mode']
    readonly_fields = ['started_at', 'completed_at', 'user', 'mode', 'total_count', 'success_count', 'failure_count', 'skipped_no_pdf_count', 'details']
    ordering = ['-started_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ImportedLicenseMapping)
class ImportedLicenseMappingAdmin(admin.ModelAdmin):
    """Admin for remote-to-local license mapping."""

    list_display = ['source_channel', 'remote_license_number', 'local_license', 'updated_at']
    list_filter = ['source_channel']
    search_fields = ['source_channel', 'remote_license_number', 'local_license__number']
    autocomplete_fields = ['local_license']

    def has_module_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return False


@admin.register(ExchangeItem)
class ExchangeItemAdmin(admin.ModelAdmin):
    """Admin for ExchangeItem."""
    
    def changelist_view(self, request, extra_context=None):
        """Add link to Exchange Feed UI in changelist."""
        extra_context = extra_context or {}
        extra_context['exchange_feed_url'] = reverse('austausch:feed')
        return super().changelist_view(request, extra_context)
    
    list_display = [
        'id',
        'contribution_id',
        'filename_short',
        'channel',
        'file_type',
        'import_status_badge',
        'is_oktools_managed_badge',
        'discovered_at',
        'actions_column'
    ]
    list_filter = [
        'channel',
        'import_status',
        'is_oktools_managed',
        'is_legacy',
        'file_type',
        'discovered_at',
    ]
    search_fields = ['filename', 'title', 'description', 'contribution_id']
    readonly_fields = [
        'contribution_id',
        'filename',
        'file_path',
        'channel',
        'file_size',
        'file_type',
        'checksum',
        'title',
        'description',
        'duration',
        'sendeverantwortung',
        'is_oktools_managed',
        'is_legacy',
        'discovered_at',
        'last_seen_at',
        'imported_at',
        'imported_license_link',
    ]
    
    actions = ['import_selected_items']
    
    def filename_short(self, obj):
        """Display shortened filename."""
        if len(obj.filename) > 50:
            return obj.filename[:47] + '...'
        return obj.filename
    filename_short.short_description = _('Filename')
    
    def import_status_badge(self, obj):
        """Display import status as badge."""
        colors = {
            'new': 'warning',
            'imported': 'success',
            'failed': 'danger',
        }
        color = colors.get(obj.import_status, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_import_status_display()
        )
    import_status_badge.short_description = _('Status')
    
    def is_oktools_managed_badge(self, obj):
        """Display OK-Tools managed badge."""
        if obj.is_oktools_managed:
            return format_html('<span class="badge bg-success">{}</span>', _('OK-Tools'))
        elif obj.is_legacy:
            return format_html('<span class="badge bg-secondary">{}</span>', _('Legacy'))
        return '-'
    is_oktools_managed_badge.short_description = _('Type')
    
    def imported_license_link(self, obj):
        """Link to imported license."""
        if obj.imported_license:
            url = reverse('admin:licenses_license_change', args=[obj.imported_license.id])
            return format_html('<a href="{}">{}</a>', url, obj.imported_license)
        return '-'
    imported_license_link.short_description = _('Imported License')
    
    def actions_column(self, obj):
        """Action buttons column."""
        if obj.import_status in ('new', 'failed'):
            url = reverse('austausch:api_import', args=[obj.id])
            return format_html(
                '<a href="{}" class="button" onclick="return confirm(\'{}\')">{}</a>',
                url,
                _('Import this item?'),
                _('Retry') if obj.import_status == 'failed' else _('Import')
            )
        elif obj.import_status == 'imported' and obj.imported_license:
            url = reverse('admin:licenses_license_change', args=[obj.imported_license.id])
            return format_html('<a href="{}">{}</a>', url, _('View License'))
        return '-'
    actions_column.short_description = _('Actions')
    
    def import_selected_items(self, request, queryset):
        """Admin action to import selected items."""
        count = 0
        for item in queryset.filter(import_status__in=['new', 'failed']):
            try:
                # Import synchronously in admin (or could use Celery task)
                from .services.import_service import ImportService
                import_service = ImportService(item, request.user)
                import_service.import_item()
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    _('Error importing {}: {}').format(item.filename, str(e)),
                    level='ERROR'
                )
        
        self.message_user(
            request,
            _('Successfully imported {} items.').format(count),
            level='SUCCESS'
        )
    import_selected_items.short_description = _('Import or retry selected items')


@admin.register(ExchangeImport)
class ExchangeImportAdmin(admin.ModelAdmin):
    """Admin for ExchangeImport."""
    
    list_display = [
        'id',
        'exchange_item_link',
        'status_badge',
        'imported_by',
        'created_at',
        'completed_at',
        'license_link',
        'error_message_short',
    ]
    list_filter = ['status', 'created_at', 'completed_at']
    search_fields = [
        'exchange_item__filename',
        'exchange_item__title',
        'error_message',
    ]
    readonly_fields = [
        'exchange_item',
        'imported_by',
        'status',
        'error_message',
        'created_at',
        'completed_at',
        'license_link',
        'video_file_link',
    ]
    
    def exchange_item_link(self, obj):
        """Link to exchange item."""
        url = reverse('admin:austausch_exchangeitem_change', args=[obj.exchange_item.id])
        return format_html('<a href="{}">{}</a>', url, obj.exchange_item.filename)
    exchange_item_link.short_description = _('Exchange Item')
    
    def status_badge(self, obj):
        """Display status as badge."""
        colors = {
            'pending': 'secondary',
            'downloading': 'info',
            'processing': 'primary',
            'completed': 'success',
            'failed': 'danger',
        }
        color = colors.get(obj.status, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    
    def license_link(self, obj):
        """Link to license."""
        if obj.license:
            url = reverse('admin:licenses_license_change', args=[obj.license.id])
            return format_html('<a href="{}">{}</a>', url, obj.license)
        return '-'
    license_link.short_description = _('License')
    
    def video_file_link(self, obj):
        """Link to video file."""
        if obj.video_file:
            url = reverse('admin:media_files_videofile_change', args=[obj.video_file.id])
            return format_html('<a href="{}">{}</a>', url, obj.video_file)
        return '-'
    video_file_link.short_description = _('Video File')
    
    def error_message_short(self, obj):
        """Display shortened error message."""
        if obj.error_message:
            if len(obj.error_message) > 100:
                return format_html(
                    '<span style="color: red;" title="{}">{}...</span>',
                    obj.error_message,
                    obj.error_message[:97]
                )
            return format_html('<span style="color: red;">{}</span>', obj.error_message)
        return '-'
    error_message_short.short_description = _('Error Message')
