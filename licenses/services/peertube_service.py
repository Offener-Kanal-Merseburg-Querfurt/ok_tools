from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
import logging
from typing import Any
from urllib.parse import quote
from urllib.parse import urljoin

import requests
from django.utils import timezone


logger = logging.getLogger('django')


DEFAULT_PEERTUBE_BASE_URL = 'https://lokalmedial.de'


@dataclass
class PeerTubeEndpointConfig:
    base_url: str
    channel_handle: str


def normalize_channel_handle(channel_handle: str | None) -> str:
    """Normalize PeerTube channel identifier to plain handle (name/slug)."""
    value = (channel_handle or '').strip()
    if value.startswith('@'):
        value = value[1:]
    return value.split('@', 1)[0].strip()


def parse_target_channel(target_channel: str | None) -> tuple[str | None, str | None]:
    """Parse @handle@domain and return (handle, domain)."""
    value = (target_channel or '').strip()
    if not value:
        return None, None

    if value.startswith('@'):
        value = value[1:]

    if '@' not in value:
        return None, None

    handle, domain = value.split('@', 1)
    handle = handle.strip()
    domain = domain.strip()
    if not handle or not domain:
        return None, None
    return handle, domain


def resolve_peertube_endpoint(*, target_channel: str | None, organization_channel: str | None) -> PeerTubeEndpointConfig:
    """Resolve PeerTube base URL and channel handle."""
    parsed_handle, parsed_domain = parse_target_channel(target_channel)

    org_handle = normalize_channel_handle(organization_channel)
    parsed_handle = normalize_channel_handle(parsed_handle)
    channel_handle = org_handle or parsed_handle
    if not channel_handle:
        raise ValueError('PeerTube channel handle is not configured')

    base_url = DEFAULT_PEERTUBE_BASE_URL
    if parsed_domain:
        base_url = f'https://{parsed_domain}'

    return PeerTubeEndpointConfig(base_url=base_url.rstrip('/'), channel_handle=channel_handle)


def peertube_get_json(base_url: str, path: str, params: dict | None = None, timeout: int = 15) -> dict:
    """GET JSON from PeerTube public API."""
    base_url = base_url.rstrip('/') + '/'
    url = urljoin(base_url, path.lstrip('/'))
    response = requests.get(
        url,
        params=params,
        headers={'Accept': 'application/json'},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        return payload
    raise ValueError('Unexpected PeerTube response payload')


def find_video_by_number_in_channel(
    base_url: str,
    channel_handle: str,
    video_number: str | int,
    *,
    page_size: int = 100,
    max_pages: int = 50,
) -> dict | None:
    """Find full PeerTube video object by pluginData.videoNumber in channel."""
    channel_handle = normalize_channel_handle(channel_handle)
    if not channel_handle:
        raise ValueError('PeerTube channel handle is empty')

    def _fetch_for_channel(channel_identifier: str) -> dict[str, Any] | None:
        start = 0
        video_number_str = str(video_number)

        for _ in range(max_pages):
            path = f'/api/v1/video-channels/{quote(channel_identifier, safe="")}/videos'
            data = peertube_get_json(
                base_url,
                path,
                params={'count': page_size, 'start': start, 'sort': '-publishedAt'},
            )

            items = data.get('data') or []
            if not items:
                return None

            for item in items:
                plugin_data = item.get('pluginData') or {}
                if str(plugin_data.get('videoNumber', '')) == video_number_str:
                    uuid = item.get('uuid')
                    if not uuid:
                        continue
                    return peertube_get_json(base_url, f'/api/v1/videos/{quote(uuid, safe="")}')

                uuid = item.get('uuid')
                if not uuid:
                    continue

                full = peertube_get_json(base_url, f'/api/v1/videos/{quote(uuid, safe="")}')
                full_plugin_data = full.get('pluginData') or {}
                if str(full_plugin_data.get('videoNumber', '')) == video_number_str:
                    return full

            if len(items) < page_size:
                return None
            start += page_size

        return None

    return _fetch_for_channel(channel_handle)


def peertube_watch_url(base_url: str, video: dict) -> str:
    """Build watch URL /w/{shortUUID|uuid}."""
    base_url = base_url.rstrip('/')
    video_id = video.get('shortUUID') or video.get('uuid')
    if not video_id:
        raise ValueError('No shortUUID/uuid in video data')
    return f'{base_url}/w/{video_id}'


PUBLISH_SOURCE_CONTRIBUTION = 'contribution'
PUBLISH_SOURCE_PLANUNG = 'planung'


def compute_publish_time_for_license(license_obj) -> datetime | None:
    """Resolve publish time using Contribution first, then planned TagesPlan entry."""
    found = compute_publish_times_for_licenses([license_obj.number])
    return found[license_obj.number][0] if license_obj.number in found else None


def compute_publish_times_for_licenses(
        license_numbers) -> dict[int, tuple[datetime, str]]:
    """Resolve publish times for many licenses at once.

    Same rules as :func:`compute_publish_time_for_license`: the first
    Contribution wins, otherwise the earliest planned (not draft) TagesPlan
    entry with a start time. One query for the contributions and one pass over
    the plans, however many licenses are asked for.

    Returns ``{number: (aware datetime, source)}`` with source
    ``'contribution'`` or ``'planung'``; licenses without any time are left out.
    """
    wanted = {int(n) for n in license_numbers if n is not None}
    result: dict[int, tuple[datetime, str]] = {}
    if not wanted:
        return result

    try:
        from contributions.models import Contribution
        from django.db.models import Min

        rows = (
            Contribution.objects
            .filter(license__number__in=wanted, broadcast_date__isnull=False)
            .values('license__number')
            .annotate(first_broadcast=Min('broadcast_date'))
        )
        for row in rows:
            result[row['license__number']] = (
                row['first_broadcast'], PUBLISH_SOURCE_CONTRIBUTION)
    except (ImportError, RuntimeError, ModuleNotFoundError):
        pass

    missing = wanted - result.keys()
    if not missing:
        return result

    try:
        from planung.models import TagesPlan

        plans = TagesPlan.objects.filter(datum__isnull=False).order_by('datum')
        for plan in plans.iterator():
            plan_json = plan.json_plan or {}
            if plan_json.get('draft') is True or plan_json.get('planned') is False:
                continue

            for item in plan_json.get('items', []):
                number = item.get('number')
                if number not in missing:
                    continue

                start_raw = (item.get('start') or '').strip()
                if not start_raw:
                    continue

                try:
                    parts = start_raw.split(':')
                    hour = int(parts[0])
                    minute = int(parts[1]) if len(parts) > 1 else 0
                    second = int(parts[2]) if len(parts) > 2 else 0
                    naive_dt = datetime.combine(
                        plan.datum,
                        datetime.min.time().replace(hour=hour, minute=minute, second=second),
                    )
                except (ValueError, TypeError, IndexError):
                    continue
                result[number] = (timezone.make_aware(naive_dt), PUBLISH_SOURCE_PLANUNG)
                missing.discard(number)
            if not missing:
                break
    except (ImportError, RuntimeError, ModuleNotFoundError):
        pass

    return result


def compute_lookup_eta(publish_time: datetime | None) -> datetime:
    """Compute first lookup ETA: publish_time + 5 minutes, else now."""
    if publish_time is None:
        return timezone.now()
    return publish_time + timedelta(minutes=5)
