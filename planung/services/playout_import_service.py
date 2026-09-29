"""Send planned media metadata and schedule to an external playout system."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from django.apps import apps
from licenses.models import License
from licenses.models import YouthProtectionCategory
from planung.models import PlanungConfig
from planung.serializers import _sender_name
from requests import RequestException
from typing import Any
import logging
import requests


logger = logging.getLogger(__name__)


YOUTH_PROTECTION_MAP = {
    YouthProtectionCategory.NONE: "0+",
    YouthProtectionCategory.FROM_12: "12",
    YouthProtectionCategory.FROM_16: "16",
    YouthProtectionCategory.FROM_18: "18",
}


@dataclass(frozen=True)
class PlayoutImportResult:
    configured: bool
    sent: int
    matched: int | None
    unmatched: list[str]
    error: str


@dataclass(frozen=True)
class PlayoutMissingMediaResult:
    configured: bool
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    error: str


@dataclass(frozen=True)
class PlayoutScheduleResult:
    configured: bool
    sent: int
    created: int | None
    unmatched: list[dict[str, str]]
    rejected: list[dict[str, str]]
    error: str
    placeholders_created: int | None = None


def _duration_seconds(video_file: Any, license_obj: License) -> float | None:
    """Return the best known duration in seconds."""
    video_duration = getattr(video_file, "duration", None)
    if video_duration:
        return video_duration.total_seconds()
    license_duration = getattr(license_obj, "duration", None)
    if license_duration:
        return license_duration.total_seconds()
    return None


def _resolution(video_file: Any) -> str:
    """Return video resolution as WIDTHxHEIGHT when available."""
    width = getattr(video_file, "width", None)
    height = getattr(video_file, "height", None)
    if width and height:
        return f"{width}x{height}"
    return ""


def _author_name(license_obj: License) -> str:
    """Build an author name from the license profile."""
    profile = getattr(license_obj, "profile", None)
    if not profile:
        return ""
    first_name = getattr(profile, "first_name", "") or ""
    last_name = getattr(profile, "last_name", "") or ""
    return f"{first_name} {last_name}".strip()


def _language_code() -> str:
    """Return the configured base language code for outbound metadata."""
    from django.conf import settings

    language = getattr(settings, "LANGUAGE_CODE", "") or ""
    return language.lower().split("-")[0]


def _production_year(license_obj: License) -> int | None:
    """Return the closest available year for playout metadata."""
    suggested_date = getattr(license_obj, "suggested_date", None)
    if suggested_date:
        return suggested_date.year
    created_at = getattr(license_obj, "created_at", None)
    if created_at:
        return created_at.year
    return None


def _tags(license_obj: License) -> list[str]:
    """Return cleaned license tags, capped to the public metadata limit."""
    tags = getattr(license_obj, "tags", None)
    if not isinstance(tags, list):
        return []
    return [str(tag).strip() for tag in tags if str(tag).strip()][:4]


def _build_item(license_obj: License, video_file: Any) -> dict[str, Any] | None:
    """Build one external playout payload item for a license."""
    filename = getattr(video_file, "filename", "")
    if not video_file or not filename:
        return None

    category = getattr(license_obj, "category", None)

    item: dict[str, Any] = {
        "filename": filename,
        "title": getattr(license_obj, "title", "") or "",
        "description": getattr(license_obj, "description", "") or "",
        "author": _author_name(license_obj),
        "sender": _sender_name(license_obj),
        "language": _language_code(),
        "category_name": getattr(category, "name", "") if category else "",
        "tags": _tags(license_obj),
        "filler_category": "none",
    }

    production_year = _production_year(license_obj)
    if production_year is not None:
        item["production_year"] = production_year
    duration_sec = _duration_seconds(video_file, license_obj)
    if duration_sec is not None:
        item["duration_sec"] = duration_sec
    video_codec = getattr(video_file, "video_codec", "")
    if video_codec:
        item["video_codec"] = video_codec
    audio_codec = getattr(video_file, "audio_codec", "")
    if audio_codec:
        item["audio_codec"] = audio_codec
    fps = getattr(video_file, "fps", None)
    if fps is not None:
        item["fps"] = fps
    resolution = _resolution(video_file)
    if resolution:
        item["resolution"] = resolution

    return item


def build_playout_import_items(plan_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build outbound playout metadata items from day-plan rows."""
    license_numbers = [item.get("number") for item in plan_items if item.get("number")]
    if not license_numbers:
        return []

    licenses = License.objects.filter(number__in=license_numbers).select_related(
        "category",
        "profile__media_authority",
    )
    licenses_by_number = {license_obj.number: license_obj for license_obj in licenses}

    video_files_by_number: dict[int, Any] = {}
    try:
        VideoFile = apps.get_model("media_files", "VideoFile")
        video_files = VideoFile.objects.filter(
            number__in=license_numbers, is_preview=False,
        ).select_related("storage_location")
        for video_file in video_files:
            existing = video_files_by_number.get(video_file.number)
            if existing and existing.is_manual_primary:
                continue
            if not existing or video_file.is_manual_primary:
                video_files_by_number[video_file.number] = video_file
    except (ImportError, LookupError):
        video_files_by_number = {}

    payload_items = []
    for plan_item in plan_items:
        license_obj = licenses_by_number.get(plan_item.get("number"))
        if not license_obj:
            continue
        payload_item = _build_item(license_obj, video_files_by_number.get(license_obj.number))
        if payload_item:
            payload_items.append(payload_item)
    return payload_items


