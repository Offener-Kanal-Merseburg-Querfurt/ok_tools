"""Admin interface for media files."""

import logging
import os
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django import forms
from django.contrib import admin
from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from rangefilter.filters import DateRangeFilter

from .models import StorageLocation, VideoFile, FileOperation, MediaFilesConfig, CoverTemplate, CoverOverlay, CoverOverlayRule, POSITION_PRESET_CHOICES
from .utils import verify_file_integrity, extract_video_metadata, extract_video_metadata_fast, extract_number_from_filename, calculate_checksum, copy_file_with_progress, copy_video_to_playout
from media_files.management.commands.render_video_preset import _apply_metadata
from media_files.rendering.ffmpeg import (
    FfmpegError,
    render_with_intro_outro,
    render_with_overlays_on_main_edges,
    render_preview_overlays_on_main_edges,
)
from tools.rendering.presets import load_encode_preset, load_style_preset, resolve_preset_asset_path
from media_files.rendering.templates import build_template_context


logger = logging.getLogger('django')

def _is_archive_protected() -> bool:
    """Return True if ARCHIVE deletion protection is enabled (DB config with env fallback)."""
    try:
        from media_files.config import get_video_archive_protected
        return bool(get_video_archive_protected())
    except Exception:
        return bool(getattr(settings, 'VIDEO_ARCHIVE_PROTECTED', True))


def _admin_archive_cleanup_preview_page(title: str, rows: list) -> HttpResponse:
    """Render a simple HTML preview page for archive cleanup."""
    # rows: list of dicts {number, keep, delete[]}
    def esc(s):
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    html = [
        "<html><head><meta charset='utf-8' />",
        f"<title>{esc(title)}</title>",
        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; padding:16px}"
        "table{border-collapse:collapse; width:100%}"
        "th,td{border:1px solid #ddd; padding:8px; vertical-align:top}"
        "th{background:#f6f6f6; text-align:left}"
        ".keep{color:#17a2b8; font-weight:700}"
        ".del{color:#dc3545}"
        ".muted{color:#666}"
        "</style></head><body>",
        f"<h2>{esc(title)}</h2>",
        "<p class='muted'>This is a preview only. No files were deleted.</p>",
        "<table>",
        "<tr><th>Number</th><th>Keep</th><th>Delete</th></tr>",
    ]

    for r in rows:
        deletes = "<br/>".join([esc(x) for x in r.get("delete", [])]) or "—"
        html.append(
            "<tr>"
            f"<td><strong>{esc(r['number'])}</strong></td>"
            f"<td class='keep'>{esc(r['keep'])}</td>"
            f"<td class='del'>{deletes}</td>"
            "</tr>"
        )

    html.extend(["</table></body></html>"])
    return HttpResponse("".join(html))


def _archive_version_sort_key(v):
    """Sort key for choosing which ARCHIVE version to keep."""
    from datetime import datetime
    created = v.created_at or v.last_scanned or v.updated_at
    if created is None:
        created = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        bool(getattr(v, 'is_manual_primary', False)),
        bool(getattr(v, 'is_available', True)),
        v.total_bitrate or 0,
        created,
    )


def _archive_newest_sort_key(v):
    """Sort key for choosing newest ARCHIVE version to keep."""
    from datetime import datetime
    created = v.created_at or v.last_scanned or v.updated_at
    if created is None:
        created = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        bool(getattr(v, 'is_manual_primary', False)),
        bool(getattr(v, 'is_available', True)),
        created,
    )


def _archive_largest_sort_key(v):
    """Sort key for choosing largest ARCHIVE file to keep."""
    from datetime import datetime
    created = v.created_at or v.last_scanned or v.updated_at
    if created is None:
        created = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        bool(getattr(v, 'is_manual_primary', False)),
        bool(getattr(v, 'is_available', True)),
        v.file_size or 0,
        v.total_bitrate or 0,
        created,
    )


