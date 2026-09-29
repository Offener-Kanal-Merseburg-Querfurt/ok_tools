"""Tests for playout integration API v1 endpoints."""

from datetime import date
from datetime import timedelta
from django.test import override_settings
from django.utils.timezone import now
from licenses.models import License
from licenses.models import default_category
from planung.models import AirReport
from planung.models import IncomingWebhookLog
from planung.models import PlanungConfig
from planung.models import TagesPlan
from rest_framework.authtoken.models import Token
import pytest


@pytest.fixture
def planung_config(db):
    config = PlanungConfig.get_config()
    config.playout_import_api_key = "test-api-key-12345"
    config.webhook_hmac_secret = "test-hmac-secret"
    config.save()
    return config


@pytest.fixture
def staff_user(user):
    """Upgrade default user fixture to staff user for token/API tests."""
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return user


@pytest.fixture
def api_client(client, planung_config):
    """Return a Django test client with the X-API-Key header pre-set."""
    client.defaults["HTTP_X_API_KEY"] = planung_config.playout_import_api_key
    return client


@pytest.fixture
def license_with_video(db, staff_user):
    """Create a license with a linked VideoFile."""
    from media_files.models import StorageLocation
    from media_files.models import VideoFile

    profile = staff_user.profile
    profile.verified = True
    profile.save()

    license_obj = License.objects.create(
        profile=profile,
        category=default_category(),
        title="Test Show — Episode 1",
        description="A test episode description",
        duration=timedelta(minutes=30),
        further_persons="",
        suggested_date=None,
        repetitions_allowed=True,
        media_authority_exchange_allowed=True,
        youth_protection_necessary=False,
        store_in_ok_media_library=True,
    )

    storage = StorageLocation.objects.create(
        name="Test Playout",
        storage_type="PLAYOUT",
        path="/mnt/playout/",
    )

    video = VideoFile.objects.create(
        number=license_obj.number,
        filename="test_show_ep01.mp4",
        storage_location=storage,
        file_path="test_show_ep01.mp4",
        duration=timedelta(minutes=30),
    )

    return license_obj, video


@pytest.fixture
def day_plan(db, license_with_video):
    lic, vf = license_with_video
    plan = TagesPlan.objects.create(
        datum=date(2026, 6, 1),
        json_plan={
            "items": [
                {"number": lic.number, "start": "20:00", "duration": 1800},
                {"number": lic.number, "start": "20:30", "duration": 1800},
            ],
            "draft": False,
            "planned": True,
        },
    )
    return plan