def send_playout_import(plan_items: list[dict[str, Any]]) -> PlayoutImportResult:
    """Send planned media metadata to the configured playout import endpoint."""
    config = PlanungConfig.get_config()
    if not config.is_playout_import_configured():
        return PlayoutImportResult(
            configured=False,
            sent=0,
            matched=None,
            unmatched=[],
            error="",
        )

    url = config.playout_import_url
    api_key = config.playout_import_api_key
    timeout = config.playout_import_timeout
    payload_items = build_playout_import_items(plan_items)
    if not payload_items:
        return PlayoutImportResult(
            configured=True,
            sent=0,
            matched=0,
            unmatched=[],
            error="",
        )

    try:
        response = requests.post(
            url,
            json={"items": payload_items},
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except (RequestException, ValueError) as exc:
        logger.exception("Failed to send playout media metadata")
        return PlayoutImportResult(
            configured=True,
            sent=len(payload_items),
            matched=None,
            unmatched=[],
            error=str(exc),
        )

    unmatched = data.get("unmatched", [])
    if not isinstance(unmatched, list):
        unmatched = []

    return PlayoutImportResult(
        configured=True,
        sent=len(payload_items),
        matched=data.get("matched"),
        unmatched=unmatched,
        error="",
    )


def fetch_playout_missing_media(*, page: int = 1, page_size: int | None = None) -> PlayoutMissingMediaResult:
    """Fetch playout files that exist there but do not yet have metadata."""
    config = PlanungConfig.get_config()
    effective_page_size = page_size or config.playout_missing_page_size
    if not config.is_playout_missing_configured():
        return PlayoutMissingMediaResult(
            configured=False,
            items=[],
            total=0,
            page=page,
            page_size=effective_page_size,
            error="",
        )

    try:
        response = requests.get(
            config.get_playout_missing_url(),
            params={"page": page, "page_size": effective_page_size},
            headers={"X-API-Key": config.playout_import_api_key},
            timeout=config.playout_import_timeout,
        )
        response.raise_for_status()
        data = response.json()
    except (RequestException, ValueError) as exc:
        logger.exception("Failed to fetch playout files missing metadata")
        return PlayoutMissingMediaResult(
            configured=True,
            items=[],
            total=0,
            page=page,
            page_size=effective_page_size,
            error=str(exc),
        )

    items = data.get("items", [])
    if not isinstance(items, list):
        items = []

    return PlayoutMissingMediaResult(
        configured=True,
        items=items,
        total=int(data.get("total") or 0),
        page=int(data.get("page") or page),
        page_size=int(data.get("page_size") or effective_page_size),
        error="",
    )


def _youth_protection_label(license_obj: License) -> str:
    ypc = getattr(license_obj, "youth_protection_category", None) or ""
    return YOUTH_PROTECTION_MAP.get(ypc, "0+")


def _start_time(value: Any) -> str:
    """Return local schedule time as HH:MM:SS."""
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")
    text = str(value or "").strip()
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) == 2:
        return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:00"
    if len(parts) == 3:
        return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{parts[2].zfill(2)}"
    return text


