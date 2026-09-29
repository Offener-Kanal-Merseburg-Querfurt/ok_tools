"""DRF API views for playout integration endpoints.

Endpoints served by OK Tools for an external playout adapter:

    GET  /api/v1/media          — pull media metadata (incremental + backfill)
    GET  /api/v1/schedule       — pull broadcast schedule for a date range
    POST /api/v1/air-reports    — push air reports from playout
    POST /api/integrations/incoming/<connector_id> — incoming webhook receiver
"""

from django.apps import apps
from django.utils.dateparse import parse_datetime
from django.utils.timezone import make_aware
from django.utils.translation import gettext_lazy as _
from licenses.models import License
from planung.authentication import PlayoutApiKeyAuthentication
from planung.models import AirReport
from planung.models import IncomingWebhookLog
from planung.models import PlanungConfig
from planung.models import TagesPlan
from planung.serializers import AirReportRequestSerializer
from planung.serializers import IncomingWebhookSerializer
from planung.serializers import MediaItemSerializer
from planung.serializers import ScheduleItemSerializer
from planung.serializers import _author_name
from planung.serializers import _duration_seconds
from planung.serializers import _sender_name
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
import hashlib
import hmac
import logging


logger = logging.getLogger(__name__)

_AGE_RATING_MAP = {
    "none": "",
    "from_12": "12+",
    "from_16": "16+",
    "from_18": "18+",
}


def _get_video_file_model():
    """Return the VideoFile model if media_files app is installed, else None."""
    try:
        return apps.get_model("media_files", "VideoFile")
    except LookupError:
        return None


def _media_item(vf, license_obj) -> dict:
    """Build one GET /api/v1/media item from a video file and its license."""
    cat_name = ""
    year = None
    age_rating = ""
    if license_obj:
        cat = getattr(license_obj, "category", None)
        cat_name = getattr(cat, "name", "") or ""
        created_at = getattr(license_obj, "created_at", None)
        year = created_at.year if created_at else None
        raw_rating = getattr(license_obj, "youth_protection_category", "") or ""
        age_rating = _AGE_RATING_MAP.get(raw_rating, "")
    return {
        "id": str(vf.number),
        "filename": vf.filename,
        "title": getattr(license_obj, "title", "") or "" if license_obj else "",
        "author": _author_name(license_obj) if license_obj else "",
        "description": getattr(license_obj, "description", "") or "" if license_obj else "",
        "year": year,
        "category": cat_name,
        "age_rating": age_rating,
        "sender": _sender_name(license_obj) if license_obj else "",
    }


class MediaListView(APIView):
    """GET /api/v1/media — Return media metadata for playout pull.

    Query params:
        updated_since  — ISO 8601 datetime, return only records modified after this
        filename       — Comma-separated filenames, return only matching records

    Response: {"items": [{id, filename, title, author, description, year,
    category, age_rating, sender}, ...]} — one item per filename.
    """

    authentication_classes = [PlayoutApiKeyAuthentication]
    permission_classes = []

    def get(self, request):
        """Handle GET /api/v1/media."""
        VideoFile = _get_video_file_model()
        if VideoFile is None:
            return Response({"items": []})

        updated_since = request.query_params.get("updated_since")
        filename_param = request.query_params.get("filename")

        qs = (
            VideoFile.objects
            .filter(is_available=True, is_preview=False)
            .select_related(
                "license",
                "license__profile__media_authority",
                "license__category",
            )
        )

        if updated_since:
            dt = parse_datetime(updated_since)
            if dt is None:
                raise ValidationError(
                    {"updated_since": _("Invalid ISO 8601 datetime format.")}
                )
            qs = qs.filter(updated_at__gte=dt)

        if filename_param:
            sep = request.query_params.get("filename_sep", ",")
            filenames = [f.strip() for f in filename_param.split(sep) if f.strip()]
            if filenames:
                qs = qs.filter(filename__in=filenames)

        qs = qs.order_by("number", "filename", "pk")[:2000]
        video_files = list(qs)

        # Only one copy of a file carries the OneToOne license link; copies in
        # other storages or versions share the number, so resolve by number.
        licenses_by_number = {
            lic.number: lic
            for lic in License.objects.filter(
                number__in={vf.number for vf in video_files}
            ).select_related("profile__media_authority", "category")
        }

        items_by_filename = {}
        for vf in video_files:
            license_obj = vf.license or licenses_by_number.get(vf.number)
            existing = items_by_filename.get(vf.filename)
            if existing is not None and (existing[1] is not None or license_obj is None):
                continue
            items_by_filename[vf.filename] = (vf, license_obj)

        items = [
            _media_item(vf, license_obj)
            for vf, license_obj in items_by_filename.values()
        ]

        serializer = MediaItemSerializer(items, many=True)
        return Response({"items": serializer.data})