@pytest.mark.django_db
class TestMediaListView:
    def test_requires_api_key(self, client, planung_config):
        response = client.get("/api/v1/media")
        assert response.status_code == 401

    def test_invalid_api_key(self, client, planung_config):
        response = client.get("/api/v1/media", HTTP_X_API_KEY="wrong-key")
        assert response.status_code == 401

    def test_returns_empty_list_without_data(self, api_client):
        response = api_client.get("/api/v1/media")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_accepts_admin_token_as_x_api_key(self, client, staff_user, planung_config):
        planung_config.playout_import_api_key = ""
        planung_config.save(update_fields=["playout_import_api_key"])
        token = Token.objects.create(user=staff_user)

        response = client.get("/api/v1/media", HTTP_X_API_KEY=token.key)

        assert response.status_code == 200

    def test_accepts_admin_token_as_bearer_token(self, client, staff_user, planung_config):
        planung_config.playout_import_api_key = ""
        planung_config.save(update_fields=["playout_import_api_key"])
        token = Token.objects.create(user=staff_user)

        response = client.get(
            "/api/v1/media",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )

        assert response.status_code == 200

    def test_accepts_admin_token_auth_scheme(self, client, staff_user, planung_config):
        planung_config.playout_import_api_key = ""
        planung_config.save(update_fields=["playout_import_api_key"])
        token = Token.objects.create(user=staff_user)

        response = client.get(
            "/api/v1/media",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        assert response.status_code == 200

    @override_settings(MEDIA_FILES_ENABLED=True)
    def test_returns_media_items(self, api_client, license_with_video):
        lic, vf = license_with_video
        response = api_client.get("/api/v1/media")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) > 0
        item = data["items"][0]
        assert item["id"] == str(lic.number)
        assert item["filename"] == vf.filename
        assert item["title"] == lic.title
        assert "author" in item
        assert "description" in item
        assert item["year"] == lic.created_at.year
        assert item["category"] == lic.category.name
        assert item["age_rating"] == ""
        assert item["sender"] == lic.profile.media_authority.name

    @override_settings(MEDIA_FILES_ENABLED=True)
    def test_sender_is_owner_media_authority(self, api_client, license_with_video):
        from registration.models import MediaAuthority

        lic, vf = license_with_video
        dessau = MediaAuthority.objects.create(name="OK Dessau")
        lic.profile.media_authority = dessau
        lic.profile.save()
        response = api_client.get(f"/api/v1/media?filename={vf.filename}")
        assert response.json()["items"][0]["sender"] == "OK Dessau"

    @override_settings(MEDIA_FILES_ENABLED=True)
    def test_copy_in_other_storage_yields_one_filled_item(self, api_client, license_with_video):
        from media_files.models import StorageLocation
        from media_files.models import VideoFile

        lic, vf = license_with_video
        archive = StorageLocation.objects.create(
            name="Test Archive",
            storage_type="ARCHIVE",
            path="/mnt/archive/",
        )
        VideoFile.objects.create(
            number=lic.number,
            filename=vf.filename,
            storage_location=archive,
            file_path=vf.filename,
            duration=timedelta(minutes=30),
        )
        assert VideoFile.objects.filter(filename=vf.filename).count() == 2

        response = api_client.get(f"/api/v1/media?filename={vf.filename}")
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == str(lic.number)
        assert items[0]["title"] == lic.title

    @override_settings(MEDIA_FILES_ENABLED=True)
    def test_filter_by_updated_since(self, api_client, license_with_video):
        lic, vf = license_with_video
        future = (now() + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        response = api_client.get(f"/api/v1/media?updated_since={future}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 0

    @override_settings(MEDIA_FILES_ENABLED=True)
    def test_filter_by_filename(self, api_client, license_with_video):
        lic, vf = license_with_video
        response = api_client.get(f"/api/v1/media?filename={vf.filename}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 1
        assert data["items"][0]["filename"] == vf.filename

    @override_settings(MEDIA_FILES_ENABLED=True)
    def test_filter_by_filename_csv(self, api_client, license_with_video):
        lic, vf = license_with_video
        nonexist = "nonexistent_file.mp4"
        response = api_client.get(f"/api/v1/media?filename={vf.filename},{nonexist}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 1


@pytest.mark.django_db
class TestScheduleListView:
    def test_requires_api_key(self, client, planung_config):
        response = client.get("/api/v1/schedule")
        assert response.status_code == 401

    def test_requires_from_and_to(self, api_client):
        response = api_client.get("/api/v1/schedule")
        assert response.status_code == 400

    def test_requires_to_param(self, api_client):
        response = api_client.get("/api/v1/schedule?from=2026-06-01")
        assert response.status_code == 400

    @override_settings(MEDIA_FILES_ENABLED=True)
    def test_returns_schedule_items(self, api_client, day_plan, license_with_video):
        response = api_client.get(
            "/api/v1/schedule?from=2026-06-01&to=2026-06-01"
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) == 2  # two items in day_plan

    @override_settings(MEDIA_FILES_ENABLED=True)
    def test_schedule_item_fields(self, api_client, day_plan, license_with_video):
        response = api_client.get(
            "/api/v1/schedule?from=2026-06-01&to=2026-06-01"
        )
        data = response.json()
        item = data["items"][0]
        assert "id" in item
        assert "start" in item
        assert "duration_sec" in item
        assert "media_filename" in item


@pytest.mark.django_db
class TestAirReportCreateView:
    def test_requires_api_key(self, client, planung_config):
        response = client.post(
            "/api/v1/air-reports",
            data={"reports": []},
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_create_air_report(self, api_client):
        response = api_client.post(
            "/api/v1/air-reports",
            data={
                "reports": [
                    {
                        "report_id": 42,
                        "scheduled_start": "2026-05-30T20:00:00+00:00",
                        "started_at": "2026-05-30T20:00:01+00:00",
                        "ended_at": "2026-05-30T20:30:00+00:00",
                        "used_fallback": False,
                    }
                ]
            },
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "received"
        assert data["count"] == 1
        assert AirReport.objects.count() == 1

    def test_empty_reports_list(self, api_client):
        response = api_client.post(
            "/api/v1/air-reports",
            data={"reports": []},
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["count"] == 0

    def test_invalid_payload(self, api_client):
        response = api_client.post(
            "/api/v1/air-reports",
            data={"not_reports": []},
            content_type="application/json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestIncomingWebhookView:
    def test_requires_api_key(self, client, planung_config):
        response = client.post(
            "/api/integrations/incoming/test-connector",
            data={"direction": "inbound_media", "items": []},
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_webhook_without_hmac(self, api_client, planung_config):
        planung_config.webhook_hmac_secret = ""
        planung_config.save()

        response = api_client.post(
            "/api/integrations/incoming/test-connector",
            data={"direction": "inbound_media", "items": []},
            content_type="application/json",
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "received"
        assert "run_id" in data
        assert IncomingWebhookLog.objects.count() == 1

    def test_webhook_with_valid_hmac(self, api_client, planung_config):
        import hashlib
        import hmac as hmac_module

        body = b'{"direction":"inbound_media","items":[]}'
        sig = hmac_module.new(
            planung_config.webhook_hmac_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        response = api_client.post(
            "/api/integrations/incoming/test-connector",
            data=body.decode(),
            content_type="application/json",
            HTTP_X_SIGNATURE=sig,
        )
        assert response.status_code == 202

    def test_webhook_with_invalid_hmac(self, api_client, planung_config):
        response = api_client.post(
            "/api/integrations/incoming/test-connector",
            data='{"direction":"inbound_media","items":[]}',
            content_type="application/json",
            HTTP_X_SIGNATURE="invalid-signature",
        )
        assert response.status_code == 403

    def test_invalid_direction(self, api_client, planung_config):
        planung_config.webhook_hmac_secret = ""
        planung_config.save()

        response = api_client.post(
            "/api/integrations/incoming/test-connector",
            data={"direction": "invalid_direction", "items": []},
            content_type="application/json",
        )
        assert response.status_code == 400