def _duration_sec(value: Any) -> int:
    """Return schedule duration as integer seconds."""
    if isinstance(value, (int, float)):
        return int(value)
    if hasattr(value, "total_seconds"):
        return int(value.total_seconds())
    text = str(value or "").strip()
    if not text:
        return 0
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = [int(part) for part in parts]
            return hours * 3600 + minutes * 60 + seconds
        if len(parts) == 2:
            minutes, seconds = [int(part) for part in parts]
            return minutes * 60 + seconds
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _determine_kind(license_obj: License, has_video_file: bool, explicit_kind: Any = "") -> str:
    explicit = str(explicit_kind or "").strip().lower()
    if explicit in {"placeholder", "freistellung"}:
        return "placeholder"
    if getattr(license_obj, "is_live", False):
        return "live"
    if explicit == "live":
        return "live"
    if has_video_file:
        return "video"
    return "placeholder"


def _first_text(*values: Any) -> str:
    """Return the first non-empty text value."""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _add_plan_item_metadata(item: dict[str, Any], plan_item: dict[str, Any]) -> None:
    """Copy optional placeholder metadata from a stored plan row."""
    for source_key, target_key in (
        ("description", "description"),
        ("author", "author"),
        ("sender_responsible", "author"),
        ("category", "category"),
        ("category_name", "category"),
    ):
        if target_key in item:
            continue
        value = _first_text(plan_item.get(source_key))
        if value:
            item[target_key] = value

    language = _first_text(plan_item.get("language"))
    item["language"] = language or _language_code()

    youth_protection = _first_text(
        plan_item.get("youth_protection"),
        plan_item.get("age_rating"),
    )
    if youth_protection:
        item["youth_protection"] = youth_protection


def _placeholder_filename(plan_item: dict[str, Any]) -> str:
    """Return the expected placeholder file name from a plan row."""
    return _first_text(plan_item.get("placeholder_filename"), plan_item.get("filename"))


