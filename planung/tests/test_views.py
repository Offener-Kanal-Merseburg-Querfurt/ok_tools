from datetime import timedelta
from django.test import override_settings
from django.urls import reverse
from licenses.models import License
from licenses.models import default_category
from planung.models import TagesPlan
from planung.services.playout_import_service import PlayoutImportResult
from planung.services.playout_import_service import PlayoutMissingMediaResult
from planung.services.playout_import_service import PlayoutScheduleResult
from unittest.mock import patch
import json
import pytest


@pytest.fixture
def staff_user(user):
    """Upgrade default user fixture to staff user for admin-protected endpoints."""
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.fixture
def license_obj(staff_user):
    """Create one license used by API tests."""
    profile = staff_user.profile
    profile.verified = True
    profile.save()
    return License.objects.create(
        profile=profile,
        category=default_category(),
        title="Planning API License",
        subtitle="",
        description="",
        duration=timedelta(minutes=20),
        further_persons="",
        suggested_date=None,
        repetitions_allowed=True,
        media_authority_exchange_allowed=True,
        youth_protection_necessary=False,
        store_in_ok_media_library=True,
    )


@pytest.mark.django_db
def test__planung__get_license_endpoint(client, staff_user, license_obj):
    """License endpoint returns metadata for known license number."""
    client.force_login(staff_user)
    response = client.get(f"/api/license/{license_obj.number}/")
    assert response.status_code == 200
    data = response.json()
    assert data["number"] == license_obj.number
    assert data["title"] == "Planning API License"


@pytest.mark.django_db
def test__planung__day_plan_crud_flow(client, staff_user, license_obj):
    """POST/GET/DELETE workflow works for day plan endpoint."""
    client.force_login(staff_user)

    payload = {
        "date": "2026-02-10",
        "items": [
            {
                "number": license_obj.number,
                "start": "18:00:00",
                "duration": 1200,
                "title": "Planning API License",
                "subtitle": "",
            }
        ],
        "draft": True,
        "comment": "API test",
    }
    post_resp = client.post(
        reverse("save_day_plan"),
        data=payload,
        content_type="application/json",
    )
    assert post_resp.status_code == 200
    assert TagesPlan.objects.filter(datum="2026-02-10").exists()

    get_resp = client.get("/api/day-plan/2026-02-10/")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["date"] == "2026-02-10"
    assert get_data["draft"] is True
    assert len(get_data["items"]) == 1

    del_resp = client.delete("/api/day-plan/2026-02-10/")
    assert del_resp.status_code == 204
    assert not TagesPlan.objects.filter(datum="2026-02-10").exists()


@pytest.mark.django_db
def test__planung__save_day_plan_validation_error(client, staff_user, license_obj):
    """Endpoint returns structured validation errors for invalid payload."""
    client.force_login(staff_user)
    payload = {
        "date": "2026-02-10",
        "items": [
            {"number": license_obj.number, "start": "18:00:00", "duration": 1200},
            {"number": license_obj.number + 1, "start": "18:10:00", "duration": 1200},
        ],
        "draft": True,
    }
    response = client.post(
        reverse("save_day_plan"),
        data=payload,
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]
    assert isinstance(body.get("errors"), list)
    assert len(body["errors"]) > 0


@pytest.mark.django_db
def test__planung__week_stats_endpoint(client, staff_user):
    """Week stats endpoint responds with aggregated week rows."""
    client.force_login(staff_user)
    response = client.get("/api/planning/week-stats/?start=2026-02-09&weeks=2")
    assert response.status_code == 200
    data = response.json()
    assert "weeks" in data
    assert len(data["weeks"]) == 2


@pytest.mark.django_db
def test__planung__calendar_weeks_view__injects_js_csrf_token(client, staff_user):
    """Calendar weeks admin view exposes a CSRF token for AJAX write actions."""
    client.force_login(staff_user)
    response = client.get("/admin/planung/tagesplan/calendar-weeks/")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "const PLANNING_CSRF_TOKEN = '" in content
    assert "const PLANNING_CSRF_TOKEN = 'NOTPROVIDED'" not in content


@pytest.mark.django_db
@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test__planung__plan_action__does_not_send_playout_automatically(client, staff_user, license_obj):
    """Planning a day no longer triggers outbound playout calls automatically."""
    client.force_login(staff_user)

    payload = {
        "date": "2026-02-10",
        "items": [
            {
                "number": license_obj.number,
                "start": "18:00:00",
                "duration": 1200,
                "title": "Planning API License",
                "subtitle": "",
            }
        ],
        "planned": True,
        "comment": "API test",
    }

    with patch("planung.views.send_playout_import") as mocked_import, patch(
        "planung.views.send_playout_schedule_service"
    ) as mocked_schedule:
        response = client.post(
            reverse("save_day_plan"),
            data=payload,
            content_type="application/json",
        )

    assert response.status_code == 200
    mocked_import.assert_not_called()
    mocked_schedule.assert_not_called()
    body = response.json()
    assert "playout_import" not in body
    assert "playout_schedule" not in body


