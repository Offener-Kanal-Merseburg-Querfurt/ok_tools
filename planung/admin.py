# planung/admin.py
from .models import CalendarWeeksProxy
from .models import PlanChangeLog
from .models import PlanTemplate
from .models import PlanungConfig
from .models import TagesPlan
from datetime import date
from datetime import timedelta
from django.contrib import admin
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from licenses.models import License
from planung.services.plan_service import enrich_plan_items


@admin.register(TagesPlan)
class TagesPlanAdmin(admin.ModelAdmin):
    """Admin interface for managing TagesPlan entries."""

    list_display = ("datum", "is_draft", "show_items", "kommentar_short")
    readonly_fields = ("preview_plan",)
    fields = ("datum", "preview_plan", "kommentar")

    def get_urls(self):
        """Define custom URLs for the TagesPlan admin.

        Adds a calendar-weeks URL for displaying the weekly calendar
        view.
        """
        urls = super().get_urls()
        custom = [
            path(
                "calendar-weeks/",
                self.admin_site.admin_view(self.calendar_weeks_view),
                name="calendar_weeks_view",
            )
        ]
        return custom + urls

    def calendar_weeks_view(self, request):
        """Display a calendar view with 18 weeks of planning data.

        Shows the status of each day with color coding and icons based
        on planned content.
        """
        version = cache.get("planung_cache_version", 1)
        start_param = request.GET.get("start")
        weeks = request.GET.get("weeks", "18")
        cache_key = f"planung_calendar_weeks_context:{version}:{start_param or 'default'}:{weeks}"
        cached = cache.get(cache_key)
        if cached:
            return TemplateResponse(request, "admin/planung/calendar_weeks.html", cached)

        # Parse broadcast block from organization config
        from registration import organization_config
        broadcast_start = organization_config.get_broadcast_start()
        broadcast_end = organization_config.get_broadcast_end()
        broadcast_start_parts = broadcast_start.split(":")
        broadcast_end_parts = broadcast_end.split(":")
        block_start_seconds = int(broadcast_start_parts[0]) * 3600 + int(broadcast_start_parts[1]) * 60
        block_end_seconds = int(broadcast_end_parts[0]) * 3600 + int(broadcast_end_parts[1]) * 60
        max_block_seconds = block_end_seconds - block_start_seconds
        
        today = date.today()
        start = parse_date(start_param) if start_param else None
        if not start:
            start = today - timedelta(weeks=3, days=today.weekday())
        # The grid labels its columns Mon–Sun, so it always starts on a Monday.
        start -= timedelta(days=start.weekday())

        try:
            weeks_count = max(1, min(int(weeks), 52))
        except (TypeError, ValueError):
            weeks_count = 18
        days = [
            start + timedelta(days=i)
            for i in range(weeks_count * 7)
        ]

        # 1. status-dictionary
        plans = {}
        # range is 83 days (0-based → 12*7 - 1)
        end_date = start + timedelta(days=len(days) - 1)
        author_cache = {}

        for plan in TagesPlan.objects.filter(
            datum__range=(start, end_date)
        ):
            items = plan.json_plan.get("items", [])
            enriched_items = enrich_plan_items(items)

            # Calculate total duration within the block only
            total = 0
            outside_block_count = 0
            for item in enriched_items:
                start_str = item.get("start", "")
                duration = item.get("duration", 0)
                if not start_str or not duration:
                    continue
                # Parse start time to seconds
                parts = start_str.split(":")
                start_h = int(parts[0]) if len(parts) > 0 else 0
                start_m = int(parts[1]) if len(parts) > 1 else 0
                start_s = int(parts[2]) if len(parts) > 2 else 0
                item_start_sec = start_h * 3600 + start_m * 60 + start_s
                item_end_sec = item_start_sec + duration

                # Check if item is completely outside block
                if item_end_sec <= block_start_seconds or item_start_sec >= block_end_seconds:
                    outside_block_count += 1
                    continue

                # Clamp to block boundaries
                clamped_start = max(item_start_sec, block_start_seconds)
                clamped_end = min(item_end_sec, block_end_seconds)
                if clamped_end > clamped_start:
                    total += clamped_end - clamped_start

            search_tokens = []
            for item in items:
                if item.get("number"):
                    search_tokens.append(str(item.get("number")))
                if item.get("title"):
                    search_tokens.append(str(item.get("title")))
                if item.get("subtitle"):
                    search_tokens.append(str(item.get("subtitle")))
                if item.get("sender_responsible"):
                    search_tokens.append(str(item.get("sender_responsible")))
                if item.get("author"):
                    search_tokens.append(str(item.get("author")))

                # Fallback: resolve author from License profile when day-plan item
                # does not carry sender_responsible/author fields.
                if not item.get("sender_responsible") and not item.get("author"):
                    number = item.get("number")
                    if number:
                        if number not in author_cache:
                            author_name = ""
                            try:
                                lic = License.objects.filter(number=number).select_related("profile").first()
                                if lic and lic.profile:
                                    author_name = f"{lic.profile.first_name or ''} {lic.profile.last_name or ''}".strip()
                            except Exception:
                                author_name = ""
                            author_cache[number] = author_name

                        if author_cache.get(number):
                            search_tokens.append(author_cache[number])
            if plan.kommentar:
                search_tokens.append(str(plan.kommentar))

            has_live = any(item.get("is_live") for item in enriched_items)

            plans[str(plan.datum)] = {
                "seconds": total,
                "draft": plan.json_plan.get("draft", False),
                "planned": plan.json_plan.get("planned", False),
                "comment": plan.kommentar or "",
                "search_text": " ".join(search_tokens).lower(),
                "has_live": has_live,
                "outside_block_count": outside_block_count,
            }

        # 2. forming weeks
        weeks = []
        for i in range(0, len(days), 7):  # ← use all days list
            week_days = []
            for day in days[i: i + 7]:
                iso = day.isoformat()
                info = plans.get(
                    iso,
                    {
                        "seconds": 0,
                        "draft": False,
                        "planned": False,
                        "comment": "",
                        "search_text": "",
                        "outside_block_count": 0,
                    },
                )

                remaining_seconds = max(max_block_seconds - info["seconds"], 0)
                remaining_minutes = (remaining_seconds + 59) // 60

                has_comment = bool(info.get("comment"))
                is_planned = bool(info.get("planned"))
                is_draft = bool(info["draft"])
                seconds = info["seconds"]
                outside_block_count = info.get("outside_block_count", 0)
                is_full = seconds >= max_block_seconds
                is_partial = 0 < seconds < max_block_seconds
                has_outside = outside_block_count > 0 and seconds == 0

                # Determine background colors
                if is_planned or (is_full and not is_draft):
                    cell_cls = "bg-success text-white"
                elif is_full:
                    cell_cls = "bg-info text-white"
                elif is_partial:
                    cell_cls = "bg-warning"
                elif has_outside:
                    cell_cls = "bg-outside"
                elif has_comment:
                    cell_cls = "bg-info"
                else:
                    cell_cls = ""

                # Determine icon flags (multiple can be shown simultaneously)
                show_check = is_planned or (is_full and not is_draft)
                show_pencil = is_full and is_draft and not is_planned
                show_clock = is_partial and not is_planned
                show_outside = outside_block_count > 0
                show_live = info.get("has_live", False)

                # Strict status mapping for frontend filtering
                if show_check:
                    data_status = "planned"
                elif show_pencil or show_clock:
                    data_status = "draft"
                elif show_outside:
                    data_status = "outside"
                elif has_comment:
                    data_status = "comment"
                else:
                    data_status = "empty"

                week_days.append(
                    {
                        "date": day,
                        "iso": iso,
                        "cls": cell_cls,
                        "data_status": data_status,
                        "search": info.get("search_text", ""),
                        "has_comment": has_comment,
                        "show_check": show_check,
                        "show_pencil": show_pencil,
                        "show_clock": show_clock,
                        "show_outside": show_outside,
                        "show_live": show_live,
                        "remaining_minutes": remaining_minutes if show_clock else 0,
                    }
                )

            weeks.append(
                {
                    "num": week_days[0]["date"].isocalendar()[1],
                    "days": week_days,
                }
            )

        weekday_names = [
            _("Mon"),
            _("Tue"),
            _("Wed"),
            _("Thu"),
            _("Fri"),
            _("Sat"),
            _("Sun"),
        ]

        context = {
            "title": _("Calendar Weeks – Broadcast Planning"),
            "weeks": weeks,
            "weekday_names": weekday_names,
            "current_week": today.isocalendar()[1],
            "broadcast_start": broadcast_start,
            "broadcast_end": broadcast_end,
            "calendar_start": start.isoformat(),
            "calendar_weeks": weeks_count,
            "show_api_docs": PlanungConfig.get_config().is_playout_api_configured(),
        }
        cache.set(cache_key, context, timeout=300)
        return TemplateResponse(request, "admin/planung/calendar_weeks.html", context)

    def is_draft(self, obj):
        """Return whether the plan is marked as draft.

        Used as a status column in the admin list view.
        """
        if obj.json_plan.get("draft", False):
            return mark_safe('<svg viewBox="0 0 24 24" fill="none" stroke="#888" stroke-width="2" width="18" height="18" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>')
        else:
            return mark_safe('<svg viewBox="0 0 24 24" fill="none" stroke="#0074D9" stroke-width="2.5" width="18" height="18" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>')
    is_draft.short_description = _("Draft?")

    def show_items(self, obj):
        """Return the count of planned items in this TagesPlan.

        Used as a column in the admin list view.
        """
        return len(obj.json_plan.get("items", []))

    show_items.short_description = _("Planned items")

    def kommentar_short(self, obj):
        """Return a shortened version of the comment for display in the admin list.

        Truncates to 50 characters with ellipsis if longer.
        """
        return (obj.kommentar[:50] + "...") if obj.kommentar else "-"

    kommentar_short.short_description = _("Comment")

    def preview_plan(self, obj):
        """Generate an HTML table preview of the planned items.

        Shows start time, license title with link, author, and duration for each
        item.
        """
        items = obj.json_plan.get("items", [])
        if not items:
            return "-"

        rows = []
        for item in items:
            number = item.get("number")
            author_name = item.get("author", "")
            
            try:
                lic = License.objects.get(number=number)
                url = f"/admin/licenses/license/{lic.id}/change/"
                link = format_html('<a href="{}">{} – {}</a>', url, number, lic.title)
                
                # Get author from license if not in item
                if not author_name and lic.profile:
                    author_name = f"{lic.profile.first_name or ''} {lic.profile.last_name or ''}".strip()
            except License.DoesNotExist:
                link = format_html('{} ({})', number, _('not found'))

            # Format duration as MM:SS
            duration_seconds = item.get('duration', 0)
            duration_mins = duration_seconds // 60
            duration_secs = duration_seconds % 60
            duration_formatted = f"{duration_mins}:{duration_secs:02d}"

            rows.append((
                item.get('start'),
                link,
                author_name or "-",
                duration_formatted,
            ))

        return format_html(
            "<table style='width:100%;border-collapse:collapse;'>"
            "<tr><th style='border-bottom:1px solid #ccc;'>{}</th>"
            "<th style='border-bottom:1px solid #ccc;'>{}</th>"
            "<th style='border-bottom:1px solid #ccc;'>{}</th>"
            "<th style='border-bottom:1px solid #ccc;'>{}</th></tr>"
            "{}</table>",
            _('Start'),
            _('License'),
            _('Author'),
            _('Duration'),
            format_html_join(
                '',
                '<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>',
                rows,
            ),
        )

    preview_plan.short_description = _("Planned items (preview)")