def build_playout_schedule_payload(
    plan_date: date,
    plan_items: list[dict[str, Any]],
    draft: bool,
    planned: bool,
) -> dict[str, Any]:
    """Build the outbound playout schedule payload from a day plan."""
    license_numbers = [item.get("number") for item in plan_items if item.get("number")]
    licenses_by_number: dict[int, License] = {}
    video_files_by_number: dict[int, Any] = {}

    if license_numbers:
        licenses = License.objects.filter(number__in=license_numbers).select_related(
            "category", "profile__media_authority",
        )
        licenses_by_number = {lic.number: lic for lic in licenses}
        try:
            VideoFile = apps.get_model("media_files", "VideoFile")
            video_files = VideoFile.objects.filter(
                number__in=license_numbers, is_preview=False,
            ).select_related("storage_location")
            for vf in video_files:
                existing = video_files_by_number.get(vf.number)
                if existing and existing.is_manual_primary:
                    continue
                if not existing or vf.is_manual_primary:
                    video_files_by_number[vf.number] = vf
        except (ImportError, LookupError):
            pass

    schedule_items: list[dict[str, Any]] = []
    for position, plan_item in enumerate(plan_items, start=1):
        number = plan_item.get("number")
        license_obj = licenses_by_number.get(number) if number else None
        video_file = video_files_by_number.get(number) if number else None

        if not license_obj:
            item = {
                "position": position,
                "start": _start_time(plan_item.get("start", "")),
                "duration_sec": _duration_sec(plan_item.get("duration", 0)),
                "kind": "placeholder",
                "title": plan_item.get("title", ""),
                "youth_protection": "0+",
            }
            filename = _placeholder_filename(plan_item)
            if filename:
                item["placeholder_filename"] = filename
            _add_plan_item_metadata(item, plan_item)
            schedule_items.append(item)
            continue

        kind = _determine_kind(license_obj, video_file is not None, plan_item.get("kind", ""))
        item: dict[str, Any] = {
            "position": position,
            "start": _start_time(plan_item.get("start", "")),
            "duration_sec": _duration_sec(plan_item.get("duration", 0)),
            "kind": kind,
            "title": getattr(license_obj, "title", "") or "",
            "youth_protection": _youth_protection_label(license_obj),
        }

        category = getattr(license_obj, "category", None)
        if category:
            item["category"] = str(getattr(category, "name", "") or "")

        if kind == "video" and video_file:
            item["filename"] = getattr(video_file, "filename", "")
        elif kind == "placeholder":
            placeholder_filename = _placeholder_filename(plan_item)
            if placeholder_filename:
                item["placeholder_filename"] = placeholder_filename
            is_screen_board = getattr(license_obj, "is_screen_board", False)
            if is_screen_board and "placeholder_filename" not in item:
                item["placeholder_filename"] = f"{number}_freistellung.mp4"

        if kind == "live":
            item["live_source_name"] = getattr(license_obj, "title", "") or ""

        subtitle = getattr(license_obj, "subtitle", "") or ""
        if subtitle:
            item["subtitle"] = subtitle

        description = getattr(license_obj, "description", "") or ""
        if description:
            item["description"] = description

        author = _author_name(license_obj)
        if author:
            item["author"] = author

        sender = _sender_name(license_obj)
        if sender:
            item["sender"] = sender

        tags = _tags(license_obj)
        if tags:
            item["tags"] = tags

        is_live = getattr(license_obj, "is_live", False)
        if is_live:
            item["is_live"] = True

        repetitions_allowed = getattr(license_obj, "repetitions_allowed", None)
        if repetitions_allowed is not None:
            item["repetitions_allowed"] = repetitions_allowed

        production_year = _production_year(license_obj)
        if production_year is not None:
            item["production_year"] = production_year

        item["language"] = _language_code()

        if video_file:
            duration_sec = _duration_seconds(video_file, license_obj)
            if duration_sec is not None:
                item["duration_sec"] = int(duration_sec)

            video_codec = getattr(video_file, "video_codec", "")
            if video_codec:
                item["video_codec"] = video_codec
            audio_codec = getattr(video_file, "audio_codec", "")
            if audio_codec:
                item["audio_codec"] = audio_codec
            fps = getattr(video_file, "fps", None)
            if fps is not None:
                item["fps"] = fps
            resolution = _resolution(video_file)
            if resolution:
                item["resolution"] = resolution

        schedule_items.append(item)

    payload: dict[str, Any] = {
        "date": plan_date.isoformat(),
        "block_id": None,
        "status": "planned" if planned else "draft",
        "items": schedule_items,
    }
    if not planned and draft:
        payload["status"] = "draft"

    return payload


def send_playout_schedule(
    plan_date: date,
    plan_items: list[dict[str, Any]],
    draft: bool,
    planned: bool,
) -> PlayoutScheduleResult:
    """Send the day's broadcast schedule to the configured playout schedule endpoint."""
    config = PlanungConfig.get_config()
    if not config.is_playout_schedule_configured():
        return PlayoutScheduleResult(
            configured=False,
            sent=0,
            created=None,
            unmatched=[],
            rejected=[],
            error="",
        )

    payload = build_playout_schedule_payload(plan_date, plan_items, draft, planned)
    if not payload.get("items"):
        return PlayoutScheduleResult(
            configured=True,
            sent=0,
            created=0,
            unmatched=[],
            rejected=[],
            error="",
        )

    try:
        response = requests.post(
            config.playout_schedule_url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": config.playout_import_api_key,
            },
            timeout=config.playout_import_timeout,
        )
        response.raise_for_status()
        data = response.json()
    except (RequestException, ValueError) as exc:
        logger.exception("Failed to send playout schedule")
        return PlayoutScheduleResult(
            configured=True,
            sent=len(payload["items"]),
            created=None,
            unmatched=[],
            rejected=[],
            error=str(exc),
        )

    def _str_list(raw: Any) -> list[dict[str, str]]:
        items = raw if isinstance(raw, list) else []
        return [i for i in items if isinstance(i, dict)]

    return PlayoutScheduleResult(
        configured=True,
        sent=len(payload["items"]),
        created=data.get("created"),
        unmatched=_str_list(data.get("unmatched")),
        rejected=_str_list(data.get("rejected")),
        error="",
        placeholders_created=data.get("placeholders_created"),
    )