class ScheduleListView(APIView):
    """GET /api/v1/schedule — Return broadcast schedule for playout pull.

    Query params:
        from — ISO 8601 date/datetime, start of range (inclusive)
        to   — ISO 8601 date/datetime, end of range (inclusive)

    Response: {"items": [{id, start, duration_sec, media_filename}, ...]}
    """

    authentication_classes = [PlayoutApiKeyAuthentication]
    permission_classes = []

    def get(self, request):
        """Handle GET /api/v1/schedule."""
        from_str = request.query_params.get("from")
        to_str = request.query_params.get("to")

        if not from_str or not to_str:
            raise ValidationError(
                {"detail": _("Both 'from' and 'to' query parameters are required.")}
            )

        dt_from = parse_datetime(from_str)
        dt_to = parse_datetime(to_str)
        if dt_from is None or dt_to is None:
            raise ValidationError(
                {"detail": _("Invalid ISO 8601 datetime format.")}
            )

        date_from = dt_from.date() if hasattr(dt_from, "date") else dt_from
        date_to = dt_to.date() if hasattr(dt_to, "date") else dt_to

        plans = TagesPlan.objects.filter(
            datum__gte=date_from,
            datum__lte=date_to,
        ).order_by("datum")

        VideoFile = _get_video_file_model()
        license_numbers = set()
        for plan in plans:
            for item in plan.json_plan.get("items", []):
                number = item.get("number")
                if number is not None:
                    license_numbers.add(number)

        licenses_by_number = {}
        video_files_by_number = {}
        if license_numbers:
            licenses = License.objects.filter(
                number__in=license_numbers
            ).select_related("profile", "category")
            licenses_by_number = {lic.number: lic for lic in licenses}

            if VideoFile is not None:
                vfs = VideoFile.objects.filter(
                    number__in=license_numbers,
                    is_available=True,
                    is_preview=False,
                ).select_related("storage_location")
                for vf in vfs:
                    existing = video_files_by_number.get(vf.number)
                    if existing and existing.is_manual_primary:
                        continue
                    if not existing or vf.is_manual_primary:
                        video_files_by_number[vf.number] = vf.filename

        items = []
        for plan in plans:
            plan_items = plan.json_plan.get("items", [])
            for position, plan_item in enumerate(plan_items, start=1):
                number = plan_item.get("number")
                start_time = plan_item.get("start", "")
                duration_val = plan_item.get("duration", 0)

                if isinstance(duration_val, (int, float)):
                    duration_sec = int(duration_val)
                else:
                    duration_sec = 0

                if number:
                    event_id = f"plan-{plan.pk}-pos-{position}"
                else:
                    event_id = f"plan-{plan.pk}-pos-{position}"

                start_iso = _build_start_iso(plan.datum, start_time)
                media_filename = video_files_by_number.get(number, "") if number else ""

                item = {
                    "id": event_id,
                    "start": start_iso,
                    "duration_sec": duration_sec,
                    "media_filename": media_filename,
                }
                items.append(item)

        serializer = ScheduleItemSerializer(items, many=True)
        return Response({"items": serializer.data})


class AirReportCreateView(APIView):
    """POST /api/v1/air-reports — Receive air reports from playout.

    Request body: {"reports": [{report_id, event_id, media_id,
                                 scheduled_start, started_at, ended_at,
                                 used_fallback}, ...]}
    Success: any 2xx status. All reports in the batch are marked as received.
    Error: entire batch is considered not sent and will be retried.
    """

    authentication_classes = [PlayoutApiKeyAuthentication]
    permission_classes = []

    def post(self, request):
        """Handle POST /api/v1/air-reports."""
        serializer = AirReportRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": _("Invalid request body."), "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reports_data = serializer.validated_data.get("reports", [])
        created_reports = []

        for report_item in reports_data:
            raw = dict(report_item)
            for key, value in list(raw.items()):
                if hasattr(value, "isoformat"):
                    raw[key] = value.isoformat()
            report = AirReport.objects.create(
                external_id=str(report_item.get("report_id") or ""),
                media_filename=report_item.get("media_filename", ""),
                scheduled_start=report_item.get("scheduled_start"),
                started_at=report_item.get("started_at"),
                ended_at=report_item.get("ended_at"),
                used_fallback=report_item.get("used_fallback", False),
                raw_payload=raw,
            )
            created_reports.append(report)

        logger.info(
            "Received %d air report(s) from playout.",
            len(created_reports),
        )

        return Response(
            {"status": "received", "count": len(created_reports)},
            status=status.HTTP_201_CREATED,
        )


class IncomingWebhookView(APIView):
    """POST /api/integrations/incoming/<connector_id> — Receive webhook notifications.

    If HMAC secret is configured, the X-Signature header is verified.

    The webhook does not process items inline — it logs the event and returns
    202 {"status": "received", "run_id": N}.  The actual pull is done on the
    next scheduled cycle.
    """

    authentication_classes = [PlayoutApiKeyAuthentication]
    permission_classes = []

    def post(self, request, connector_id):
        """Handle POST /api/integrations/incoming/<connector_id>."""
        config = PlanungConfig.get_config()
        if config.webhook_hmac_secret:
            signature = request.META.get("HTTP_X_SIGNATURE", "")
            if not _verify_hmac(request.body, config.webhook_hmac_secret, signature):
                return Response(
                    {"detail": _("Invalid HMAC signature.")},
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = IncomingWebhookSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": _("Invalid webhook payload."), "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        direction = serializer.validated_data["direction"]
        items = serializer.validated_data.get("items", [])

        webhook_log = IncomingWebhookLog.objects.create(
            connector_id=connector_id,
            direction=direction,
            payload=serializer.validated_data,
        )

        logger.info(
            "Incoming webhook: connector=%s direction=%s items=%d",
            connector_id,
            direction,
            len(items),
        )

        return Response(
            {
                "status": "received",
                "run_id": webhook_log.pk,
            },
            status=status.HTTP_202_ACCEPTED,
        )


def _build_start_iso(plan_date, start_time_str: str) -> str:
    """Build an ISO 8601 datetime string from a plan date and start time.

    ``start_time_str`` may be ``HH:MM`` or ``HH:MM:SS`` or an empty string.
    """
    if not start_time_str:
        return plan_date.isoformat()

    try:
        parts = start_time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0
        from datetime import datetime
        from datetime import timezone
        dt = datetime(plan_date.year, plan_date.month, plan_date.day, hour, minute, second, tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, IndexError):
        return plan_date.isoformat()


def _verify_hmac(body: bytes, secret: str, signature: str) -> bool:
    """Verify HMAC-SHA256 of ``body`` using ``secret`` against ``signature``."""
    if not secret or not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
