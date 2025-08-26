from .models import TagesPlan
from datetime import timedelta
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from licenses.models import License
import json
import logging


logger = logging.getLogger(__name__)


@staff_member_required
def get_license_by_number(request, number):
    """Return license details by license number."""
    try:
        license = License.objects.get(number=number)
    except License.DoesNotExist:
        raise Http404(_("License not found or not confirmed."))

    return JsonResponse(
        {
            "number": license.number,
            "title": license.title or "",
            "subtitle": license.subtitle or "",
            "duration_min": int(license.duration.total_seconds() // 60),
        }
    )


@require_POST
@staff_member_required
@csrf_exempt
def save_day_plan(request):
    """Save a day plan with the provided data."""
    try:
        data = json.loads(request.body)
        # This explicitly parses ISO date as server timezone, timezone-naive
        date = parse_date(data.get("date"))
        if not date:
            return JsonResponse({"error": "Invalid date"}, status=400)



        plan_data = {
            "items": data.get("items", []),
            "draft": data.get("draft", False),
            "planned": data.get("planned", False),
        }

        kommentar = data.get("comment", "")

        plan = TagesPlan.objects.filter(datum=date).first()
        if plan:
            old_items = plan.json_plan.get("items", [])
            old_draft = plan.json_plan.get("draft", False)
            old_comment = plan.kommentar or ""
            # If this is a draft plan and only the comment has changed
            if (
                old_draft
                and old_items == plan_data["items"]
                and old_draft == plan_data["draft"]
                and kommentar != old_comment
            ):
                plan.kommentar = kommentar
                plan.save(update_fields=["kommentar"])
                return JsonResponse({"status": "comment_updated", "created": False})
        plan, created = TagesPlan.objects.update_or_create(
            datum=date, defaults={"json_plan": plan_data, "kommentar": kommentar}
        )

        return JsonResponse({"status": "ok", "created": created})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def day_plan_detail(request, iso_date):
    """Retrieve or delete a day plan by ISO date.

    Handles GET and DELETE requests for a specific day plan.
    """
    # Parse ISO date string to date object - timezone-naive
    date_obj = parse_date(iso_date)
    if not date_obj:
        if request.method == "GET":
            raise Http404("Bad date format")
        return JsonResponse({"error": "Bad date format"}, status=400)

    if request.method == "GET":
        try:
            plan = TagesPlan.objects.get(datum=date_obj)

        except TagesPlan.DoesNotExist:
            raise Http404("No plan for this day")
        return JsonResponse(
            {
                "date": str(plan.datum),  # ✅ Возвращаем реальную дату из БД
                "items": plan.json_plan.get("items", []),
                "draft": plan.json_plan.get("draft", False),
                "planned": plan.json_plan.get("planned", False),
                "comment": plan.kommentar or "",
            }
        )
    elif request.method == "DELETE":
        try:
            plan = TagesPlan.objects.get(datum=date_obj)
            plan.delete()
            return JsonResponse({"status": "deleted"}, status=204)
        except TagesPlan.DoesNotExist:
            return JsonResponse({"error": "No plan for this day"}, status=404)
    else:
        return JsonResponse({"error": "Method not allowed"}, status=405)


def calendar_weeks_view(request):
    """Render the calendar weeks view.

    Implementation of the calendar_weeks_view.
    """
    return HttpResponseRedirect(reverse("admin:calendar_weeks_view"))
