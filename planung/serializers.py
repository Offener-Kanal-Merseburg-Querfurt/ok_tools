"""DRF serializers for playout integration API endpoints."""

from datetime import timedelta
from django.utils.dateparse import parse_datetime
from licenses.models import License
from planung.models import AirReport
from planung.models import IncomingWebhookLog
from rest_framework import serializers


def _author_name(license_obj: License) -> str:
    """Build author name from license profile."""
    profile = getattr(license_obj, "profile", None)
    if not profile:
        return ""
    first_name = getattr(profile, "first_name", "") or ""
    last_name = getattr(profile, "last_name", "") or ""
    return f"{first_name} {last_name}".strip()


def _sender_name(license_obj: License) -> str:
    """Return the broadcaster set in the license owner's profile."""
    profile = getattr(license_obj, "profile", None)
    media_authority = getattr(profile, "media_authority", None) if profile else None
    return getattr(media_authority, "name", "") or "" if media_authority else ""


def _duration_seconds(license_obj: License) -> int | None:
    """Return license duration in seconds."""
    duration = getattr(license_obj, "duration", None)
    if duration:
        return int(duration.total_seconds())
    return None


class MediaItemSerializer(serializers.Serializer):
    """Single media metadata item returned by GET /api/v1/media."""

    id = serializers.CharField(help_text="License number (as string)")
    filename = serializers.CharField(help_text="Video file filename")
    title = serializers.CharField(allow_blank=True, default="")
    author = serializers.CharField(allow_blank=True, default="")
    description = serializers.CharField(allow_blank=True, default="")
    year = serializers.IntegerField(allow_null=True, default=None)
    category = serializers.CharField(allow_blank=True, default="")
    age_rating = serializers.CharField(allow_blank=True, default="")
    sender = serializers.CharField(
        allow_blank=True,
        default="",
        help_text="Broadcaster (media authority) of the license owner",
    )


class MediaListResponseSerializer(serializers.Serializer):
    """Response wrapper for GET /api/v1/media."""

    items = MediaItemSerializer(many=True)


class ScheduleItemSerializer(serializers.Serializer):
    """Single schedule item returned by GET /api/v1/schedule."""

    id = serializers.CharField()
    start = serializers.CharField(help_text="ISO 8601 datetime string")
    duration_sec = serializers.IntegerField(min_value=0)
    media_filename = serializers.CharField(allow_blank=True, default="")


class ScheduleListResponseSerializer(serializers.Serializer):
    """Response wrapper for GET /api/v1/schedule."""

    items = ScheduleItemSerializer(many=True)


class AirReportItemSerializer(serializers.Serializer):
    """Single air report item in POST /api/v1/air-reports request body."""

    report_id = serializers.IntegerField(required=False, allow_null=True)
    event_id = serializers.CharField(required=False, allow_null=True, default="")
    media_id = serializers.CharField(required=False, allow_null=True, default="")
    scheduled_start = serializers.DateTimeField(required=False, allow_null=True)
    started_at = serializers.DateTimeField(required=False, allow_null=True)
    ended_at = serializers.DateTimeField(required=False, allow_null=True)
    used_fallback = serializers.BooleanField(required=False, default=False)


class AirReportRequestSerializer(serializers.Serializer):
    """Request body for POST /api/v1/air-reports."""

    reports = AirReportItemSerializer(many=True)


class IncomingWebhookSerializer(serializers.Serializer):
    """Request body for POST /api/integrations/incoming/{connector_id}."""

    direction = serializers.ChoiceField(
        choices=[
            AirReport.DIRECTION_INBOUND_MEDIA,
            AirReport.DIRECTION_INBOUND_SCHEDULE,
            AirReport.DIRECTION_OUTBOUND_AIR_REPORT,
        ],
    )
    items = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=True,
    )