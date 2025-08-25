# planung/admin.py
from .models import CalendarWeeksProxy
from .models import TagesPlan
from datetime import date
from datetime import timedelta
from django.contrib import admin
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from licenses.models import License


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
        today = date.today()
        start = today - timedelta(weeks=3, days=today.weekday())
        days = [
            start + timedelta(days=i)
            for i in range(18 * 7)
        ]  # 18 weeks

        # 1. status-dictionary
        plans = {}
        # range is 83 days (0-based → 12*7 - 1)
        end_date = start + timedelta(days=len(days) - 1)
        for plan in TagesPlan.objects.filter(
            datum__range=(start, end_date)
        ):
            total = sum(
                item.get("duration", 0) for item in plan.json_plan.get("items", [])
            )
            plans[str(plan.datum)] = {
                "minutes": total,
                "draft": plan.json_plan.get("draft", False),
                "planned": plan.json_plan.get("planned", False),
                "comment": plan.kommentar or "",
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
                        "minutes": 0,
                        "draft": False,
                        "planned": False,
                        "comment": "",
                    },
                )

                if info.get("planned") and info.get("comment"):
                    cell_cls, icon = "bg-success text-white", "✔🗨️"
                elif info.get("planned"):
                    cell_cls, icon = "bg-success text-white", "✔"
                elif info["minutes"] >= 105 and not info["draft"] and info.get("comment"):
                    cell_cls, icon = "bg-success text-white", "✔🗨️"
                elif info["minutes"] >= 105 and not info["draft"]:
                    cell_cls, icon = "bg-success text-white", "✔"
                elif info["minutes"] >= 105 and info.get("comment"):
                    cell_cls, icon = "bg-info text-white", "📝🗨️"
                elif info["minutes"] >= 105:
                    cell_cls, icon = "bg-info text-white", "📝"
                elif info["minutes"] > 0 and info.get("comment"):
                    cell_cls, icon = "bg-warning", "🕒🗨️"
                elif info["minutes"] > 0:
                    cell_cls, icon = "bg-warning", "🕒"
                elif info.get("comment"):
                    cell_cls, icon = "bg-info", "🗨️"
                else:
                    cell_cls, icon = "", ""

                week_days.append(
                    {
                        "date": day,
                        "iso": iso,
                        "cls": cell_cls,
                        "icon": icon,
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
        }
        return TemplateResponse(request, "admin/planung/calendar_weeks.html", context)

    def is_draft(self, obj):
        """Return whether the plan is marked as draft.

        Used as a status column in the admin list view.
        """
        if obj.json_plan.get("draft", False):
            return format_html('<span style="color:#888;font-size:18px;">🕒</span>')
        else:
            return format_html('<span style="color:#0074D9;font-size:18px;">✅</span>')
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

        Shows start time, license title with link, and duration for each
        item.
        """
        items = obj.json_plan.get("items", [])
        if not items:
            return "-"

        rows = []
        for item in items:
            number = item.get("number")
            try:
                lic = License.objects.get(number=number)
                url = f"/admin/licenses/license/{lic.id}/change/"
                link = f'<a href="{url}">{number} – {lic.title}</a>'
            except License.DoesNotExist:
                link = f"{number} ({_('not found')})"

            rows.append(
                "<tr><td>{}</td><td>{}</td><td>{} {}</td></tr>".format(
                    item.get('start'),
                    link,
                    item.get('duration'),
                    _('min'),
                )
            )

        table = (
            "<table style='width:100%;border-collapse:collapse;'>"
            f"<tr><th style='border-bottom:1px solid #ccc;'>{_('Start')}</th>"
            f"<th style='border-bottom:1px solid #ccc;'>{_('License')}</th>"
            f"<th style='border-bottom:1px solid #ccc;'>{_('Duration')}</th></tr>"
            + "".join(rows)
            + "</table>"
        )
        return format_html(table)

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