@pytest.mark.django_db
def test__planung__playout_missing_media_endpoint(client, staff_user):
    """Endpoint proxies playout files that are missing metadata."""
    client.force_login(staff_user)
    import_result = PlayoutMissingMediaResult(
        configured=True,
        items=[{"id": 123, "filename": "clip01.mp4"}],
        total=1,
        page=1,
        page_size=100,
        error="",
    )

    with patch("planung.views.fetch_playout_missing_media", return_value=import_result) as mocked_fetch:
        response = client.get(reverse("planning_playout_missing"), {"page": "1", "page_size": "100"})

    assert response.status_code == 200
    mocked_fetch.assert_called_once_with(page=1, page_size=100)
    body = response.json()
    assert body["items"] == [{"id": 123, "filename": "clip01.mp4"}]
    assert body["total"] == 1
    assert body["configured"] is True


@pytest.mark.django_db
def test__planung__playout_metadata_endpoint(client, staff_user, license_obj):
    """Separate endpoint sends playout metadata for a planned day."""
    client.force_login(staff_user)
    TagesPlan.objects.create(
        datum="2026-02-10",
        json_plan={
            "items": [{"number": license_obj.number, "start": "18:00:00", "duration": 1200, "title": "Test"}],
            "draft": False,
            "planned": True,
        },
    )
    import_result = PlayoutImportResult(
        configured=True,
        sent=1,
        matched=1,
        unmatched=[],
        error="",
    )

    with patch("planung.views.send_playout_import", return_value=import_result) as mocked_import:
        response = client.post(
            reverse("planning_playout_metadata"),
            data=json.dumps({"date": "2026-02-10"}),
            content_type="application/json",
        )

    assert response.status_code == 200
    mocked_import.assert_called_once()
    body = response.json()
    assert body["configured"] is True
    assert body["sent"] == 1


@pytest.mark.django_db
def test__planung__playout_schedule_endpoint(client, staff_user, license_obj):
    """Separate endpoint sends playout schedule for a planned day."""
    client.force_login(staff_user)
    TagesPlan.objects.create(
        datum="2026-02-10",
        json_plan={
            "items": [{"number": license_obj.number, "start": "18:00:00", "duration": 1200, "title": "Test"}],
            "draft": False,
            "planned": True,
        },
    )
    schedule_result = PlayoutScheduleResult(
        configured=True,
        sent=1,
        created=1,
        unmatched=[],
        rejected=[],
        error="",
    )

    with patch("planung.views.send_playout_schedule_service", return_value=schedule_result) as mocked_schedule:
        response = client.post(
            reverse("planning_playout_schedule"),
            data=json.dumps({"date": "2026-02-10"}),
            content_type="application/json",
        )

    assert response.status_code == 200
    mocked_schedule.assert_called_once()
    body = response.json()
    assert body["configured"] is True
    assert body["created"] == 1


@pytest.mark.django_db
def test__planung__playout_payloads_carry_owner_sender(license_obj):
    """Schedule and metadata pushes send the sender from the owner's profile."""
    from datetime import date
    from media_files.models import StorageLocation
    from media_files.models import VideoFile
    from planung.services.playout_import_service import build_playout_import_items
    from planung.services.playout_import_service import build_playout_schedule_payload
    from registration.models import MediaAuthority

    profile = license_obj.profile
    profile.media_authority = MediaAuthority.objects.create(name="OK Dessau")
    profile.save()
    storage = StorageLocation.objects.create(
        name="Sender Playout", storage_type="PLAYOUT", path="/mnt/playout/",
    )
    VideoFile.objects.create(
        number=license_obj.number,
        filename="sender_clip.mp4",
        storage_location=storage,
        file_path="sender_clip.mp4",
        duration=timedelta(minutes=20),
    )
    plan_items = [{"number": license_obj.number, "start": "18:00:00", "duration": 1200}]

    schedule = build_playout_schedule_payload(date(2026, 2, 10), plan_items, draft=False, planned=True)
    metadata = build_playout_import_items(plan_items)

    assert schedule["items"][0]["sender"] == "OK Dessau"
    assert metadata[0]["sender"] == "OK Dessau"