class ForceArchiveDeleteConfirmForm(forms.Form):
    """Confirmation form for destructive ARCHIVE operations."""

    confirmation_phrase = forms.CharField(
        label=_('Confirmation phrase'),
        help_text=_('Type the exact confirmation phrase to proceed.'),
        required=True,
    )
    password = forms.CharField(
        label=_('Your password'),
        widget=forms.PasswordInput(render_value=False),
        required=True,
    )

    def __init__(self, *args, user=None, required_phrase=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        self._required_phrase = required_phrase or ''

    def clean_confirmation_phrase(self):
        phrase = (self.cleaned_data.get('confirmation_phrase') or '').strip()
        if phrase != (self._required_phrase or ''):
            raise forms.ValidationError(_('Confirmation phrase does not match.'))
        return phrase

    def clean_password(self):
        pwd = self.cleaned_data.get('password') or ''
        if not self._user or not hasattr(self._user, 'check_password'):
            raise forms.ValidationError(_('Cannot validate password for current user.'))
        if not self._user.check_password(pwd):
            raise forms.ValidationError(_('Incorrect password.'))
        return pwd

class VideoFileAdminForm(forms.ModelForm):
    """Form for adding/editing video files with file upload support."""
    
    uploaded_file = forms.FileField(
        required=False,
        label=_('Upload Video File'),
        help_text=_('Upload a video file (mp4, mov, mpeg, mpg). The file will be saved to the selected storage location.')
    )
    
    file_path_manual = forms.CharField(
        required=False,
        label=_('Or specify file path'),
        help_text=_('Full path to existing video file on the server'),
        widget=forms.TextInput(attrs={'size': '80'})
    )
    
    class Meta:
        model = VideoFile
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # If editing existing file, hide upload fields
        if self.instance and self.instance.pk:
            self.fields['uploaded_file'].widget = forms.HiddenInput()
            self.fields['file_path_manual'].widget = forms.HiddenInput()
            if 'storage_location' in self.fields:
                self.fields['storage_location'].disabled = True
    
    def clean(self):
        cleaned_data = super().clean()
        uploaded_file = cleaned_data.get('uploaded_file')
        file_path_manual = cleaned_data.get('file_path_manual')
        storage_location = cleaned_data.get('storage_location')
        
        # For new files, require either upload or path
        if not self.instance.pk:
            if not uploaded_file and not file_path_manual:
                raise forms.ValidationError(
                    _('Please either upload a file or specify an existing file path.')
                )
            
            if uploaded_file and file_path_manual:
                raise forms.ValidationError(
                    _('Please provide only one: either upload a file OR specify a path.')
                )
            
            if not storage_location:
                raise forms.ValidationError(_('Storage location is required.'))
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Only process new files
        if not instance.pk:
            from django.utils import timezone
            
            uploaded_file = self.cleaned_data.get('uploaded_file')
            file_path_manual = self.cleaned_data.get('file_path_manual')
            storage_location = self.cleaned_data.get('storage_location')
            
            if uploaded_file:
                # Handle uploaded file
                filename = uploaded_file.name
                
                # Extract number from filename
                number = extract_number_from_filename(filename)
                if not number:
                    raise forms.ValidationError(
                        _('Filename must start with a number (e.g., 12345_title.mp4)')
                    )
                
                # Save file to storage location
                file_path = os.path.join(storage_location.path, filename)
                
                # Check if file already exists
                if os.path.exists(file_path):
                    raise forms.ValidationError(
                        _('File already exists at: {}').format(file_path)
                    )
                
                # Save uploaded file
                with open(file_path, 'wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
                
                # Set instance fields
                instance.number = number
                instance.filename = filename
                instance.file_path = filename
                instance.storage_location = storage_location
                instance.is_available = True
                
                # Extract metadata
                try:
                    metadata = extract_video_metadata_fast(file_path)
                    instance.format = metadata.get('format', '')
                    instance.duration = metadata.get('duration')
                    instance.file_size = os.path.getsize(file_path)
                    
                    instance.has_video = metadata.get('has_video', False)
                    if instance.has_video:
                        instance.video_codec = metadata.get('video_codec', '')
                        instance.fps = metadata.get('fps')
                        instance.width = metadata.get('width')
                        instance.height = metadata.get('height')
                    
                    instance.has_audio = metadata.get('has_audio', False)
                    if instance.has_audio:
                        instance.audio_codec = metadata.get('audio_codec', '')
                        instance.audio_channels = metadata.get('audio_channels')
                    
                    instance.total_bitrate = metadata.get('total_bitrate')
                    
                    # Calculate checksum
                    instance.checksum = calculate_checksum(file_path)
                    
                except Exception as e:
                    logger.error(f'Error extracting metadata: {str(e)}')
                    # Continue without metadata
                
                instance.last_scanned = timezone.now()
                
            elif file_path_manual:
                # Handle manual file path
                if not os.path.exists(file_path_manual):
                    raise forms.ValidationError(
                        _('File does not exist: {}').format(file_path_manual)
                    )
                
                if not os.path.isfile(file_path_manual):
                    raise forms.ValidationError(
                        _('Path is not a file: {}').format(file_path_manual)
                    )
                
                filename = os.path.basename(file_path_manual)
                
                # Extract number
                number = extract_number_from_filename(filename)
                if not number:
                    raise forms.ValidationError(
                        _('Filename must start with a number (e.g., 12345_title.mp4)')
                    )
                
                # Calculate relative path
                storage_path = storage_location.path.rstrip('/')
                if not file_path_manual.startswith(storage_path):
                    raise forms.ValidationError(
                        _('File must be within storage location: {}').format(storage_path)
                    )
                
                relative_path = file_path_manual[len(storage_path):].lstrip('/')
                
                # Set instance fields
                instance.number = number
                instance.filename = filename
                instance.file_path = relative_path
                instance.storage_location = storage_location
                instance.is_available = True
                
                # Extract metadata
                try:
                    metadata = extract_video_metadata_fast(file_path_manual)
                    instance.format = metadata.get('format', '')
                    instance.duration = metadata.get('duration')
                    instance.file_size = os.path.getsize(file_path_manual)
                    
                    instance.has_video = metadata.get('has_video', False)
                    if instance.has_video:
                        instance.video_codec = metadata.get('video_codec', '')
                        instance.fps = metadata.get('fps')
                        instance.width = metadata.get('width')
                        instance.height = metadata.get('height')
                    
                    instance.has_audio = metadata.get('has_audio', False)
                    if instance.has_audio:
                        instance.audio_codec = metadata.get('audio_codec', '')
                        instance.audio_channels = metadata.get('audio_channels')
                    
                    instance.total_bitrate = metadata.get('total_bitrate')
                    
                    # Calculate checksum
                    instance.checksum = calculate_checksum(file_path_manual)
                    
                except Exception as e:
                    logger.error(f'Error extracting metadata: {str(e)}')
                
                instance.last_scanned = timezone.now()
        
        if commit:
            instance.save()
        
        return instance


class FileOperationInline(admin.TabularInline):
    """Inline admin for file operations history."""

    model = FileOperation
    extra = 0
    can_delete = False
    readonly_fields = [
        'operation_type', 'source_location', 'destination_location',
        'performed_by', 'performed_at', 'status', 'error_message'
    ]
    fields = readonly_fields
    classes = ('collapse',)  # Collapsed by default
    
    def has_add_permission(self, request, obj=None):
        """Disable add permission."""
        return False


@admin.register(StorageLocation)
class StorageLocationAdmin(admin.ModelAdmin):
    """Admin interface for storage locations."""

    list_display = [
        'name', 'storage_type', 'path', 'is_active',
        'scan_enabled', 'video_count_display', 'read_health_display', 'updated_at'
    ]
    list_filter = ['storage_type', 'is_active', 'scan_enabled']
    search_fields = ['name', 'path']
    readonly_fields = [
        'created_at', 'updated_at', 'video_count_info',
        'last_health_check', 'last_read_mbps',
    ]
    change_list_template = 'admin/media_files/storagelocation/change_list.html'
    delete_confirmation_template = 'admin/media_files/storagelocation/delete_confirmation.html'
    
    fieldsets = (
        (None, {
            'fields': ('name', 'storage_type', 'path', 'unc_path', 'is_active')
        }),
        (_('Scanning'), {
            'fields': ('scan_enabled', 'scan_schedule')
        }),
        (_('Read health'), {
            'fields': ('last_read_mbps', 'last_health_check'),
            'description': _(
                'Measured by the hourly auto-scan and by every export that reads '
                'from this location. A location that reads too slowly is skipped '
                'as an export source in favour of an identical copy elsewhere.'
            ),
        }),
        (_('Information'), {
            'fields': ('video_count_info', 'created_at', 'updated_at')
        }),
    )
    
    actions = ['scan_storage', 'test_connection']

    def read_health_display(self, obj):
        """Show the last measured read speed, colour-coded."""
        from media_files.storage_health import health_state

        if not obj.last_health_check:
            return format_html('<span style="color:#999;">{}</span>', _('not measured'))
        state = health_state(obj)
        if state is None:
            label = _('stale')
            colour = '#999'
        elif state:
            label = f'{obj.last_read_mbps:.1f} MB/s'
            colour = '#2e7d32'
        else:
            label = (f'{obj.last_read_mbps:.2f} MB/s'
                     if obj.last_read_mbps is not None else _('no response'))
            colour = '#ba2121'
        return format_html('<span style="color:{};">{}</span>', colour, label)
    read_health_display.short_description = _('Read speed')
    
    def get_urls(self):
        """Add custom URLs for storage management."""
        urls = super().get_urls()
        from django.urls import path
        custom_urls = [
            path(
                '<int:storage_id>/scan/',
                self.admin_site.admin_view(self.scan_storage_view),
                name='media_files_storagelocation_scan',
            ),
            path(
                '<int:storage_id>/scan-options/',
                self.admin_site.admin_view(self.scan_storage_options_view),
                name='media_files_storagelocation_scan_options',
            ),
        ]
        return custom_urls + urls
    
    def video_count_info(self, obj):
        """Display video count in fieldsets."""
        return obj.video_count
    video_count_info.short_description = _('Video count')
    
    def video_count_display(self, obj):
        """Display video count with link and scan button."""
        count = obj.video_count
        scan_url = reverse('admin:media_files_storagelocation_scan_options', args=[obj.id])
        
        if count > 0:
            list_url = reverse('admin:media_files_videofile_changelist') + f'?storage_location__id__exact={obj.id}'
            return format_html(
                '<a href="{}">{}</a> | <button type="button" onclick="openScanModal({}, \'{}\', \'{}\', \'{}\', {})" class="button" style="padding: 3px 10px; margin-left: 5px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg> Scan</button>',
                list_url, count, obj.id, obj.name, obj.path, obj.storage_type, obj.video_count
            )
        return format_html(
            '{} | <button type="button" onclick="openScanModal({}, \'{}\', \'{}\', \'{}\', {})" class="button" style="padding: 3px 10px; margin-left: 5px;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg> Scan</button>',
            count, obj.id, obj.name, obj.path, obj.storage_type, obj.video_count
        )
    video_count_display.short_description = _('Videos')
    
    def scan_storage_view(self, request, storage_id):
        """View to scan a single storage location via Celery task."""
        from django.shortcuts import redirect
        from django.contrib import messages
        from django.http import JsonResponse
        from django.urls import reverse
        from django.utils.html import format_html
        
        from media_files.tasks import run_scan_video_storage_task
        
        try:
            storage = StorageLocation.objects.get(id=storage_id)
            
            # Get scan options from request parameters (both GET and POST)
            scan_options = {'storage_id': storage_id}
            if request.GET.get('force') or request.POST.get('force'):
                scan_options['force'] = True
            if request.GET.get('strict_check') or request.POST.get('strict_check'):
                scan_options['strict_check'] = True
            if request.GET.get('skip_metadata') or request.POST.get('skip_metadata'):
                scan_options['skip_metadata'] = True
            if request.GET.get('calculate_checksum') or request.POST.get('calculate_checksum'):
                scan_options['calculate_checksum'] = True
            if request.GET.get('delete_missing') or request.POST.get('delete_missing'):
                scan_options['delete_missing'] = True
            
            # Update storage updated_at to show scan was initiated
            # The date will be updated again when task completes
            storage.updated_at = timezone.now()
            storage.save(update_fields=['updated_at'])
            
            # Queue Celery task
            task = run_scan_video_storage_task.delay(**scan_options)
            
            # Create link to task results
            task_results_url = reverse('admin:django_celery_results_taskresult_changelist')
            task_results_url += f'?task_id__exact={task.id}'
            
            success_message = format_html(
                '<svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> {}: {}<br>{}: <strong>{}</strong><br>'
                '<a href="{}" target="_blank">{} →</a>',
                _("Scan task queued successfully"),
                storage.name,
                _("Task ID"),
                task.id,
                _("The scan is running in the background. Check task results for progress."),
                task_results_url,
                _("View Task Results")
            )
            
            # If it's an AJAX request, return JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.method == 'POST':
                return JsonResponse({
                    'success': True,
                    'message': str(success_message),
                    'task_id': task.id,
                    'task_results_url': task_results_url
                })
            
            # Otherwise, redirect with message
            messages.success(request, success_message)
            
        except StorageLocation.DoesNotExist:
            error_message = _('Storage location #{} not found').format(storage_id)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.method == 'POST':
                return JsonResponse({'success': False, 'message': error_message})
            messages.error(request, error_message)
        except Exception as e:
            error_message = _('Error queueing scan task: {}').format(str(e))
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.method == 'POST':
                return JsonResponse({'success': False, 'message': error_message})
            messages.error(request, error_message)
        
        return redirect('admin:media_files_storagelocation_changelist')
    
    def scan_storage_options_view(self, request, storage_id):
        """View to show scan options for a storage location."""
        from django.shortcuts import render
        from django.contrib import messages
        
        try:
            storage = StorageLocation.objects.get(id=storage_id)
        except StorageLocation.DoesNotExist:
            messages.error(request, _('Storage location #{} not found').format(storage_id))
            return redirect('admin:media_files_storagelocation_changelist')
        
        if request.method == 'POST':
            # Process scan with options
            scan_options = {}
            if request.POST.get('force'):
                scan_options['force'] = True
            if request.POST.get('strict_check'):
                scan_options['strict_check'] = True
            if request.POST.get('skip_metadata'):
                scan_options['skip_metadata'] = True
            if request.POST.get('calculate_checksum'):
                scan_options['calculate_checksum'] = True
            if request.POST.get('delete_missing'):
                scan_options['delete_missing'] = True
            
            # Redirect to scan with options as GET parameters
            from django.urls import reverse
            from urllib.parse import urlencode
            scan_url = reverse('admin:media_files_storagelocation_scan', args=[storage_id])
            if scan_options:
                scan_url += '?' + urlencode(scan_options)
            return redirect(scan_url)
        
        context = {
            'storage': storage,
            'title': _('Scan Options - {}').format(storage.name),
            'site_header': self.admin_site.site_header,
            'site_title': self.admin_site.site_title,
        }
        return render(request, 'admin/media_files/storagelocation/scan_options.html', context)
    
    def scan_storage(self, request, queryset):
        """Action to scan selected storage locations via Celery tasks."""
        from django.urls import reverse
        from django.utils.html import format_html
        
        from media_files.tasks import run_scan_video_storage_task
        
        task_ids = []
        for storage in queryset:
            try:
                task = run_scan_video_storage_task.delay(storage_id=storage.id)
                task_ids.append((storage.name, task.id))
            except Exception as e:
                self.message_user(
                    request,
                    _('Error queueing scan task for {}: {}').format(storage.name, str(e)),
                    level='error'
                )
        
        if task_ids:
            # Create links to task results and build HTML structure
            links_html_parts = []
            for storage_name, task_id in task_ids:
                task_results_url = reverse('admin:django_celery_results_taskresult_changelist')
                task_results_url += f'?task_id__exact={task_id}'
                link_html = format_html(
                    '<a href="{}" target="_blank">{} (Task: {})</a>',
                    task_results_url,
                    storage_name,
                    task_id[:8]  # Show first 8 chars of task ID
                )
                links_html_parts.append(link_html)
            
            # Build complete message - format_html handles SafeString properly
            # Create a template with placeholders for each link
            links_template = '<br>'.join(['{}'] * len(links_html_parts))
            links_combined = format_html(links_template, *links_html_parts)
            
            message = format_html(
                '<svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> {} {} {}<br>{}',
                _("Scan tasks queued for"),
                len(task_ids),
                _("storage location(s)"),
                links_combined
            )
            self.message_user(request, message)
    scan_storage.short_description = _('Scan selected storage locations')
    
    def test_connection(self, request, queryset):
        """Action to test connection to storage."""
        import os
        
        for storage in queryset:
            if os.path.exists(storage.path) and os.path.isdir(storage.path):
                self.message_user(request, f'<svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> {storage.name}: Connection OK')
            else:
                self.message_user(
                    request,
                    f'<svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg> {storage.name}: Cannot access path',
                    level='error'
                )
    test_connection.short_description = _('Test connection to storage')


class HasDuplicatesFilter(admin.SimpleListFilter):
    title = _('Has Duplicates')
    parameter_name = 'has_duplicates'
    
    def lookups(self, request, model_admin):
        return (
            ('yes', _('Yes - has duplicates')),
            ('no', _('No - unique')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'yes':
            # Videos that have other versions with same number
            from django.db.models import Count
            duplicated_numbers = VideoFile.objects.values('number').annotate(
                count=Count('number')
            ).filter(count__gt=1).values_list('number', flat=True)
            return queryset.filter(number__in=duplicated_numbers)
        
        if self.value() == 'no':
            # Videos that are unique (no other versions)
            from django.db.models import Count
            unique_numbers = VideoFile.objects.values('number').annotate(
                count=Count('number')
            ).filter(count=1).values_list('number', flat=True)
            return queryset.filter(number__in=unique_numbers)


class IsPrimaryVersionFilter(admin.SimpleListFilter):
    title = _('Version Type')
    parameter_name = 'is_primary'
    
    def lookups(self, request, model_admin):
        return (
            ('primary', _('Primary versions')),
            ('duplicate', _('Duplicate versions')),
        )
    
    def queryset(self, request, queryset):
        from django.db.models import Case, When, IntegerField, Max, OuterRef, Subquery, F, Value, Count
        from django.utils import timezone
        from datetime import datetime
        
        if not self.value():
            return queryset
        
        # Find numbers that have more than one full version (preview clips do not count)
        duplicated_numbers = VideoFile.objects.exclude(
            is_preview=True
        ).values('number').annotate(
            count=Count('number')
        ).filter(count__gt=1).values_list('number', flat=True)
        
        if not duplicated_numbers:
            # No duplicates, so all are primary
            if self.value() == 'primary':
                return queryset
            else:
                return queryset.none()
        
        # Filter to only videos with duplicates
        queryset = queryset.filter(number__in=duplicated_numbers)
        
        # Use Python-based approach for reliability (works correctly with complex queries)
        # Don't use SQL annotations that can cause integer overflow - calculate everything in Python
        # Get all videos with duplicates and determine primary in memory
        try:
            # Load videos without any complex annotations to avoid integer overflow
            videos_list = list(queryset.select_related('storage_location').only(
                'id', 'number', 'total_bitrate', 'created_at', 'last_scanned', 'updated_at',
                'storage_location__storage_type', 'is_manual_primary', 'is_preview'
            ))
        except Exception as e:
            logger.error(f'Error loading videos for IsPrimaryVersionFilter: {e}')
            # Fallback: return empty queryset to avoid 500 error
            return queryset.none()
        
        # Group by number and find primary for each group
        by_number = {}
        for video in videos_list:
            if video.number not in by_number:
                by_number[video.number] = []
            by_number[video.number].append(video)
        
        # Determine primary versions
        primary_ids = set()
        duplicate_ids = set()
        
        storage_priority_map = {'ARCHIVE': 3, 'PLAYOUT': 2, 'CUSTOM': 1}
        
        for number, video_list in by_number.items():
            try:
                # Only full versions participate in primary/duplicate; exclude preview clips
                video_list = [v for v in video_list if not getattr(v, 'is_preview', False)]
                if not video_list:
                    continue
                # Check if any version is manually marked as primary
                manual_primary = next((v for v in video_list if getattr(v, 'is_manual_primary', False)), None)
                if manual_primary:
                    primary_ids.add(manual_primary.id)
                    duplicate_ids.update(v.id for v in video_list if v.id != manual_primary.id)
                    continue
                
                # Find best version with safe handling of None values
                def get_sort_key(v):
                    # Safely get storage type
                    storage_type = 'CUSTOM'
                    if v.storage_location and hasattr(v.storage_location, 'storage_type'):
                        storage_type = v.storage_location.storage_type or 'CUSTOM'
                    
                    # Prefer available files
                    available = bool(getattr(v, 'is_available', True))
                    
                    # Prefer higher quality (bitrate + storage type)
                    priority = storage_priority_map.get(storage_type, 1)
                    bitrate = v.total_bitrate if v.total_bitrate is not None else 0
                    quality = (priority * 1_000_000_000) + bitrate
                    
                    date = v.created_at or v.last_scanned or v.updated_at
                    if date is None:
                        date = datetime(1970, 1, 1, tzinfo=timezone.utc)
                    
                    # For CUSTOM storage: prefer newer versions if bitrate is acceptable
                    all_custom = all(
                        (vid.storage_location and 
                         getattr(vid.storage_location, 'storage_type', None) == 'CUSTOM')
                        for vid in video_list
                    )
                    
                    if all_custom:
                        max_bitrate = max((vid.total_bitrate or 0 for vid in video_list), default=0)
                        if max_bitrate > 0 and bitrate >= max_bitrate * 0.8:
                            # Newer version with acceptable quality becomes primary
                            return (available, date, quality)
                    
                    # Default: quality first, then recency
                    return (available, quality, date)
                
                best_video = max(video_list, key=get_sort_key)
                primary_ids.add(best_video.id)
                duplicate_ids.update(v.id for v in video_list if v.id != best_video.id)
            except Exception as e:
                logger.error(f'Error determining primary version for number {number}: {e}')
                # If we can't determine, mark all as duplicates (safer than failing)
                duplicate_ids.update(v.id for v in video_list)
        
        # Filter based on selection
        if self.value() == 'primary':
            if primary_ids:
                return queryset.filter(id__in=primary_ids)
            else:
                return queryset.none()
        
        if self.value() == 'duplicate':
            if duplicate_ids:
                return queryset.filter(id__in=duplicate_ids)
            else:
                return queryset.none()
        
        return queryset


class ArchiveCleanupFilter(admin.SimpleListFilter):
    title = _('Archive Cleanup')
    parameter_name = 'archive_cleanup'

    def lookups(self, request, model_admin):
        return (
            ('archive_primary', _('Archive primary (keep)')),
            ('archive_duplicate', _('Archive duplicates')),
        )

    def queryset(self, request, queryset):
        from django.db.models import Count
        from django.utils import timezone
        from datetime import datetime

        if not self.value():
            return queryset

        archive_qs = queryset.filter(storage_location__storage_type='ARCHIVE')

        duplicated_numbers = archive_qs.values('number').annotate(
            count=Count('id')
        ).filter(count__gt=1).values_list('number', flat=True)

        if not duplicated_numbers:
            return archive_qs.none()

        videos_list = list(
            archive_qs.filter(number__in=duplicated_numbers)
            .select_related('storage_location')
            .only(
                'id', 'number', 'total_bitrate', 'created_at', 'last_scanned', 'updated_at',
                'is_manual_primary', 'is_available', 'storage_location__storage_type'
            )
        )

        by_number = {}
        for v in videos_list:
            by_number.setdefault(v.number, []).append(v)

        keep_ids = set()
        drop_ids = set()

        def get_sort_key(v):
            return _archive_version_sort_key(v)

        for number, versions in by_number.items():
            best = max(versions, key=get_sort_key)
            keep_ids.add(best.id)
            drop_ids.update(v.id for v in versions if v.id != best.id)

        if self.value() == 'archive_primary':
            return archive_qs.filter(id__in=keep_ids)

        if self.value() == 'archive_duplicate':
            return archive_qs.filter(id__in=drop_ids)

        return archive_qs


class FPSFilter(admin.SimpleListFilter):
    title = _('FPS')
    parameter_name = 'fps'
    
    def lookups(self, request, model_admin):
        return (
            ('25', _('25 fps (Broadcast Standard)')),
            ('not_25', _('Not 25 fps (Warning)')),
            ('missing', _('FPS not set')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == '25':
            return queryset.filter(fps=25.0)
        elif self.value() == 'not_25':
            return queryset.exclude(fps=25.0).exclude(fps__isnull=True)
        elif self.value() == 'missing':
            return queryset.filter(fps__isnull=True)
        return queryset


@admin.register(VideoFile)
class VideoFileAdmin(admin.ModelAdmin):
    """Admin interface for video files."""

    form = VideoFileAdminForm
    change_form_template = 'admin/media_files/videofile/change_form.html'
    change_list_template = 'admin/media_files/videofile/change_list.html'
    delete_selected_confirmation_template = 'admin/media_files/videofile/delete_selected_confirmation.html'
    
    list_display = [
        'duplicates_indicator', 'filename', 'storage_location', 'number', 'resolution_display',
        'duration_display', 'fps_display', 'file_size_display', 'format',
        'is_available', 'player_link'
    ]
    list_filter = [
        'storage_location', 'format', 'is_available', 'is_preview',
        ('created_at', DateRangeFilter),
        'has_video', 'has_audio',
        ArchiveCleanupFilter, HasDuplicatesFilter, IsPrimaryVersionFilter, FPSFilter
    ]
    
    def get_rangefilter_created_at_title(self, request, field_path):
        """Set a custom filter name for created_at DateRangeFilter."""
        return _('Created at')
    
    search_fields = ['number', 'filename', 'video_codec', 'audio_codec']
    def get_readonly_fields(self, request, obj=None):
        """Make fields editable when adding new video."""
        if obj:  # Editing existing object
            return [
                'number', 'filename', 'storage_location', 'file_path',
                'file_size', 'file_size_mb', 'duration', 'format',
                'last_scanned', 'last_modified', 'checksum',
                'video_codec', 'video_codec_long', 'video_profile',
                'video_bitrate', 'video_bitrate_display', 'video_bitrate_mode', 'fps',
                'width', 'height', 'resolution_display', 'aspect_ratio',
                'pixel_format', 'color_space', 'color_range', 'chroma_subsampling',
                'audio_codec', 'audio_codec_long', 'audio_bitrate', 'audio_bitrate_display',
                'audio_sample_rate', 'audio_channels', 'audio_channel_layout',
                'has_video', 'has_audio', 'total_bitrate', 'bitrate_mbps',
                'license_link', 'is_preview', 'video_player', 'duplicate_status_display', 'all_versions_display', 'created_at', 'updated_at'
            ]
        else:  # Adding new object
            return []
    
    def get_fieldsets(self, request, obj=None):
        """Show different fields when adding vs editing."""
        if obj:  # Editing existing object
            return (
                (_('Basic Information'), {
                    'fields': (
                        'number', 'filename', 'storage_location', 'file_path',
                        'license_link', 'is_available', 'is_preview'
                    )
                }),
                (_('Video Player'), {
                    'fields': ('video_player',)
                }),
                (_('File Properties'), {
                    'fields': (
                        'format', 'file_size_mb', 'duration',
                        'checksum', 'last_modified', 'last_scanned'
                    )
                }),
                (_('Video Properties'), {
                    'fields': (
                        'has_video', 'video_codec', 'video_codec_long', 'video_profile',
                        'video_bitrate_display', 'video_bitrate_mode', 'fps',
                        'width', 'height', 'resolution_display', 'aspect_ratio',
                        'pixel_format', 'color_space', 'color_range', 'chroma_subsampling',
                        'bitrate_mbps'
                    )
                }),
                (_('Audio Properties'), {
                    'fields': (
                        'has_audio', 'audio_codec', 'audio_codec_long', 'audio_bitrate_display',
                        'audio_sample_rate', 'audio_channels', 'audio_channel_layout'
                    )
                }),
                (_('Duplicate Management'), {
                    'fields': ('duplicate_status_display', 'all_versions_display'),
                    'classes': ('collapse',),
                }),
                (_('Timestamps'), {
                    'fields': ('created_at', 'updated_at'),
                    'classes': ('collapse',)
                }),
            )
        else:  # Adding new object
            return (
                (_('Add Video File'), {
                    'fields': ('storage_location', 'uploaded_file', 'file_path_manual', 'is_available'),
                    'description': _(
                        'Choose a storage location, then either:<br>'
                        '• <strong>Upload a file</strong> - File will be saved to the storage location<br>'
                        '• <strong>Specify a path</strong> - Reference an existing file on the server<br><br>'
                        '<strong>Important:</strong> Filename must start with a number (e.g., 12345_title.mp4)'
                    )
                }),
            )
    
    inlines = [FileOperationInline]
    actions = ['copy_to_playout_action', 'update_metadata_action', 'verify_integrity_action', 
               'mark_as_primary_action', 'delete_duplicates_action', 'move_to_archive_action',
               'cleanup_missing_files_action', 'render_default_preset_action', 'render_preview_default_action',
               'delete_records_without_video_action', 'render_with_intro_outro_full_overlays_action',
               'transcode_hevc_to_h264_action',
               # Archive cleanup actions
               'preview_archive_duplicates_action',
               'preview_archive_duplicates_keep_newest_action',
               'preview_archive_duplicates_keep_largest_action',
               'delete_archive_duplicates_action',
               'delete_archive_duplicates_keep_newest_action',
               'delete_archive_duplicates_keep_largest_action',
               'force_delete_archive_duplicates_keep_best_action',
               'force_delete_archive_duplicates_keep_newest_action',
               'force_delete_archive_duplicates_keep_largest_action']

    def get_actions(self, request):
        """Hide rendering actions when the feature flag is disabled."""
        actions = super().get_actions(request)
        from media_files.config import get_video_overlay_rendering_enabled
        if not get_video_overlay_rendering_enabled() or not getattr(settings, "TOOLS_ENABLED", False):
            actions.pop("render_default_preset_action", None)
            actions.pop("render_preview_default_action", None)
            actions.pop("render_with_intro_outro_full_overlays_action", None)
        return actions

    @admin.action(description=_('Transcode HEVC to H.264 (browser compatible)'))
    def transcode_hevc_to_h264_action(self, request, queryset):
        """
        Transcode selected HEVC/H.265 videos to H.264 for browser compatibility.
        
        This creates a new H.264 version of the video while keeping the original.
        Uses Celery for async processing.
        """
        from media_files.tasks import transcode_hevc_to_h264
        
        queued = 0
        skipped = 0
        
        for video in queryset:
            # Check if video needs transcoding
            if video.is_browser_compatible:
                skipped += 1
                continue
            
            # Queue transcode task
            transcode_hevc_to_h264.delay(
                video_id=video.id,
                user_id=request.user.id,
            )
            queued += 1
        
        if queued > 0:
            self.message_user(
                request,
                _('Queued {count} video(s) for HEVC→H.264 transcoding. Check File Operations for progress.').format(
                    count=queued
                ),
                level=messages.SUCCESS,
            )
        
        if skipped > 0:
            self.message_user(
                request,
                _('Skipped {count} video(s) - already browser compatible.').format(count=skipped),
                level=messages.INFO,
            )

    @admin.action(description=_('Render video (default presets)'))
    def render_default_preset_action(self, request, queryset):
        from media_files.config import get_render_encode_preset
        encode_name = get_render_encode_preset()

        try:
            encode = load_encode_preset(encode_name)
        except Exception as e:
            self.message_user(
                request,
                _("Failed to load encode preset: {err}").format(err=str(e)),
                level=messages.ERROR,
            )
            return

        rendered = 0
        failed = 0

        for source in queryset:
            logger.info(
                "Queuing plain encode for %s with encode=%s",
                source.full_path,
                encode.name,
            )

            storage_root = Path(source.storage_location.path)
            source_rel_path = Path(source.file_path)
            rel_dir = source_rel_path.parent
            src_stem = Path(source.filename).stem

            base_stem = src_stem
            base_suffix = ".mp4"

            def is_path_taken(candidate_rel: Path) -> bool:
                cand_str = str(candidate_rel).replace("\\", "/")
                if VideoFile.objects.filter(
                    storage_location=source.storage_location,
                    file_path=cand_str
                ).exists():
                    return True
                abs_candidate = storage_root / candidate_rel
                if abs_candidate.exists():
                    return True
                return False

            version = 1
            while version < 1000:
                candidate_name = f"{base_stem}_v{version}{base_suffix}"
                rel_out = rel_dir / candidate_name
                if not is_path_taken(rel_out):
                    break
                version += 1
            else:
                logger.error("Could not find a free output filename for %s (too many versions exist)", source.full_path)
                failed += 1
                continue

            abs_out = storage_root / rel_out
            abs_out.parent.mkdir(parents=True, exist_ok=True)

            new_video = VideoFile.objects.create(
                number=source.number,
                filename=abs_out.name,
                file_path=str(rel_out).replace("\\", "/"),
                storage_location=source.storage_location,
                is_available=False,
            )

            operation = FileOperation.objects.create(
                video_file=new_video,
                operation_type="RENDER",
                source_location=source.storage_location,
                destination_location=source.storage_location,
                performed_by=request.user,
                status="IN_PROGRESS",
                details={
                    "source_video_id": source.id,
                    "encode": encode.name,
                    "use_intro_outro": False,
                    "preview": False,
                    "plain_encode": True,
                    "elements": {},
                    "styles": {},
                    "overlay_texts": {},
                },
            )

            try:
                from media_files.tasks import render_video_task
                render_video_task.delay(operation.id)
                logger.info(
                    "Queued plain encode for %s (operation_id=%s)",
                    source.full_path,
                    operation.id,
                )
                rendered += 1
            except Exception as e:
                failed += 1
                new_video.is_available = False
                new_video.save(update_fields=["is_available"])
                operation.status = "FAILED"
                operation.error_message = str(e)
                operation.save(update_fields=["status", "error_message"])
                logger.error("Failed to queue plain encode for %s: %s", source.full_path, str(e))

        if rendered:
            self.message_user(
                request,
                _("Queued plain encoding: {n} video(s). Track progress in File Operations / Task Results.").format(n=rendered),
                level=messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                _("Failed to queue encoding: {n}").format(n=failed),
                level=messages.WARNING,
            )

    @admin.action(description=_('Render preview (10s)'))
    def render_preview_default_action(self, request, queryset):
        """
        Render a fast 10-second preview (5s start + 5s end) using default presets.

        Intended for quick visual verification of overlays.
        """
        from media_files.config import get_video_overlay_rendering_enabled
        if not get_video_overlay_rendering_enabled():
            self.message_user(
                request,
                _(
                    "Video overlay rendering is disabled. Set VIDEO_OVERLAY_RENDERING_ENABLED=true to enable it."
                ),
                level=messages.ERROR,
            )
            return

        style_name = "overlay_only_center_left_v1"
        from media_files.config import get_render_encode_preset
        encode_name = get_render_encode_preset()
        preview_seconds = 5.0

        try:
            style = load_style_preset(style_name)
            encode = load_encode_preset(encode_name)
        except Exception as e:
            self.message_user(
                request,
                _("Failed to load presets: {err}").format(err=str(e)),
                level=messages.ERROR,
            )
            return

        rendered = 0
        failed = 0

        for source in queryset:
            license_obj = source.get_license()
            if not license_obj:
                failed += 1
                continue

            storage_root = Path(source.storage_location.path)
            source_rel_path = Path(source.file_path)
            rel_dir = source_rel_path.parent  # Same directory as source
            src_stem = Path(source.filename).stem
            
            # Base filename with version suffix (_v1, _v2, etc.)
            # For preview, add _preview to the stem
            base_stem = f"{src_stem}_preview"
            base_suffix = ".mp4"
            
            def is_path_taken(candidate_rel: Path) -> bool:
                """Check if path is taken (exists in DB or filesystem)."""
                cand_str = str(candidate_rel).replace("\\", "/")
                # Check database
                if VideoFile.objects.filter(
                    storage_location=source.storage_location,
                    file_path=cand_str
                ).exists():
                    return True
                # Check filesystem
                abs_candidate = storage_root / candidate_rel
                if abs_candidate.exists():
                    return True
                return False
            
            # Find first available version starting from _v1
            version = 1
            while version < 1000:
                candidate_name = f"{base_stem}_v{version}{base_suffix}"
                rel_out = rel_dir / candidate_name
                if not is_path_taken(rel_out):
                    break
                version += 1
            else:
                logger.error("Could not find a free output filename for %s (too many versions exist)", source.full_path)
                failed += 1
                continue
            
            abs_out = storage_root / rel_out
            abs_out.parent.mkdir(parents=True, exist_ok=True)

            new_video = VideoFile.objects.create(
                number=source.number,
                filename=abs_out.name,
                file_path=str(rel_out).replace("\\", "/"),
                storage_location=source.storage_location,
                is_available=True,
                is_preview=True,
            )

            operation = FileOperation.objects.create(
                video_file=new_video,
                operation_type="RENDER",
                source_location=source.storage_location,
                destination_location=source.storage_location,
                performed_by=request.user,
                status="IN_PROGRESS",
                details={
                    "source_video_id": source.id,
                    "style": style.name,
                    "encode": encode.name,
                    "preview": True,
                    "preview_seconds": preview_seconds,
                },
            )

            try:
                logger.info(
                    "Rendering PREVIEW for %s with presets style=%s encode=%s",
                    source.full_path,
                    style.name,
                    encode.name,
                )
                ctx = build_template_context(license_obj)
                render_preview_overlays_on_main_edges(
                    main_video=source.full_path,
                    output_mp4=str(abs_out),
                    encode=encode,
                    intro_layers=style.intro_overlays,
                    outro_layers=style.outro_overlays,
                    ctx=ctx,
                    segment_duration=preview_seconds,
                )
                _apply_metadata(new_video, str(abs_out))
                new_video.save()
                operation.status = "SUCCESS"
                operation.save(update_fields=["status"])
                logger.info("Rendered preview output: %s (VideoFile id=%s)", str(abs_out), new_video.id)
                rendered += 1
            except FfmpegError as e:
                failed += 1
                new_video.is_available = False
                new_video.save(update_fields=["is_available"])
                operation.status = "FAILED"
                operation.error_message = str(e)
                operation.save(update_fields=["status", "error_message"])
                logger.error("Preview render failed for %s: %s", source.full_path, str(e))

        if rendered:
            self.message_user(
                request,
                _("Rendered successfully: {n}").format(n=rendered),
                level=messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                _("Failed: {n}").format(n=failed),
                level=messages.WARNING,
            )
    
    @admin.action(description=_('Delete selected records without video'))
    def delete_records_without_video_action(self, request, queryset):
        """
        Delete VideoFile records for selected entries where the video file does not exist on disk.
        
        Only deletes database records, not physical files. Checks if file exists before deletion.
        """
        from django.db import connection
        
        deleted_count = 0
        found_count = 0
        error_count = 0
        read_only_count = 0
        
        for video in queryset:
            try:
                # Check if file exists on disk (handle read-only storage gracefully)
                file_exists = False
                try:
                    file_exists = os.path.exists(video.full_path)
                    found_count += 1
                except (OSError, PermissionError, IOError) as e:
                    # Storage might be read-only - skip this file
                    read_only_count += 1
                    logger.debug(f'Could not check file existence for {video.full_path}: {e}')
                    continue
                except Exception as e:
                    # Any other error - log and skip
                    read_only_count += 1
                    logger.warning(f'Unexpected error checking file {video.full_path}: {e}')
                    continue
                
                if not file_exists:
                    # Delete related FileOperation objects using raw SQL
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "DELETE FROM media_files_fileoperation WHERE video_file_id = %s",
                                [video.id]
                            )
                    except Exception as e:
                        logger.error(f'Error deleting FileOperation for video {video.id}: {e}')
                        # Continue anyway - will be cascade deleted
                    
                    # Delete the VideoFile
                    video.delete()
                    deleted_count += 1
                    logger.info(f'Deleted VideoFile {video.number} (file missing): {video.filename}')
            
            except Exception as e:
                error_count += 1
                logger.error(f'Error checking/deleting {video.filename}: {str(e)}')
        
        if deleted_count > 0:
            self.message_user(
                request,
                _('Deleted {} record(s) without video files').format(deleted_count),
                level='success',
            )
        if read_only_count > 0:
            self.message_user(
                request,
                _('{} file(s) could not be checked (storage may be read-only)').format(read_only_count),
                level='info',
            )
        if found_count == 0:
            self.message_user(
                request,
                _('No files could be checked'),
                level='info',
            )
        elif deleted_count == 0 and read_only_count == 0:
            self.message_user(
                request,
                _('All checked files exist on disk'),
                level='info',
            )
        if error_count > 0:
            self.message_user(
                request,
                _('{} error(s) occurred').format(error_count),
                level='error',
            )

    @admin.action(description=_('Render with intro/outro and full overlays'))
    def render_with_intro_outro_full_overlays_action(self, request, queryset):
        """
        Render selected videos with intro/outro clips and full text overlays
        (title, subtitle, broadcast responsibility, media authority).
        
        Uses intro.mp4 and outro.mp4 from docker-local/data/media/intro_outro/
        and applies all text overlays to them.
        """
        from media_files.config import get_video_overlay_rendering_enabled
        if not get_video_overlay_rendering_enabled():
            self.message_user(
                request,
                _(
                    "Video overlay rendering is disabled. Set VIDEO_OVERLAY_RENDERING_ENABLED=true to enable it."
                ),
                level=messages.ERROR,
            )
            return

        from media_files.config import get_render_encode_preset
        encode_name = get_render_encode_preset()

        try:
            encode = load_encode_preset(encode_name)
        except Exception as e:
            self.message_user(
                request,
                _("Failed to load encode preset: {err}").format(err=str(e)),
                level=messages.ERROR,
            )
            return

        # Find intro and outro files
        # In production: ./data/media is mounted to /app/media
        # In local dev: docker-local/data/media is mounted to /app/media
        # Files should be placed in: <media_root>/intro_outro/intro.mp4 and outro.mp4
        
        media_root = Path(settings.MEDIA_ROOT)
        base_dir = Path(settings.BASE_DIR)
        
        # Build list of candidate paths in order of preference
        # 1. MEDIA_ROOT/intro_outro/ (works for both production and local)
        # 2. /app/media/intro_outro/ (Docker path - production and local)
        # 3. BASE_DIR relative paths (for local development)
        
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
        
        intro_path = None
        outro_path = None
        
        for candidate in intro_candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    intro_path = str(candidate.resolve())
                    logger.info(f"Found intro file at: {intro_path}")
                    break
            except (OSError, ValueError):
                continue
        
        for candidate in outro_candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    outro_path = str(candidate.resolve())
                    logger.info(f"Found outro file at: {outro_path}")
                    break
            except (OSError, ValueError):
                continue

        if not intro_path or not outro_path:
            missing = []
            if not intro_path:
                missing.append("intro.mp4")
            if not outro_path:
                missing.append("outro.mp4")
            
            # Provide helpful error message with correct paths for production and local
            media_root_str = str(media_root)
            error_msg = _(
                "Intro/outro files not found: {files}.\n\n"
                "Please place the files in one of these locations:\n"
                "- Production: <deployment_dir>/data/media/intro_outro/\n"
                "- Local dev: docker-local/data/media/intro_outro/\n"
                "- Or: {media_root}/intro_outro/\n\n"
                "Files will be accessible at /app/media/intro_outro/ inside the container."
            ).format(
                files=", ".join(missing),
                media_root=media_root_str
            )
            self.message_user(
                request,
                error_msg,
                level=messages.ERROR,
            )
            return

        # Create operations and start async rendering via Celery
        created = 0
        failed = 0

        for source in queryset:
            license_obj = source.get_license()
            if not license_obj:
                failed += 1
                continue

            try:
                storage_root = Path(source.storage_location.path)
                source_rel_path = Path(source.file_path)
                rel_dir = source_rel_path.parent  # Same directory as source
                src_stem = Path(source.filename).stem
                
                # Base filename with version suffix (_v1, _v2, etc.)
                base_stem = src_stem
                base_suffix = ".mp4"
                
                def is_path_taken(candidate_rel: Path) -> bool:
                    """Check if path is taken (exists in DB or filesystem)."""
                    cand_str = str(candidate_rel).replace("\\", "/")
                    # Check database
                    if VideoFile.objects.filter(
                        storage_location=source.storage_location,
                        file_path=cand_str
                    ).exists():
                        return True
                    # Check filesystem
                    abs_candidate = storage_root / candidate_rel
                    if abs_candidate.exists():
                        return True
                    return False
                
                # Find first available version starting from _v1
                version = 1
                while version < 1000:
                    candidate_name = f"{base_stem}_v{version}{base_suffix}"
                    rel_out = rel_dir / candidate_name
                    if not is_path_taken(rel_out):
                        break
                    version += 1
                else:
                    logger.error("Could not find a free output filename for %s (too many versions exist)", source.full_path)
                    failed += 1
                    continue
                
                abs_out = storage_root / rel_out
                abs_out.parent.mkdir(parents=True, exist_ok=True)

                new_video = VideoFile.objects.create(
                    number=source.number,
                    filename=abs_out.name,
                    file_path=str(rel_out).replace("\\", "/"),
                    storage_location=source.storage_location,
                    is_available=False,  # Will be set to True after rendering completes
                )

                operation = FileOperation.objects.create(
                    video_file=new_video,
                    operation_type="RENDER",
                    source_location=source.storage_location,
                    destination_location=source.storage_location,
                    performed_by=request.user,
                    status="IN_PROGRESS",
                    details={
                        "source_video_id": source.id,
                        "license_number": license_obj.number,
                        "encode": encode.name,
                        "intro_clip": intro_path,
                        "outro_clip": outro_path,
                        "overlay_type": "full_intro_outro",
                    },
                )

                # Start async rendering task via Celery
                from media_files.tasks import render_video_task
                render_video_task.delay(operation.id)
                
                logger.info(
                    "Started async rendering for video %s with intro/outro and full overlays (operation_id=%s)",
                    source.full_path,
                    operation.id,
                )
                created += 1
            except Exception as e:
                failed += 1
                logger.error("Failed to create operation for %s: %s", source.full_path, str(e))

        if created:
            self.message_user(
                request,
                _("Started rendering with intro/outro and full overlays: {n} video(s). You can track progress in File Operations.").format(n=created),
                level=messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                _("Failed to start rendering: {n}").format(n=failed),
                level=messages.WARNING,
            )
    
    def get_urls(self):
        """Add custom URLs."""
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:video_id>/stream/',
                self.admin_site.admin_view(self.stream_video),
                name='media_files_videofile_stream',
            ),
            path(
                '<int:video_id>/player/',
                self.admin_site.admin_view(self.video_player_page),
                name='media_files_videofile_player',
            ),
            path(
                'system-management/',
                self.admin_site.admin_view(system_management_view),
                name='media_files_system_management',
            ),
        ]
        return custom_urls + urls
    
    def file_size_display(self, obj):
        """Display file size in MB."""
        if obj.file_size_mb:
            return f"{obj.file_size_mb} MB"
        return "-"
    file_size_display.short_description = _('Size')
    
    def duration_display(self, obj):
        """Display duration without milliseconds."""
        if obj.duration:
            # Format duration as HH:MM:SS (without microseconds)
            total_seconds = int(obj.duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return "-"
    duration_display.short_description = _('Duration')
    
    def fps_display(self, obj):
        """Display FPS with warning if not 25."""
        if obj.fps is None:
            return mark_safe('<span style="color: #999;">—</span>')
        
        fps_value = float(obj.fps)
        fps_formatted = f"{fps_value:.2f}"
        
        if fps_value == 25.0:
            return format_html('<span style="color: #28a745;">{}</span>', fps_formatted)
        else:
            warning_text = _('FPS is not 25 - not suitable for broadcast')
            return format_html(
                '<span style="color: #dc3545; font-weight: bold;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> {}</span>',
                warning_text,
                fps_formatted
            )
    fps_display.short_description = _('FPS')
    
    def video_bitrate_display(self, obj):
        """Display video bitrate in kbps."""
        if obj.video_bitrate:
            kbps = obj.video_bitrate / 1000
            return f"{kbps:,.0f} kbps"
        return "-"
    video_bitrate_display.short_description = _('Video Bitrate (kbps)')
    
    def audio_bitrate_display(self, obj):
        """Display audio bitrate in kbps."""
        if obj.audio_bitrate:
            kbps = obj.audio_bitrate / 1000
            return f"{kbps:,.0f} kbps"
        return "-"
    audio_bitrate_display.short_description = _('Audio Bitrate (kbps)')
    
    def license_link(self, obj):
        """Display link to associated license."""
        license_obj = obj.get_license()
        if license_obj:
            url = reverse('admin:licenses_license_change', args=[license_obj.id])
            return format_html('<a href="{}">{} - {}</a>', url, license_obj.number, license_obj.title)
        return "-"
    license_link.short_description = _('License')
    
    def duplicates_indicator(self, obj):
        """Show duplicate status indicator with version info."""
        if not obj.pk:
            return '—'
        
        # Wrap main logic in try/except to prevent admin 500 errors
        try:
            if getattr(obj, 'is_preview', False):
                return format_html(
                    '<span style="color: #6c757d;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg> {}</span>',
                    _('Preview clip (not a version)'),
                )
            # Check for duplicates (same number, any storage; previews excluded by get_all_versions)
            all_versions = obj.get_all_versions().exclude(id=obj.id)
            same_storage_versions = all_versions.filter(storage_location=obj.storage_location)
            
            if not all_versions.exists():
                return format_html('<span style="color: #6c757d;" title="{}">—</span>', _('Unique - no duplicates'))
            
            is_primary = obj.is_primary_version()
            total_count = all_versions.count()
            same_storage_versions = all_versions.filter(storage_location=obj.storage_location)
            same_storage_count = same_storage_versions.count()
            
            # Build tooltip with version details
            tooltip_parts = []
            if same_storage_count > 0:
                tooltip_parts.append(_('{} version(s) in same storage').format(same_storage_count + 1))
            if total_count > same_storage_count:
                tooltip_parts.append(_('{} version(s) in other storages').format(total_count - same_storage_count))
            
            tooltip = ' | '.join(tooltip_parts)
            
            if is_primary:
                return format_html(
                    '<span style="color: #28a745; font-weight: bold;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> PRIMARY</span><br>'
                    '<span style="color: #6c757d; font-size: 0.85em;">({} {})</span>',
                    tooltip,
                    total_count + 1,
                    _('versions total')
                )
            else:
                # ARCHIVE: if multiple versions exist in ARCHIVE, label non-best ones as "ARCHIVE DUPLICATE"
                if obj.storage_location and obj.storage_location.storage_type == 'ARCHIVE':
                    archive_versions = [obj] + list(
                        all_versions.filter(storage_location__storage_type='ARCHIVE')
                    )
                    if len(archive_versions) > 1:
                        from django.utils import timezone
                        from datetime import datetime

                        def archive_key(v):
                            created = v.created_at or v.last_scanned or v.updated_at
                            if created is None:
                                created = datetime(1970, 1, 1, tzinfo=timezone.utc)
                            return (
                                bool(getattr(v, 'is_manual_primary', False)),
                                bool(getattr(v, 'is_available', True)),
                                v.total_bitrate or 0,
                                created,
                            )

                        best_archive = max(archive_versions, key=archive_key)
                        if obj.id == best_archive.id:
                            return format_html(
                                '<span style="color: #17a2b8; font-weight: bold;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg> {}</span><br>'
                                '<span style="color: #6c757d; font-size: 0.85em;">({} {})</span>',
                                tooltip,
                                _('ARCHIVE PRIMARY'),
                                total_count + 1,
                                _('versions total')
                            )
                        return format_html(
                            '<span style="color: #ffc107; font-weight: bold;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> {}</span><br>'
                            '<span style="color: #6c757d; font-size: 0.85em;">({} {})</span>',
                            tooltip,
                            _('ARCHIVE DUPLICATE'),
                            total_count + 1,
                            _('versions total')
                        )

                # Single archive copy among multiple storages: treat as canonical archive copy
                return format_html(
                    '<span style="color: #17a2b8; font-weight: bold;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg> {}</span><br>'
                    '<span style="color: #6c757d; font-size: 0.85em;">({} {})</span>',
                    tooltip,
                    _('ARCHIVE VERSION'),
                    total_count + 1,
                    _('versions total')
                )

            # Check if this is an old version (lower quality or older date)
            primary_versions = [v for v in obj.get_all_versions() if v.is_primary_version()]
            if primary_versions:
                primary = primary_versions[0]
                is_old = (
                    obj.total_bitrate and primary.total_bitrate and obj.total_bitrate < primary.total_bitrate
                ) or (
                    obj.created_at and primary.created_at and obj.created_at < primary.created_at
                )
                
                if is_old:
                    return format_html(
                        '<span style="color: #dc3545; font-weight: bold;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> OLD VERSION</span><br>'
                        '<span style="color: #6c757d; font-size: 0.85em;">({} {})</span>',
                        tooltip,
                        total_count + 1,
                        _('versions total')
                    )

            return format_html(
                '<span style="color: #ffc107; font-weight: bold;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> {}</span><br>'
                '<span style="color: #6c757d; font-size: 0.85em;">({} {})</span>',
                tooltip,
                _('DUPLICATE'),
                total_count + 1,
                _('versions total')
            )
        except Exception as e:
            # Log the error and return neutral indicator to prevent 500
            logger.error(f'Error in duplicates_indicator for VideoFile {obj.id}: {e}', exc_info=True)
            return format_html('<span style="color: #6c757d;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg></span>', _('Error determining status'))

    duplicates_indicator.short_description = _('Versions')
    
    def duplicate_status_display(self, obj):
        """Show detailed duplicate status."""
        if not obj.pk:
            return '-'
        if getattr(obj, 'is_preview', False):
            return format_html(
                '<span style="color: #6c757d;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg> {}</span><br>'
                '<span style="color: #666;">{}</span>',
                _('Preview clip'),
                _('Not linked to license; not counted as a version.'),
            )
        if not obj.has_duplicates:
            return mark_safe('<span style="color: #28a745;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> Unique (no duplicates)</span>')

        try:
            is_primary = obj.is_primary_version()
        except Exception as e:
            logger.error(f'Error in duplicate_status_display for VideoFile {obj.id}: {e}', exc_info=True)
            return format_html('<span style="color: #6c757d;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg></span>', _('Error determining status'))
        count = obj.duplicate_count
        
        if is_primary:
            return format_html(
                '<span style="color: #28a745;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> PRIMARY VERSION</span><br>'
                '<span style="color: #666;">This is the best quality version. {} duplicate(s) exist.</span>',
                count
            )
        else:
            try:
                primary_versions = [v for v in obj.get_all_versions() if v.is_primary_version()]
                if not primary_versions:
                    return format_html('<span style="color: #6c757d;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg></span>', _('Error determining status'))
                primary = primary_versions[0]
            except Exception as e:
                logger.error(f'Error selecting primary in duplicate_status_display for VideoFile {obj.id}: {e}', exc_info=True)
                return format_html('<span style="color: #6c757d;" title="{}"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg></span>', _('Error determining status'))
            if obj.storage_location and obj.storage_location.storage_type == 'ARCHIVE':
                archive_versions = list(
                    VideoFile.objects.filter(
                        number=obj.number,
                        storage_location__storage_type='ARCHIVE'
                    )
                )
                if len(archive_versions) > 1:
                    from django.utils import timezone
                    from datetime import datetime

                    def archive_key(v):
                        created = v.created_at or v.last_scanned or v.updated_at
                        if created is None:
                            created = datetime(1970, 1, 1, tzinfo=timezone.utc)
                        return (
                            bool(getattr(v, 'is_manual_primary', False)),
                            bool(getattr(v, 'is_available', True)),
                            v.total_bitrate or 0,
                            created,
                        )

                    best_archive = max(archive_versions, key=archive_key)
                    if obj.id != best_archive.id:
                        return format_html(
                            '<span style="color: #ffc107;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> {}</span><br>'
                            '<span style="color: #666;">Keep: <a href="{}">{}</a></span>',
                            _('ARCHIVE DUPLICATE'),
                            reverse('admin:media_files_videofile_change', args=[best_archive.id]),
                            best_archive.filename
                        )
                    return format_html(
                        '<span style="color: #17a2b8;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg> {}</span><br>'
                        '<span style="color: #666;">Other archive versions exist: {}.</span>',
                        _('ARCHIVE PRIMARY'),
                        len(archive_versions) - 1
                    )

                return format_html(
                    '<span style="color: #17a2b8;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg> {}</span><br>'
                    '<span style="color: #666;">Primary version is in: <a href="{}">{}</a></span>',
                    _('ARCHIVE VERSION'),
                    reverse('admin:media_files_videofile_change', args=[primary.id]),
                    primary.storage_location.name
                )
            return format_html(
                '<span style="color: #ffc107;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> {} </span><br>'
                '<span style="color: #666;">Primary version is in: <a href="{}">{}</a></span>',
                _('DUPLICATE VERSION'),
                reverse('admin:media_files_videofile_change', args=[primary.id]),
                primary.storage_location.name
            )

    duplicate_status_display.short_description = _('Duplicate Status')

    def all_versions_display(self, obj):
        """Show all versions of this video with detailed comparison."""
        if not obj.pk:
            return '-'
        
        # Get full versions only (preview clips are not listed as versions)
        all_versions = obj.get_all_versions()
        if getattr(obj, 'is_preview', False):
            # This record is a preview clip; show note and list full versions only
            intro = format_html(
                mark_safe('<div style="padding: 8px; background: #f0f0f0; border-left: 3px solid #6c757d; margin: 5px 0;">'
                '<svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg> <strong>{}</strong></div>'),
                _('This record is a preview clip (not linked to license). Full versions:'),
            )
        else:
            intro = ''
        if all_versions.count() <= 1 and not getattr(obj, 'is_preview', False):
            return format_html('<span style="color: #6c757d;">{}</span>', _('No other versions'))
        if all_versions.count() == 0 and getattr(obj, 'is_preview', False):
            return format_html('{}<span style="color: #6c757d;">{}</span>', intro, _('No full versions for this number.'))
        
        versions_list = list(all_versions.select_related('storage_location'))
        html_parts = []
        primary = None

        archive_versions = [v for v in versions_list if v.storage_location and v.storage_location.storage_type == 'ARCHIVE']
        best_archive = None
        if len(archive_versions) > 1:
            from django.utils import timezone
            from datetime import datetime

            def archive_key(v):
                created = v.created_at or v.last_scanned or v.updated_at
                if created is None:
                    created = datetime(1970, 1, 1, tzinfo=timezone.utc)
                return (
                    bool(getattr(v, 'is_manual_primary', False)),
                    bool(getattr(v, 'is_available', True)),
                    v.total_bitrate or 0,
                    created,
                )

            best_archive = max(archive_versions, key=archive_key)
        
        for v in versions_list:
            is_current = v.id == obj.id
            try:
                is_primary = v.is_primary_version()
            except Exception as e:
                logger.error(f'Error in all_versions_display for VideoFile {v.id}: {e}', exc_info=True)
                is_primary = False
            if is_primary:
                primary = v
            
            # Determine version status
            if is_primary:
                status = mark_safe('<span style="color: #28a745; font-weight: bold;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><polyline points="20 6 9 17 4 12"></polyline></svg> PRIMARY</span>')
            elif is_current:
                status = mark_safe('<span style="color: #007bff; font-weight: bold;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg> CURRENT</span>')
            else:
                if v.storage_location and v.storage_location.storage_type == 'ARCHIVE':
                    if best_archive and v.id == best_archive.id:
                        status = mark_safe(f'<span style="color: #17a2b8;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg> {_("ARCHIVE PRIMARY")}</span>')
                    elif best_archive and v.id != best_archive.id:
                        status = mark_safe(f'<span style="color: #ffc107;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> {_("ARCHIVE DUPLICATE")}</span>')
                    else:
                        status = mark_safe(f'<span style="color: #17a2b8;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg> {_("ARCHIVE VERSION")}</span>')
                else:
                    # Check if old version
                    is_old = False
                    if primary:
                        is_old = (
                            (v.total_bitrate and primary.total_bitrate and v.total_bitrate < primary.total_bitrate * 0.8)
                            or (v.created_at and primary.created_at and v.created_at < primary.created_at - timedelta(days=30))
                        )
                    
                    if is_old:
                        status = mark_safe('<span style="color: #dc3545;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> OLD</span>')
                    else:
                        status = mark_safe(f'<span style="color: #ffc107;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> {_("DUPLICATE")}</span>')
            
            # Build version info
            format_info = v.format.upper() if v.format else '?'
            resolution = f'{v.width}x{v.height}' if v.width and v.height else '?'
            bitrate = f'{v.bitrate_mbps} Mbps' if v.bitrate_mbps else '?'
            size = f'{v.file_size_mb} MB' if v.file_size_mb else '?'
            date = v.created_at.strftime('%Y-%m-%d') if v.created_at else '?'
            
            # format_html escapes every argument: filename and storage name come
            # from scanning the video storage, so a file dropped on the NAS as
            # `<img src=x onerror=...>.mp4` would otherwise run script in the
            # admin. ``status`` is already a SafeString and passes through.
            info = format_html(
                '<strong>{}</strong><br>'
                '{} • {} • {} • {} • {}<br>'
                '<small style="color: #6c757d;">{}: {}</small>',
                v.filename,
                v.storage_location.name,
                format_info,
                resolution,
                bitrate,
                size,
                _("Created"),
                date,
            )

            if is_current:
                html_parts.append(format_html(
                    '<div style="padding: 8px; background: #e7f3ff; '
                    'border-left: 3px solid #007bff; margin: 5px 0;">{}<br>{}</div>',
                    status,
                    info,
                ))
            else:
                url = reverse('admin:media_files_videofile_change', args=[v.id])
                html_parts.append(format_html(
                    '<div style="padding: 8px; background: #f8f9fa; '
                    'border-left: 3px solid #dee2e6; margin: 5px 0;">'
                    '{}<br><a href="{}">{}</a></div>',
                    status,
                    url,
                    info,
                ))

        body = mark_safe(''.join(html_parts))
        if getattr(obj, 'is_preview', False) and intro:
            return format_html('{} {}', intro, body)
        return body

    all_versions_display.short_description = _('All Versions')

    def player_link(self, obj):
        """Link to open video stream in modal."""
        if obj.is_available and obj.pk:
            stream_url = reverse('admin:media_files_videofile_stream', args=[obj.id])
            # Prepare additional fields for modal
            number = obj.number or ''
            storage_name = obj.storage_location.name if obj.storage_location else ''
            duration = str(obj.duration) if obj.duration else 'N/A'
            size_display = ''
            try:
                size_display = self.file_size_display(obj) or ''
            except Exception:
                size_display = 'N/A'
            bitrate_display = f"{obj.total_bitrate} bps" if obj.total_bitrate else 'N/A'
            player_text = _("Player")  # Get translated text beforehand

            return format_html(
                '<a href="#" onclick="openVideoModal(\'{}\', \'{}\', \'{}\', \'{}\', \'{}\', \'{}\', \'{}\')" style="color: #417690; text-decoration: none;"><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg> {}</a>',
                stream_url,
                obj.filename or '',
                number,
                storage_name,
                duration,
                size_display,
                bitrate_display,
                player_text,
            )
        return "-"
    player_link.short_description = _('Player')
    
    def video_player(self, obj):
        """Embed Video.js player in admin."""
        if obj.is_available and obj.pk:
            stream_url = reverse('admin:media_files_videofile_stream', args=[obj.id])
            
            # Get correct MIME type based on file extension
            import os
            file_extension = os.path.splitext(obj.filename)[1].lower()
            content_types = {
                '.mp4': 'video/mp4',
                '.mov': 'video/quicktime',
                '.mpeg': 'video/mpeg',
                '.mpg': 'video/mpeg',
                '.avi': 'video/x-msvideo',
                '.mkv': 'video/x-matroska',
                '.webm': 'video/webm',
            }
            mime_type = content_types.get(file_extension, 'video/mp4')
            
            # Generate UNC path for VLC
            vlc_path = self._get_vlc_path(obj)
            
            # Get translated strings beforehand
            file_path_linux = _("File path (Linux)")
            file_path_windows = _("File path (Windows UNC)")
            try:
                if getattr(settings, "TOOLS_ENABLED", False) and "tools" in getattr(settings, "INSTALLED_APPS", []):
                    render_url = reverse("tools:video_render", args=[obj.id])
                else:
                    render_url = reverse('media_files:render_video_admin', args=[obj.id])
            except Exception:
                if getattr(settings, "TOOLS_ENABLED", False):
                    render_url = f"/tools/video-render/{obj.id}/"
                else:
                    render_url = f'/media-files/render/video/{obj.id}/'
            
            render_label = _('Render Video with Overlays')
            
            return format_html(
                '''
                <div style="max-width: 640px; margin: 10px 0;">
                    <!-- Plyr CSS -->
                    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
                    
                    <!-- Plyr Player -->
                    <video
                        id="plyr-player-{}"
                        controls
                        preload="metadata"
                        crossorigin="anonymous"
                        width="640"
                        height="360">
                        <source src="{}" type="{}">
                        <p>To view the video, enable JavaScript or use
                            <a href="{}" download>download video</a>
                        </p>
                    </video>
                    
                    <!-- Plyr JavaScript -->
                    <script src="https://cdn.plyr.io/3.7.8/plyr.polyfilled.js"></script>
                    
                    <!-- Render Button -->
                    <div style="margin-top: 15px; text-align: center;">
                        <a href="{}" class="button" style="display: inline-block; padding: 10px 20px; background: #28a745; color: white; text-decoration: none; border-radius: 4px; font-weight: 500;">
                            <svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg> {}
                        </a>
                    </div>
                    
                    <!-- Video Info -->
                    <div style="margin-top: 15px; padding: 12px; background: #f8f9fa; border-radius: 4px; border-left: 4px solid #007bff;">
                        <div style="font-size: 12px; color: #333; margin-bottom: 5px;">
                            <strong><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg> {}:</strong>
                        </div>
                        <code style="display: block; padding: 8px; background: white; border-radius: 3px; word-break: break-all; font-size: 11px; color: #495057; border: 1px solid #dee2e6;">{}</code>
                        {}
                    </div>
                    
                    <!-- Initialize Plyr -->
                    <script>
                        document.addEventListener('DOMContentLoaded', function() {{
                            if (typeof Plyr !== 'undefined') {{
                                const player = new Plyr('#plyr-player-{}', {{
                                    controls: [
                                        'play-large', 'restart', 'rewind', 'play', 'fast-forward', 'progress',
                                        'current-time', 'duration', 'mute', 'volume', 'settings', 'fullscreen'
                                    ],
                                    settings: ['quality', 'speed'],
                                    speed: {{ selected: 1, options: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2] }},
                                    quality: {{ default: 720, options: [1080, 720, 480, 360] }},
                                    loadSprite: false,  // Disable sprite loading for faster init
                                    clickToPlay: true,  // Enable click to play
                                    hideControls: true, // Hide controls when not interacting
                                    resetOnEnd: false,  // Don't reset on end for better UX
                                    disableContextMenu: false, // Allow right-click menu
                                    keyboard: {{ focused: true, global: false }}, // Keyboard controls
                                    tooltips: {{ controls: true, seek: true }}, // Show tooltips
                                    captions: {{ active: false, language: 'auto', update: false }}, // Disable captions
                                    previewThumbnails: {{ enabled: false }}, // Disable thumbnails for speed
                                    volume: 1, // Default volume
                                    muted: false, // Not muted by default
                                    autoplay: false, // Don't autoplay
                                    loop: {{ active: false }}, // Don't loop
                                    ratio: null // Auto aspect ratio
                                }});
                                console.log('Plyr player ready');
                                
                                // Optimize for fast playback
                                player.on('ready', function() {{
                                    console.log('Modal player ready for fast streaming');
                                    const video = player.media;
                                    if (video) {{
                                        video.addEventListener('loadstart', function() {{
                                            console.log('Modal video buffering started');
                                        }});
                                        
                                        video.addEventListener('seeking', function() {{
                                            console.log('Modal video seeking to:', video.currentTime);
                                        }});
                                        
                                        video.addEventListener('progress', function() {{
                                            if (video.buffered.length > 0) {{
                                                const bufferedEnd = video.buffered.end(video.buffered.length - 1);
                                                const duration = video.duration;
                                                if (duration > 0) {{
                                                    const bufferedPercent = (bufferedEnd / duration) * 100;
                                                    console.log('Modal video buffered:', bufferedPercent.toFixed(1) + '%');
                                                }}
                                            }}
                                        }});
                                    }}
                                }});
                            }}
                        }});
                    </script>
                </div>
                ''',
                obj.id,  # video player ID
                stream_url,
                mime_type,
                stream_url,
                render_url,  # Render button URL
                render_label,  # Render button label
                file_path_linux,  # Use pre-translated string
                obj.full_path,
                f'''
                    <div style="font-size: 12px; color: #333; margin-top: 10px; margin-bottom: 5px;">
                        <strong><svg class="icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-bottom;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg> {file_path_windows}:</strong>
                    </div>
                    <code style="display: block; padding: 8px; background: white; border-radius: 3px; word-break: break-all; font-size: 11px; color: #495057; border: 1px solid #dee2e6;">{obj.unc_path}</code>
                ''' if obj.unc_path else '',
                obj.id  # video player ID for script
            )
        return _('Video not available')
    
    video_player.short_description = _('Video Player')
    
    def video_player_page(self, request, video_id):
        """Display video player page."""
        try:
            video = VideoFile.objects.get(id=video_id)
            return render(request, 'admin/video_player.html', {'video': video})
        except VideoFile.DoesNotExist:
            return HttpResponse(_('Video not found'), status=404)
        except Exception as e:
            logger.error(f'Error loading video player: {str(e)}', exc_info=True)
            return HttpResponse(_('Error: {}').format(str(e)), status=500)

    @csrf_exempt
    def stream_video(self, request, video_id):
        """Stream video file with range support using django-downloadview."""
        try:
            video = VideoFile.objects.get(id=video_id)
            
            if not video.is_available:
                return HttpResponse(_('Video not available'), status=404)

            file_path = video.full_path

            # Handle read-only storage gracefully
            try:
                if not os.path.exists(file_path):
                    video.is_available = False
                    video.save()
                    return HttpResponse(_('Video file not found'), status=404)
            except (OSError, PermissionError, IOError) as e:
                # Storage might be read-only - try to serve anyway if file path is valid
                logger.debug(f'Could not check file existence for {file_path}: {e}')
                # Continue to try serving - django-downloadview will handle the error
            except Exception as e:
                logger.warning(f'Unexpected error checking file {file_path}: {e}')
                # Continue to try serving
            
            # Determine content type based on file extension, not database format
            file_extension = os.path.splitext(video.filename)[1].lower()
            content_types = {
                '.mp4': 'video/mp4',
                '.mov': 'video/quicktime',
                '.mpeg': 'video/mpeg',
                '.mpg': 'video/mpeg',
                '.avi': 'video/x-msvideo',
                '.mkv': 'video/x-matroska',
                '.webm': 'video/webm',
            }
            content_type = content_types.get(file_extension, 'video/mp4')
            
            # Use FileResponse with range support for efficient streaming
            from django.http import FileResponse
            import mimetypes
            
            # Get file size for range requests
            file_size = os.path.getsize(file_path)
            
            # Open file in binary mode
            video_file = open(file_path, 'rb')
            
            # Create FileResponse with range support
            response = FileResponse(video_file, content_type=content_type)
            response['Content-Disposition'] = f'inline; filename="{video.filename}"'
            response['Accept-Ranges'] = 'bytes'
            response['Cache-Control'] = 'public, max-age=86400'  # Cache for 24 hours
            response['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
            
            # Handle Range requests for video streaming
            range_header = request.META.get('HTTP_RANGE')
            if range_header:
                import re
                range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
                if range_match:
                    start = int(range_match.group(1))
                    end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
                    
                    # Set partial content response
                    response.status_code = 206
                    response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
                    response['Content-Length'] = str(end - start + 1)
                    
                    # Seek to start position
                    video_file.seek(start)
            
            return response
            
        except VideoFile.DoesNotExist:
            return HttpResponse(_('Video not found'), status=404)
        except Exception as e:
            logger.error(f'Error streaming video: {str(e)}', exc_info=True)
            return HttpResponse(_('Error: {}').format(str(e)), status=500)
    
    def copy_to_playout_action(self, request, queryset):
        """Action to copy selected videos to playout."""
        from .utils import check_duplicate_before_copy
        
        success_count = 0
        error_count = 0
        
        # Get destination storage
        destination = StorageLocation.objects.filter(
            storage_type='PLAYOUT',
            is_active=True
        ).first()
        
        if not destination:
            self.message_user(request, _('No PLAYOUT storage configured'), level='error')
            return
        
        for video in queryset:
            # Check for duplicates if copying to ARCHIVE
            if destination.storage_type == 'ARCHIVE':
                is_dup, existing, msg = check_duplicate_before_copy(video, destination)
                if is_dup:
                    self.message_user(
                        request,
                        f'{video.number}: Cannot copy - {msg}',
                        level='error'
                    )
                    error_count += 1
                    continue
            
            success, message = copy_video_to_playout(video, destination, user=request.user)
            if success:
                success_count += 1
            else:
                error_count += 1
                if 'already exists' not in message.lower():
                    self.message_user(request, f'{video.number}: {message}', level='warning')
        
        if success_count > 0:
            self.message_user(request, f'Successfully copied {success_count} video(s) to playout')
        if error_count > 0:
            self.message_user(
                request,
                f'{error_count} video(s) failed or already in playout',
                level='warning'
            )
    copy_to_playout_action.short_description = _('Copy to playout storage')
    
    def update_metadata_action(self, request, queryset):
        """Action to update metadata for selected videos."""
        from django.utils import timezone
        
        success_count = 0
        error_count = 0
        
        for video in queryset:
            try:
                if not video.is_available:
                    continue
                
                metadata = extract_video_metadata_fast(video.full_path)
                
                # Update fields
                if 'format' in metadata:
                    video.format = metadata['format']
                if 'duration' in metadata:
                    video.duration = metadata['duration']
                if 'total_bitrate' in metadata:
                    video.total_bitrate = metadata['total_bitrate']
                
                video.has_video = metadata.get('has_video', False)
                if video.has_video:
                    video.video_codec = metadata.get('video_codec', '')
                    video.fps = metadata.get('fps')
                    video.width = metadata.get('width')
                    video.height = metadata.get('height')
                
                video.has_audio = metadata.get('has_audio', False)
                if video.has_audio:
                    video.audio_codec = metadata.get('audio_codec', '')
                    video.audio_channels = metadata.get('audio_channels')
                
                video.last_scanned = timezone.now()
                video.save()
                
                success_count += 1
                
            except Exception as e:
                error_count += 1
                logger.error(f'Error updating metadata for {video.number}: {str(e)}')
        
        if success_count > 0:
            self.message_user(request, f'Updated metadata for {success_count} video(s)')
        if error_count > 0:
            self.message_user(request, f'{error_count} error(s) occurred', level='error')
    update_metadata_action.short_description = _('Update metadata')
    
    def verify_integrity_action(self, request, queryset):
        """Action to verify file integrity."""
        success_count = 0
        error_count = 0
        
        for video in queryset:
            if not video.checksum:
                self.message_user(
                    request,
                    f'{video.number}: No checksum stored',
                    level='warning'
                )
                continue
            
            is_valid, message = verify_file_integrity(video)
            if is_valid:
                success_count += 1
            else:
                error_count += 1
                self.message_user(
                    request,
                    f'{video.number}: {message}',
                    level='error'
                )
        
        if success_count > 0:
            self.message_user(request, f'{success_count} video(s) verified successfully')
        if error_count > 0:
            self.message_user(request, f'{error_count} video(s) failed verification', level='error')
    verify_integrity_action.short_description = _('Verify file integrity')
    
    @admin.action(description=_('Mark selected as primary version'))
    def mark_as_primary_action(self, request, queryset):
        """Mark selected videos as primary (manual override)."""
        # Group by number
        by_number = {}
        for video in queryset:
            if video.number not in by_number:
                by_number[video.number] = []
            by_number[video.number].append(video)
        
        marked_count = 0
        
        for number, videos in by_number.items():
            if len(videos) > 1:
                self.message_user(
                    request,
                    _('Multiple videos selected for number {}. Please select only one per number.').format(number),
                    level='error'
                )
                continue
            
            primary = videos[0]
            
            # Clear manual primary flag from all other versions with same number
            VideoFile.objects.filter(number=number).exclude(id=primary.id).update(is_manual_primary=False)
            
            # Set manual primary flag for selected video
            primary.is_manual_primary = True
            primary.save(update_fields=['is_manual_primary'])
            marked_count += 1
            
            all_versions = VideoFile.objects.filter(number=number).exclude(id=primary.id)
            if all_versions.exists():
                logger.info(f'Video #{number} marked as manual primary. Found {all_versions.count()} duplicate(s)')
        
        if marked_count > 0:
            self.message_user(
                request,
                _('Marked {} video(s) as primary version').format(marked_count),
                level='success'
            )
    
    @admin.action(description=_('Delete duplicate versions (keep best quality)'))
    def delete_duplicates_action(self, request, queryset):
        """Delete duplicate versions, keeping the best quality one."""
        # Get unique numbers from selection
        numbers = set(queryset.values_list('number', flat=True))
        
        deleted_count = 0
        kept_count = 0
        
        for number in numbers:
            versions = VideoFile.objects.filter(number=number).select_related('storage_location')
            if versions.count() <= 1:
                continue
            
            # Check if any version is manually marked as primary
            manual_primary = versions.filter(is_manual_primary=True).first()
            if manual_primary:
                primary = manual_primary
            else:
                # Find primary version by quality (availability > bitrate+storage > recency)
                storage_priority = {'ARCHIVE': 3, 'PLAYOUT': 2, 'CUSTOM': 1}
                primary = max(versions, key=lambda v: (
                    bool(getattr(v, 'is_available', True)),
                    (storage_priority.get(v.storage_location.storage_type, 0) * 1_000_000_000) + (v.total_bitrate or 0),
                    v.created_at,
                ))
            
            # Delete others
            duplicates = versions.exclude(id=primary.id)
            for dup in duplicates:
                # Log before deletion
                logger.info(f'Deleting duplicate video {dup.number} from {dup.storage_location.name}')
                dup.delete()
                deleted_count += 1
            
            kept_count += 1
        
        self.message_user(
            request,
            f'Deleted {deleted_count} duplicate(s), kept {kept_count} primary version(s)',
            level='success'
        )

    @admin.action(description=_('Delete archive duplicate versions (keep best archive)'))
    def delete_archive_duplicates_action(self, request, queryset):
        """Delete duplicate versions inside ARCHIVE only, keeping the best ARCHIVE version per number."""
        if _is_archive_protected():
            self.message_user(
                request,
                _('Cannot delete videos from ARCHIVE storage. Archive is read-only for deletion to prevent data loss.'),
                level='error'
            )
            return

        # Only operate on ARCHIVE selections (ignore others)
        archive_selected = queryset.filter(storage_location__storage_type='ARCHIVE')
        numbers = set(archive_selected.values_list('number', flat=True))

        deleted_count = 0
        kept_count = 0
        skipped_count = 0

        for number in numbers:
            versions = VideoFile.objects.filter(
                number=number,
                storage_location__storage_type='ARCHIVE'
            ).select_related('storage_location')

            if versions.count() <= 1:
                skipped_count += 1
                continue

            best = max(list(versions), key=_archive_version_sort_key)
            duplicates = versions.exclude(id=best.id)

            for dup in duplicates:
                dup.delete()
                deleted_count += 1

            kept_count += 1

        if deleted_count:
            self.message_user(
                request,
                _('Deleted {} archive duplicate(s), kept {} archive primary version(s).').format(deleted_count, kept_count),
                level='success'
            )
        if skipped_count:
            self.message_user(
                request,
                _('Skipped {} number(s) with no archive duplicates.').format(skipped_count),
                level='info'
            )

    @admin.action(description=_('Preview archive cleanup (keep best archive)'))
    def preview_archive_duplicates_action(self, request, queryset):
        """Preview deleting archive duplicates, keeping best ARCHIVE version per number."""
        archive_selected = queryset.filter(storage_location__storage_type='ARCHIVE')
        numbers = set(archive_selected.values_list('number', flat=True))

        rows = []
        for number in sorted(numbers):
            versions = list(
                VideoFile.objects.filter(
                    number=number,
                    storage_location__storage_type='ARCHIVE'
                ).select_related('storage_location')
            )
            if len(versions) <= 1:
                continue

            keep = max(versions, key=_archive_version_sort_key)
            delete = [v for v in versions if v.id != keep.id]

            def fmt(v):
                bitrate = f"{(v.total_bitrate or 0) / 1_000_000:.2f} Mbps" if v.total_bitrate else "?"
                size = f"{(v.file_size or 0) / (1024 * 1024):.2f} MB" if v.file_size else "?"
                created = v.created_at or v.last_scanned or v.updated_at
                created_s = created.strftime('%Y-%m-%d %H:%M') if created else '?'
                return f"#{v.id} {v.filename} • {bitrate} • {size} • {created_s}"

            rows.append({
                "number": number,
                "keep": fmt(keep),
                "delete": [fmt(v) for v in sorted(delete, key=_archive_version_sort_key, reverse=True)],
            })

        return _admin_archive_cleanup_preview_page("Preview: ARCHIVE cleanup (keep best archive)", rows)

    @admin.action(description=_('Preview archive cleanup (keep newest archive)'))
    def preview_archive_duplicates_keep_newest_action(self, request, queryset):
        """Preview deleting archive duplicates, keeping newest ARCHIVE version per number."""
        archive_selected = queryset.filter(storage_location__storage_type='ARCHIVE')
        numbers = set(archive_selected.values_list('number', flat=True))

        rows = []
        for number in sorted(numbers):
            versions = list(
                VideoFile.objects.filter(
                    number=number,
                    storage_location__storage_type='ARCHIVE'
                ).select_related('storage_location')
            )
            if len(versions) <= 1:
                continue

            keep = max(versions, key=_archive_newest_sort_key)
            delete = [v for v in versions if v.id != keep.id]

            def fmt(v):
                bitrate = f"{(v.total_bitrate or 0) / 1_000_000:.2f} Mbps" if v.total_bitrate else "?"
                size = f"{(v.file_size or 0) / (1024 * 1024):.2f} MB" if v.file_size else "?"
                created = v.created_at or v.last_scanned or v.updated_at
                created_s = created.strftime('%Y-%m-%d %H:%M') if created else '?'
                return f"#{v.id} {v.filename} • {bitrate} • {size} • {created_s}"

            rows.append({
                "number": number,
                "keep": fmt(keep),
                "delete": [fmt(v) for v in sorted(delete, key=_archive_newest_sort_key, reverse=True)],
            })

        return _admin_archive_cleanup_preview_page("Preview: ARCHIVE cleanup (keep newest)", rows)

    @admin.action(description=_('Preview archive cleanup (keep largest archive file)'))
    def preview_archive_duplicates_keep_largest_action(self, request, queryset):
        """Preview deleting archive duplicates, keeping largest ARCHIVE file per number."""
        archive_selected = queryset.filter(storage_location__storage_type='ARCHIVE')
        numbers = set(archive_selected.values_list('number', flat=True))

        rows = []
        for number in sorted(numbers):
            versions = list(
                VideoFile.objects.filter(
                    number=number,
                    storage_location__storage_type='ARCHIVE'
                ).select_related('storage_location')
            )
            if len(versions) <= 1:
                continue

            keep = max(versions, key=_archive_largest_sort_key)
            delete = [v for v in versions if v.id != keep.id]

            def fmt(v):
                bitrate = f"{(v.total_bitrate or 0) / 1_000_000:.2f} Mbps" if v.total_bitrate else "?"
                size = f"{(v.file_size or 0) / (1024 * 1024):.2f} MB" if v.file_size else "?"
                created = v.created_at or v.last_scanned or v.updated_at
                created_s = created.strftime('%Y-%m-%d %H:%M') if created else '?'
                return f"#{v.id} {v.filename} • {bitrate} • {size} • {created_s}"

            rows.append({
                "number": number,
                "keep": fmt(keep),
                "delete": [fmt(v) for v in sorted(delete, key=_archive_largest_sort_key, reverse=True)],
            })

        return _admin_archive_cleanup_preview_page("Preview: ARCHIVE cleanup (keep largest)", rows)

    def _force_archive_cleanup_confirm_page(self, request, queryset, *, action_name: str, title: str, required_phrase: str):
        """Render confirmation page for force archive cleanup actions."""
        cancel_url = reverse('admin:media_files_videofile_changelist')
        form = ForceArchiveDeleteConfirmForm(
            request.POST or None,
            user=request.user,
            required_phrase=required_phrase,
        )
        context = {
            **self.admin_site.each_context(request),
            'title': title,
            'action_name': action_name,
            'required_phrase': required_phrase,
            'form': form,
            'queryset': queryset,
            'cancel_url': cancel_url,
        }
        return form, render(request, 'admin/media_files/videofile/force_archive_delete_confirm.html', context)

    def _force_delete_videofile_best_effort(self, video: VideoFile) -> tuple[bool, bool, str]:
        """Delete physical file (best effort) and DB record for a VideoFile."""
        file_deleted = False
        try:
            if getattr(video, 'is_available', False):
                try:
                    full_path = video.full_path
                except Exception:
                    full_path = None
                if full_path and os.path.exists(full_path):
                    try:
                        os.remove(full_path)
                        file_deleted = True
                    except Exception as e:
                        # Continue with DB deletion even if file deletion fails
                        logger.warning(f"Could not delete physical file {full_path}: {e}")
            video.delete()
            return True, file_deleted, ""
        except Exception as e:
            return False, file_deleted, str(e)

    def _force_archive_cleanup_delete_with_confirmation(
        self,
        request,
        queryset,
        *,
        sort_key,
        action_name: str,
        title: str,
        required_phrase: str = "DELETE ARCHIVE",
    ):
        """
        Force delete duplicate versions inside ARCHIVE only, even if archive protection is enabled.
        Requires confirmation phrase + current user's password.
        """
        if not admin.ModelAdmin.has_delete_permission(self, request):
            self.message_user(request, _('You do not have permission to delete videos.'), level='error')
            return

        archive_selected = queryset.filter(storage_location__storage_type='ARCHIVE')
        numbers = sorted(set(archive_selected.values_list('number', flat=True)))

        planned_delete = 0
        sample_rows = []
        for number in numbers:
            versions = list(VideoFile.objects.filter(number=number, storage_location__storage_type='ARCHIVE'))
            if len(versions) <= 1:
                continue
            keep = max(versions, key=sort_key)
            delete = [v for v in versions if v.id != keep.id]
            planned_delete += len(delete)
            if len(sample_rows) < 20:
                sample_rows.append({
                    'number': number,
                    'keep': f"#{keep.id} {keep.filename}",
                    'delete': [f"#{v.id} {v.filename}" for v in delete],
                })

        # Step 1: show confirmation page
        if request.POST.get('force_apply') != '1':
            return render(
                request,
                'admin/media_files/videofile/force_archive_delete_confirm.html',
                {
                    **self.admin_site.each_context(request),
                    'title': title,
                    'action_name': action_name,
                    'required_phrase': required_phrase,
                    'form': ForceArchiveDeleteConfirmForm(user=request.user, required_phrase=required_phrase),
                    'queryset': archive_selected,
                    'cancel_url': reverse('admin:media_files_videofile_changelist'),
                    'planned_delete_count': planned_delete,
                    'planned_numbers_count': len(numbers),
                    'sample_rows': sample_rows,
                }
            )

        # Step 2: validate confirmation
        form = ForceArchiveDeleteConfirmForm(request.POST, user=request.user, required_phrase=required_phrase)
        if not form.is_valid():
            return render(
                request,
                'admin/media_files/videofile/force_archive_delete_confirm.html',
                {
                    **self.admin_site.each_context(request),
                    'title': title,
                    'action_name': action_name,
                    'required_phrase': required_phrase,
                    'form': form,
                    'queryset': archive_selected,
                    'cancel_url': reverse('admin:media_files_videofile_changelist'),
                    'planned_delete_count': planned_delete,
                    'planned_numbers_count': len(numbers),
                    'sample_rows': sample_rows,
                }
            )

        # Step 3: apply deletions
        deleted_records = 0
        deleted_files = 0
        errors = 0
        affected_numbers = 0

        for number in numbers:
            versions = list(
                VideoFile.objects.filter(
                    number=number,
                    storage_location__storage_type='ARCHIVE'
                ).select_related('storage_location')
            )
            if len(versions) <= 1:
                continue
            keep = max(versions, key=sort_key)
            to_delete = [v for v in versions if v.id != keep.id]
            if not to_delete:
                continue
            affected_numbers += 1
            for v in to_delete:
                ok, file_deleted, err = self._force_delete_videofile_best_effort(v)
                if ok:
                    deleted_records += 1
                    if file_deleted:
                        deleted_files += 1
                else:
                    errors += 1
                    logger.error(f"Force delete failed for VideoFile {v.id}: {err}")

        if deleted_records:
            self.message_user(
                request,
                _('Force delete completed: deleted %(records)d record(s), deleted %(files)d file(s), affected %(numbers)d number(s).') % {
                    'records': deleted_records,
                    'files': deleted_files,
                    'numbers': affected_numbers,
                },
                level='success'
            )
        if errors:
            self.message_user(
                request,
                _('Force delete encountered %(count)d error(s). Check logs for details.') % {'count': errors},
                level='warning'
            )

    @admin.action(description=_('Force delete archive duplicates (keep best archive) [requires confirmation]'))
    def force_delete_archive_duplicates_keep_best_action(self, request, queryset):
        return self._force_archive_cleanup_delete_with_confirmation(
            request,
            queryset,
            sort_key=_archive_version_sort_key,
            action_name='force_delete_archive_duplicates_keep_best_action',
            title=_('Force delete ARCHIVE duplicates (keep best archive)'),
        )

    @admin.action(description=_('Force delete archive duplicates (keep newest archive) [requires confirmation]'))
    def force_delete_archive_duplicates_keep_newest_action(self, request, queryset):
        return self._force_archive_cleanup_delete_with_confirmation(
            request,
            queryset,
            sort_key=_archive_newest_sort_key,
            action_name='force_delete_archive_duplicates_keep_newest_action',
            title=_('Force delete ARCHIVE duplicates (keep newest archive)'),
        )

    @admin.action(description=_('Force delete archive duplicates (keep largest archive file) [requires confirmation]'))
    def force_delete_archive_duplicates_keep_largest_action(self, request, queryset):
        return self._force_archive_cleanup_delete_with_confirmation(
            request,
            queryset,
            sort_key=_archive_largest_sort_key,
            action_name='force_delete_archive_duplicates_keep_largest_action',
            title=_('Force delete ARCHIVE duplicates (keep largest archive file)'),
        )

    @admin.action(description=_('Delete archive duplicate versions (keep newest archive)'))
    def delete_archive_duplicates_keep_newest_action(self, request, queryset):
        """Delete duplicate versions inside ARCHIVE only, keeping the newest ARCHIVE version per number."""
        if _is_archive_protected():
            self.message_user(
                request,
                _('Cannot delete videos from ARCHIVE storage. Archive is read-only for deletion to prevent data loss.'),
                level='error'
            )
            return

        archive_selected = queryset.filter(storage_location__storage_type='ARCHIVE')
        numbers = set(archive_selected.values_list('number', flat=True))

        deleted_count = 0
        kept_count = 0
        skipped_count = 0

        for number in numbers:
            versions = VideoFile.objects.filter(
                number=number,
                storage_location__storage_type='ARCHIVE'
            ).select_related('storage_location')

            if versions.count() <= 1:
                skipped_count += 1
                continue

            best = max(list(versions), key=_archive_newest_sort_key)
            duplicates = versions.exclude(id=best.id)
            for dup in duplicates:
                dup.delete()
                deleted_count += 1
            kept_count += 1

        if deleted_count:
            self.message_user(
                request,
                _('Deleted {} archive duplicate(s), kept {} newest archive version(s).').format(deleted_count, kept_count),
                level='success'
            )
        if skipped_count:
            self.message_user(
                request,
                _('Skipped {} number(s) with no archive duplicates.').format(skipped_count),
                level='info'
            )

    @admin.action(description=_('Delete archive duplicate versions (keep largest archive file)'))
    def delete_archive_duplicates_keep_largest_action(self, request, queryset):
        """Delete duplicate versions inside ARCHIVE only, keeping the largest ARCHIVE file per number."""
        if _is_archive_protected():
            self.message_user(
                request,
                _('Cannot delete videos from ARCHIVE storage. Archive is read-only for deletion to prevent data loss.'),
                level='error'
            )
            return

        archive_selected = queryset.filter(storage_location__storage_type='ARCHIVE')
        numbers = set(archive_selected.values_list('number', flat=True))

        deleted_count = 0
        kept_count = 0
        skipped_count = 0

        for number in numbers:
            versions = VideoFile.objects.filter(
                number=number,
                storage_location__storage_type='ARCHIVE'
            ).select_related('storage_location')

            if versions.count() <= 1:
                skipped_count += 1
                continue

            best = max(list(versions), key=_archive_largest_sort_key)
            duplicates = versions.exclude(id=best.id)
            for dup in duplicates:
                dup.delete()
                deleted_count += 1
            kept_count += 1

        if deleted_count:
            self.message_user(
                request,
                _('Deleted {} archive duplicate(s), kept {} largest archive file(s).').format(deleted_count, kept_count),
                level='success'
            )
        if skipped_count:
            self.message_user(
                request,
                _('Skipped {} number(s) with no archive duplicates.').format(skipped_count),
                level='info'
            )
    
    @admin.action(description=_('Move to archive storage'))
    def move_to_archive_action(self, request, queryset):
        """Move selected videos to archive storage."""
        from .utils import move_video_to_archive, has_system_attributes, is_file_in_use
        
        success_count = 0
        error_count = 0
        skipped_count = 0
        
        for video in queryset:
            # Only process playout videos
            if video.storage_location.storage_type != 'PLAYOUT':
                self.message_user(
                    request,
                    f'{video.number}: Not in playout storage, skipping',
                    level='warning'
                )
                skipped_count += 1
                continue
            
            # Check if file is still in use
            if has_system_attributes(video.full_path):
                self.message_user(
                    request,
                    f'{video.number}: Has system attributes - still in use by playout system',
                    level='warning'
                )
                skipped_count += 1
                continue
            
            if is_file_in_use(video.full_path):
                self.message_user(
                    request,
                    f'{video.number}: File is locked - still in use',
                    level='warning'
                )
                skipped_count += 1
                continue
            
            success, message = move_video_to_archive(video, user=request.user)
            if success:
                success_count += 1
            else:
                error_count += 1
                self.message_user(request, f'{video.number}: {message}', level='error')
        
        if success_count > 0:
            self.message_user(request, f'Successfully moved {success_count} video(s) to archive')
        if skipped_count > 0:
            self.message_user(request, f'{skipped_count} video(s) skipped (still in use)', level='warning')
        if error_count > 0:
            self.message_user(request, f'{error_count} video(s) failed to move', level='error')
    
    @admin.action(description=_('Cleanup records for files missing from disk'))
    def cleanup_missing_files_action(self, request, queryset):
        """Delete VideoFile records for files that no longer exist on disk.
        
        Works with read-only storage - handles errors gracefully when files cannot be checked.
        """
        import os
        from django.db import connection
        
        deleted_count = 0
        found_count = 0
        error_count = 0
        read_only_count = 0
        
        for video in queryset:
            try:
                if not video.is_available:
                    # Skip files already marked as unavailable
                    continue
                
                # Check if file exists on disk (handle read-only storage gracefully)
                file_exists = False
                try:
                    file_exists = os.path.exists(video.full_path)
                    found_count += 1
                except (OSError, PermissionError, IOError) as e:
                    # Storage might be read-only - skip this file
                    read_only_count += 1
                    logger.debug(f'Could not check file existence for {video.full_path}: {e}')
                    continue
                except Exception as e:
                    # Any other error - log and skip
                    read_only_count += 1
                    logger.warning(f'Unexpected error checking file {video.full_path}: {e}')
                    continue
                
                if not file_exists:
                    # Delete related FileOperation objects using raw SQL
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "DELETE FROM media_files_fileoperation WHERE video_file_id = %s",
                                [video.id]
                            )
                    except Exception as e:
                        logger.error(f'Error deleting FileOperation for video {video.id}: {e}')
                        # Continue anyway - will be cascade deleted
                    
                    # Delete the VideoFile
                    video.delete()
                    deleted_count += 1
                    logger.info(f'Deleted VideoFile {video.number} (file missing): {video.filename}')
            
            except Exception as e:
                error_count += 1
                logger.error(f'Error checking/deleting {video.filename}: {str(e)}')
                self.message_user(
                    request,
                    f'Error processing {video.number}: {str(e)}',
                    level='error'
                )
        
        if deleted_count > 0:
            self.message_user(
                request,
                _('Deleted {} record(s) for files missing from disk').format(deleted_count),
                level='success'
            )
        if read_only_count > 0:
            self.message_user(
                request,
                _('{} file(s) could not be checked (storage may be read-only)').format(read_only_count),
                level='info'
            )
        if found_count == 0:
            self.message_user(
                request,
                _('No files to check (all selected files are already marked as unavailable)'),
                level='info'
            )
        elif deleted_count == 0 and read_only_count == 0:
            self.message_user(
                request,
                _('All checked files exist on disk'),
                level='info'
            )
        if error_count > 0:
            self.message_user(
                request,
                _('{} error(s) occurred').format(error_count),
                level='error'
            )
    
    def has_delete_permission(self, request, obj=None):
        """
        Check if user has permission to delete VideoFile.
        
        ARCHIVE storage protection can be configured via VIDEO_ARCHIVE_PROTECTED setting.
        """
        # Check if archive protection is enabled
        archive_protected = _is_archive_protected()
        
        if archive_protected:
            # PROTECTION: Prevent deletion from ARCHIVE storage
            if obj and hasattr(obj, 'storage_location'):
                if obj.storage_location.storage_type == 'ARCHIVE':
                    return False
            
            # For queryset (bulk delete), check if any video is in ARCHIVE
            if hasattr(request, '_delete_queryset'):
                queryset = request._delete_queryset
                if queryset and queryset.filter(storage_location__storage_type='ARCHIVE').exists():
                    return False
        
        # Use default Django permission checking for other storages
        return super().has_delete_permission(request, obj)
    
    def get_deleted_objects(self, objs, request):
        """
        Override get_deleted_objects to bypass permission checks for FileOperation.
        
        This allows deletion of VideoFile records even when the user doesn't have
        delete permission for FileOperation (which is intentionally disabled).
        """
        from django.contrib.admin.utils import NestedObjects
        
        # Use collector to get all related objects
        collector = NestedObjects(using='default')
        collector.collect(objs)
        
        # Filter out FileOperation from all collections
        file_operation_label = 'media_files.fileoperation'
        
        # Filter model_objs - remove FileOperation
        filtered_model_objs = {}
        for model, instances in collector.model_objs.items():
            if model._meta.label_lower != file_operation_label:
                filtered_model_objs[model] = instances
        
        # Filter protected - remove FileOperation
        filtered_protected = []
        for item in collector.protected:
            if hasattr(item, '_meta') and item._meta.label_lower != file_operation_label:
                filtered_protected.append(item)
            elif not hasattr(item, '_meta'):
                filtered_protected.append(item)
        
        # Build deleted_objects list (format: list of readable strings)
        deleted_objects = []
        for model, instances in filtered_model_objs.items():
            for instance in instances:
                deleted_objects.append(f'{model._meta.verbose_name}: {instance}')
        
        # Build model_count dict (format: {verbose_name_plural: count})
        model_count = {}
        for model, instances in filtered_model_objs.items():
            model_count[model._meta.verbose_name_plural] = len(instances)
        
        # Build perms_needed set - check permissions for each model (excluding FileOperation)
        perms_needed = set()
        for model, instances in filtered_model_objs.items():
            # Check if user has delete permission for this model
            model_admin = self.admin_site._registry.get(model)
            if model_admin and not model_admin.has_delete_permission(request):
                perms_needed.add(model._meta.verbose_name)
        
        return deleted_objects, model_count, perms_needed, filtered_protected
    
    def delete_model(self, request, obj):
        """
        Override delete_model to bypass permission checks for related FileOperation objects.
        
        This allows deletion of VideoFile records even when the user doesn't have
        delete permission for FileOperation (which is intentionally disabled).
        Also deletes physical files from disk.
        """
        import os
        import traceback
        
        # PROTECTION: Prevent deletion from ARCHIVE storage
        archive_protected = _is_archive_protected()
        if archive_protected and obj.storage_location.storage_type == 'ARCHIVE':
            from django.contrib import messages
            self.message_user(
                request,
                _('Cannot delete videos from ARCHIVE storage. '
                  'Archive is read-only for deletion to prevent data loss. '
                  'You can read and copy videos from archive, but deletion is disabled.'),
                level='error'
            )
            raise PermissionError('ARCHIVE storage is protected from deletion')
        
        logger.info(f'delete_model called for VideoFile {obj.id} (number: {obj.number})')
        
        try:
            # Check if file exists on disk (handle read-only storage gracefully)
            file_exists = False
            file_check_error = None
            if obj.is_available:
                try:
                    # Safely get full_path - may fail if storage_location is None or path is missing
                    full_path = None
                    try:
                        full_path = obj.full_path
                    except (AttributeError, TypeError) as e:
                        logger.debug(f'Could not get full_path for video {obj.id}: {e}')
                        file_check_error = 'Could not determine file path'
                    
                    if full_path:
                        file_exists = os.path.exists(full_path)
                except (OSError, PermissionError, IOError) as e:
                    # Storage might be read-only or inaccessible - that's OK, we're only deleting DB record
                    file_check_error = str(e)
                    logger.debug(f'Could not check file existence: {e}')
                except Exception as e:
                    # Any other error - log but don't fail
                    file_check_error = str(e)
                    logger.warning(f'Unexpected error checking file: {e}')
            
            # Delete related FileOperation objects using raw SQL to bypass permission checks
            # FileOperationAdmin has delete permission disabled, so we use direct SQL
            from django.db import connection
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM media_files_fileoperation WHERE video_file_id = %s",
                        [obj.id]
                    )
            except Exception as e:
                logger.error(f'Error deleting FileOperation records for video {obj.id}: {e}')
                # Continue anyway - FileOperation will be cascade deleted
            
            # Delete physical file if it exists
            file_deleted = False
            file_delete_error = None
            if file_exists and full_path:
                try:
                    os.remove(full_path)
                    file_deleted = True
                    logger.info(f'Deleted physical file: {full_path}')
                except (OSError, PermissionError, IOError) as e:
                    file_delete_error = str(e)
                    logger.warning(f'Could not delete physical file {full_path}: {e}')
                    # Continue with DB deletion even if file deletion fails
                except Exception as e:
                    file_delete_error = str(e)
                    logger.error(f'Unexpected error deleting file {full_path}: {e}')
                    # Continue with DB deletion even if file deletion fails
            
            # Delete related FileOperation objects using raw SQL to bypass permission checks
            # FileOperationAdmin has delete permission disabled, so we use direct SQL
            from django.db import connection
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM media_files_fileoperation WHERE video_file_id = %s",
                        [obj.id]
                    )
            except Exception as e:
                logger.error(f'Error deleting FileOperation records for video {obj.id}: {e}')
                # Continue anyway - FileOperation will be cascade deleted
            
            # Delete the VideoFile (database record)
            try:
                logger.debug(f'Attempting to delete VideoFile {obj.id}')
                obj.delete()
                logger.info(f'Successfully deleted VideoFile {obj.id}')
            except Exception as e:
                error_traceback = traceback.format_exc()
                logger.error(f'Error in delete_model for VideoFile {obj.id}: {e}')
                logger.error(f'Traceback: {error_traceback}')
                # Re-raise to let Django admin handle it properly
                raise
            
            # Show appropriate message (only if deletion succeeded)
            if file_delete_error:
                self.message_user(
                    request,
                    _('Video record deleted. Could not delete physical file: {error}').format(error=file_delete_error),
                    level='warning'
                )
            elif file_check_error:
                self.message_user(
                    request,
                    _('Video record deleted. Could not check file status (storage may be read-only).'),
                    level='info'
                )
            elif file_deleted:
                self.message_user(
                    request,
                    _('Video record and physical file deleted successfully.'),
                    level='success'
                )
            elif not file_exists:
                self.message_user(
                    request,
                    _('Video record deleted (file was already removed from disk)'),
                    level='success'
                )
            else:
                self.message_user(
                    request,
                    _('Video record deleted.'),
                    level='success'
                )
        except Exception as e:
            error_traceback = traceback.format_exc()
            logger.error(f'Unexpected error in delete_model for VideoFile {obj.id}: {e}')
            logger.error(f'Traceback: {error_traceback}')
            raise
    
    def delete_queryset(self, request, queryset):
        """
        Override delete_queryset to bypass permission checks for related FileOperation objects.
        
        This allows bulk deletion of VideoFile records even when the user doesn't have
        delete permission for FileOperation (which is intentionally disabled).
        Also deletes physical files from disk.
        """
        import os
        import traceback
        
        # PROTECTION: Check if any video is in ARCHIVE storage
        archive_protected = _is_archive_protected()
        if archive_protected:
            archive_videos = queryset.filter(storage_location__storage_type='ARCHIVE')
            if archive_videos.exists():
                archive_count = archive_videos.count()
                self.message_user(
                    request,
                    _('Cannot delete %(count)d video(s) from ARCHIVE storage. '
                      'Archive is read-only for deletion to prevent data loss. '
                      'You can read and copy videos from archive, but deletion is disabled.') % {
                        'count': archive_count
                    },
                    level='error'
                )
                # Filter out ARCHIVE videos and continue with others
                queryset = queryset.exclude(storage_location__storage_type='ARCHIVE')
                
                if not queryset.exists():
                    # All videos were in ARCHIVE, nothing to delete
                    return
        
        logger.info(f'delete_queryset called with {queryset.count()} objects')
        
        deleted_count = 0
        files_deleted = 0
        files_missing = 0
        files_delete_errors = 0
        read_only_count = 0
        error_count = 0
        
        try:
            for obj in queryset:
                # Check if file exists on disk and delete it
                file_exists = False
                file_deleted = False
                file_check_error = None
                full_path = None
                
                if obj.is_available:
                    try:
                        # Safely get full_path - may fail if storage_location is None or path is missing
                        try:
                            full_path = obj.full_path
                        except (AttributeError, TypeError) as e:
                            logger.debug(f'Could not get full_path for video {obj.id}: {e}')
                            file_check_error = 'Could not determine file path'
                            read_only_count += 1
                        
                        if full_path:
                            file_exists = os.path.exists(full_path)
                            if not file_exists:
                                files_missing += 1
                            elif file_exists:
                                # Try to delete the physical file
                                try:
                                    os.remove(full_path)
                                    file_deleted = True
                                    files_deleted += 1
                                    logger.info(f'Deleted physical file: {full_path}')
                                except (OSError, PermissionError, IOError) as e:
                                    files_delete_errors += 1
                                    logger.warning(f'Could not delete physical file {full_path}: {e}')
                                    # Continue with DB deletion even if file deletion fails
                                except Exception as e:
                                    files_delete_errors += 1
                                    logger.error(f'Unexpected error deleting file {full_path}: {e}')
                                    # Continue with DB deletion even if file deletion fails
                    except (OSError, PermissionError, IOError) as e:
                        # Storage might be read-only or inaccessible
                        file_check_error = str(e)
                        read_only_count += 1
                        logger.debug(f'Could not check file existence: {e}')
                    except Exception as e:
                        # Any other error - log but don't fail
                        file_check_error = str(e)
                        read_only_count += 1
                        logger.warning(f'Unexpected error checking file: {e}')
                
                # Delete related FileOperation objects using raw SQL to bypass permission checks
                # Do this AFTER getting all info but BEFORE calling obj.delete() to avoid signal conflicts
                from django.db import connection
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "DELETE FROM media_files_fileoperation WHERE video_file_id = %s",
                            [obj.id]
                        )
                except Exception as e:
                    logger.error(f'Error deleting FileOperation records for video {obj.id}: {e}')
                    # Continue anyway - FileOperation will be cascade deleted
                
                # Delete the VideoFile (database record)
                # Wrap in try-except to catch any errors during deletion
                try:
                    logger.debug(f'Attempting to delete VideoFile {obj.id} (number: {obj.number})')
                    obj.delete()
                    deleted_count += 1
                    logger.debug(f'Successfully deleted VideoFile {obj.id}')
                except Exception as e:
                    error_count += 1
                    error_traceback = traceback.format_exc()
                    logger.error(f'Error deleting VideoFile {obj.id}: {e}')
                    logger.error(f'Traceback: {error_traceback}')
                    # Log error but continue with other deletions
                    self.message_user(
                        request,
                        _('Error deleting video {}: {}').format(obj.number or obj.id, str(e)),
                        level='error'
                    )
        
        except Exception as e:
            # Catch any unexpected errors in the loop
            error_traceback = traceback.format_exc()
            logger.error(f'Unexpected error in delete_queryset loop: {e}')
            logger.error(f'Traceback: {error_traceback}')
            self.message_user(
                request,
                _('Unexpected error during deletion: {}').format(str(e)),
                level='error'
            )
        
        # Show appropriate message
        if files_delete_errors > 0:
            self.message_user(
                request,
                _('{} video record(s) deleted. {} file(s) deleted from disk. {} file(s) could not be deleted from disk.').format(
                    deleted_count, files_deleted, files_delete_errors
                ),
                level='warning'
            )
        elif read_only_count > 0:
            self.message_user(
                request,
                _('{} video record(s) deleted. {} file(s) deleted from disk. {} file(s) could not be checked (storage may be read-only).').format(
                    deleted_count, files_deleted, read_only_count
                ),
                level='info'
            )
        elif files_missing == deleted_count:
            self.message_user(
                request,
                _('{} video record(s) deleted (files were already removed from disk)').format(deleted_count),
                level='success'
            )
        elif files_deleted > 0:
            self.message_user(
                request,
                _('{} video record(s) and {} physical file(s) deleted successfully.').format(deleted_count, files_deleted),
                level='success'
            )
        else:
            self.message_user(
                request,
                _('{} video record(s) deleted.').format(deleted_count),
                level='success'
            )
        
        if error_count > 0:
            logger.warning(f'delete_queryset completed with {error_count} error(s), {deleted_count} successful deletion(s)')
        else:
            logger.info(f'delete_queryset completed successfully: {deleted_count} deletion(s), {files_deleted} file(s) deleted')

    class Media:
        css = {
            'all': ('css/admin/custom_admin.css',)
        }


@admin.register(FileOperation)
class FileOperationAdmin(admin.ModelAdmin):
    """Admin interface for file operations (read-only)."""

    change_list_template = 'admin/media_files/fileoperation/change_list.html'
    
    list_display = [
        'video_file', 'operation_type', 'status',
        'source_location', 'destination_location',
        'performed_by', 'performed_at'
    ]
    list_filter = [
        'operation_type', 'status',
        ('performed_at', DateRangeFilter),
        'source_location', 'destination_location'
    ]
    search_fields = ['video_file__number', 'video_file__filename', 'error_message']
    readonly_fields = [
        'video_file', 'operation_type', 'source_location', 'destination_location',
        'performed_by', 'performed_at', 'status', 'error_message', 'details'
    ]
    
    fieldsets = (
        (None, {
            'fields': (
                'video_file', 'operation_type', 'status',
                'source_location', 'destination_location'
            )
        }),
        (_('Execution'), {
            'fields': ('performed_by', 'performed_at')
        }),
        (_('Details'), {
            'fields': ('error_message', 'details'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Disable add permission."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Disable delete permission."""
        return False


# Add System Management as a proxy model like in planung
from .admin_commands import system_management_view
from django.http import HttpResponseRedirect
from django.urls import reverse


class SystemManagementProxy(VideoFile):
    """Proxy model to show System Management in admin menu."""
    
    class Meta:
        verbose_name = _('System Management')
        verbose_name_plural = _('System Management')
        proxy = True


@admin.register(SystemManagementProxy)
class SystemManagementProxyAdmin(admin.ModelAdmin):
    """Admin for System Management proxy model."""
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return request.user.is_staff
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def changelist_view(self, request, extra_context=None):
        """Redirect to System Management page."""
        url = reverse('admin:media_files_system_management')
        return HttpResponseRedirect(url)


@admin.register(MediaFilesConfig)
class MediaFilesConfigAdmin(admin.ModelAdmin):
    """Admin interface for MediaFilesConfig model."""
    
    def has_add_permission(self, request):
        """Only one config instance allowed."""
        return not MediaFilesConfig.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of config."""
        return False


def cover_generation_enabled():
    """Return True if cover generation is switched on in MediaFilesConfig."""
    try:
        return MediaFilesConfig.get_config().cover_enabled
    except Exception:
        return False


class CoverFeatureGateMixin:
    """Hide/disable a cover-related admin unless cover generation is enabled."""

    @staticmethod
    def _enabled(request):
        """Cache the feature flag on the request (several hooks call it)."""
        cached = getattr(request, '_cover_feature_enabled', None)
        if cached is None:
            cached = cover_generation_enabled()
            request._cover_feature_enabled = cached
        return cached

    def has_module_permission(self, request):
        """Hide from the admin index when the feature is off."""
        return self._enabled(request) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return self._enabled(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self._enabled(request) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return self._enabled(request) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._enabled(request) and super().has_delete_permission(request, obj)


@admin.register(CoverTemplate)
class CoverTemplateAdmin(CoverFeatureGateMixin, admin.ModelAdmin):
    """Admin interface for editor-configurable cover template rules."""

    list_display = ['priority', 'name', 'scope', 'match_pattern', 'template', 'is_active']
    list_display_links = ['name']
    list_editable = ['priority', 'is_active']
    list_filter = ['scope', 'template', 'is_active']
    search_fields = ['name', 'match_pattern']
    ordering = ['priority', 'id']


class CoverRegionWidget(forms.Textarea):
    """JSON widget augmented with a visual drag/resize text-area picker."""

    class Media:
        js = ['media_files/cover_region_picker.js']
        css = {'all': ['media_files/cover_region_picker.css']}

    def render(self, name, value, attrs=None, renderer=None):
        """Wrap the JSON textarea in a picker container holding the image URL."""
        base = super().render(name, value, attrs, renderer)
        image_url = self.attrs.get('data-image-url', '')
        return format_html(
            '<div class="cover-region-picker" data-image-url="{}" '
            'data-native-w="1280" data-native-h="720">{}</div>',
            image_url, base)


class CoverOverlayForm(forms.ModelForm):
    """Form wiring the visual picker and passing the saved image URL to it."""

    class Meta:
        model = CoverOverlay
        fields = '__all__'
        widgets = {
            'text_area': CoverRegionWidget(),
            'logo_area': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        """Expose the uploaded image URL to the picker widget."""
        super().__init__(*args, **kwargs)
        instance = getattr(self, 'instance', None)
        if instance and instance.pk and instance.image:
            self.fields['text_area'].widget.attrs['data-image-url'] = reverse(
                'admin:media_files_coveroverlay_image',
                args=[instance.pk])


@admin.register(CoverOverlay)
class CoverOverlayAdmin(CoverFeatureGateMixin, admin.ModelAdmin):
    """Admin for uploadable graphic overlays (PNG/SVG) grouped into pools."""

    form = CoverOverlayForm
    list_display = [
        'name', 'pool', 'preview', 'use_video_frame', 'draw_title',
        'draw_logo', 'is_active']
    list_display_links = ['name']
    list_editable = ['is_active']
    list_filter = ['pool', 'is_active', 'use_video_frame', 'draw_title']
    search_fields = ['name', 'pool']
    readonly_fields = ['preview']

    def get_urls(self):
        """Add an admin-protected image endpoint for files outside MEDIA_ROOT."""
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:object_id>/image/',
                self.admin_site.admin_view(self.image_view),
                name='media_files_coveroverlay_image',
            ),
        ]
        return custom_urls + urls

    def image_view(self, request, object_id):
        """Stream the uploaded overlay file from disk for admin previews."""
        import mimetypes
        import os

        from django.http import FileResponse, Http404

        try:
            obj = self.get_queryset(request).get(pk=object_id)
        except CoverOverlay.DoesNotExist:
            raise Http404
        if not self.has_view_permission(request, obj) or not obj.image:
            raise Http404
        try:
            image_path = obj.image.path
        except (NotImplementedError, ValueError):
            raise Http404
        if not os.path.isfile(image_path):
            raise Http404
        content_type = mimetypes.guess_type(image_path)[0] or 'application/octet-stream'
        return FileResponse(open(image_path, 'rb'), content_type=content_type)

    @admin.display(description=_('Vorschau'))
    def preview(self, obj):
        """Small inline preview of the uploaded overlay."""
        if not obj.pk or not obj.image:
            return '-'
        image_url = reverse('admin:media_files_coveroverlay_image', args=[obj.pk])
        if obj.image and not obj.image.name.lower().endswith('.svg'):
            return format_html(
                '<img src="{}" style="height:60px;background:#ddd;border:1px solid #ccc"/>',
                image_url)
        return format_html('<a href="{}">SVG</a>', image_url)


@admin.register(CoverOverlayRule)
class CoverOverlayRuleAdmin(CoverFeatureGateMixin, admin.ModelAdmin):
    """Admin for pattern -> overlay-pool rules."""

    list_display = ['priority', 'name', 'scope', 'match_pattern', 'pool', 'selection_mode', 'is_active']
    list_display_links = ['name']
    list_editable = ['priority', 'is_active']
    list_filter = ['scope', 'selection_mode', 'is_active']
    search_fields = ['name', 'match_pattern', 'pool']
    ordering = ['priority', 'id']
    filter_horizontal = ['overlays']
