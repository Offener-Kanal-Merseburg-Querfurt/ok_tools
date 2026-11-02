"""DRF API views for playout integration endpoints.

Endpoints served by OK Tools for an external playout adapter:

    GET  /api/v1/media          — pull media metadata (incremental + backfill)
    GET  /api/v1/schedule       — pull broadcast schedule for a date range
    POST /api/v1/air-reports    — push air reports from playout
    POST /api/integrations/incoming/<connector_id> — incoming webhook receiver
"""

from datetime import datetime
from datetime import time
from datetime import timedelta
from django.apps import apps
from django.db.models import Min
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from django.utils.timezone import get_current_timezone
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
from planung.services.playout_import_service import \
    build_playout_schedule_payload
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
import hashlib
import hmac
import logging


logger = logging.getLogger(__name__)

_AGE_RATING_MAP = {
    "from_12": "12+",
    "from_16": "16+",
    "from_18": "18+",
}


def _age_rating(license_obj):
    """Age rating for playout: "0+", "12+".."18+", or None if not rated.

    "Youth protection necessary" = No means checked without restrictions;
    unknown (or Yes without a category) means not rated yet.
    """
    necessary = getattr(license_obj, "youth_protection_necessary", None)
    if necessary is False:
        return "0+"
    if necessary:
        category = getattr(license_obj, "youth_protection_category", None)
        return _AGE_RATING_MAP.get(category)
    return None


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
    age_rating = None
    if license_obj:
        cat = getattr(license_obj, "category", None)
        cat_name = getattr(cat, "name", "") or ""
        created_at = getattr(license_obj, "created_at", None)
        year = created_at.year if created_at else None
        age_rating = _age_rating(license_obj)
    return {
        "id": str(vf.number) if vf else "",
        "filename": vf.filename if vf else None,
        "title": getattr(license_obj, "title", "") or "" if license_obj else "",
        "author": _author_name(license_obj) if license_obj else "",
        "description": getattr(license_obj, "description", "") or "" if license_obj else "",
        "year": year,
        "category": cat_name,
        "age_rating": age_rating,
        "sender": _sender_name(license_obj) if license_obj else "",
    }


MEDIA_PAGE_LIMIT_DEFAULT = 2000
MEDIA_PAGE_LIMIT_MAX = 5000


def _page_params(request) -> tuple[int, int]:
    """Return validated ``page`` and ``limit`` query params."""
    try:
        page = int(request.query_params.get("page") or 1)
        limit = int(request.query_params.get("limit") or MEDIA_PAGE_LIMIT_DEFAULT)
    except ValueError:
        raise ValidationError({"detail": _("page and limit must be integers.")})
    if page < 1 or limit < 1:
        raise ValidationError({"detail": _("page and limit must be positive.")})
    return page, min(limit, MEDIA_PAGE_LIMIT_MAX)


def _number_list(raw: str | None) -> list[int] | None:
    """Parse a comma-separated list of license numbers, None when absent."""
    if raw is None:
        return None
    numbers = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            numbers.append(int(part))
        except ValueError:
            raise ValidationError({"id": _("License numbers must be integers.")})
    return numbers


def _media_items_for_filenames(VideoFile, filenames: list[str]) -> list[dict]:
    """Build one media item per filename, keeping the order of ``filenames``."""
    if VideoFile is None or not filenames:
        return []
    video_files = list(
        VideoFile.objects.filter(
            is_available=True, is_preview=False, filename__in=filenames,
        )
        .select_related(
            "license",
            "license__profile__media_authority",
            "license__category",
        )
        .order_by("number", "filename", "pk")
    )

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

    return [
        _media_item(*items_by_filename[filename])
        for filename in filenames
        if filename in items_by_filename
    ]


def _license_only_item(license_obj: License) -> dict:
    """Build a media item for a license that has no file yet."""
    item = _media_item(None, license_obj)
    item["id"] = str(license_obj.number)
    return item


def _schedule_item(plan: TagesPlan, row: dict) -> dict:
    """Map one schedule push row to a GET /api/v1/schedule item."""
    position = row["position"]
    start_time = row.get("start") or ""
    duration_sec = int(row.get("duration_sec") or 0)
    start_dt = _plan_datetime(plan.datum, start_time)
    end_time = ""
    if start_dt is not None:
        end_time = (start_dt + timedelta(seconds=duration_sec)).strftime("%H:%M:%S")
    return {
        "id": f"plan-{plan.pk}-pos-{position}",
        "position": position,
        "date": plan.datum.isoformat(),
        "start": start_dt.isoformat() if start_dt else plan.datum.isoformat(),
        "start_time": start_time,
        "end_time": end_time,
        "duration_sec": duration_sec,
        "kind": row.get("kind", ""),
        "media_id": row.get("media_id"),
        "title": row.get("title", "") or "",
        "media_filename": row.get("filename") or None,
        "live_source_name": row.get("live_source_name") or None,
    }


