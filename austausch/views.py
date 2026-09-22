"""Views for Austausch module."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView
from django.db.models import Q
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

from .models import ExchangeConfig
from .models import ExchangeItem
from registration.models import OrganizationConfig


def check_austausch_enabled():
    """Check if Austausch module is enabled."""
    if not getattr(settings, 'AUSTAUSCH_ENABLED', False):
        raise ImproperlyConfigured(
            _('Austausch module is disabled. Set AUSTAUSCH_ENABLED=true to enable.')
        )


class ExchangeFeedView(UserPassesTestMixin, LoginRequiredMixin, ListView):
    """Display exchange items feed. Only accessible to staff members."""
    
    model = ExchangeItem
    template_name = 'austausch/feed_admin.html'  # Use admin template without sidebar
    context_object_name = 'exchange_items'
    paginate_by = 20
    
    def test_func(self):
        """Check if user is staff member."""
        return self.request.user.is_authenticated and self.request.user.is_staff
    
    def dispatch(self, request, *args, **kwargs):
        """Check if module is enabled before processing request."""
        check_austausch_enabled()
        return super().dispatch(request, *args, **kwargs)

    def _get_visible_video_queryset(self):
        exchange_config = ExchangeConfig.get_config()
        viewer_bundesland_code = OrganizationConfig.get_config().bundesland_code
        same_state_channels = exchange_config.get_same_state_channel_exceptions()
        same_state_filter = Q(
            bundesland_code__iexact=viewer_bundesland_code,
            allow_exchange=True,
        )
        for channel_name in same_state_channels:
            same_state_filter |= Q(
                channel__iexact=channel_name,
                allow_exchange=True,
            )

        return ExchangeItem.objects.filter(file_type='video').filter(
            Q(allow_exchange_other_states=True)
            | same_state_filter
        )

    def get_queryset(self):
        """Get filtered queryset based on request parameters."""
        qs = self._get_visible_video_queryset()
        
        # Filter by channel
        channel = self.request.GET.get('channel')
        if channel:
            qs = qs.filter(channel=channel)
        
        # Filter by date (items discovered after this date)
        date_from = self.request.GET.get('date_from')
        if date_from:
            try:
                from django.utils.dateparse import parse_datetime, parse_date
                # Try datetime first
                dt = parse_datetime(date_from)
                if dt:
                    qs = qs.filter(discovered_at__gte=dt)
                else:
                    # Try date
                    d = parse_date(date_from)
                    if d:
                        from django.utils import timezone
                        qs = qs.filter(discovered_at__date__gte=d)
            except (ValueError, TypeError):
                pass  # Invalid date format, ignore filter
        
        # Filter by status
        status = self.request.GET.get('status')
        if status in ['new', 'imported', 'failed']:
            qs = qs.filter(import_status=status)
        
        # Filter by OK-Tools managed
        oktools_only = self.request.GET.get('oktools_only')
        if oktools_only and oktools_only.lower() == 'true':
            qs = qs.filter(is_oktools_managed=True)
        
        # Filter by legacy
        legacy_only = self.request.GET.get('legacy_only')
        if legacy_only and legacy_only.lower() == 'true':
            qs = qs.filter(is_legacy=True)
        
        # Search by title/description/sender
        search = self.request.GET.get('search')
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search) |
                Q(filename__icontains=search) |
                Q(sendeverantwortung__icontains=search)
            )
        
        return qs.order_by('-discovered_at')
    
    def get_context_data(self, **kwargs):
        """Add additional context data."""
        context = super().get_context_data(**kwargs)
        
        # Get distinct channels for filter dropdown
        context['channels'] = ExchangeItem.objects.values_list(
            'channel', flat=True
        ).distinct().order_by('channel')
        
        # Get filter values from request
        context['current_channel'] = self.request.GET.get('channel', '')
        context['current_status'] = self.request.GET.get('status', '')
        context['current_date_from'] = self.request.GET.get('date_from', '')
        context['oktools_only'] = self.request.GET.get('oktools_only', '')
        context['legacy_only'] = self.request.GET.get('legacy_only', '')
        context['search'] = self.request.GET.get('search', '')
        
        # Statistics (only video items, matching the queryset filter)
        video_items = self._get_visible_video_queryset()
        context['total_items'] = video_items.count()
        context['new_items'] = video_items.filter(import_status='new').count()
        context['imported_items'] = video_items.filter(import_status='imported').count()
        context['failed_items'] = video_items.filter(import_status='failed').count()
        context['oktools_items'] = video_items.filter(is_oktools_managed=True).count()
        
        return context


# --- Export to server (step1, step2, result) ---

def _export_to_server_staff_required(view_func):
    """Decorator: staff required and 404 if AUSTAUSCH_ENABLED is False."""
    from django.contrib.admin.views.decorators import staff_member_required
    from django.http import HttpResponseNotFound

    @staff_member_required
    def wrapped(request, *args, **kwargs):
        if not getattr(settings, 'AUSTAUSCH_ENABLED', False):
            return HttpResponseNotFound()
        return view_func(request, *args, **kwargs)
    return wrapped


def _parse_license_numbers(text):
    """Parse comma- or newline-separated license numbers; return list of ints."""
    numbers = []
    for part in text.replace(',', '\n').split():
        part = part.strip()
        if not part:
            continue
        try:
            numbers.append(int(part))
        except ValueError:
            continue
    return numbers


def _license_has_pdf(license_obj, config):
    """Return True if license has PDF (signature or file in configured fallback paths)."""
    if hasattr(license_obj, 'has_any_signature') and license_obj.has_any_signature():
        return True
    if getattr(license_obj, 'signature', None) or getattr(license_obj, 'signature_svg', None) or getattr(license_obj, 'signature_points', None):
        return True
    from .services.export_to_server_service import _find_pdf_in_paths
    paths = [
        getattr(config, 'local_pdf_fallback_path', None) or '',
        getattr(config, 'local_pdf_fallback_path_2', None) or '',
    ]
    return _find_pdf_in_paths(license_obj.number, paths) is not None


def _cover_settings():
    """Return (enabled, output_dir) for cover generation; ('', '') if off."""
    try:
        from media_files.models import MediaFilesConfig
        if not MediaFilesConfig.get_config().cover_enabled:
            return False, ''
        from media_files.covers.config import get_cover_config
        return True, get_cover_config().output_dir
    except Exception:
        return False, ''


def _license_has_cover(number, cover_output_dir):
    """Return True if a canonical cover file exists for this license number."""
    from media_files.utils import has_cover

    return has_cover(number, cover_output_dir)


def _format_duration(td):
    """Format timedelta as H:MM:SS or M:SS."""
    if td is None:
        return ''
    total = int(td.total_seconds())
    if total < 0:
        return ''
    s = total % 60
    m = (total // 60) % 60
    h = total // 3600
    if h > 0:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


def _get_planung_license_numbers(date_from_str, date_to_str):
    """
    Return sorted unique license numbers from TagesPlan items in the given date range.
    date_from_str, date_to_str: YYYY-MM-DD. Returns list of ints.
    """
    from datetime import datetime
    from planung.models import TagesPlan

    if not date_from_str or not date_to_str:
        return []
    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return []
    plans = TagesPlan.objects.filter(
        datum__gte=date_from,
        datum__lte=date_to,
    )
    numbers = set()
    for plan in plans:
        for item in plan.json_plan.get('items', []):
            num = item.get('number')
            if num is not None:
                try:
                    numbers.add(int(num))
                except (ValueError, TypeError):
                    continue
    return sorted(numbers)


def _filter_planung_exclude_early_premiere(license_numbers, date_from_str, date_to_str):
    """
    Exclude only licenses that already had their premiere before the selected range (repeats).
    Include: licenses with no premiere yet (only planned) or premiere on/after date_from.
    license_numbers: list of int; date_from_str, date_to_str: YYYY-MM-DD. Returns list of ints.
    """
    from datetime import datetime
    from django.db.models import Min
    from django.utils import timezone
    from contributions.models import Contribution
    from licenses.models import License

    if not license_numbers or not date_from_str or not date_to_str:
        return list(license_numbers)
    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return list(license_numbers)
    date_from_dt = timezone.make_aware(datetime.combine(date_from, datetime.min.time()))
    licenses = License.objects.filter(number__in=license_numbers).values_list('id', 'number')
    license_id_by_number = {num: lid for lid, num in licenses}
    license_ids = list(license_id_by_number.values())
    if not license_ids:
        return []
    primary_dates = (
        Contribution.objects.filter(license_id__in=license_ids)
        .values('license_id')
        .annotate(min_date=Min('broadcast_date'))
    )
    # Exclude only if premiere exists and is before date_from (repeat)
    excluded = {
        row['license_id'] for row in primary_dates
        if row['min_date'] is not None and row['min_date'] < date_from_dt
    }
    license_id_to_number = {lid: num for num, lid in license_id_by_number.items()}
    return sorted(
        license_id_to_number[lid] for lid in license_ids
        if lid in license_id_to_number and lid not in excluded
    )


def _filter_license_numbers_by_authority_and_flags(license_numbers, config):
    """
    Keep only license numbers that:
    - belong to default_media_authority when it is set;
    - have at least one of: store_in_ok_media_library, media_authority_exchange_allowed,
      media_authority_exchange_allowed_other_states True.
    """
    from django.db.models import Q
    from licenses.models import License

    if not license_numbers:
        return []
    qs = License.objects.filter(number__in=license_numbers).filter(
        Q(store_in_ok_media_library=True)
        | Q(media_authority_exchange_allowed=True)
        | Q(media_authority_exchange_allowed_other_states=True)
    )
    default_ma_id = getattr(config, 'default_media_authority_id', None)
    if default_ma_id:
        qs = qs.filter(profile__media_authority_id=default_ma_id)
    return sorted(qs.values_list('number', flat=True).distinct())


def _split_license_numbers_by_authority_and_flags(license_numbers, config):
    """Split numbers into (kept, rejected) by media authority and exchange flags.

    Returning the rejected numbers as well lets the caller say *which* entries
    were dropped instead of only that nothing was left.
    """
    kept = _filter_license_numbers_by_authority_and_flags(license_numbers, config)
    kept_set = set(kept)
    rejected = [number for number in license_numbers if number not in kept_set]
    return kept, sorted(set(rejected))


def _format_license_number_list(license_numbers, limit=15):
    """Render a short, comma-separated preview of license numbers for messages."""
    numbers = list(license_numbers)
    preview = ', '.join(str(number) for number in numbers[:limit])
    if len(numbers) > limit:
        preview += ', …'
    return preview


def _get_already_exported_license_numbers() -> set[int]:
    """
    Return set of license numbers that were already successfully exported.
    Uses ExportedLicense table for unified tracking across all export modes.
    """
    from .models import ExportedLicense
    return set(
        ExportedLicense.objects.values_list('license_number', flat=True)
    )


def _export_step1_context(config):
    """Build context for step1 template: media authority from settings only."""
    default_media_authority_name = ''
    default_media_authority_id = getattr(config, 'default_media_authority_id', None)
    if getattr(config, 'default_media_authority', None):
        default_media_authority_name = config.default_media_authority.name
    return {
        'default_media_authority_id': default_media_authority_id,
        'default_media_authority_name': default_media_authority_name,
    }


@_export_to_server_staff_required
def export_to_server_step1(request):
    """Step 1: form to select mode (contributions/planung vs licenses) and filters or license numbers."""
    from django.shortcuts import redirect, render
    from django.urls import reverse
    from contributions.admin import get_export_to_server_contribution_ids

    from .models import ExchangeConfig

    config = ExchangeConfig.get_config()
    ctx = _export_step1_context(config)

    if request.method == 'POST':
        mode = (
            'license' if request.POST.get('mode_license')
            else 'planung' if request.POST.get('mode_planung')
            else 'contributions'
        )
        if mode == 'license':
            raw = request.POST.get('license_numbers', '')
            ids = _parse_license_numbers(raw)
            if not ids:
                ctx['error'] = _('Enter at least one license number.')
                return render(request, 'austausch/export_to_server_step1.html', ctx)
            ids, rejected = _split_license_numbers_by_authority_and_flags(ids, config)
            if not ids:
                ctx['error'] = _(
                    'None of the entered license numbers (%(numbers)s) may be exported: the Default '
                    'Media Authority (when set) and at least one of Exchange SA, Exchange outside '
                    'SA, or In OK-Mediathek are required.'
                ) % {'numbers': _format_license_number_list(rejected)}
                return render(request, 'austausch/export_to_server_step1.html', ctx)
            already = _get_already_exported_license_numbers()
            ids = [i for i in ids if i not in already]
            if not ids:
                ctx['error'] = _('All entered license numbers were already successfully exported.')
                return render(request, 'austausch/export_to_server_step1.html', ctx)
            request.session['export_to_server'] = {'mode': 'licenses', 'ids': ids}
            return redirect(reverse('austausch:export_to_server_step2'))
        if mode == 'planung':
            date_from = request.POST.get('planung_date_from')
            date_to = request.POST.get('planung_date_to')
            if not date_from or not date_to:
                ctx['error'] = _('Date from and Date to are required for Planung mode.')
                return render(request, 'austausch/export_to_server_step1.html', ctx)
            ids = _get_planung_license_numbers(date_from, date_to)
            if not ids:
                ctx['error'] = _(
                    'No license numbers found in Planung between %(date_from)s and %(date_to)s. '
                    'Check the date range, or enter the license numbers directly.'
                ) % {'date_from': date_from, 'date_to': date_to}
                return render(request, 'austausch/export_to_server_step1.html', ctx)
            ids = _filter_planung_exclude_early_premiere(ids, date_from, date_to)
            if not ids:
                ctx['error'] = _(
                    'No items to export: all licenses in Planung for this range are repeats '
                    '(premiere was before the selected date range).'
                )
                return render(request, 'austausch/export_to_server_step1.html', ctx)
            ids, rejected = _split_license_numbers_by_authority_and_flags(ids, config)
            if not ids:
                ctx['error'] = _(
                    'Planung found %(count)s license number(s) for this date range (%(numbers)s), '
                    'but none of them may be exported: the Default Media Authority (when set) and '
                    'at least one of Exchange SA, Exchange outside SA, or In OK-Mediathek are required.'
                ) % {
                    'count': len(rejected),
                    'numbers': _format_license_number_list(rejected),
                }
                return render(request, 'austausch/export_to_server_step1.html', ctx)
            already = _get_already_exported_license_numbers()
            exported_now = [i for i in ids if i in already]
            ids = [i for i in ids if i not in already]
            if not ids:
                ctx['error'] = _(
                    'All %(count)s license number(s) from Planung were already successfully '
                    'exported (%(numbers)s).'
                ) % {
                    'count': len(exported_now),
                    'numbers': _format_license_number_list(exported_now),
                }
                return render(request, 'austausch/export_to_server_step1.html', ctx)
            request.session['export_to_server'] = {'mode': 'licenses', 'ids': ids}
            return redirect(reverse('austausch:export_to_server_step2'))
        # Mode contributions: media_authority from config, has_video always true.
        # Backend always restricts to licenses with at least one of: store_in_ok_media_library,
        # media_authority_exchange_allowed, media_authority_exchange_allowed_other_states.
        params = {
            'date_from': request.POST.get('date_from'),
            'time_from': request.POST.get('time_from', '00:00'),
            'date_to': request.POST.get('date_to'),
            'time_to': request.POST.get('time_to', '23:59'),
            'media_authority': str(config.default_media_authority_id) if getattr(config, 'default_media_authority_id', None) else '',
            'global_producer': request.POST.get('global_producer', ''),
            'has_video': '1',
        }
        if not params['date_from'] or not params['date_to']:
            ctx['error'] = _('Date from and Date to are required for contributions mode.')
            return render(request, 'austausch/export_to_server_step1.html', ctx)
        ids = get_export_to_server_contribution_ids(params)
        if not ids:
            ctx['error'] = _('No contributions match the selected filters.')
            return render(request, 'austausch/export_to_server_step1.html', ctx)
        
        # Filter out contributions whose licenses were already exported
        already = _get_already_exported_license_numbers()
        if already:
            from contributions.models import Contribution
            # Get license numbers for these contributions
            contribs = Contribution.objects.filter(pk__in=ids).select_related('license')
            # Filter to only contributions with non-exported licenses
            ids = [c.pk for c in contribs if c.license and c.license.number not in already]
        
        if not ids:
            ctx['error'] = _('All matching contributions were already successfully exported.')
            return render(request, 'austausch/export_to_server_step1.html', ctx)
        request.session['export_to_server'] = {'mode': 'contributions', 'ids': ids}
        return redirect(reverse('austausch:export_to_server_step2'))

    return render(request, 'austausch/export_to_server_step1.html', ctx)


@_export_to_server_staff_required
def export_to_server_step2(request):
    """Step 2: list items with checkboxes; POST starts upload (immediate or scheduled)."""
    from django.shortcuts import redirect, render
    from django.urls import reverse
    from django.utils import timezone
    from django.contrib import messages
    from django.utils.safestring import mark_safe
    from contributions.models import Contribution
    from licenses.models import License
    from .tasks import export_to_server_task
    from .models import ExportToServerRun

    data = request.session.get('export_to_server')
    if not data:
        return redirect(reverse('austausch:export_to_server_step1'))

    mode = data.get('mode')
    ids = data.get('ids', [])
    if not ids:
        if 'export_to_server' in request.session:
            del request.session['export_to_server']
        return redirect(reverse('austausch:export_to_server_step1'))

    if request.method == 'POST':
        selected = request.POST.getlist('selected_ids')
        try:
            selected_ids = [int(x) for x in selected if x and str(x).strip().isdigit()]
        except (ValueError, AttributeError):
            selected_ids = []
        if not selected_ids:
            messages.warning(request, _('Select at least one item to export.'))
        else:
            schedule_at = request.POST.get('schedule_at')
            if schedule_at:
                try:
                    from datetime import datetime
                    raw_dt = datetime.fromisoformat(schedule_at.replace('Z', '+00:00'))
                    dt = raw_dt if timezone.is_aware(raw_dt) else timezone.make_aware(raw_dt)
                    if dt <= timezone.now():
                        dt = None
                except Exception:
                    dt = None
            else:
                dt = None

            if dt:
                result = export_to_server_task.apply_async(
                    args=[selected_ids, mode],
                    kwargs={'user_id': request.user.pk},
                    eta=dt,
                )
                request.session['export_task_id'] = result.id
                messages.success(request, _('Export to server has been scheduled.'))
            else:
                result = export_to_server_task.delay(selected_ids, mode, request.user.pk)
                request.session['export_task_id'] = result.id
            if 'export_to_server' in request.session:
                del request.session['export_to_server']
            messages.success(
                request,
                mark_safe(
                    _('Export to server has been started in the background. ')
                    + _('You can view the result when ready: ')
                    + f'<a href="{reverse("austausch:export_to_server_result")}">'
                    + _('View last export result') + '</a>'
                ),
            )
            return redirect(reverse('austausch:export_to_server_step1'))

    from .models import ExchangeConfig
    from .services.export_locks import locked_item_ids
    from contributions.models import ContributionManager

    config = ExchangeConfig.get_config()
    cover_enabled, cover_dir = _cover_settings()
    already_exported = _get_already_exported_license_numbers()
    # Items another export task is uploading right now: shown greyed out so
    # the user does not queue a second copy of the same file.
    running_items = locked_item_ids(mode)
    items = []
    if mode == 'contributions':
        qs = (
            Contribution.objects
            .filter(pk__in=ids)
            .select_related('license', 'license__profile')
            .order_by('-broadcast_date')
        )
        # Only show primary (premiere) contributions, same as Mediathek export
        primary_ids = ContributionManager().primary_contributions(list(qs))
        primary_ids_set = set(primary_ids)
        qs = [c for c in qs if c.pk in primary_ids_set]
        for c in qs:
            if c.license and c.license.number in already_exported:
                continue  # Skip already successfully exported
            lic = c.license
            video = lic.get_video_file() if hasattr(lic, 'get_video_file') else None
            if not video:
                continue  # Only show items with video; export skips no-video anyway
            profile = getattr(lic, 'profile', None)
            profile_display = str(profile).strip() if profile else ''
            video_url = reverse('admin:media_files_videofile_change', args=[video.id])
            broadcast_date_display = (
                timezone.localtime(c.broadcast_date).strftime('%d.%m.%Y %H:%M')
                if c.broadcast_date
                else ''
            )
            item_id = c.pk
            items.append({
                'item_id': item_id,
                'license_number': lic.number,
                'broadcast_date_display': broadcast_date_display,
                'title': lic.title or '',
                'profile_display': profile_display,
                'duration_display': _format_duration(getattr(lic, 'duration', None)),
                'exchange_saxony_anhalt': lic.media_authority_exchange_allowed,
                'exchange_outside_saxony_anhalt': lic.media_authority_exchange_allowed_other_states,
                'store_in_ok_media_library': lic.store_in_ok_media_library,
                'has_pdf': _license_has_pdf(lic, config),
                'has_cover': _license_has_cover(lic.number, cover_dir),
                'cover_url': (reverse('admin:licenses_license_cover_candidates', args=[lic.number]) if cover_enabled else None),
                'video_url': video_url,
                'running_task_id': running_items.get(str(item_id)),
            })
    else:
        qs = License.objects.filter(number__in=ids).select_related('profile').order_by('number')
        for lic in qs:
            if lic.number in already_exported:
                continue  # Skip already successfully exported
            video = lic.get_video_file() if hasattr(lic, 'get_video_file') else None
            if not video:
                continue  # Only show items with video; export skips no-video anyway
            profile = getattr(lic, 'profile', None)
            profile_display = str(profile).strip() if profile else ''
            video_url = reverse('admin:media_files_videofile_change', args=[video.id])
            item_id = lic.number
            items.append({
                'item_id': item_id,
                'license_number': lic.number,
                'broadcast_date_display': '',  # No contribution in License/Planung mode
                'title': lic.title or '',
                'profile_display': profile_display,
                'duration_display': _format_duration(getattr(lic, 'duration', None)),
                'exchange_saxony_anhalt': lic.media_authority_exchange_allowed,
                'exchange_outside_saxony_anhalt': lic.media_authority_exchange_allowed_other_states,
                'store_in_ok_media_library': lic.store_in_ok_media_library,
                'has_pdf': _license_has_pdf(lic, config),
                'has_cover': _license_has_cover(lic.number, cover_dir),
                'cover_url': (reverse('admin:licenses_license_cover_candidates', args=[lic.number]) if cover_enabled else None),
                'video_url': video_url,
                'running_task_id': running_items.get(str(item_id)),
            })

    if not items:
        if 'export_to_server' in request.session:
            del request.session['export_to_server']
        messages.info(
            request,
            _('No items to export: all selected were already successfully exported or have no video/PDF.'),
        )
        return redirect(reverse('austausch:export_to_server_step1'))

    return render(request, 'austausch/export_to_server_step2.html', {
        'mode': mode,
        'items': items,
        'all_ids': ids,
        'cover_enabled': cover_enabled,
    })


@_export_to_server_staff_required
def export_to_server_result(request):
    """Show the latest export-to-server run result (uploaded, failed, skipped no PDF)."""
    from django.shortcuts import render
    from .models import ExportToServerRun

    task_id = request.session.get('export_task_id')
    
    # Try to find the run that matches the current task_id
    # If not found (e.g., task_id cleared), fall back to latest run
    if task_id:
        try:
            # Use Python filtering to avoid JSONField lookup issues
            runs = ExportToServerRun.objects.order_by('-started_at')[:10]
            run = None
            for r in runs:
                if r.details and r.details.get('task_id') == task_id:
                    run = r
                    break
            
            # If not found by task_id, try latest run but still show progress
            if not run:
                run = ExportToServerRun.objects.order_by('-started_at').first()
        except Exception:
            # Fallback to latest run on any error
            run = ExportToServerRun.objects.order_by('-started_at').first()
    else:
        run = ExportToServerRun.objects.order_by('-started_at').first()
    
    if not run:
        return render(request, 'austausch/export_to_server_result.html', {'run': None, 'task_id': task_id})
    return render(request, 'austausch/export_to_server_result.html', {'run': run, 'task_id': task_id})