@admin.register(CalendarWeeksProxy)
class CalendarWeeksAdmin(admin.ModelAdmin):
    """Menu entry that redirects straight to /calendar-weeks/."""

    def has_add_permission(self, request):
        """Disable the "Add" button for the calendar weeks proxy model.

        Users should add plans through the calendar interface instead.
        """
        return False  # hide "Add" button

    def changelist_view(self, request, extra_context=None):
        """Redirect the changelist view to the calendar weeks view.

        This makes the menu item go directly to the calendar interface.
        """
        url = reverse("admin:calendar_weeks_view")
        return HttpResponseRedirect(url)


@admin.register(PlanTemplate)
class PlanTemplateAdmin(admin.ModelAdmin):
    """Admin for reusable day plan templates."""

    list_display = ("name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")
    fields = ("name", "description", "json_plan", "is_active", "created_at", "updated_at")


@admin.register(PlanungConfig)
class PlanungConfigAdmin(admin.ModelAdmin):
    """Admin interface for planning module configuration."""

    fieldsets = (
        (_('Playout Import'), {
            'fields': (
                'playout_import_url',
                'playout_import_api_key',
                'playout_import_timeout',
                'playout_missing_url',
                'playout_missing_sync_enabled',
                'playout_missing_sync_interval_minutes',
                'playout_missing_page_size',
            ),
            'description': _(
                'When configured, the Plan! action sends planned media metadata to '
                'the external playout import endpoint. The missing metadata settings '
                'can periodically query playout for files that still need metadata.'
            ),
        }),
        (_('Playout Schedule'), {
            'fields': (
                'playout_schedule_url',
            ),
            'description': _(
                'When configured, the Plan! action also sends the day\'s broadcast '
                'schedule (day, start times, item kinds, filenames) to the external '
                'playout schedule endpoint.'
            ),
        }),
        (_('Anchor Render'), {
            'fields': (
                'anchor_render_url',
                'anchor_render_api_key',
                'anchor_render_timeout',
                'anchor_contribution_duration_seconds',
                'anchor_output_filename_pattern',
                'anchor_output_playout_directory',
                'anchor_playout_path_prefix',
                'anchor_default_placeholder_video',
                'anchor_placeholder_rules',
            ),
            'description': _(
                'When configured, planned days can be sent to the external '
                'anchor renderer to create a programme preview video.'
            ),
        }),
    )

    def has_add_permission(self, request):
        """Only one config instance allowed."""
        return not PlanungConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of config."""
        return False


@admin.register(PlanChangeLog)
class PlanChangeLogAdmin(admin.ModelAdmin):
    """Read-only audit entries for day plan changes."""

    list_display = ("created_at", "plan_date", "action", "changed_by")
    list_filter = ("action", "created_at")
    search_fields = ("plan_date",)
    readonly_fields = ("plan_date", "action", "old_payload", "new_payload", "changed_by", "created_at")

    def has_add_permission(self, request):
        """Disable manual creation of log records."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable deleting audit records from admin."""
        return False