class MediaListView(APIView):
    """GET /api/v1/media — Return media metadata for playout pull.

    Query params:
        updated_since  — ISO 8601 datetime, return only records whose file or
                         license was modified after this
        filename       — Comma-separated filenames, return only matching records
        id             — Comma-separated license numbers, return only matching
                         records; a license without a file comes back with
                         ``filename: null``
        page           — 1-based page number (default 1)
        limit          — items per page (default 2000, max 5000)

    Response: {"items": [{id, filename, title, author, description, year,
    category, age_rating, sender}, ...], "total", "page", "limit", "next"}
    — one item per filename, ordered by number and filename. ``next`` is the
    URL of the following page or null on the last one.
    """

    authentication_classes = [PlayoutApiKeyAuthentication]
    permission_classes = []

    def get(self, request):
        """Handle GET /api/v1/media."""
        page, limit = _page_params(request)
        VideoFile = _get_video_file_model()
        numbers = _number_list(request.query_params.get("id"))

        qs = (
            VideoFile.objects.filter(is_available=True, is_preview=False)
            if VideoFile is not None else None
        )

        updated_since = request.query_params.get("updated_since")
        if updated_since:
            dt = parse_datetime(updated_since)
            if dt is None:
                raise ValidationError(
                    {"updated_since": _("Invalid ISO 8601 datetime format.")}
                )
            if qs is not None:
                # Metadata lives on the license, so an edited license counts
                # as a change of all its files.
                changed_numbers = License.objects.filter(
                    updated_at__gte=dt,
                ).values("number")
                qs = qs.filter(
                    Q(updated_at__gte=dt) | Q(number__in=changed_numbers)
                )

        filename_param = request.query_params.get("filename")
        if filename_param and qs is not None:
            sep = request.query_params.get("filename_sep", ",")
            filenames = [f.strip() for f in filename_param.split(sep) if f.strip()]
            if filenames:
                qs = qs.filter(filename__in=filenames)

        if numbers is not None and qs is not None:
            qs = qs.filter(number__in=numbers)

        # Page over distinct filenames, not rows: copies of one file in other
        # storages must not be split across pages.
        filenames_page: list[str] = []
        total_files = 0
        if qs is not None:
            keys = (
                qs.values("filename")
                .annotate(first_number=Min("number"))
                .order_by("first_number", "filename")
            )
            total_files = keys.count()
            offset = (page - 1) * limit
            filenames_page = [
                row["filename"] for row in keys[offset:offset + limit]
            ]

        items = _media_items_for_filenames(VideoFile, filenames_page)

        # Licenses asked for by number that have no file at all.
        missing_licenses: list[License] = []
        if numbers:
            with_files = set()
            if VideoFile is not None:
                with_files = set(
                    VideoFile.objects.filter(
                        number__in=numbers, is_available=True, is_preview=False,
                    ).values_list("number", flat=True)
                )
            missing_licenses = list(
                License.objects.filter(number__in=numbers)
                .exclude(number__in=with_files)
                .select_related("profile__media_authority", "category")
                .order_by("number")
            )

        total = total_files + len(missing_licenses)
        if page * limit >= total_files:
            # License-only items follow the files, on the pages after them.
            start = max(0, (page - 1) * limit - total_files)
            room = limit - len(items)
            items += [
                _license_only_item(license_obj)
                for license_obj in missing_licenses[start:start + room]
            ]

        next_url = None
        if page * limit < total:
            params = request.query_params.copy()
            params["page"] = str(page + 1)
            params["limit"] = str(limit)
            next_url = request.build_absolute_uri(
                f"{request.path}?{params.urlencode()}"
            )

        serializer = MediaItemSerializer(items, many=True)
        return Response({
            "items": serializer.data,
            "total": total,
            "page": page,
            "limit": limit,
            "next": next_url,
        })


class ScheduleListView(APIView):
    """GET /api/v1/schedule — Return broadcast schedule for playout pull.

    Query params:
        from — ISO 8601 date/datetime, start of range (inclusive)
        to   — ISO 8601 date/datetime, end of range (inclusive)

    Response: {"items": [{id, position, date, start, start_time, end_time,
    duration_sec, kind, media_id, title, media_filename, live_source_name},
    ...]}. Rows are built like the schedule push to the playout, so ``kind``
    is ``video``, ``live`` or ``placeholder`` (Freistellung) and rows without
    a file carry ``media_filename: null``.
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

        plans = TagesPlan.objects.filter(
            datum__gte=dt_from.date(),
            datum__lte=dt_to.date(),
        ).order_by("datum")

        items = []
        for plan in plans:
            json_plan = plan.json_plan if isinstance(plan.json_plan, dict) else {}
            plan_items = [
                item for item in json_plan.get("items", []) if isinstance(item, dict)
            ]
            payload = build_playout_schedule_payload(
                plan.datum, plan_items, draft=False, planned=True,
            )
            for row in payload["items"]:
                items.append(_schedule_item(plan, row))

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


def _plan_datetime(plan_date, start_time_str: str) -> datetime | None:
    """Return the plan row start as an aware datetime in the local time zone.

    Plan times are local broadcast times; ``start_time_str`` may be
    ``HH:MM`` or ``HH:MM:SS``. Returns None when it cannot be parsed.
    """
    if not start_time_str:
        return None
    try:
        parts = start_time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0
        naive = datetime.combine(plan_date, time(0)) + timedelta(
            hours=hour, minutes=minute, seconds=second,
        )
    except (ValueError, IndexError):
        return None
    return make_aware(naive, get_current_timezone())


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
